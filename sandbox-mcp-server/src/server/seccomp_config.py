"""Seccomp configuration for sandbox system call filtering.

Provides seccomp profiles to restrict system calls available to sandbox
processes, enhancing security by limiting attack surface.
"""

import json
import logging
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class SeccompAction(str, Enum):
    """Seccomp action values."""
    ALLOW = "SCMP_ACT_ALLOW"
    ERRNO = "SCMP_ACT_ERRNO"
    KILL = "SCMP_ACT_KILL"
    TRAP = "SCMP_ACT_TRAP"
    TRACE = "SCMP_ACT_TRACE"


@dataclass
class SyscallRule:
    """A single seccomp system call rule.

    Attributes:
        names: List of system call names
        action: Action to take when syscall is invoked
    """
    names: List[str]
    action: SeccompAction

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "names": self.names,
            "action": self.action.value,
            "args": [],
            "comment": f"{self.action.value} for syscalls",
            "includes": {},
            "excludes": {},
        }


class SeccompProfile:
    """Seccomp profile manager for sandbox security.

    Loads and manages seccomp profiles that restrict available system calls.

    Usage:
        profile = SeccompProfile()
        profile_dict = profile.get_profile("strict")
        # Use with Docker: docker run --security-opt seccomp=profile.json
    """

    # Default profile directory
    DEFAULT_PROFILE_DIR = Path("/opt/seccomp")

    def __init__(self, profile_dir: Optional[Path] = None):
        """Initialize the seccomp profile manager.

        Args:
            profile_dir: Directory containing profile JSON files
        """
        self._profile_dir = profile_dir or self.DEFAULT_PROFILE_DIR
        self._profiles: Dict[str, dict] = {}

    def get_profile(self, name: str = "default") -> dict:
        """Get a seccomp profile by name.

        Args:
            name: Profile name (default, strict, minimal)

        Returns:
            Seccomp profile dictionary

        Raises:
            FileNotFoundError: If profile file doesn't exist
            ValueError: If profile JSON is invalid
        """
        if name in self._profiles:
            return self._profiles[name]

        # Try to load from file
        profile_path = self._profile_dir / f"{name}.json"
        if profile_path.exists():
            with open(profile_path) as f:
                profile = json.load(f)
            self._profiles[name] = profile
            return profile

        # Use built-in default profile
        if name == "default":
            profile = self._get_default_profile()
            self._profiles[name] = profile
            return profile

        if name == "strict":
            profile = self._get_strict_profile()
            self._profiles[name] = profile
            return profile

        if name == "minimal":
            profile = self._get_minimal_profile()
            self._profiles[name] = profile
            return profile

        raise FileNotFoundError(f"Seccomp profile '{name}' not found")

    def save_profile(self, name: str, profile: dict, path: Optional[Path] = None) -> None:
        """Save a profile to disk.

        Args:
            name: Profile name
            profile: Profile dictionary
            path: Custom save path (defaults to profile_dir)
        """
        save_path = path or (self._profile_dir / f"{name}.json")
        save_path.parent.mkdir(parents=True, exist_ok=True)

        with open(save_path, "w") as f:
            json.dump(profile, f, indent=2)

        self._profiles[name] = profile

    def _get_default_profile(self) -> dict:
        """Get the default seccomp profile.

        Blocks dangerous system calls while allowing normal operations.
        """
        blocked_syscalls = [
            # System administration
            "kexec_load", "kexec_file_load", "init_module", "finit_module",
            "delete_module", "acct", "swapon", "swapoff", "reboot",
            # Time manipulation
            "settimeofday", "stime", "clock_settime", "adjtimex",
            # Process tracing
            "ptrace", "process_vm_readv", "process_vm_writev",
        ]

        return {
            "defaultAction": "SCMP_ACT_ERRNO",
            "architectures": ["SCMP_ARCH_X86_64", "SCMP_ARCH_X86", "SCMP_ARCH_X32"],
            "syscalls": [
                SyscallRule(
                    names=blocked_syscalls,
                    action=SeccompAction.ERRNO,
                ).to_dict(),
            ],
        }

    def _get_strict_profile(self) -> dict:
        """Get a strict seccomp profile with more restrictions.

        Blocks additional system calls for higher security.
        """
        blocked_syscalls = [
            # System administration
            "kexec_load", "kexec_file_load", "init_module", "finit_module",
            "delete_module", "acct", "swapon", "swapoff", "reboot",
            # Time manipulation
            "settimeofday", "stime", "clock_settime", "adjtimex",
            # Process tracing
            "ptrace", "process_vm_readv", "process_vm_writev",
            # Hardware access
            "iopl", "ioperm",
            # Raw I/O
            "ioprio_set", "ioprio_get",
        ]

        return {
            "defaultAction": "SCMP_ACT_ERRNO",
            "architectures": ["SCMP_ARCH_X86_64", "SCMP_ARCH_X86", "SCMP_ARCH_X32"],
            "syscalls": [
                SyscallRule(
                    names=blocked_syscalls,
                    action=SeccompAction.ERRNO,
                ).to_dict(),
            ],
        }

    def _get_minimal_profile(self) -> dict:
        """Get a minimal seccomp profile (most restrictive).

        Only allows essential system calls.
        """
        allowed_syscalls = [
            # Basic I/O
            "read", "write", "open", "close", "stat", "fstat", "lstat",
            "poll", "lseek", "mmap", "mprotect", "munmap", "brk",
            # Signals
            "rt_sigaction", "rt_sigprocmask", "rt_sigreturn",
            # Process
            "clone", "fork", "vfork", "execve", "exit", "exit_group", "wait4",
            "getpid", "getppid",
            # File operations
            "access", "pipe", "dup", "dup2", "fcntl", "flock",
            # Time
            "gettimeofday", "time", "nanosleep",
            # Memory
            "msync", "madvise", "mremap",
            # Scheduling
            "sched_yield", "sched_getparam", "sched_setparam",
            # Socket (basic)
            "socket", "connect", "send", "recv", "shutdown",
            # Misc
            "getuid", "getgid", "geteuid", "getegid", "uname",
        ]

        return {
            "defaultAction": "SCMP_ACT_ERRNO",
            "architectures": ["SCMP_ARCH_X86_64", "SCMP_ARCH_X86", "SCMP_ARCH_X32"],
            "syscalls": [
                SyscallRule(
                    names=allowed_syscalls,
                    action=SeccompAction.ALLOW,
                ).to_dict(),
            ],
        }


def get_seccomp_profile_path(profile_name: str = "default") -> Optional[str]:
    """Get the path to a seccomp profile file.

    Args:
        profile_name: Name of the profile

    Returns:
        Path to profile file or None if not found
    """
    # Check common locations
    locations = [
        Path("/opt/seccomp") / f"{profile_name}.json",
        Path("/etc/seccomp") / f"{profile_name}.json",
        Path("docker") / "seccomp-profile.json",
    ]

    for location in locations:
        if location.exists():
            return str(location)

    return None


def load_seccomp_profile(profile_name: str = "default") -> dict:
    """Load a seccomp profile by name.

    Args:
        profile_name: Name of the profile to load

    Returns:
        Seccomp profile dictionary

    Raises:
        FileNotFoundError: If profile not found
    """
    manager = SeccompProfile()
    return manager.get_profile(profile_name)
