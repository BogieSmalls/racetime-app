"""Fail-closed phase and cleanup state for the G0 worker."""

from __future__ import annotations

import copy
import re
from collections.abc import Callable

from scripts.g0.runner import WorkerDisposalRequired


PHASES = ("preflight", "setup", "images", "security", "services", "recovery", "cross_repo", "identities", "cleanup")
_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class StateError(RuntimeError):
    """Qualification state was used out of order."""


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
        self._disposal: WorkerDisposalRequired | None = None
        self._deferred_base_exception_raised = False

    @property
    def result(self) -> dict | None:
        return copy.deepcopy(self._result)

    def begin(self, phase: str) -> None:
        self._ensure_open()
        if self._primary_failure is not None or self._active_phase is not None:
            raise StateError("qualification cannot begin this phase")
        if self._phase_index >= len(PHASES) - 1 or phase != PHASES[self._phase_index]:
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
        self._phase_records[phase] = {"name": phase, "status": "PASS", "evidence": promoted}
        self._evidence[phase] = promoted
        self._active_phase = None
        self._phase_index += 1

    def fail_phase(self, phase: str, error_class: str) -> None:
        self._require_active(phase)
        normalized = self._safe_class(error_class, "UnclassifiedFailure")
        self._phase_records[phase] = {"name": phase, "status": "FAIL", "error_class": normalized}
        self._primary_failure = {"phase": phase, "error_class": normalized}
        self._active_phase = None

    def register_cleanup(self, cleanup_id: str, callback: Callable[[], None]) -> None:
        self._ensure_open()
        if self._closing:
            raise StateError("cleanup is already running")
        if not isinstance(cleanup_id, str) or _SAFE_IDENTIFIER.fullmatch(cleanup_id) is None or not callable(callback):
            raise StateError("invalid cleanup registration")
        if cleanup_id in self._cleanup_ids:
            raise StateError("duplicate cleanup registration")
        self._cleanup_ids.add(cleanup_id)
        self._cleanups.append((cleanup_id, callback))

    def require_worker_disposal(self, error: WorkerDisposalRequired) -> None:
        """Latch unknown work immediately; no in-host callback is safe afterward."""
        self._ensure_open()
        if self._closing or not isinstance(error, WorkerDisposalRequired):
            raise StateError("invalid worker disposal transition")
        phase = self._active_phase or PHASES[self._phase_index]
        self._phase_records[phase] = {"name": phase, "status": "UNVERIFIABLE", "error_class": "WorkerDisposalRequired"}
        self._primary_failure = {"phase": phase, "error_class": "WorkerDisposalRequired"}
        self._active_phase = None
        self._finish([], [], cleanup_status="unverifiable")
        self._disposal = error
        raise error

    def close(self) -> dict:
        if self._closing:
            raise StateError("cleanup is already running")
        if self._disposal is not None:
            raise self._disposal
        if self._result is not None:
            return copy.deepcopy(self._result)
        self._closing = True
        self._record_incomplete()
        completed: list[str] = []
        failures: list[dict] = []
        deferred: BaseException | None = None
        try:
            for cleanup_id, callback in reversed(self._cleanups):
                try:
                    callback()
                except WorkerDisposalRequired as error:
                    failures.append({"cleanup_id": cleanup_id, "error_class": "WorkerDisposalRequired"})
                    self._finish(completed, failures, cleanup_status="unverifiable")
                    self._disposal = error
                    raise
                except BaseException as error:
                    failures.append({"cleanup_id": cleanup_id, "error_class": self._safe_class(type(error).__name__, "UnclassifiedCleanupFailure")})
                    if not isinstance(error, Exception) and deferred is None:
                        deferred = error
                else:
                    completed.append(cleanup_id)
            self._finish(completed, failures, cleanup_status="failed" if failures else "verified")
        finally:
            self._closing = False
        if deferred is not None and not self._deferred_base_exception_raised:
            self._deferred_base_exception_raised = True
            raise deferred
        return copy.deepcopy(self._result)

    def _record_incomplete(self) -> None:
        if self._primary_failure is not None or self._phase_index >= len(PHASES) - 1:
            return
        if self._active_phase is not None:
            self.fail_phase(self._active_phase, "IncompletePhase")
            return
        phase = PHASES[self._phase_index]
        self._phase_records[phase] = {"name": phase, "status": "FAIL", "error_class": "IncompleteQualification"}
        self._primary_failure = {"phase": phase, "error_class": "IncompleteQualification"}

    def _finish(self, completed: list[str], failures: list[dict], *, cleanup_status: str) -> None:
        status = "UNVERIFIABLE" if cleanup_status == "unverifiable" else ("FAIL" if failures else "PASS")
        self._phase_records["cleanup"] = {"name": "cleanup", "status": status, "evidence": {"completed": list(completed)}}
        phases = [copy.deepcopy(self._phase_records.get(phase, {"name": phase, "status": "BLOCKED"})) for phase in PHASES]
        passed = self._primary_failure is None and not failures and all(phase["status"] == "PASS" for phase in phases)
        final_result = (
            "WORKER_DISPOSAL_REQUIRED"
            if cleanup_status == "unverifiable"
            else ("PASS" if passed else "FAIL")
        )
        self._result = {
            "result": final_result,
            "phases": phases,
            "evidence": copy.deepcopy(self._evidence),
            "primary_failure": copy.deepcopy(self._primary_failure),
            "cleanup_failures": copy.deepcopy(failures),
            "cleanup_status": cleanup_status,
        }

    def _ensure_open(self) -> None:
        if self._result is not None or self._disposal is not None:
            raise StateError("qualification is closed")

    def _require_active(self, phase: str) -> None:
        self._ensure_open()
        if self._active_phase != phase:
            raise StateError("phase is not active")

    @staticmethod
    def _safe_class(value: object, fallback: str) -> str:
        return value if isinstance(value, str) and _SAFE_IDENTIFIER.fullmatch(value) is not None else fallback

    @classmethod
    def _contains_skip(cls, value: object) -> bool:
        if isinstance(value, dict):
            for key, child in value.items():
                normalized_key = str(key).lower().replace("-", "_")
                if "skip" in normalized_key and child not in (None, False, 0, "", (), [], {}):
                    return True
                if cls._contains_skip(child):
                    return True
            return False
        if isinstance(value, (list, tuple)):
            return any(cls._contains_skip(child) for child in value)
        return isinstance(value, str) and value.strip().upper() in {"SKIP", "SKIPPED", "SKIPPING"}
