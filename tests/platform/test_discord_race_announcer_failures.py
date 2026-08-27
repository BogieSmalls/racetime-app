import json
from pathlib import Path
import tempfile
import unittest

from racetime.discord_race_announcer import DiscordRaceAnnouncer, TransportError
from tests.platform.test_discord_race_announcer import (
    CHANNELS,
    FEED_ORIGIN,
    FakeTransport,
    ORIGIN,
)


class FailingChannelTransport(FakeTransport):
    def __init__(self):
        super().__init__()
        self.failing_channel = CHANNELS[0]

    def request_json(self, method, url, *, headers=None, payload=None, expected_statuses=(200,)):
        if method == "POST" and f"/channels/{self.failing_channel}/" in url:
            self.calls.append({
                "method": method,
                "url": url,
                "headers": headers or {},
                "payload": payload,
                "expected_statuses": expected_statuses,
            })
            raise TransportError("Discord request failed", status=503)
        return super().request_json(
            method,
            url,
            headers=headers,
            payload=payload,
            expected_statuses=expected_statuses,
        )


class DiscordRaceAnnouncerFailureTests(unittest.TestCase):
    def test_one_discord_destination_failure_does_not_block_the_other_and_retries(self):
        transport = FailingChannelTransport()
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            announcer = DiscordRaceAnnouncer(
                public_origin=ORIGIN,
                feed_url=f"{FEED_ORIGIN}/z1rr/data",
                category="z1rr",
                channel_ids=CHANNELS,
                bot_token="discord-bot-token",
                state_path=state_path,
                transport=transport,
            )

            announcer.sync_once()

            state = json.loads(state_path.read_text(encoding="utf-8"))
            messages = state["races"]["z1rr/season-five-opener"]["messages"]
            self.assertNotIn(CHANNELS[0], messages)
            self.assertEqual(messages[CHANNELS[1]], f"message-{CHANNELS[1]}")

            transport.failing_channel = None
            transport.calls.clear()
            announcer.sync_once()

            posts = [call for call in transport.calls if call["method"] == "POST"]
            self.assertEqual(
                [call["url"] for call in posts],
                [f"https://discord.com/api/v10/channels/{CHANNELS[0]}/messages"],
            )


if __name__ == "__main__":
    unittest.main()
