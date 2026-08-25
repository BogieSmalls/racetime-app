"""Behavioral coverage for the PowerShell Compose health parser."""

from pathlib import Path
import shutil
import subprocess
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
POWERSHELL_TEST = REPOSITORY_ROOT / "tests" / "e2e" / "integration_health.Tests.ps1"


class IntegrationHealthPowerShellTests(unittest.TestCase):
    def test_dual_format_parser_and_exact_health_gate(self):
        powershell = shutil.which("pwsh")
        self.assertIsNotNone(powershell, "PowerShell 7 is required for integration tooling")
        result = subprocess.run(
            [powershell, "-NoProfile", "-File", str(POWERSHELL_TEST)],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PowerShell integration health tests: 17 passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
