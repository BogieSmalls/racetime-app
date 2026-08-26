from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
MONITORING = ROOT / "deploy" / "monitoring"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeProbeAdapters:
    def __init__(self):
        self.internal_headers = None

    def http_status(self, url, *, headers, timeout):
        if url.endswith("/admin/"):
            return 404
        if url.startswith("http://127.0.0.1"):
            self.internal_headers = headers
            return 200
        return 200

    def websocket_ok(self, url, *, timeout):
        return True

    def tls_days_remaining(self, host, port, *, timeout, now):
        return 45.0

    def container_metrics(self, names):
        return {
            name: {"running": True, "healthy": True, "restart_count": 0}
            for name in names
        }

    def filesystem_metrics(self, path):
        return {
            "disk_used_percent": 31.0,
            "inode_used_percent": 9.0,
            "memory_used_percent": 42.0,
            "cpu_used_percent": 17.0,
        }

    def read_json(self, path):
        name = Path(path).name
        if name == "application.json":
            return {
                "database_size_bytes": 2_000_000,
                "database_growth_bytes_24h": 100_000,
                "oauth_errors_5m": 1,
                "oauth_requests_5m": 100,
            }
        if name == "backups.json":
            return {
                "database_age_hours": 1.0,
                "media_age_hours": 4.0,
                "database_verified": True,
                "media_verified": True,
                "production_caddy_verified_generations": 3,
            }
        if name == "oci.json":
            return {
                "a1_actual_ocpu_hours": 1000.0,
                "a1_projected_ocpu_hours": 1500.0,
                "a1_forecast_ocpu_hours": 1494.0,
                "a1_slope_projected_72h": 1550.0,
                "object_storage_bytes_percent": 20.0,
                "object_storage_requests_percent": 10.0,
                "retained_volume_cost_usd": 3.61,
                "billing_events": [],
            }
        raise AssertionError(path)


class ProbeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.probe = load_module("z1rr_monitor_probe", MONITORING / "probe.py")

    def config(self):
        return {
            "schema_version": 1,
            "public_origin": "https://raceroom.z1rracing.com",
            "websocket_url": "wss://raceroom.z1rracing.com/ws/oob/",
            "public_admin_path": "/admin/",
            "internal_readiness_url": "http://127.0.0.1:8000/healthz?scope=internal",
            "internal_token_env": "RACETIME_MONITOR_TOKEN",
            "tls_host": "raceroom.z1rracing.com",
            "tls_port": 443,
            "container_names": ["web", "racebot", "db", "redis", "caddy"],
            "filesystem_path": "/srv/racetime",
            "application_metrics_path": "application.json",
            "backup_metrics_path": "backups.json",
            "oci_metrics_path": "oci.json",
            "timeout_seconds": 5,
        }

    def test_collect_snapshot_covers_every_required_signal_without_bodies(self):
        adapters = FakeProbeAdapters()
        now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)

        snapshot = self.probe.collect_snapshot(
            self.config(),
            adapters=adapters,
            environ={"RACETIME_MONITOR_TOKEN": "monitor-canary-secret"},
            now=now,
        )

        self.assertEqual(snapshot["observed_at"], "2026-08-24T12:00:00Z")
        self.assertEqual(
            set(snapshot["checks"]),
            {"https", "websocket", "public_admin_denial", "internal_readiness", "tls"},
        )
        self.assertEqual(
            set(snapshot["metrics"]),
            {"containers", "system", "application", "backups", "oci"},
        )
        self.assertEqual(
            adapters.internal_headers,
            {"Authorization": "Bearer monitor-canary-secret"},
        )
        rendered = json.dumps(snapshot, sort_keys=True)
        self.assertNotIn("monitor-canary-secret", rendered)
        self.assertNotIn("response_body", rendered)

    def test_rejects_non_loopback_internal_probe_and_noncanonical_urls(self):
        for key, value in (
            ("public_origin", "http://raceroom.z1rracing.com"),
            ("websocket_url", "wss://example.test/ws/"),
            ("internal_readiness_url", "http://10.0.0.9:8000/healthz"),
        ):
            with self.subTest(key=key):
                config = self.config()
                config[key] = value
                with self.assertRaises(ValueError):
                    self.probe.collect_snapshot(
                        config,
                        adapters=FakeProbeAdapters(),
                        environ={"RACETIME_MONITOR_TOKEN": "secret"},
                    )

    def test_rule_events_are_directly_compatible_with_the_signed_alert_contract(self):
        snapshot = self.probe.empty_snapshot()
        snapshot["checks"]["https"] = {"ok": False, "consecutive_failures": 2}
        event = self.probe.evaluate_rules(snapshot)[0]
        self.assertEqual(
            set(event),
            {
                "schema_version", "event_id", "status", "code", "severity",
                "component", "summary", "observed_at", "runbook", "details",
            },
        )
        self.assertEqual(event["event_id"], "ingress:HTTPS_UNAVAILABLE")
        self.assertEqual(event["status"], "firing")
        self.assertEqual(
            json.loads((MONITORING / "rules.example.json").read_text(encoding="utf-8")),
            self.probe.default_rules(),
        )

    def test_cost_policy_warns_below_cutoff_suppresses_high_forecast_and_escalates(self):
        evaluate = self.probe.evaluate_rules
        rules = self.probe.default_rules()

        low = self.probe.empty_snapshot()
        low["metrics"]["oci"] = {
            "a1_actual_ocpu_hours": 1000,
            "a1_projected_ocpu_hours": 1600,
            "a1_forecast_ocpu_hours": 1494,
            "a1_slope_projected_72h": 1610,
            "object_storage_bytes_percent": 20,
            "object_storage_requests_percent": 10,
            "retained_volume_cost_usd": 3.61,
            "billing_events": [],
        }
        low_codes = {event["code"] for event in evaluate(low, rules)}
        self.assertIn("A1_FORECAST_VARIANCE", low_codes)

        high = json.loads(json.dumps(low))
        high["metrics"]["oci"].update(
            a1_forecast_ocpu_hours=2744,
            a1_projected_ocpu_hours=2881,
            a1_slope_projected_72h=2881,
        )
        high_codes = {event["code"] for event in evaluate(high, rules)}
        self.assertNotIn("A1_FORECAST_VARIANCE", high_codes)
        self.assertIn("A1_HIGH_FORECAST_RECORDED", high_codes)

        high["metrics"]["oci"]["a1_projected_ocpu_hours"] = 2900
        events = evaluate(high, rules)
        escalation = next(event for event in events if event["code"] == "A1_ALLOWANCE_ESCALATION")
        self.assertEqual(escalation["severity"], "P2")
        self.assertIn("Restream", escalation["summary"])

    def test_service_backup_storage_and_auth_thresholds_are_actionable(self):
        snapshot = self.probe.empty_snapshot()
        snapshot["checks"]["https"] = {"ok": False, "consecutive_failures": 3}
        snapshot["checks"]["websocket"] = {"ok": False, "consecutive_failures": 3}
        snapshot["checks"]["tls"] = {"ok": True, "days_remaining": 20}
        snapshot["metrics"]["containers"] = {
            "web": {"running": True, "healthy": False, "restart_count": 4},
            "racebot": {"running": False, "healthy": False, "restart_count": 0},
            "db": {"running": True, "healthy": False, "restart_count": 0},
            "redis": {"running": True, "healthy": False, "restart_count": 0},
        }
        snapshot["metrics"]["system"] = {
            "cpu_used_percent": 85,
            "memory_used_percent": 75,
            "disk_used_percent": 85,
            "inode_used_percent": 91,
        }
        snapshot["metrics"]["application"] = {
            "database_growth_bytes_24h": 2_000_000_000,
            "oauth_errors_5m": 10,
            "oauth_requests_5m": 20,
        }
        snapshot["metrics"]["backups"] = {
            "database_age_hours": 8,
            "media_age_hours": 27,
            "database_verified": False,
            "media_verified": False,
            "production_caddy_verified_generations": 1,
        }
        snapshot["metrics"]["oci"] = {
            "a1_actual_ocpu_hours": 1000,
            "a1_projected_ocpu_hours": 1200,
            "a1_forecast_ocpu_hours": 1494,
            "a1_slope_projected_72h": 1200,
            "object_storage_bytes_percent": 91,
            "object_storage_requests_percent": 76,
            "retained_volume_cost_usd": 6.62,
            "billing_events": [{"service": "compute", "amount_usd": 1.0}],
        }

        codes = {event["code"] for event in self.probe.evaluate_rules(snapshot, self.probe.default_rules())}
        expected = {
            "HTTPS_UNAVAILABLE", "WSS_UNAVAILABLE", "TLS_EXPIRING",
            "CONTAINER_UNHEALTHY", "CONTAINER_RESTART_LOOP", "RESOURCE_HEADROOM",
            "DATABASE_GROWTH", "OAUTH_ERROR_RATE", "DATABASE_BACKUP_STALE",
            "MEDIA_BACKUP_STALE", "BACKUP_UNVERIFIED", "CADDY_BACKUP_GENERATIONS",
            "OBJECT_STORAGE_ESCALATION", "RETAINED_VOLUME_ESCALATION", "BILLING_EVENT",
        }
        self.assertTrue(expected.issubset(codes), expected - codes)


class AlertContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.alert = load_module("z1rr_monitor_alert", MONITORING / "alert.py")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.sent = []
        self.responses = [204]
        self.secret = b"alert-signing-secret"
        self.config = {
            "schema_version": 1,
            "webhook_url": "https://discord.com/api/webhooks/example/token",
            "webhook_host_allowlist": ["discord.com"],
            "signing_secret_env": "RACETIME_ALERT_HMAC",
            "state_path": str(Path(self.temp.name) / "state.json"),
            "max_attempts": 3,
            "retry_seconds": 0,
            "dedupe_seconds": 900,
        }

    def sender(self, url, body, timeout):
        self.sent.append((url, json.loads(body.decode("utf-8"))))
        return self.responses.pop(0)

    def signed(self, payload):
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature = "sha256=" + hmac.new(self.secret, raw, hashlib.sha256).hexdigest()
        return raw, signature

    def event(self, *, status="firing", event_id="event-1"):
        return {
            "schema_version": 1,
            "event_id": event_id,
            "status": status,
            "code": "HTTPS_UNAVAILABLE",
            "severity": "P1",
            "component": "ingress",
            "summary": "HTTPS failed; token=summary-canary",
            "observed_at": "2026-08-24T12:00:00Z",
            "runbook": "docs/runbooks/monitoring.md",
            "details": {
                "authorization": "Bearer nested-canary",
                "url": "https://discord.com/api/webhooks/id/url-canary",
            },
        }

    def dispatcher(self):
        return self.alert.AlertDispatcher(
            self.config,
            environ={"RACETIME_ALERT_HMAC": self.secret.decode()},
            sender=self.sender,
            sleeper=lambda _: None,
            clock=lambda: 1_777_000_000.0,
        )

    def test_signed_alert_is_redacted_retried_deduped_and_recovers(self):
        self.responses = [500, 204, 204]
        payload = self.event()
        raw, signature = self.signed(payload)
        result = self.dispatcher().dispatch(raw, signature)
        self.assertEqual(result, "delivered")
        self.assertEqual(len(self.sent), 2)
        rendered = json.dumps(self.sent[-1][1], sort_keys=True)
        for canary in ("summary-canary", "nested-canary", "url-canary"):
            self.assertNotIn(canary, rendered)
        self.assertIn("[REDACTED]", rendered)

        duplicate = self.dispatcher().dispatch(raw, signature)
        self.assertEqual(duplicate, "deduped")
        self.assertEqual(len(self.sent), 2)

        recovery_raw, recovery_signature = self.signed(self.event(status="resolved"))
        recovered = self.dispatcher().dispatch(recovery_raw, recovery_signature)
        self.assertEqual(recovered, "delivered")
        self.assertEqual(len(self.sent), 3)
        self.assertEqual(self.sent[-1][1]["content"].split()[0], "RESOLVED")

    def test_bad_signature_bad_host_and_unbounded_attempts_fail_closed(self):
        raw, signature = self.signed(self.event())
        with self.assertRaises(ValueError):
            self.dispatcher().dispatch(raw, "sha256=" + "0" * 64)

        bad_config = dict(self.config, webhook_url="https://example.test/hook")
        with self.assertRaises(ValueError):
            self.alert.AlertDispatcher(
                bad_config,
                environ={"RACETIME_ALERT_HMAC": self.secret.decode()},
                sender=self.sender,
            )

        bad_config = dict(self.config, max_attempts=6)
        with self.assertRaises(ValueError):
            self.alert.AlertDispatcher(
                bad_config,
                environ={"RACETIME_ALERT_HMAC": self.secret.decode()},
                sender=self.sender,
            )


if __name__ == "__main__":
    unittest.main()
