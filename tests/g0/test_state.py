import unittest

from scripts.g0.runner import WorkerDisposalRequired
from scripts.g0.state import PHASES, QualificationState, StateError


class ShutdownSignal(BaseException):
    pass


class _UnsafeSignal(BaseException):
    pass


class QualificationStateTests(unittest.TestCase):
    def test_result_and_close_return_detached_snapshots(self):
        state = QualificationState()
        state.begin("preflight")
        state.pass_phase("preflight", {"safe": {"value": "original"}})
        first = state.close()
        first["result"] = "PASS"
        first["phases"][0]["status"] = "PASS"
        first["evidence"]["preflight"]["safe"]["value"] = "tampered"
        observed = state.result
        self.assertEqual("FAIL", observed["result"])
        self.assertEqual("original", observed["evidence"]["preflight"]["safe"]["value"])
        observed["cleanup_status"] = "tampered"
        self.assertEqual("verified", state.result["cleanup_status"])
        self.assertEqual("FAIL", state.close()["result"])

    def test_exact_phase_order_and_lifo_idempotent_cleanup(self):
        state = QualificationState(); observed = []
        state.register_cleanup("first", lambda: observed.append("first"))
        state.register_cleanup("second", lambda: observed.append("second"))
        for phase in PHASES[:-1]:
            state.begin(phase); state.pass_phase(phase, {"proof": phase})
        result = state.close()
        self.assertEqual("PASS", result["result"]); self.assertEqual(["second", "first"], observed)
        self.assertEqual(result, state.close())
        self.assertIsNot(result, state.close())

    def test_out_of_order_or_late_phase_is_rejected(self):
        state = QualificationState()
        with self.assertRaises(StateError): state.begin("images")
        state.begin("preflight")
        with self.assertRaises(StateError): state.begin("preflight")

    def test_failure_blocks_later_promotion_but_runs_ordinary_cleanup(self):
        state = QualificationState(); observed = []
        state.register_cleanup("restore", lambda: observed.append("restore"))
        state.begin("preflight"); state.fail_phase("preflight", "ProbeFailed")
        with self.assertRaises(StateError): state.begin("setup")
        result = state.close()
        self.assertEqual("FAIL", result["result"]); self.assertEqual(["restore"], observed)
        self.assertEqual("BLOCKED", result["phases"][1]["status"])

    def test_restoration_failure_is_fail_plus_cleanup_failed(self):
        state = QualificationState()
        state.register_cleanup("restore", lambda: (_ for _ in ()).throw(OSError("unsafe")))
        result = state.close()
        self.assertEqual("FAIL", result["result"]); self.assertEqual("FAIL", result["phases"][-1]["status"])
        self.assertEqual("OSError", result["cleanup_failures"][0]["error_class"])

    def test_other_base_exception_is_aggregated_after_all_callbacks_then_reraised_once(self):
        state = QualificationState(); observed = []
        state.register_cleanup("later", lambda: observed.append("later"))
        state.register_cleanup("shutdown", lambda: (_ for _ in ()).throw(ShutdownSignal()))
        with self.assertRaises(ShutdownSignal): state.close()
        self.assertEqual(["later"], observed)
        result = state.close(); self.assertEqual("ShutdownSignal", result["cleanup_failures"][0]["error_class"])

    def test_unsafe_base_exception_class_is_normalized(self):
        state = QualificationState()
        state.register_cleanup("unsafe", lambda: (_ for _ in ()).throw(_UnsafeSignal()))
        with self.assertRaises(_UnsafeSignal): state.close()
        self.assertEqual("UnclassifiedCleanupFailure", state.close()["cleanup_failures"][0]["error_class"])

    def test_reentrant_close_is_rejected_and_recorded_without_stopping_lifo(self):
        state = QualificationState(); observed = []
        state.register_cleanup("later", lambda: observed.append("later")); state.register_cleanup("reentrant", state.close)
        result = state.close()
        self.assertEqual(["later"], observed); self.assertEqual("StateError", result["cleanup_failures"][0]["error_class"])

    def test_disposal_required_stops_remaining_callbacks_and_marks_unverifiable(self):
        state = QualificationState(); observed = []
        state.register_cleanup("must-not-run", lambda: observed.append("unsafe"))
        disposal = WorkerDisposalRequired("safe")
        state.register_cleanup("unknown-work", lambda: (_ for _ in ()).throw(disposal))
        with self.assertRaises(WorkerDisposalRequired) as raised: state.close()
        self.assertIs(disposal, raised.exception); self.assertEqual([], observed)
        self.assertEqual("WORKER_DISPOSAL_REQUIRED", state.result["result"])
        self.assertEqual("unverifiable", state.result["cleanup_status"])
        self.assertEqual("UNVERIFIABLE", state.result["phases"][-1]["status"])
        with self.assertRaises(WorkerDisposalRequired): state.close()

    def test_phase_disposal_is_immediate_and_never_runs_in_host_cleanup(self):
        state = QualificationState(); observed = []
        state.register_cleanup("unsafe-after-unknown-work", lambda: observed.append("unsafe"))
        state.begin("preflight")
        disposal = WorkerDisposalRequired("safe")
        with self.assertRaises(WorkerDisposalRequired) as raised:
            state.require_worker_disposal(disposal)
        self.assertIs(disposal, raised.exception); self.assertEqual([], observed)
        self.assertEqual("WORKER_DISPOSAL_REQUIRED", state.result["result"])
        self.assertEqual("unverifiable", state.result["cleanup_status"])
        self.assertEqual("UNVERIFIABLE", state.result["phases"][-1]["status"])
        with self.assertRaises(WorkerDisposalRequired): state.close()

    def test_mandatory_skip_spellings_never_promote(self):
        for evidence in ({"status": "SKIP"}, {"status": "SKIPPED"}, {"status": "SKIPPING"}, {"mandatory_skip": True}):
            with self.subTest(evidence=evidence):
                state = QualificationState(); state.begin("preflight"); state.pass_phase("preflight", evidence)
                result = state.close(); self.assertEqual("MandatorySkip", result["primary_failure"]["error_class"])

    def test_duplicate_or_invalid_cleanup_registration_is_rejected(self):
        state = QualificationState(); state.register_cleanup("one", lambda: None)
        with self.assertRaises(StateError): state.register_cleanup("one", lambda: None)
        with self.assertRaises(StateError): state.register_cleanup("bad id", lambda: None)


if __name__ == "__main__": unittest.main()
