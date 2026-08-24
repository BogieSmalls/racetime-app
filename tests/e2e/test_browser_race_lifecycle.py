"""Browser acceptance for the complete two-entrant race lifecycle."""

import unittest

from tests.e2e.fixtures import (
    IntegrationEndpoints,
    assert_recorded_leaderboard,
    chromium_page,
    complete_two_entrant_race,
    create_race,
    fixture_discord_account,
    join_with_fixture_discord,
)


class BrowserRaceLifecycleTests(unittest.TestCase):
    def test_two_entrants_finish_and_leaderboard_records(self):
        with chromium_page(IntegrationEndpoints.from_env()) as page:
            first = fixture_discord_account(
                page,
                subject="1001",
                display_name="Racer One",
            )
            room = create_race(page, first, goal="Beat the game")
            second = join_with_fixture_discord(
                page,
                room,
                subject="1002",
                display_name="Racer Two",
            )
            complete_two_entrant_race(page, room, first, second)
            assert_recorded_leaderboard(
                page,
                room,
                expected_names=("Racer One", "Racer Two"),
            )


if __name__ == "__main__":
    unittest.main()
