"""Announce public Z1RR Raceroom races through an existing Discord bot."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import re
import sys
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests


DISCORD_API_ORIGIN = "https://discord.com/api/v10"
EXPECTED_PUBLIC_ORIGIN = "https://raceroom.z1rracing.com"
RACEROOM_ORANGE = 0xE05000
CHANNEL_ID = re.compile(r"^[0-9]{17,20}$")


class ConfigurationError(RuntimeError):
    pass


class TransportError(RuntimeError):
    def __init__(self, message, *, status=None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class AnnouncerConfig:
    public_origin: str
    feed_url: str
    channel_ids: tuple[str, ...]
    bot_token: str
    state_path: Path
    poll_seconds: int


def load_config(environment):
    public_origin = environment.get("RT_SITE_URI", "").rstrip("/")
    if public_origin != EXPECTED_PUBLIC_ORIGIN:
        raise ConfigurationError("RT_SITE_URI must be the canonical Raceroom origin")

    feed_url = environment.get(
        "RACETIME_ANNOUNCER_FEED_URL",
        "http://web:8000/z1rr/data",
    )
    feed = urlsplit(feed_url)
    if (
        feed.scheme != "http"
        or feed.hostname != "web"
        or feed.port != 8000
        or feed.path != "/z1rr/data"
        or feed.username
        or feed.password
        or feed.query
        or feed.fragment
    ):
        raise ConfigurationError("RACETIME_ANNOUNCER_FEED_URL is invalid")

    raw_channels = environment.get("RACETIME_ANNOUNCER_CHANNEL_IDS", "")
    channel_ids = tuple(value.strip() for value in raw_channels.split(",") if value.strip())
    if (
        not channel_ids
        or len(channel_ids) > 10
        or len(set(channel_ids)) != len(channel_ids)
        or any(not CHANNEL_ID.fullmatch(value) for value in channel_ids)
    ):
        raise ConfigurationError("RACETIME_ANNOUNCER_CHANNEL_IDS is invalid")

    token_path = Path(environment.get(
        "RACETIME_ANNOUNCER_TOKEN_FILE",
        "/run/racetime-secrets/DISCORD_RACE_ANNOUNCER_BOT_TOKEN",
    ))
    if not token_path.is_absolute() or not token_path.is_file():
        raise ConfigurationError("Discord race-announcer token file is unavailable")
    bot_token = token_path.read_text(encoding="utf-8").strip()
    if not bot_token or any(character.isspace() for character in bot_token):
        raise ConfigurationError("Discord race-announcer token is invalid")

    state_path = Path(environment.get(
        "RACETIME_ANNOUNCER_STATE_FILE",
        "/srv/racetime/announcer/state.json",
    ))
    if not state_path.is_absolute():
        raise ConfigurationError("RACETIME_ANNOUNCER_STATE_FILE must be absolute")

    try:
        poll_seconds = int(environment.get("RACETIME_ANNOUNCER_POLL_SECONDS", "10"))
    except ValueError as exc:
        raise ConfigurationError("RACETIME_ANNOUNCER_POLL_SECONDS is invalid") from exc
    if not 5 <= poll_seconds <= 300:
        raise ConfigurationError("RACETIME_ANNOUNCER_POLL_SECONDS is invalid")

    return AnnouncerConfig(
        public_origin=public_origin,
        feed_url=feed_url,
        channel_ids=channel_ids,
        bot_token=bot_token,
        state_path=state_path,
        poll_seconds=poll_seconds,
    )


class RequestsTransport:
    def __init__(self, session=None):
        self.session = session or requests.Session()

    def request_json(
        self,
        method,
        url,
        *,
        headers=None,
        payload=None,
        expected_statuses=(200,),
    ):
        try:
            response = self.session.request(
                method,
                url,
                headers=headers,
                json=payload,
                timeout=(3.05, 10),
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise TransportError("HTTP request failed") from exc
        if response.status_code not in expected_statuses:
            raise TransportError("HTTP request failed", status=response.status_code)
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            raise TransportError("HTTP response was not valid JSON", status=response.status_code) from exc


class DiscordRaceAnnouncer:
    def __init__(
        self,
        *,
        public_origin,
        feed_url,
        category,
        channel_ids,
        bot_token,
        state_path,
        transport,
        error_handler=None,
    ):
        self.public_origin = public_origin.rstrip("/")
        self.feed_url = feed_url
        self.feed_origin = self._origin(feed_url)
        self.category = category
        self.channel_ids = tuple(channel_ids)
        self.bot_token = bot_token
        self.state_path = Path(state_path)
        self.transport = transport
        self.error_handler = error_handler or (lambda error: None)

    def sync_once(self):
        state = self._load_state()
        category_data = self.transport.request_json(
            "GET",
            self.feed_url,
            headers=self._race_api_headers(),
        )
        current_names = set()
        for summary in category_data.get("current_races", []):
            race_name = summary.get("name")
            if not isinstance(race_name, str) or not race_name.startswith(f"{self.category}/"):
                continue
            detail_url = self._feed_api_url(summary.get("data_url"))
            race = self.transport.request_json(
                "GET",
                detail_url,
                headers=self._race_api_headers(),
            )
            if (
                race.get("name") != race_name
                or race.get("category", {}).get("slug") != self.category
            ):
                raise ValueError("Race API returned mismatched identity")
            current_names.add(race_name)
            previous = state["races"].get(race_name, {})
            previous_version = previous.get("version")
            messages = dict(previous.get("messages", {}))
            embed = self._embed(race)
            update_complete = True
            for channel_id in self.channel_ids:
                message_id = messages.get(channel_id)
                try:
                    if message_id and previous_version != race.get("version"):
                        self._edit_message(channel_id, message_id, embed)
                    elif not message_id:
                        messages[channel_id] = self._post_message(channel_id, embed)
                except TransportError as error:
                    update_complete = False
                    self.error_handler(error)
            stored_version = race.get("version")
            if previous_version is not None and not update_complete:
                stored_version = previous_version
            state["races"][race_name] = {
                "version": stored_version,
                "messages": messages,
            }

        for race_name in set(state["races"]) - current_names:
            remaining = {}
            for channel_id, message_id in state["races"][race_name]["messages"].items():
                try:
                    self._delete_message(channel_id, message_id)
                except TransportError as error:
                    remaining[channel_id] = message_id
                    self.error_handler(error)
            if remaining:
                state["races"][race_name]["messages"] = remaining
            else:
                del state["races"][race_name]
        self._save_state(state)
        return len(current_names)

    def _race_api_headers(self):
        return {
            "Host": urlsplit(self.public_origin).hostname,
            "X-Forwarded-Proto": "https",
            "User-Agent": "Z1RR-Raceroom-Race-Announcer/1.0",
        }

    def _discord_headers(self):
        return {
            "Authorization": f"Bot {self.bot_token}",
            "User-Agent": "Z1RR-Raceroom-Race-Announcer/1.0",
        }

    def _post_message(self, channel_id, embed):
        response = self.transport.request_json(
            "POST",
            f"{DISCORD_API_ORIGIN}/channels/{channel_id}/messages",
            headers=self._discord_headers(),
            payload={"embeds": [embed]},
            expected_statuses=(200, 201),
        )
        return response["id"]

    def _edit_message(self, channel_id, message_id, embed):
        self.transport.request_json(
            "PATCH",
            f"{DISCORD_API_ORIGIN}/channels/{channel_id}/messages/{message_id}",
            headers=self._discord_headers(),
            payload={"embeds": [embed]},
            expected_statuses=(200,),
        )

    def _delete_message(self, channel_id, message_id):
        self.transport.request_json(
            "DELETE",
            f"{DISCORD_API_ORIGIN}/channels/{channel_id}/messages/{message_id}",
            headers=self._discord_headers(),
            expected_statuses=(200, 204),
        )

    def _feed_api_url(self, value):
        public_url = self._same_origin_url(value)
        public = urlsplit(public_url)
        feed = urlsplit(self.feed_origin)
        return urlunsplit((feed.scheme, feed.netloc, public.path, public.query, ""))

    def _same_origin_url(self, value):
        if not isinstance(value, str):
            raise ValueError("Race API URL is missing")
        resolved = urljoin(f"{self.public_origin}/", value)
        if self._origin(resolved) != self.public_origin:
            raise ValueError("Race API URL belongs to another origin")
        return resolved

    @staticmethod
    def _origin(value):
        parsed = urlsplit(value)
        return urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")

    def _embed(self, race):
        category = race["category"]
        goal = race["goal"]
        status = race["status"]
        embed = {
            "color": RACEROOM_ORANGE,
            "title": f"{category['name']} ~ {goal['name']}",
            "url": self._same_origin_url(race["url"]),
            "description": status["help_text"],
            "fields": [{
                "name": "Entrants",
                "value": (
                    f"{race['entrants_count']} total, "
                    f"{race['entrants_count_inactive']} inactive"
                ),
                "inline": False,
            }],
            "footer": {"text": "Z1RR Raceroom"},
        }
        if category.get("image"):
            embed["thumbnail"] = {"url": self._same_origin_url(category["image"])}
        opened_by = race.get("opened_by")
        if opened_by:
            embed["author"] = {
                "name": f"Race room opened by {opened_by['full_name']}",
            }
            if opened_by.get("avatar"):
                embed["author"]["icon_url"] = self._same_origin_url(opened_by["avatar"])
        return embed

    def _load_state(self):
        if not self.state_path.exists():
            return {"version": 1, "races": {}}
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        if state.get("version") != 1 or not isinstance(state.get("races"), dict):
            raise ValueError("Race-announcer state is invalid")
        return state

    def _save_state(self, state):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.state_path)


def _report_destination_error(error):
    status = error.status if error.status is not None else "network"
    print(f"ANNOUNCER_DESTINATION=RETRY status={status}", file=sys.stderr, flush=True)


def run_forever(config, *, transport=None, sleep=time.sleep):
    announcer = DiscordRaceAnnouncer(
        public_origin=config.public_origin,
        feed_url=config.feed_url,
        category="z1rr",
        channel_ids=config.channel_ids,
        bot_token=config.bot_token,
        state_path=config.state_path,
        transport=transport or RequestsTransport(),
        error_handler=_report_destination_error,
    )
    while True:
        try:
            race_count = announcer.sync_once()
            print(f"ANNOUNCER_SYNC=PASS public_races={race_count}", flush=True)
        except TransportError as error:
            status = error.status if error.status is not None else "network"
            print(f"ANNOUNCER_SYNC=RETRY status={status}", file=sys.stderr, flush=True)
        sleep(config.poll_seconds)


def main():
    run_forever(load_config(os.environ))


if __name__ == "__main__":
    main()
