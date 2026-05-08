"""Workspace runtime forwarding tests for the ReAct stream mixin."""

from src.infrastructure.agent.core.react_agent_stream_mixin import (
    _workspace_runtime_forwarded_fields,
)


def test_workspace_runtime_forwarded_fields_preserves_worktree_override() -> None:
    payload = {
        "additional_instructions": "worktree_path=/workspace/.memstack/worktrees/att-1",
        "workspace_root_override": {"source": "additional_instructions"},
        "code_context": {"sandbox_code_root": "/workspace/my-evo"},
    }

    forwarded = _workspace_runtime_forwarded_fields(payload)

    assert forwarded == {
        "additional_instructions": "worktree_path=/workspace/.memstack/worktrees/att-1",
        "workspace_root_override": {"source": "additional_instructions"},
    }


def test_workspace_runtime_forwarded_fields_ignores_empty_or_invalid_values() -> None:
    forwarded = _workspace_runtime_forwarded_fields(
        {
            "additional_instructions": " ",
            "workspace_root_override": True,
        }
    )

    assert forwarded == {}
