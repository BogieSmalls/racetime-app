import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "deploy" / "backup" / "retention.py"
SPEC = importlib.util.spec_from_file_location("z1rr_retention", MODULE_PATH)
retention = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(retention)

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


def point(name, backup_type, age_days, *, verified=True, pinned_until=None):
    completed = NOW - timedelta(days=age_days)
    item = {
        "schema": 1,
        "type": backup_type,
        "completed_at": completed.isoformat().replace("+00:00", "Z"),
        "verification": {
            "result": "verified" if verified else "failed",
            "at": completed.isoformat().replace("+00:00", "Z"),
        },
        "object_storage": {
            "object": f"production/{backup_type}/{name}.age",
            "manifest_object": f"production/{backup_type}/{name}.manifest.json",
        },
    }
    if pinned_until:
        item["retention"] = {"pinned_until": pinned_until}
    return item


class RetentionPolicyTests(unittest.TestCase):
    def actions(self, items):
        plan = retention.plan_retention(items, now=NOW)
        return {
            action: {entry["name"] for entry in entries}
            for action, entries in plan.items()
        }

    def test_keeps_every_database_and_media_point_for_fourteen_days(self):
        items = []
        for backup_type in ("database", "media"):
            items.extend(
                point(f"{backup_type}-{age}", backup_type, age)
                for age in (0, 1, 7, 13.999)
            )

        actions = self.actions(items)

        self.assertEqual(len(actions["retain"]), 8)
        self.assertEqual(actions["delete"], set())
        self.assertEqual(actions["quarantine"], set())

    def test_keeps_one_newest_weekly_point_for_weeks_three_through_thirteen(self):
        items = [
            point("week3-new", "database", 15),
            point("week3-old", "database", 19),
            point("week4-new", "database", 22),
            point("week4-old", "database", 27),
            point("week13", "database", 88),
        ]

        actions = self.actions(items)

        self.assertTrue({"week3-new", "week4-new", "week13"} <= actions["retain"])
        self.assertTrue({"week3-old", "week4-old"} <= actions["delete"])

    def test_keeps_one_newest_calendar_month_point_for_months_four_to_twelve(self):
        items = [
            point("may-new", "media", 105),
            point("may-old", "media", 112),
            point("april", "media", 140),
            point("oldest-window", "media", 360),
            point("expired", "media", 370),
        ]

        actions = self.actions(items)

        self.assertTrue({"may-new", "april", "oldest-window"} <= actions["retain"])
        self.assertTrue({"may-old", "expired"} <= actions["delete"])

    def test_pinned_predeploy_points_survive_until_explicit_expiry(self):
        future = (NOW + timedelta(days=20)).isoformat().replace("+00:00", "Z")
        past = (NOW - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        items = [
            point("pinned", "database", 500, pinned_until=future),
            point("expired-pin", "database", 500, pinned_until=past),
            point("newest", "database", 400),
        ]

        actions = self.actions(items)

        self.assertIn("pinned", actions["retain"])
        self.assertIn("newest", actions["retain"])
        self.assertIn("expired-pin", actions["delete"])

    def test_caddy_retains_current_plus_two_prior_verified_generations(self):
        items = [
            point(f"caddy-{age}", "production-caddy-state", age)
            for age in (1, 5, 10, 15, 20)
        ]

        actions = self.actions(items)

        self.assertEqual(actions["retain"], {"caddy-1", "caddy-5", "caddy-10"})
        self.assertEqual(actions["delete"], {"caddy-15", "caddy-20"})

    def test_newest_verified_point_of_each_type_is_never_deleted(self):
        items = [
            point("db-only", "database", 800),
            point("media-only", "media", 800),
            point("caddy-only", "production-caddy-state", 800),
        ]

        actions = self.actions(items)

        self.assertEqual(actions["retain"], {"db-only", "media-only", "caddy-only"})
        self.assertEqual(actions["delete"], set())

    def test_malformed_unverified_and_qualification_points_are_quarantined(self):
        malformed = {"type": "database"}
        failed = point("failed", "database", 1, verified=False)
        qualification = point("qualification", "database", 1)
        qualification["object_storage"]["object"] = "qualification/database/q.age"
        unknown = point("unknown", "redis", 1)

        plan = retention.plan_retention(
            [malformed, failed, qualification, unknown], now=NOW
        )

        self.assertEqual(len(plan["quarantine"]), 4)
        self.assertEqual(plan["delete"], [])

    def test_invalid_or_ambiguous_timestamps_are_quarantined(self):
        naive = point("naive", "database", 1)
        naive["completed_at"] = "2026-08-23T12:00:00"
        future = point("future", "database", -2)

        plan = retention.plan_retention([naive, future], now=NOW)

        self.assertEqual(len(plan["quarantine"]), 2)


class RetentionExecutionTests(unittest.TestCase):
    def setUp(self):
        self.plan = {
            "retain": [],
            "quarantine": [],
            "delete": [
                {
                    "name": "expired",
                    "object": "production/database/expired.age",
                    "manifest_object": "production/database/expired.manifest.json",
                    "reason": "expired",
                }
            ],
        }
        self.config = {
            "namespace": "testnamespace",
            "bucket": "z1rr-backups",
        }

    def test_dry_run_is_default_and_never_invokes_delete(self):
        runner = mock.Mock()

        result = retention.apply_retention(
            self.plan, config=self.config, runner=runner
        )

        self.assertEqual(result["mode"], "dry-run")
        runner.assert_not_called()

    def test_apply_removes_completion_marker_before_artifact_with_instance_principal(self):
        runner = mock.Mock(
            return_value=subprocess.CompletedProcess([], 0, "", "")
        )

        result = retention.apply_retention(
            self.plan, config=self.config, apply=True, runner=runner
        )

        self.assertEqual(result["mode"], "apply")
        self.assertEqual(runner.call_count, 2)
        commands = [call.args[0] for call in runner.call_args_list]
        self.assertIn("--auth", commands[0])
        self.assertIn("instance_principal", commands[0])
        self.assertEqual(commands[0][-1], "production/database/expired.manifest.json")
        self.assertEqual(commands[1][-1], "production/database/expired.age")

    def test_delete_failure_stops_without_claiming_success(self):
        runner = mock.Mock(
            return_value=subprocess.CompletedProcess([], 1, "", "denied")
        )
        with self.assertRaises(retention.RetentionError):
            retention.apply_retention(
                self.plan, config=self.config, apply=True, runner=runner
            )

    def test_namespace_not_found_is_an_error_not_an_empty_listing(self):
        runner = mock.Mock(
            return_value=subprocess.CompletedProcess(
                [], 1, "", "ServiceError: NamespaceNotFound"
            )
        )
        with self.assertRaises(retention.RetentionError):
            retention.list_manifest_objects(
                config=self.config, prefix="production/", runner=runner
            )

    def test_remote_loader_lists_and_downloads_verified_manifests(self):
        expected = point("db", "database", 1)
        commands = []

        def runner(command, **kwargs):
            commands.append(command)
            operation = command[3]
            if operation == "list":
                return subprocess.CompletedProcess(
                    command,
                    0,
                    json.dumps(
                        {
                            "data": [
                                {
                                    "name": (
                                        "production/database/"
                                        "db.manifest.json"
                                    )
                                }
                            ]
                        }
                    ),
                    "",
                )
            self.assertEqual(operation, "get")
            destination = Path(command[command.index("--file") + 1])
            destination.write_text(json.dumps(expected), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        loaded = retention.load_remote_manifests(
            config=self.config, prefix="production/", runner=runner
        )

        self.assertEqual(loaded, [expected])
        self.assertEqual([command[3] for command in commands], ["list", "get"])
        self.assertIn("instance_principal", commands[1])

    def test_cli_writes_quarantine_plan_and_returns_failure_for_alerting(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "manifests.json"
            source.write_text(
                json.dumps([{"schema": 1, "type": "database"}]),
                encoding="utf-8",
            )
            output = Path(temp) / "plan.json"

            with mock.patch.object(retention, "apply_retention") as apply:
                code = retention.main(
                    [
                        "--manifest-index",
                        str(source),
                        "--output",
                        str(output),
                        "--now",
                        NOW.isoformat(),
                        "--apply",
                    ]
                )

            self.assertEqual(code, 2)
            apply.assert_not_called()
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["mode"], "blocked-quarantine")
            self.assertEqual(len(payload["actions"]["quarantine"]), 1)
            self.assertEqual(payload["actions"]["delete"], [])

    def test_cli_writes_schema_versioned_plan_and_requires_apply_flag(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "manifests.json"
            source.write_text(
                json.dumps([point("db", "database", 1)]), encoding="utf-8"
            )
            output = Path(temp) / "plan.json"
            code = retention.main(
                [
                    "--manifest-index",
                    str(source),
                    "--output",
                    str(output),
                    "--now",
                    NOW.isoformat(),
                ]
            )
            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema"], 1)
            self.assertEqual(payload["mode"], "dry-run")


if __name__ == "__main__":
    unittest.main()
