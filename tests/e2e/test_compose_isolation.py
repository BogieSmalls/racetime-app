"""Contracts that keep the local integration stack away from production."""

from pathlib import Path
import unittest

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_COMPOSE = REPOSITORY_ROOT / "deploy" / "compose.production.yml"
INTEGRATION_COMPOSE = REPOSITORY_ROOT / "deploy" / "compose.integration.yml"
INTEGRATION_ENV = REPOSITORY_ROOT / "deploy" / "env" / "integration.env.example"
INTEGRATION_UP = REPOSITORY_ROOT / "scripts" / "integration-up.ps1"


class ComposeIsolationTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(PRODUCTION_COMPOSE.is_file())
        self.assertTrue(
            INTEGRATION_COMPOSE.is_file(),
            "deploy/compose.integration.yml must define the isolated stack",
        )
        self.assertTrue(INTEGRATION_ENV.is_file())
        self.production = yaml.safe_load(PRODUCTION_COMPOSE.read_text(encoding="utf-8"))
        self.integration_text = INTEGRATION_COMPOSE.read_text(encoding="utf-8")
        self.integration = yaml.safe_load(self.integration_text)
        self.integration_env = INTEGRATION_ENV.read_text(encoding="utf-8")

    def test_project_network_volume_and_environment_names_are_disjoint(self):
        self.assertEqual(self.production["name"], "z1rr-racetime")
        self.assertEqual(self.integration["name"], "z1rr-racetime-integration")

        production_networks = set(self.production.get("networks", {}))
        integration_networks = set(self.integration.get("networks", {}))
        self.assertTrue(production_networks)
        self.assertTrue(integration_networks)
        for name, config in self.integration["networks"].items():
            self.assertEqual(config["name"], f"z1rr-racetime-integration-{name}")

        production_volume_names = {
            value.get("name")
            for value in self.production.get("volumes", {}).values()
            if isinstance(value, dict) and value.get("name")
        }
        integration_volume_names = {
            value.get("name")
            for value in self.integration.get("volumes", {}).values()
            if isinstance(value, dict) and value.get("name")
        }
        self.assertTrue(integration_volume_names)
        self.assertTrue(
            all(name.startswith("z1rr-racetime-integration-") for name in integration_volume_names)
        )
        self.assertTrue(production_volume_names.isdisjoint(integration_volume_names))

        for service in self.integration["services"].values():
            env_files = service.get("env_file", [])
            if isinstance(env_files, str):
                env_files = [env_files]
            self.assertNotIn(".env.production", " ".join(env_files).lower())
            self.assertNotIn("production.env", " ".join(env_files).lower())

        self.assertIn("/15", self.integration_env)
        self.assertNotIn("RACETIME_STATE_GENERATION", self.integration_env)
        self.assertNotIn("CADDY_STATE_VOLUME", self.integration_env)

    def test_only_the_exact_loopback_caddy_port_is_published(self):
        published = []
        for service in self.integration["services"].values():
            published.extend(service.get("ports", []))
        self.assertEqual(published, ["127.0.0.1:8443:8443"])

    def test_proxy_addresses_are_reserved_for_all_integration_members(self):
        services = self.integration["services"]
        addresses = {
            name: services[name]["networks"]["proxy"].get("ipv4_address")
            for name in ("caddy", "web", "fixture-provider")
        }
        self.assertEqual(addresses, {
            "caddy": "172.30.0.2",
            "web": "172.30.0.3",
            "fixture-provider": "172.30.0.4",
        })

    def test_racebot_healthcheck_allows_django_startup_on_small_hosts(self):
        healthcheck = self.integration["services"]["racebot"].get("healthcheck", {})
        self.assertEqual(
            healthcheck.get("test"),
            ["CMD", "/srv/racetime/.docker/healthcheck", "racebot"],
        )
        self.assertEqual(healthcheck.get("timeout"), "15s")
        self.assertEqual(healthcheck.get("start_period"), "40s")

    def test_rendered_source_contains_no_production_or_external_secret_path(self):
        combined = f"{self.integration_text}\n{self.integration_env}".lower()
        forbidden = (
            "raceroom.z1rracing.com",
            ".env.production",
            "discord.com/api/oauth2/token",
            "discord.com/api/users/@me",
            "hooks.slack.com",
            "discord.com/api/webhooks",
            "twitch.tv/oauth2",
        )
        for value in forbidden:
            self.assertNotIn(value, combined)

        self.assertIn("integration.racetime.test", combined)
        self.assertIn("fixture-discord-client", combined)
        self.assertIn("project.settings.integration", combined)

    def test_service_images_and_storage_are_integration_owned(self):
        services = self.integration["services"]
        self.assertEqual(
            set(services),
            {"caddy", "web", "racebot", "db", "redis", "fixture-provider"},
        )
        self.assertEqual(services["web"]["build"]["target"], "web")
        self.assertEqual(services["racebot"]["build"]["target"], "racebot")
        self.assertNotIn("image", services["web"])
        self.assertNotIn("image", services["racebot"])

        db_mounts = " ".join(services["db"]["volumes"])
        redis_mounts = " ".join(services["redis"]["volumes"])
        self.assertIn("integration-db-data", db_mounts)
        self.assertIn("integration-redis-data", redis_mounts)
        self.assertNotIn("secret-data", self.integration_text)

    def test_fixture_preparation_exposes_the_application_import_root(self):
        integration_up = INTEGRATION_UP.read_text(encoding="utf-8")
        self.assertIn(
            "run --rm --env PYTHONPATH=/srv/racetime --entrypoint python web "
            "/fixtures/prepare_integration.py",
            integration_up,
        )

if __name__ == "__main__":
    unittest.main()
