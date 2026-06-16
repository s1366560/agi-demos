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
        orch.get_agent.assert_awaited_once_with(
            "agent-123",
            tenant_id="tenant-1",
            project_id="proj-1",
            exact_project=True,
        )

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
        orch.get_agent.assert_awaited_once_with(
            "agent-123",
            tenant_id="tenant-1",
            project_id="proj-1",
            exact_project=True,
        )
        orch.update_agent.assert_awaited_once_with(
            agent,
            tenant_id="tenant-1",
            project_id="proj-1",
            exact_project=True,
        )
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
        orch.get_agent.assert_awaited_once_with(
            "agent-123",
            tenant_id="tenant-1",
            project_id="proj-1",
            exact_project=True,
        )
        orch.delete_agent.assert_awaited_once_with(
            "agent-123",
            tenant_id="tenant-1",
            project_id="proj-1",
            exact_project=True,
        )
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

    async def test_create_with_a2a_allowlist_uses_explicit_values(self) -> None:
        orch = _mock_orchestrator()
        agent = _make_agent(
            agent_to_agent_enabled=True,
            agent_to_agent_allowlist=["sender-1", "sender-2"],
        )
        orch.create_agent.return_value = agent
        configure_agent_definition_manage(orch)

        ctx = _make_ctx()
        result = await agent_definition_manage_tool.execute(
            ctx,
            action="create",
            name="a2a-agent",
            system_prompt="You collaborate with other agents.",
            agent_to_agent_enabled=True,
            agent_to_agent_allowlist=[" sender-1 ", "sender-2", "sender-1"],
        )

        assert result.is_error is False
        created_call = orch.create_agent.call_args[0][0]
        assert created_call.agent_to_agent_enabled is True
        assert created_call.agent_to_agent_allowlist == ["sender-1", "sender-2"]

    async def test_create_with_a2a_enabled_without_allowlist_uses_builtin_default(self) -> None:
        orch = _mock_orchestrator()
        agent = _make_agent(
            agent_to_agent_enabled=True,
            agent_to_agent_allowlist=["builtin:sisyphus", "sisyphus"],
        )
        orch.create_agent.return_value = agent
        configure_agent_definition_manage(orch)

        ctx = _make_ctx()
        result = await agent_definition_manage_tool.execute(
            ctx,
            action="create",
            name="a2a-agent",
            system_prompt="You collaborate with other agents.",
            agent_to_agent_enabled=True,
        )

        assert result.is_error is False
        created_call = orch.create_agent.call_args[0][0]
        assert created_call.agent_to_agent_allowlist == ["builtin:sisyphus", "sisyphus"]

    async def test_create_with_full_capability_policy_fields(self) -> None:
        orch = _mock_orchestrator()
        orch.create_agent.return_value = _make_agent()
        configure_agent_definition_manage(orch)

        ctx = _make_ctx()
        result = await agent_definition_manage_tool.execute(
            ctx,
            action="create",
            name="policy-rich-agent",
            system_prompt="You can use scoped system capabilities.",
            allowed_tools=["web_search", "skill_loader"],
            allowed_skills=["research"],
            allowed_mcp_servers=["filesystem"],
            persona_files=["SOUL.md"],
            workspace_dir=".memstack/agents/policy-rich-agent",
            workspace_config={
                "base_path": ".memstack/agents/policy-rich-agent",
                "max_size_mb": 256,
                "shared_files": ["AGENTS.md"],
                "sandbox_scope": "shared",
            },
            can_spawn=True,
            max_spawn_depth=2,
            max_retries=3,
            fallback_models=["gpt-4o-mini"],
            metadata={"owner": "qa"},
            session_policy={"dm_scope": "per_chat", "max_messages": 20},
            delegate_config={
                "capability_tier": "read_write",
                "max_delegation_depth": 2,
                "allowed_tools": ["web_search"],
                "budget_limit_tokens": 1000,
            },
        )

        assert result.is_error is False
        created_call = orch.create_agent.call_args[0][0]
        assert created_call.allowed_tools == ["web_search", "skill_loader"]
        assert created_call.allowed_skills == ["research"]
        assert created_call.allowed_mcp_servers == ["filesystem"]
        assert created_call.persona_files == ["SOUL.md"]
        assert created_call.workspace_dir == ".memstack/agents/policy-rich-agent"
        assert created_call.workspace_config.max_size_mb == 256
        assert created_call.workspace_config.shared_files == ["AGENTS.md"]
        assert created_call.workspace_config.sandbox_scope.value == "shared"
        assert created_call.can_spawn is True
        assert created_call.max_spawn_depth == 2
        assert created_call.max_retries == 3
        assert created_call.fallback_models == ["gpt-4o-mini"]
        assert created_call.metadata["owner"] == "qa"
        assert created_call.session_policy is not None
        assert created_call.session_policy.dm_scope.value == "per_chat"
        assert created_call.delegate_config is not None
        assert created_call.delegate_config.capability_tier.value == "read_write"

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

    async def test_update_with_a2a_allowlist_uses_explicit_values(self) -> None:
        orch = _mock_orchestrator()
        agent = _make_agent(agent_to_agent_enabled=True, agent_to_agent_allowlist=["old-sender"])
        orch.get_agent.return_value = agent
        orch.update_agent.return_value = agent
        configure_agent_definition_manage(orch)

        ctx = _make_ctx()
        result = await agent_definition_manage_tool.execute(
            ctx,
            action="update",
            agent_id="agent-123",
            agent_to_agent_enabled=True,
            agent_to_agent_allowlist=[" sender-1 ", "sender-2", "sender-1"],
        )

        assert result.is_error is False
        updated_call = orch.update_agent.call_args[0][0]
        assert updated_call.agent_to_agent_enabled is True
        assert updated_call.agent_to_agent_allowlist == ["sender-1", "sender-2"]

    async def test_update_with_full_capability_policy_fields(self) -> None:
        orch = _mock_orchestrator()
        existing = _make_agent()
        orch.get_agent.return_value = existing
        orch.update_agent.return_value = existing
        configure_agent_definition_manage(orch)

        ctx = _make_ctx()
        result = await agent_definition_manage_tool.execute(
            ctx,
            action="update",
            agent_id="agent-123",
            allowed_tools=["terminal"],
            allowed_skills=["python-executor"],
            allowed_mcp_servers=["github"],
            persona_files=["USER.md"],
            workspace_dir=".memstack/agents/updated",
            workspace_config={"type": "isolated", "retention_days": 7},
            max_spawn_depth=4,
            max_retries=2,
            fallback_models=["gpt-4o-mini"],
            metadata={"tier": "gold"},
            session_policy={"dm_scope": "global", "session_ttl_hours": 12},
            delegate_config={
                "capability_tier": "read_only",
                "max_delegation_depth": 0,
            },
        )

        assert result.is_error is False
        updated_call = orch.update_agent.call_args[0][0]
        assert updated_call.allowed_tools == ["terminal"]
        assert updated_call.allowed_skills == ["python-executor"]
        assert updated_call.allowed_mcp_servers == ["github"]
        assert updated_call.persona_files == ["USER.md"]
        assert updated_call.workspace_dir == ".memstack/agents/updated"
        assert updated_call.workspace_config.retention_days == 7
        assert updated_call.workspace_config.sandbox_scope.value == "agent"
        assert updated_call.max_spawn_depth == 4
        assert updated_call.max_retries == 2
        assert updated_call.fallback_models == ["gpt-4o-mini"]
        assert updated_call.metadata == {"tier": "gold"}
        assert updated_call.session_policy is not None
        assert updated_call.session_policy.dm_scope.value == "global"
        assert updated_call.delegate_config is not None
        assert updated_call.delegate_config.max_delegation_depth == 0

    # ------------------------------------------------------------------
    # Partial-update semantics — PR1 acceptance criteria
    # ------------------------------------------------------------------

    async def test_update_changing_only_display_name_preserves_all_other_scalar_fields(
        self,
    ) -> None:
        """Spec: update changing only display_name preserves all other scalar fields."""
        orch = _mock_orchestrator()
        existing = _make_agent(
            can_spawn=False,
            discoverable=True,
            max_iterations=99,
            temperature=0.9,
            max_tokens=8192,
            agent_to_agent_enabled=True,
            agent_to_agent_allowlist=["peer-1"],
        )
        orch.get_agent.return_value = existing
        orch.update_agent.return_value = existing
        configure_agent_definition_manage(orch)

        ctx = _make_ctx()
        result = await agent_definition_manage_tool.execute(
            ctx,
            action="update",
            agent_id="agent-123",
            display_name="Renamed Agent",
        )

        assert result.is_error is False
        updated_call = orch.update_agent.call_args[0][0]
        assert updated_call.display_name == "Renamed Agent"
        assert updated_call.can_spawn is False
        assert updated_call.discoverable is True
        assert updated_call.max_iterations == 99
        assert updated_call.temperature == 0.9
        assert updated_call.max_tokens == 8192
        assert updated_call.agent_to_agent_enabled is True
        assert updated_call.agent_to_agent_allowlist == ["peer-1"]

    async def test_update_with_explicit_falsey_values_preserves_intent(self) -> None:
        """Spec: explicit falsey updates (can_spawn=False, discoverable=False,
        temperature=0.0) must be applied, not silently dropped."""
        orch = _mock_orchestrator()
        existing = _make_agent(
            can_spawn=True,
            discoverable=True,
            temperature=0.7,
        )
        orch.get_agent.return_value = existing
        orch.update_agent.return_value = existing
        configure_agent_definition_manage(orch)

        ctx = _make_ctx()
        result = await agent_definition_manage_tool.execute(
            ctx,
            action="update",
            agent_id="agent-123",
            can_spawn=False,
            discoverable=False,
            temperature=0.0,
        )

        assert result.is_error is False
        updated_call = orch.update_agent.call_args[0][0]
        assert updated_call.can_spawn is False
        assert updated_call.discoverable is False
        assert updated_call.temperature == 0.0
