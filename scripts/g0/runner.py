"""Secret-safe controller for one-shot G0 operation supervisors."""

from __future__ import annotations

import base64
import json
import os
import re
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MAX_PROTOCOL_BYTES = 1_048_576


def _unique_protocol_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate protocol key")
        result[key] = value
    return result


class RunnerError(RuntimeError):
    """An ordinary, safely bounded command failure."""


class WorkerDisposalRequired(BaseException):
    """The worker must be externally stopped/restarted before reuse."""


@dataclass(frozen=True)
class CommandSpec:
    command_id: str
    argv: tuple[str, ...]
    cwd: Path
    execution_timeout_seconds: int
    cleanup_timeout_seconds: int
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


def _is_plain_int(value: object, minimum: int, maximum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum


def _contains_reparse_or_symlink(path: Path) -> bool:
    candidate = path
    while True:
        try:
            status = os.lstat(candidate)
        except FileNotFoundError:
            pass
        except OSError:
            return True
        else:
            if stat.S_ISLNK(status.st_mode):
                return True
            if getattr(status, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
                return True
        if candidate.parent == candidate:
            return False
        candidate = candidate.parent


def _is_within(path: Path, root: Path) -> bool:
    if ".." in path.parts or ".." in root.parts:
        return False
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


class Runner:
    """Run commands only through a disposable, fixed-protocol supervisor."""

    def __init__(self, *, run_root: Path | None = None, popen_factory=subprocess.Popen) -> None:
        self._run_root = None if run_root is None else Path(run_root)
        self._popen_factory = popen_factory
        self._supervisor = Path(__file__).with_name("supervisor.py").resolve()

    def run(self, spec: CommandSpec, *, input_bytes: bytes | None = None) -> CommandResult:
        command_id, run_root = self._validate(spec, input_bytes)
        request = {
            "protocol_version": 1,
            "command_id": command_id,
            "argv": list(spec.argv),
            "cwd": str(spec.cwd),
            "run_root": str(run_root),
            "execution_timeout_seconds": spec.execution_timeout_seconds,
            "cleanup_timeout_seconds": spec.cleanup_timeout_seconds,
            "environment": [list(item) for item in spec.environment],
            "secret_canaries_b64": [base64.b64encode(value.encode("utf-8")).decode("ascii") for value in spec.secret_canaries],
            "input_b64": None if input_bytes is None else base64.b64encode(input_bytes).decode("ascii"),
            "stdout_limit": spec.stdout_limit,
            "stderr_limit": spec.stderr_limit,
            "log_directory": str(spec.log_directory),
        }
        payload = (json.dumps(request, ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")
        if len(payload) > _MAX_PROTOCOL_BYTES:
            raise RunnerError(f"command {command_id} is invalid")

        supervisor_environment = {}
        for name in ("SystemRoot", "WINDIR"):
            if name in os.environ:
                supervisor_environment[name] = os.environ[name]
        process = None
        response_bytes = b""
        supervisor_completion_observed_ns = None
        supervisor_deadline = time.monotonic() + spec.execution_timeout_seconds + spec.cleanup_timeout_seconds
        request_read = request_write = response_read = response_write = None
        try:
            request_read, request_write = os.pipe()
            response_read, response_write = os.pipe()
            os.set_blocking(request_write, False)
            os.set_blocking(response_read, False)
            request_endpoint = self._endpoint(request_read)
            response_endpoint = self._endpoint(response_write)
            self._set_endpoint_inheritable(request_read, request_endpoint, True)
            self._set_endpoint_inheritable(response_write, response_endpoint, True)
            command = (
                sys.executable,
                str(self._supervisor),
                "--request-endpoint",
                str(request_endpoint),
                "--response-endpoint",
                str(response_endpoint),
            )
            kwargs = {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "cwd": str(run_root),
                "env": supervisor_environment,
                "shell": False,
                "close_fds": True,
                "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            }
            if os.name == "nt":
                startup = subprocess.STARTUPINFO()
                startup.lpAttributeList = {"handle_list": [request_endpoint, response_endpoint]}
                kwargs["startupinfo"] = startup
            else:
                kwargs["pass_fds"] = (request_read, response_write)
            try:
                process = self._popen_factory(command, **kwargs)
            finally:
                self._set_endpoint_inheritable(request_read, request_endpoint, False)
                self._set_endpoint_inheritable(response_write, response_endpoint, False)
            os.close(request_read); request_read = None
            os.close(response_write); response_write = None
            response_bytes, supervisor_completion_observed_ns = self._exchange(
                process,
                request_write,
                response_read,
                payload,
                supervisor_deadline,
            )
            request_write = None; response_read = None
        except WorkerDisposalRequired:
            raise WorkerDisposalRequired(f"command {command_id} worker disposal required") from None
        except BaseException:
            if process is not None:
                try:
                    process.kill()
                    process.poll()
                except BaseException:
                    pass
            raise WorkerDisposalRequired(f"command {command_id} worker disposal required") from None
        finally:
            for descriptor in (request_read, request_write, response_read, response_write):
                if descriptor is not None:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass

        response = self._decode_response(command_id, response_bytes, process.returncode)
        cleanup_deadline_ns = response["cleanup_deadline_monotonic_ns"]
        if cleanup_deadline_ns is not None and supervisor_completion_observed_ns >= cleanup_deadline_ns:
            raise WorkerDisposalRequired(f"command {command_id} worker disposal required")
        status = response["status"]
        if status == "WORKER_DISPOSAL_REQUIRED":
            raise WorkerDisposalRequired(f"command {command_id} worker disposal required")
        if status == "TIMED_OUT":
            raise RunnerError(f"command {command_id} timed out")
        if status == "CANARY_DETECTED":
            raise RunnerError(f"command {command_id} exposed a canary")
        if status == "FAILED":
            raise RunnerError(f"command {command_id} failed")
        return CommandResult(
            command_id=command_id,
            exit_code=response["exit_code"],
            duration_ms=response["duration_ms"],
            stdout_sha256=response["stdout_sha256"],
            stderr_sha256=response["stderr_sha256"],
        )

    def _exchange(self, process, request_write: int, response_read: int, payload: bytes, deadline: float) -> tuple[bytes, int]:
        offset = 0
        response = bytearray()
        request_open = True
        response_eof = False
        while True:
            if time.monotonic() >= deadline:
                try:
                    process.kill()
                    process.poll()
                except BaseException:
                    pass
                raise WorkerDisposalRequired("supervisor deadline expired")
            if request_open:
                try:
                    count = os.write(request_write, payload[offset : offset + 65_536])
                except BlockingIOError:
                    pass
                except BrokenPipeError:
                    raise WorkerDisposalRequired("supervisor request channel failed") from None
                else:
                    if count <= 0:
                        raise WorkerDisposalRequired("supervisor request channel failed")
                    offset += count
                    if offset == len(payload):
                        os.close(request_write)
                        request_open = False
            if not response_eof:
                try:
                    content = os.read(response_read, 65_537 - len(response))
                except BlockingIOError:
                    content = None
                if content == b"":
                    response_eof = True
                elif content is not None:
                    response.extend(content)
                    if len(response) > 65_536:
                        raise WorkerDisposalRequired("supervisor response channel failed")
            returncode = process.poll()
            if returncode is not None and response_eof:
                observed_ns = time.monotonic_ns()
                os.close(response_read)
                return bytes(response), observed_ns
            time.sleep(min(0.005, max(0.0, deadline - time.monotonic())))

    def _validate(self, spec: CommandSpec, input_bytes: bytes | None) -> tuple[str, Path]:
        command_id = getattr(spec, "command_id", "invalid")
        safe_id = isinstance(command_id, str) and _SAFE_IDENTIFIER.fullmatch(command_id) is not None
        display_id = command_id if safe_id else "invalid"
        invalid = f"command {display_id} is invalid"
        if not isinstance(spec, CommandSpec) or not safe_id:
            raise RunnerError(invalid)
        run_root = self._run_root if self._run_root is not None else spec.cwd
        if not isinstance(run_root, Path) or not run_root.is_absolute():
            raise RunnerError(invalid)
        if (
            not isinstance(spec.argv, tuple) or not spec.argv
            or any(not isinstance(value, str) or not value or "\x00" in value for value in spec.argv)
            or not isinstance(spec.cwd, Path) or not spec.cwd.is_absolute() or not spec.cwd.is_dir()
            or not isinstance(spec.log_directory, Path) or not spec.log_directory.is_absolute()
            or str(spec.log_directory).startswith(("//", "\\\\"))
            or not run_root.is_dir() or not _is_within(spec.cwd, run_root) or not _is_within(spec.log_directory, run_root)
            or _contains_reparse_or_symlink(run_root) or _contains_reparse_or_symlink(spec.cwd)
            or _contains_reparse_or_symlink(spec.log_directory)
            or not _is_plain_int(spec.execution_timeout_seconds, 1, 18_000)
            or not _is_plain_int(spec.cleanup_timeout_seconds, 5, 600)
            or not _is_plain_int(spec.stdout_limit, 0, 2**31 - 1)
            or not _is_plain_int(spec.stderr_limit, 0, 2**31 - 1)
            or not isinstance(spec.environment, tuple) or not isinstance(spec.secret_canaries, tuple)
            or input_bytes is not None and not isinstance(input_bytes, bytes)
        ):
            raise RunnerError(invalid)
        keys = []
        for item in spec.environment:
            if not isinstance(item, tuple) or len(item) != 2 or any(not isinstance(value, str) for value in item):
                raise RunnerError(invalid)
            key, value = item
            if not key or "=" in key or "\x00" in key or "\x00" in value:
                raise RunnerError(invalid)
            keys.append(key)
        normalized_keys = [key.casefold() for key in keys] if os.name == "nt" else keys
        if len(normalized_keys) != len(set(normalized_keys)):
            raise RunnerError(invalid)
        for canary in spec.secret_canaries:
            if not isinstance(canary, str) or not canary or "\x00" in canary:
                raise RunnerError(invalid)
            try:
                canary.encode("utf-8")
            except UnicodeError:
                raise RunnerError(invalid) from None
        return command_id, run_root

    @staticmethod
    def _endpoint(descriptor: int) -> int:
        if os.name != "nt":
            return descriptor
        import msvcrt
        return int(msvcrt.get_osfhandle(descriptor))

    @staticmethod
    def _set_endpoint_inheritable(descriptor: int, endpoint: int, inheritable: bool) -> None:
        if os.name == "nt":
            os.set_handle_inheritable(endpoint, inheritable)
        else:
            os.set_inheritable(descriptor, inheritable)

    @staticmethod
    def _decode_response(command_id: str, raw: bytes, returncode: int | None) -> dict:
        disposal = WorkerDisposalRequired(f"command {command_id} worker disposal required")
        if returncode != 0 or not isinstance(raw, bytes) or len(raw) > 65_536 or raw.count(b"\n") != 1 or not raw.endswith(b"\n"):
            raise disposal
        try:
            value = json.loads(raw.decode("ascii"), object_pairs_hook=_unique_protocol_object)
        except (UnicodeError, ValueError, RecursionError):
            raise disposal from None
        required = {
            "protocol_version", "status", "exit_code", "duration_ms",
            "cleanup_deadline_monotonic_ns", "stdout_sha256", "stderr_sha256", "proof",
        }
        if (
            not isinstance(value, dict)
            or set(value) != required
            or type(value.get("protocol_version")) is not int
            or value["protocol_version"] != 1
        ):
            raise disposal
        proof = value.get("proof")
        if (
            not isinstance(proof, dict)
            or set(proof) != {"boundary_empty", "streams_eof", "logs_finalized"}
            or any(type(value) is not bool for value in proof.values())
            or not all(proof.values())
        ):
            raise disposal
        if value.get("status") not in {"PASS", "FAILED", "TIMED_OUT", "CANARY_DETECTED", "WORKER_DISPOSAL_REQUIRED"}:
            raise disposal
        if not _is_plain_int(value.get("duration_ms"), 0, 2**63 - 1):
            raise disposal
        cleanup_deadline = value.get("cleanup_deadline_monotonic_ns")
        if cleanup_deadline is not None and not _is_plain_int(cleanup_deadline, 1, 2**63 - 1):
            raise disposal
        if not isinstance(value.get("stdout_sha256"), str) or not _SHA256.fullmatch(value["stdout_sha256"]):
            raise disposal
        if not isinstance(value.get("stderr_sha256"), str) or not _SHA256.fullmatch(value["stderr_sha256"]):
            raise disposal
        exit_code = value.get("exit_code")
        if exit_code is not None and not _is_plain_int(exit_code, -2**31, 2**31 - 1):
            raise disposal
        status = value["status"]
        valid_exit = (
            status == "PASS" and exit_code == 0
            or status == "FAILED" and (exit_code is None or isinstance(exit_code, int) and exit_code != 0)
            or status == "CANARY_DETECTED" and (exit_code is None or isinstance(exit_code, int))
            or status in {"TIMED_OUT", "WORKER_DISPOSAL_REQUIRED"} and exit_code is None
        )
        if not valid_exit or (
            cleanup_deadline is None
            and not (status == "FAILED" and exit_code is None)
        ):
            raise disposal
        return value
