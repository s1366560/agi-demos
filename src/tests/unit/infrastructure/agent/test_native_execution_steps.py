"""Inner device operations use the live selected agent, including child identity."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.adapters.primary.web.routers.agent.computer_use_steps import (
    current_agent_servers,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_registry import (
    SqlAgentRegistryRepository,
)
from src.infrastructure.agent.native_computer_use.store import DeviceBridgeError

pytestmark = pytest.mark.unit


def scope(**changes):
    return {
        "user_id": "user",
        "tenant_id": "tenant",
        "project_id": "project",
        "conversation_id": "conversation",
        "agent_id": "agent",
        **changes,
    }


def conversation(selected="agent"):
    return SimpleNamespace(
        user_id="user",
        tenant_id="tenant",
        project_id="project",
        agent_config={"selected_agent_id": selected},
    )


def agent():
    return SimpleNamespace(
        enabled=True,
        project_id="project",
        name="child-agent",
        allowed_mcp_servers=["server"],
        has_tool_access=lambda tool: tool == "allowed",
    )


async def test_selected_agent_change_and_tool_roster_reject_old_cell(monkeypatch):
    loader = AsyncMock(return_value=agent())
    monkeypatch.setattr(SqlAgentRegistryRepository, "get_by_id", loader)
    db = SimpleNamespace(get=AsyncMock(return_value=conversation()))
    assert await current_agent_servers(db, scope(), "allowed") == ("server",)
    with pytest.raises(DeviceBridgeError, match="tool_denied"):
        await current_agent_servers(db, scope(), "unlisted")
    db.get.return_value = conversation("replacement")
    with pytest.raises(DeviceBridgeError, match="authority_changed"):
        await current_agent_servers(db, scope(), "allowed")
    assert loader.await_count == 2


async def test_child_agent_uses_own_definition_and_never_parent_roster(monkeypatch):
    loader = AsyncMock(return_value=agent())
    monkeypatch.setattr(SqlAgentRegistryRepository, "get_by_id", loader)
    child = {"status": "running", "subagent_name": "child-agent"}
    snapshot = SimpleNamespace(tenant_id="tenant", project_id="project", runs={"child": child})
    db = SimpleNamespace(get=AsyncMock(side_effect=[conversation("parent"), snapshot]))
    assert await current_agent_servers(db, scope(child_run_id="child"), "allowed") == ("server",)
    child["subagent_name"] = "other-child"
    db.get.side_effect = [conversation("parent"), snapshot]
    with pytest.raises(DeviceBridgeError, match="child_agent_changed"):
        await current_agent_servers(db, scope(child_run_id="child"), "allowed")
    child["status"] = "completed"
    db.get.side_effect = [conversation("parent"), snapshot]
    with pytest.raises(DeviceBridgeError, match="child_authority_revoked"):
        await current_agent_servers(db, scope(child_run_id="child"), "allowed")
    assert loader.await_count == 2
