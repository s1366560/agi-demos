"""Tests for DefaultMessageRouter -- Phase 3 Wave 5.

Verifies that DefaultMessageRouter correctly implements MessageRouterPort
with scope-priority binding resolution and regex filter_pattern matching.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.domain.model.agent.binding_scope import BindingScope
from src.domain.model.agent.conversation.message import Message, MessageRole, MessageType
from src.domain.model.agent.message_binding import MessageBinding
from src.domain.model.agent.routing_context import RoutingContext
from src.domain.ports.agent.message_router_port import MessageRouterPort
from src.infrastructure.agent.routing.default_message_router import DefaultMessageRouter

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_binding_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.save = AsyncMock()
    repo.delete = AsyncMock()
    repo.find_by_scope = AsyncMock(return_value=[])
    return repo


@pytest.fixture()
def router(mock_binding_repo: AsyncMock) -> DefaultMessageRouter:
    return DefaultMessageRouter(binding_repo=mock_binding_repo)


@pytest.fixture()
def sample_message() -> Message:
    return Message(
        conversation_id="conv-1",
        role=MessageRole.USER,
        content="Hello, world!",
        message_type=MessageType.TEXT,
    )


@pytest.fixture()
def sample_context() -> RoutingContext:
    return RoutingContext(
        conversation_id="conv-1",
        project_id="proj-1",
        tenant_id="t-1",
        channel_type="web",
    )


def _make_binding(
    agent_id: str = "agent-1",
    scope: BindingScope = BindingScope.DEFAULT,
    scope_id: str = "default",
    priority: int = 0,
    filter_pattern: str | None = None,
    is_active: bool = True,
) -> MessageBinding:
    return MessageBinding(
        agent_id=agent_id,
        scope=scope,
        scope_id=scope_id,
        priority=priority,
        filter_pattern=filter_pattern,
        is_active=is_active,
    )


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProtocolConformance:
    """DefaultMessageRouter must satisfy MessageRouterPort protocol."""

    async def test_is_instance_of_message_router_port(self, router: DefaultMessageRouter) -> None:
        assert isinstance(router, MessageRouterPort)


# ---------------------------------------------------------------------------
# resolve_agent -- basic scope-priority ordering
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveAgentScopePriority:
    """resolve_agent should prefer higher-priority (lower numeric) scopes."""

    async def test_no_bindings_returns_none(
        self,
        router: DefaultMessageRouter,
        sample_message: Message,
        sample_context: RoutingContext,
    ) -> None:
        result = await router.resolve_agent(sample_message, sample_context)
        assert result is None

    async def test_single_matching_binding(
        self,
        router: DefaultMessageRouter,
        sample_message: Message,
        sample_context: RoutingContext,
    ) -> None:
        binding = _make_binding(
            agent_id="agent-default",
            scope=BindingScope.DEFAULT,
            scope_id="default",
        )
        await router.register_binding(binding)

        result = await router.resolve_agent(sample_message, sample_context)
        assert result == "agent-default"

    async def test_conversation_scope_wins_over_project(
        self,
        router: DefaultMessageRouter,
        sample_message: Message,
        sample_context: RoutingContext,
    ) -> None:
        project_binding = _make_binding(
            agent_id="agent-project",
            scope=BindingScope.PROJECT,
            scope_id="proj-1",
        )
        conv_binding = _make_binding(
            agent_id="agent-conv",
            scope=BindingScope.CONVERSATION,
            scope_id="conv-1",
        )
        await router.register_binding(project_binding)
        await router.register_binding(conv_binding)

        result = await router.resolve_agent(sample_message, sample_context)
        assert result == "agent-conv"

    async def test_tenant_scope_loses_to_project(
        self,
        router: DefaultMessageRouter,
        sample_message: Message,
        sample_context: RoutingContext,
    ) -> None:
        tenant_binding = _make_binding(
            agent_id="agent-tenant",
            scope=BindingScope.TENANT,
            scope_id="t-1",
        )
        project_binding = _make_binding(
            agent_id="agent-project",
            scope=BindingScope.PROJECT,
            scope_id="proj-1",
        )
        await router.register_binding(tenant_binding)
        await router.register_binding(project_binding)

        result = await router.resolve_agent(sample_message, sample_context)
        assert result == "agent-project"

    async def test_priority_tie_breaker_within_same_scope(
        self,
        router: DefaultMessageRouter,
        sample_message: Message,
        sample_context: RoutingContext,
    ) -> None:
        low_priority = _make_binding(
            agent_id="agent-low",
            scope=BindingScope.PROJECT,
            scope_id="proj-1",
            priority=10,
        )
        high_priority = _make_binding(
            agent_id="agent-high",
            scope=BindingScope.PROJECT,
            scope_id="proj-1",
            priority=1,
        )
        await router.register_binding(low_priority)
        await router.register_binding(high_priority)

        result = await router.resolve_agent(sample_message, sample_context)
        assert result == "agent-high"


# ---------------------------------------------------------------------------
# resolve_agent -- scope_id matching
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveAgentScopeIdMatching:
    """resolve_agent must match scope_id against the relevant context field."""

    async def test_conversation_scope_only_matches_same_conversation(
        self,
        router: DefaultMessageRouter,
        sample_message: Message,
        sample_context: RoutingContext,
    ) -> None:
        wrong_conv = _make_binding(
            agent_id="agent-wrong",
            scope=BindingScope.CONVERSATION,
            scope_id="conv-OTHER",
        )
        await router.register_binding(wrong_conv)

        result = await router.resolve_agent(sample_message, sample_context)
        assert result is None

    async def test_project_scope_matches_project_id(
        self,
        router: DefaultMessageRouter,
        sample_message: Message,
        sample_context: RoutingContext,
    ) -> None:
        binding = _make_binding(
            agent_id="agent-proj",
            scope=BindingScope.PROJECT,
            scope_id="proj-1",
        )
        await router.register_binding(binding)

        result = await router.resolve_agent(sample_message, sample_context)
        assert result == "agent-proj"

    async def test_tenant_scope_matches_tenant_id(
        self,
        router: DefaultMessageRouter,
        sample_message: Message,
        sample_context: RoutingContext,
    ) -> None:
        binding = _make_binding(
            agent_id="agent-t",
            scope=BindingScope.TENANT,
            scope_id="t-1",
        )
        await router.register_binding(binding)

        result = await router.resolve_agent(sample_message, sample_context)
        assert result == "agent-t"

    async def test_default_scope_always_matches(
        self,
        router: DefaultMessageRouter,
        sample_message: Message,
        sample_context: RoutingContext,
    ) -> None:
        binding = _make_binding(
            agent_id="agent-def",
            scope=BindingScope.DEFAULT,
            scope_id="any-value",
        )
        await router.register_binding(binding)

        result = await router.resolve_agent(sample_message, sample_context)
        assert result == "agent-def"


# ---------------------------------------------------------------------------
# resolve_agent -- regex filter_pattern
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveAgentFilterPattern:
    """resolve_agent should apply regex filter_pattern against message content."""

    async def test_matching_pattern_returns_agent(
        self,
        router: DefaultMessageRouter,
        sample_context: RoutingContext,
    ) -> None:
        binding = _make_binding(
            agent_id="agent-hello",
            scope=BindingScope.DEFAULT,
            scope_id="default",
            filter_pattern=r"Hello.*",
        )
        await router.register_binding(binding)

        msg = Message(
            conversation_id="conv-1",
            role=MessageRole.USER,
            content="Hello, world!",
            message_type=MessageType.TEXT,
        )
        result = await router.resolve_agent(msg, sample_context)
        assert result == "agent-hello"

    async def test_non_matching_pattern_skips_binding(
        self,
        router: DefaultMessageRouter,
        sample_context: RoutingContext,
    ) -> None:
        binding = _make_binding(
            agent_id="agent-bye",
            scope=BindingScope.DEFAULT,
            scope_id="default",
            filter_pattern=r"Goodbye.*",
        )
        await router.register_binding(binding)

        msg = Message(
            conversation_id="conv-1",
            role=MessageRole.USER,
            content="Hello, world!",
            message_type=MessageType.TEXT,
        )
        result = await router.resolve_agent(msg, sample_context)
        assert result is None

    async def test_none_filter_pattern_matches_everything(
        self,
        router: DefaultMessageRouter,
        sample_message: Message,
        sample_context: RoutingContext,
    ) -> None:
        binding = _make_binding(
            agent_id="agent-catch-all",
            scope=BindingScope.DEFAULT,
            scope_id="default",
            filter_pattern=None,
        )
        await router.register_binding(binding)

        result = await router.resolve_agent(sample_message, sample_context)
        assert result == "agent-catch-all"

    async def test_pattern_with_higher_scope_wins_over_lower_scope_catch_all(
        self,
        router: DefaultMessageRouter,
        sample_context: RoutingContext,
    ) -> None:
        catch_all = _make_binding(
            agent_id="agent-default",
            scope=BindingScope.DEFAULT,
            scope_id="default",
            filter_pattern=None,
        )
        specific = _make_binding(
            agent_id="agent-conv",
            scope=BindingScope.CONVERSATION,
            scope_id="conv-1",
            filter_pattern=r"Hello.*",
        )
        await router.register_binding(catch_all)
        await router.register_binding(specific)

        msg = Message(
            conversation_id="conv-1",
            role=MessageRole.USER,
            content="Hello there!",
            message_type=MessageType.TEXT,
        )
        result = await router.resolve_agent(msg, sample_context)
        assert result == "agent-conv"

    async def test_invalid_regex_is_treated_as_non_matching(
        self,
        router: DefaultMessageRouter,
        sample_message: Message,
        sample_context: RoutingContext,
    ) -> None:
        binding = _make_binding(
            agent_id="agent-bad-regex",
            scope=BindingScope.DEFAULT,
            scope_id="default",
            filter_pattern=r"[invalid",
        )
        await router.register_binding(binding)

        result = await router.resolve_agent(sample_message, sample_context)
        assert result is None


# ---------------------------------------------------------------------------
# resolve_agent -- inactive bindings
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveAgentInactiveBindings:
    """Inactive bindings should be skipped during resolution."""

    async def test_inactive_binding_is_skipped(
        self,
        router: DefaultMessageRouter,
        sample_message: Message,
        sample_context: RoutingContext,
    ) -> None:
        inactive = _make_binding(
            agent_id="agent-inactive",
            scope=BindingScope.DEFAULT,
            scope_id="default",
            is_active=False,
        )
        await router.register_binding(inactive)

        result = await router.resolve_agent(sample_message, sample_context)
        assert result is None

    async def test_active_binding_after_inactive_is_used(
        self,
        router: DefaultMessageRouter,
        sample_message: Message,
        sample_context: RoutingContext,
    ) -> None:
        inactive = _make_binding(
            agent_id="agent-inactive",
            scope=BindingScope.DEFAULT,
            scope_id="default",
            is_active=False,
        )
        active = _make_binding(
            agent_id="agent-active",
            scope=BindingScope.DEFAULT,
            scope_id="default",
        )
        await router.register_binding(inactive)
        await router.register_binding(active)

        result = await router.resolve_agent(sample_message, sample_context)
        assert result == "agent-active"


# ---------------------------------------------------------------------------
# register_binding / remove_binding
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRegisterAndRemoveBinding:
    """register_binding and remove_binding manage the in-memory binding store."""

    async def test_register_binding_persists_via_repo(
        self,
        router: DefaultMessageRouter,
        mock_binding_repo: AsyncMock,
    ) -> None:
        binding = _make_binding(agent_id="agent-1")
        await router.register_binding(binding)
        mock_binding_repo.save.assert_awaited_once_with(binding)

    async def test_remove_binding_deletes_via_repo(
        self,
        router: DefaultMessageRouter,
        mock_binding_repo: AsyncMock,
    ) -> None:
        binding = _make_binding(agent_id="agent-1")
        await router.register_binding(binding)

        await router.remove_binding(binding.id)
        mock_binding_repo.delete.assert_awaited_once_with(binding.id)

    async def test_remove_nonexistent_binding_still_calls_repo(
        self,
        router: DefaultMessageRouter,
        mock_binding_repo: AsyncMock,
    ) -> None:
        await router.remove_binding("nonexistent-id")
        mock_binding_repo.delete.assert_awaited_once_with("nonexistent-id")

    async def test_removed_binding_no_longer_resolves(
        self,
        router: DefaultMessageRouter,
        sample_message: Message,
        sample_context: RoutingContext,
    ) -> None:
        binding = _make_binding(
            agent_id="agent-temp",
            scope=BindingScope.DEFAULT,
            scope_id="default",
        )
        await router.register_binding(binding)
        assert await router.resolve_agent(sample_message, sample_context) == "agent-temp"

        await router.remove_binding(binding.id)
        assert await router.resolve_agent(sample_message, sample_context) is None


# ---------------------------------------------------------------------------
# Full priority chain
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFullPriorityChain:
    """End-to-end test across the full scope priority hierarchy."""

    async def test_full_scope_order(
        self,
        router: DefaultMessageRouter,
        sample_context: RoutingContext,
    ) -> None:
        scopes_and_ids = [
            (BindingScope.DEFAULT, "default"),
            (BindingScope.TENANT, "t-1"),
            (BindingScope.PROJECT, "proj-1"),
            (BindingScope.CONVERSATION, "conv-1"),
        ]
        for scope, scope_id in scopes_and_ids:
            await router.register_binding(
                _make_binding(
                    agent_id=f"agent-{scope.value}",
                    scope=scope,
                    scope_id=scope_id,
                )
            )

        msg = Message(
            conversation_id="conv-1",
            role=MessageRole.USER,
            content="test",
            message_type=MessageType.TEXT,
        )
        result = await router.resolve_agent(msg, sample_context)
        assert result == "agent-conversation"
