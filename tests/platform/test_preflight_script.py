import hashlib
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "scripts" / "preflight.sh"
GIT_BASH = Path(r"C:\Program Files\Git\bin\bash.exe")
BASH = shutil.which("bash") or (str(GIT_BASH) if GIT_BASH.exists() else None)
RELEASE_SHA = "1" * 40
IMAGE_DIGEST = "sha256:" + "a" * 64
MAINTENANCE_DIGEST = "sha256:" + "b" * 64


class PreflightScriptContractTests(unittest.TestCase):
    def test_script_declares_every_authoritative_boundary(self):
        source = SCRIPT.read_text(encoding="utf-8")
        required = (
            "Z1RR_G1_ACTIVATION_RECORD",
            "Z1RR_G2_EVIDENCE_PATH",
            "Z1RR_G2_EVIDENCE_SHA256",
            "RACETIME_IMAGE_DIGEST",
            "RACETIME_MAINTENANCE_IMAGE_DIGEST",
            "deploy/validate-config.py",
            "MIN_FREE_DISK_KB",
            "NTPSynchronized",
            "compose",
            "ps --status running --services",
            "docker inspect",
            "deployment_preflight",
            "Z1RR_BACKUP_SCRIPT",
            "Z1RR_BACKUP_CONFIG",
            "--emergency-change-id",
            "--allow-active-races",
        )
        for token in required:
            with self.subTest(token=token):
                self.assertIn(token, source)


@unittest.skipUnless(BASH, "bash is required for shell behavior tests")
class PreflightScriptBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix="preflight-", dir=ROOT / "tests" / "platform"
        )
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.bin = self.work / "bin"
        self.bin.mkdir()
        self.docker_log = self.work / "docker.log"
        self.backup_script = self.work / "backup.sh"
        self.backup_config = self.work / "backup.env"
        self._write_executable(self.backup_script, "#!/usr/bin/env bash\nexit 0\n")
        self.backup_config.write_text("BUCKET=test-only\n", encoding="utf-8")
        self._install_fakes()

    def _write_executable(self, path, source):
        path.write_text(source, encoding="utf-8", newline="\n")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def _install_fakes(self):
        self._write_executable(
            self.bin / "docker",
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                set -eu
                printf '%s\\n' "$*" >> "$FAKE_DOCKER_LOG"
                case "$*" in
                  *" config --quiet") exit "${FAKE_CONFIG_EXIT:-0}" ;;
                  *" ps --status running --services")
                    printf '%s\\n' ${FAKE_DOCKER_SERVICES:-caddy web racebot db redis}
                    ;;
                  *" ps -q "*)
                    service="${!#}"
                    printf 'container-%s\\n' "$service"
                    ;;
                  "inspect --format "*)
                    service="${!#}"
                    service="${service#container-}"
                    [[ "$service" == "${FAKE_UNHEALTHY_SERVICE:-}" ]] \
                      && printf '%s\\n' unhealthy || printf '%s\\n' healthy
                    ;;
                  *" exec -T web python manage.py deployment_preflight"*)
                    printf '%s\\n' '{"schema":1,"status":"pass"}'
                    exit "${FAKE_PREFLIGHT_EXIT:-0}"
                    ;;
                  *) exit 91 ;;
                esac
                """
            ),
        )
        self._write_executable(
            self.bin / "timedatectl",
            "#!/usr/bin/env bash\nprintf '%s\\n' \"${FAKE_NTP:-yes}\"\n",
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
            self.bin / "stat",
            "#!/usr/bin/env bash\nprintf '%s\\n' \"${FAKE_UID:-0}\"\n",
        )
        self._write_executable(
            self.bin / "fake-python",
            "#!/usr/bin/env bash\nexit \"${FAKE_VALIDATOR_EXIT:-0}\"\n",
        )
        for name in ("age", "zstd", "oci"):
            self._write_executable(
                self.bin / name,
                "#!/usr/bin/env bash\nexit 0\n",
            )

    def _posix(self, path):
        return path.resolve().as_posix()

    def _base_env(self):
        env = os.environ.copy()
        env.update(
            {
                "PATH": str(self.bin) + os.pathsep + env.get("PATH", ""),
                "FAKE_DOCKER_LOG": self._posix(self.docker_log),
                "PYTHON_BIN": "fake-python",
                "RACETIME_IMAGE": f"ghcr.io/z1rr/racetime:{RELEASE_SHA}",
                "RACETIME_IMAGE_DIGEST": IMAGE_DIGEST,
                "RACETIME_MAINTENANCE_IMAGE": (
                    f"ghcr.io/z1rr/racetime-maintenance:{RELEASE_SHA}"
                ),
                "RACETIME_MAINTENANCE_IMAGE_DIGEST": MAINTENANCE_DIGEST,
                "Z1RR_BACKUP_SCRIPT": self._posix(self.backup_script),
                "Z1RR_BACKUP_CONFIG": self._posix(self.backup_config),
                "MIN_FREE_DISK_KB": "1000",
            }
        )
        return env

    def _run(self, environment="integration", extra_args=(), env=None):
        shell_env = env or self._base_env()
        shell_env["Z1RR_TEST_FAKE_BIN"] = self._posix(self.bin)
        shell_env["Z1RR_TEST_PREFLIGHT_SCRIPT"] = self._posix(SCRIPT)
        command = [
            BASH,
            "-c",
            (
                'fake_bin="$(cygpath -u "$Z1RR_TEST_FAKE_BIN")"; '
                'export PATH="$fake_bin:$PATH"; hash -r; '
                'exec "$Z1RR_TEST_PREFLIGHT_SCRIPT" "$@"'
            ),
            "preflight-test",
            "--environment",
            environment,
            "--release-sha",
            RELEASE_SHA,
            *extra_args,
        ]
        return subprocess.run(
            command,
            cwd=ROOT,
            env=shell_env,
            text=True,
            capture_output=True,
            check=False,
        )

    def _production_config(self, evidence_content="qualified\n"):
        activation = self.work / "activation.md"
        evidence = self.work / "evidence.json"
        config = self.work / "preflight.env"
        activation.write_text("Plan B activated\n", encoding="utf-8")
        evidence.write_text(evidence_content, encoding="utf-8")
        digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
        config.write_text(
            "\n".join(
                (
                    f"Z1RR_G1_ACTIVATION_RECORD='{self._posix(activation)}'",
                    f"Z1RR_G2_EVIDENCE_PATH='{self._posix(evidence)}'",
                    f"Z1RR_G2_EVIDENCE_SHA256='{digest}'",
                    "",
                )
            ),
            encoding="utf-8",
            newline="\n",
        )
        return config, evidence

    def test_integration_runs_every_local_preflight_and_passes(self):
        result = self._run()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PREFLIGHT=PASS", result.stdout)
        docker_calls = self.docker_log.read_text(encoding="utf-8")
        self.assertIn("config --quiet", docker_calls)
        self.assertIn("ps --status running --services", docker_calls)
        self.assertIn(
            "exec -T web python manage.py deployment_preflight --json",
            docker_calls,
        )

    def test_production_requires_root_owned_activation_and_hashed_evidence(self):
        missing = self._run(environment="production")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("root-owned preflight config", missing.stderr)

        config, _ = self._production_config()
        env = self._base_env()
        env["Z1RR_PREFLIGHT_CONFIG"] = self._posix(config)
        passed = self._run(environment="production", env=env)
        self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)

    def test_production_rejects_changed_evidence(self):
        config, evidence = self._production_config()
        evidence.write_text("changed after qualification\n", encoding="utf-8")
        env = self._base_env()
        env["Z1RR_PREFLIGHT_CONFIG"] = self._posix(config)

        result = self._run(environment="production", env=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("evidence hash mismatch", result.stderr)

    def test_ambient_active_race_override_is_rejected(self):
        env = self._base_env()
        env["Z1RR_ALLOW_ACTIVE_RACES"] = "1"

        result = self._run(env=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("emergency-change-id", result.stderr)
        self.assertFalse(self.docker_log.exists())

    def test_emergency_id_is_audited_and_narrowly_forwarded(self):
        change_id = "INC-20260823-001"
        result = self._run(extra_args=("--emergency-change-id", change_id))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"emergency_change_id={change_id}", result.stdout)
        docker_calls = self.docker_log.read_text(encoding="utf-8")
        self.assertIn("deployment_preflight --json --allow-active-races", docker_calls)

    def test_config_stack_time_disk_and_authoritative_failures_stop(self):
        cases = (
            ({"FAKE_VALIDATOR_EXIT": "2"}, "configuration validation failed"),
            ({"FAKE_CONFIG_EXIT": "2"}, "Compose configuration invalid"),
            ({"FAKE_NTP": "no"}, "time synchronization unavailable"),
            ({"FAKE_FREE_KB": "999"}, "insufficient disk headroom"),
            ({"FAKE_DOCKER_SERVICES": "caddy web db redis"}, "service not running: racebot"),
            ({"FAKE_UNHEALTHY_SERVICE": "web"}, "service unhealthy: web"),
            ({"FAKE_PREFLIGHT_EXIT": "2"}, "authoritative application preflight failed"),
        )
        for additions, message in cases:
            with self.subTest(additions=additions):
                if self.docker_log.exists():
                    self.docker_log.unlink()
                env = self._base_env()
                env.update(additions)
                result = self._run(env=env)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)


if __name__ == "__main__":
    unittest.main()
