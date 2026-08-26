"""Fail-closed phase and cleanup state for the G0 worker."""

from __future__ import annotations

import copy
import re
from collections.abc import Callable


PHASES = (
    "preflight",
    "setup",
    "images",
    "security",
    "services",
    "recovery",
    "cross_repo",
    "identities",
    "cleanup",
)
_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class StateError(RuntimeError):
    """Raised when qualification state is used out of order."""


class QualificationState:
    def __init__(self) -> None:
        self._phase_index = 0
        self._active_phase: str | None = None
        self._phase_records: dict[str, dict] = {}
        self._evidence: dict[str, dict] = {}
        self._primary_failure: dict | None = None
        self._cleanups: list[tuple[str, Callable[[], None]]] = []
        self._cleanup_ids: set[str] = set()
        self._closing = False
        self._result: dict | None = None

    def begin(self, phase: str) -> None:
        self._ensure_open()
        if self._primary_failure is not None:
            raise StateError("qualification is already failed")
        if self._active_phase is not None:
            raise StateError("a phase is already active")
        if self._phase_index >= len(PHASES) - 1:
            raise StateError("cleanup is controlled by close")
        if phase != PHASES[self._phase_index]:
            raise StateError("phase order violation")
        self._active_phase = phase

    def pass_phase(self, phase: str, evidence: dict) -> None:
        self._require_active(phase)
        if not isinstance(evidence, dict):
            self.fail_phase(phase, "InvalidEvidence")
            return
        if self._contains_skip(evidence):
            self.fail_phase(phase, "MandatorySkip")
            return
        promoted = copy.deepcopy(evidence)
        self._phase_records[phase] = {
            "name": phase,
            "status": "PASS",
            "evidence": promoted,
        }
        self._evidence[phase] = promoted
        self._active_phase = None
        self._phase_index += 1

    def fail_phase(self, phase: str, error_class: str) -> None:
        self._require_active(phase)
        if (
            not isinstance(error_class, str)
            or _SAFE_IDENTIFIER.fullmatch(error_class) is None
        ):
            error_class = "UnclassifiedFailure"
        failure = {"phase": phase, "error_class": error_class}
        self._phase_records[phase] = {
            "name": phase,
            "status": "FAIL",
            "error_class": error_class,
        }
        self._primary_failure = failure
        self._active_phase = None

    def register_cleanup(
        self,
        cleanup_id: str,
        callback: Callable[[], None],
    ) -> None:
        self._ensure_open()
        if self._closing:
            raise StateError("cleanup is already running")
        if (
            not isinstance(cleanup_id, str)
            or _SAFE_IDENTIFIER.fullmatch(cleanup_id) is None
            or not callable(callback)
        ):
            raise StateError("invalid cleanup registration")
        if cleanup_id in self._cleanup_ids:
            raise StateError("duplicate cleanup registration")
        self._cleanup_ids.add(cleanup_id)
        self._cleanups.append((cleanup_id, callback))

    def close(self) -> dict:
        if self._result is not None:
            return self._result
        self._closing = True

        if self._primary_failure is None and self._phase_index < len(PHASES) - 1:
            if self._active_phase is not None:
                self.fail_phase(self._active_phase, "IncompletePhase")
            else:
                phase = PHASES[self._phase_index]
                failure = {"phase": phase, "error_class": "IncompleteQualification"}
                self._phase_records[phase] = {
                    "name": phase,
                    "status": "FAIL",
                    "error_class": "IncompleteQualification",
                }
                self._primary_failure = failure

        completed_cleanups = []
        cleanup_failures = []
        for cleanup_id, callback in reversed(self._cleanups):
            try:
                callback()
            except Exception as error:
                cleanup_failures.append(
                    {
                        "cleanup_id": cleanup_id,
                        "error_class": type(error).__name__,
                    }
                )
            else:
                completed_cleanups.append(cleanup_id)

        cleanup_status = "FAIL" if cleanup_failures else "PASS"
        self._phase_records["cleanup"] = {
            "name": "cleanup",
            "status": cleanup_status,
            "evidence": {"completed": completed_cleanups},
        }
        phase_results = []
        for phase in PHASES:
            phase_results.append(
                self._phase_records.get(phase, {"name": phase, "status": "BLOCKED"})
            )

        passed = (
            self._primary_failure is None
            and not cleanup_failures
            and all(
                record["status"] == "PASS"
                for record in phase_results
            )
        )
        self._result = {
            "result": "PASS" if passed else "FAIL",
            "phases": phase_results,
            "evidence": copy.deepcopy(self._evidence),
            "primary_failure": copy.deepcopy(self._primary_failure),
            "cleanup_failures": cleanup_failures,
        }
        return self._result

    def _ensure_open(self) -> None:
        if self._result is not None:
            raise StateError("qualification is closed")

    def _require_active(self, phase: str) -> None:
        self._ensure_open()
        if self._active_phase != phase:
            raise StateError("phase is not active")

    @classmethod
    def _contains_skip(cls, value: object) -> bool:
        if isinstance(value, dict):
            for key, child in value.items():
                normalized_key = str(key).lower().replace("-", "_")
                if "skip" in normalized_key and cls._truthy_skip(child):
                    return True
                if cls._contains_skip(child):
                    return True
            return False
        if isinstance(value, (list, tuple)):
            return any(cls._contains_skip(child) for child in value)
        return isinstance(value, str) and value.upper() == "SKIP"

    @staticmethod
    def _truthy_skip(value: object) -> bool:
        return value not in (None, False, 0, "", (), [], {})
