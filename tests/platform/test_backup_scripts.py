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
BACKUP = ROOT / "deploy" / "backup" / "backup.sh"
VERIFY = ROOT / "deploy" / "backup" / "verify.sh"
RESTORE_TEST = ROOT / "deploy" / "backup" / "restore-test.sh"
SCHEMA = ROOT / "deploy" / "backup" / "manifest.schema.json"
MANIFEST_MODULE = ROOT / "deploy" / "backup" / "manifest.py"
BACKUP_ENV = ROOT / "deploy" / "backup" / "backup.env.example"
SCHEDULED_BACKUP = ROOT / "deploy" / "backup" / "scheduled-backup.sh"
BACKUP_SERVICE = ROOT / "deploy" / "systemd" / "z1rr-racetime-backup.service"
BACKUP_TIMER = ROOT / "deploy" / "systemd" / "z1rr-racetime-backup.timer"
RESTORE_SERVICE = ROOT / "deploy" / "systemd" / "z1rr-racetime-restore-test.service"
RESTORE_TIMER = ROOT / "deploy" / "systemd" / "z1rr-racetime-restore-test.timer"
GIT_BASH = Path(r"C:\Program Files\Git\bin\bash.exe")
BASH = shutil.which("bash") or (str(GIT_BASH) if GIT_BASH.exists() else None)
RELEASE_SHA = "2" * 40
DIGEST = "sha256:" + "c" * 64


class BackupManifestContractTests(unittest.TestCase):
    def test_schema_requires_complete_secret_free_recovery_record(self):
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            set(schema["required"]),
            {
                "schema",
                "type",
                "started_at",
                "completed_at",
                "release_sha",
                "database",
                "source",
                "plaintext",
                "encrypted",
                "encryption",
                "verification",
                "object_storage",
                "tools",
                "retention",
            },
        )
        serialized = json.dumps(schema).lower()
        self.assertNotIn("password", serialized)
        self.assertNotIn("client_secret", serialized)
        self.assertNotIn("private_key", serialized)

    def test_manifest_validator_rejects_secrets_qualification_and_bad_hashes(self):
        spec = importlib.util.spec_from_file_location("z1rr_manifest", MANIFEST_MODULE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        valid = module.example_manifest()
        module.validate_manifest(valid, require_verified=True)

        mutations = []
        with_secret = json.loads(json.dumps(valid))
        with_secret["database"]["password"] = "bad"
        mutations.append(with_secret)
        qualification = json.loads(json.dumps(valid))
        qualification["object_storage"]["object"] = "qualification/database/x.age"
        mutations.append(qualification)
        bad_hash = json.loads(json.dumps(valid))
        bad_hash["encrypted"]["sha256"] = "nope"
        mutations.append(bad_hash)
        for candidate in mutations:
            with self.subTest(candidate=candidate), self.assertRaises(module.ManifestError):
                module.validate_manifest(candidate, require_verified=True)


class BackupScriptContractTests(unittest.TestCase):
    def test_backup_and_verify_declare_consistency_and_atomicity_controls(self):
        backup = BACKUP.read_text(encoding="utf-8")
        verify = VERIFY.read_text(encoding="utf-8")
        for token in (
            "--single-transaction",
            "--routines",
            "--events",
            "--triggers",
            "--hex-blob",
            "trap cleanup",
            "--auth instance_principal",
            "os object put",
            "os object head",
            "os object rename",
            "manifest.py",
            "verify.sh",
            "PRODUCTION_MEDIA_VOLUME",
            "PRODUCTION_CADDY_STATE_VOLUME",
        ):
            with self.subTest(token=token):
                self.assertIn(token, backup)
        self.assertIn("volume inspect", backup)
        for token in (
            "age --decrypt",
            "zstd --decompress",
            "mariadb-admin ping",
            "mariadb",
            "--network none",
            "tar -tf",
            "trap cleanup",
        ):
            with self.subTest(token=token):
                self.assertIn(token, verify)

    def test_restore_test_is_isolated_and_cannot_target_production(self):
        source = RESTORE_TEST.read_text(encoding="utf-8")
        for token in (
            "--database-manifest",
            "--media-manifest",
            "--caddy-manifest",
            "z1rr-restore-test-",
            "migrate --check",
            "User.objects",
            "Category.objects",
            "Race.objects",
            "Leaderboard",
            "--network none",
            "CADDY_STATE_VOLUME",
            "production replacement is forbidden",
        ):
            with self.subTest(token=token):
                self.assertIn(token, source)

        self.assertIn("volume inspect", source)
        self.assertIn("*/certificates/*", source)

    def test_schedules_enforce_rpo_retention_hardening_and_failure_status(self):
        scheduled = SCHEDULED_BACKUP.read_text(encoding="utf-8")
        backup_service = BACKUP_SERVICE.read_text(encoding="utf-8")
        backup_timer = BACKUP_TIMER.read_text(encoding="utf-8")
        restore_service = RESTORE_SERVICE.read_text(encoding="utf-8")
        restore_timer = RESTORE_TIMER.read_text(encoding="utf-8")
        restore_source = RESTORE_TEST.read_text(encoding="utf-8")

        self.assertIn("--type database", scheduled)
        self.assertIn("--type media", scheduled)
        self.assertIn("date -u +%H", scheduled)
        self.assertIn("retention.py", scheduled)
        self.assertIn("--apply", scheduled)
        self.assertIn("BACKUP_ALERT_HOOK", scheduled)
        self.assertIn("failure", scheduled)
        self.assertIn("BACKUP_ALERT_HOOK", restore_source)
        self.assertIn("trap - EXIT", scheduled)
        self.assertIn("restore-test-failure", restore_source)
        self.assertIn("--type production-caddy-state", scheduled)
        self.assertIn("--reason renewal", scheduled)

        self.assertIn("OnCalendar=*-*-* 00,06,12,18:00:00", backup_timer)
        self.assertIn("Persistent=true", backup_timer)
        self.assertIn("RandomizedDelaySec=15m", backup_timer)
        self.assertIn("OnCalendar=*-01,04,07,10-01 03:00:00", restore_timer)
        self.assertIn("RandomizedDelaySec=7d", restore_timer)

        for unit in (backup_service, restore_service):
            for token in (
                "EnvironmentFile=/etc/z1rr-racetime/backup.env",
                "UMask=0077",
                "NoNewPrivileges=true",
                "ProtectSystem=strict",
                "ProtectHome=true",
                "PrivateTmp=true",
                "TimeoutStartSec=",
                "ReadWritePaths=",
            ):
                with self.subTest(unit=unit[:30], token=token):
                    self.assertIn(token, unit)
        self.assertIn("scheduled-backup.sh", backup_service)
        self.assertIn("restore-test.sh", restore_service)

    def test_environment_template_is_complete_and_contains_no_secrets(self):
        source = BACKUP_ENV.read_text(encoding="utf-8")
        keys = {
            line.split("=", 1)[0]
            for line in source.splitlines()
            if line and not line.startswith("#") and "=" in line
        }
        required = {
            "OCI_NAMESPACE",
            "OCI_BUCKET",
            "OCI_PREFIX",
            "AGE_RECIPIENT",
            "AGE_IDENTITY_FILE",
            "AGE_KEY_ID",
            "BACKUP_SCRATCH_ROOT",
            "BACKUP_STATUS_DIR",
            "RACETIME_COMPOSE_FILE",
            "RACETIME_ENV_FILE",
            "CADDY_ENV_FILE",
            "RACETIME_RELEASE_SHA",
            "RACETIME_IMAGE",
            "RACETIME_IMAGE_DIGEST",
            "RACETIME_MAINTENANCE_IMAGE",
            "RACETIME_MAINTENANCE_IMAGE_DIGEST",
            "PRODUCTION_DB_VOLUME",
            "PRODUCTION_MEDIA_VOLUME",
            "PRODUCTION_SECRET_VOLUME",
            "PRODUCTION_CADDY_STATE_VOLUME",
            "MARIADB_VERIFY_IMAGE",
            "ARCHIVE_HELPER_IMAGE",
            "CADDY_IMAGE",
            "DB_SCHEMA_NAME",
            "RESTORE_DATABASE_MANIFEST",
            "RESTORE_MEDIA_MANIFEST",
            "RESTORE_CADDY_MANIFEST",
        }
        self.assertEqual(required - keys, set())
        lowered = source.lower()
        self.assertNotIn("age-secret-key-", lowered)
        self.assertNotIn("password=", lowered)
        self.assertNotIn("client_secret=", lowered)
        self.assertIn("MARIADB_VERIFY_IMAGE=mariadb:11.4.12@", source)
        self.assertIn("CADDY_IMAGE=caddy:2.11.4-alpine@", source)


@unittest.skipUnless(BASH, "bash is required for backup behavior tests")
class BackupScriptBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix="backup-", dir=ROOT / "tests" / "platform"
        )
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.bin = self.work / "bin"
        self.bin.mkdir()
        self.scratch = self.work / "scratch"
        self.scratch.mkdir()
        self.status = self.work / "status"
        self.status.mkdir()
        self.store = self.work / "object-store"
        self.store.mkdir()
        self.volume_source = self.work / "volume"
        self.volume_source.mkdir()
        (self.volume_source / "sample.txt").write_text("sample media\n", encoding="utf-8")
        self.identity = self.work / "age-identity.txt"
        self.identity.write_text("TEST_PRIVATE_IDENTITY_CANARY\n", encoding="utf-8")
        self.log = self.work / "commands.log"
        self._install_fakes()
        self.config = self.work / "backup.env"
        self._write_config()

    def _posix(self, path):
        resolved = path.resolve()
        value = resolved.as_posix()
        if os.name == "nt":
            drive = resolved.drive.rstrip(":").lower()
            remainder = value[len(resolved.drive):].lstrip("/")
            return f"/{drive}/{remainder}"
        return value

    def _write_executable(self, path, source):
        path.write_text(source, encoding="utf-8", newline="\n")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def _install_fakes(self):
        self._write_executable(
            self.bin / "stat",
            "#!/usr/bin/env bash\nprintf '%s\\n' \"${FAKE_STAT_VALUE:-0}\"\n",
        )
        self._write_executable(
            self.bin / "df",
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                printf '%s\\n' 'Filesystem 1024-blocks Used Available Capacity Mounted on'
                printf 'fake 10000000 1 %s 1%% /\\n' "${FAKE_FREE_KB:-9000000}"
                """
            ),
        )
        self._write_executable(
            self.bin / "docker",
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                set -eu
                printf 'docker %s\\n' "$*" >> "$FAKE_COMMAND_LOG"
                [[ "$*" == --version ]] && { printf '%s\\n' 'Docker 29.1.3'; exit 0; }
                case "$*" in
                  *"mariadb-dump"*)
                    printf '%s\\n' 'CREATE DATABASE racetime;' 'CREATE TABLE racetime.sample (id int);' 'INSERT INTO racetime.sample VALUES (1);'
                    ;;
                  *"showmigrations --plan"*) printf '%s\\n' '[X]  racetime.0082_externalidentity' ;;
                  *" tar "*" -cf -"*) tar -C "$FAKE_VOLUME_SOURCE" -cf - . ;;
                  *" tar "*" -xf "*) exit 0 ;;
                  *"volume inspect"*) exit "${FAKE_VOLUME_INSPECT_FAIL:-0}" ;;
                  "run "*) printf '%s\\n' verifier-container ;;
                  *"mariadb-admin ping"*) exit 0 ;;
                  *"exec -i "*" mariadb")
                    cat >/dev/null
                    exit "${FAKE_DB_IMPORT_FAIL:-0}"
                    ;;
                  *"rm -f"*) exit 0 ;;
                  *) exit 0 ;;
                esac
                """
            ),
        )
        self._write_executable(
            self.bin / "zstd",
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                set -eu
                printf 'zstd %s\\n' "$*" >> "$FAKE_COMMAND_LOG"
                [[ "$*" == --version ]] && { printf '%s\\n' 'zstd 1.5.7'; exit 0; }
                input=''
                for arg in "$@"; do [[ "$arg" == -* ]] || input="$arg"; done
                [[ -n "$input" ]] && cat "$input" || cat
                """
            ),
        )
        self._write_executable(
            self.bin / "age",
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                set -eu
                printf 'age %s\\n' "$*" >> "$FAKE_COMMAND_LOG"
                [[ "$*" == --version ]] && { printf '%s\\n' 'age 1.2.1'; exit 0; }
                if [[ " $* " == *" --decrypt "* ]]; then
                  [[ "${FAKE_AGE_DECRYPT_FAIL:-0}" == 1 ]] && exit 8
                  cat "${!#}"
                  exit 0
                fi
                output=''
                input="${!#}"
                while (($#)); do
                  [[ "$1" == --output ]] && { output="$2"; shift 2; continue; }
                  shift
                done
                cp "$input" "$output"
                """
            ),
        )
        self._write_executable(
            self.bin / "oci",
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                set -eu
                printf 'oci %s\\n' "$*" >> "$FAKE_COMMAND_LOG"
                [[ "$*" == --version ]] && { printf '%s\\n' 'oci 3.90.3'; exit 0; }
                op="$3"
                [[ "${FAKE_OCI_FAIL_ON:-}" == "$op" ]] && exit 9
                name=''; source_name=''; new_name=''; file=''; query=''; metadata=''
                while (($#)); do
                  case "$1" in
                    --name|--object-name) name="$2"; shift 2 ;;
                    --source-name) source_name="$2"; shift 2 ;;
                    --new-name) new_name="$2"; shift 2 ;;
                    --file) file="$2"; shift 2 ;;
                    --query) query="$2"; shift 2 ;;
                    --metadata) metadata="$2"; shift 2 ;;
                    *) shift ;;
                  esac
                done
                safe() { printf '%s' "${1//\\//__}"; }
                case "$op" in
                  put)
                    cp "$file" "$FAKE_OCI_STORE/$(safe "$name")"
                    printf '%s' "$metadata" | sed -n 's/.*z1rr-sha256[^0-9a-f]*\\([0-9a-f]\\{64\\}\\).*/\\1/p' > "$FAKE_OCI_STORE/$(safe "$name").sha"
                    ;;
                  head)
                    target="$FAKE_OCI_STORE/$(safe "$name")"
                    [[ -f "$target" ]] || exit 4
                    if [[ "$query" == *content-length* ]]; then wc -c < "$target" | tr -d ' '; else cat "$target.sha"; fi
                    ;;
                  rename)
                    mv "$FAKE_OCI_STORE/$(safe "$source_name")" "$FAKE_OCI_STORE/$(safe "$new_name")"
                    mv "$FAKE_OCI_STORE/$(safe "$source_name").sha" "$FAKE_OCI_STORE/$(safe "$new_name").sha"
                    ;;
                  delete)
                    rm -f "$FAKE_OCI_STORE/$(safe "$name")" "$FAKE_OCI_STORE/$(safe "$name").sha"
                    ;;
                  get) cp "$FAKE_OCI_STORE/$(safe "$name")" "$file" ;;
                  *) exit 3 ;;
                esac
                """
            ),
        )

    def _write_config(self, **overrides):
        values = {
            "OCI_NAMESPACE": "testnamespace",
            "OCI_BUCKET": "z1rr-backups",
            "OCI_PREFIX": "production",
            "AGE_RECIPIENT": "age1testrecipient",
            "AGE_IDENTITY_FILE": self._posix(self.identity),
            "AGE_KEY_ID": "age-test-key-v1",
            "BACKUP_SCRATCH_ROOT": self._posix(self.scratch),
            "BACKUP_STATUS_DIR": self._posix(self.status),
            "RACETIME_COMPOSE_FILE": self._posix(ROOT / "deploy" / "compose.production.yml"),
            "PRODUCTION_MEDIA_VOLUME": "z1rr-racetime-production-media",
            "PRODUCTION_CADDY_STATE_VOLUME": "caddy-production",
            "MARIADB_VERIFY_IMAGE": f"mariadb:11.4@{DIGEST}",
            "ARCHIVE_HELPER_IMAGE": f"alpine:3.22@{DIGEST}",
            "CADDY_IMAGE": f"caddy:2.11@{DIGEST}",
            "CADDY_ENV_FILE": self._posix(self.config),
            "PRODUCTION_SECRET_VOLUME": "z1rr-racetime-production-secrets",
            "PRODUCTION_DB_VOLUME": "z1rr-racetime-production-db",
            "DB_SCHEMA_NAME": "racetime",
            "MIN_BACKUP_FREE_KB": "1000",
        }
        values.update(overrides)
        self.config.write_text(
            "".join(f"{key}='{value}'\n" for key, value in values.items()),
            encoding="utf-8",
            newline="\n",
        )

    def _env(self, **updates):
        env = os.environ.copy()
        env.update(
            {
                "Z1RR_BACKUP_CONFIG": self._posix(self.config),
                "FAKE_COMMAND_LOG": self._posix(self.log),
                "FAKE_OCI_STORE": self._posix(self.store),
                "FAKE_VOLUME_SOURCE": self._posix(self.volume_source),
                "PYTHON_BIN": self._posix(ROOT / "venv" / "Scripts" / "python.exe"),
                "Z1RR_TEST_FAKE_BIN": self._posix(self.bin),
                "Z1RR_TEST_BACKUP_SCRIPT": self._posix(BACKUP),
                "Z1RR_TEST_RESTORE_SCRIPT": self._posix(RESTORE_TEST),
            }
        )
        env.update(updates)
        return env

    def _run(self, backup_type, *, extra_args=(), env=None):
        command = [
            BASH,
            "-c",
            (
                'fake_bin="$(cygpath -u "$Z1RR_TEST_FAKE_BIN" 2>/dev/null || printf %s "$Z1RR_TEST_FAKE_BIN")"; '
                'export PATH="$fake_bin:$PATH"; hash -r; '
                'exec "$Z1RR_TEST_BACKUP_SCRIPT" "$@"'
            ),
            "backup-test",
            "--type",
            backup_type,
            "--release-sha",
            RELEASE_SHA,
            *extra_args,
        ]
        return subprocess.run(
            command,
            cwd=ROOT,
            env=env or self._env(),
            text=True,
            capture_output=True,
            check=False,
        )

    def _last_manifest(self, backup_type):
        path = self.status / f"last-{backup_type}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def _create_restore_manifests(self):
        manifests = {}
        for backup_type, extra_args in (
            ("database", ()),
            ("media", ()),
            ("production-caddy-state", ("--reason", "initial-issuance")),
        ):
            result = self._run(backup_type, extra_args=extra_args)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            manifests[backup_type] = self._last_manifest(backup_type)[
                "object_storage"
            ]["manifest_object"]
        return manifests

    def _run_restore(self, manifests, *, env=None):
        command = [
            BASH,
            "-c",
            (
                'fake_bin="$(cygpath -u "$Z1RR_TEST_FAKE_BIN" 2>/dev/null || printf %s "$Z1RR_TEST_FAKE_BIN")"; '
                'export PATH="$fake_bin:$PATH"; hash -r; '
                'exec "$Z1RR_TEST_RESTORE_SCRIPT" "$@"'
            ),
            "restore-test",
            "--database-manifest",
            manifests["database"],
            "--media-manifest",
            manifests["media"],
            "--caddy-manifest",
            manifests["production-caddy-state"],
            "--release-sha",
            RELEASE_SHA,
        ]
        return subprocess.run(
            command,
            cwd=ROOT,
            env=env or self._env(),
            text=True,
            capture_output=True,
            check=False,
        )

    def test_database_backup_verifies_restores_and_atomically_uploads(self):
        result = self._run("database")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest = self._last_manifest("database")
        self.assertEqual(manifest["verification"]["result"], "verified")
        self.assertEqual(manifest["database"]["schema"], "racetime")
        self.assertIn("racetime.0082_externalidentity", manifest["database"]["migrations"])
        self.assertTrue(manifest["object_storage"]["object"].startswith("production/database/"))
        self.assertNotIn("TEST_PRIVATE_IDENTITY_CANARY", json.dumps(manifest))
        log = self.log.read_text(encoding="utf-8")
        self.assertIn("--single-transaction --routines --events --triggers --hex-blob", log)
        self.assertIn("--network none", log)
        self.assertIn("mariadb-admin ping", log)
        self.assertIn("--auth instance_principal", log)
        self.assertIn("os object rename", log)
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_media_uses_only_declared_read_only_volume(self):
        result = self._run("media")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest = self._last_manifest("media")
        self.assertEqual(manifest["source"]["volume"], "z1rr-racetime-production-media")
        log = self.log.read_text(encoding="utf-8")
        self.assertIn("z1rr-racetime-production-media:/source:ro", log)
        self.assertNotIn("qualification", log)

    def test_caddy_requires_allowed_reason_and_exact_production_volume(self):
        missing_reason = self._run("production-caddy-state")
        self.assertNotEqual(missing_reason.returncode, 0)
        passed = self._run(
            "production-caddy-state", extra_args=("--reason", "renewal")
        )
        self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)
        self.assertEqual(
            self._last_manifest("production-caddy-state")["source"]["volume"],
            "caddy-production",
        )
        self._write_config(PRODUCTION_CADDY_STATE_VOLUME="caddy-qualification")
        rejected = self._run(
            "production-caddy-state", extra_args=("--reason", "renewal")
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("qualification", rejected.stderr)

    def test_missing_named_volume_fails_without_creating_or_marking_a_backup(self):
        result = self._run(
            "media", env=self._env(FAKE_VOLUME_INSPECT_FAIL="1")
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("source volume unavailable", result.stderr)
        self.assertFalse((self.status / "last-media.json").exists())
        self.assertNotIn("docker run", self.log.read_text(encoding="utf-8"))

    def test_restore_test_downloads_into_unique_isolated_stack_without_acme(self):
        manifests = self._create_restore_manifests()
        result = self._run_restore(manifests)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("RESTORE_TEST=PASS", result.stdout)
        log = self.log.read_text(encoding="utf-8")
        self.assertIn("--project-name z1rr-restore-test-", log)
        self.assertIn("python manage.py migrate --check", log)
        self.assertIn("python manage.py shell -c", log)
        self.assertIn("--network none", log)
        self.assertNotIn("z1rr-racetime-production-media:/target", log)
        status = json.loads(
            (self.status / "restore-test-status.json").read_text(encoding="utf-8")
        )
        self.assertEqual(status["status"], "pass")
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_restore_failure_writes_status_and_invokes_alert_hook(self):
        manifests = self._create_restore_manifests()
        alert_log = self.work / "alerts.log"
        alert_hook = self.work / "alert-hook"
        self._write_executable(
            alert_hook,
            "#!/usr/bin/env bash\nprintf '%s %s\\n' \"$1\" \"$2\" > \"$FAKE_ALERT_LOG\"\n",
        )
        self._write_config(BACKUP_ALERT_HOOK=self._posix(alert_hook))

        result = self._run_restore(
            manifests,
            env=self._env(
                FAKE_AGE_DECRYPT_FAIL="1",
                FAKE_ALERT_LOG=self._posix(alert_log),
            ),
        )
        self.assertNotEqual(result.returncode, 0)
        status = json.loads(
            (self.status / "restore-test-status.json").read_text(encoding="utf-8")
        )
        self.assertEqual(status["status"], "failure")
        self.assertTrue((self.status / "restore-test-failure").exists())
        self.assertEqual(alert_log.read_text(encoding="utf-8").strip(), "restore-test failure")

    def test_decrypt_db_upload_and_disk_failures_never_mark_complete(self):
        cases = (
            ({"FAKE_AGE_DECRYPT_FAIL": "1"}, "verification failed"),
            ({"FAKE_DB_IMPORT_FAIL": "1"}, "verification failed"),
            ({"FAKE_OCI_FAIL_ON": "put"}, "Object Storage"),
            ({"FAKE_FREE_KB": "999"}, "disk"),
        )
        for additions, message in cases:
            with self.subTest(additions=additions):
                for path in self.status.glob("*"):
                    path.unlink()
                result = self._run("database", env=self._env(**additions))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertFalse((self.status / "last-database.json").exists())
                self.assertEqual(list(self.scratch.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
