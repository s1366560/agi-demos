"""Unit tests for channel binding agent resolution."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.application.services.agent_router_service import AgentRouterService
from src.domain.model.agent.agent_binding import AgentBinding


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_agent_fails_closed_for_project_scoped_binding_target() -> None:
    binding = AgentBinding(id="binding-1", tenant_id="tenant-1", agent_id="project-agent")
    binding_repo = SimpleNamespace(resolve_binding=AsyncMock(return_value=binding))
    project_agent = SimpleNamespace(
        id="project-agent",
        name="Project Agent",
        project_id="project-1",
        is_enabled=lambda: True,
    )
    agent_registry = SimpleNamespace(get_by_id=AsyncMock(return_value=project_agent))
    service = AgentRouterService(binding_repo, agent_registry)

    result = await service.resolve_agent(tenant_id="tenant-1", channel_type="slack")

    assert result.binding_matched is True
    assert result.reason == "invalid_binding:agent_project_scoped:project-agent"
    assert result.agent is None
    agent_registry.get_by_id.assert_awaited_once_with("project-agent", tenant_id="tenant-1")
