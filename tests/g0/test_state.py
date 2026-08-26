import unittest

from scripts.g0.state import QualificationState, StateError


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


class RestoreError(RuntimeError):
    pass


class QualificationStateTests(unittest.TestCase):
    def pass_through_identities(self, state):
        for phase in PHASES[:-1]:
            state.begin(phase)
            state.pass_phase(phase, {"command_id": f"check-{phase}"})

    def test_phases_run_in_exact_order_and_close_runs_cleanup(self):
        state = QualificationState()
        with self.assertRaises(StateError):
            state.begin("setup")

        self.pass_through_identities(state)
        result = state.close()

        self.assertEqual(list(PHASES), [phase["name"] for phase in result["phases"]])
        self.assertEqual(["PASS"] * len(PHASES), [phase["status"] for phase in result["phases"]])
        self.assertEqual("PASS", result["result"])

    def test_failure_blocks_later_evidence_promotion_but_always_cleans_up(self):
        events = []
        state = QualificationState()
        state.begin("preflight")
        state.pass_phase("preflight", {"artifact": "preflight.json"})
        state.begin("setup")
        state.register_cleanup("remove-builder", lambda: events.append("cleanup"))
        state.fail_phase("setup", "SetupFailure")

        with self.assertRaises(StateError):
            state.begin("images")
        result = state.close()

        self.assertEqual(["cleanup"], events)
        self.assertEqual({"preflight": {"artifact": "preflight.json"}}, result["evidence"])
        self.assertEqual("FAIL", result["result"])
        self.assertEqual(
            {"phase": "setup", "error_class": "SetupFailure"},
            result["primary_failure"],
        )
        statuses = {phase["name"]: phase["status"] for phase in result["phases"]}
        self.assertEqual("FAIL", statuses["setup"])
        self.assertEqual("BLOCKED", statuses["images"])
        self.assertEqual("PASS", statuses["cleanup"])

    def test_cleanup_is_lifo_idempotent_and_can_be_registered_before_mutation(self):
        events = []
        state = QualificationState()
        state.register_cleanup("restore-original", lambda: events.append("restore-original"))
        events.append("mutation")
        state.register_cleanup("remove-new", lambda: events.append("remove-new"))

        first = state.close()
        second = state.close()

        self.assertEqual(["mutation", "remove-new", "restore-original"], events)
        self.assertIs(first, second)

    def test_cleanup_restoration_failure_is_reported_separately(self):
        events = []
        state = QualificationState()
        state.begin("preflight")
        state.register_cleanup("still-runs", lambda: events.append("still-runs"))

        def fail_restore():
            raise RestoreError("unsafe restoration details")

        state.register_cleanup("restore-binfmt", fail_restore)
        state.fail_phase("preflight", "PreflightFailure")

        result = state.close()

        self.assertEqual(["still-runs"], events)
        self.assertEqual(
            {"phase": "preflight", "error_class": "PreflightFailure"},
            result["primary_failure"],
        )
        self.assertEqual(
            [{"cleanup_id": "restore-binfmt", "error_class": "RestoreError"}],
            result["cleanup_failures"],
        )
        self.assertEqual("FAIL", result["phases"][-1]["status"])
        self.assertNotIn("unsafe restoration details", repr(result))

    def test_mandatory_skips_are_converted_to_failure(self):
        state = QualificationState()
        state.begin("preflight")

        state.pass_phase(
            "preflight",
            {"command_id": "preflight", "mandatory_skips": 1},
        )
        result = state.close()

        self.assertEqual("FAIL", result["result"])
        self.assertEqual(
            {"phase": "preflight", "error_class": "MandatorySkip"},
            result["primary_failure"],
        )
        self.assertNotIn("preflight", result["evidence"])

    def test_duplicate_cleanup_registration_is_rejected(self):
        state = QualificationState()
        state.register_cleanup("restore", lambda: None)

        with self.assertRaises(StateError):
            state.register_cleanup("restore", lambda: None)


if __name__ == "__main__":
    unittest.main()
