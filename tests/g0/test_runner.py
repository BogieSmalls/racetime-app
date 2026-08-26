import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from scripts.g0.runner import CommandSpec, Runner, RunnerError, WorkerDisposalRequired


class _FakeProcess:
    def __init__(self, response, *, returncode=0, error=None, polls_before_response=0):
        self.response = response
        self.returncode = returncode
        self.error = error
        self.killed = False
        self.poll_calls = 0
        self.request = None
        self._request_endpoint = None
        self._response_endpoint = None
        self._polls_before_response = polls_before_response

    def configure(self, command):
        request = int(command[command.index("--request-endpoint") + 1])
        response = int(command[command.index("--response-endpoint") + 1])
        self._request_endpoint = self._duplicate_endpoint(request)
        self._response_endpoint = self._duplicate_endpoint(response)

    @staticmethod
    def _duplicate_endpoint(endpoint):
        if os.name != "nt":
            return os.dup(endpoint)
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.DuplicateHandle.argtypes = (
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p), ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong,
        )
        kernel32.DuplicateHandle.restype = ctypes.c_int
        current = kernel32.GetCurrentProcess()
        duplicate = ctypes.c_void_p()
        if not kernel32.DuplicateHandle(current, ctypes.c_void_p(endpoint), current, ctypes.byref(duplicate), 0, False, 2):
            raise OSError("fake endpoint duplicate failed")
        return duplicate.value

    @staticmethod
    def _close_endpoint(endpoint):
        if endpoint is None:
            return
        if os.name != "nt":
            os.close(endpoint)
        else:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(endpoint)

    @staticmethod
    def _read_endpoint(endpoint):
        if os.name != "nt":
            return os.read(endpoint, 1_048_576)
        import ctypes
        buffer = ctypes.create_string_buffer(1_048_576); read = ctypes.c_ulong()
        if not ctypes.windll.kernel32.ReadFile(endpoint, buffer, len(buffer), ctypes.byref(read), None):
            raise OSError("fake endpoint read failed")
        return buffer.raw[: read.value]

    @staticmethod
    def _write_endpoint(endpoint, content):
        if os.name != "nt":
            os.write(endpoint, content); return
        import ctypes
        written = ctypes.c_ulong(); buffer = ctypes.create_string_buffer(content)
        if not ctypes.windll.kernel32.WriteFile(endpoint, buffer, len(content), ctypes.byref(written), None) or written.value != len(content):
            raise OSError("fake endpoint write failed")

    def poll(self):
        self.poll_calls += 1
        if self.killed:
            return self.returncode
        if self.error is not None and not self.killed:
            return None
        if self._polls_before_response:
            self._polls_before_response -= 1
            return None
        if self.request is None:
            self.request = self._read_endpoint(self._request_endpoint)
            self._close_endpoint(self._request_endpoint); self._request_endpoint = None
            self._write_endpoint(self._response_endpoint, self.response)
            self._close_endpoint(self._response_endpoint); self._response_endpoint = None
        return self.returncode

    def kill(self):
        self.killed = True
        self._close_endpoint(self._request_endpoint); self._request_endpoint = None
        self._close_endpoint(self._response_endpoint); self._response_endpoint = None
        self.returncode = -9



def _response(status="PASS", **changes):
    value = {
        "protocol_version": 1,
        "status": status,
        "exit_code": 0,
        "duration_ms": 1,
        "cleanup_deadline_monotonic_ns": 9_000_000_000_000_000_000,
        "stdout_sha256": "sha256:" + "0" * 64,
        "stderr_sha256": "sha256:" + "1" * 64,
        "proof": {"boundary_empty": True, "streams_eof": True, "logs_finalized": True},
    }
    value.update(changes)
    return (json.dumps(value) + "\n").encode()


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name).resolve()
        self.logs = self.root / "logs"

    def tearDown(self):
        self.temporary_directory.cleanup()

    def spec(self, command_id="probe", argv=None, **changes):
        values = {
            "command_id": command_id,
            "argv": tuple(argv or (sys.executable, "-I", "-c", "print('ok')")),
            "cwd": self.root,
            "execution_timeout_seconds": 5,
            "cleanup_timeout_seconds": 5,
            "environment": (),
            "secret_canaries": (),
            "stdout_limit": 4096,
            "stderr_limit": 4096,
            "log_directory": self.logs,
        }
        values.update(changes)
        return CommandSpec(**values)

    def fake_runner(self, process):
        def create(command, **kwargs):
            process.configure(command)
            return process
        factory = mock.Mock(side_effect=create)
        return Runner(run_root=self.root, popen_factory=factory), factory

    def test_every_command_is_sent_to_a_dedicated_supervisor_without_shell(self):
        process = _FakeProcess(_response())
        runner, factory = self.fake_runner(process)
        literal = "; echo shell-injection"
        result = runner.run(self.spec(argv=(sys.executable, "-c", "print(1)", literal)))
        self.assertEqual(0, result.exit_code)
        args, kwargs = factory.call_args
        self.assertEqual(sys.executable, args[0][0])
        self.assertTrue(args[0][1].endswith("supervisor.py"))
        self.assertFalse(kwargs["shell"])
        request = json.loads(process.request)
        self.assertEqual(literal, request["argv"][-1])
        self.assertEqual([], request["environment"])
        self.assertGreaterEqual(process.poll_calls, 1)

    def test_execution_and_cleanup_timeout_ranges_are_independent(self):
        runner, factory = self.fake_runner(_FakeProcess(_response()))
        invalid = (
            self.spec(execution_timeout_seconds=0), self.spec(execution_timeout_seconds=18001),
            self.spec(cleanup_timeout_seconds=4), self.spec(cleanup_timeout_seconds=601),
        )
        for spec in invalid:
            with self.subTest(spec=spec):
                with self.assertRaisesRegex(RunnerError, r"^command probe is invalid$"):
                    runner.run(spec)
        factory.assert_not_called()

    def test_paths_must_be_absolute_local_and_inside_the_retained_run_root(self):
        runner, factory = self.fake_runner(_FakeProcess(_response()))
        invalid = (
            self.spec(cwd=Path("relative")), self.spec(log_directory=self.root.parent / "outside"),
            self.spec(log_directory=Path("//server/share/logs")), self.spec(cwd=self.root / "missing"),
            self.spec(log_directory=self.root / "logs" / ".." / ".." / "outside"),
        )
        for spec in invalid:
            with self.subTest(spec=spec):
                with self.assertRaises(RunnerError):
                    runner.run(spec)
        factory.assert_not_called()

    def test_invalid_argv_environment_limits_and_canaries_fail_before_launch(self):
        runner, factory = self.fake_runner(_FakeProcess(_response()))
        invalid = (
            replace(self.spec(), argv="not-a-tuple"), self.spec(environment=(("A=B", "x"),)),
            self.spec(environment=(("A", "1"), ("A", "2"))), self.spec(stdout_limit=-1),
            self.spec(secret_canaries=("\ud800",)),
        )
        for spec in invalid:
            with self.subTest(spec=spec):
                with self.assertRaises(RunnerError):
                    runner.run(spec)
        factory.assert_not_called()

    def test_supervisor_wall_timeout_is_disposal_required_and_is_reaped(self):
        process = _FakeProcess(b"", error=subprocess.TimeoutExpired("supervisor", 10))
        runner, _ = self.fake_runner(process)
        with mock.patch("scripts.g0.runner.time.monotonic", side_effect=(0.0, 0.0, 0.0, 11.0)):
            with self.assertRaises(WorkerDisposalRequired):
                runner.run(self.spec())
        self.assertTrue(process.killed)
        self.assertGreaterEqual(process.poll_calls, 2)

    def test_response_and_exit_after_the_single_absolute_ceiling_are_rejected(self):
        process = _FakeProcess(_response(), polls_before_response=1)
        runner, _ = self.fake_runner(process)
        with mock.patch("scripts.g0.runner.time.monotonic", side_effect=(0.0, 0.0, 0.0, 10.001)):
            with self.assertRaises(WorkerDisposalRequired):
                runner.run(self.spec())
        self.assertTrue(process.killed)
        self.assertIsNone(process.request)

    def test_supervisor_exit_observed_after_its_cleanup_deadline_is_disposal(self):
        runner, _ = self.fake_runner(_FakeProcess(_response(cleanup_deadline_monotonic_ns=1)))
        with self.assertRaises(WorkerDisposalRequired):
            runner.run(self.spec())

    def test_disposal_sentinel_cannot_be_downgraded_by_exception_handlers(self):
        self.assertTrue(issubclass(WorkerDisposalRequired, BaseException))
        self.assertFalse(issubclass(WorkerDisposalRequired, Exception))
        observed = False
        try:
            raise WorkerDisposalRequired("safe")
        except Exception:
            observed = True
        except WorkerDisposalRequired:
            pass
        self.assertFalse(observed)

    def test_lost_or_malformed_fixed_protocol_is_disposal_required(self):
        boolean_version = json.loads(_response())
        boolean_version["protocol_version"] = True
        deeply_nested = b"[" * 1100 + b"0" + b"]" * 1100 + b"\n"
        duplicate_key = _response().replace(b'"protocol_version": 1,', b'"protocol_version": 1, "protocol_version": 1,')
        for payload in (
            b"", b"not-json", b"{}\nextra", b"{\"protocol_version\":2}\n",
            (json.dumps(boolean_version) + "\n").encode(), deeply_nested, duplicate_key,
        ):
            with self.subTest(payload=payload):
                runner, _ = self.fake_runner(_FakeProcess(payload))
                with self.assertRaises(WorkerDisposalRequired):
                    runner.run(self.spec())

    def test_nonempty_or_unfinalized_proof_is_disposal_required(self):
        for key in ("boundary_empty", "streams_eof", "logs_finalized"):
            decoded = json.loads(_response())
            decoded["proof"][key] = False
            runner, _ = self.fake_runner(_FakeProcess((json.dumps(decoded) + "\n").encode()))
            with self.subTest(key=key):
                with self.assertRaises(WorkerDisposalRequired):
                    runner.run(self.spec())

        decoded = json.loads(_response())
        decoded["proof"]["boundary_empty"] = 1
        runner, _ = self.fake_runner(_FakeProcess((json.dumps(decoded) + "\n").encode()))
        with self.assertRaises(WorkerDisposalRequired):
            runner.run(self.spec())

    def test_status_and_exit_code_invariants_are_fail_closed(self):
        invalid = (
            _response("TIMED_OUT", exit_code=0),
            _response("FAILED", exit_code=0),
            _response("WORKER_DISPOSAL_REQUIRED", exit_code=0),
        )
        for payload in invalid:
            with self.subTest(payload=payload):
                runner, _ = self.fake_runner(_FakeProcess(payload))
                with self.assertRaises(WorkerDisposalRequired):
                    runner.run(self.spec())

    @unittest.skipUnless(os.name == "nt", "Windows environment keys are case-insensitive")
    def test_windows_environment_keys_are_case_insensitively_unique(self):
        runner, factory = self.fake_runner(_FakeProcess(_response()))
        with self.assertRaises(RunnerError):
            runner.run(self.spec(environment=(("PATH", "one"), ("Path", "two"))))
        factory.assert_not_called()

    def test_timed_out_is_ordinary_only_after_all_proofs(self):
        runner, _ = self.fake_runner(_FakeProcess(_response("TIMED_OUT", exit_code=None)))
        with self.assertRaisesRegex(RunnerError, r"^command probe timed out$"):
            runner.run(self.spec())

    def test_nonzero_and_canary_failures_are_safe_ordinary_failures(self):
        cases = (
            (_response("FAILED", exit_code=7), "failed"),
            (_response("FAILED", exit_code=None), "failed"),
            (_response("CANARY_DETECTED"), "exposed a canary"),
        )
        for response, phrase in cases:
            with self.subTest(phrase=phrase):
                runner, _ = self.fake_runner(_FakeProcess(response))
                with self.assertRaisesRegex(RunnerError, rf"^command probe {phrase}$"):
                    runner.run(self.spec(secret_canaries=("secret",)))

    def test_supervisor_exit_and_protocol_eof_are_both_required(self):
        runner, _ = self.fake_runner(_FakeProcess(_response(), returncode=9))
        with self.assertRaises(WorkerDisposalRequired):
            runner.run(self.spec())

    def test_errors_never_reproduce_argv_environment_or_canaries(self):
        unsafe = "sensitive-value"
        runner, _ = self.fake_runner(_FakeProcess(b"unsafe protocol " + unsafe.encode()))
        observed = None
        try:
            runner.run(self.spec(argv=(sys.executable, "-c", unsafe), environment=(("TOKEN", unsafe),), secret_canaries=(unsafe,)))
        except BaseException as error:
            observed = error
        self.assertIsInstance(observed, WorkerDisposalRequired)
        self.assertEqual("command probe worker disposal required", str(observed))
        self.assertNotIn(unsafe, str(observed))

    def test_no_thread_or_callback_can_outlive_runner_return(self):
        source = Path(__file__).parents[2] / "scripts" / "g0" / "runner.py"
        text = source.read_text(encoding="utf-8")
        self.assertNotIn("threading", text)
        self.assertNotIn("ThreadPool", text)
        self.assertNotIn(".communicate(", text)
        self.assertNotIn("TemporaryFile", text)

    def test_live_supervisor_controls_cwd_environment_and_literal_argv(self):
        code = "import json,os,sys;print(json.dumps({'cwd':os.getcwd(),'visible':os.environ.get('VISIBLE'),'inherited':os.environ.get('INHERITED'),'arg':sys.argv[1]}))"
        literal = "; echo shell-injection"
        with mock.patch.dict(os.environ, {"INHERITED": "must-not-leak"}):
            Runner(run_root=self.root).run(self.spec("controlled", (sys.executable, "-c", code, literal), environment=(("VISIBLE", "yes"),)))
        value = json.loads((self.logs / "controlled.stdout.log").read_text(encoding="utf-8"))
        self.assertEqual(str(self.root), value["cwd"]); self.assertEqual("yes", value["visible"])
        self.assertIsNone(value["inherited"]); self.assertEqual(literal, value["arg"])

    def test_live_canary_is_not_retained_in_any_command_log(self):
        secret = "canary-value-not-for-logs"
        spec = self.spec("canary", (sys.executable, "-c", "import sys;print(sys.argv[1])", secret), secret_canaries=(secret,))
        with self.assertRaisesRegex(RunnerError, "exposed a canary"):
            Runner(run_root=self.root).run(spec)
        if self.logs.exists():
            self.assertEqual([], list(self.logs.glob("canary*")))
            self.assertNotIn(secret.encode(), b"".join(path.read_bytes() for path in self.logs.iterdir() if path.is_file()))

    @unittest.skipUnless(os.name == "nt", "Windows canary stdin pipe case runs only on Windows")
    def test_live_windows_canary_input_never_uses_a_named_spool_file(self):
        secret = b"stdin-canary-not-for-disk"
        code = "import sys;sys.stdout.buffer.write(sys.stdin.buffer.read())"
        spec = self.spec("stdin-canary", (sys.executable, "-c", code), secret_canaries=(secret.decode(),))
        with self.assertRaisesRegex(RunnerError, "exposed a canary"):
            Runner(run_root=self.root).run(spec, input_bytes=secret)
        self.assertNotIn("create_capture", (Path(__file__).parents[2] / "scripts" / "g0" / "supervisor.py").read_text(encoding="utf-8"))
        if self.logs.exists():
            self.assertEqual([], list(self.logs.iterdir()))

    def test_live_nonzero_exit_is_checked_after_logs_finalize(self):
        spec = self.spec("nonzero", (sys.executable, "-c", "import sys;print('bounded');sys.exit(7)"))
        with self.assertRaisesRegex(RunnerError, r"^command nonzero failed$"):
            Runner(run_root=self.root).run(spec)
        self.assertEqual(b"bounded" + os.linesep.encode(), (self.logs / "nonzero.stdout.log").read_bytes())

    def test_live_timeout_never_terminates_an_unrelated_concurrent_child(self):
        unrelated = subprocess.Popen((sys.executable, "-c", "import time;time.sleep(30)"))
        try:
            spec = self.spec("sibling-safe", (sys.executable, "-c", "import time;time.sleep(30)"), execution_timeout_seconds=1)
            with self.assertRaisesRegex(RunnerError, "timed out"):
                Runner(run_root=self.root).run(spec)
            self.assertIsNone(unrelated.poll())
        finally:
            unrelated.terminate()
            unrelated.wait(timeout=5)

    @unittest.skipUnless(os.name == "nt", "live Windows Job Object case runs only on Windows")
    def test_live_windows_timeout_kills_orphan_before_return(self):
        marker = self.root / "orphan-survived"
        child = "import pathlib,sys,time;time.sleep(2);pathlib.Path(sys.argv[1]).write_text('bad')"
        parent = "import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]);time.sleep(30)"
        spec = self.spec("windows-tree", (sys.executable, "-c", parent, child, str(marker)), execution_timeout_seconds=1)
        with self.assertRaisesRegex(RunnerError, "timed out"):
            Runner(run_root=self.root).run(spec)
        time.sleep(2.2)
        self.assertFalse(marker.exists())

    @unittest.skipIf(os.name == "nt", "live Linux cgroup case is unavailable on Windows")
    def test_live_linux_timeout_kills_orphan_and_removes_cgroup(self):
        marker = self.root / "orphan-survived"
        child = "import pathlib,sys,time;time.sleep(2);pathlib.Path(sys.argv[1]).write_text('bad')"
        parent = "import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]);time.sleep(30)"
        spec = self.spec("linux-tree", (sys.executable, "-c", parent, child, str(marker)), execution_timeout_seconds=1)
        with self.assertRaisesRegex(RunnerError, "timed out"):
            Runner(run_root=self.root).run(spec)
        time.sleep(2.2)
        self.assertFalse(marker.exists())

    @unittest.skipUnless(os.name == "nt", "live Windows log permissions run only on Windows")
    def test_live_windows_success_hashes_and_bounds_logs(self):
        spec = self.spec("windows-success", (sys.executable, "-c", "import sys;sys.stdout.write('abcdef')"), stdout_limit=3)
        result = Runner(run_root=self.root).run(spec)
        self.assertEqual(b"abc", (self.logs / "windows-success.stdout.log").read_bytes())
        self.assertEqual("sha256:" + hashlib.sha256(b"abcdef").hexdigest(), result.stdout_sha256)

    @unittest.skipUnless(os.name == "nt", "live Windows pipe capture runs only on Windows")
    def test_live_windows_pipe_capture_does_not_spool_unbounded_output(self):
        size = 5 * 1024 * 1024
        spec = self.spec(
            "windows-large-output",
            (sys.executable, "-c", f"import sys;sys.stdout.buffer.write(b'x'*{size})"),
            stdout_limit=7,
        )
        result = Runner(run_root=self.root).run(spec)
        self.assertEqual(b"x" * 7, (self.logs / "windows-large-output.stdout.log").read_bytes())
        self.assertEqual("sha256:" + hashlib.sha256(b"x" * size).hexdigest(), result.stdout_sha256)
        self.assertFalse(any(path.suffix == ".capture" for path in self.logs.iterdir()))

    @unittest.skipUnless(os.name == "nt", "live Windows continuous pipe case runs only on Windows")
    def test_live_windows_continuous_output_still_reaches_execution_timeout(self):
        code = "import os;chunk=b'x'*65536\nwhile True: os.write(1,chunk)"
        spec = self.spec("windows-continuous-output", (sys.executable, "-c", code), execution_timeout_seconds=1, stdout_limit=7)
        with self.assertRaisesRegex(RunnerError, "timed out"):
            Runner(run_root=self.root).run(spec)

    def test_live_controlled_input_is_written_completely(self):
        content = b"x" * 131_071
        code = "import sys;data=sys.stdin.buffer.read();print(len(data))"
        Runner(run_root=self.root).run(self.spec("input-complete", (sys.executable, "-c", code)), input_bytes=content)
        self.assertEqual(b"131071" + os.linesep.encode(), (self.logs / "input-complete.stdout.log").read_bytes())

    @unittest.skipUnless(os.name == "nt", "live Windows retained-log collision runs only on Windows")
    def test_existing_final_log_fails_before_target_release(self):
        self.logs.mkdir()
        existing = self.logs / "collision.stdout.log"
        existing.write_bytes(b"retained")
        marker = self.root / "target-ran"
        spec = self.spec("collision", (sys.executable, "-c", "import pathlib,sys;pathlib.Path(sys.argv[1]).write_text('bad')", str(marker)))
        with self.assertRaises(RunnerError):
            Runner(run_root=self.root).run(spec)
        self.assertEqual(b"retained", existing.read_bytes())
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
