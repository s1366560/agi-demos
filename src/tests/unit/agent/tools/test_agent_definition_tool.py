"""Tests for agent_definition_manage tool."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.model.agent.agent_definition import Agent
from src.domain.model.agent.agent_source import AgentSource
from src.domain.model.agent.subagent import AgentModel, AgentTrigger
from src.infrastructure.agent.tools.agent_definition_tool import (
    agent_definition_manage_tool,
    configure_agent_definition_manage,
)
from src.infrastructure.agent.tools.context import ToolContext


def _make_ctx(**overrides: object) -> ToolContext:
    defaults = {
        "session_id": "sess-1",
        "message_id": "msg-1",
        "call_id": "call-1",
        "agent_name": "test-agent",
        "conversation_id": "conv-1",
        "project_id": "proj-1",
        "tenant_id": "tenant-1",
        "user_id": "user-1",
    }
    defaults.update(overrides)
    return ToolContext(**defaults)  # type: ignore[arg-type]


def _make_agent(**overrides: object) -> Agent:
    defaults = {
        "id": "agent-123",
        "tenant_id": "tenant-1",
        "name": "test-agent-def",
        "display_name": "Test Agent",
        "system_prompt": "You are a test agent.",
        "trigger": AgentTrigger(
            description="test trigger",
            examples=["example1"],
            keywords=["test"],
        ),
        "project_id": "proj-1",
        "model": AgentModel.INHERIT,
        "source": AgentSource.DATABASE,
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


def _mock_orchestrator() -> MagicMock:
    orch = MagicMock()
    orch.create_agent = AsyncMock()
    orch.update_agent = AsyncMock()
    orch.delete_agent = AsyncMock()
    orch.get_agent = AsyncMock()
    orch.get_agent_by_name = AsyncMock()
    return orch


@pytest.mark.unit
class TestAgentDefinitionManageTool:
    """Tests for agent_definition_manage tool."""

    async def test_not_configured_returns_error(self) -> None:
        import src.infrastructure.agent.tools.agent_definition_tool as mod

        original = mod._orchestrator
        mod._orchestrator = None
        try:
            ctx = _make_ctx()
            result = await agent_definition_manage_tool.execute(ctx, action="create")
            assert result.is_error is True
            assert "not configured" in json.loads(result.output)["error"]
        finally:
            mod._orchestrator = original

    async def test_unknown_action_returns_error(self) -> None:
        orch = _mock_orchestrator()
        configure_agent_definition_manage(orch)

        ctx = _make_ctx()
        result = await agent_definition_manage_tool.execute(ctx, action="invalid")
        assert result.is_error is True
        assert "Unknown action" in json.loads(result.output)["error"]

    async def test_create_success(self) -> None:
        orch = _mock_orchestrator()
        agent = _make_agent()
        orch.create_agent.return_value = agent
        configure_agent_definition_manage(orch)

        ctx = _make_ctx()
        result = await agent_definition_manage_tool.execute(
            ctx,
            action="create",
            name="test-agent-def",
            display_name="Test Agent",
            system_prompt="You are a test agent.",
            trigger_description="test trigger",
            trigger_keywords=["test"],
        )

        assert result.is_error is False
        data = json.loads(result.output)
        assert data["name"] == "test-agent-def"
        assert data["display_name"] == "Test Agent"
        orch.create_agent.assert_awaited_once()
        assert len(ctx._pending_events) == 1
        assert ctx._pending_events[0]["type"] == "agent_definition_created"

    async def test_create_missing_name_returns_error(self) -> None:
        orch = _mock_orchestrator()
        configure_agent_definition_manage(orch)

        ctx = _make_ctx()
        result = await agent_definition_manage_tool.execute(
            ctx,
            action="create",
            system_prompt="prompt",
        )
        assert result.is_error is True
        assert "name" in json.loads(result.output)["error"].lower()

    async def test_create_missing_system_prompt_returns_error(self) -> None:
        orch = _mock_orchestrator()
        configure_agent_definition_manage(orch)

        ctx = _make_ctx()
        result = await agent_definition_manage_tool.execute(
            ctx,
            action="create",
            name="test",
        )
        assert result.is_error is True
        assert "system_prompt" in json.loads(result.output)["error"]

    async def test_create_duplicate_name_returns_error(self) -> None:
        orch = _mock_orchestrator()
        orch.create_agent.side_effect = ValueError("already exists")
        configure_agent_definition_manage(orch)

        ctx = _make_ctx()
        result = await agent_definition_manage_tool.execute(
            ctx,
            action="create",
            name="duplicate",
            system_prompt="prompt",
        )
        assert result.is_error is True
        assert "already exists" in json.loads(result.output)["error"]

    async def test_get_success(self) -> None:
        orch = _mock_orchestrator()
        agent = _make_agent()
        orch.get_agent.return_value = agent
        configure_agent_definition_manage(orch)

        ctx = _make_ctx()
        result = await agent_definition_manage_tool.execute(
            ctx,
            action="get",
            agent_id="agent-123",
        )
        assert result.is_error is False
        data = json.loads(result.output)
        assert data["id"] == "agent-123"
        assert data["name"] == "test-agent-def"

    async def test_get_not_found_returns_error(self) -> None:
        orch = _mock_orchestrator()
        orch.get_agent.return_value = None
        configure_agent_definition_manage(orch)

        ctx = _make_ctx()
        result = await agent_definition_manage_tool.execute(
            ctx,
            action="get",
            agent_id="nonexistent",
        )
        assert result.is_error is True
        assert "not found" in json.loads(result.output)["error"].lower()

    async def test_get_missing_agent_id_returns_error(self) -> None:
        orch = _mock_orchestrator()
        configure_agent_definition_manage(orch)

        ctx = _make_ctx()
        result = await agent_definition_manage_tool.execute(ctx, action="get")
        assert result.is_error is True
        assert "agent_id" in json.loads(result.output)["error"]

    async def test_update_success(self) -> None:
        orch = _mock_orchestrator()
        agent = _make_agent()
        orch.get_agent.return_value = agent
        updated_agent = _make_agent(display_name="Updated Agent")
        orch.update_agent.return_value = updated_agent
        configure_agent_definition_manage(orch)

        ctx = _make_ctx()
        result = await agent_definition_manage_tool.execute(
            ctx,
            action="update",
            agent_id="agent-123",
            display_name="Updated Agent",
        )
        assert result.is_error is False
        data = json.loads(result.output)
        assert data["display_name"] == "Updated Agent"
        orch.update_agent.assert_awaited_once()
        assert len(ctx._pending_events) == 1
        assert ctx._pending_events[0]["type"] == "agent_definition_updated"

    async def test_update_not_found_returns_error(self) -> None:
        orch = _mock_orchestrator()
        orch.get_agent.return_value = None
        configure_agent_definition_manage(orch)

        ctx = _make_ctx()
        result = await agent_definition_manage_tool.execute(
            ctx,
            action="update",
            agent_id="nonexistent",
            display_name="New Name",
        )
        assert result.is_error is True
        assert "not found" in json.loads(result.output)["error"].lower()

    async def test_update_missing_agent_id_returns_error(self) -> None:
        orch = _mock_orchestrator()
        configure_agent_definition_manage(orch)

        ctx = _make_ctx()
        result = await agent_definition_manage_tool.execute(
            ctx,
            action="update",
            display_name="New Name",
        )
        assert result.is_error is True
        assert "agent_id" in json.loads(result.output)["error"]

    async def test_delete_success(self) -> None:
        orch = _mock_orchestrator()
        agent = _make_agent()
        orch.get_agent.return_value = agent
        orch.delete_agent.return_value = True
        configure_agent_definition_manage(orch)

        ctx = _make_ctx()
        result = await agent_definition_manage_tool.execute(
            ctx,
            action="delete",
            agent_id="agent-123",
        )
        assert result.is_error is False
        data = json.loads(result.output)
        assert data["deleted"] is True
        assert data["id"] == "agent-123"
        orch.delete_agent.assert_awaited_once_with("agent-123")
        assert len(ctx._pending_events) == 1
        assert ctx._pending_events[0]["type"] == "agent_definition_deleted"

    async def test_delete_not_found_returns_error(self) -> None:
        orch = _mock_orchestrator()
        orch.get_agent.return_value = None
        configure_agent_definition_manage(orch)

        ctx = _make_ctx()
        result = await agent_definition_manage_tool.execute(
            ctx,
            action="delete",
            agent_id="nonexistent",
        )
        assert result.is_error is True
        assert "not found" in json.loads(result.output)["error"].lower()

    async def test_delete_missing_agent_id_returns_error(self) -> None:
        orch = _mock_orchestrator()
        configure_agent_definition_manage(orch)

        ctx = _make_ctx()
        result = await agent_definition_manage_tool.execute(ctx, action="delete")
        assert result.is_error is True
        assert "agent_id" in json.loads(result.output)["error"]

    async def test_create_with_model(self) -> None:
        orch = _mock_orchestrator()
        agent = _make_agent(model=AgentModel.GPT4O)
        orch.create_agent.return_value = agent
        configure_agent_definition_manage(orch)

        ctx = _make_ctx()
        result = await agent_definition_manage_tool.execute(
            ctx,
            action="create",
            name="gpt-agent",
            system_prompt="You use GPT-4o.",
            model="gpt-4o",
        )
        assert result.is_error is False
        created_call = orch.create_agent.call_args[0][0]
        assert created_call.model == AgentModel.GPT4O

    async def test_update_trigger_fields(self) -> None:
        orch = _mock_orchestrator()
        agent = _make_agent()
        orch.get_agent.return_value = agent
        orch.update_agent.return_value = agent
        configure_agent_definition_manage(orch)

        ctx = _make_ctx()
        result = await agent_definition_manage_tool.execute(
            ctx,
            action="update",
            agent_id="agent-123",
            trigger_description="new trigger",
            trigger_keywords=["new", "keywords"],
        )
        assert result.is_error is False
        updated_call = orch.update_agent.call_args[0][0]
        assert updated_call.trigger.description == "new trigger"
        assert list(updated_call.trigger.keywords) == ["new", "keywords"]
