"""Workspace runtime forwarding tests for the ReAct stream mixin."""

from src.infrastructure.agent.core.react_agent_stream_mixin import (
    _workspace_runtime_forwarded_fields,
)


def test_workspace_runtime_forwarded_fields_preserves_worktree_override() -> None:
    payload = {
        "additional_instructions": "worktree_path=/workspace/.memstack/worktrees/att-1",
        "workspace_root_override": {"source": "additional_instructions"},
        "workspace_verification_integrity": {
            "iteration_phase": "test",
            "protected_script_changes": True,
        },
        "attempt_worktree": {
            "active_root": "/workspace/.memstack/worktrees/att-1",
            "setup_status": "prepared",
        },
        "active_execution_root": "/workspace/.memstack/worktrees/att-1",
        "worktree_setup": {"status": "prepared"},
        "code_context": {"sandbox_code_root": "/workspace/my-evo"},
    }

    forwarded = _workspace_runtime_forwarded_fields(payload)

    assert forwarded == {
        "additional_instructions": "worktree_path=/workspace/.memstack/worktrees/att-1",
        "workspace_root_override": {"source": "additional_instructions"},
        "attempt_worktree": {
            "active_root": "/workspace/.memstack/worktrees/att-1",
            "setup_status": "prepared",
        },
        "active_execution_root": "/workspace/.memstack/worktrees/att-1",
        "worktree_setup": {"status": "prepared"},
        "workspace_verification_integrity": {
            "iteration_phase": "test",
            "protected_script_changes": True,
        },
    }


def test_workspace_runtime_forwarded_fields_ignores_empty_or_invalid_values() -> None:
    forwarded = _workspace_runtime_forwarded_fields(
        {
            "additional_instructions": " ",
            "workspace_root_override": True,
            "attempt_worktree": False,
            "active_execution_root": " ",
            "worktree_setup": False,
            "workspace_verification_integrity": False,
        }
    )

    assert forwarded == {}
