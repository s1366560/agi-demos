"""Tests for AgentOrchestrator multi-agent lifecycle management."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, Mock, call

import pytest

from src.domain.model.agent.agent_role import AgentRole
from src.domain.model.agent.spawn_mode import SpawnMode
from src.domain.model.agent.spawn_record import SpawnRecord
from src.domain.ports.agent.agent_registry import AgentRegistryPort
from src.domain.ports.services.agent_message_bus_port import (
    AgentMessageBusPort,
    AgentMessageType,
)
from src.infrastructure.agent.orchestration.orchestrator import (
    AgentOrchestrator,
    SendResult,
    SpawnResult,
)
from src.infrastructure.agent.orchestration.session_registry import (
    AgentSession,
    AgentSessionRegistry,
)
from src.infrastructure.agent.orchestration.spawn_manager import SpawnManager


class _OrchestratorFixture:
    """Container for orchestrator and its mocked dependencies."""

    def __init__(self) -> None:
        self.agent_registry = AsyncMock(spec=AgentRegistryPort)
        self.session_registry = AsyncMock(spec=AgentSessionRegistry)
        self.session_registry.get_session_for_conversation = AsyncMock(
            side_effect=lambda conversation_id, project_id: AgentSession(
                agent_id="parent-1",
                conversation_id=conversation_id,
                project_id=project_id,
            )
        )
        self.spawn_manager = AsyncMock(spec=SpawnManager)
        self.message_bus = AsyncMock(spec=AgentMessageBusPort)
        self.orchestrator = AgentOrchestrator(
            self.agent_registry,
            self.session_registry,
            self.spawn_manager,
            self.message_bus,
        )


@pytest.fixture
def fx() -> _OrchestratorFixture:
    """Create an AgentOrchestrator with all four dependencies mocked."""
    return _OrchestratorFixture()


def _make_agent(**overrides: Any) -> Mock:
    """Create a mock Agent with sensible defaults."""
    agent = Mock()
    agent.id = overrides.pop("id", "agent-1")
    agent.name = overrides.pop("name", agent.id)
    agent.display_name = overrides.pop("display_name", agent.name)
    agent.tenant_id = overrides.pop("tenant_id", "tenant-1")
    agent.project_id = overrides.pop("project_id", "proj-1")
    agent.enabled = True
    agent.discoverable = True
    agent.agent_to_agent_enabled = True
    agent.can_spawn = True
    agent.max_spawn_depth = overrides.pop("max_spawn_depth", 3)
    agent.role = AgentRole.ORCHESTRATOR
    for key, value in overrides.items():
        setattr(agent, key, value)
    return agent


def _make_spawn_record(**overrides: Any) -> SpawnRecord:
    """Create a SpawnRecord with sensible defaults."""
    defaults: dict[str, Any] = {
        "parent_agent_id": "parent-1",
        "child_agent_id": "target-1",
        "child_session_id": "child-sess-1",
        "project_id": "proj-1",
        "mode": SpawnMode.RUN,
    }
    defaults.update(overrides)
    return SpawnRecord(**defaults)


def _make_session(**overrides: Any) -> AgentSession:
    """Create an AgentSession with sensible defaults."""
    defaults: dict[str, Any] = {
        "agent_id": "target-1",
        "conversation_id": "child-sess-1",
        "project_id": "proj-1",
    }
    defaults.update(overrides)
    return AgentSession(**defaults)


# ---------------------------------------------------------------------------
# spawn_agent
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSpawnAgent:
    """Test suite for AgentOrchestrator.spawn_agent."""

    async def test_spawn_agent_happy_path_returns_spawn_result(
        self, fx: _OrchestratorFixture
    ) -> None:
        """Happy path: agent found, enabled, discoverable -- returns SpawnResult."""
        # Arrange
        parent_agent = _make_agent(id="parent-1")
        mock_agent = _make_agent(id="target-1")
        expected_record = _make_spawn_record()
        expected_session = _make_session()

        fx.agent_registry.get_by_id = AsyncMock(side_effect=[parent_agent, mock_agent])
        fx.spawn_manager.get_spawn_depth = AsyncMock(return_value=0)
        fx.spawn_manager.max_spawn_depth = 3
        fx.spawn_manager.register_spawn = AsyncMock(return_value=expected_record)
        fx.session_registry.register = AsyncMock(return_value=expected_session)
        fx.message_bus.send_message = AsyncMock(return_value="msg-id-1")

        # Act
        result = await fx.orchestrator.spawn_agent(
            parent_agent_id="parent-1",
            target_agent_id="target-1",
            message="Do something useful",
            mode=SpawnMode.RUN,
            parent_session_id="parent-sess-1",
            project_id="proj-1",
        )

        # Assert
        assert isinstance(result, SpawnResult)
        assert result.agent is mock_agent
        assert result.spawn_record is expected_record
        assert result.session is expected_session

    async def test_spawn_agent_calls_registry_with_target_id(
        self, fx: _OrchestratorFixture
    ) -> None:
        """Verify get_by_id is called with the target_agent_id."""
        # Arrange
        parent_agent = _make_agent(id="parent-1")
        target_agent = _make_agent(id="my-target")
        fx.agent_registry.get_by_id = AsyncMock(side_effect=[parent_agent, target_agent])
        fx.spawn_manager.get_spawn_depth = AsyncMock(return_value=0)
        fx.spawn_manager.max_spawn_depth = 3
        fx.spawn_manager.register_spawn = AsyncMock(return_value=_make_spawn_record())
        fx.session_registry.register = AsyncMock(return_value=_make_session())
        fx.message_bus.send_message = AsyncMock(return_value="msg-id-1")

        # Act
        await fx.orchestrator.spawn_agent(
            parent_agent_id="parent-1",
            target_agent_id="my-target",
            message="hello",
            mode=SpawnMode.RUN,
            parent_session_id="parent-sess",
            project_id="proj-1",
        )

        # Assert
        assert fx.agent_registry.get_by_id.await_args_list == [
            call("parent-1", tenant_id=None, project_id="proj-1"),
            call("my-target", tenant_id=None, project_id="proj-1"),
        ]

    async def test_spawn_agent_calls_spawn_depth_with_parent_session(
        self, fx: _OrchestratorFixture
    ) -> None:
        """Verify get_spawn_depth is called with parent_session_id."""
        # Arrange
        parent_agent = _make_agent(id="parent-1")
        target_agent = _make_agent(id="target-1")
        fx.agent_registry.get_by_id = AsyncMock(side_effect=[parent_agent, target_agent])
        fx.spawn_manager.get_spawn_depth = AsyncMock(return_value=0)
        fx.spawn_manager.max_spawn_depth = 3
        fx.spawn_manager.register_spawn = AsyncMock(return_value=_make_spawn_record())
        fx.session_registry.register = AsyncMock(return_value=_make_session())
        fx.message_bus.send_message = AsyncMock(return_value="msg-id-1")

        # Act
        await fx.orchestrator.spawn_agent(
            parent_agent_id="parent-1",
            target_agent_id="target-1",
            message="hello",
            mode=SpawnMode.RUN,
            parent_session_id="ps-123",
            project_id="proj-1",
        )

        # Assert
        fx.spawn_manager.get_spawn_depth.assert_called_once_with("ps-123")

    async def test_spawn_agent_sends_request_message(self, fx: _OrchestratorFixture) -> None:
        """Verify message_bus.send_message is called with REQUEST type."""
        # Arrange
        parent_agent = _make_agent(id="parent-1")
        target_agent = _make_agent(id="target-1")
        fx.agent_registry.get_by_id = AsyncMock(side_effect=[parent_agent, target_agent])
        fx.spawn_manager.get_spawn_depth = AsyncMock(return_value=0)
        fx.spawn_manager.max_spawn_depth = 3
        fx.spawn_manager.register_spawn = AsyncMock(return_value=_make_spawn_record())
        fx.session_registry.register = AsyncMock(return_value=_make_session())
        fx.message_bus.send_message = AsyncMock(return_value="msg-id-1")

        # Act
        await fx.orchestrator.spawn_agent(
            parent_agent_id="parent-1",
            target_agent_id="target-1",
            message="Do this task",
            mode=SpawnMode.RUN,
            parent_session_id="parent-sess",
            project_id="proj-1",
        )

        # Assert
        fx.message_bus.send_message.assert_called_once()
        send_kwargs = fx.message_bus.send_message.call_args.kwargs
        assert send_kwargs["message_type"] == AgentMessageType.REQUEST
        assert send_kwargs["content"] == "Do this task"
        assert send_kwargs["from_agent_id"] == "parent-1"
        assert send_kwargs["to_agent_id"] == "target-1"

    async def test_spawn_agent_invokes_spawn_executor_with_child_request(
        self, fx: _OrchestratorFixture
    ) -> None:
        spawn_executor = AsyncMock()
        fx.orchestrator = AgentOrchestrator(
            fx.agent_registry,
            fx.session_registry,
            fx.spawn_manager,
            fx.message_bus,
            spawn_executor=spawn_executor,
        )
        parent_agent = _make_agent(id="parent-1")
        child_agent = _make_agent(
            id="target-1",
            name="child-agent",
            display_name="Child Agent",
        )
        fx.agent_registry.get_by_id = AsyncMock(side_effect=[parent_agent, child_agent])
        fx.spawn_manager.get_spawn_depth = AsyncMock(return_value=0)
        fx.spawn_manager.max_spawn_depth = 3
        fx.spawn_manager.register_spawn = AsyncMock(return_value=_make_spawn_record())
        fx.session_registry.register = AsyncMock(return_value=_make_session())
        fx.message_bus.send_message = AsyncMock(return_value="msg-id-1")

        await fx.orchestrator.spawn_agent(
            parent_agent_id="parent-1",
            target_agent_id="target-1",
            message="Do this task",
            mode=SpawnMode.RUN,
            parent_session_id="parent-sess",
            project_id="proj-1",
            conversation_id="conv-1",
            tenant_id="tenant-1",
            user_id="user-1",
        )

        spawn_executor.assert_awaited_once()
        request = spawn_executor.await_args.args[0]
        assert request.parent_agent_id == "parent-1"
        assert request.child_agent_id == "target-1"
        assert request.child_agent_name == "Child Agent"
        assert request.parent_session_id == "parent-sess"
        assert request.project_id == "proj-1"
        assert request.tenant_id == "tenant-1"
        assert request.user_id == "user-1"
        assert request.conversation_id == "conv-1"
        assert request.message == "Do this task"

    async def test_spawn_agent_not_found_raises_value_error(self, fx: _OrchestratorFixture) -> None:
        """Agent not found raises ValueError."""
        # Arrange
        parent_agent = _make_agent(id="parent-1")
        fx.agent_registry.get_by_id = AsyncMock(side_effect=[parent_agent, None])

        # Act / Assert
        with pytest.raises(ValueError, match="Target agent not found: missing-agent"):
            await fx.orchestrator.spawn_agent(
                parent_agent_id="parent-1",
                target_agent_id="missing-agent",
                message="hello",
                mode=SpawnMode.RUN,
                parent_session_id="parent-sess",
                project_id="proj-1",
            )

    async def test_spawn_agent_disabled_raises_value_error(self, fx: _OrchestratorFixture) -> None:
        """Disabled agent raises ValueError."""
        # Arrange
        parent_agent = _make_agent(id="parent-1")
        disabled_agent = _make_agent(id="disabled-1", enabled=False)
        fx.agent_registry.get_by_id = AsyncMock(side_effect=[parent_agent, disabled_agent])

        # Act / Assert
        with pytest.raises(ValueError, match="Target agent is disabled: disabled-1"):
            await fx.orchestrator.spawn_agent(
                parent_agent_id="parent-1",
                target_agent_id="disabled-1",
                message="hello",
                mode=SpawnMode.RUN,
                parent_session_id="parent-sess",
                project_id="proj-1",
            )

    async def test_spawn_agent_not_discoverable_raises_value_error(
        self, fx: _OrchestratorFixture
    ) -> None:
        """Non-discoverable agent raises ValueError."""
        # Arrange
        parent_agent = _make_agent(id="parent-1")
        hidden_agent = _make_agent(id="hidden-1", discoverable=False)
        fx.agent_registry.get_by_id = AsyncMock(side_effect=[parent_agent, hidden_agent])

        # Act / Assert
        with pytest.raises(ValueError, match="Target agent is not discoverable: hidden-1"):
            await fx.orchestrator.spawn_agent(
                parent_agent_id="parent-1",
                target_agent_id="hidden-1",
                message="hello",
                mode=SpawnMode.RUN,
                parent_session_id="parent-sess",
                project_id="proj-1",
            )

    async def test_spawn_agent_parent_without_spawn_capability_raises_value_error(
        self, fx: _OrchestratorFixture
    ) -> None:
        """Parents must explicitly opt in before spawning child agents."""
        parent_agent = _make_agent(id="parent-1", can_spawn=False)
        fx.agent_registry.get_by_id = AsyncMock(return_value=parent_agent)

        with pytest.raises(
            ValueError,
            match="Parent agent is not allowed to spawn child agents: parent-1",
        ):
            await fx.orchestrator.spawn_agent(
                parent_agent_id="parent-1",
                target_agent_id="target-1",
                message="hello",
                mode=SpawnMode.RUN,
                parent_session_id="parent-sess",
                project_id="proj-1",
            )

    async def test_spawn_agent_parent_session_must_belong_to_parent_agent(
        self, fx: _OrchestratorFixture
    ) -> None:
        """Parent session ownership is validated before child work is registered."""
        parent_agent = _make_agent(id="parent-1")
        fx.agent_registry.get_by_id = AsyncMock(return_value=parent_agent)
        fx.session_registry.get_session_for_conversation = AsyncMock(
            return_value=AgentSession(
                agent_id="other-agent",
                conversation_id="parent-sess",
                project_id="proj-1",
            )
        )

        with pytest.raises(
            ValueError,
            match="Parent session parent-sess does not belong to parent agent parent-1",
        ):
            await fx.orchestrator.spawn_agent(
                parent_agent_id="parent-1",
                target_agent_id="target-1",
                message="hello",
                mode=SpawnMode.RUN,
                parent_session_id="parent-sess",
                project_id="proj-1",
            )

    async def test_spawn_agent_parent_max_spawn_depth_is_enforced(
        self, fx: _OrchestratorFixture
    ) -> None:
        """Per-agent spawn depth caps are enforced alongside the global limit."""
        parent_agent = _make_agent(id="parent-1", max_spawn_depth=0)
        target_agent = _make_agent(id="target-1")
        fx.agent_registry.get_by_id = AsyncMock(side_effect=[parent_agent, target_agent])
        fx.spawn_manager.get_spawn_depth = AsyncMock(return_value=0)

        with pytest.raises(
            ValueError,
            match="Parent agent parent-1 exceeded max_spawn_depth 0",
        ):
            await fx.orchestrator.spawn_agent(
                parent_agent_id="parent-1",
                target_agent_id="target-1",
                message="hello",
                mode=SpawnMode.RUN,
                parent_session_id="parent-sess",
                project_id="proj-1",
            )

    async def test_spawn_agent_system_parent_bypasses_registry_lookup(
        self, fx: _OrchestratorFixture
    ) -> None:
        """Explicit system parents can still launch graph-managed child agents."""
        target_agent = _make_agent(id="target-1")
        fx.agent_registry.get_by_id = AsyncMock(return_value=target_agent)
        fx.spawn_manager.get_spawn_depth = AsyncMock(return_value=0)
        fx.spawn_manager.max_spawn_depth = 3
        fx.spawn_manager.register_spawn = AsyncMock(
            return_value=_make_spawn_record(parent_agent_id="__system__")
        )
        fx.session_registry.register = AsyncMock(return_value=_make_session())
        fx.message_bus.send_message = AsyncMock(return_value="msg-id-1")

        await fx.orchestrator.spawn_agent(
            parent_agent_id="__system__",
            target_agent_id="target-1",
            message="hello",
            mode=SpawnMode.RUN,
            parent_session_id="parent-sess",
            project_id="proj-1",
        )

        fx.agent_registry.get_by_id.assert_awaited_once_with(
            "target-1",
            tenant_id=None,
            project_id="proj-1",
        )

    async def test_spawn_agent_metadata_enrichment_with_existing_metadata(
        self, fx: _OrchestratorFixture
    ) -> None:
        """When metadata is provided, enriched_metadata has original keys plus agent_role and agent_depth."""
        # Arrange
        parent_agent = _make_agent(id="parent-1")
        target_agent = _make_agent(id="target-1")
        fx.agent_registry.get_by_id = AsyncMock(side_effect=[parent_agent, target_agent])
        fx.spawn_manager.get_spawn_depth = AsyncMock(return_value=0)
        fx.spawn_manager.max_spawn_depth = 3
        fx.spawn_manager.register_spawn = AsyncMock(return_value=_make_spawn_record())
        fx.session_registry.register = AsyncMock(return_value=_make_session())
        fx.message_bus.send_message = AsyncMock(return_value="msg-id-1")

        # Act
        await fx.orchestrator.spawn_agent(
            parent_agent_id="parent-1",
            target_agent_id="target-1",
            message="hello",
            mode=SpawnMode.RUN,
            parent_session_id="parent-sess",
            project_id="proj-1",
            metadata={"key": "val"},
        )

        # Assert
        register_kwargs = fx.spawn_manager.register_spawn.call_args.kwargs
        enriched = register_kwargs["metadata"]
        assert enriched["key"] == "val"
        assert "agent_role" in enriched
        assert "agent_depth" in enriched
        # depth 0 parent -> child depth 1, max_depth 3 -> ORCHESTRATOR
        assert enriched["agent_role"] == AgentRole.ORCHESTRATOR.value
        assert enriched["agent_depth"] == 1

    async def test_spawn_agent_metadata_none_default_still_enriched(
        self, fx: _OrchestratorFixture
    ) -> None:
        """When metadata=None, enriched_metadata still has agent_role and agent_depth."""
        # Arrange
        parent_agent = _make_agent(id="parent-1")
        target_agent = _make_agent(id="target-1")
        fx.agent_registry.get_by_id = AsyncMock(side_effect=[parent_agent, target_agent])
        fx.spawn_manager.get_spawn_depth = AsyncMock(return_value=0)
        fx.spawn_manager.max_spawn_depth = 3
        fx.spawn_manager.register_spawn = AsyncMock(return_value=_make_spawn_record())
        fx.session_registry.register = AsyncMock(return_value=_make_session())
        fx.message_bus.send_message = AsyncMock(return_value="msg-id-1")

        # Act
        await fx.orchestrator.spawn_agent(
            parent_agent_id="parent-1",
            target_agent_id="target-1",
            message="hello",
            mode=SpawnMode.RUN,
            parent_session_id="parent-sess",
            project_id="proj-1",
            metadata=None,
        )

        # Assert
        register_kwargs = fx.spawn_manager.register_spawn.call_args.kwargs
        enriched = register_kwargs["metadata"]
        assert "agent_role" in enriched
        assert "agent_depth" in enriched


# ---------------------------------------------------------------------------
# send_message
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSendMessage:
    """Test suite for AgentOrchestrator.send_message."""

    async def test_send_message_happy_path_with_explicit_session(
        self, fx: _OrchestratorFixture
    ) -> None:
        """Happy path with explicit session_id returns SendResult."""
        # Arrange
        from_agent = _make_agent(id="agent-a")
        to_agent = _make_agent(id="agent-b")
        fx.agent_registry.get_by_id = AsyncMock(side_effect=[from_agent, to_agent])
        fx.session_registry.get_session_for_conversation = AsyncMock(
            side_effect=[
                AgentSession(
                    agent_id="agent-b",
                    conversation_id="sess-explicit",
                    project_id="proj-1",
                ),
                AgentSession(
                    agent_id="agent-a",
                    conversation_id="sender-sess",
                    project_id="proj-1",
                ),
            ]
        )
        fx.message_bus.send_message = AsyncMock(return_value="msg-42")

        # Act
        result = await fx.orchestrator.send_message(
            from_agent_id="agent-a",
            to_agent_id="agent-b",
            message="hello",
            session_id="sess-explicit",
            sender_session_id="sender-sess",
            project_id="proj-1",
        )

        # Assert
        assert isinstance(result, SendResult)
        assert result.message_id == "msg-42"
        assert result.from_agent_id == "agent-a"
        assert result.to_agent_id == "agent-b"
        assert result.session_id == "sess-explicit"

    async def test_send_message_resolves_session_from_project(
        self, fx: _OrchestratorFixture
    ) -> None:
        """When session_id=None, resolves session from project's active sessions."""
        # Arrange
        from_agent = _make_agent(id="agent-a")
        to_agent = _make_agent(id="agent-b")
        fx.agent_registry.get_by_id = AsyncMock(side_effect=[from_agent, to_agent])
        fx.session_registry.get_session_for_conversation = AsyncMock(
            return_value=AgentSession(
                agent_id="agent-a",
                conversation_id="sender-sess",
                project_id="proj-1",
            )
        )
        fx.session_registry.get_sessions = AsyncMock(
            return_value=[
                AgentSession(
                    agent_id="other-agent",
                    conversation_id="other-sess",
                    project_id="proj-1",
                ),
                AgentSession(
                    agent_id="agent-b",
                    conversation_id="older-sess",
                    project_id="proj-1",
                    registered_at="2026-01-01T00:00:00+00:00",
                ),
                AgentSession(
                    agent_id="agent-b",
                    conversation_id="resolved-sess",
                    project_id="proj-1",
                    registered_at="2026-01-02T00:00:00+00:00",
                ),
            ]
        )
        fx.message_bus.send_message = AsyncMock(return_value="msg-99")

        # Act
        result = await fx.orchestrator.send_message(
            from_agent_id="agent-a",
            to_agent_id="agent-b",
            message="hello",
            sender_session_id="sender-sess",
            project_id="proj-1",
        )

        # Assert
        assert result.session_id == "resolved-sess"
        send_kwargs = fx.message_bus.send_message.call_args.kwargs
        assert send_kwargs["session_id"] == "resolved-sess"

    async def test_send_message_resolves_sender_name_with_tenant_context(
        self, fx: _OrchestratorFixture
    ) -> None:
        """Legacy callers can still resolve a sender by tenant-scoped agent name."""
        from_agent = _make_agent(id="agent-a", name="sender-name")
        to_agent = _make_agent(id="agent-b")
        fx.agent_registry.get_by_id = AsyncMock(side_effect=[None, to_agent])
        fx.agent_registry.get_by_name = AsyncMock(return_value=from_agent)
        fx.session_registry.get_session_for_conversation = AsyncMock(
            side_effect=[
                AgentSession(
                    agent_id="agent-b",
                    conversation_id="sess-explicit",
                    project_id="proj-1",
                ),
                AgentSession(
                    agent_id="agent-a",
                    conversation_id="sender-sess",
                    project_id="proj-1",
                ),
            ]
        )
        fx.message_bus.send_message = AsyncMock(return_value="msg-42")

        result = await fx.orchestrator.send_message(
            from_agent_id="sender-name",
            to_agent_id="agent-b",
            message="hello",
            session_id="sess-explicit",
            sender_session_id="sender-sess",
            project_id="proj-1",
            tenant_id="tenant-1",
        )

        assert result.from_agent_id == "agent-a"
        fx.agent_registry.get_by_name.assert_awaited_once_with("tenant-1", "sender-name")

    async def test_send_message_accepts_legacy_name_based_allowlist(
        self, fx: _OrchestratorFixture
    ) -> None:
        """Targets remain compatible with historical name-based allowlists during migration."""
        from_agent = _make_agent(id="agent-a", name="sender-name")
        to_agent = _make_agent(id="agent-b")
        to_agent.accepts_messages_from = Mock(
            side_effect=lambda sender_ref: sender_ref == "sender-name"
        )
        fx.agent_registry.get_by_id = AsyncMock(side_effect=[from_agent, to_agent])
        fx.session_registry.get_session_for_conversation = AsyncMock(
            side_effect=[
                AgentSession(
                    agent_id="agent-b",
                    conversation_id="sess-explicit",
                    project_id="proj-1",
                ),
                AgentSession(
                    agent_id="agent-a",
                    conversation_id="sender-sess",
                    project_id="proj-1",
                ),
            ]
        )
        fx.message_bus.send_message = AsyncMock(return_value="msg-42")

        result = await fx.orchestrator.send_message(
            from_agent_id="agent-a",
            to_agent_id="agent-b",
            message="hello",
            session_id="sess-explicit",
            sender_session_id="sender-sess",
            project_id="proj-1",
        )

        assert result.message_id == "msg-42"

    async def test_send_message_explicit_session_must_belong_to_target_agent(
        self, fx: _OrchestratorFixture
    ) -> None:
        """Explicit session IDs are validated against the target agent binding."""
        from_agent = _make_agent(id="agent-a")
        to_agent = _make_agent(id="agent-b")
        fx.agent_registry.get_by_id = AsyncMock(side_effect=[from_agent, to_agent])
        fx.session_registry.get_session_for_conversation = AsyncMock(
            return_value=AgentSession(
                agent_id="other-agent",
                conversation_id="sess-explicit",
                project_id="proj-1",
            )
        )

        with pytest.raises(
            ValueError,
            match="Session sess-explicit does not belong to target agent agent-b",
        ):
            await fx.orchestrator.send_message(
                from_agent_id="agent-a",
                to_agent_id="agent-b",
                message="hello",
                session_id="sess-explicit",
                project_id="proj-1",
            )

    async def test_send_message_sender_session_must_belong_to_sender_agent(
        self, fx: _OrchestratorFixture
    ) -> None:
        """Sender sessions are bound to the resolved sender identity."""
        from_agent = _make_agent(id="agent-a", name="sender-name")
        to_agent = _make_agent(id="agent-b")
        fx.agent_registry.get_by_id = AsyncMock(side_effect=[from_agent, to_agent])
        fx.session_registry.get_session_for_conversation = AsyncMock(
            side_effect=[
                AgentSession(
                    agent_id="agent-b",
                    conversation_id="sess-explicit",
                    project_id="proj-1",
                ),
                AgentSession(
                    agent_id="other-agent",
                    conversation_id="sender-sess",
                    project_id="proj-1",
                ),
            ]
        )

        with pytest.raises(
            ValueError,
            match="Sender session sender-sess does not belong to sender agent agent-a",
        ):
            await fx.orchestrator.send_message(
                from_agent_id="agent-a",
                to_agent_id="agent-b",
                message="hello",
                session_id="sess-explicit",
                sender_session_id="sender-sess",
                project_id="proj-1",
            )

    async def test_send_message_unknown_sender_raises_value_error(
        self, fx: _OrchestratorFixture
    ) -> None:
        """Unknown senders are rejected instead of being treated as trusted roots."""
        fx.agent_registry.get_by_id = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="Sender agent not found: unknown-sender"):
            await fx.orchestrator.send_message(
                from_agent_id="unknown-sender",
                to_agent_id="agent-b",
                message="hello",
                session_id="sess-1",
            )

    async def test_send_message_sender_with_a2a_disabled_raises_value_error(
        self, fx: _OrchestratorFixture
    ) -> None:
        """Senders must explicitly opt in to agent-to-agent messaging."""
        from_agent = _make_agent(id="agent-a", agent_to_agent_enabled=False)
        fx.agent_registry.get_by_id = AsyncMock(return_value=from_agent)

        with pytest.raises(
            ValueError, match="Sender agent-to-agent messaging is disabled: agent-a"
        ):
            await fx.orchestrator.send_message(
                from_agent_id="agent-a",
                to_agent_id="agent-b",
                message="hello",
                session_id="sess-1",
            )

    async def test_send_message_disabled_sender_raises_value_error(
        self, fx: _OrchestratorFixture
    ) -> None:
        """Disabled senders cannot initiate agent-to-agent messages."""
        from_agent = _make_agent(id="agent-a", enabled=False)
        fx.agent_registry.get_by_id = AsyncMock(return_value=from_agent)

        with pytest.raises(ValueError, match="Sender agent is disabled: agent-a"):
            await fx.orchestrator.send_message(
                from_agent_id="agent-a",
                to_agent_id="agent-b",
                message="hello",
                session_id="sess-1",
            )

    async def test_send_message_target_not_found_raises_value_error(
        self, fx: _OrchestratorFixture
    ) -> None:
        """Target not found raises ValueError."""
        # Arrange
        from_agent = _make_agent(id="agent-a")
        fx.agent_registry.get_by_id = AsyncMock(side_effect=[from_agent, None])

        # Act / Assert
        with pytest.raises(ValueError, match="Target agent not found: unknown-target"):
            await fx.orchestrator.send_message(
                from_agent_id="agent-a",
                to_agent_id="unknown-target",
                message="hello",
                session_id="sess-1",
            )

    async def test_send_message_sender_in_target_default_allowlist_passes_after_pr1(
        self, fx: _OrchestratorFixture
    ) -> None:
        """After PR1, a sender present in the default allowlist (builtin:sisyphus)
        passes the target's allowlist check even though allowlist is None.

        Regression check: Router/Tool now set the default allowlist when enabling
        A2A without an explicit list. The orchestrator must still honour that default
        allowlist when evaluating accepts_messages_from."""
        from_agent = _make_agent(id="builtin:sisyphus")
        to_agent = _make_agent(
            id="agent-b",
            agent_to_agent_enabled=True,
            agent_to_agent_allowlist=None,  # None = use default allowlist
        )
        # accepts_messages_from for a BUILTIN source with allowlist=None returns True
        # (trusted-open policy), so this should not raise.
        fx.agent_registry.get_by_id = AsyncMock(side_effect=[from_agent, to_agent])
        fx.session_registry.get_session_for_conversation = AsyncMock(
            side_effect=[
                # 1. Resolve target session: session_id="sess-to-b" belongs to agent-b
                AgentSession(agent_id="agent-b", conversation_id="sess-to-b", project_id="proj-1"),
                # 2. Resolve sender session: sender_session_id="sess-from-sender" belongs to builtin:sisyphus
                AgentSession(agent_id="builtin:sisyphus", conversation_id="sess-from-sender", project_id="proj-1"),
            ],
        )

        result = await fx.orchestrator.send_message(
            from_agent_id="builtin:sisyphus",
            to_agent_id="agent-b",
            message="hello",
            session_id="sess-to-b",
            sender_session_id="sess-from-sender",
            project_id="proj-1",
        )

        assert result.from_agent_id == "builtin:sisyphus"
        assert result.to_agent_id == "agent-b"

    async def test_send_message_target_allowlist_rejects_sender(
        self, fx: _OrchestratorFixture
    ) -> None:
        """Target that rejects sender via accepts_messages_from raises ValueError."""
        # Arrange
        from_agent = _make_agent(id="agent-a")
        to_agent = _make_agent(id="agent-b")
        to_agent.accepts_messages_from = Mock(return_value=False)
        fx.agent_registry.get_by_id = AsyncMock(side_effect=[from_agent, to_agent])

        # Act / Assert
        with pytest.raises(
            ValueError,
            match="does not accept messages from sender",
        ):
            await fx.orchestrator.send_message(
                from_agent_id="agent-a",
                to_agent_id="agent-b",
                message="hello",
                session_id="sess-1",
            )

    async def test_send_message_no_session_and_no_project_raises_value_error(
        self, fx: _OrchestratorFixture
    ) -> None:
        """Both session_id and project_id are None raises ValueError."""
        # Arrange
        from_agent = _make_agent(id="agent-a")
        to_agent = _make_agent(id="agent-b")
        fx.agent_registry.get_by_id = AsyncMock(side_effect=[from_agent, to_agent])

        # Act / Assert
        with pytest.raises(ValueError, match="Either session_id or project_id must be provided"):
            await fx.orchestrator.send_message(
                from_agent_id="agent-a",
                to_agent_id="agent-b",
                message="hello",
            )

    async def test_send_message_no_matching_session_raises_value_error(
        self, fx: _OrchestratorFixture
    ) -> None:
        """No matching session for the target agent raises ValueError."""
        # Arrange
        from_agent = _make_agent(id="agent-a")
        to_agent = _make_agent(id="agent-b")
        fx.agent_registry.get_by_id = AsyncMock(side_effect=[from_agent, to_agent])
        fx.session_registry.get_sessions = AsyncMock(
            return_value=[
                AgentSession(
                    agent_id="other-agent",
                    conversation_id="other-sess",
                    project_id="proj-1",
                ),
            ]
        )

        # Act / Assert
        with pytest.raises(
            ValueError,
            match="No active session found for agent agent-b in project proj-1",
        ):
            await fx.orchestrator.send_message(
                from_agent_id="agent-a",
                to_agent_id="agent-b",
                message="hello",
                project_id="proj-1",
            )

    async def test_send_message_target_with_a2a_disabled_raises_value_error(
        self, fx: _OrchestratorFixture
    ) -> None:
        """Targets must also opt in before accepting direct agent messages."""
        from_agent = _make_agent(id="agent-a")
        to_agent = _make_agent(id="agent-b", agent_to_agent_enabled=False)
        fx.agent_registry.get_by_id = AsyncMock(side_effect=[from_agent, to_agent])

        with pytest.raises(
            ValueError, match="Target agent-to-agent messaging is disabled: agent-b"
        ):
            await fx.orchestrator.send_message(
                from_agent_id="agent-a",
                to_agent_id="agent-b",
                message="hello",
                session_id="sess-1",
            )


# ---------------------------------------------------------------------------
# stop_agent
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStopAgent:
    """Test suite for AgentOrchestrator.stop_agent."""

    async def test_stop_agent_cascade_true_calls_cascade_stop(
        self, fx: _OrchestratorFixture
    ) -> None:
        """With cascade=True, calls spawn_manager.cascade_stop and cleans up each session."""
        # Arrange
        fx.spawn_manager.cascade_stop = AsyncMock(return_value=["sess-1", "sess-2"])
        fx.message_bus.cleanup_session = AsyncMock()

        # Act
        result = await fx.orchestrator.stop_agent(
            agent_id="agent-1",
            session_id="sess-root",
            project_id="proj-1",
            cascade=True,
            conversation_id="conv-1",
        )

        # Assert
        assert result == ["sess-1", "sess-2"]
        fx.spawn_manager.cascade_stop.assert_called_once()
        cascade_kwargs = fx.spawn_manager.cascade_stop.call_args.kwargs
        assert cascade_kwargs["session_id"] == "sess-root"
        assert cascade_kwargs["project_id"] == "proj-1"
        assert cascade_kwargs["conversation_id"] == "conv-1"
        assert callable(cascade_kwargs["on_stop"])

    async def test_stop_agent_cascade_true_cleanup_called_for_each(
        self, fx: _OrchestratorFixture
    ) -> None:
        """After cascade returns 3 IDs, cleanup_session is called 3 times."""
        # Arrange
        fx.spawn_manager.cascade_stop = AsyncMock(return_value=["s1", "s2", "s3"])
        fx.message_bus.cleanup_session = AsyncMock()

        # Act
        await fx.orchestrator.stop_agent(
            agent_id="agent-1",
            session_id="sess-root",
            project_id="proj-1",
        )

        # Assert
        assert fx.message_bus.cleanup_session.call_count == 3
        fx.message_bus.cleanup_session.assert_has_calls(
            [call("s1"), call("s2"), call("s3")], any_order=False
        )

    async def test_stop_agent_cascade_false_calls_update_status_and_unregister(
        self, fx: _OrchestratorFixture
    ) -> None:
        """With cascade=False, calls update_status and unregister, returns [session_id]."""
        # Arrange
        fx.spawn_manager.update_status = AsyncMock()
        fx.session_registry.unregister = AsyncMock()
        fx.message_bus.cleanup_session = AsyncMock()

        # Act
        result = await fx.orchestrator.stop_agent(
            agent_id="agent-1",
            session_id="sess-1",
            project_id="proj-1",
            cascade=False,
            conversation_id="conv-1",
        )

        # Assert
        assert result == ["sess-1"]
        fx.spawn_manager.update_status.assert_called_once_with(
            child_session_id="sess-1",
            new_status="stopped",
            conversation_id="conv-1",
        )
        fx.session_registry.unregister.assert_called_once_with(
            conversation_id="sess-1",
            project_id="proj-1",
        )
        fx.message_bus.cleanup_session.assert_called_once_with("sess-1")


# ---------------------------------------------------------------------------
# list_agents
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListAgents:
    """Test suite for AgentOrchestrator.list_agents."""

    async def test_list_agents_discoverable_only_filters_non_discoverable(
        self, fx: _OrchestratorFixture
    ) -> None:
        """With discoverable_only=True, filters out non-discoverable agents."""
        # Arrange
        agent_a = _make_agent(discoverable=True)
        agent_b = _make_agent(discoverable=False)
        agent_c = _make_agent(discoverable=True)
        fx.agent_registry.list_by_project = AsyncMock(return_value=[agent_a, agent_b, agent_c])

        # Act
        result = await fx.orchestrator.list_agents(
            project_id="proj-1",
            tenant_id="tenant-1",
            discoverable_only=True,
        )

        # Assert
        assert len(result) == 2
        assert agent_a in result
        assert agent_c in result
        assert agent_b not in result

    async def test_list_agents_discoverable_false_returns_all(
        self, fx: _OrchestratorFixture
    ) -> None:
        """With discoverable_only=False, returns all agents."""
        # Arrange
        agent_a = _make_agent(discoverable=True)
        agent_b = _make_agent(discoverable=False)
        agent_c = _make_agent(discoverable=True)
        fx.agent_registry.list_by_project = AsyncMock(return_value=[agent_a, agent_b, agent_c])

        # Act
        result = await fx.orchestrator.list_agents(
            project_id="proj-1",
            tenant_id="tenant-1",
            discoverable_only=False,
        )

        # Assert
        assert len(result) == 3

    async def test_list_agents_empty_list_returns_empty(self, fx: _OrchestratorFixture) -> None:
        """When registry returns empty list, returns empty list."""
        # Arrange
        fx.agent_registry.list_by_project = AsyncMock(return_value=[])

        # Act
        result = await fx.orchestrator.list_agents(
            project_id="proj-1",
            tenant_id="tenant-1",
        )

        # Assert
        assert result == []


# ---------------------------------------------------------------------------
# get_agent_sessions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetAgentSessions:
    """Test suite for AgentOrchestrator.get_agent_sessions."""

    async def test_get_agent_sessions_include_children_calls_find_descendants(
        self, fx: _OrchestratorFixture
    ) -> None:
        """With include_children=True, calls find_descendants with include_self=True."""
        # Arrange
        expected = [_make_spawn_record()]
        fx.spawn_manager.find_descendants = AsyncMock(return_value=expected)

        # Act
        result = await fx.orchestrator.get_agent_sessions(
            parent_session_id="ps-1",
            include_children=True,
        )

        # Assert
        assert result is expected
        fx.spawn_manager.find_descendants.assert_called_once_with("ps-1", include_self=True)

    async def test_get_agent_sessions_exclude_children_calls_find_children(
        self, fx: _OrchestratorFixture
    ) -> None:
        """With include_children=False, calls find_children."""
        # Arrange
        expected = [_make_spawn_record()]
        fx.spawn_manager.find_children = AsyncMock(return_value=expected)

        # Act
        result = await fx.orchestrator.get_agent_sessions(
            parent_session_id="ps-1",
            include_children=False,
        )

        # Assert
        assert result is expected
        fx.spawn_manager.find_children.assert_called_once_with("ps-1")


# ---------------------------------------------------------------------------
# get_agent_history
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetAgentHistory:
    """Test suite for AgentOrchestrator.get_agent_history."""

    async def test_get_agent_history_default_limit(self, fx: _OrchestratorFixture) -> None:
        """Default limit=50 is passed to get_message_history."""
        # Arrange
        expected = [Mock()]
        fx.message_bus.get_message_history = AsyncMock(return_value=expected)

        # Act
        result = await fx.orchestrator.get_agent_history(session_id="sess-1")

        # Assert
        assert result is expected
        fx.message_bus.get_message_history.assert_called_once_with(session_id="sess-1", limit=50)

    async def test_get_agent_history_custom_limit(self, fx: _OrchestratorFixture) -> None:
        """Custom limit is forwarded to get_message_history."""
        # Arrange
        expected = [Mock(), Mock()]
        fx.message_bus.get_message_history = AsyncMock(return_value=expected)

        # Act
        result = await fx.orchestrator.get_agent_history(session_id="sess-1", limit=10)

        # Assert
        assert result is expected
        fx.message_bus.get_message_history.assert_called_once_with(session_id="sess-1", limit=10)
