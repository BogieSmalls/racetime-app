import hashlib
import json
import os
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from scripts.g0.runner import CommandSpec, Runner, RunnerError


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.log_directory = self.root / "logs"
        self.runner = Runner()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def spec(
        self,
        command_id,
        argv,
        *,
        timeout_seconds=5,
        environment=(),
        secret_canaries=(),
        stdout_limit=4096,
        stderr_limit=4096,
    ):
        return CommandSpec(
            command_id=command_id,
            argv=tuple(argv),
            cwd=self.root,
            timeout_seconds=timeout_seconds,
            environment=tuple(environment),
            secret_canaries=tuple(secret_canaries),
            stdout_limit=stdout_limit,
            stderr_limit=stderr_limit,
            log_directory=self.log_directory,
        )

    def log(self, command_id, stream):
        return self.log_directory / f"{command_id}.{stream}.log"

    def test_argv_is_not_interpreted_by_a_shell(self):
        shell_text = "; echo shell-injection"
        spec = self.spec(
            "literal-argv",
            (sys.executable, "-I", "-c", "import sys; print(sys.argv[1])", shell_text),
        )

        result = self.runner.run(spec)

        self.assertEqual(0, result.exit_code)
        self.assertEqual(
            (shell_text + os.linesep).encode(),
            self.log("literal-argv", "stdout").read_bytes(),
        )

    def test_string_argv_is_rejected_instead_of_being_reinterpreted(self):
        spec = CommandSpec(
            command_id="invalid-argv",
            argv=sys.executable,
            cwd=self.root,
            timeout_seconds=5,
            environment=(),
            secret_canaries=(),
            stdout_limit=100,
            stderr_limit=100,
            log_directory=self.log_directory,
        )

        with self.assertRaisesRegex(RunnerError, r"^command invalid-argv is invalid$"):
            self.runner.run(spec)

    def test_cwd_and_environment_are_explicitly_controlled(self):
        code = (
            "import json, os; "
            "print(json.dumps({'cwd': os.getcwd(), "
            "'visible': os.environ.get('RUNNER_VISIBLE'), "
            "'inherited': os.environ.get('RUNNER_INHERITED')}))"
        )
        spec = self.spec(
            "controlled-context",
            (sys.executable, "-I", "-c", code),
            environment=(("RUNNER_VISIBLE", "yes"),),
        )

        with mock.patch.dict(os.environ, {"RUNNER_INHERITED": "must-not-leak"}):
            self.runner.run(spec)

        observed = json.loads(
            self.log("controlled-context", "stdout").read_text(encoding="utf-8")
        )
        self.assertEqual(str(self.root.resolve()), observed["cwd"])
        self.assertEqual("yes", observed["visible"])
        self.assertIsNone(observed["inherited"])

    def test_timeout_kills_descendant_processes(self):
        marker = self.root / "descendant-survived"
        child_code = (
            "import pathlib, sys, time; "
            "time.sleep(2); pathlib.Path(sys.argv[1]).write_text('alive')"
        )
        parent_code = (
            "import subprocess, sys, time; "
            "subprocess.Popen([sys.executable, '-I', '-c', sys.argv[1], sys.argv[2]]); "
            "time.sleep(30)"
        )
        spec = self.spec(
            "tree-timeout",
            (sys.executable, "-I", "-c", parent_code, child_code, str(marker)),
            timeout_seconds=1,
        )

        with self.assertRaisesRegex(RunnerError, r"^command tree-timeout timed out$"):
            self.runner.run(spec)

        time.sleep(1.5)
        self.assertFalse(marker.exists(), "a descendant survived the timeout")

    def test_timeout_still_applies_after_direct_child_exits(self):
        marker = self.root / "orphaned-descendant-survived"
        child_code = (
            "import pathlib, sys, time; "
            "time.sleep(2); pathlib.Path(sys.argv[1]).write_text('alive')"
        )
        parent_code = (
            "import subprocess, sys; "
            "subprocess.Popen([sys.executable, '-I', '-c', sys.argv[1], sys.argv[2]])"
        )
        spec = self.spec(
            "orphan-timeout",
            (sys.executable, "-I", "-c", parent_code, child_code, str(marker)),
            timeout_seconds=1,
        )

        started = time.monotonic()
        with self.assertRaisesRegex(RunnerError, r"^command orphan-timeout timed out$"):
            self.runner.run(spec)

        self.assertLess(time.monotonic() - started, 2)
        time.sleep(1.5)
        self.assertFalse(marker.exists(), "an orphaned descendant survived the timeout")

    @unittest.skipUnless(os.name == "nt", "Windows Job Objects are Windows-only")
    def test_timeout_force_kills_orphan_that_ignores_break_signal(self):
        marker = self.root / "break-resistant-descendant-survived"
        child_code = (
            "import pathlib, signal, sys, time; "
            "signal.signal(signal.SIGBREAK, signal.SIG_IGN); "
            "time.sleep(2); pathlib.Path(sys.argv[1]).write_text('alive')"
        )
        parent_code = (
            "import subprocess, sys; "
            "subprocess.Popen([sys.executable, '-I', '-c', sys.argv[1], sys.argv[2]])"
        )
        spec = self.spec(
            "resistant-orphan-timeout",
            (sys.executable, "-I", "-c", parent_code, child_code, str(marker)),
            timeout_seconds=1,
        )

        with self.assertRaisesRegex(
            RunnerError,
            r"^command resistant-orphan-timeout timed out$",
        ):
            self.runner.run(spec)

        time.sleep(1.5)
        self.assertFalse(marker.exists(), "a break-resistant descendant survived")

    def test_thread_start_failure_is_sanitized_and_kills_launched_process(self):
        marker = self.root / "process-survived-thread-start-failure"
        unsafe_detail = "thread-secret-that-must-not-escape"
        code = (
            "import pathlib, sys, time; "
            "time.sleep(1); pathlib.Path(sys.argv[1]).write_text('alive')"
        )
        spec = self.spec(
            "thread-start",
            (sys.executable, "-I", "-c", code, str(marker)),
        )

        observed = None
        with mock.patch(
            "scripts.g0.runner._StreamCollector.start",
            side_effect=RuntimeError(unsafe_detail),
        ):
            try:
                self.runner.run(spec)
            except Exception as error:
                observed = error

        time.sleep(1.5)
        self.assertIsInstance(observed, RunnerError)
        self.assertEqual("command thread-start failed to initialize", str(observed))
        self.assertNotIn(unsafe_detail, str(observed))
        self.assertFalse(marker.exists(), "the launched process survived setup failure")

    def test_full_streams_are_hashed_while_logs_are_size_bounded(self):
        stdout = b"A" * 10000
        stderr = b"B" * 8000
        code = (
            "import os; "
            f"os.write(1, b'A' * {len(stdout)}); "
            f"os.write(2, b'B' * {len(stderr)})"
        )
        spec = self.spec(
            "bounded-output",
            (sys.executable, "-I", "-c", code),
            stdout_limit=17,
            stderr_limit=19,
        )

        result = self.runner.run(spec)

        self.assertEqual("sha256:" + hashlib.sha256(stdout).hexdigest(), result.stdout_sha256)
        self.assertEqual("sha256:" + hashlib.sha256(stderr).hexdigest(), result.stderr_sha256)
        self.assertEqual(stdout[:17], self.log("bounded-output", "stdout").read_bytes())
        self.assertEqual(stderr[:19], self.log("bounded-output", "stderr").read_bytes())

    def test_unencodable_canary_is_rejected_by_the_safe_error_boundary(self):
        canary = "\ud800do-not-display"
        spec = self.spec(
            "invalid-canary",
            (sys.executable, "-I", "-c", "print('not-run')"),
            secret_canaries=(canary,),
        )

        with self.assertRaisesRegex(RunnerError, r"^command invalid-canary is invalid$") as raised:
            self.runner.run(spec)

        self.assertNotIn(canary, str(raised.exception))

    def test_secret_canary_anywhere_in_output_fails_without_reproduction(self):
        canary = "canary-value-that-must-not-escape"
        code = (
            "import os; "
            "os.write(1, b'x' * 128 + " + repr(canary.encode()) + "); "
            "os.write(2, b'diagnostic')"
        )
        spec = self.spec(
            "canary-check",
            (sys.executable, "-I", "-c", code),
            secret_canaries=(canary,),
            stdout_limit=8,
        )

        with self.assertRaisesRegex(RunnerError, r"^command canary-check exposed a canary$") as raised:
            self.runner.run(spec)

        self.assertNotIn(canary, str(raised.exception))
        self.assertFalse(self.log("canary-check", "stdout").exists())
        self.assertFalse(self.log("canary-check", "stderr").exists())

    def test_nonzero_exit_is_checked_and_exception_contains_only_safe_id(self):
        secret_argument = "top-secret-argument"
        code = "import os, sys; os.write(2, sys.argv[1].encode()); raise SystemExit(7)"
        spec = self.spec(
            "checked-exit",
            (sys.executable, "-I", "-c", code, secret_argument),
        )

        with self.assertRaises(RunnerError) as raised:
            self.runner.run(spec)

        self.assertEqual("command checked-exit failed", str(raised.exception))
        self.assertNotIn(secret_argument, str(raised.exception))
        self.assertNotIn(str(self.root), str(raised.exception))

    @unittest.skipIf(os.name == "nt", "POSIX permission bits are not meaningful on Windows")
    def test_logs_are_owner_read_write_only_on_posix(self):
        spec = self.spec(
            "private-logs",
            (sys.executable, "-I", "-c", "print('private')"),
        )

        self.runner.run(spec)

        for stream in ("stdout", "stderr"):
            mode = stat.S_IMODE(self.log("private-logs", stream).stat().st_mode)
            self.assertEqual(0o600, mode)


if __name__ == "__main__":
    unittest.main()
