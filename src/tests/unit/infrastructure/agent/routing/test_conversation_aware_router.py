"""Tests for ConversationAwareRouter — Track B P2-3 phase-2.

Verifies coordinator-first, mode-aware routing while delegating binding-based
fallback to the inner MessageRouterPort.

Agent First: the router must never inspect message content; these tests assert
exactly that by proving an inner router call is skipped when a structural rule
(mention / focused / coordinator) picks a winner.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.domain.model.agent.conversation.conversation import Conversation, ConversationStatus
from src.domain.model.agent.conversation.conversation_mode import ConversationMode
from src.domain.model.agent.conversation.message import Message, MessageRole, MessageType
from src.domain.model.agent.routing_context import RoutingContext
from src.infrastructure.agent.routing.conversation_aware_router import (
    ConversationAwareRouter,
)


def _ctx(conv_id: str = "conv-1") -> RoutingContext:
    return RoutingContext(conversation_id=conv_id, project_id="p1", tenant_id="t1")


def _msg(content: str = "anything", mentions: list[str] | None = None) -> Message:
    return Message(
        conversation_id="conv-1",
        role=MessageRole.USER,
        content=content,
        message_type=MessageType.TEXT,
        mentions=mentions or [],
    )


def _conv(
    *,
    mode: ConversationMode | None,
    participants: list[str],
    coordinator: str | None = None,
    focused: str | None = None,
) -> Conversation:
    return Conversation(
        id="conv-1",
        user_id="u1",
        project_id="p1",
        tenant_id="t1",
        title="t",
        status=ConversationStatus.ACTIVE,
        participant_agents=list(participants),
        conversation_mode=mode,
        coordinator_agent_id=coordinator,
        focused_agent_id=focused,
    )


@pytest.fixture()
def inner_router() -> AsyncMock:
    r = AsyncMock()
    r.resolve_agent = AsyncMock(return_value="binding-agent")
    r.register_binding = AsyncMock()
    r.remove_binding = AsyncMock()
    return r


@pytest.fixture()
def conv_repo() -> AsyncMock:
    r = AsyncMock()
    r.find_by_id = AsyncMock()
    return r


async def test_legacy_conversation_missing_delegates_to_inner(
    inner_router: AsyncMock, conv_repo: AsyncMock
) -> None:
    conv_repo.find_by_id.return_value = None
    router = ConversationAwareRouter(inner=inner_router, conversation_repository=conv_repo)

    agent = await router.resolve_agent(_msg(), _ctx())

    assert agent == "binding-agent"
    inner_router.resolve_agent.assert_awaited_once()


async def test_single_agent_mode_delegates_to_inner(
    inner_router: AsyncMock, conv_repo: AsyncMock
) -> None:
    conv_repo.find_by_id.return_value = _conv(
        mode=ConversationMode.SINGLE_AGENT, participants=["a1"]
    )
    router = ConversationAwareRouter(inner=inner_router, conversation_repository=conv_repo)

    agent = await router.resolve_agent(_msg(), _ctx())

    assert agent == "binding-agent"
    inner_router.resolve_agent.assert_awaited_once()


async def test_explicit_mention_short_circuits(
    inner_router: AsyncMock, conv_repo: AsyncMock
) -> None:
    conv_repo.find_by_id.return_value = _conv(
        mode=ConversationMode.MULTI_AGENT_SHARED,
        participants=["coord", "worker-x", "worker-y"],
        coordinator="coord",
    )
    router = ConversationAwareRouter(inner=inner_router, conversation_repository=conv_repo)

    agent = await router.resolve_agent(_msg(mentions=["worker-x"]), _ctx())

    assert agent == "worker-x"
    inner_router.resolve_agent.assert_not_called()


async def test_mention_not_in_roster_falls_through_to_coordinator(
    inner_router: AsyncMock, conv_repo: AsyncMock
) -> None:
    conv_repo.find_by_id.return_value = _conv(
        mode=ConversationMode.MULTI_AGENT_SHARED,
        participants=["coord", "worker-x"],
        coordinator="coord",
    )
    router = ConversationAwareRouter(inner=inner_router, conversation_repository=conv_repo)

    agent = await router.resolve_agent(_msg(mentions=["stranger"]), _ctx())

    assert agent == "coord"
    inner_router.resolve_agent.assert_not_called()


async def test_isolated_mode_prefers_focused_agent(
    inner_router: AsyncMock, conv_repo: AsyncMock
) -> None:
    conv_repo.find_by_id.return_value = _conv(
        mode=ConversationMode.MULTI_AGENT_ISOLATED,
        participants=["coord", "focused-one", "other"],
        coordinator="coord",
        focused="focused-one",
    )
    router = ConversationAwareRouter(inner=inner_router, conversation_repository=conv_repo)

    agent = await router.resolve_agent(_msg(), _ctx())

    assert agent == "focused-one"
    inner_router.resolve_agent.assert_not_called()


async def test_isolated_mode_falls_back_to_coordinator_when_no_focus(
    inner_router: AsyncMock, conv_repo: AsyncMock
) -> None:
    conv_repo.find_by_id.return_value = _conv(
        mode=ConversationMode.MULTI_AGENT_ISOLATED,
        participants=["coord", "worker-x"],
        coordinator="coord",
    )
    router = ConversationAwareRouter(inner=inner_router, conversation_repository=conv_repo)

    agent = await router.resolve_agent(_msg(), _ctx())

    assert agent == "coord"


async def test_shared_mode_routes_to_coordinator(
    inner_router: AsyncMock, conv_repo: AsyncMock
) -> None:
    conv_repo.find_by_id.return_value = _conv(
        mode=ConversationMode.MULTI_AGENT_SHARED,
        participants=["coord", "worker-x"],
        coordinator="coord",
    )
    router = ConversationAwareRouter(inner=inner_router, conversation_repository=conv_repo)

    agent = await router.resolve_agent(_msg(), _ctx())

    assert agent == "coord"
    inner_router.resolve_agent.assert_not_called()


async def test_shared_mode_without_coordinator_falls_through(
    inner_router: AsyncMock, conv_repo: AsyncMock
) -> None:
    conv_repo.find_by_id.return_value = _conv(
        mode=ConversationMode.MULTI_AGENT_SHARED,
        participants=["a", "b"],
        coordinator=None,
    )
    router = ConversationAwareRouter(inner=inner_router, conversation_repository=conv_repo)

    agent = await router.resolve_agent(_msg(), _ctx())

    assert agent == "binding-agent"
    inner_router.resolve_agent.assert_awaited_once()


async def test_autonomous_mode_requires_coordinator_in_roster(
    inner_router: AsyncMock, conv_repo: AsyncMock
) -> None:
    conv_repo.find_by_id.return_value = _conv(
        mode=ConversationMode.AUTONOMOUS,
        participants=["coord", "helper"],
        coordinator="coord",
    )
    router = ConversationAwareRouter(inner=inner_router, conversation_repository=conv_repo)

    agent = await router.resolve_agent(_msg(), _ctx())

    assert agent == "coord"


async def test_autonomous_mode_with_stale_coordinator_falls_through(
    inner_router: AsyncMock, conv_repo: AsyncMock
) -> None:
    conv_repo.find_by_id.return_value = _conv(
        mode=ConversationMode.AUTONOMOUS,
        participants=["helper"],
        coordinator="left-the-room",
    )
    router = ConversationAwareRouter(inner=inner_router, conversation_repository=conv_repo)

    agent = await router.resolve_agent(_msg(), _ctx())

    assert agent == "binding-agent"
    inner_router.resolve_agent.assert_awaited_once()


async def test_register_binding_delegates(inner_router: AsyncMock, conv_repo: AsyncMock) -> None:
    router = ConversationAwareRouter(inner=inner_router, conversation_repository=conv_repo)
    sentinel = object()
    await router.register_binding(sentinel)  # type: ignore[arg-type]
    inner_router.register_binding.assert_awaited_once_with(sentinel)


async def test_remove_binding_delegates(inner_router: AsyncMock, conv_repo: AsyncMock) -> None:
    router = ConversationAwareRouter(inner=inner_router, conversation_repository=conv_repo)
    await router.remove_binding("b-1")
    inner_router.remove_binding.assert_awaited_once_with("b-1")
