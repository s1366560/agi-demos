"""Unit tests for workspace attempt recovery startup helpers."""

from __future__ import annotations

from src.infrastructure.adapters.primary.web.startup.attempt_recovery import (
    _attempt_cleanup_count,
    _attempt_runtime_cleanup_command,
)


def test_attempt_runtime_cleanup_command_targets_attempt_worktree_cwd() -> None:
    command = _attempt_runtime_cleanup_command("att-123")

    assert "/.memstack/worktrees/att-123" in command
    assert "/proc/[0-9]*/status" in command
    assert 'readlink "$proc_dir/cwd"' in command
    assert "NSpgid" in command
    assert 'kill -TERM "-$pgid"' in command
    assert 'kill -KILL "-$pgid"' in command
    assert "[workspace_attempt_cleanup]" in command


def test_attempt_cleanup_count_reads_tool_content() -> None:
    raw = {
        "content": [
            {
                "type": "text",
                "text": "[workspace_attempt_cleanup] attempt_id=att matched=3 groups=2 remaining=0",
            }
        ]
    }

    assert _attempt_cleanup_count(raw) == 3
