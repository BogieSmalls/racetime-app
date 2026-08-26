import errno
import hashlib
import os
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

import scripts.g0.supervisor as supervisor


class CaptureTests(unittest.TestCase):
    def test_full_stream_is_hashed_while_log_is_bounded_and_split_canary_is_seen(self):
        capture = supervisor.StreamCapture(limit=3, canaries=(b"secret",))
        capture.feed(b"abcse"); capture.feed(b"cretxyz"); capture.finish()
        self.assertEqual(b"abc", capture.retained)
        self.assertEqual(hashlib.sha256(b"abcsecretxyz").hexdigest(), capture.hexdigest)
        self.assertTrue(capture.canary_seen); self.assertTrue(capture.eof)


class CgroupTests(unittest.TestCase):
    def test_pidfd_is_closed_when_identity_or_verification_fails_before_ownership_transfer(self):
        for read_identity, signal_pidfd, expected_exception in (
            (lambda pid: (_ for _ in ()).throw(FileNotFoundError()), lambda fd, sig: None, None),
            (lambda pid: (pid, 1), lambda fd, sig: (_ for _ in ()).throw(OSError("injected")), supervisor.SupervisorDisposalRequired),
        ):
            closed = []
            registry = supervisor.PidfdRegistry(
                open_pidfd=lambda pid: 70,
                read_identity=read_identity,
                signal_pidfd=signal_pidfd,
                close_pidfd=closed.append,
            )
            if expected_exception is None:
                self.assertFalse(registry.retain(55))
            else:
                with self.assertRaises(expected_exception):
                    registry.retain(55)
            self.assertEqual([70], closed)
            self.assertEqual(frozenset(), registry.identities)

    def test_kill_requires_exact_empty_reap_and_removal_proof(self):
        events = iter(("populated 1\n", "populated 0\n", "populated 0\n")); writes = []; removed = []
        group = supervisor.LinuxCgroup(
            path=Path("/sys/fs/cgroup/g0-test"), read_text=lambda name: next(events),
            write_text=lambda name, value: writes.append((name, value)), list_pids=lambda: (),
            remove=lambda: removed.append(True), monotonic=lambda: 0.0, sleep=lambda _: None,
        )
        group.kill_empty_remove(1.0)
        self.assertEqual([("cgroup.kill", "1")], writes); self.assertEqual([True], removed)

    def test_nonempty_cgroup_and_simulated_d_state_require_disposal(self):
        group = supervisor.LinuxCgroup(
            path=Path("/sys/fs/cgroup/g0-test"), read_text=lambda name: "populated 1\n",
            write_text=lambda name, value: None, list_pids=lambda: (42,), remove=lambda: None,
            process_state=lambda pid: "D", monotonic=lambda: 1.0, sleep=lambda _: None,
        )
        with self.assertRaises(supervisor.SupervisorDisposalRequired): group.kill_empty_remove(1.0)

    def test_pidfd_is_retained_at_discovery_and_pid_reuse_is_rejected(self):
        closed = []
        registry = supervisor.PidfdRegistry(open_pidfd=lambda pid: 70, read_identity=lambda pid: (pid, 100), signal_pidfd=lambda fd, sig: None, close_pidfd=closed.append)
        self.assertTrue(registry.retain(55, expected_identity=(55, 100)))
        self.assertFalse(registry.retain(55, expected_identity=(55, 101)))
        registry.close_all(); self.assertEqual([70], closed)

    def test_process_vanishing_between_cgroup_snapshot_and_pidfd_retain_is_safe(self):
        registry = supervisor.PidfdRegistry(
            open_pidfd=lambda pid: (_ for _ in ()).throw(ProcessLookupError()),
            read_identity=lambda pid: (_ for _ in ()).throw(FileNotFoundError()),
            signal_pidfd=lambda fd, sig: None,
            close_pidfd=lambda fd: None,
        )
        self.assertFalse(registry.retain(55))

    def test_pid_reuse_retains_both_old_and_new_pidfds_without_numeric_signal(self):
        current = {55: (55, 100)}; opened = iter((70, 71)); closed = []; signalled = []
        def send(descriptor, number):
            signalled.append((descriptor, number))
            if descriptor == 70 and current[55] == (55, 101):
                raise ProcessLookupError()
        registry = supervisor.PidfdRegistry(open_pidfd=lambda pid: next(opened), read_identity=lambda pid: current[pid], signal_pidfd=send, close_pidfd=closed.append)
        self.assertTrue(registry.retain(55)); current[55] = (55, 101)
        self.assertTrue(registry.retain(55))
        self.assertEqual(frozenset({(55, 100), (55, 101)}), registry.identities)
        registry.close_all(); self.assertEqual([70, 71], closed)
        self.assertNotIn((55, 9), signalled)

    def test_unrelated_concurrent_pid_is_never_added_without_cgroup_membership(self):
        opened = []
        registry = supervisor.PidfdRegistry(open_pidfd=lambda pid: opened.append(pid) or pid, read_identity=lambda pid: (pid, 1), signal_pidfd=lambda fd, sig: None, close_pidfd=lambda fd: None)
        registry.refresh((10, 11)); registry.refresh((10, 11))
        self.assertEqual([10, 11], opened); self.assertNotIn(99, registry.identities)


class JobTests(unittest.TestCase):
    def test_windows_termination_empty_and_close_failures_are_disposal(self):
        for operation in ("terminate", "wait_empty", "close"):
            job = supervisor.WindowsJobBoundary(
                terminate=lambda: operation != "terminate", active_count=lambda: (1 if operation == "wait_empty" else 0),
                close=lambda: operation != "close", monotonic=lambda: 1.0, sleep=lambda _: None,
            )
            with self.subTest(operation=operation):
                with self.assertRaises(supervisor.SupervisorDisposalRequired): job.terminate_empty_close(1.0)

    def test_windows_wait_timeout_is_rechecked_against_monotonic_deadline(self):
        moments = iter((1.0, 1.1))
        waits = iter((supervisor._WAIT_TIMEOUT, supervisor._WAIT_OBJECT_0))
        self.assertTrue(supervisor.wait_windows_process_until(
            123,
            2.0,
            wait=lambda handle, milliseconds: next(waits),
            monotonic=lambda: next(moments),
        ))

    def test_windows_wait_reports_timeout_only_at_the_deadline(self):
        self.assertFalse(supervisor.wait_windows_process_until(
            123,
            2.0,
            wait=lambda handle, milliseconds: supervisor._WAIT_TIMEOUT,
            monotonic=iter((1.9, 2.0)).__next__,
        ))

    def test_windows_completion_poll_precedes_deadline_classification(self):
        self.assertTrue(supervisor.wait_windows_process_until(
            123,
            1.0,
            wait=lambda handle, milliseconds: supervisor._WAIT_OBJECT_0,
            monotonic=lambda: 2.0,
        ))

    def test_windows_completion_between_first_poll_and_expiry_is_not_timeout(self):
        waits = iter((supervisor._WAIT_TIMEOUT, supervisor._WAIT_OBJECT_0))
        self.assertTrue(supervisor.wait_windows_process_until(
            123,
            1.0,
            wait=lambda handle, milliseconds: next(waits),
            monotonic=lambda: 2.0,
        ))


class SecureLogTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "Linux retained-dirfd case is unavailable on Windows")
    def test_posix_logs_finalize_0600_with_retained_directory_handles(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); store = supervisor.PosixLogStore(root, root / "logs")
            store.finalize("probe", b"out", b"err")
            stdout = root / "logs" / "probe.stdout.log"
            self.assertEqual(b"out", stdout.read_bytes()); self.assertEqual(0o600, stdout.stat().st_mode & 0o777)
            store.close()

    def test_network_and_outside_paths_are_rejected(self):
        with self.assertRaises(supervisor.SupervisorOrdinaryFailure): supervisor.validate_log_paths(Path("C:/run"), Path("//server/share/logs"), platform="windows")
        with self.assertRaises(supervisor.SupervisorOrdinaryFailure): supervisor.validate_log_paths(Path("/run/g0"), Path("/tmp/outside"), platform="linux")
        with self.assertRaises(supervisor.SupervisorOrdinaryFailure): supervisor.validate_log_paths(Path("/run/g0"), Path("/run/g0/logs/../../outside"), platform="linux")

    def test_mount_identity_or_network_filesystem_mismatch_is_rejected(self):
        with self.assertRaises(supervisor.SupervisorOrdinaryFailure): supervisor.require_local_mount("nfs", 2, 2)
        with self.assertRaises(supervisor.SupervisorOrdinaryFailure): supervisor.require_local_mount("ext4", 2, 3)

    def test_canary_cleanup_requires_unlink_directory_fsync_and_absence(self):
        calls = []
        cleanup = supervisor.CanaryLogCleanup(unlink=lambda name: calls.append(("unlink", name)), fsync_directory=lambda: calls.append(("fsync", None)), exists=lambda name: False)
        cleanup.remove_and_prove(("a.tmp", "a.log")); self.assertEqual(("fsync", None), calls[-1])
        failing = supervisor.CanaryLogCleanup(unlink=lambda name: None, fsync_directory=lambda: None, exists=lambda name: True)
        with self.assertRaises(supervisor.SupervisorDisposalRequired): failing.remove_and_prove(("a.log",))

    def test_symlink_and_finalize_syscall_failures_are_disposal(self):
        with self.assertRaises(supervisor.SupervisorDisposalRequired): supervisor.classify_log_proof_failure(OSError(errno.ELOOP, "symlink"))
        with self.assertRaises(supervisor.SupervisorDisposalRequired): supervisor.classify_log_proof_failure(OSError(errno.EIO, "fsync"))

    @unittest.skipIf(os.name == "nt", "Linux POSIX syscall injection is unavailable on Windows")
    def test_posix_fsync_publish_and_close_failures_are_directly_disposal(self):
        for operation in ("fsync", "publish"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve(); store = supervisor.PosixLogStore(root, root / "logs")
                target = "os.fsync" if operation == "fsync" else "_link_descriptor_at"
                with mock.patch(f"scripts.g0.supervisor.{target}", side_effect=OSError(errno.EIO, operation)):
                    with self.assertRaises(supervisor.SupervisorDisposalRequired):
                        store.finalize(operation, b"out", b"err")
                store.close()

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); store = supervisor.PosixLogStore(root, root / "logs")
            failing_descriptor = store._directory_fd; original_close = os.close
            def injected_close(descriptor):
                if descriptor == failing_descriptor:
                    raise OSError(errno.EIO, "close")
                return original_close(descriptor)
            try:
                with mock.patch.object(supervisor.os, "close", side_effect=injected_close):
                    with self.assertRaises(supervisor.SupervisorDisposalRequired):
                        store.close()
            finally:
                original_close(failing_descriptor)

    @unittest.skipUnless(os.name == "nt", "Windows retained-handle race runs only on Windows")
    def test_windows_retained_ancestor_blocks_rename_until_close(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); logs = root / "logs"
            store = supervisor.WindowsLogStore(root, logs)
            with self.assertRaises(OSError):
                logs.rename(root / "moved")
            store.close()
            logs.rename(root / "moved")

    @unittest.skipUnless(os.name == "nt", "Windows finalization injection runs only on Windows")
    def test_windows_flush_and_handle_rename_failures_are_disposal(self):
        for operation in ("flush", "rename"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve(); store = supervisor.WindowsLogStore(root, root / "logs")
                target = "_flush_file" if operation == "flush" else "_set_file_info"
                with mock.patch.object(supervisor, target, return_value=False):
                    with self.assertRaises(supervisor.SupervisorDisposalRequired):
                        store._write_final(f"{operation}.log", b"evidence")
                store.close()

    def test_cleanup_deadline_is_checked_after_blocking_proof_steps(self):
        with self.assertRaises(supervisor.SupervisorDisposalRequired):
            supervisor.require_before_deadline(1.0, monotonic=lambda: 1.0)

    @unittest.skipIf(os.name == "nt", "Linux retained-dirfd ownership case is unavailable on Windows")
    def test_posix_existing_log_directory_must_be_owner_private(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            logs = root / "logs"; logs.mkdir(mode=0o755)
            with self.assertRaises(supervisor.SupervisorOrdinaryFailure):
                supervisor.PosixLogStore(root, logs)

    @unittest.skipIf(os.name == "nt", "Linux retained-dirfd race cases are unavailable on Windows")
    def test_posix_ancestor_and_final_symlink_swaps_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); logs = root / "logs"
            store = supervisor.PosixLogStore(root, logs)
            moved = root / "moved"; logs.rename(moved); logs.mkdir(mode=0o700)
            with self.assertRaises(supervisor.SupervisorDisposalRequired):
                store.finalize("ancestor", b"out", b"err")
            store.close()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); target = root / "target"; target.write_bytes(b"safe")
            store = supervisor.PosixLogStore(root, root / "logs")
            store.prepare("final")
            (root / "logs" / "final.stdout.log").symlink_to(target)
            with self.assertRaises(supervisor.SupervisorDisposalRequired):
                store.finalize("final", b"bad", b"err")
            self.assertEqual(b"safe", target.read_bytes())
            store.close()

    @unittest.skipIf(os.name == "nt", "Linux retained cgroup identity case is unavailable on Windows")
    def test_retained_cgroup_name_replacement_is_disposal(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary); child = parent / "child"; child.mkdir()
            group = supervisor.LinuxCgroup.retain(child)
            child.rename(parent / "moved"); child.mkdir()
            with self.assertRaises(supervisor.SupervisorDisposalRequired):
                group._verify_retained_name()
            group.close()


class ProtocolTests(unittest.TestCase):
    def test_expired_execution_deadline_never_calls_irreversible_release(self):
        release = mock.Mock()
        with self.assertRaises(supervisor.SupervisorOrdinaryFailure):
            supervisor._release_before_deadline(10.0, release, monotonic=lambda: 10.0)
        release.assert_not_called()
        supervisor._release_before_deadline(10.0, release, monotonic=lambda: 9.999)
        release.assert_called_once_with()

    @unittest.skipUnless(sys.platform == "win32", "Windows diagnostic")
    def test_windows_direct_supervisor_diagnostic(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            request = {"protocol_version": 1, "command_id": "direct", "argv": [sys.executable, "-c", "print(1)"], "cwd": str(root), "run_root": str(root), "execution_timeout_seconds": 5, "cleanup_timeout_seconds": 5, "environment": [], "secret_canaries_b64": [], "input_b64": None, "stdout_limit": 10, "stderr_limit": 10, "log_directory": str(root / "logs")}
            result = supervisor._execute_windows(request, time.monotonic())
            self.assertEqual("PASS", result["status"])

    def test_request_requires_exact_fields_and_timeout_ranges(self):
        root = (Path(tempfile.gettempdir()).resolve() / "g0-request")
        request = {"protocol_version": 1, "command_id": "probe", "argv": [sys.executable, "-c", "print(1)"], "cwd": str(root), "run_root": str(root), "execution_timeout_seconds": 1, "cleanup_timeout_seconds": 5, "environment": [], "secret_canaries_b64": [], "input_b64": None, "stdout_limit": 1, "stderr_limit": 1, "log_directory": str(root / "logs")}
        self.assertEqual("probe", supervisor.validate_request(request)["command_id"])
        for key, value in (("execution_timeout_seconds", 0), ("cleanup_timeout_seconds", 601)):
            changed = dict(request); changed[key] = value
            with self.assertRaises(supervisor.SupervisorOrdinaryFailure): supervisor.validate_request(changed)
        changed = dict(request); changed["protocol_version"] = True
        with self.assertRaises(supervisor.SupervisorOrdinaryFailure): supervisor.validate_request(changed)

    def test_missing_platform_primitives_fail_before_target_release(self):
        boundary = supervisor.ReleaseGate()
        with self.assertRaises(supervisor.SupervisorOrdinaryFailure): boundary.release()
        self.assertFalse(boundary.released)

    def test_missing_linux_cgroup_primitive_fails_before_forking_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); retained_root = 101; cwd_fd = 102
            class FakeStore:
                _root_fd = retained_root
                def prepare(self, command_id): pass
                def close(self): pass
            request = {"protocol_version": 1, "command_id": "probe", "argv": [sys.executable, "-c", "print(1)"], "cwd": str(root), "run_root": str(root), "execution_timeout_seconds": 1, "cleanup_timeout_seconds": 5, "environment": [], "secret_canaries_b64": [], "input_b64": None, "stdout_limit": 1, "stderr_limit": 1, "log_directory": str(root / "logs")}
            fork = mock.Mock()
            with (
                mock.patch.object(supervisor, "_ACTIVE_CLEANUP_DEADLINE", None),
                mock.patch.object(supervisor, "_ensure_linux_primitives"),
                mock.patch.object(supervisor, "PosixLogStore", return_value=FakeStore()),
                mock.patch.object(supervisor, "_open_directory_beneath", return_value=cwd_fd),
                mock.patch.object(supervisor, "_mount_id", return_value=1),
                mock.patch.object(supervisor, "_create_linux_cgroup", side_effect=supervisor.SupervisorOrdinaryFailure("missing")),
                mock.patch.object(supervisor, "_close_descriptors", side_effect=lambda descriptors: descriptors.clear()),
                mock.patch.object(supervisor.os, "fork", fork, create=True),
            ):
                with self.assertRaises(supervisor.SupervisorOrdinaryFailure):
                    supervisor._execute_linux(request, time.monotonic())
            fork.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows Job primitive injection runs only on Windows")
    def test_missing_windows_job_primitive_fails_before_createprocess(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            request = {"protocol_version": 1, "command_id": "probe", "argv": [sys.executable, "-c", "print(1)"], "cwd": str(root), "run_root": str(root), "execution_timeout_seconds": 1, "cleanup_timeout_seconds": 5, "environment": [], "secret_canaries_b64": [], "input_b64": None, "stdout_limit": 1, "stderr_limit": 1, "log_directory": str(root / "logs")}
            create_process = mock.Mock()
            class FakeStore:
                def __init__(self, *_): pass
                def prepare(self, _): pass
                def retain_cwd(self, _): pass
                def close(self): pass
            with (
                mock.patch.object(supervisor, "_ACTIVE_CLEANUP_DEADLINE", None),
                mock.patch.object(supervisor, "WindowsLogStore", FakeStore),
                mock.patch.object(supervisor, "_create_job", return_value=0),
                mock.patch.object(supervisor._winapi, "CreateProcess", create_process),
                mock.patch.object(supervisor.os, "pipe", side_effect=((11, 12), (13, 14), (15, 16))),
                mock.patch.object(supervisor.os, "set_blocking"),
                mock.patch.object(supervisor.os, "set_inheritable"),
                mock.patch.object(supervisor.os, "close"),
            ):
                with self.assertRaises(supervisor.SupervisorOrdinaryFailure):
                    supervisor._execute_windows(request, time.monotonic())
            create_process.assert_not_called()

    def test_release_is_latched_before_the_os_action_can_make_target_runnable(self):
        boundary = supervisor.ReleaseGate(); boundary.mark_contained()
        with self.assertRaises(OSError):
            boundary.release_with(lambda: (_ for _ in ()).throw(OSError("injected")))
        self.assertTrue(boundary.released)

if __name__ == "__main__": unittest.main()
