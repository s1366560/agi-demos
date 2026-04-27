"""Tests for the built-in workspace runtime plugin."""

import pytest

from src.infrastructure.agent.plugins.registry import AgentPluginRegistry
from src.infrastructure.agent.workspace.runtime_plugin import register_builtin_workspace_plugin


@pytest.mark.unit
async def test_workspace_runtime_plugin_adds_guidance_for_workspace_context() -> None:
    registry = AgentPluginRegistry()
    register_builtin_workspace_plugin(registry)

    result = await registry.apply_hook(
        "before_response",
        payload={
            "runtime_context": {
                "task_authority": "workspace",
                "workspace_id": "ws-1",
                "workspace_session_role": "worker",
            },
            "response_instructions": [],
        },
    )

    instructions = result.payload["response_instructions"]
    assert len(instructions) == 1
    assert "workspace_report_complete" in instructions[0]
    assert "<minimax:tool_call>" in instructions[0]


@pytest.mark.unit
async def test_workspace_runtime_plugin_ignores_non_workspace_context() -> None:
    registry = AgentPluginRegistry()
    register_builtin_workspace_plugin(registry)

    result = await registry.apply_hook(
        "before_response",
        payload={
            "runtime_context": {"task_authority": "chat"},
            "response_instructions": [],
        },
    )

    assert result.payload["response_instructions"] == []
