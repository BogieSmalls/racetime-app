"""Bounded, fail-closed command execution for the G0 worker."""

from __future__ import annotations

import hashlib
import os
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path


_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_TERMINATION_GRACE_SECONDS = 1.0
_LINUX_SIGKILL = 9


@dataclass(frozen=True)
class _ProcessIdentity:
    pid: int
    start_time: int


@dataclass(frozen=True)
class _ProcessRecord:
    identity: _ProcessIdentity
    parent_pid: int
    state: str


class _LineageTracker:
    """Bind a root and its descendants without trusting reusable PIDs."""

    def __init__(
        self,
        *,
        runner_pid: int,
        baseline_children: frozenset[_ProcessIdentity],
    ) -> None:
        self._runner_pid = runner_pid
        self._excluded = set(baseline_children)
        self._owned: set[_ProcessIdentity] = set()

    @property
    def owned(self) -> frozenset[_ProcessIdentity]:
        return frozenset(self._owned)

    def bind_root(self, identity: _ProcessIdentity) -> None:
        self._owned.add(identity)

    def update(
        self,
        records: dict[_ProcessIdentity, _ProcessRecord],
    ) -> set[_ProcessIdentity]:
        current_by_pid = {identity.pid: identity for identity in records}
        changed = True
        while changed:
            changed = False
            for identity, record in records.items():
                if identity in self._owned or identity in self._excluded:
                    continue
                parent_identity = current_by_pid.get(record.parent_pid)
                if parent_identity in self._excluded:
                    self._excluded.add(identity)
                    changed = True
                    continue
                is_descendant = parent_identity in self._owned
                is_new_adoption = (
                    record.parent_pid == self._runner_pid
                    and identity not in self._excluded
                )
                if is_descendant or is_new_adoption:
                    self._owned.add(identity)
                    changed = True
        return {identity for identity in self._owned if identity in records}


class _LinuxOwnershipError(RuntimeError):
    """Raised when Linux process ownership cannot be proved."""


def _parse_linux_stat(content: bytes, *, pid: int) -> _ProcessRecord:
    closing_parenthesis = content.rfind(b")")
    if closing_parenthesis < 2:
        raise _LinuxOwnershipError("Linux process stat is malformed")
    fields = content[closing_parenthesis + 2 :].split()
    if len(fields) < 20:
        raise _LinuxOwnershipError("Linux process stat is incomplete")
    try:
        state = fields[0].decode("ascii")
        parent_pid = int(fields[1])
        start_time = int(fields[19])
    except (UnicodeError, ValueError) as error:
        raise _LinuxOwnershipError(
            "Linux process stat contains invalid fields"
        ) from error
    identity = _ProcessIdentity(pid=pid, start_time=start_time)
    return _ProcessRecord(
        identity=identity,
        parent_pid=parent_pid,
        state=state,
    )


def _signal_linux_identity(
    identity: _ProcessIdentity,
    *,
    open_pidfd,
    read_record,
    send_signal,
    close_pidfd,
) -> None:
    try:
        pidfd = open_pidfd(identity.pid, 0)
    except (FileNotFoundError, ProcessLookupError):
        return
    except OSError as error:
        raise _LinuxOwnershipError("Linux pidfd cannot be opened") from error
    try:
        try:
            current = read_record(identity.pid)
        except (FileNotFoundError, ProcessLookupError):
            return
        except OSError as error:
            raise _LinuxOwnershipError(
                "Linux process identity cannot be rechecked"
            ) from error
        if current.identity != identity:
            return
        try:
            send_signal(pidfd, _LINUX_SIGKILL, None, 0)
        except ProcessLookupError:
            return
        except OSError as error:
            raise _LinuxOwnershipError(
                "Linux pidfd termination failed"
            ) from error
    finally:
        try:
            close_pidfd(pidfd)
        except OSError as error:
            raise _LinuxOwnershipError(
                "Linux pidfd cannot be closed"
            ) from error


def _safe_linux_baseline(
    records: dict[_ProcessIdentity, _ProcessRecord],
    runner_pid: int,
) -> frozenset[_ProcessIdentity]:
    if any(record.parent_pid == runner_pid for record in records.values()):
        raise _LinuxOwnershipError(
            "Linux runner already has a child process"
        )
    return frozenset(
        identity for identity in records if identity.pid != runner_pid
    )


if sys.platform == "linux":
    import ctypes as _linux_ctypes
    import errno as _linux_errno

    _PR_SET_CHILD_SUBREAPER = 36
    _PR_GET_CHILD_SUBREAPER = 37
    try:
        _linux_libc = _linux_ctypes.CDLL(None, use_errno=True)
        _linux_prctl = _linux_libc.prctl
    except (AttributeError, OSError):
        _linux_prctl = None
    else:
        _linux_prctl.argtypes = (
            _linux_ctypes.c_int,
            _linux_ctypes.c_ulong,
            _linux_ctypes.c_ulong,
            _linux_ctypes.c_ulong,
            _linux_ctypes.c_ulong,
        )
        _linux_prctl.restype = _linux_ctypes.c_int

    class _LinuxProcessOwner:
        """Own one Linux command tree with subreaper adoption and /proc identity."""

        _POLL_SECONDS = 0.01

        def __init__(self) -> None:
            self.runner_pid = os.getpid()
            self._ensure_pidfd_primitives()
            self._ensure_subreaper()
            records = self._read_table()
            baseline_children = _safe_linux_baseline(records, self.runner_pid)
            self.tracker = _LineageTracker(
                runner_pid=self.runner_pid,
                baseline_children=baseline_children,
            )
            self.root_identity: _ProcessIdentity | None = None

        @staticmethod
        def _prctl(option: int, argument: int) -> None:
            if _linux_prctl is None:
                raise _LinuxOwnershipError("Linux prctl is unavailable")
            result = _linux_prctl(option, argument, 0, 0, 0)
            if result != 0:
                raise _LinuxOwnershipError("Linux subreaper control failed")

        @classmethod
        def _ensure_subreaper(cls) -> None:
            current = _linux_ctypes.c_int()
            address = _linux_ctypes.addressof(current)
            cls._prctl(_PR_GET_CHILD_SUBREAPER, address)
            if current.value != 1:
                cls._prctl(_PR_SET_CHILD_SUBREAPER, 1)
                current = _linux_ctypes.c_int()
                cls._prctl(
                    _PR_GET_CHILD_SUBREAPER,
                    _linux_ctypes.addressof(current),
                )
            if current.value != 1:
                raise _LinuxOwnershipError("Linux subreaper verification failed")

        @staticmethod
        def _ensure_pidfd_primitives() -> None:
            open_pidfd = getattr(os, "pidfd_open", None)
            send_signal = getattr(signal, "pidfd_send_signal", None)
            if not callable(open_pidfd) or not callable(send_signal):
                raise _LinuxOwnershipError("Linux pidfd is unavailable")
            pidfd = None
            try:
                pidfd = open_pidfd(os.getpid(), 0)
                send_signal(pidfd, 0, None, 0)
            except OSError as error:
                raise _LinuxOwnershipError(
                    "Linux pidfd verification failed"
                ) from error
            finally:
                if pidfd is not None:
                    try:
                        os.close(pidfd)
                    except OSError as error:
                        raise _LinuxOwnershipError(
                            "Linux pidfd verification cleanup failed"
                        ) from error

        @staticmethod
        def _read_record(path: Path) -> _ProcessRecord:
            try:
                pid = int(path.parent.name)
            except ValueError as error:
                raise _LinuxOwnershipError(
                    "Linux process path contains an invalid pid"
                ) from error
            return _parse_linux_stat(path.read_bytes(), pid=pid)

        @classmethod
        def _read_table(cls) -> dict[_ProcessIdentity, _ProcessRecord]:
            proc_root = Path("/proc")
            try:
                cls._read_record(proc_root / str(os.getpid()) / "stat")
                entries = tuple(proc_root.iterdir())
            except (OSError, UnicodeError) as error:
                raise _LinuxOwnershipError("Linux procfs is unavailable") from error
            records = {}
            for entry in entries:
                if not entry.name.isdigit():
                    continue
                try:
                    record = cls._read_record(entry / "stat")
                except FileNotFoundError:
                    continue
                except UnicodeError as error:
                    raise _LinuxOwnershipError(
                        "Linux procfs process visibility is incomplete"
                    ) from error
                except OSError as error:
                    if error.errno in {
                        _linux_errno.ENOENT,
                        _linux_errno.ESRCH,
                    }:
                        continue
                    raise _LinuxOwnershipError(
                        "Linux procfs process visibility is incomplete"
                    ) from error
                records[record.identity] = record
            return records

        def bind_root(self, pid: int) -> None:
            try:
                record = self._read_record(Path("/proc") / str(pid) / "stat")
            except (OSError, UnicodeError) as error:
                raise _LinuxOwnershipError(
                    "Linux command root identity is unavailable"
                ) from error
            self.root_identity = record.identity
            self.tracker.bind_root(record.identity)

        def scan_active(self) -> dict[_ProcessIdentity, _ProcessRecord]:
            records = self._read_table()
            owned = self.tracker.update(records)
            reaped = False
            for identity in owned:
                record = records[identity]
                if (
                    identity != self.root_identity
                    and record.parent_pid == self.runner_pid
                ):
                    try:
                        reaped_pid, _ = os.waitpid(identity.pid, os.WNOHANG)
                    except ChildProcessError:
                        reaped_pid = 0
                    except OSError as error:
                        raise _LinuxOwnershipError(
                            "Linux adopted child cannot be reaped"
                        ) from error
                    if reaped_pid:
                        reaped = True
            if reaped:
                records = self._read_table()
                owned = self.tracker.update(records)
            return {identity: records[identity] for identity in owned}

        def active_descendants(self) -> dict[_ProcessIdentity, _ProcessRecord]:
            return {
                identity: record
                for identity, record in self.scan_active().items()
                if identity != self.root_identity
            }

        @staticmethod
        def _kill_identity(identity: _ProcessIdentity) -> None:
            _signal_linux_identity(
                identity,
                open_pidfd=os.pidfd_open,
                read_record=lambda pid: _LinuxProcessOwner._read_record(
                    Path("/proc") / str(pid) / "stat"
                ),
                send_signal=signal.pidfd_send_signal,
                close_pidfd=os.close,
            )

        def terminate_until_clear(
            self,
            process: subprocess.Popen,
            deadline: float,
        ) -> bool:
            while True:
                active = self.scan_active()
                for identity in active:
                    self._kill_identity(identity)
                remaining_active = self.scan_active()
                active_descendants = {
                    identity: record
                    for identity, record in remaining_active.items()
                    if identity != self.root_identity
                }
                if process.poll() is not None and not active_descendants:
                    return True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    for identity in remaining_active:
                        self._kill_identity(identity)
                    return False
                time.sleep(min(self._POLL_SECONDS, remaining))

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9

    class _JobObjectBasicLimitInformation(ctypes.Structure):
        _fields_ = (
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        )

    class _IoCounters(ctypes.Structure):
        _fields_ = (
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        )

    class _JobObjectExtendedLimitInformation(ctypes.Structure):
        _fields_ = (
            ("BasicLimitInformation", _JobObjectBasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        )

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _create_job_object = _kernel32.CreateJobObjectW
    _create_job_object.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    _create_job_object.restype = wintypes.HANDLE
    _set_job_information = _kernel32.SetInformationJobObject
    _set_job_information.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    _set_job_information.restype = wintypes.BOOL
    _assign_process_to_job = _kernel32.AssignProcessToJobObject
    _assign_process_to_job.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    _assign_process_to_job.restype = wintypes.BOOL
    _terminate_job = _kernel32.TerminateJobObject
    _terminate_job.argtypes = (wintypes.HANDLE, wintypes.UINT)
    _terminate_job.restype = wintypes.BOOL
    _create_event = _kernel32.CreateEventW
    _create_event.argtypes = (
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    )
    _create_event.restype = wintypes.HANDLE
    _set_event = _kernel32.SetEvent
    _set_event.argtypes = (wintypes.HANDLE,)
    _set_event.restype = wintypes.BOOL
    _close_handle = _kernel32.CloseHandle
    _close_handle.argtypes = (wintypes.HANDLE,)
    _close_handle.restype = wintypes.BOOL

    _WINDOWS_JOB_WRAPPER = """\
import ctypes
import subprocess
import sys

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
wait_for_single_object = kernel32.WaitForSingleObject
wait_for_single_object.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
wait_for_single_object.restype = ctypes.c_uint32
close_handle = kernel32.CloseHandle
close_handle.argtypes = (ctypes.c_void_p,)
event = ctypes.c_void_p(int(sys.argv[1]))
wait_result = wait_for_single_object(event, 0xFFFFFFFF)
close_handle(event)
if wait_result != 0:
    raise SystemExit(126)
try:
    completed = subprocess.run(sys.argv[2:], shell=False, check=False)
except BaseException:
    raise SystemExit(127) from None
raise SystemExit(completed.returncode)
"""

    class _WindowsJob:
        def __init__(self) -> None:
            self._handle = _create_job_object(None, None)
            if not self._handle:
                raise OSError(ctypes.get_last_error())
            information = _JobObjectExtendedLimitInformation()
            information.BasicLimitInformation.LimitFlags = (
                _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            )
            if not _set_job_information(
                self._handle,
                _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                ctypes.byref(information),
                ctypes.sizeof(information),
            ):
                error_code = ctypes.get_last_error()
                self.close()
                raise OSError(error_code)

        def assign(self, process: subprocess.Popen) -> None:
            if not _assign_process_to_job(
                self._handle,
                wintypes.HANDLE(int(process._handle)),
            ):
                raise OSError(ctypes.get_last_error())

        def terminate(self) -> None:
            if self._handle:
                _terminate_job(self._handle, 1)

        def close(self) -> None:
            if self._handle:
                _close_handle(self._handle)
                self._handle = None

    class _WindowsEvent:
        def __init__(self) -> None:
            self._handle = _create_event(None, True, False, None)
            if not self._handle:
                raise OSError(ctypes.get_last_error())
            try:
                os.set_handle_inheritable(int(self._handle), True)
            except OSError:
                self.close()
                raise

        @property
        def argument(self) -> str:
            return str(int(self._handle))

        @property
        def handle(self) -> int:
            return int(self._handle)

        def set(self) -> None:
            if not _set_event(self._handle):
                raise OSError(ctypes.get_last_error())

        def close(self) -> None:
            if self._handle:
                _close_handle(self._handle)
                self._handle = None


class RunnerError(RuntimeError):
    """Raised when a bounded command does not complete safely."""


@dataclass(frozen=True)
class CommandSpec:
    command_id: str
    argv: tuple[str, ...]
    cwd: Path
    timeout_seconds: int
    environment: tuple[tuple[str, str], ...]
    secret_canaries: tuple[str, ...]
    stdout_limit: int
    stderr_limit: int
    log_directory: Path


@dataclass(frozen=True)
class CommandResult:
    command_id: str
    exit_code: int
    duration_ms: int
    stdout_sha256: str
    stderr_sha256: str


class _StreamCollector(threading.Thread):
    def __init__(self, stream, limit: int, canaries: tuple[bytes, ...]):
        super().__init__(daemon=True)
        self._stream = stream
        self._limit = limit
        self._canaries = canaries
        self._maximum_canary_length = max((len(value) for value in canaries), default=0)
        self.digest = hashlib.sha256()
        self.output = bytearray()
        self.canary_seen = False
        self.failed = False

    def run(self) -> None:
        tail = b""
        try:
            while True:
                chunk = self._stream.read(65536)
                if not chunk:
                    break
                self.digest.update(chunk)
                remaining = self._limit - len(self.output)
                if remaining > 0:
                    self.output.extend(chunk[:remaining])
                if self._canaries:
                    window = tail + chunk
                    if any(canary in window for canary in self._canaries):
                        self.canary_seen = True
                    overlap = self._maximum_canary_length - 1
                    tail = window[-overlap:] if overlap > 0 else b""
        except (OSError, ValueError):
            self.failed = True
        finally:
            try:
                self._stream.close()
            except (OSError, ValueError):
                self.failed = True


def _write_input(stream, value: bytes) -> None:
    try:
        stream.write(value)
        stream.flush()
    except (BrokenPipeError, OSError):
        pass
    finally:
        try:
            stream.close()
        except (OSError, ValueError):
            pass


class Runner:
    def run(
        self,
        spec: CommandSpec,
        *,
        input_bytes: bytes | None = None,
    ) -> CommandResult:
        command_id = self._validate(spec, input_bytes)
        started = time.monotonic()
        deadline = started + spec.timeout_seconds
        termination_deadline = deadline + _TERMINATION_GRACE_SECONDS
        try:
            canaries = tuple(value.encode("utf-8") for value in spec.secret_canaries)
        except UnicodeError:
            raise RunnerError(f"command {command_id} is invalid") from None
        environment = dict(spec.environment)

        job = None
        event = None
        launch_argv = list(spec.argv)
        startupinfo = None
        linux_owner = None
        if sys.platform == "linux":
            try:
                linux_owner = _LinuxProcessOwner()
            except _LinuxOwnershipError:
                raise RunnerError(
                    f"command {command_id} could not start"
                ) from None
        elif os.name == "posix":
            raise RunnerError(f"command {command_id} could not start")

        if os.name == "nt":
            try:
                job = _WindowsJob()
                event = _WindowsEvent()
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.lpAttributeList = {
                    "handle_list": [event.handle],
                }
                launch_argv = [
                    sys.executable,
                    "-I",
                    "-c",
                    _WINDOWS_JOB_WRAPPER,
                    event.argument,
                    *spec.argv,
                ]
            except OSError:
                if event is not None:
                    event.close()
                if job is not None:
                    job.close()
                raise RunnerError(f"command {command_id} could not start") from None

        try:
            spec.log_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            if os.name != "nt":
                spec.log_directory.chmod(0o700)
            process = subprocess.Popen(
                launch_argv,
                cwd=str(spec.cwd),
                env=environment,
                stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                close_fds=True,
                start_new_session=os.name != "nt",
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
                ),
                startupinfo=startupinfo,
            )
        except (OSError, UnicodeError, ValueError):
            if event is not None:
                event.close()
            if job is not None:
                job.close()
            raise RunnerError(f"command {command_id} could not start") from None

        if linux_owner is not None:
            try:
                linux_owner.bind_root(process.pid)
            except _LinuxOwnershipError:
                try:
                    linux_owner.terminate_until_clear(
                        process,
                        termination_deadline,
                    )
                except _LinuxOwnershipError:
                    self._kill_direct_process(process)
                raise RunnerError(
                    f"command {command_id} could not start"
                ) from None

        if job is not None:
            try:
                job.assign(process)
                event.set()
            except OSError:
                job.terminate()
                if process.poll() is None:
                    process.kill()
                event.close()
                job.close()
                raise RunnerError(f"command {command_id} could not start") from None
            event.close()

        try:
            stdout = _StreamCollector(process.stdout, spec.stdout_limit, canaries)
            stderr = _StreamCollector(process.stderr, spec.stderr_limit, canaries)
            started_threads = []
            try:
                stdout.start()
                started_threads.append(stdout)
                stderr.start()
                started_threads.append(stderr)

                input_thread = None
                if input_bytes is not None:
                    input_thread = threading.Thread(
                        target=_write_input,
                        args=(process.stdin, input_bytes),
                        daemon=True,
                    )
                    input_thread.start()
                    started_threads.append(input_thread)
            except RuntimeError:
                self._kill_process_tree(
                    process,
                    job,
                    linux_owner,
                    termination_deadline,
                )
                if linux_owner is None:
                    self._wait_process_until(process, termination_deadline)
                self._join_threads_until(tuple(started_threads), termination_deadline)
                raise RunnerError(
                    f"command {command_id} failed to initialize"
                ) from None

            threads = tuple(started_threads)
            try:
                if linux_owner is not None:
                    timed_out, drained = self._wait_linux_command(
                        process,
                        threads,
                        linux_owner,
                        deadline,
                    )
                else:
                    timed_out = False
                    try:
                        process.wait(timeout=max(0, deadline - time.monotonic()))
                    except subprocess.TimeoutExpired:
                        timed_out = True
                    if not timed_out and not self._join_threads_until(
                        threads,
                        deadline,
                    ):
                        timed_out = True
                    drained = not any(thread.is_alive() for thread in threads)
            except _LinuxOwnershipError:
                self._kill_process_tree(
                    process,
                    job,
                    linux_owner,
                    termination_deadline,
                )
                self._join_threads_until(threads, termination_deadline)
                raise RunnerError(
                    f"command {command_id} ownership failed"
                ) from None

            if timed_out:
                self._kill_process_tree(
                    process,
                    job,
                    linux_owner,
                    termination_deadline,
                )
                if linux_owner is None:
                    self._wait_process_until(process, termination_deadline)
                drained = self._join_threads_until(threads, termination_deadline)

            duration_ms = int((time.monotonic() - started) * 1000)
            if timed_out and not drained:
                raise RunnerError(f"command {command_id} timed out")
            if stdout.failed or stderr.failed:
                raise RunnerError(f"command {command_id} capture failed")
            if stdout.canary_seen or stderr.canary_seen:
                raise RunnerError(f"command {command_id} exposed a canary")

            try:
                self._write_log(
                    spec.log_directory / f"{command_id}.stdout.log",
                    stdout.output,
                )
                self._write_log(
                    spec.log_directory / f"{command_id}.stderr.log",
                    stderr.output,
                )
            except (OSError, UnicodeError, ValueError):
                raise RunnerError(f"command {command_id} log write failed") from None

            if timed_out:
                raise RunnerError(f"command {command_id} timed out")
            if process.returncode != 0:
                raise RunnerError(f"command {command_id} failed")
            return CommandResult(
                command_id=command_id,
                exit_code=process.returncode,
                duration_ms=duration_ms,
                stdout_sha256="sha256:" + stdout.digest.hexdigest(),
                stderr_sha256="sha256:" + stderr.digest.hexdigest(),
            )
        finally:
            if job is not None:
                job.close()

    @staticmethod
    def _validate(spec: CommandSpec, input_bytes: bytes | None) -> str:
        command_id = spec.command_id
        if not isinstance(command_id, str) or _SAFE_IDENTIFIER.fullmatch(command_id) is None:
            raise RunnerError("command identifier is invalid")

        invalid = f"command {command_id} is invalid"
        if (
            not isinstance(spec.argv, tuple)
            or not spec.argv
            or any(not isinstance(value, str) or not value for value in spec.argv)
            or not isinstance(spec.cwd, Path)
            or not isinstance(spec.log_directory, Path)
            or not isinstance(spec.timeout_seconds, int)
            or isinstance(spec.timeout_seconds, bool)
            or spec.timeout_seconds <= 0
            or not isinstance(spec.stdout_limit, int)
            or isinstance(spec.stdout_limit, bool)
            or spec.stdout_limit < 0
            or not isinstance(spec.stderr_limit, int)
            or isinstance(spec.stderr_limit, bool)
            or spec.stderr_limit < 0
            or not isinstance(spec.environment, tuple)
            or not isinstance(spec.secret_canaries, tuple)
            or input_bytes is not None
            and not isinstance(input_bytes, bytes)
        ):
            raise RunnerError(invalid)

        environment_keys = []
        for item in spec.environment:
            if (
                not isinstance(item, tuple)
                or len(item) != 2
                or not isinstance(item[0], str)
                or not isinstance(item[1], str)
                or not item[0]
                or "=" in item[0]
                or "\x00" in item[0]
                or "\x00" in item[1]
            ):
                raise RunnerError(invalid)
            environment_keys.append(item[0])
        if len(set(environment_keys)) != len(environment_keys):
            raise RunnerError(invalid)
        if any(
            not isinstance(canary, str) or not canary or "\x00" in canary
            for canary in spec.secret_canaries
        ):
            raise RunnerError(invalid)
        return command_id

    @staticmethod
    def _write_log(path: Path, content: bytearray) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        descriptor = os.open(path, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = -1
                stream.write(content)
            if os.name != "nt":
                path.chmod(0o600)
        finally:
            if descriptor != -1:
                os.close(descriptor)

    @staticmethod
    def _wait_linux_command(
        process: subprocess.Popen,
        threads: tuple[threading.Thread, ...],
        owner: _LinuxProcessOwner,
        deadline: float,
    ) -> tuple[bool, bool]:
        while True:
            process.poll()
            descendants = owner.active_descendants()
            drained = not any(thread.is_alive() for thread in threads)
            if process.returncode is not None and not descendants and drained:
                return False, True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True, drained
            time.sleep(min(owner._POLL_SECONDS, remaining))

    @staticmethod
    def _wait_process_until(
        process: subprocess.Popen,
        deadline: float,
    ) -> None:
        try:
            process.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            pass

    @staticmethod
    def _join_threads_until(
        threads: tuple[threading.Thread, ...],
        deadline: float,
    ) -> bool:
        for thread in threads:
            thread.join(max(0, deadline - time.monotonic()))
        return not any(thread.is_alive() for thread in threads)

    @staticmethod
    def _kill_process_tree(
        process: subprocess.Popen,
        job,
        linux_owner,
        deadline: float,
    ) -> bool:
        if linux_owner is not None:
            try:
                return linux_owner.terminate_until_clear(process, deadline)
            except _LinuxOwnershipError:
                Runner._kill_direct_process(process)
                return False
        if job is not None:
            job.terminate()
        elif os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass
        Runner._kill_direct_process(process)
        return True

    @staticmethod
    def _kill_direct_process(process: subprocess.Popen) -> None:
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
