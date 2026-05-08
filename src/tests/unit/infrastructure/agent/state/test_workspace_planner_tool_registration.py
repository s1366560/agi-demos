"""Regression coverage for workspace planner terminal tool registration."""

from __future__ import annotations

import pytest

from src.infrastructure.agent.state import agent_worker_state
from src.infrastructure.agent.tools.workspace_planning_contract import (
    WORKSPACE_SUBMIT_PLANNING_CONTRACT_TOOL_NAME,
)


@pytest.mark.unit
async def test_get_or_create_tools_exposes_planner_contract_without_agent_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Planner kickoff must see its terminal contract tool before multi-agent bootstraps."""

    async def _async_noop(*args: object, **kwargs: object) -> None:
        return None

    async def _empty_builtin_tools(*args: object, **kwargs: object) -> dict[str, object]:
        return {}

    def _noop(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(agent_worker_state, "_get_or_create_builtin_tools", _empty_builtin_tools)
    for name in (
        "_add_sandbox_tools",
        "_add_skill_loader_tool",
        "_add_plugin_tools",
        "_add_sandbox_plugin_tools",
        "_add_workspace_chat_tools",
    ):
        monkeypatch.setattr(agent_worker_state, name, _async_noop)

    for name in (
        "_add_skill_installer_tools",
        "_add_skill_sync_tool",
        "_add_env_var_tools",
        "_add_hitl_tools",
        "_add_todo_tools",
        "_configure_skill_evolution_capture",
        "_add_model_awareness_tools",
        "_add_register_mcp_server_tool",
        "_add_custom_tools",
        "_add_session_comm_tools",
        "_add_session_status_tool",
        "_add_cron_tool",
        "_add_canvas_tools",
        "_add_agent_tools",
    ):
        monkeypatch.setattr(agent_worker_state, name, _noop)

    tools = await agent_worker_state.get_or_create_tools(
        project_id="project-1",
        tenant_id="tenant-1",
        graph_service=object(),
        redis_client=object(),
    )

    assert WORKSPACE_SUBMIT_PLANNING_CONTRACT_TOOL_NAME in tools
