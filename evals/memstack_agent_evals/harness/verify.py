"""Verification command execution."""

from __future__ import annotations

from pathlib import Path

from memstack_agent_evals.subprocess_utils import CommandResult, run_command


def run_verification(
    *,
    workspace: Path,
    command: str,
    timeout_sec: int = 600,
) -> CommandResult:
    """Run the case verification command in a shell."""
    return run_command(["bash", "-lc", command], cwd=workspace, timeout_sec=timeout_sec)
