from pathlib import Path
import re
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = ROOT / "deploy" / "compose.production.yml"
VARIABLE = re.compile(r"\$\{([A-Z0-9_]+):\?[^}]+\}")
BASE_ENVIRONMENT = {
    "RACETIME_IMAGE": "ghcr.io/z1rracing/racetime-app",
    "RACETIME_IMAGE_DIGEST": "sha256:" + "1" * 64,
    "RACETIME_MAINTENANCE_IMAGE": "ghcr.io/z1rracing/racetime-maintenance",
    "RACETIME_MAINTENANCE_IMAGE_DIGEST": "sha256:" + "2" * 64,
    "RACETIME_ENV_FILE": "./env/ci.env",
    "CADDY_ENV_FILE": "./caddy/qualification.env.example",
}


def render_compose(state, *, caddy_state=None, environment=None):
    values = {
        **BASE_ENVIRONMENT,
        "RACETIME_STATE_GENERATION": state,
        "CADDY_STATE_VOLUME": caddy_state or f"z1rr-racetime-caddy-{state}",
        "CADDY_ENV_FILE": (
            f"./caddy/{'qualification' if state == 'qualification' else 'production-restricted'}.env.example"
        ),
        **(environment or {}),
    }
    text = COMPOSE_PATH.read_text(encoding="utf-8")

    def replace(match):
        name = match.group(1)
        if not values.get(name):
            raise ValueError(f"missing {name}")
        return values[name]

    rendered = VARIABLE.sub(replace, text)
    if "${" in rendered:
        raise AssertionError("unresolved Compose interpolation")
    return yaml.safe_load(rendered), rendered


class ComposeContractTests(unittest.TestCase):
    def test_required_service_and_one_shot_topology(self):
        config, _ = render_compose("qualification")
        services = config["services"]
        self.assertEqual(set(services), {
            "caddy", "web", "racebot", "db", "redis",
            "migrate", "collectstatic", "maintenance",
        })
        self.assertEqual(services["migrate"]["command"], ["migrate"])
        self.assertEqual(
            services["collectstatic"]["command"], ["collectstatic"],
        )
        self.assertEqual(services["migrate"]["restart"], "no")
        self.assertEqual(services["collectstatic"]["restart"], "no")
        self.assertEqual(services["migrate"]["profiles"], ["deploy"])
        self.assertEqual(services["collectstatic"]["profiles"], ["deploy"])
        self.assertEqual(services["maintenance"]["profiles"], ["maintenance"])
        self.assertEqual(services["maintenance"]["command"], ["maintenance"])
        self.assertEqual(
            services["caddy"]["env_file"],
            ["./caddy/qualification.env.example"],
        )
        self.assertNotIn("migrate", services["racebot"].get("depends_on", {}))

    def test_proxy_network_has_exactly_caddy_and_web(self):
        config, _ = render_compose("qualification")
        proxy = config["networks"]["proxy"]
        self.assertEqual(
            proxy["ipam"]["config"], [{"subnet": "172.30.0.0/29"}],
        )
        attached = {
            name: service["networks"]["proxy"]["ipv4_address"]
            for name, service in config["services"].items()
            if "proxy" in service.get("networks", {})
        }
        self.assertEqual(attached, {
            "caddy": "172.30.0.2",
            "web": "172.30.0.3",
        })
        self.assertTrue(config["networks"]["data"]["internal"])
        self.assertNotIn("data", config["services"]["caddy"]["networks"])
        for service in ("web", "racebot", "db", "redis"):
            self.assertIn("data", config["services"][service]["networks"])
        self.assertEqual(
            config["services"]["web"]["environment"]
            ["RACETIME_TRUSTED_PROXY_CIDRS"],
            "172.30.0.2/32",
        )

    def test_only_caddy_publishes_reviewed_ports(self):
        config, rendered = render_compose("qualification")
        services = config["services"]
        self.assertEqual(
            services["caddy"]["ports"],
            ["80:80", "443:443", "127.0.0.1:8081:8081"],
        )
        for name, service in services.items():
            if name != "caddy":
                self.assertNotIn("ports", service, name)
        self.assertNotIn("0.0.0.0:8081", rendered)
        self.assertNotIn("8081:8081", rendered.replace(
            "127.0.0.1:8081:8081", "",
        ))

    def test_images_are_immutable_and_no_build_or_bind_mount_exists(self):
        config, rendered = render_compose("qualification")
        for name, service in config["services"].items():
            self.assertNotIn("build", service, name)
            self.assertRegex(
                service["image"], r"^[^\s]+@sha256:[0-9a-f]{64}$", name,
            )
            self.assertNotIn(":latest", service["image"])
            for mount in service.get("volumes", []):
                source = mount.split(":", 1)[0]
                self.assertFalse(source.startswith((".", "/", "~")), mount)
        self.assertNotIn("qualification state", rendered.lower())
        self.assertNotRegex(rendered, r"(?i)\b(copy|cp|rsync|promote)\b.*(?:volume|state)")

    def test_state_generations_select_distinct_named_volumes(self):
        expected_suffixes = {"db", "redis", "media", "static", "secrets"}
        rendered = {}
        for state in ("qualification", "production"):
            config, text = render_compose(state)
            names = {entry["name"] for entry in config["volumes"].values()}
            expected = {
                f"z1rr-racetime-{state}-{suffix}"
                for suffix in expected_suffixes
            } | {f"z1rr-racetime-caddy-{state}"}
            self.assertEqual(names, expected)
            caddy_mounts = config["services"]["caddy"]["volumes"]
            self.assertEqual(
                [mount for mount in caddy_mounts if mount.startswith("caddy-state:")],
                ["caddy-state:/var/lib/caddy"],
            )
            rendered[state] = text
        self.assertNotIn("qualification", rendered["production"])
        self.assertNotIn("production", rendered["qualification"])

    def test_storage_ownership_and_secret_mounts_are_explicit(self):
        config, _ = render_compose("qualification")
        services = config["services"]
        self.assertIn("db-data:/var/lib/mysql", services["db"]["volumes"])
        self.assertIn("redis-data:/data", services["redis"]["volumes"])
        self.assertIn("static-data:/srv/racetime/static", services["web"]["volumes"])
        self.assertIn("media-data:/srv/racetime/media", services["web"]["volumes"])
        self.assertIn("static-data:/srv/racetime/static:ro", services["caddy"]["volumes"])
        self.assertIn("media-data:/srv/racetime/media:ro", services["caddy"]["volumes"])
        for name in ("web", "racebot", "db", "redis", "migrate", "maintenance"):
            self.assertIn(
                "secret-data:/run/racetime-secrets:ro",
                services[name]["volumes"],
            )
        entrypoint = (
            ROOT / ".docker" / "start-production"
        ).read_text(encoding="utf-8")
        for secret in (
            "DJANGO_SECRET_KEY", "DB_PASSWORD", "REDIS_URL",
            "INTERNAL_HEALTH_TOKEN", "RACETIME_THROTTLE_HMAC_KEY",
            "DISCORD_CLIENT_SECRET", "TWITCH_CLIENT_SECRET",
        ):
            self.assertIn(secret, entrypoint)
        self.assertIn("/run/racetime-secrets", entrypoint)

    def test_long_running_services_have_health_restart_limits_and_logs(self):
        config, _ = render_compose("qualification")
        for name in ("caddy", "web", "racebot", "db", "redis"):
            service = config["services"][name]
            self.assertIn("healthcheck", service, name)
            self.assertEqual(service["restart"], "unless-stopped", name)
            self.assertIn("cpus", service, name)
            self.assertIn("mem_limit", service, name)
            self.assertEqual(service["logging"]["driver"], "json-file")
            self.assertEqual(service["logging"]["options"]["max-size"], "10m")
            self.assertEqual(service["logging"]["options"]["max-file"], "3")
        for name in ("caddy", "web", "racebot"):
            self.assertTrue(config["services"][name]["read_only"])
            self.assertIn("/tmp", " ".join(config["services"][name]["tmpfs"]))
        health_script = (
            ROOT / ".docker" / "healthcheck"
        ).read_text(encoding="utf-8")
        self.assertIn(
            ".docker/healthcheck web",
            " ".join(config["services"]["web"]["healthcheck"]["test"]),
        )
        self.assertIn("/healthz", health_script)
        self.assertIn("racebot_health", health_script)
        self.assertIn("innodb_initialized", " ".join(config["services"]["db"]["healthcheck"]["test"]))
        self.assertIn("redis-cli", " ".join(config["services"]["redis"]["healthcheck"]["test"]))

    def test_missing_generation_selectors_fail_closed(self):
        original = COMPOSE_PATH.read_text(encoding="utf-8")
        for missing in ("RACETIME_STATE_GENERATION", "CADDY_STATE_VOLUME", "CADDY_ENV_FILE"):
            values = {
                **BASE_ENVIRONMENT,
                "RACETIME_STATE_GENERATION": "qualification",
                "CADDY_STATE_VOLUME": "z1rr-racetime-caddy-qualification",
            }
            values.pop(missing)
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                VARIABLE.sub(
                    lambda match: values.get(match.group(1))
                    or (_ for _ in ()).throw(ValueError(match.group(1))),
                    original,
                )


if __name__ == "__main__":
    unittest.main()
