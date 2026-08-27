from pathlib import Path
import tempfile
import unittest

from racetime.discord_race_announcer import ConfigurationError, load_config


class DiscordRaceAnnouncerRuntimeTests(unittest.TestCase):
    def test_loads_two_channel_destinations_and_bot_token_from_an_exact_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            token_file = root / "DISCORD_RACE_ANNOUNCER_BOT_TOKEN"
            token_file.write_text("existing-z1rracing-bot-token\n", encoding="utf-8")
            state_file = root / "state.json"

            config = load_config({
                "RT_SITE_URI": "https://raceroom.z1rracing.com",
                "RACETIME_ANNOUNCER_FEED_URL": "http://web:8000/z1rr/data",
                "RACETIME_ANNOUNCER_CHANNEL_IDS": (
                    "111111111111111111,222222222222222222"
                ),
                "RACETIME_ANNOUNCER_TOKEN_FILE": str(token_file),
                "RACETIME_ANNOUNCER_STATE_FILE": str(state_file),
                "RACETIME_ANNOUNCER_POLL_SECONDS": "10",
            })

            self.assertEqual(config.public_origin, "https://raceroom.z1rracing.com")
            self.assertEqual(config.feed_url, "http://web:8000/z1rr/data")
            self.assertEqual(
                config.channel_ids,
                ("111111111111111111", "222222222222222222"),
            )
            self.assertEqual(config.bot_token, "existing-z1rracing-bot-token")
            self.assertEqual(config.state_path, state_file)
            self.assertEqual(config.poll_seconds, 10)

    def test_rejects_invalid_or_duplicate_channel_destinations(self):
        with tempfile.TemporaryDirectory() as directory:
            token_file = Path(directory) / "token"
            token_file.write_text("token", encoding="utf-8")
            base = {
                "RT_SITE_URI": "https://raceroom.z1rracing.com",
                "RACETIME_ANNOUNCER_FEED_URL": "http://web:8000/z1rr/data",
                "RACETIME_ANNOUNCER_TOKEN_FILE": str(token_file),
                "RACETIME_ANNOUNCER_STATE_FILE": str(Path(directory) / "state.json"),
            }
            invalid_values = (
                "",
                "not-a-channel",
                "111111111111111111,111111111111111111",
            )
            for value in invalid_values:
                with self.subTest(value=value), self.assertRaises(ConfigurationError):
                    load_config({**base, "RACETIME_ANNOUNCER_CHANNEL_IDS": value})

    def test_rejects_noncanonical_public_origin_and_nonlocal_feed(self):
        with tempfile.TemporaryDirectory() as directory:
            token_file = Path(directory) / "token"
            token_file.write_text("token", encoding="utf-8")
            base = {
                "RT_SITE_URI": "https://raceroom.z1rracing.com",
                "RACETIME_ANNOUNCER_FEED_URL": "http://web:8000/z1rr/data",
                "RACETIME_ANNOUNCER_CHANNEL_IDS": "111111111111111111",
                "RACETIME_ANNOUNCER_TOKEN_FILE": str(token_file),
                "RACETIME_ANNOUNCER_STATE_FILE": str(Path(directory) / "state.json"),
            }
            invalid = (
                {"RT_SITE_URI": "https://racetime.z1rracing.com"},
                {"RT_SITE_URI": "http://raceroom.z1rracing.com"},
                {"RACETIME_ANNOUNCER_FEED_URL": "https://attacker.invalid/z1rr/data"},
                {"RACETIME_ANNOUNCER_FEED_URL": "http://web:8000/other/data"},
            )
            for changes in invalid:
                with self.subTest(changes=changes), self.assertRaises(ConfigurationError):
                    load_config({**base, **changes})


if __name__ == "__main__":
    unittest.main()
