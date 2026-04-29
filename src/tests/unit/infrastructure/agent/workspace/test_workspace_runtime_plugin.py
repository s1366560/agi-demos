"""Tests for the built-in workspace runtime plugin."""

import pytest

from src.infrastructure.agent.plugins.registry import AgentPluginRegistry, PluginSkillBuildContext
from src.infrastructure.agent.workspace.runtime_plugin import (
    WORKSPACE_TASK_HARNESS_SKILL_NAME,
    register_builtin_workspace_plugin,
)


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
async def test_workspace_runtime_plugin_tells_workers_not_to_extend_global_task_tree() -> None:
    registry = AgentPluginRegistry()
    register_builtin_workspace_plugin(registry)

    result = await registry.apply_hook(
        "on_session_start",
        payload={
            "runtime_context": {
                "task_authority": "workspace",
                "workspace_id": "ws-1",
                "workspace_session_role": "worker",
            },
            "session_instructions": [],
        },
    )

    instructions = result.payload["session_instructions"]
    assert any("todowrite add/replace" in item for item in instructions)
    assert any("workspace_report_progress/complete/blocked" in item for item in instructions)


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


@pytest.mark.unit
async def test_workspace_runtime_plugin_exposes_task_harness_skill() -> None:
    registry = AgentPluginRegistry()
    register_builtin_workspace_plugin(registry)

    skills, diagnostics = await registry.build_skills(
        PluginSkillBuildContext(
            tenant_id="tenant-1",
            project_id="project-1",
            agent_mode="default",
        )
    )

    assert [skill["name"] for skill in skills] == [WORKSPACE_TASK_HARNESS_SKILL_NAME]
    skill = skills[0]
    assert "workspace_report_complete" in skill["tools"]
    assert "collaboration_tracking" in skill["metadata"]["capabilities"]
    assert "workspace_report_complete" in skill["full_content"]
    assert any(d.code == "plugin_skills_loaded" for d in diagnostics)
