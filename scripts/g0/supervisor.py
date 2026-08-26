"""One-shot command supervisor for the OCI G0 worker.

The controller treats this process as disposable.  This process alone launches
the target, owns its OS containment boundary, captures streams, and finalizes
logs before emitting one fixed-protocol response.
"""

from __future__ import annotations

import base64
import errno
import hashlib
import json
import os
import re
import secrets
import signal
import stat
import subprocess
import sys
import time
import math
from pathlib import Path


_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_MAX_REQUEST_BYTES = 1_048_576
_LOCAL_FILESYSTEMS = frozenset({"btrfs", "ext2", "ext3", "ext4", "overlay", "tmpfs", "xfs", "zfs"})
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 258
_ACTIVE_CLEANUP_DEADLINE: float | None = None


def _unique_protocol_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate protocol key")
        result[key] = value
    return result


class SupervisorOrdinaryFailure(Exception):
    """A failure proved to have no work left behind."""


class SupervisorDisposalRequired(BaseException):
    """Some in-host proof is unavailable; external disposal is mandatory."""


def require_before_deadline(deadline: float, *, monotonic=time.monotonic) -> None:
    if monotonic() >= deadline:
        raise SupervisorDisposalRequired("cleanup deadline expired")


def _latch_cleanup_deadline(deadline: float) -> None:
    global _ACTIVE_CLEANUP_DEADLINE
    if _ACTIVE_CLEANUP_DEADLINE is None:
        _ACTIVE_CLEANUP_DEADLINE = deadline
    elif _ACTIVE_CLEANUP_DEADLINE != deadline:
        raise SupervisorDisposalRequired("cleanup deadline changed")


def wait_windows_process_until(handle: int, deadline: float, *, wait, monotonic=time.monotonic) -> bool:
    """Wait without rounding an unexpired deadline down to an immediate timeout."""
    while True:
        result = wait(handle, 0)
        if result == _WAIT_OBJECT_0:
            return True
        if result != _WAIT_TIMEOUT:
            raise SupervisorDisposalRequired("Windows process wait failed")
        remaining = deadline - monotonic()
        if remaining <= 0:
            result = wait(handle, 0)
            if result == _WAIT_OBJECT_0:
                return True
            if result == _WAIT_TIMEOUT:
                return False
            raise SupervisorDisposalRequired("Windows process wait failed")
        result = wait(handle, max(1, min(0xFFFFFFFE, math.ceil(remaining * 1000))))
        if result == _WAIT_OBJECT_0:
            return True
        if result != _WAIT_TIMEOUT:
            raise SupervisorDisposalRequired("Windows process wait failed")


class ReleaseGate:
    def __init__(self) -> None:
        self.contained = False
        self.released = False

    def mark_contained(self) -> None:
        self.contained = True

    def release(self) -> None:
        self.release_with(lambda: None)

    def release_with(self, action) -> None:
        if not self.contained:
            raise SupervisorOrdinaryFailure("target containment is not proved")
        self.released = True
        action()


def _release_before_deadline(deadline: float, action, *, monotonic=time.monotonic) -> None:
    if monotonic() >= deadline:
        raise SupervisorOrdinaryFailure("execution deadline expired before target release")
    action()


class StreamCapture:
    def __init__(self, *, limit: int, canaries: tuple[bytes, ...]) -> None:
        self._limit = limit
        self._canaries = canaries
        self._hash = hashlib.sha256()
        self._retained = bytearray()
        self._tail = b""
        self.canary_seen = False
        self.eof = False
        self._overlap = max((len(value) for value in canaries), default=1) - 1

    def feed(self, content: bytes) -> None:
        if self.eof:
            raise SupervisorDisposalRequired("stream changed after EOF")
        self._hash.update(content)
        remaining = self._limit - len(self._retained)
        if remaining > 0:
            self._retained.extend(content[:remaining])
        window = self._tail + content
        if any(canary in window for canary in self._canaries):
            self.canary_seen = True
        self._tail = window[-self._overlap :] if self._overlap else b""

    def finish(self) -> None:
        self.eof = True

    @property
    def retained(self) -> bytes:
        return bytes(self._retained)

    @property
    def hexdigest(self) -> str:
        return self._hash.hexdigest()


def validate_log_paths(run_root: Path, log_directory: Path, *, platform: str) -> None:
    raw = str(log_directory)
    if not run_root.is_absolute() or not log_directory.is_absolute() or ".." in run_root.parts or ".." in log_directory.parts:
        raise SupervisorOrdinaryFailure("log path is not absolute")
    if raw.startswith(("//", "\\\\")):
        raise SupervisorOrdinaryFailure("network log path is forbidden")
    try:
        log_directory.relative_to(run_root)
    except ValueError:
        raise SupervisorOrdinaryFailure("log path is outside run root") from None
    if platform == "windows" and run_root.drive.lower() != log_directory.drive.lower():
        raise SupervisorOrdinaryFailure("log path crosses a volume")


def require_local_mount(filesystem: str, approved_mount_id: int, observed_mount_id: int) -> None:
    if filesystem not in _LOCAL_FILESYSTEMS or approved_mount_id != observed_mount_id:
        raise SupervisorOrdinaryFailure("log storage identity is not approved local storage")


class CanaryLogCleanup:
    def __init__(self, *, unlink, fsync_directory, exists) -> None:
        self._unlink = unlink
        self._fsync_directory = fsync_directory
        self._exists = exists

    def remove_and_prove(self, names: tuple[str, ...]) -> None:
        try:
            for name in names:
                try:
                    self._unlink(name)
                except FileNotFoundError:
                    pass
            self._fsync_directory()
            if any(self._exists(name) for name in names):
                raise OSError("log absence is not proved")
        except BaseException as error:
            if isinstance(error, SupervisorDisposalRequired):
                raise
            raise SupervisorDisposalRequired("canary log cleanup is unverifiable") from None


def classify_log_proof_failure(error: BaseException) -> None:
    del error
    raise SupervisorDisposalRequired("log finalization is unverifiable")


def _mount_id(descriptor: int) -> int:
    import ctypes

    try:
        libc = ctypes.CDLL(None, use_errno=True)
        statx = libc.statx
        statx.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_uint, ctypes.c_void_p)
        statx.restype = ctypes.c_int
        buffer = (ctypes.c_ubyte * 256)()
        statx_mnt_id = 0x00001000
        if statx(descriptor, b"", 0x1000 | 0x100, statx_mnt_id, ctypes.byref(buffer)) != 0:
            raise OSError(ctypes.get_errno(), "statx failed")
        mask = int.from_bytes(bytes(buffer[0:4]), sys.byteorder)
        mount_id = int.from_bytes(bytes(buffer[144:152]), sys.byteorder)
        if mask & statx_mnt_id == 0 or mount_id <= 0:
            raise ValueError
        return mount_id
    except (AttributeError, OSError, ValueError, IndexError):
        raise SupervisorOrdinaryFailure("mount identity is unavailable") from None


def _mount_filesystem(mount_id: int) -> str:
    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
        matches = []
        for line in lines:
            before, separator, after = line.partition(" - ")
            fields = before.split()
            trailing = after.split()
            if separator and len(fields) >= 5 and trailing and int(fields[0]) == mount_id:
                matches.append(trailing[0])
        if len(matches) != 1:
            raise ValueError
        return matches[0]
    except (OSError, UnicodeError, ValueError, IndexError):
        raise SupervisorOrdinaryFailure("mount filesystem is unavailable") from None


def _open_absolute_directory(path: Path) -> int:
    if not path.is_absolute() or not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
        raise SupervisorOrdinaryFailure("retained directory traversal is unavailable")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path.anchor, flags)
    try:
        for component in path.parts[1:]:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException as error:
        os.close(descriptor)
        raise


def _open_directory_beneath(root_fd: int, relative: Path) -> int:
    """Retain one no-follow directory identity beneath an already retained root."""
    descriptor = os.dup(root_fd)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        for component in relative.parts:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _link_descriptor_at(descriptor: int, directory_fd: int, final_name: str) -> None:
    """Give the exact still-open inode a final name without path-reopening it."""
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    linkat = libc.linkat
    linkat.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int)
    linkat.restype = ctypes.c_int
    source = os.fsencode(f"/proc/self/fd/{descriptor}")
    if linkat(-100, source, directory_fd, os.fsencode(final_name), 0x400) != 0:  # AT_FDCWD, AT_SYMLINK_FOLLOW
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


class PosixLogStore:
    """Retained-dirfd, no-follow, mount-bound log finalization."""

    def __init__(self, run_root: Path, log_directory: Path) -> None:
        validate_log_paths(run_root, log_directory, platform="linux")
        self._root_fd = None
        self._directory_fd = None
        self._relative_directory = log_directory.relative_to(run_root)
        try:
            self._root_fd = _open_absolute_directory(run_root)
            self._require_private_directory(self._root_fd)
            approved_id = _mount_id(self._root_fd)
            filesystem = _mount_filesystem(approved_id)
            descriptor = os.dup(self._root_fd)
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
            try:
                for component in self._relative_directory.parts:
                    created = False
                    try:
                        os.mkdir(component, 0o700, dir_fd=descriptor)
                        created = True
                    except FileExistsError:
                        pass
                    next_descriptor = os.open(component, flags, dir_fd=descriptor)
                    if created:
                        os.fchmod(next_descriptor, 0o700)
                    self._require_private_directory(next_descriptor)
                    require_local_mount(filesystem, approved_id, _mount_id(next_descriptor))
                    os.close(descriptor)
                    descriptor = next_descriptor
                self._directory_fd = descriptor
                descriptor = None
            finally:
                if descriptor is not None:
                    os.close(descriptor)
        except SupervisorOrdinaryFailure:
            self.close()
            raise
        except BaseException:
            self.close()
            raise SupervisorOrdinaryFailure("secure log directory cannot be opened") from None

    def _verify_directory_identity(self) -> None:
        candidate = None
        try:
            candidate = _open_directory_beneath(self._root_fd, self._relative_directory)
            current = os.fstat(candidate); retained = os.fstat(self._directory_fd)
            if (current.st_dev, current.st_ino) != (retained.st_dev, retained.st_ino):
                raise OSError("retained log directory identity changed")
        except BaseException as error:
            if isinstance(error, SupervisorDisposalRequired):
                raise
            raise SupervisorDisposalRequired("retained log directory identity is unavailable") from None
        finally:
            if candidate is not None:
                try:
                    os.close(candidate)
                except OSError:
                    raise SupervisorDisposalRequired("log identity handle close failed") from None

    @staticmethod
    def _require_private_directory(descriptor: int) -> None:
        details = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(details.st_mode)
            or details.st_uid != os.geteuid()
            or details.st_mode & 0o777 != 0o700
        ):
            raise SupervisorOrdinaryFailure("log directory is not owner-private")

    def _write_one(self, final_name: str, content: bytes) -> None:
        temporary = f".{final_name}.{secrets.token_hex(12)}.tmp"
        descriptor = None
        try:
            self._verify_directory_identity()
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
            descriptor = os.open(temporary, flags, 0o600, dir_fd=self._directory_fd)
            os.fchmod(descriptor, 0o600)
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise OSError("log is not regular")
            if os.fstat(descriptor).st_mode & 0o777 != 0o600:
                raise OSError("log mode is not private")
            view = memoryview(content)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short log write")
                view = view[written:]
            os.fsync(descriptor)
            _link_descriptor_at(descriptor, self._directory_fd, final_name)
            final_status = os.stat(final_name, dir_fd=self._directory_fd, follow_symlinks=False)
            retained_status = os.fstat(descriptor)
            if (
                (final_status.st_dev, final_status.st_ino) != (retained_status.st_dev, retained_status.st_ino)
                or final_status.st_mode & 0o777 != 0o600
                or not stat.S_ISREG(final_status.st_mode)
            ):
                raise OSError("final log identity changed")
            os.unlink(temporary, dir_fd=self._directory_fd)
            os.fsync(self._directory_fd)
            self._verify_directory_identity()
            os.close(descriptor); descriptor = None
        except BaseException as error:
            if descriptor is not None:
                try: os.close(descriptor)
                except OSError: pass
            try: os.unlink(temporary, dir_fd=self._directory_fd)
            except OSError: pass
            classify_log_proof_failure(error)

    def prepare(self, command_id: str) -> None:
        self._verify_directory_identity()
        if any(_exists_at(self._directory_fd, f"{command_id}.{stream}.log") for stream in ("stdout", "stderr")):
            raise SupervisorOrdinaryFailure("command log already exists")

    def finalize(self, command_id: str, stdout: bytes, stderr: bytes) -> None:
        self._write_one(f"{command_id}.stdout.log", stdout)
        self._write_one(f"{command_id}.stderr.log", stderr)

    def prove_canary_absent(self, command_id: str) -> None:
        self._verify_directory_identity()
        names = (f"{command_id}.stdout.log", f"{command_id}.stderr.log")
        cleanup = CanaryLogCleanup(
            unlink=lambda name: os.unlink(name, dir_fd=self._directory_fd),
            fsync_directory=lambda: os.fsync(self._directory_fd),
            exists=lambda name: _exists_at(self._directory_fd, name),
        )
        cleanup.remove_and_prove(names)
        self._verify_directory_identity()

    def close(self) -> None:
        failure = False
        for name in ("_directory_fd", "_root_fd"):
            descriptor = getattr(self, name, None)
            if descriptor is not None:
                try: os.close(descriptor)
                except OSError: failure = True
                setattr(self, name, None)
        if failure:
            raise SupervisorDisposalRequired("log directory handle close failed")


def _exists_at(descriptor: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _path_entry_exists(path: Path) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    return True


def _read_process_identity(pid: int) -> tuple[int, int]:
    try:
        content = (Path("/proc") / str(pid) / "stat").read_bytes()
        end = content.rfind(b")")
        fields = content[end + 2 :].split()
        if end < 2 or len(fields) < 20:
            raise ValueError
        return pid, int(fields[19])
    except FileNotFoundError:
        raise
    except (OSError, ValueError, IndexError):
        raise SupervisorDisposalRequired("process identity is unavailable") from None


def _process_state(pid: int) -> str:
    try:
        content = (Path("/proc") / str(pid) / "stat").read_bytes()
        end = content.rfind(b")")
        return content[end + 2 :].split()[0].decode("ascii")
    except FileNotFoundError:
        return "X"
    except (OSError, UnicodeError, IndexError):
        raise SupervisorDisposalRequired("process state is unavailable") from None


class PidfdRegistry:
    def __init__(self, *, open_pidfd=None, read_identity=_read_process_identity, signal_pidfd=None, close_pidfd=os.close) -> None:
        self._open = open_pidfd or (lambda pid: os.pidfd_open(pid, 0))
        self._read = read_identity
        self._signal = signal_pidfd or (lambda fd, number: signal.pidfd_send_signal(fd, number, None, 0))
        self._close = close_pidfd
        self._entries: dict[tuple[int, int], int] = {}

    @property
    def identities(self) -> frozenset[tuple[int, int]]:
        return frozenset(self._entries)

    def retain(self, pid: int, expected_identity: tuple[int, int] | None = None) -> bool:
        known = [identity for identity in self._entries if identity[0] == pid]
        if known:
            try: current = self._read(pid)
            except (FileNotFoundError, ProcessLookupError): return False
            except SupervisorDisposalRequired: raise
            except OSError: raise SupervisorDisposalRequired("process identity refresh failed") from None
            if expected_identity is not None and current != expected_identity:
                return False
            existing = self._entries.get(current)
            if existing is not None:
                try: self._signal(existing, 0)
                except ProcessLookupError: pass
                except OSError: raise SupervisorDisposalRequired("pidfd refresh failed") from None
                else: return True
        descriptor = None
        try:
            descriptor = self._open(pid)
            identity = self._read(pid)
            if expected_identity is not None and identity != expected_identity:
                return False
            if identity in self._entries:
                return True
            try:
                self._signal(descriptor, 0)
            except ProcessLookupError:
                return False
            except OSError:
                raise SupervisorDisposalRequired("pidfd verification failed") from None
            self._entries[identity] = descriptor
            descriptor = None
            return True
        except (FileNotFoundError, ProcessLookupError):
            return False
        except SupervisorDisposalRequired:
            raise
        except OSError:
            raise SupervisorDisposalRequired("pidfd retain failed") from None
        finally:
            if descriptor is not None:
                try: self._close(descriptor)
                except OSError: raise SupervisorDisposalRequired("pidfd close failed") from None

    def refresh(self, pids: tuple[int, ...]) -> None:
        for pid in pids:
            self.retain(pid)

    def close_all(self) -> None:
        failure = False
        for descriptor in self._entries.values():
            try: self._close(descriptor)
            except OSError: failure = True
        self._entries.clear()
        if failure:
            raise SupervisorDisposalRequired("pidfd close failed")

    def verify_dead(self) -> None:
        for descriptor in self._entries.values():
            try:
                self._signal(descriptor, 0)
            except ProcessLookupError:
                continue
            except OSError:
                raise SupervisorDisposalRequired("pidfd terminal proof failed") from None
            raise SupervisorDisposalRequired("retained process remains live")


class LinuxCgroup:
    def __init__(self, *, path: Path, read_text=None, write_text=None, list_pids=None, remove=None, process_state=_process_state, exists=None, monotonic=time.monotonic, sleep=time.sleep, parent_fd=None, directory_fd=None) -> None:
        self.path = path
        self._parent_fd = parent_fd
        self._directory_fd = directory_fd
        self._identity = None if directory_fd is None else self._stat_identity(os.fstat(directory_fd))
        self._read = read_text or self._read_control
        self._write = write_text or self._write_control
        self._pids = list_pids or self._read_pids
        self._remove = remove or self._remove_retained
        self._state = process_state
        self._exists = exists or self._retained_name_exists
        self._monotonic = monotonic
        self._sleep = sleep

    @classmethod
    def retain(cls, path: Path) -> "LinuxCgroup":
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        parent_fd = _open_absolute_directory(path.parent)
        try:
            directory_fd = os.open(path.name, flags, dir_fd=parent_fd)
        except BaseException:
            os.close(parent_fd)
            raise
        return cls(path=path, parent_fd=parent_fd, directory_fd=directory_fd)

    @staticmethod
    def _stat_identity(details) -> tuple[int, int]:
        return details.st_dev, details.st_ino

    def _verify_retained_name(self) -> None:
        if self._directory_fd is None:
            return
        try:
            named = os.stat(self.path.name, dir_fd=self._parent_fd, follow_symlinks=False)
            retained = os.fstat(self._directory_fd)
        except OSError:
            raise SupervisorDisposalRequired("cgroup retained identity is unavailable") from None
        if self._stat_identity(named) != self._identity or self._stat_identity(retained) != self._identity:
            raise SupervisorDisposalRequired("cgroup retained identity changed")

    def open_control(self, name: str, flags: int) -> int:
        if self._directory_fd is None:
            return os.open(self.path / name, flags | getattr(os, "O_CLOEXEC", 0))
        self._verify_retained_name()
        try:
            return os.open(name, flags | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0), dir_fd=self._directory_fd)
        except OSError:
            raise SupervisorDisposalRequired("cgroup control file is unavailable") from None

    def _read_control(self, name: str) -> str:
        descriptor = self.open_control(name, os.O_RDONLY)
        try:
            return os.read(descriptor, 1_048_576).decode("ascii")
        finally:
            os.close(descriptor)

    def _write_control(self, name: str, value: str) -> None:
        descriptor = self.open_control(name, os.O_WRONLY)
        try:
            data = value.encode("ascii")
            if os.write(descriptor, data) != len(data):
                raise OSError("short cgroup write")
        finally:
            os.close(descriptor)

    def _remove_retained(self) -> None:
        self._verify_retained_name()
        os.rmdir(self.path.name, dir_fd=self._parent_fd)

    def _retained_name_exists(self) -> bool:
        if self._parent_fd is None:
            return self.path.exists()
        try:
            os.stat(self.path.name, dir_fd=self._parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        return True

    def close(self) -> None:
        failed = False
        for name in ("_directory_fd", "_parent_fd"):
            descriptor = getattr(self, name, None)
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    failed = True
                setattr(self, name, None)
        if failed:
            raise SupervisorDisposalRequired("cgroup retained handle close failed")

    def _read_pids(self) -> tuple[int, ...]:
        try:
            values = tuple(int(value) for value in self._read("cgroup.procs").split())
        except (OSError, ValueError):
            raise SupervisorDisposalRequired("cgroup process list is unavailable") from None
        if any(value <= 0 for value in values) or len(values) != len(set(values)):
            raise SupervisorDisposalRequired("cgroup process list is invalid")
        return values

    def pids(self) -> tuple[int, ...]:
        return self._pids()

    def _populated(self) -> bool:
        try:
            values = dict(line.split() for line in self._read("cgroup.events").splitlines())
        except (OSError, ValueError):
            raise SupervisorDisposalRequired("cgroup events are unavailable") from None
        if values.get("populated") not in {"0", "1"}:
            raise SupervisorDisposalRequired("cgroup populated state is invalid")
        return values["populated"] == "1"

    def kill_empty_remove(self, deadline: float) -> None:
        try:
            self._write("cgroup.kill", "1")
        except OSError:
            raise SupervisorDisposalRequired("cgroup kill failed") from None
        while self._populated():
            pids = self.pids()
            if any(self._state(pid) == "D" for pid in pids):
                raise SupervisorDisposalRequired("cgroup contains unkillable work")
            if self._monotonic() >= deadline:
                raise SupervisorDisposalRequired("cgroup did not become empty")
            self._sleep(min(0.01, max(0.0, deadline - self._monotonic())))
        if self.pids() or self._populated():
            raise SupervisorDisposalRequired("cgroup emptiness is not stable")
        try:
            self._remove()
        except OSError:
            raise SupervisorDisposalRequired("cgroup removal failed") from None
        if self._exists():
            raise SupervisorDisposalRequired("cgroup removal is not proved")
        if self._directory_fd is not None:
            try:
                retained = os.fstat(self._directory_fd)
            except OSError:
                raise SupervisorDisposalRequired("removed cgroup identity is unavailable") from None
            if retained.st_nlink != 0:
                raise SupervisorDisposalRequired("removed cgroup inode remains linked")
        self.close()


class WindowsJobBoundary:
    def __init__(self, *, terminate, active_count, close, monotonic=time.monotonic, sleep=time.sleep) -> None:
        self._terminate = terminate; self._active_count = active_count; self._close = close
        self._monotonic = monotonic; self._sleep = sleep

    def terminate_empty_close(self, deadline: float) -> None:
        if not self._terminate():
            raise SupervisorDisposalRequired("job termination failed")
        while self._active_count() != 0:
            if self._monotonic() >= deadline:
                raise SupervisorDisposalRequired("job did not become empty")
            self._sleep(min(0.01, max(0.0, deadline - self._monotonic())))
        if self._active_count() != 0 or not self._close():
            raise SupervisorDisposalRequired("job closure failed")


def _ensure_linux_primitives() -> None:
    if sys.platform != "linux" or not callable(getattr(os, "fork", None)):
        raise SupervisorOrdinaryFailure("Linux fork is unavailable")
    if not callable(getattr(os, "pidfd_open", None)) or not callable(getattr(signal, "pidfd_send_signal", None)):
        raise SupervisorOrdinaryFailure("Linux pidfd is unavailable")
    if not Path("/proc/self/stat").is_file():
        raise SupervisorOrdinaryFailure("procfs is unavailable")
    descriptor = None
    try:
        descriptor = os.pidfd_open(os.getpid(), 0)
        _read_process_identity(os.getpid())
        signal.pidfd_send_signal(descriptor, 0, None, 0)
    except BaseException as error:
        if isinstance(error, SupervisorOrdinaryFailure): raise
        raise SupervisorOrdinaryFailure("Linux pidfd contract is unavailable") from None
    finally:
        if descriptor is not None:
            try: os.close(descriptor)
            except OSError: raise SupervisorOrdinaryFailure("Linux pidfd close failed") from None

    import ctypes as linux_ctypes
    libc = linux_ctypes.CDLL(None, use_errno=True)
    try: prctl = libc.prctl
    except AttributeError: raise SupervisorOrdinaryFailure("Linux subreaper is unavailable") from None
    prctl.argtypes = (linux_ctypes.c_int, linux_ctypes.c_ulong, linux_ctypes.c_ulong, linux_ctypes.c_ulong, linux_ctypes.c_ulong)
    prctl.restype = linux_ctypes.c_int
    current = linux_ctypes.c_int()
    if prctl(36, 1, 0, 0, 0) != 0 or prctl(37, linux_ctypes.addressof(current), 0, 0, 0) != 0 or current.value != 1:
        raise SupervisorOrdinaryFailure("Linux subreaper contract is unavailable")


def _retain_new_linux_cgroup(path: Path) -> LinuxCgroup:
    path.mkdir(mode=0o700)
    group = None
    try:
        group = LinuxCgroup.retain(path)
        for name, flags in (
            ("cgroup.procs", os.O_RDONLY),
            ("cgroup.procs", os.O_WRONLY),
            ("cgroup.events", os.O_RDONLY),
            ("cgroup.kill", os.O_WRONLY),
        ):
            descriptor = group.open_control(name, flags)
            os.close(descriptor)
        if group.pids() or group._populated():
            raise SupervisorDisposalRequired("new cgroup is not empty")
        return group
    except BaseException:
        if group is not None:
            try:
                group.kill_empty_remove(time.monotonic() + 5)
            except BaseException:
                raise SupervisorDisposalRequired("incomplete cgroup residue is unverifiable") from None
        else:
            try:
                path.rmdir()
            except OSError:
                raise SupervisorDisposalRequired("incomplete cgroup residue is unverifiable") from None
        raise


def _probe_linux_cgroup_capabilities(group: LinuxCgroup, deadline: float) -> None:
    read_fd, write_fd = os.pipe()
    registry = PidfdRegistry(); child = None; status = None
    try:
        child = os.fork()
        if child == 0:
            try:
                os.close(write_fd)
                os.read(read_fd, 1)
            finally:
                os._exit(0)
        os.close(read_fd); read_fd = -1
        identity = _read_process_identity(child)
        if not registry.retain(child, expected_identity=identity):
            raise SupervisorDisposalRequired("cgroup probe pidfd could not be retained")
        group._write("cgroup.procs", str(child))
        if group.pids() != (child,) or os.getpid() in group.pids():
            raise SupervisorDisposalRequired("cgroup attach capability is not exact")
        group.kill_empty_remove(deadline)
        group = None
        while status is None:
            try:
                waited, raw_status = os.waitpid(child, os.WNOHANG)
            except OSError:
                raise SupervisorDisposalRequired("cgroup probe reap failed") from None
            if waited == child:
                status = raw_status
                break
            require_before_deadline(deadline)
            time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
        registry.verify_dead(); registry.close_all()
    finally:
        cleanup_failed = False
        for descriptor in (read_fd, write_fd):
            if descriptor >= 0:
                try: os.close(descriptor)
                except OSError: cleanup_failed = True
        if group is not None:
            try: group.kill_empty_remove(deadline)
            except BaseException: cleanup_failed = True
        if child is not None and status is None:
            try:
                for descriptor in tuple(registry._entries.values()):
                    registry._signal(descriptor, signal.SIGKILL)
                os.waitpid(child, 0)
            except BaseException:
                cleanup_failed = True
        try: registry.close_all()
        except BaseException: cleanup_failed = True
        if cleanup_failed:
            raise SupervisorDisposalRequired("cgroup capability probe cleanup failed")


def _create_linux_cgroup(command_id: str) -> LinuxCgroup:
    mount = Path("/sys/fs/cgroup")
    try:
        lines = Path("/proc/self/cgroup").read_text(encoding="ascii").splitlines()
        memberships = [line[3:] for line in lines if line.startswith("0::")]
        if len(memberships) != 1 or ".." in Path(memberships[0]).parts:
            raise SupervisorOrdinaryFailure("cgroup v2 membership is invalid")
        root = mount.resolve(strict=True)
        if not (root / "cgroup.controllers").is_file():
            raise SupervisorOrdinaryFailure("cgroup v2 is unavailable")
        parent = (root / memberships[0].lstrip("/")).resolve(strict=True)
        if parent != root and root not in parent.parents:
            raise SupervisorOrdinaryFailure("cgroup v2 membership escaped its mount")
        prefix = f"z1rr-g0-{command_id}-{os.getpid()}-{secrets.token_hex(6)}"
        probe = _retain_new_linux_cgroup(parent / f"{prefix}-probe")
        _probe_linux_cgroup_capabilities(probe, time.monotonic() + 5)
        return _retain_new_linux_cgroup(parent / prefix)
    except SupervisorDisposalRequired:
        raise
    except SupervisorOrdinaryFailure:
        raise
    except (OSError, UnicodeError, ValueError):
        raise SupervisorOrdinaryFailure("target cgroup cannot be created") from None


def _pipe_nonblocking() -> tuple[int, int]:
    required = getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    if not hasattr(os, "pipe2") or not required:
        raise SupervisorOrdinaryFailure("fixed nonblocking IPC is unavailable")
    try: return os.pipe2(required)
    except OSError: raise SupervisorOrdinaryFailure("fixed nonblocking IPC is unavailable") from None


def _close_descriptors(descriptors: list[int]) -> None:
    failure = False
    while descriptors:
        descriptor = descriptors.pop()
        try: os.close(descriptor)
        except OSError: failure = True
    if failure: raise SupervisorDisposalRequired("descriptor close failed")


def _wait_read_byte(descriptor: int, expected: bytes, deadline: float) -> None:
    import select
    while time.monotonic() < deadline:
        readable, _, _ = select.select((descriptor,), (), (), min(0.05, max(0.0, deadline - time.monotonic())))
        if not readable: continue
        try: content = os.read(descriptor, 2)
        except BlockingIOError: continue
        if content != expected: raise SupervisorDisposalRequired("containment handshake is invalid")
        return
    raise SupervisorDisposalRequired("containment handshake timed out")


def _linux_child(request: dict, cgroup_fd: int, cwd_fd: int, attach_write: int, release_read: int, stdin_read: int, stdout_write: int, stderr_write: int, close_fds: tuple[int, ...]) -> None:
    try:
        for descriptor in close_fds:
            try: os.close(descriptor)
            except OSError: pass
        os.write(cgroup_fd, str(os.getpid()).encode("ascii"))
        os.close(cgroup_fd)
        if os.write(attach_write, b"A") != 1: os._exit(125)
        os.close(attach_write)
        os.set_blocking(release_read, True)
        if os.read(release_read, 1) != b"G": os._exit(125)
        os.close(release_read)
        for descriptor in (stdin_read, stdout_write, stderr_write): os.set_blocking(descriptor, True)
        os.dup2(stdin_read, 0); os.dup2(stdout_write, 1); os.dup2(stderr_write, 2)
        for descriptor in (stdin_read, stdout_write, stderr_write):
            if descriptor > 2: os.close(descriptor)
        os.fchdir(cwd_fd)
        os.close(cwd_fd)
        environment = dict(request["environment"])
        os.execvpe(request["argv"][0], request["argv"], environment)
    except BaseException:
        try: os.write(2, b"target exec failed\n")
        except OSError: pass
    os._exit(127)


def _reap_all(deadline: float, root_pid: int, root_status: int | None) -> int | None:
    while True:
        reaped_any = False
        while True:
            try: pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError: return root_status
            except InterruptedError: continue
            except OSError: raise SupervisorDisposalRequired("child reap failed") from None
            if pid == 0: break
            reaped_any = True
            if pid == root_pid: root_status = status
        if time.monotonic() >= deadline:
            raise SupervisorDisposalRequired("adopted children were not reaped")
        if not reaped_any: time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))


def _drain_linux_streams(stdout_fd: int, stderr_fd: int, stdin_fd: int | None, input_bytes: bytes, stdout: StreamCapture, stderr: StreamCapture, *, execution_deadline: float, root_pid: int, group: LinuxCgroup, registry: PidfdRegistry) -> tuple[bool, int | None, int | None]:
    import selectors
    selector = selectors.DefaultSelector()
    selector.register(stdout_fd, selectors.EVENT_READ, stdout)
    selector.register(stderr_fd, selectors.EVENT_READ, stderr)
    input_offset = 0
    if stdin_fd is not None and input_bytes:
        selector.register(stdin_fd, selectors.EVENT_WRITE, None)
    elif stdin_fd is not None:
        os.close(stdin_fd); stdin_fd = None
    root_status = None; timed_out = False
    try:
        while True:
            try:
                waited, status = os.waitpid(root_pid, os.WNOHANG)
            except ChildProcessError:
                waited = root_pid; status = root_status
            except OSError:
                raise SupervisorDisposalRequired("root process wait failed") from None
            if waited == root_pid:
                if status is not None: root_status = status
                break
            now = time.monotonic()
            if now >= execution_deadline:
                try:
                    waited, status = os.waitpid(root_pid, os.WNOHANG)
                except ChildProcessError:
                    waited = root_pid; status = root_status
                except OSError:
                    raise SupervisorDisposalRequired("root process wait failed") from None
                if waited == root_pid:
                    if status is not None: root_status = status
                    break
                timed_out = True; break
            pids = group.pids(); registry.refresh(pids)
            for pid in pids:
                if _process_state(pid) == "D": raise SupervisorDisposalRequired("target entered unkillable kernel state")
            events = selector.select(min(0.05, max(0.0, execution_deadline - now)))
            for key, _ in events:
                if key.fileobj == stdin_fd:
                    try: count = os.write(stdin_fd, input_bytes[input_offset : input_offset + 65_536])
                    except BlockingIOError: continue
                    except BrokenPipeError:
                        selector.unregister(stdin_fd); os.close(stdin_fd); stdin_fd = None
                        continue
                    input_offset += count
                    if input_offset == len(input_bytes):
                        selector.unregister(stdin_fd); os.close(stdin_fd); stdin_fd = None
                    continue
                capture = key.data
                try: content = os.read(key.fd, 65_536)
                except BlockingIOError: continue
                if content: capture.feed(content)
                else:
                    selector.unregister(key.fileobj); os.close(key.fd); capture.finish()
                    if key.fd == stdout_fd: stdout_fd = -1
                    else: stderr_fd = -1
    finally:
        selector.close()
    return timed_out, root_status, stdin_fd


def _drain_to_eof(stdout_fd: int, stderr_fd: int, stdout: StreamCapture, stderr: StreamCapture, deadline: float) -> None:
    import selectors
    selector = selectors.DefaultSelector()
    if not stdout.eof and stdout_fd >= 0: selector.register(stdout_fd, selectors.EVENT_READ, stdout)
    if not stderr.eof and stderr_fd >= 0: selector.register(stderr_fd, selectors.EVENT_READ, stderr)
    try:
        while selector.get_map():
            if time.monotonic() >= deadline: raise SupervisorDisposalRequired("stream EOF was not reached")
            for key, _ in selector.select(min(0.05, max(0.0, deadline - time.monotonic()))):
                try: content = os.read(key.fd, 65_536)
                except BlockingIOError: continue
                if content: key.data.feed(content)
                else:
                    selector.unregister(key.fileobj); os.close(key.fd); key.data.finish()
    finally:
        selector.close()


def _execute_linux(request: dict, started: float, supervisor_response_fd: int | None = None) -> dict:
    _ensure_linux_primitives()
    execution_deadline = started + request["execution_timeout_seconds"]
    run_root = Path(request["run_root"]); log_directory = Path(request["log_directory"])
    canaries = tuple(base64.b64decode(item) for item in request["secret_canaries_b64"])
    stdout = StreamCapture(limit=request["stdout_limit"], canaries=canaries)
    stderr = StreamCapture(limit=request["stderr_limit"], canaries=canaries)
    store = PosixLogStore(run_root, log_directory)
    group = None; registry = PidfdRegistry(); root_pid = None; released = False
    descriptors: list[int] = []; root_status = None; cleanup_deadline = None
    try:
        store.prepare(request["command_id"])
        cwd_fd = _open_directory_beneath(store._root_fd, Path(request["cwd"]).relative_to(run_root))
        if _mount_id(cwd_fd) != _mount_id(store._root_fd):
            os.close(cwd_fd)
            raise SupervisorOrdinaryFailure("target cwd crosses the retained run-root mount")
        descriptors.append(cwd_fd)
        group = _create_linux_cgroup(request["command_id"])
        attach_read, attach_write = _pipe_nonblocking(); release_read, release_write = _pipe_nonblocking()
        stdin_read, stdin_write = _pipe_nonblocking(); stdout_read, stdout_write = _pipe_nonblocking(); stderr_read, stderr_write = _pipe_nonblocking()
        descriptors.extend((attach_read, attach_write, release_read, release_write, stdin_read, stdin_write, stdout_read, stdout_write, stderr_read, stderr_write))
        cgroup_fd = group.open_control("cgroup.procs", os.O_WRONLY)
        root_pid = os.fork()
        if root_pid == 0:
            _linux_child(
                request, cgroup_fd, cwd_fd, attach_write, release_read, stdin_read, stdout_write, stderr_write,
                tuple(descriptor for descriptor in (attach_read, release_write, stdin_write, stdout_read, stderr_read, supervisor_response_fd) if descriptor is not None),
            )
        os.close(cgroup_fd)
        os.close(cwd_fd); descriptors.remove(cwd_fd)
        for descriptor in (attach_write, release_read, stdin_read, stdout_write, stderr_write):
            os.close(descriptor); descriptors.remove(descriptor)
        identity = _read_process_identity(root_pid)
        if not registry.retain(root_pid, expected_identity=identity):
            raise SupervisorDisposalRequired("root pidfd could not be retained")
        handshake_deadline = min(execution_deadline, time.monotonic() + request["cleanup_timeout_seconds"])
        _wait_read_byte(attach_read, b"A", handshake_deadline)
        os.close(attach_read); descriptors.remove(attach_read)
        pids = group.pids()
        if pids != (root_pid,) or os.getpid() in pids:
            raise SupervisorDisposalRequired("target cgroup membership is not exact")
        gate = ReleaseGate(); gate.mark_contained()
        def release_target() -> None:
            def write_release() -> None:
                if os.write(release_write, b"G") != 1:
                    raise SupervisorDisposalRequired("target release failed")
            _release_before_deadline(execution_deadline, write_release)
        try: gate.release_with(release_target)
        finally: released = gate.released
        os.close(release_write); descriptors.remove(release_write)
        input_bytes = b"" if request["input_b64"] is None else base64.b64decode(request["input_b64"])
        timed_out, root_status, remaining_stdin = _drain_linux_streams(
            stdout_read, stderr_read, stdin_write, input_bytes, stdout, stderr,
            execution_deadline=execution_deadline, root_pid=root_pid, group=group, registry=registry,
        )
        if remaining_stdin is None and stdin_write in descriptors: descriptors.remove(stdin_write)
        cleanup_deadline = time.monotonic() + request["cleanup_timeout_seconds"]
        _latch_cleanup_deadline(cleanup_deadline)
        registry.refresh(group.pids())
        group.kill_empty_remove(cleanup_deadline); group = None
        require_before_deadline(cleanup_deadline)
        root_status = _reap_all(cleanup_deadline, root_pid, root_status)
        registry.verify_dead(); registry.close_all()
        _drain_to_eof(stdout_read, stderr_read, stdout, stderr, cleanup_deadline)
        require_before_deadline(cleanup_deadline)
        for descriptor in (stdout_read, stderr_read):
            if descriptor in descriptors: descriptors.remove(descriptor)
        if stdin_write in descriptors:
            os.close(stdin_write); descriptors.remove(stdin_write)
        if root_status is None and not timed_out:
            raise SupervisorDisposalRequired("root exit status is unavailable")
        exit_code = None if timed_out else os.waitstatus_to_exitcode(root_status)
        if stdout.canary_seen or stderr.canary_seen:
            store.prove_canary_absent(request["command_id"])
            require_before_deadline(cleanup_deadline)
            return _response("CANARY_DETECTED", exit_code, started, stdout, stderr)
        store.finalize(request["command_id"], stdout.retained, stderr.retained)
        require_before_deadline(cleanup_deadline)
        status = "TIMED_OUT" if timed_out else ("PASS" if exit_code == 0 else "FAILED")
        return _response(status, exit_code, started, stdout, stderr)
    except SupervisorOrdinaryFailure:
        raise
    except SupervisorDisposalRequired:
        raise
    except BaseException:
        if released or root_pid is not None:
            raise SupervisorDisposalRequired("Linux operation proof failed") from None
        raise SupervisorOrdinaryFailure("Linux target did not start") from None
    finally:
        cleanup_failed = False
        if cleanup_deadline is None:
            cleanup_deadline = time.monotonic() + request["cleanup_timeout_seconds"]
            _latch_cleanup_deadline(cleanup_deadline)
        try:
            if group is not None:
                group.kill_empty_remove(cleanup_deadline)
        except SupervisorDisposalRequired:
            cleanup_failed = True
        try:
            if root_pid is not None:
                root_status = _reap_all(cleanup_deadline, root_pid, root_status)
        except SupervisorDisposalRequired:
            cleanup_failed = True
        try:
            registry.verify_dead()
        except SupervisorDisposalRequired:
            cleanup_failed = True
        try:
            registry.close_all()
        except SupervisorDisposalRequired:
            cleanup_failed = True
        try:
            _close_descriptors(descriptors)
        except SupervisorDisposalRequired:
            cleanup_failed = True
        try:
            store.close()
        except SupervisorDisposalRequired:
            cleanup_failed = True
        try:
            require_before_deadline(cleanup_deadline)
        except SupervisorDisposalRequired:
            cleanup_failed = True
        if cleanup_failed:
            raise SupervisorDisposalRequired("Linux cleanup proof failed")


_REQUEST_FIELDS = {
    "protocol_version", "command_id", "argv", "cwd", "run_root",
    "execution_timeout_seconds", "cleanup_timeout_seconds", "environment",
    "secret_canaries_b64", "input_b64", "stdout_limit", "stderr_limit", "log_directory",
}


def _plain_int(value: object, minimum: int, maximum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum


def validate_request(value: object) -> dict:
    if (
        not isinstance(value, dict)
        or set(value) != _REQUEST_FIELDS
        or type(value.get("protocol_version")) is not int
        or value["protocol_version"] != 1
    ):
        raise SupervisorOrdinaryFailure("request shape is invalid")
    if not isinstance(value.get("command_id"), str) or _SAFE_IDENTIFIER.fullmatch(value["command_id"]) is None:
        raise SupervisorOrdinaryFailure("request command is invalid")
    if not isinstance(value.get("argv"), list) or not value["argv"] or any(not isinstance(item, str) or not item or "\x00" in item for item in value["argv"]):
        raise SupervisorOrdinaryFailure("request argv is invalid")
    if not _plain_int(value.get("execution_timeout_seconds"), 1, 18_000) or not _plain_int(value.get("cleanup_timeout_seconds"), 5, 600):
        raise SupervisorOrdinaryFailure("request timeout is invalid")
    if not _plain_int(value.get("stdout_limit"), 0, 2**31 - 1) or not _plain_int(value.get("stderr_limit"), 0, 2**31 - 1):
        raise SupervisorOrdinaryFailure("request limit is invalid")
    for key in ("cwd", "run_root", "log_directory"):
        if not isinstance(value.get(key), str) or "\x00" in value[key]:
            raise SupervisorOrdinaryFailure("request path is invalid")
    environment = value.get("environment")
    if not isinstance(environment, list) or any(not isinstance(item, list) or len(item) != 2 or any(not isinstance(part, str) for part in item) for item in environment):
        raise SupervisorOrdinaryFailure("request environment is invalid")
    keys = [item[0] for item in environment]
    normalized_keys = [key.casefold() for key in keys] if os.name == "nt" else keys
    if len(normalized_keys) != len(set(normalized_keys)) or any(not key or "=" in key or "\x00" in key or "\x00" in val for key, val in environment):
        raise SupervisorOrdinaryFailure("request environment is invalid")
    canaries = value.get("secret_canaries_b64")
    if not isinstance(canaries, list) or any(not isinstance(item, str) for item in canaries):
        raise SupervisorOrdinaryFailure("request canaries are invalid")
    try:
        decoded = tuple(base64.b64decode(item, validate=True) for item in canaries)
        input_value = value.get("input_b64")
        if input_value is not None:
            base64.b64decode(input_value, validate=True)
    except (ValueError, TypeError):
        raise SupervisorOrdinaryFailure("request encoding is invalid") from None
    if any(not item for item in decoded):
        raise SupervisorOrdinaryFailure("request canary is empty")
    run_root = Path(value["run_root"]); cwd = Path(value["cwd"]); logs = Path(value["log_directory"])
    validate_log_paths(run_root, logs, platform="windows" if os.name == "nt" else "linux")
    if ".." in cwd.parts:
        raise SupervisorOrdinaryFailure("request cwd contains parent traversal")
    try: cwd.relative_to(run_root)
    except ValueError: raise SupervisorOrdinaryFailure("request cwd is outside run root") from None
    return value


def _empty_capture(limit: int, canaries: tuple[bytes, ...]) -> StreamCapture:
    capture = StreamCapture(limit=limit, canaries=canaries)
    capture.finish()
    return capture


def _response(status: str, exit_code: int | None, started: float, stdout: StreamCapture, stderr: StreamCapture, *, proof: bool = True) -> dict:
    return {
        "protocol_version": 1,
        "status": status,
        "exit_code": exit_code,
        "duration_ms": max(0, int((time.monotonic() - started) * 1000)),
        "cleanup_deadline_monotonic_ns": (
            None
            if _ACTIVE_CLEANUP_DEADLINE is None
            else int(_ACTIVE_CLEANUP_DEADLINE * 1_000_000_000)
        ),
        "stdout_sha256": "sha256:" + stdout.hexdigest,
        "stderr_sha256": "sha256:" + stderr.hexdigest,
        "proof": {"boundary_empty": proof, "streams_eof": proof and stdout.eof and stderr.eof, "logs_finalized": proof},
    }


if os.name == "nt":
    import ctypes
    import msvcrt
    import _winapi
    from ctypes import wintypes

    _INVALID_HANDLE = ctypes.c_void_p(-1).value
    _GENERIC_READ = 0x80000000
    _GENERIC_WRITE = 0x40000000
    _DELETE = 0x00010000
    _SHARE_READ = 0x00000001
    _SHARE_WRITE = 0x00000002
    _OPEN_EXISTING = 3
    _CREATE_NEW = 1
    _FILE_ATTRIBUTE_NORMAL = 0x80
    _FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    _FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    _FILE_ATTRIBUTE_DIRECTORY = 0x10
    _FILE_ATTRIBUTE_REPARSE_POINT = 0x400
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
    _STILL_ACTIVE = 259

    class _FileAttributeTagInfo(ctypes.Structure):
        _fields_ = [("FileAttributes", wintypes.DWORD), ("ReparseTag", wintypes.DWORD)]

    class _ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("FileAttributes", wintypes.DWORD), ("CreationTimeLow", wintypes.DWORD), ("CreationTimeHigh", wintypes.DWORD),
            ("LastAccessTimeLow", wintypes.DWORD), ("LastAccessTimeHigh", wintypes.DWORD),
            ("LastWriteTimeLow", wintypes.DWORD), ("LastWriteTimeHigh", wintypes.DWORD),
            ("VolumeSerialNumber", wintypes.DWORD), ("FileSizeHigh", wintypes.DWORD), ("FileSizeLow", wintypes.DWORD),
            ("NumberOfLinks", wintypes.DWORD), ("FileIndexHigh", wintypes.DWORD), ("FileIndexLow", wintypes.DWORD),
        ]

    class _IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimitInformation), ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class _BasicAccountingInformation(ctypes.Structure):
        _fields_ = [
            ("TotalUserTime", ctypes.c_longlong), ("TotalKernelTime", ctypes.c_longlong),
            ("ThisPeriodTotalUserTime", ctypes.c_longlong), ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
            ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD),
            ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _create_file = _kernel32.CreateFileW
    _create_file.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    _create_file.restype = wintypes.HANDLE
    _get_info = _kernel32.GetFileInformationByHandleEx
    _get_info.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
    _get_info.restype = wintypes.BOOL
    _get_basic_info = _kernel32.GetFileInformationByHandle
    _get_basic_info.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ByHandleFileInformation)); _get_basic_info.restype = wintypes.BOOL
    _get_final_path = _kernel32.GetFinalPathNameByHandleW
    _get_final_path.argtypes = (wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD)
    _get_final_path.restype = wintypes.DWORD
    _close_handle = _kernel32.CloseHandle
    _close_handle.argtypes = (wintypes.HANDLE,); _close_handle.restype = wintypes.BOOL
    _flush_file = _kernel32.FlushFileBuffers
    _flush_file.argtypes = (wintypes.HANDLE,); _flush_file.restype = wintypes.BOOL
    _set_file_info = _kernel32.SetFileInformationByHandle
    _set_file_info.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD); _set_file_info.restype = wintypes.BOOL
    _peek_named_pipe = _kernel32.PeekNamedPipe
    _peek_named_pipe.argtypes = (wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, wintypes.LPVOID, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID); _peek_named_pipe.restype = wintypes.BOOL
    _create_job = _kernel32.CreateJobObjectW
    _create_job.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR); _create_job.restype = wintypes.HANDLE
    _set_job = _kernel32.SetInformationJobObject
    _set_job.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD); _set_job.restype = wintypes.BOOL
    _assign_job = _kernel32.AssignProcessToJobObject
    _assign_job.argtypes = (wintypes.HANDLE, wintypes.HANDLE); _assign_job.restype = wintypes.BOOL
    _terminate_job = _kernel32.TerminateJobObject
    _terminate_job.argtypes = (wintypes.HANDLE, wintypes.UINT); _terminate_job.restype = wintypes.BOOL
    _query_job = _kernel32.QueryInformationJobObject
    _query_job.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD, wintypes.LPVOID); _query_job.restype = wintypes.BOOL
    _wait_handle = _kernel32.WaitForSingleObject
    _wait_handle.argtypes = (wintypes.HANDLE, wintypes.DWORD); _wait_handle.restype = wintypes.DWORD
    _get_exit_code = _kernel32.GetExitCodeProcess
    _get_exit_code.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)); _get_exit_code.restype = wintypes.BOOL
    _terminate_process = _kernel32.TerminateProcess
    _terminate_process.argtypes = (wintypes.HANDLE, wintypes.UINT); _terminate_process.restype = wintypes.BOOL
    _resume_thread = _kernel32.ResumeThread
    _resume_thread.argtypes = (wintypes.HANDLE,); _resume_thread.restype = wintypes.DWORD
    _get_drive_type = _kernel32.GetDriveTypeW
    _get_drive_type.argtypes = (wintypes.LPCWSTR,); _get_drive_type.restype = wintypes.UINT


class WindowsLogStore:
    """Retains no-delete-share ancestor handles and finalizes with write-through."""

    def __init__(self, run_root: Path, log_directory: Path) -> None:
        validate_log_paths(run_root, log_directory, platform="windows")
        self._handles: list[int] = []
        self._volume_serial: int | None = None
        self._run_root = run_root
        self.directory = log_directory
        try:
            if _get_drive_type(run_root.anchor) not in {3, 6}:
                raise SupervisorOrdinaryFailure("Windows run root is not local storage")
            current = Path(run_root.anchor)
            self._retain_directory(current)
            for component in run_root.parts[1:]:
                current = current / component
                self._retain_directory(current)
            current = run_root
            for component in log_directory.relative_to(run_root).parts:
                current = current / component
                try: current.mkdir(mode=0o700)
                except FileExistsError: pass
                self._retain_directory(current)
        except SupervisorOrdinaryFailure:
            self.close()
            raise
        except BaseException:
            self.close()
            raise SupervisorOrdinaryFailure("secure Windows log directory cannot be opened") from None

    def retain_cwd(self, cwd: Path) -> None:
        current = self._run_root
        for component in cwd.relative_to(self._run_root).parts:
            current = current / component
            self._retain_directory(current)

    @staticmethod
    def _normalize(value: str) -> str:
        if value.startswith("\\\\?\\UNC\\"): value = "\\\\" + value[8:]
        elif value.startswith("\\\\?\\"): value = value[4:]
        return os.path.normcase(os.path.normpath(value))

    def _retain_directory(self, path: Path) -> None:
        handle = _create_file(str(path), _GENERIC_READ, _SHARE_READ | _SHARE_WRITE, None, _OPEN_EXISTING, _FILE_FLAG_OPEN_REPARSE_POINT | _FILE_FLAG_BACKUP_SEMANTICS, None)
        if handle == _INVALID_HANDLE:
            raise SupervisorOrdinaryFailure("Windows directory handle cannot be retained")
        try:
            attributes = _FileAttributeTagInfo()
            if not _get_info(handle, 9, ctypes.byref(attributes), ctypes.sizeof(attributes)):
                raise SupervisorOrdinaryFailure("Windows directory handle cannot be verified")
            if not attributes.FileAttributes & _FILE_ATTRIBUTE_DIRECTORY or attributes.FileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
                raise SupervisorOrdinaryFailure("Windows log path contains a reparse point")
            basic = _ByHandleFileInformation()
            if not _get_basic_info(handle, ctypes.byref(basic)):
                raise SupervisorOrdinaryFailure("Windows volume identity is unavailable")
            if self._volume_serial is None:
                self._volume_serial = int(basic.VolumeSerialNumber)
            elif self._volume_serial != int(basic.VolumeSerialNumber):
                raise SupervisorOrdinaryFailure("Windows log path crosses a mount boundary")
            needed = _get_final_path(handle, None, 0, 0)
            if needed == 0: raise SupervisorOrdinaryFailure("Windows final path is unavailable")
            buffer = ctypes.create_unicode_buffer(needed)
            if _get_final_path(handle, buffer, needed, 0) == 0 or self._normalize(buffer.value) != self._normalize(str(path)):
                raise SupervisorOrdinaryFailure("Windows retained path identity changed")
            self._handles.append(int(handle)); handle = None
        finally:
            if handle is not None: _close_handle(handle)

    def prepare(self, command_id: str) -> None:
        for stream in ("stdout", "stderr"):
            if _path_entry_exists(self.directory / f"{command_id}.{stream}.log"):
                raise SupervisorOrdinaryFailure("command log already exists")

    def _write_final(self, final_name: str, content: bytes) -> None:
        temp_name = f".{final_name}.{secrets.token_hex(12)}.tmp"
        temp_path = self.directory / temp_name; final_path = self.directory / final_name
        handle = _create_file(str(temp_path), _GENERIC_READ | _GENERIC_WRITE | _DELETE, _SHARE_READ, None, _CREATE_NEW, _FILE_ATTRIBUTE_NORMAL, None)
        if handle == _INVALID_HANDLE: raise SupervisorDisposalRequired("Windows log create failed")
        descriptor = None
        try:
            descriptor = msvcrt.open_osfhandle(int(handle), os.O_WRONLY | getattr(os, "O_BINARY", 0)); handle = None
            view = memoryview(content)
            while view:
                count = os.write(descriptor, view)
                if count <= 0: raise OSError("short Windows log write")
                view = view[count:]
            raw_handle = msvcrt.get_osfhandle(descriptor)
            if not _flush_file(raw_handle): raise OSError("Windows log flush failed")
            name_bytes = str(final_path).encode("utf-16-le")
            class RenameHeader(ctypes.Structure):
                _fields_ = [
                    ("ReplaceIfExists", wintypes.BOOLEAN),
                    ("RootDirectory", wintypes.HANDLE),
                    ("FileNameLength", wintypes.DWORD),
                    ("FileName", wintypes.WCHAR * 1),
                ]
            size = ctypes.sizeof(RenameHeader) + len(name_bytes)
            buffer = ctypes.create_string_buffer(size)
            header = RenameHeader.from_buffer(buffer)
            header.ReplaceIfExists = False
            header.RootDirectory = None
            header.FileNameLength = len(name_bytes)
            ctypes.memmove(ctypes.addressof(buffer) + RenameHeader.FileName.offset, name_bytes, len(name_bytes))
            if not _set_file_info(raw_handle, 3, buffer, size):
                code = ctypes.get_last_error()
                raise OSError(code, "Windows handle-bound log rename failed")
            needed = _get_final_path(raw_handle, None, 0, 0)
            if needed == 0: raise OSError("Windows finalized log identity is unavailable")
            final_buffer = ctypes.create_unicode_buffer(needed)
            if _get_final_path(raw_handle, final_buffer, needed, 0) == 0:
                raise OSError("Windows finalized log identity is unavailable")
            if self._normalize(final_buffer.value) != self._normalize(str(final_path)):
                raise OSError("Windows finalized log identity changed")
            if not _flush_file(raw_handle): raise OSError("Windows finalized log flush failed")
            os.close(descriptor); descriptor = None
        except BaseException as error:
            if descriptor is not None:
                try: os.close(descriptor)
                except OSError: pass
            if handle is not None: _close_handle(handle)
            try: temp_path.unlink()
            except OSError: pass
            classify_log_proof_failure(error)

    def finalize(self, command_id: str, stdout: bytes, stderr: bytes) -> None:
        self._write_final(f"{command_id}.stdout.log", stdout); self._write_final(f"{command_id}.stderr.log", stderr)

    def prove_absent(self, names: tuple[str, ...]) -> None:
        try:
            if any(_path_entry_exists(self.directory / name) for name in names):
                raise OSError("Windows log exists unexpectedly")
        except BaseException:
            raise SupervisorDisposalRequired("Windows log absence is unverifiable") from None

    def close(self) -> None:
        failure = False
        for handle in reversed(self._handles):
            if not _close_handle(handle): failure = True
        self._handles.clear()
        if failure: raise SupervisorDisposalRequired("Windows directory handle close failed")


def _drain_windows_pipe(descriptor: int, capture: StreamCapture, *, byte_budget: int = 262_144) -> None:
    if capture.eof:
        return
    handle = msvcrt.get_osfhandle(descriptor)
    remaining_budget = byte_budget
    while remaining_budget > 0:
        available = wintypes.DWORD()
        if not _peek_named_pipe(handle, None, 0, None, ctypes.byref(available), None):
            if ctypes.get_last_error() in {109, 232}:  # ERROR_BROKEN_PIPE / ERROR_NO_DATA
                capture.finish()
                return
            raise SupervisorDisposalRequired("Windows stream state is unavailable")
        if available.value == 0:
            return
        try:
            content = os.read(descriptor, min(65_536, available.value, remaining_budget))
        except OSError:
            raise SupervisorDisposalRequired("Windows stream read failed") from None
        if not content:
            capture.finish()
            return
        capture.feed(content)
        remaining_budget -= len(content)


class WindowsInputPump:
    def __init__(self, descriptor: int, content: bytes) -> None:
        self.descriptor = descriptor
        self._content = content
        self._offset = 0
        os.set_blocking(descriptor, False)

    def pump(self, *, byte_budget: int = 262_144) -> None:
        if self.descriptor is None:
            return
        remaining_budget = byte_budget
        while self._offset < len(self._content) and remaining_budget > 0:
            chunk = self._content[self._offset : self._offset + min(65_536, remaining_budget)]
            try:
                count = os.write(self.descriptor, chunk)
            except BlockingIOError:
                return
            except BrokenPipeError:
                self.close()
                return
            except OSError as error:
                if error.errno == errno.EPIPE or getattr(error, "winerror", None) in {109, 232}:
                    self.close()
                    return
                raise SupervisorDisposalRequired("Windows input pipe write failed") from None
            if count <= 0:
                raise SupervisorDisposalRequired("Windows input pipe write was short")
            self._offset += count
            remaining_budget -= count
        if self._offset == len(self._content):
            self.close()

    def close(self) -> None:
        if self.descriptor is None:
            return
        descriptor = self.descriptor
        self.descriptor = None
        try:
            os.close(descriptor)
        except OSError:
            raise SupervisorDisposalRequired("Windows input pipe close failed") from None


def _wait_windows_with_streams(process: int, deadline: float, streams: tuple[tuple[int, StreamCapture], ...], input_pump: WindowsInputPump) -> bool:
    while True:
        input_pump.pump()
        for descriptor, capture in streams:
            _drain_windows_pipe(descriptor, capture)
        result = _wait_handle(process, 0)
        if result == _WAIT_OBJECT_0:
            for descriptor, capture in streams:
                _drain_windows_pipe(descriptor, capture)
            return True
        if result != _WAIT_TIMEOUT:
            raise SupervisorDisposalRequired("Windows process wait failed")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            result = _wait_handle(process, 0)
            if result == _WAIT_OBJECT_0:
                for descriptor, capture in streams:
                    _drain_windows_pipe(descriptor, capture)
                return True
            if result == _WAIT_TIMEOUT:
                return False
            raise SupervisorDisposalRequired("Windows process wait failed")
        result = _wait_handle(process, max(1, min(10, math.ceil(remaining * 1000))))
        if result == _WAIT_OBJECT_0:
            for descriptor, capture in streams:
                _drain_windows_pipe(descriptor, capture)
            return True
        if result != _WAIT_TIMEOUT:
            raise SupervisorDisposalRequired("Windows process wait failed")


def _drain_windows_to_eof(streams: tuple[tuple[int, StreamCapture], ...], deadline: float) -> None:
    while not all(capture.eof for _, capture in streams):
        require_before_deadline(deadline)
        for descriptor, capture in streams:
            _drain_windows_pipe(descriptor, capture)
        if not all(capture.eof for _, capture in streams):
            time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))


def _windows_active_processes(job: int) -> int:
    information = _BasicAccountingInformation()
    if not _query_job(job, _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION, ctypes.byref(information), ctypes.sizeof(information), None):
        raise SupervisorDisposalRequired("Windows job state is unavailable")
    return int(information.ActiveProcesses)


def _windows_close_job(job: int) -> bool:
    return bool(_close_handle(job))


def _execute_windows(request: dict, started: float) -> dict:
    stage = "log-store"
    execution_deadline = started + request["execution_timeout_seconds"]
    run_root = Path(request["run_root"]); log_directory = Path(request["log_directory"])
    canaries = tuple(base64.b64decode(item) for item in request["secret_canaries_b64"])
    stdout = StreamCapture(limit=request["stdout_limit"], canaries=canaries)
    stderr = StreamCapture(limit=request["stderr_limit"], canaries=canaries)
    store = WindowsLogStore(run_root, log_directory)
    descriptors: list[int] = []; process = thread = job = None; input_pump = None
    released = False; timed_out = False; exit_code = None; cleanup_deadline = None
    try:
        store.prepare(request["command_id"])
        store.retain_cwd(Path(request["cwd"]))
        stage = "pipe-files"
        input_read_fd, input_write_fd = os.pipe(); descriptors.extend((input_read_fd, input_write_fd))
        input_pump = WindowsInputPump(input_write_fd, b"" if request["input_b64"] is None else base64.b64decode(request["input_b64"]))
        descriptors.remove(input_write_fd)
        stdout_fd, stdout_write_fd = os.pipe(); descriptors.extend((stdout_fd, stdout_write_fd))
        stderr_fd, stderr_write_fd = os.pipe(); descriptors.extend((stderr_fd, stderr_write_fd))
        for descriptor in (input_read_fd, stdout_write_fd, stderr_write_fd): os.set_inheritable(descriptor, True)
        stage = "job-create"
        job = _create_job(None, None)
        if not job:
            job = None
            raise SupervisorOrdinaryFailure("Windows Job Object is unavailable")
        limits = _ExtendedLimitInformation(); limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not _set_job(job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise SupervisorOrdinaryFailure("Windows Job Object contract is unavailable")
        if _windows_active_processes(job) != 0:
            raise SupervisorOrdinaryFailure("new Windows Job Object is not empty")
        stage = "startup-info"
        startup = subprocess.STARTUPINFO(); startup.dwFlags |= subprocess.STARTF_USESTDHANDLES | subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0; startup.hStdInput = msvcrt.get_osfhandle(input_read_fd)
        startup.hStdOutput = msvcrt.get_osfhandle(stdout_write_fd); startup.hStdError = msvcrt.get_osfhandle(stderr_write_fd)
        startup.lpAttributeList = {"handle_list": [startup.hStdInput, startup.hStdOutput, startup.hStdError]}
        command_line = subprocess.list2cmdline(request["argv"])
        stage = "create-suspended"
        process, thread, _, _ = _winapi.CreateProcess(
            request["argv"][0], command_line, None, None, True,
            0x00000004 | getattr(subprocess, "CREATE_NO_WINDOW", 0),
            dict(request["environment"]), request["cwd"], startup,
        )
        for descriptor in (input_read_fd, stdout_write_fd, stderr_write_fd): os.set_inheritable(descriptor, False)
        if not _assign_job(job, process): raise SupervisorOrdinaryFailure("Windows target assignment failed")
        if _windows_active_processes(job) != 1:
            raise SupervisorDisposalRequired("Windows suspended target membership is not exact")
        gate = ReleaseGate(); gate.mark_contained()
        def release_target() -> None:
            def resume() -> None:
                if _resume_thread(thread) == 0xFFFFFFFF:
                    raise SupervisorDisposalRequired("Windows target release failed")
            _release_before_deadline(execution_deadline, resume)
        try: gate.release_with(release_target)
        finally: released = gate.released
        if not _close_handle(thread): raise SupervisorDisposalRequired("Windows thread handle close failed")
        thread = None
        for descriptor in (input_read_fd, stdout_write_fd, stderr_write_fd):
            os.close(descriptor); descriptors.remove(descriptor)
        streams = ((stdout_fd, stdout), (stderr_fd, stderr))
        timed_out = not _wait_windows_with_streams(process, execution_deadline, streams, input_pump)
        if not timed_out:
            value = wintypes.DWORD()
            if not _get_exit_code(process, ctypes.byref(value)) or value.value == _STILL_ACTIVE:
                raise SupervisorDisposalRequired("Windows exit status is unavailable")
            exit_code = ctypes.c_int32(value.value).value
        cleanup_deadline = time.monotonic() + request["cleanup_timeout_seconds"]
        _latch_cleanup_deadline(cleanup_deadline)
        boundary = WindowsJobBoundary(
            terminate=lambda: bool(_terminate_job(job, 137)), active_count=lambda: _windows_active_processes(job),
            close=lambda: _windows_close_job(job), monotonic=time.monotonic, sleep=time.sleep,
        )
        boundary.terminate_empty_close(cleanup_deadline); job = None
        require_before_deadline(cleanup_deadline)
        input_pump.close()
        if not wait_windows_process_until(process, cleanup_deadline, wait=_wait_handle):
            raise SupervisorDisposalRequired("Windows target was not reaped")
        if not _close_handle(process): raise SupervisorDisposalRequired("Windows process handle close failed")
        process = None
        _drain_windows_to_eof(streams, cleanup_deadline)
        for descriptor in (stdout_fd, stderr_fd):
            os.close(descriptor); descriptors.remove(descriptor)
        require_before_deadline(cleanup_deadline)
        if stdout.canary_seen or stderr.canary_seen:
            store.prove_absent((f"{request['command_id']}.stdout.log", f"{request['command_id']}.stderr.log"))
            require_before_deadline(cleanup_deadline)
            return _response("CANARY_DETECTED", exit_code, started, stdout, stderr)
        store.finalize(request["command_id"], stdout.retained, stderr.retained)
        require_before_deadline(cleanup_deadline)
        status = "TIMED_OUT" if timed_out else ("PASS" if exit_code == 0 else "FAILED")
        return _response(status, exit_code, started, stdout, stderr)
    except SupervisorDisposalRequired:
        raise
    except BaseException as error:
        if released:
            raise SupervisorDisposalRequired("Windows operation proof failed") from None
        if cleanup_deadline is None:
            cleanup_deadline = time.monotonic() + request["cleanup_timeout_seconds"]
            _latch_cleanup_deadline(cleanup_deadline)
        if process is not None:
            if not _terminate_process(process, 137) or not wait_windows_process_until(process, cleanup_deadline, wait=_wait_handle):
                raise SupervisorDisposalRequired("suspended Windows target cleanup failed") from None
        code = getattr(error, "winerror", None)
        raise SupervisorOrdinaryFailure(f"Windows target did not start at {stage}:{type(error).__name__}:{code}") from None
    finally:
        finalization_failed = False
        if cleanup_deadline is None:
            cleanup_deadline = time.monotonic() + request["cleanup_timeout_seconds"]
            _latch_cleanup_deadline(cleanup_deadline)
        for descriptor in descriptors:
            try: os.close(descriptor)
            except OSError: finalization_failed = True
        if input_pump is not None:
            try: input_pump.close()
            except SupervisorDisposalRequired: finalization_failed = True
        if thread is not None and not _close_handle(thread): finalization_failed = True
        if process is not None and not _close_handle(process): finalization_failed = True
        if job is not None and not _close_handle(job): finalization_failed = True
        try: store.close()
        except SupervisorDisposalRequired: finalization_failed = True
        try: require_before_deadline(cleanup_deadline)
        except SupervisorDisposalRequired: finalization_failed = True
        if finalization_failed:
            raise SupervisorDisposalRequired("Windows finalization proof failed")


def _read_nonblocking_endpoint(descriptor: int) -> bytes:
    os.set_blocking(descriptor, False)
    content = bytearray()
    while True:
        try:
            chunk = os.read(descriptor, min(65_536, _MAX_REQUEST_BYTES + 1 - len(content)))
        except BlockingIOError:
            time.sleep(0.005)
            continue
        if not chunk:
            return bytes(content)
        content.extend(chunk)
        if len(content) > _MAX_REQUEST_BYTES:
            return bytes(content)


def _write_nonblocking_endpoint(descriptor: int, content: bytes) -> None:
    os.set_blocking(descriptor, False)
    offset = 0
    while offset < len(content):
        try:
            count = os.write(descriptor, content[offset : offset + 65_536])
        except BlockingIOError:
            time.sleep(0.005)
            continue
        if count <= 0:
            raise OSError("short supervisor response write")
        offset += count


def _main() -> int:
    global _ACTIVE_CLEANUP_DEADLINE
    _ACTIVE_CLEANUP_DEADLINE = None
    started = time.monotonic()
    empty_stdout = _empty_capture(0, ())
    empty_stderr = _empty_capture(0, ())
    if len(sys.argv) != 5 or sys.argv[1] != "--request-endpoint" or sys.argv[3] != "--response-endpoint":
        return 64
    try:
        request_endpoint = int(sys.argv[2]); response_endpoint = int(sys.argv[4])
        if request_endpoint < 0 or response_endpoint < 0 or request_endpoint == response_endpoint:
            return 64
    except ValueError:
        return 64
    try:
        if os.name == "nt":
            import msvcrt
            request_descriptor = msvcrt.open_osfhandle(request_endpoint, os.O_RDONLY | getattr(os, "O_BINARY", 0))
            response_descriptor = msvcrt.open_osfhandle(response_endpoint, os.O_WRONLY | getattr(os, "O_BINARY", 0))
        else:
            request_descriptor = request_endpoint; response_descriptor = response_endpoint
        os.set_inheritable(response_descriptor, False)
        raw = _read_nonblocking_endpoint(request_descriptor)
        os.close(request_descriptor)
        if len(raw) > _MAX_REQUEST_BYTES or raw.count(b"\n") != 1 or not raw.endswith(b"\n"):
            raise SupervisorOrdinaryFailure("fixed request protocol is invalid")
        try:
            request = validate_request(json.loads(raw.decode("ascii"), object_pairs_hook=_unique_protocol_object))
        except (UnicodeError, ValueError):
            raise SupervisorOrdinaryFailure("fixed request protocol is invalid") from None
        if os.name == "nt":
            result = _execute_windows(request, started)
        elif sys.platform == "linux":
            result = _execute_linux(request, started, response_descriptor)
        else:
            raise SupervisorOrdinaryFailure("unsupported worker platform")
    except SupervisorOrdinaryFailure:
        result = _response("FAILED", None, started, empty_stdout, empty_stderr)
    except SupervisorDisposalRequired:
        result = _response("WORKER_DISPOSAL_REQUIRED", None, started, empty_stdout, empty_stderr, proof=False)
    except BaseException:
        result = _response("WORKER_DISPOSAL_REQUIRED", None, started, empty_stdout, empty_stderr, proof=False)
    try:
        encoded = (json.dumps(result, separators=(",", ":")) + "\n").encode("ascii")
        _write_nonblocking_endpoint(response_descriptor, encoded)
        os.close(response_descriptor)
        if _ACTIVE_CLEANUP_DEADLINE is not None:
            require_before_deadline(_ACTIVE_CLEANUP_DEADLINE)
    except BaseException:
        return 70
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
