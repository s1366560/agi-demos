"""Workspace runtime forwarding tests for the ReAct stream mixin."""

from src.infrastructure.agent.core.react_agent_stream_mixin import (
    _workspace_runtime_forwarded_fields,
    _workspace_runtime_limit_overrides,
)
from src.infrastructure.agent.workspace.runtime_role_contract import (
    WORKSPACE_ROLE_CONTRACT,
    WORKSPACE_SESSION_ROLE_KEY,
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


def test_workspace_runtime_limit_overrides_accepts_positive_ints_only() -> None:
    assert _workspace_runtime_limit_overrides(
        {
            WORKSPACE_SESSION_ROLE_KEY: WORKSPACE_ROLE_CONTRACT,
            "runtime_limits": {
                "max_steps": 8,
                "max_tokens": 8192,
                "ignored": 1,
            },
        }
    ) == {"max_steps": 8, "max_tokens": 8192}

    assert (
        _workspace_runtime_limit_overrides(
            {
                WORKSPACE_SESSION_ROLE_KEY: WORKSPACE_ROLE_CONTRACT,
                "runtime_limits": {
                    "max_steps": 0,
                    "max_tokens": True,
                },
            }
        )
        == {}
    )

    assert (
        _workspace_runtime_limit_overrides(
            {
                "runtime_limits": {
                    "max_steps": 8,
                    "max_tokens": 8192,
                }
            }
        )
        == {}
    )
