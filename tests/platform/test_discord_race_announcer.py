import json
from pathlib import Path
import tempfile
import unittest

from racetime.discord_race_announcer import DiscordRaceAnnouncer


ORIGIN = "https://raceroom.z1rracing.com"
FEED_ORIGIN = "http://web:8000"
CHANNELS = ("111111111111111111", "222222222222222222")


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.race_is_current = True
        self.race_version = 7

    def request_json(self, method, url, *, headers=None, payload=None, expected_statuses=(200,)):
        self.calls.append({
            "method": method,
            "url": url,
            "headers": headers or {},
            "payload": payload,
            "expected_statuses": expected_statuses,
        })
        if method == "GET" and url == f"{FEED_ORIGIN}/z1rr/data":
            return {
                "current_races": [{
                    "name": "z1rr/season-five-opener",
                    "url": "/z1rr/season-five-opener",
                    "data_url": "/z1rr/season-five-opener/data",
                }] if self.race_is_current else [],
            }
        if method == "GET" and url == f"{FEED_ORIGIN}/z1rr/season-five-opener/data":
            return race_detail(version=self.race_version)
        if method == "POST" and "/channels/" in url:
            channel_id = url.split("/channels/", 1)[1].split("/", 1)[0]
            return {"id": f"message-{channel_id}"}
        if method == "PATCH" and "/channels/" in url:
            return {"id": url.rsplit("/", 1)[1]}
        if method == "DELETE" and "/channels/" in url:
            return None
        raise AssertionError(f"unexpected request: {method} {url}")


def race_detail(*, version):
    return {
        "version": version,
        "name": "z1rr/season-five-opener",
        "url": "/z1rr/season-five-opener",
        "data_url": "/z1rr/season-five-opener/data",
        "status": {
            "value": "open",
            "verbose_value": "Open",
            "help_text": "The race is open for entrants.",
        },
        "category": {
            "name": "The Legend of Zelda Randomizer",
            "short_name": "Z1RR",
            "slug": "z1rr",
            "url": "/z1rr",
            "data_url": "/z1rr/data",
            "image": f"{ORIGIN}/media/z1rr.png",
        },
        "goal": {"name": "TTP Season 5", "custom": False},
        "entrants_count": 3,
        "entrants_count_inactive": 1,
        "opened_by": {
            "full_name": "Bogie#4670",
            "avatar": f"{ORIGIN}/media/bogie.png",
        },
    }


class DiscordRaceAnnouncerTests(unittest.TestCase):
    def make_announcer(self, state_path, transport):
        return DiscordRaceAnnouncer(
            public_origin=ORIGIN,
            feed_url=f"{FEED_ORIGIN}/z1rr/data",
            category="z1rr",
            channel_ids=CHANNELS,
            bot_token="discord-bot-token",
            state_path=state_path,
            transport=transport,
        )

    def test_posts_each_public_z1rr_race_to_every_configured_channel(self):
        transport = FakeTransport()
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            announcer = self.make_announcer(state_path, transport)

            announcer.sync_once()

            posts = [call for call in transport.calls if call["method"] == "POST"]
            self.assertEqual(len(posts), 2)
            self.assertEqual(
                {call["url"] for call in posts},
                {
                    f"https://discord.com/api/v10/channels/{channel_id}/messages"
                    for channel_id in CHANNELS
                },
            )
            for call in posts:
                self.assertEqual(call["headers"]["Authorization"], "Bot discord-bot-token")
                embed = call["payload"]["embeds"][0]
                self.assertEqual(embed["title"], "The Legend of Zelda Randomizer ~ TTP Season 5")
                self.assertEqual(embed["url"], f"{ORIGIN}/z1rr/season-five-opener")
                self.assertEqual(embed["color"], 0xE05000)
                self.assertEqual(embed["footer"]["text"], "Z1RR Raceroom")
                self.assertEqual(embed["fields"], [{
                    "name": "Entrants",
                    "value": "3 total, 1 inactive",
                    "inline": False,
                }])

            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["races"]["z1rr/season-five-opener"], {
                "version": 7,
                "messages": {
                    CHANNELS[0]: f"message-{CHANNELS[0]}",
                    CHANNELS[1]: f"message-{CHANNELS[1]}",
                },
            })
            self.assertNotIn("discord-bot-token", state_path.read_text(encoding="utf-8"))

            feed_calls = [call for call in transport.calls if call["method"] == "GET"]
            self.assertEqual(
                [call["url"] for call in feed_calls],
                [
                    f"{FEED_ORIGIN}/z1rr/data",
                    f"{FEED_ORIGIN}/z1rr/season-five-opener/data",
                ],
            )
            for call in feed_calls:
                self.assertEqual(call["headers"]["Host"], "raceroom.z1rracing.com")
                self.assertEqual(call["headers"]["X-Forwarded-Proto"], "https")

    def test_updates_existing_messages_only_when_the_public_race_version_changes(self):
        transport = FakeTransport()
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            announcer = self.make_announcer(state_path, transport)
            announcer.sync_once()
            transport.calls.clear()

            announcer.sync_once()

            self.assertFalse(any(
                call["method"] in {"POST", "PATCH", "DELETE"}
                for call in transport.calls
            ))

            transport.race_version = 8
            announcer.sync_once()

            patches = [call for call in transport.calls if call["method"] == "PATCH"]
            self.assertEqual(len(patches), 2)
            self.assertEqual(
                {call["url"] for call in patches},
                {
                    f"https://discord.com/api/v10/channels/{channel_id}/messages/message-{channel_id}"
                    for channel_id in CHANNELS
                },
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["races"]["z1rr/season-five-opener"]["version"], 8)

    def test_deletes_messages_when_a_race_leaves_the_public_category_feed(self):
        transport = FakeTransport()
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            announcer = self.make_announcer(state_path, transport)
            announcer.sync_once()
            transport.calls.clear()
            transport.race_is_current = False

            announcer.sync_once()

            deletes = [call for call in transport.calls if call["method"] == "DELETE"]
            self.assertEqual(len(deletes), 2)
            self.assertEqual(
                {call["url"] for call in deletes},
                {
                    f"https://discord.com/api/v10/channels/{channel_id}/messages/message-{channel_id}"
                    for channel_id in CHANNELS
                },
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["races"], {})


if __name__ == "__main__":
    unittest.main()
