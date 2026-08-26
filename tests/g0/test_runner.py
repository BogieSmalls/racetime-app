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

import scripts.g0.runner as runner_module

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

    def test_lineage_tracker_binds_only_root_descendants_and_new_adoptions(self):
        identity = runner_module._ProcessIdentity
        record = runner_module._ProcessRecord
        baseline_child = identity(pid=20, start_time=200)
        root = identity(pid=10, start_time=100)
        child = identity(pid=11, start_time=110)
        unrelated_child = identity(pid=21, start_time=210)
        tracker = runner_module._LineageTracker(
            runner_pid=1000,
            baseline_children=frozenset({baseline_child}),
        )
        tracker.bind_root(root)

        owned = tracker.update(
            {
                root: record(identity=root, parent_pid=1000, state="S"),
                child: record(identity=child, parent_pid=root.pid, state="S"),
                baseline_child: record(
                    identity=baseline_child,
                    parent_pid=1000,
                    state="S",
                ),
                unrelated_child: record(
                    identity=unrelated_child,
                    parent_pid=baseline_child.pid,
                    state="S",
                ),
            }
        )

        self.assertEqual({root, child}, owned)

        daemon = identity(pid=12, start_time=120)
        owned = tracker.update(
            {
                child: record(identity=child, parent_pid=1000, state="S"),
                daemon: record(identity=daemon, parent_pid=1000, state="S"),
                unrelated_child: record(
                    identity=unrelated_child,
                    parent_pid=1000,
                    state="S",
                ),
                baseline_child: record(
                    identity=baseline_child,
                    parent_pid=1000,
                    state="S",
                ),
            }
        )

        self.assertEqual({child, daemon}, owned)
        self.assertNotIn(baseline_child, tracker.owned)
        self.assertNotIn(unrelated_child, tracker.owned)

    def test_linux_stat_parser_accepts_non_ascii_process_names(self):
        fields = [b"S", b"42", *([b"0"] * 17), b"999"]
        content = b"123 (daemon-\xff) " + b" ".join(fields)

        record = runner_module._parse_linux_stat(content, pid=123)

        self.assertEqual(
            runner_module._ProcessIdentity(pid=123, start_time=999),
            record.identity,
        )
        self.assertEqual(42, record.parent_pid)
        self.assertEqual("S", record.state)

    def test_linux_identity_signal_uses_pidfd_across_pid_reuse(self):
        identity = runner_module._ProcessIdentity
        record = runner_module._ProcessRecord
        original = identity(pid=55, start_time=100)
        reused = identity(pid=55, start_time=101)
        current = {55: original}
        opened = []
        signalled = []
        closed = []

        def open_pidfd(pid, flags):
            opened.append((pid, flags))
            return 73

        def read_record(pid):
            observed = current[pid]
            current[pid] = reused
            return record(identity=observed, parent_pid=1, state="S")

        def send_signal(pidfd, signal_number, siginfo, flags):
            signalled.append((pidfd, signal_number, siginfo, flags))

        runner_module._signal_linux_identity(
            original,
            open_pidfd=open_pidfd,
            read_record=read_record,
            send_signal=send_signal,
            close_pidfd=closed.append,
        )

        self.assertEqual([(55, 0)], opened)
        self.assertEqual([(73, 9, None, 0)], signalled)
        self.assertEqual([73], closed)
        self.assertEqual(reused, current[55], "the numeric PID was reused before signal")

        signalled.clear()
        runner_module._signal_linux_identity(
            original,
            open_pidfd=lambda pid, flags: 74,
            read_record=lambda pid: record(
                identity=reused,
                parent_pid=1,
                state="S",
            ),
            send_signal=lambda *args: signalled.append(args),
            close_pidfd=closed.append,
        )
        self.assertEqual([], signalled, "a reused PID identity must not be signalled")
        self.assertEqual([73, 74], closed)

    def test_linux_baseline_rejects_preexisting_direct_children(self):
        identity = runner_module._ProcessIdentity
        record = runner_module._ProcessRecord
        runner = identity(pid=1000, start_time=10)
        preexisting = identity(pid=20, start_time=200)
        records = {
            runner: record(identity=runner, parent_pid=1, state="S"),
            preexisting: record(
                identity=preexisting,
                parent_pid=runner.pid,
                state="S",
            ),
        }

        with self.assertRaises(runner_module._LinuxOwnershipError):
            runner_module._safe_linux_baseline(records, runner.pid)

        self.assertEqual(
            frozenset({preexisting}),
            runner_module._safe_linux_baseline(
                {
                    preexisting: record(
                        identity=preexisting,
                        parent_pid=1,
                        state="S",
                    )
                },
                runner.pid,
            ),
        )

    def test_linux_ownership_failure_stops_before_process_launch(self):
        spec = self.spec(
            "linux-owner-unavailable",
            (sys.executable, "-I", "-c", "raise SystemExit('not-run')"),
        )

        with (
            mock.patch.object(runner_module.sys, "platform", "linux"),
            mock.patch.object(
                runner_module,
                "_LinuxProcessOwner",
                side_effect=runner_module._LinuxOwnershipError("unsafe detail"),
                create=True,
            ),
            mock.patch("scripts.g0.runner.subprocess.Popen") as popen,
        ):
            with self.assertRaisesRegex(
                RunnerError,
                r"^command linux-owner-unavailable could not start$",
            ):
                self.runner.run(spec)

        popen.assert_not_called()

    def test_non_linux_posix_stops_before_process_launch(self):
        spec = self.spec(
            "unsupported-posix",
            (sys.executable, "-I", "-c", "raise SystemExit('not-run')"),
        )

        with (
            mock.patch.object(runner_module.sys, "platform", "darwin"),
            mock.patch.object(runner_module.os, "name", "posix"),
            mock.patch("scripts.g0.runner.subprocess.Popen") as popen,
        ):
            with self.assertRaisesRegex(
                RunnerError,
                r"^command unsupported-posix could not start$",
            ):
                self.runner.run(spec)

        popen.assert_not_called()

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux subreaper regression")
    def test_linux_timeout_kills_daemonized_new_session_with_closed_stdio(self):
        marker = self.root / "linux-daemon-survived"
        daemon_code = (
            "import ctypes, pathlib, sys, time; "
            "libc=ctypes.CDLL(None); "
            "libc.prctl.argtypes=(ctypes.c_int, ctypes.c_ulong, "
            "ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong); "
            "name=ctypes.create_string_buffer(b'\\xffdaemon'); "
            "result=libc.prctl(15, ctypes.addressof(name), 0, 0, 0); "
            "assert result == 0; "
            "time.sleep(2); pathlib.Path(sys.argv[1]).write_text('alive')"
        )
        parent_code = (
            "import subprocess, sys; "
            "subprocess.Popen([sys.executable, '-I', '-c', sys.argv[1], sys.argv[2]], "
            "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
            "stderr=subprocess.DEVNULL, start_new_session=True)"
        )
        spec = self.spec(
            "linux-daemon-timeout",
            (sys.executable, "-I", "-c", parent_code, daemon_code, str(marker)),
            timeout_seconds=1,
        )

        try:
            observed = self.runner.run(spec)
        except Exception as error:
            observed = error

        time.sleep(1.5)
        self.assertIsInstance(observed, RunnerError)
        self.assertEqual("command linux-daemon-timeout timed out", str(observed))
        self.assertFalse(marker.exists(), "a daemonized Linux descendant survived")

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
