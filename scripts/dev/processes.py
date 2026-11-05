"""Kernel-backed identity checks for local development service processes."""

from __future__ import annotations

import ctypes
import errno
import os
import signal
import struct
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ENV = "MEMSTACK_DEV_REPO"
ROLE_ENV = "MEMSTACK_DEV_ROLE"
LAUNCH_ENV = "MEMSTACK_DEV_LAUNCH_ID"
PROFILE_ENV = "AGISTACK_DESKTOP_QA_PROFILE_DIR"


class ProbeError(RuntimeError):
    """The kernel could not establish process ownership safely."""


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    birth: str
    group: int
    repo: str
    role: str
    nonce: str
    profile: str


class _BsdInfo(ctypes.Structure):
    # Darwin sys/proc_info.h: struct proc_bsdinfo (PROC_PIDTBSDINFO).
    _fields_ = (
        ("ids", ctypes.c_uint32 * 12),
        ("comm", ctypes.c_char * 16),
        ("name", ctypes.c_char * 32),
        ("numbers", ctypes.c_uint32 * 6),
        ("start_sec", ctypes.c_uint64),
        ("start_usec", ctypes.c_uint64),
    )


class ProcessProbe:
    deadline: float = float("inf")

    def _command(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ProbeError("probe_timeout")
        try:
            return subprocess.run(
                args,
                capture_output=True,
                text=True,
                check=False,
                timeout=min(1.0, remaining),
                env={"PATH": os.environ.get("PATH", ""), "LC_ALL": "C"},
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ProbeError("process_probe_unavailable") from error

    @staticmethod
    def _environment(raw: bytes) -> dict[str, str]:
        return dict(os.fsdecode(item).split("=", 1) for item in raw.split(b"\0") if b"=" in item)

    def inspect(self, pid: int) -> ProcessIdentity | None:
        try:
            if sys.platform == "darwin":
                birth, group, env = self._darwin(pid)
            elif sys.platform.startswith("linux"):
                root = Path("/proc") / str(pid)
                fields = (root / "stat").read_text().rsplit(")", 1)[1].split()
                if fields[0] == "Z":
                    return None
                birth, group = fields[19], int(fields[2])
                env = self._environment((root / "environ").read_bytes())
            else:
                raise ProbeError("unsupported_process_platform")
        except (FileNotFoundError, ProcessLookupError):
            return None
        except (OSError, ValueError, IndexError) as error:
            raise ProbeError("process_identity_unavailable") from error
        return ProcessIdentity(
            pid,
            birth,
            group,
            env.get(REPO_ENV, ""),
            env.get(ROLE_ENV, ""),
            env.get(LAUNCH_ENV, ""),
            env.get(PROFILE_ENV, ""),
        )

    @staticmethod
    def _bsd(pid: int) -> _BsdInfo:
        info = _BsdInfo()
        library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        count = library.proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info))
        if count == 0 and ctypes.get_errno() in (0, errno.ESRCH):
            raise ProcessLookupError(pid)
        if count != ctypes.sizeof(info) or info.ids[3] != pid:
            raise ProbeError("process_birth_unavailable")
        if info.ids[1] == 5:  # SZOMB from Darwin sys/proc.h
            raise ProcessLookupError(pid)
        return info

    def _darwin(self, pid: int) -> tuple[str, int, dict[str, str]]:
        before = self._bsd(pid)
        libc = ctypes.CDLL(None, use_errno=True)
        mib = (ctypes.c_int * 3)(1, 49, pid)  # CTL_KERN, KERN_PROCARGS2
        size = ctypes.c_size_t()
        if libc.sysctl(mib, 3, None, ctypes.byref(size), None, 0):
            _ = self._bsd(pid)  # Distinguish a process that exited during this observation.
            raise ProbeError("process_environment_unavailable")
        buffer = ctypes.create_string_buffer(size.value)
        if libc.sysctl(mib, 3, buffer, ctypes.byref(size), None, 0):
            _ = self._bsd(pid)
            raise ProbeError("process_environment_unavailable")
        raw = buffer.raw[: size.value]
        argc = struct.unpack_from("i", raw)[0]
        offset = raw.index(b"\0", 4) + 1
        while offset < len(raw) and raw[offset] == 0:
            offset += 1
        for _ in range(argc):
            offset = raw.index(b"\0", offset) + 1
        after = self._bsd(pid)
        if (before.start_sec, before.start_usec) != (after.start_sec, after.start_usec):
            raise ProbeError("process_identity_changed_during_observation")
        return (
            f"{after.start_sec}:{after.start_usec}",
            after.numbers[1],
            self._environment(raw[offset:]),
        )

    def group(self, group: int) -> list[ProcessIdentity]:
        result = self._command(["ps", "-axo", "pid=,pgid="])
        if result.returncode:
            raise ProbeError("process_group_unavailable")
        identities: list[ProcessIdentity] = []
        try:
            for line in result.stdout.splitlines():
                fields = line.split()
                if len(fields) == 2 and int(fields[1]) == group:
                    identity = self.inspect(int(fields[0]))
                    if identity is not None:
                        identities.append(identity)
        except ValueError as error:
            raise ProbeError("process_group_unavailable") from error
        return identities

    def listeners(self, port: int) -> list[int]:
        result = self._command(["lsof", "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"])
        if result.returncode not in (0, 1) or result.stderr.strip():
            raise ProbeError("listener_identity_unavailable")
        try:
            return sorted({int(line) for line in result.stdout.splitlines()})
        except ValueError as error:
            raise ProbeError("listener_identity_unavailable") from error

    def signal(self, identity: ProcessIdentity, number: signal.Signals) -> None:
        descriptor = None
        try:
            sender = getattr(signal, "pidfd_send_signal", None)
            if hasattr(os, "pidfd_open") and sender is not None:
                descriptor = os.pidfd_open(identity.pid)
            if self.inspect(identity.pid) != identity:
                return
            if descriptor is not None and sender is not None:
                sender(descriptor, number)
            else:
                os.kill(identity.pid, number)
        except ProcessLookupError:
            pass
        finally:
            if descriptor is not None:
                os.close(descriptor)
