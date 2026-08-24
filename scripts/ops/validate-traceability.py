#!/usr/bin/env python3
"""Validate bidirectional requirement/artifact/evidence traceability by gate."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys


class TraceabilityError(ValueError):
    pass


GATE_ORDER = {f"G{index}": index for index in range(5)}
REQUIREMENT = re.compile(r"(?:FR|NFR)-[A-Z]+-[0-9]{3}")
REQUIREMENT_DEFINITION = re.compile(r"(?m)^\s*-\s+\*\*((?:FR|NFR)-[A-Z]+-[0-9]{3}):\*\*")
ARTIFACT = re.compile(r"[A-Z]{2,4}-[0-9]{3}")
SINGLE = re.compile(r"^(?P<prefix>[A-Z]{2,4})-(?P<number>[0-9]{3})$")
RANGE = re.compile(r"^(?P<start>[A-Z]{2,4})-(?P<first>[0-9]{3})–(?:(?P<endprefix>[A-Z]{2,4})-)?(?P<last>[0-9]{3})$")
RANGE_SCAN = re.compile(r"(?P<start>[A-Z]{2,4})-(?P<first>[0-9]{3})–(?:(?P<endprefix>[A-Z]{2,4})-)?(?P<last>[0-9]{3})")
SLASH_SCAN = re.compile(r"(?P<prefix>[A-Z]{2,4})-(?P<numbers>[0-9]{3}(?:/[0-9]{3})+)")
VERIFIED = re.compile(r"^Verified \(\[[^\]]+\]\(([^)]+)\)\)$")
EXCEPTION = re.compile(r"^Accepted exception \((COUNCIL-[0-9]{4}-[0-9]{3,}), \[[^\]]+\]\(([^)]+)\)\)$")


def _read(path, label):
    target = Path(path).resolve()
    if not target.is_file() or target.is_symlink():
        raise TraceabilityError(f"{label} file is missing or unsafe")
    try:
        return target, target.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise TraceabilityError(f"{label} is not UTF-8") from exc


def _unique(values, label):
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise TraceabilityError(f"duplicate {label}: {','.join(duplicates)}")
    return set(values)


def _table_rows(text):
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells or all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        yield line_number, cells


def _artifact_register(text):
    values = []
    for _, cells in _table_rows(text):
        if cells and SINGLE.fullmatch(cells[0]):
            values.append(cells[0])
    if not values:
        raise TraceabilityError("artifact register contains no artifacts")
    return _unique(values, "artifact definition")


def _expand_expression(expression):
    expression = expression.strip().strip("`")
    single = SINGLE.fullmatch(expression)
    if single:
        return [expression]
    match = RANGE.fullmatch(expression)
    if not match:
        raise TraceabilityError(f"invalid or ambiguous artifact expression: {expression}")
    prefix = match.group("start")
    end_prefix = match.group("endprefix") or prefix
    first = int(match.group("first"))
    last = int(match.group("last"))
    if end_prefix != prefix or last < first or last - first > 200:
        raise TraceabilityError(f"invalid or ambiguous artifact range: {expression}")
    return [f"{prefix}-{number:03d}" for number in range(first, last + 1)]


def _strict_artifact_cell(value):
    expressions = [part.strip() for part in value.split(",") if part.strip()]
    if not expressions:
        raise TraceabilityError("traceability row has no artifacts")
    expanded = []
    for expression in expressions:
        expanded.extend(_expand_expression(expression))
    if len(expanded) != len(set(expanded)):
        raise TraceabilityError("traceability row repeats an artifact")
    return set(expanded)


def _coverage_artifacts(value):
    found = set()
    consumed = [False] * len(value)
    for match in RANGE_SCAN.finditer(value):
        expression = match.group(0)
        found.update(_expand_expression(expression))
        consumed[match.start():match.end()] = [True] * (match.end() - match.start())
    for match in SLASH_SCAN.finditer(value):
        if any(consumed[match.start():match.end()]):
            continue
        prefix = match.group("prefix")
        found.update(f"{prefix}-{number}" for number in match.group("numbers").split("/"))
        consumed[match.start():match.end()] = [True] * (match.end() - match.start())
    remainder = "".join(" " if used else char for char, used in zip(value, consumed))
    found.update(ARTIFACT.findall(remainder))
    return found


def _repo_root(matrix_path):
    for parent in (matrix_path.parent, *matrix_path.parents):
        if (parent / ".git").exists():
            return parent.resolve()
    return matrix_path.parent.resolve()


def _evidence_target(matrix_path, raw_target):
    if not raw_target or "://" in raw_target or raw_target.startswith(("/", "\\")):
        raise TraceabilityError("evidence link must be a local relative path")
    target = (matrix_path.parent / raw_target).resolve()
    root = _repo_root(matrix_path)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise TraceabilityError("evidence link escapes repository") from exc
    if not target.is_file() or target.is_symlink():
        raise TraceabilityError("evidence link target is missing or unsafe")
    return target


def _validate_status(status, matrix_path):
    if status == "Planned":
        return "Planned"
    verified = VERIFIED.fullmatch(status)
    accepted = EXCEPTION.fullmatch(status)
    if verified:
        _evidence_target(matrix_path, verified.group(1))
        return "Verified"
    if accepted:
        _evidence_target(matrix_path, accepted.group(2))
        return "Accepted exception"
    raise TraceabilityError("traceability status is invalid or lacks one evidence link")


def _gates(value):
    gates = [part.strip() for part in value.split("/")]
    if not gates or any(gate not in GATE_ORDER for gate in gates) or len(gates) != len(set(gates)):
        raise TraceabilityError("gate cell is invalid")
    return gates


def _trace_rows(text, matrix_path, known_requirements, known_artifacts):
    rows = {}
    in_architecture = False
    architecture_artifacts = set()
    for line in text.splitlines():
        if line.startswith("## Architecture coverage"):
            in_architecture = True
            continue
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        if in_architecture:
            if len(cells) >= 2 and cells[0] != "Architecture topic":
                architecture_artifacts.update(_coverage_artifacts(cells[1]))
            continue
        if not cells or cells[0] == "Requirement":
            continue
        match = REQUIREMENT.match(cells[0])
        if not match:
            continue
        if len(cells) != 6:
            raise TraceabilityError("traceability requirement row must have six cells")
        requirement = match.group(0)
        if requirement not in known_requirements:
            raise TraceabilityError(f"unknown requirement in matrix: {requirement}")
        if requirement in rows:
            raise TraceabilityError(f"duplicate requirement row: {requirement}")
        artifacts = _strict_artifact_cell(cells[2])
        unknown = artifacts - known_artifacts
        if unknown:
            raise TraceabilityError(f"unknown artifact in matrix: {','.join(sorted(unknown))}")
        gate_values = _gates(cells[4])
        status = _validate_status(cells[5], matrix_path)
        rows[requirement] = {"artifacts": artifacts, "gates": gate_values, "status": status}
    unknown_architecture = architecture_artifacts - known_artifacts
    if unknown_architecture:
        raise TraceabilityError(f"unknown architecture artifact: {','.join(sorted(unknown_architecture))}")
    return rows, architecture_artifacts


def validate_traceability(*, requirements_path, artifacts_path, matrix_path, gate):
    if gate not in GATE_ORDER:
        raise TraceabilityError("selected gate is invalid")
    requirements_file, requirements_text = _read(requirements_path, "requirements")
    artifacts_file, artifacts_text = _read(artifacts_path, "artifact register")
    matrix_file, matrix_text = _read(matrix_path, "traceability matrix")
    del requirements_file, artifacts_file
    requirement_list = REQUIREMENT_DEFINITION.findall(requirements_text)
    if not requirement_list:
        raise TraceabilityError("requirements file contains no definitions")
    requirements = _unique(requirement_list, "requirement definition")
    artifacts = _artifact_register(artifacts_text)
    rows, architecture = _trace_rows(matrix_text, matrix_file, requirements, artifacts)
    missing_requirements = requirements - set(rows)
    if missing_requirements:
        raise TraceabilityError(f"requirements absent from matrix: {','.join(sorted(missing_requirements))}")
    mapped = set().union(*(row["artifacts"] for row in rows.values())) if rows else set()
    orphans = artifacts - mapped - architecture
    if orphans:
        raise TraceabilityError(f"registered artifacts lack coverage: {','.join(sorted(orphans))}")
    due = []
    selected = GATE_ORDER[gate]
    for requirement, row in rows.items():
        if min(GATE_ORDER[value] for value in row["gates"]) <= selected:
            due.append(requirement)
            if row["status"] == "Planned":
                raise TraceabilityError(f"due requirement remains Planned: {requirement}")
    if gate == "G4":
        remaining = sorted(requirement for requirement, row in rows.items() if row["status"] == "Planned")
        if remaining:
            raise TraceabilityError(f"G4 contains Planned rows: {','.join(remaining)}")
    return {"requirements": len(requirements), "artifacts": len(artifacts), "due": len(due), "gate": gate}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate", choices=sorted(GATE_ORDER), required=True)
    parser.add_argument("--requirements", default="docs/racetime-z1rr/requirements-and-decisions.md")
    parser.add_argument("--artifacts", default="docs/racetime-z1rr/artifact-register.md")
    parser.add_argument("--matrix", default="docs/racetime-z1rr/requirements-traceability.md")
    args = parser.parse_args(argv)
    try:
        summary = validate_traceability(
            requirements_path=args.requirements,
            artifacts_path=args.artifacts,
            matrix_path=args.matrix,
            gate=args.gate,
        )
    except TraceabilityError as exc:
        sys.stderr.write(f"TRACEABILITY=FAIL gate={args.gate} code={type(exc).__name__}\n")
        return 1
    print(
        f"TRACEABILITY=PASS gate={summary['gate']} requirements={summary['requirements']} "
        f"artifacts={summary['artifacts']} due={summary['due']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
