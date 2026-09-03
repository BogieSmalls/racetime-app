from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
RUNBOOKS = ROOT / "docs" / "runbooks"
LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


class RunbookLinkTests(unittest.TestCase):
    def test_every_relative_markdown_link_resolves_without_traversal(self):
        for path in sorted(RUNBOOKS.glob("*.md")):
            for target in LINK.findall(path.read_text(encoding="utf-8")):
                target = target.split("#", 1)[0]
                if not target or "://" in target or target.startswith("mailto:"):
                    continue
                with self.subTest(runbook=path.name, link=target):
                    resolved = (path.parent / target).resolve()
                    self.assertTrue(str(resolved).startswith(str(ROOT.resolve())))
                    self.assertTrue(resolved.exists(), f"broken link: {path} -> {target}")


if __name__ == "__main__":
    unittest.main()
