import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy" / "scripts" / "deploy.sh"
ROLLBACK = ROOT / "deploy" / "scripts" / "rollback.sh"
SMOKE = ROOT / "deploy" / "scripts" / "smoke.py"
RELEASE_TOOL = ROOT / "deploy" / "scripts" / "release_tool.py"
RELEASE_SCHEMA = ROOT / "deploy" / "release-manifest.schema.json"
BACKUP_MANIFEST_TOOL = ROOT / "deploy" / "backup" / "manifest.py"
GIT_BASH = Path(r"C:\Program Files\Git\bin\bash.exe")
BASH = shutil.which("bash") or (str(GIT_BASH) if GIT_BASH.exists() else None)

PRIOR_SHA = "1" * 40
TARGET_SHA = "2" * 40
FIX_SHA = "3" * 40


def digest(character):
    return "sha256:" + character * 64


def release_manifest(
    release_sha,
    character,
    *,
    strategy="none",
    rollback_class="code-only",
    reverse_target=None,
    forward_fix_release=None,
    minimum_rollback_digest=None,
):
    return {
        "schema": 1,
        "release_sha": release_sha,
        "generated_at": "2026-08-24T00:00:00Z",
        "images": {
            "application": {
                "repository": "ghcr.io/z1rracing/racetime",
                "digest": digest(character),
                "platforms": {
                    "linux/arm64": digest("a"),
                    "linux/amd64": digest("b"),
                },
            },
            "maintenance": {
                "repository": "ghcr.io/z1rracing/racetime-maintenance",
                "digest": digest(character.upper().lower()),
                "platforms": {
                    "linux/arm64": digest("c"),
                    "linux/amd64": digest("d"),
                },
            },
        },
        "migrations": {
            "from": "racetime.0082_externalidentity",
            "to": (
                "racetime.0083_example"
                if strategy != "none"
                else "racetime.0082_externalidentity"
            ),
            "strategy": strategy,
            "rollback_class": rollback_class,
            "reverse_target": reverse_target,
            "forward_fix_release": forward_fix_release,
        },
        "config_schema_version": 1,
        "minimum_rollback_digest": (
            minimum_rollback_digest or digest("1")
        ),
        "smoke_version": 1,
    }


def canonical_hash(value):
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def release_record(manifest, *, emergency_change_id=None):
    return {
        "schema": 1,
        "manifest": manifest,
        "manifest_sha256": canonical_hash(manifest),
        "promoted_at": "2026-08-24T00:01:00Z",
        "actor": "test-operator",
        "emergency_change_id": emergency_change_id,
    }


class ReleaseManifestContractTests(unittest.TestCase):
    def test_schema_and_validator_require_immutable_multiplatform_release(self):
        schema = json.loads(RELEASE_SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(
            set(schema["required"]),
            {
                "schema",
                "release_sha",
                "generated_at",
                "images",
                "migrations",
                "config_schema_version",
                "minimum_rollback_digest",
                "smoke_version",
            },
        )
        spec = importlib.util.spec_from_file_location(
            "z1rr_release_tool", RELEASE_TOOL
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        valid = release_manifest(
            TARGET_SHA,
            "2",
            strategy="expand",
            rollback_class="code-only",
        )
        module.validate_manifest(valid)

        bad_platform = json.loads(json.dumps(valid))
        del bad_platform["images"]["application"]["platforms"]["linux/amd64"]
        bad_repository = json.loads(json.dumps(valid))
        bad_repository["images"]["application"]["repository"] = "https://evil.invalid/x"
        blind_reverse = json.loads(json.dumps(valid))
        blind_reverse["migrations"]["rollback_class"] = "reversible"
        for candidate in (bad_platform, bad_repository, blind_reverse):
            with self.subTest(candidate=candidate), self.assertRaises(
                module.ReleaseError
            ):
                module.validate_manifest(candidate)

    def test_scripts_declare_every_required_gate_and_no_database_restore(self):
        deploy = DEPLOY.read_text(encoding="utf-8")
        rollback = ROLLBACK.read_text(encoding="utf-8")
        smoke = SMOKE.read_text(encoding="utf-8")
        for token in (
            "flock",
            "preflight.sh",
            "--type database",
            "--pinned-until",
            "cosign verify",
            "verify-attestation",
            "spdxjson",
            "slsaprovenance",
            "migrate --plan",
            "collectstatic",
            "stop web racebot",
            "smoke.py",
            "promote",
            "audit",
        ):
            with self.subTest(token=token):
                self.assertIn(token, deploy)
        for token in (
            "code-only",
            "forward-fix",
            "reversible",
            "--expected-current-release",
            "--reverse-target",
            "--emergency-change-id",
        ):
            with self.subTest(token=token):
                self.assertIn(token, rollback)
        self.assertNotIn("restore-test.sh", rollback)
        self.assertNotIn("mariadb <", rollback)
        for token in (
            "/healthz",
            "/internal/readyz",
            "/account/discord",
            "Sec-WebSocket-Key",
            "101",
            "database",
            "cache",
        ):
            with self.subTest(token=token):
                self.assertIn(token, smoke)


class SmokeValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("z1rr_smoke", SMOKE)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_public_origin_requires_a_bare_https_origin(self):
        self.assertEqual(
            self.module._origin("https://raceroom.z1rracing.com"),
            ("raceroom.z1rracing.com", 443),
        )
        for value in (
            "http://raceroom.z1rracing.com",
            "https://user@raceroom.z1rracing.com",
            "https://raceroom.z1rracing.com/healthz",
            "https://raceroom.z1rracing.com?token=bad",
        ):
            with self.subTest(value=value), self.assertRaises(
                self.module.SmokeError
            ):
                self.module._origin(value)

    def test_internal_token_destination_is_strictly_local(self):
        for value in (
            "http://127.0.0.1/internal/readyz",
            "https://localhost/internal/readyz",
            "http://web/internal/readyz",
        ):
            self.module._internal_url(value)
        for value in (
            "https://attacker.invalid/internal/readyz",
            "https://web/internal/readyz",
            "http://127.0.0.1/internal/readyz?redirect=bad",
        ):
            with self.subTest(value=value), self.assertRaises(
                self.module.SmokeError
            ):
                self.module._internal_url(value)


@unittest.skipUnless(BASH, "bash is required for deploy behavior tests")
class DeployScriptBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix="deploy-", dir=ROOT / "tests" / "platform"
        )
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.bin = self.work / "bin"
        self.bin.mkdir()
        self.state = self.work / "state"
        self.state.mkdir()
        self.backup_status = self.work / "backup-status"
        self.backup_status.mkdir()
        self.log = self.work / "commands.log"
        self.log.write_text("", encoding="utf-8")
        self.config = self.work / "deploy.env"
        self.prior_manifest = release_manifest(PRIOR_SHA, "1")
        self.target_manifest = release_manifest(
            TARGET_SHA,
            "2",
            strategy="expand",
            rollback_class="code-only",
            minimum_rollback_digest=digest("1"),
        )
        self.prior_path = self.work / "prior.json"
        self.target_path = self.work / "target.json"
        self._write_json(self.prior_path, self.prior_manifest)
        self._write_json(self.target_path, self.target_manifest)
        self._write_json(
            self.state / "current-release.json",
            release_record(self.prior_manifest),
        )
        self.backup_manifest = self.work / "verified-backup.json"
        self._write_backup_manifest(PRIOR_SHA)
        self._install_fakes()
        self._write_config()

    def _posix(self, path):
        resolved = Path(path).resolve()
        value = resolved.as_posix()
        if os.name == "nt":
            drive = resolved.drive.rstrip(":").lower()
            remainder = value[len(resolved.drive):].lstrip("/")
            return f"/{drive}/{remainder}"
        return value

    def _write_json(self, path, value):
        path.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    def _write_executable(self, path, source):
        path.write_text(source, encoding="utf-8", newline="\n")
        path.chmod(
            path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )

    def _write_backup_manifest(self, release_sha):
        spec = importlib.util.spec_from_file_location(
            "z1rr_backup_manifest", BACKUP_MANIFEST_TOOL
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        value = module.example_manifest()
        value["release_sha"] = release_sha
        self._write_json(self.backup_manifest, value)

    def _install_fakes(self):
        self._write_executable(
            self.bin / "stat",
            "#!/usr/bin/env bash\nprintf '%s\\n' 0\n",
        )
        self._write_executable(
            self.bin / "flock",
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                printf 'flock %s\n' "$*" >> "$FAKE_COMMAND_LOG"
                [ "$FAKE_FLOCK_FAIL" = 1 ] && exit 9
                exit 0
                """
            ),
        )
        self._write_executable(
            self.bin / "docker",
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                printf 'docker %s app_digest=%s maintenance_digest=%s state_generation=%s\n' "$*" \
                  "${RACETIME_IMAGE_DIGEST:-unset}" "${RACETIME_MAINTENANCE_IMAGE_DIGEST:-unset}" \
                  "${RACETIME_STATE_GENERATION:-unset}" >> "$FAKE_COMMAND_LOG"
                case "$*" in
                  *" ps -q "*) printf '%s\n' fake-container ;;
                  "inspect --format "*) printf '%s\n' healthy ;;
                  *"migrate --plan"*) printf '%s\n' 'Planned operations:' 'racetime.0083_example' ;;
                  *"showmigrations --plan"*) printf '%s\n' '[X] racetime.0082_externalidentity' ;;
                esac
                exit 0
                """
            ),
        )
        self._write_executable(
            self.bin / "cosign",
            "#!/usr/bin/env bash\nprintf 'cosign %s\\n' \"$*\" >> \"$FAKE_COMMAND_LOG\"\n",
        )
        self.preflight = self.work / "preflight.sh"
        self._write_executable(
            self.preflight,
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                printf 'preflight %s\n' "$*" >> "$FAKE_COMMAND_LOG"
                if [ "$FAKE_ACTIVE_RACES" = 1 ]; then
                  case " $* " in
                    *" --emergency-change-id "*) exit 0 ;;
                    *) exit 23 ;;
                  esac
                fi
                """
            ),
        )
        self.backup = self.work / "backup.sh"
        self._write_executable(
            self.backup,
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                printf 'backup %s\n' "$*" >> "$FAKE_COMMAND_LOG"
                release=''
                while (($#)); do
                  [ "$1" = --release-sha ] && { release="$2"; shift 2; continue; }
                  shift
                done
                [ "$release" = "$FAKE_EXPECTED_BACKUP_SHA" ] || exit 31
                cp "$FAKE_BACKUP_MANIFEST" "$FAKE_BACKUP_STATUS_DIR/last-database.json"
                """
            ),
        )
        self.smoke = self.work / "smoke.sh"
        self._write_executable(
            self.smoke,
            "#!/usr/bin/env bash\nprintf 'smoke %s\\n' \"$*\" >> \"$FAKE_COMMAND_LOG\"\n",
        )

    def _write_config(self):
        values = {
            "Z1RR_DEPLOY_STATE_DIR": self._posix(self.state),
            "Z1RR_BACKUP_STATUS_DIR": self._posix(self.backup_status),
            "Z1RR_COMPOSE_FILE": self._posix(
                ROOT / "deploy" / "compose.production.yml"
            ),
            "Z1RR_PREFLIGHT_SCRIPT": self._posix(self.preflight),
            "Z1RR_BACKUP_SCRIPT": self._posix(self.backup),
            "Z1RR_SMOKE_SCRIPT": self._posix(self.smoke),
            "Z1RR_APP_IMAGE_REPOSITORY": "ghcr.io/z1rracing/racetime",
            "Z1RR_MAINTENANCE_IMAGE_REPOSITORY": (
                "ghcr.io/z1rracing/racetime-maintenance"
            ),
            "Z1RR_COSIGN_IDENTITY_REGEXP": (
                "https://github.com/z1rracing/racetime/"
                ".github/workflows/release.yml@refs/heads/main"
            ),
            "Z1RR_COSIGN_OIDC_ISSUER": (
                "https://token.actions.githubusercontent.com"
            ),
            "Z1RR_PUBLIC_ORIGIN": "https://raceroom.z1rracing.com",
            "Z1RR_SMOKE_WEBSOCKET_PATH": "/ws/race/deploy-smoke",
            "Z1RR_DEPLOY_ACTOR": "test-operator",
            "RACETIME_ENV_FILE": "/etc/z1rr-racetime/racetime.env",
            "CADDY_ENV_FILE": "/etc/z1rr-racetime/caddy.env",
            "RACETIME_STATE_GENERATION": "qualification",
            "CADDY_STATE_VOLUME": "z1rr-racetime-integration-caddy",
        }
        self.config.write_text(
            "".join(f"{key}='{value}'\n" for key, value in values.items()),
            encoding="utf-8",
            newline="\n",
        )

    def _env(self, **updates):
        env = os.environ.copy()
        env.update(
            {
                "Z1RR_DEPLOY_CONFIG": self._posix(self.config),
                "Z1RR_TEST_DEPLOY_SCRIPT": self._posix(DEPLOY),
                "Z1RR_TEST_ROLLBACK_SCRIPT": self._posix(ROLLBACK),
                "Z1RR_TEST_FAKE_BIN": self._posix(self.bin),
                "FAKE_COMMAND_LOG": self._posix(self.log),
                "FAKE_BACKUP_MANIFEST": self._posix(self.backup_manifest),
                "FAKE_BACKUP_STATUS_DIR": self._posix(self.backup_status),
                "FAKE_EXPECTED_BACKUP_SHA": PRIOR_SHA,
                "FAKE_FLOCK_FAIL": "0",
                "FAKE_ACTIVE_RACES": "0",
                "PYTHON_BIN": self._posix(
                    ROOT / "venv" / "Scripts" / "python.exe"
                ),
            }
        )
        env.update(updates)
        return env

    def _run(self, script, arguments, *, env=None):
        return subprocess.run(
            [
                BASH,
                "-c",
                (
                    'fake_bin="$(cygpath -u "$Z1RR_TEST_FAKE_BIN" '
                    '2>/dev/null || printf %s "$Z1RR_TEST_FAKE_BIN")"; '
                    'export PATH="$fake_bin:$PATH"; hash -r; '
                    'exec "$@"'
                ),
                "deploy-test",
                self._posix(script),
                *arguments,
            ],
            cwd=ROOT,
            env=env or self._env(),
            text=True,
            capture_output=True,
            check=False,
        )

    def _deploy(self, manifest=None, *, env=None, extra=()):
        return self._run(
            DEPLOY,
            (
                "--environment",
                "integration",
                "--manifest",
                self._posix(manifest or self.target_path),
                *extra,
            ),
            env=env,
        )

    def _rollback(self, target=None, *, env=None, extra=()):
        return self._run(
            ROLLBACK,
            (
                "--environment",
                "integration",
                "--target-manifest",
                self._posix(target or self.prior_path),
                *extra,
            ),
            env=env,
        )

    def _current_release(self):
        return json.loads(
            (self.state / "current-release.json").read_text(encoding="utf-8")
        )["manifest"]["release_sha"]

    def _audit_pass_stages(self):
        audit = self.state / "deploy-audit.jsonl"
        if not audit.exists():
            return []
        return [
            entry["stage"]
            for entry in (
                json.loads(line)
                for line in audit.read_text(encoding="utf-8").splitlines()
            )
            if entry["status"] == "pass"
        ]

    def _reset_state(self):
        self._write_json(
            self.state / "current-release.json",
            release_record(self.prior_manifest),
        )
        for name in ("previous-release.json", "deploy-audit.jsonl"):
            path = self.state / name
            if path.exists():
                path.unlink()
        self.log.write_text("", encoding="utf-8")

    def test_deploy_runs_ordered_gates_and_promotes_only_after_smoke(self):
        result = self._deploy()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self._current_release(), TARGET_SHA)
        self.assertTrue((self.state / "previous-release.json").exists())
        self.assertEqual(
            self._audit_pass_stages(),
            [
                "lock",
                "preflight",
                "backup",
                "pull",
                "supply_chain",
                "migration_plan",
                "stop_writes",
                "migrate",
                "collectstatic",
                "start_services",
                "smoke",
                "promote",
                "unlock",
            ],
        )
        log = self.log.read_text(encoding="utf-8")
        self.assertLess(log.index("preflight "), log.index("backup "))
        self.assertLess(log.index("backup "), log.index("docker pull"))
        self.assertLess(log.index("cosign verify"), log.index("migrate --plan"))
        self.assertLess(log.index("stop web racebot"), log.index("run --rm migrate"))
        self.assertLess(log.index("collectstatic"), log.index("up -d web racebot"))
        self.assertLess(log.index("up -d web racebot"), log.index("smoke "))
        self.assertIn("state_generation=qualification", log)

    def test_injected_failure_at_every_boundary_never_promotes(self):
        stages = (
            "preflight",
            "backup",
            "pull",
            "supply_chain",
            "migration_plan",
            "stop_writes",
            "migrate",
            "collectstatic",
            "start_services",
            "smoke",
            "promote",
        )
        for stage in stages:
            with self.subTest(stage=stage):
                self._reset_state()
                result = self._deploy(
                    env=self._env(Z1RR_FAIL_STAGE=stage)
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self._current_release(), PRIOR_SHA)
                self.assertNotIn("promote", self._audit_pass_stages())
        self._reset_state()
        result = self._deploy(env=self._env(Z1RR_FAIL_STAGE="smoke"))
        self.assertNotEqual(result.returncode, 0)
        log = self.log.read_text(encoding="utf-8")
        self.assertIn(digest("1"), log)
        self.assertIn("up -d web racebot", log)

    def test_no_migration_release_keeps_write_services_running(self):
        no_migration = release_manifest(TARGET_SHA, "2")
        path = self.work / "no-migration.json"
        self._write_json(path, no_migration)
        result = self._deploy(path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        log = self.log.read_text(encoding="utf-8")
        self.assertNotIn("stop web racebot", log)
        self.assertNotIn("run --rm migrate", log)

    def test_lock_contention_fails_before_preflight(self):
        result = self._deploy(env=self._env(FAKE_FLOCK_FAIL="1"))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self._current_release(), PRIOR_SHA)
        log = self.log.read_text(encoding="utf-8")
        self.assertNotIn("preflight ", log)

    def test_code_only_and_reversible_rollbacks_are_manifest_driven(self):
        deployed = self._deploy()
        self.assertEqual(deployed.returncode, 0, deployed.stdout + deployed.stderr)
        self._write_backup_manifest(TARGET_SHA)
        env = self._env(FAKE_EXPECTED_BACKUP_SHA=TARGET_SHA)
        rolled_back = self._rollback(env=env)
        self.assertEqual(
            rolled_back.returncode,
            0,
            rolled_back.stdout + rolled_back.stderr,
        )
        self.assertEqual(self._current_release(), PRIOR_SHA)

        reversible = release_manifest(
            TARGET_SHA,
            "2",
            strategy="migrate",
            rollback_class="reversible",
            reverse_target="racetime.0082_externalidentity",
            minimum_rollback_digest=digest("1"),
        )
        self._write_json(
            self.state / "current-release.json",
            release_record(reversible),
        )
        self._write_json(
            self.state / "previous-release.json",
            release_record(self.prior_manifest),
        )
        self.log.write_text("", encoding="utf-8")
        reversed_result = self._rollback(env=env)
        self.assertEqual(
            reversed_result.returncode,
            0,
            reversed_result.stdout + reversed_result.stderr,
        )
        self.assertIn(
            "migrate racetime 0082_externalidentity --noinput",
            self.log.read_text(encoding="utf-8"),
        )

    def test_forward_fix_refuses_an_unapproved_target(self):
        forward_only = release_manifest(
            TARGET_SHA,
            "2",
            strategy="contract",
            rollback_class="forward-fix",
            forward_fix_release=FIX_SHA,
        )
        self._write_json(
            self.state / "current-release.json",
            release_record(forward_only),
        )
        self._write_json(
            self.state / "previous-release.json",
            release_record(self.prior_manifest),
        )
        result = self._rollback()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self._current_release(), TARGET_SHA)
        self.assertNotIn("migrate ", self.log.read_text(encoding="utf-8"))

    def test_rollback_active_race_requires_named_emergency_override(self):
        deployed = self._deploy()
        self.assertEqual(deployed.returncode, 0, deployed.stdout + deployed.stderr)
        self._write_backup_manifest(TARGET_SHA)
        blocked = self._rollback(
            env=self._env(
                FAKE_ACTIVE_RACES="1",
                FAKE_EXPECTED_BACKUP_SHA=TARGET_SHA,
            )
        )
        self.assertNotEqual(blocked.returncode, 0)
        allowed = self._rollback(
            env=self._env(
                FAKE_ACTIVE_RACES="1",
                FAKE_EXPECTED_BACKUP_SHA=TARGET_SHA,
            ),
            extra=("--emergency-change-id", "INC-2026-001"),
        )
        self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)
        self.assertIn(
            "--emergency-change-id INC-2026-001",
            self.log.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
