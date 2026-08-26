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
        try:
            canaries = tuple(value.encode("utf-8") for value in spec.secret_canaries)
        except UnicodeError:
            raise RunnerError(f"command {command_id} is invalid") from None
        environment = dict(spec.environment)

        job = None
        event = None
        launch_argv = list(spec.argv)
        startupinfo = None
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
                termination_deadline = time.monotonic() + _TERMINATION_GRACE_SECONDS
                self._kill_process_tree(process, job)
                try:
                    process.wait(
                        timeout=max(0, termination_deadline - time.monotonic())
                    )
                except subprocess.TimeoutExpired:
                    pass
                self._join_threads_until(tuple(started_threads), termination_deadline)
                raise RunnerError(
                    f"command {command_id} failed to initialize"
                ) from None

            threads = tuple(started_threads)
            timed_out = False
            try:
                process.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                timed_out = True
            if not timed_out and not self._join_threads_until(threads, deadline):
                timed_out = True

            drained = not any(thread.is_alive() for thread in threads)
            if timed_out:
                termination_deadline = time.monotonic() + _TERMINATION_GRACE_SECONDS
                self._kill_process_tree(process, job)
                try:
                    process.wait(
                        timeout=max(0, termination_deadline - time.monotonic())
                    )
                except subprocess.TimeoutExpired:
                    pass
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
    def _join_threads_until(
        threads: tuple[threading.Thread, ...],
        deadline: float,
    ) -> bool:
        for thread in threads:
            thread.join(max(0, deadline - time.monotonic()))
        return not any(thread.is_alive() for thread in threads)

    @staticmethod
    def _kill_process_tree(process: subprocess.Popen, job) -> None:
        if job is not None:
            job.terminate()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
