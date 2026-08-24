from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
RUNBOOKS = ROOT / "docs" / "runbooks"
EXPECTED = {
    "deploy.md", "rollback.md", "backup-restore.md", "vm-loss.md",
    "identity-recovery.md", "access-review.md", "incidents.md",
    "status-comms.md", "qualification.md", "cutover.md", "monitoring.md",
}
HEADINGS = {
    "Purpose", "Prerequisites", "Roles", "Inputs and exact commands",
    "Safety preflight", "Normal steps", "Verification",
    "Rollback and escalation", "Evidence fields", "Secret handling",
    "Last reviewed",
}
LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


class RunbookContractTests(unittest.TestCase):
    def test_complete_runbook_set_has_executable_contract_sections(self):
        self.assertTrue(EXPECTED.issubset({path.name for path in RUNBOOKS.glob("*.md")}))
        for name in sorted(EXPECTED):
            with self.subTest(runbook=name):
                path = RUNBOOKS / name
                text = path.read_text(encoding="utf-8")
                headings = {
                    line.removeprefix("## ").strip()
                    for line in text.splitlines()
                    if line.startswith("## ")
                }
                self.assertTrue(HEADINGS.issubset(headings), HEADINGS - headings)
                self.assertIn("```", text)
                self.assertRegex(text, r"(?i)primary technical operator")
                self.assertRegex(text, r"(?i)(stop|refus|fail|block)")
                self.assertRegex(text, r"(?i)(UTC|timestamp)")
                self.assertRegex(text, r"(?i)(secret|credential|token)")
                self.assertRegex(text, r"Last reviewed:\s*2026-08-24")

    def test_every_relative_markdown_link_resolves_without_traversal(self):
        for path in sorted(RUNBOOKS.glob("*.md")):
            for target in LINK.findall(path.read_text(encoding="utf-8")):
                target = target.split("#", 1)[0]
                if not target or "://" in target or target.startswith("mailto:"):
                    continue
                resolved = (path.parent / target).resolve()
                self.assertTrue(str(resolved).startswith(str(ROOT.resolve())))
                self.assertTrue(resolved.exists(), f"broken link: {path} -> {target}")

    def test_vm_loss_covers_sealed_and_account_level_recovery(self):
        text = (RUNBOOKS / "vm-loss.md").read_text(encoding="utf-8")
        for token in (
            "sealed", "recovery custodian", "OCI tenancy", "GitHub", "GHCR",
            "authoritative DNS", "VM.Standard.E5.Flex", "linux/amd64", "four-hour RTO",
        ):
            with self.subTest(token=token):
                self.assertIn(token, text)

    def test_incident_and_status_contract_covers_required_failures(self):
        incidents = (RUNBOOKS / "incidents.md").read_text(encoding="utf-8").lower()
        for token in (
            "discord", "twitch", "mariadb", "redis", "racebot", "disk", "tls",
            "backup", "provider", "duplicate scheduler", "auth", "oci capacity", "cost",
        ):
            with self.subTest(token=token):
                self.assertIn(token, incidents)
        status = (RUNBOOKS / "status-comms.md").read_text(encoding="utf-8")
        for token in ("INVESTIGATING", "IDENTIFIED", "MONITORING", "RESOLVED", "ROLLBACK"):
            self.assertIn(token, status)
        self.assertIn("within five minutes", status)
        self.assertIn("before reapplying", status)

    def test_role_and_severity_documents_match_single_operator_model(self):
        raci = (ROOT / "docs" / "operations" / "raci.md").read_text(encoding="utf-8")
        severity = (ROOT / "docs" / "operations" / "severity-and-slo.md").read_text(encoding="utf-8")
        self.assertIn("sole routine", raci)
        self.assertNotRegex(raci.lower(), r"requires? (?:a )?(?:two operators|second technical approver)")
        self.assertIn("recovery custodian", raci.lower())
        for token in ("P0", "P1", "P2", "P3", "RPO", "RTO", "active-race", "auth compromise"):
            self.assertIn(token, severity)


if __name__ == "__main__":
    unittest.main()
