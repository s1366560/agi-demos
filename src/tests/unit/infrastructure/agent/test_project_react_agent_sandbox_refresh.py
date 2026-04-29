"""Regression tests for project sandbox tool refresh behavior."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.core.project_react_agent import ProjectReActAgent


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sandbox_refresh_ignores_non_running_project_sandbox(monkeypatch):
    """Created/stopped containers should not trigger endless tool refreshes."""
    agent = ProjectReActAgent.__new__(ProjectReActAgent)
    agent._initialized = True
    agent._tools = {"existing_tool": object()}
    agent.config = SimpleNamespace(
        tenant_id="tenant",
        project_id="proj-1",
        agent_mode="default",
    )
    agent.initialize = AsyncMock(return_value=True)

    adapter = AsyncMock()
    adapter.list_sandboxes.return_value = [
        SimpleNamespace(
            id="mcp-sandbox-stale",
            project_path="/tmp/memstack_proj-1",
            labels={"memstack.project_id": "proj-1"},
        )
    ]
    adapter.container_exists.return_value = False

    monkeypatch.setattr(
        "src.infrastructure.agent.state.agent_worker_state.get_mcp_sandbox_adapter",
        lambda: adapter,
    )

    refreshed = await ProjectReActAgent._check_and_refresh_sandbox_tools(agent)

    assert refreshed is False
    agent.initialize.assert_not_awaited()
