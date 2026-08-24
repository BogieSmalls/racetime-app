#!/usr/bin/env python3
"""Compare a preserved RaceTime ref manifest with a read-only ref capture."""

import argparse
import json
import re
import sys
from pathlib import Path


OBJECT_ID = re.compile(r"^[0-9a-f]{40}$")
REF_NAME = re.compile(r"^[A-Za-z0-9._/-]+$")


def _validate_snapshot(snapshot, label):
    if not isinstance(snapshot, dict):
        raise ValueError(f"{label} must be a JSON object")
    for field in ("default_branch", "upstream_head", "branches", "tags"):
        if field not in snapshot:
            raise ValueError(f"{label} is missing {field}")
    if not isinstance(snapshot["default_branch"], str) or not REF_NAME.fullmatch(
        snapshot["default_branch"]
    ):
        raise ValueError(f"{label}.default_branch is invalid")
    if not isinstance(snapshot["upstream_head"], str) or not OBJECT_ID.fullmatch(
        snapshot["upstream_head"]
    ):
        raise ValueError(f"{label}.upstream_head is invalid")
    for namespace in ("branches", "tags"):
        refs = snapshot[namespace]
        if not isinstance(refs, dict):
            raise ValueError(f"{label}.{namespace} must be an object")
        for name, object_id in refs.items():
            if not isinstance(name, str) or not REF_NAME.fullmatch(name):
                raise ValueError(f"{label}.{namespace} contains an invalid ref name")
            if not isinstance(object_id, str) or not OBJECT_ID.fullmatch(object_id):
                raise ValueError(f"{label}.{namespace}.{name} is not an object ID")
    default_tip = snapshot["branches"].get(snapshot["default_branch"])
    if default_tip != snapshot["upstream_head"]:
        raise ValueError(
            f"{label} default branch tip does not equal {label}.upstream_head"
        )


def _compare_namespace(before, after):
    before_names = set(before)
    after_names = set(after)
    added = {name: after[name] for name in sorted(after_names - before_names)}
    removed = {name: before[name] for name in sorted(before_names - after_names)}
    changed = {
        name: {"before": before[name], "after": after[name]}
        for name in sorted(before_names & after_names)
        if before[name] != after[name]
    }
    return {"added": added, "removed": removed, "changed": changed}


def compare_refs(baseline, captured):
    """Return a deterministic, JSON-serializable ref difference."""
    _validate_snapshot(baseline, "baseline")
    _validate_snapshot(captured, "captured")
    default_changed = (
        baseline["default_branch"] != captured["default_branch"]
        or baseline["upstream_head"] != captured["upstream_head"]
    )
    branches = _compare_namespace(baseline["branches"], captured["branches"])
    tags = _compare_namespace(baseline["tags"], captured["tags"])
    has_ref_drift = any(branches[change] for change in branches) or any(
        tags[change] for change in tags
    )
    return {
        "default": {
            "changed": default_changed,
            "before_branch": baseline["default_branch"],
            "after_branch": captured["default_branch"],
            "before_head": baseline["upstream_head"],
            "after_head": captured["upstream_head"],
        },
        "branches": branches,
        "tags": tags,
        "has_drift": bool(default_changed or has_ref_drift),
    }


def _render_namespace(title, changes):
    lines = [f"## {title}", "", "| Change | Ref | Before | After |", "|---|---|---|---|"]
    rows = []
    for name, object_id in changes["added"].items():
        rows.append((name, f"| Added | `{name}` | — | `{object_id}` |"))
    for name, object_id in changes["removed"].items():
        rows.append((name, f"| Removed | `{name}` | `{object_id}` | — |"))
    for name, values in changes["changed"].items():
        rows.append(
            (name, f"| Changed | `{name}` | `{values['before']}` | `{values['after']}` |")
        )
    if rows:
        lines.extend(row for _, row in sorted(rows, key=lambda item: (item[0], item[1])))
    else:
        lines.append("| None | — | — | — |")
    return lines


def render_markdown(result):
    status = "DRIFT DETECTED" if result["has_drift"] else "NO DRIFT"
    default = result["default"]
    lines = [
        "# RaceTime upstream drift report",
        "",
        f"Result: **{status}**",
        "",
        "| Check | Baseline | Captured | Status |",
        "|---|---|---|---|",
        (
            f"| Default HEAD | `{default['before_branch']}` @ `{default['before_head']}` "
            f"| `{default['after_branch']}` @ `{default['after_head']}` "
            f"| {'Changed' if default['changed'] else 'Unchanged'} |"
        ),
        "",
    ]
    lines.extend(_render_namespace("Branches", result["branches"]))
    lines.append("")
    lines.extend(_render_namespace("Tags", result["tags"]))
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--captured", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        captured = json.loads(args.captured.read_text(encoding="utf-8"))
        result = compare_refs(baseline, captured)
        report = render_markdown(result)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8", newline="\n")
        sys.stdout.write(report)
        return 1 if result["has_drift"] else 0
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
