"""Small subprocess helpers for the eval harness."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path


class CommandResult:
    """Completed shell command with elapsed wall time."""

    def __init__(
        self,
        *,
        args: list[str],
        cwd: Path,
        returncode: int,
        stdout: str,
        stderr: str,
        duration_sec: float,
    ) -> None:
        self.args = args
        self.cwd = cwd
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.duration_sec = duration_sec


def run_command(
    args: list[str],
    *,
    cwd: Path,
    timeout_sec: int = 600,
    env: dict[str, str] | None = None,
) -> CommandResult:
    """Run a command and capture text output."""
    start = time.monotonic()
    completed = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_sec,
        check=False,
    )
    return CommandResult(
        args=args,
        cwd=cwd,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_sec=time.monotonic() - start,
    )
