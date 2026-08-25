"""Contract tests for the repository's narrowly scoped Gitleaks exception."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / ".gitleaks.toml"
ALLOWED_COMMIT = "b5093119e17327e649a7626f86cee102cbf6c27e"
ALLOWED_PATH = r"^deploy/env/ci\.env$"
ALLOWED_MATCH = (
    r"^RACETIME_THROTTLE_HMAC_KEY="
    r"(?:[A-Za-z0-9+/]{32}|[A-Za-z0-9+/]{43}=)$"
)


class GitleaksPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gitleaks = os.environ.get("GITLEAKS_BIN") or shutil.which("gitleaks")
        if not cls.gitleaks:
            if os.environ.get("REQUIRE_GITLEAKS_TESTS") == "1":
                raise RuntimeError("GITLEAKS_BIN or gitleaks on PATH is required")
            raise unittest.SkipTest("gitleaks is not available")

    def test_exception_is_exact_and_conjunctive(self) -> None:
        config = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(config.get("extend"), {"useDefault": True})
        self.assertEqual(
            config.get("rules"),
            [
                {
                    "id": "generic-api-key",
                    "allowlists": [
                        {
                            "description": "Known non-production CI throttle HMAC fixture",
                            "condition": "AND",
                            "commits": [ALLOWED_COMMIT],
                            "paths": [ALLOWED_PATH],
                            "regexTarget": "match",
                            "regexes": [ALLOWED_MATCH],
                        }
                    ],
                }
            ],
        )

    def test_real_gitleaks_requires_every_exception_dimension(self) -> None:
        fixture_line = (ROOT / "deploy" / "env" / "ci.env").read_text(
            encoding="utf-8"
        ).splitlines()[12]
        fixture_name, allowed_value = fixture_line.split("=", 1)
        self.assertEqual(fixture_name, "RACETIME_THROTTLE_HMAC_KEY")
        self.assertRegex(
            f"RACETIME_THROTTLE_HMAC_KEY={allowed_value}", ALLOWED_MATCH
        )

        self.assertEqual(
            self._scan_fixture(
                {"deploy/env/ci.env": f"RACETIME_THROTTLE_HMAC_KEY={allowed_value}\n"},
                allow_fixture_commit=False,
                use_policy=False,
            ),
            1,
            "the known fixture must be detected without the narrow exception",
        )

        self.assertEqual(
            self._scan_fixture(
                {"deploy/env/ci.env": f"RACETIME_THROTTLE_HMAC_KEY={allowed_value}\n"},
                allow_fixture_commit=True,
            ),
            0,
            "the single exact CI fixture must be allowlisted",
        )
        self.assertEqual(
            self._scan_fixture(
                {
                    "deploy/env/ci.env":
                        f"RACETIME_THROTTLE_HMAC_KEY={allowed_value[:-4]}\n"
                },
                allow_fixture_commit=True,
            ),
            1,
            "a different value shape under the same key/path/commit must still fail",
        )
        self.assertEqual(
            self._scan_fixture(
                {"deploy/env/ci.env": f"SECONDARY_SERVICE_API_KEY={allowed_value}\n"},
                allow_fixture_commit=True,
            ),
            1,
            "a different key in the same path and commit must still fail",
        )
        self.assertEqual(
            self._scan_fixture(
                {"elsewhere/ci.env": f"RACETIME_THROTTLE_HMAC_KEY={allowed_value}\n"},
                allow_fixture_commit=True,
            ),
            1,
            "the same fixture-shaped line in another path must still fail",
        )
        self.assertEqual(
            self._scan_fixture(
                {"deploy/env/ci.env": f"RACETIME_THROTTLE_HMAC_KEY={allowed_value}\n"},
                allow_fixture_commit=False,
            ),
            1,
            "the same fixture-shaped line in another commit must still fail",
        )

    def _scan_fixture(
        self,
        files: dict[str, str],
        *,
        allow_fixture_commit: bool,
        use_policy: bool = True,
    ) -> int:
        with tempfile.TemporaryDirectory(prefix="racetime-gitleaks-") as temp:
            repo = Path(temp)
            self._run(repo, "git", "init", "--quiet")
            self._run(repo, "git", "config", "user.name", "Gitleaks Policy Test")
            self._run(repo, "git", "config", "user.email", "gitleaks-test@example.invalid")
            for relative, content in files.items():
                target = repo / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            self._run(repo, "git", "add", ".")
            self._run(repo, "git", "commit", "--quiet", "-m", "fixture")
            fixture_commit = self._run(repo, "git", "rev-parse", "HEAD").stdout.strip()

            if use_policy:
                config_text = CONFIG.read_text(encoding="utf-8")
                if allow_fixture_commit:
                    config_text = config_text.replace(ALLOWED_COMMIT, fixture_commit, 1)
            else:
                config_text = "[extend]\nuseDefault = true\n"
            fixture_config = repo / ".gitleaks-policy-test.toml"
            fixture_config.write_text(config_text, encoding="utf-8")

            result = subprocess.run(
                [
                    str(self.gitleaks),
                    "git",
                    str(repo),
                    "--config",
                    str(fixture_config),
                    "--no-banner",
                    "--redact=100",
                    "--exit-code",
                    "1",
                ],
                cwd=repo,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertIn(
                result.returncode,
                (0, 1),
                f"gitleaks failed unexpectedly: {result.stderr}",
            )
            return result.returncode

    @staticmethod
    def _run(cwd: Path, *command: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
