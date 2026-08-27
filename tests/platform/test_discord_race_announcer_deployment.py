from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]


class DiscordRaceAnnouncerDeploymentTests(unittest.TestCase):
    def test_production_compose_runs_the_announcer_with_persistent_state_and_no_ports(self):
        compose = yaml.safe_load(
            (ROOT / "deploy" / "compose.production.yml").read_text(encoding="utf-8")
        )
        service = compose["services"]["discord-announcer"]

        self.assertEqual(service["command"], ["discord-announcer"])
        self.assertEqual(
            service["depends_on"]["web"],
            {"condition": "service_healthy"},
        )
        self.assertEqual(
            service["healthcheck"]["test"],
            ["CMD", "/srv/racetime/.docker/healthcheck", "process"],
        )
        self.assertIn(
            "announcer-data:/srv/racetime/announcer",
            service["volumes"],
        )
        self.assertIn(
            "secret-data:/run/racetime-secrets:ro",
            service["volumes"],
        )
        self.assertEqual(
            service["networks"]["proxy"]["ipv4_address"],
            "172.30.0.4",
        )
        self.assertNotIn("ports", service)
        self.assertTrue(service["read_only"])
        self.assertEqual(service["restart"], "unless-stopped")
        self.assertEqual(
            compose["volumes"]["announcer-data"]["name"],
            "z1rr-racetime-${RACETIME_STATE_GENERATION:?choose qualification or production}-announcer",
        )

    def test_runtime_image_and_entrypoint_include_the_announcer_process(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        entrypoint = (ROOT / ".docker" / "start-production").read_text(encoding="utf-8")
        ci_environment = (ROOT / "deploy" / "env" / "ci.env").read_text(encoding="utf-8")
        production_settings = (
            ROOT / "project" / "settings" / "production.py"
        ).read_text(encoding="utf-8")

        self.assertIn("/srv/racetime/announcer", dockerfile)
        self.assertIn("discord-announcer)", entrypoint)
        self.assertIn("python -m racetime.discord_race_announcer", entrypoint)
        self.assertIn(
            "RACETIME_ANNOUNCER_CHANNEL_IDS=111111111111111111,222222222222222222",
            ci_environment,
        )
        self.assertIn('"RACETIME_ANNOUNCER_CHANNEL_IDS"', production_settings)

    def test_deployment_starts_health_checks_and_restores_the_announcer(self):
        deploy = (ROOT / "deploy" / "scripts" / "deploy.sh").read_text(
            encoding="utf-8"
        )

        self.assertGreaterEqual(
            deploy.count(r'"${compose[@]}" up -d web racebot discord-announcer'),
            2,
        )
        self.assertIn(
            "for service in web racebot discord-announcer db redis",
            deploy,
        )
        self.assertIn(
            "--entrypoint test",
            deploy,
        )
        self.assertIn(
            "rm -sf discord-announcer",
            deploy,
        )


if __name__ == "__main__":
    unittest.main()
