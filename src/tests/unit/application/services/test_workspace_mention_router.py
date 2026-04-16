from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.application.services.workspace_mention_router import (
    WorkspaceMentionRouter,
)
from src.domain.model.workspace.workspace_message import (
    MessageSenderType,
    WorkspaceMessage,
)


def _make_agent(agent_id: str, display_name: str = "TestAgent") -> MagicMock:
    agent = MagicMock()
    agent.agent_id = agent_id
    agent.display_name = display_name
    return agent


def _make_message(
    mentions: list[str] | None = None,
    content: str = "Hello @agent",
    sender_name: str = "Alice",
) -> WorkspaceMessage:
    return WorkspaceMessage(
        workspace_id="ws-1",
        sender_id="user-1",
        sender_type=MessageSenderType.HUMAN,
        content=content,
        mentions=mentions or [],
        metadata={"sender_name": sender_name},
    )


def _mock_db_session_factory() -> tuple[Any, AsyncMock]:
    mock_db = AsyncMock()

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncMock]:
        yield mock_db

    return factory, mock_db


def _build_router(
    agents: list[MagicMock] | None = None,
    stream_events: list[dict[str, Any]] | None = None,
    existing_conversation: Any = None,
) -> tuple[WorkspaceMentionRouter, dict[str, AsyncMock]]:
    session_factory, mock_db = _mock_db_session_factory()

    agent_repo = AsyncMock()
    agent_repo.find_by_workspace = AsyncMock(return_value=agents or [])

    conversation_repo = AsyncMock()
    conversation_repo.find_by_id = AsyncMock(return_value=existing_conversation)
    conversation_repo.save = AsyncMock()

    message_service = AsyncMock()

    message_service.send_message = AsyncMock(
        side_effect=lambda **kwargs: _make_message(  # type: ignore[arg-type]
            content=kwargs.get("content", "")
        )
    )

    events = stream_events or [{"type": "complete", "data": {"content": "Agent response"}}]

    async def _stream_events(**_kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        for e in events:
            yield e

    agent_service = MagicMock()
    agent_service.stream_chat_v2 = _stream_events

    router = WorkspaceMentionRouter(
        agent_repo_factory=lambda db: agent_repo,  # type: ignore[arg-type]
        agent_service_factory=lambda db, llm: agent_service,  # type: ignore[arg-type]
        message_service_factory=lambda db, publisher: message_service,  # type: ignore[arg-type]
        conversation_repo_factory=lambda db: conversation_repo,  # type: ignore[arg-type]
        db_session_factory=session_factory,
    )

    mocks: dict[str, AsyncMock] = {
        "agent_repo": agent_repo,
        "conversation_repo": conversation_repo,
        "message_service": message_service,
        "agent_service": agent_service,
        "mock_db": mock_db,
    }
    return router, mocks


@pytest.mark.unit
class TestRouterNoMentions:
    async def test_no_mentions_returns_early(self) -> None:
        router, mocks = _build_router()
        msg = _make_message(mentions=[])
        await router.route_mentions(
            workspace_id="ws-1", message=msg, tenant_id="t-1", project_id="p-1", user_id="user-1"
        )
        mocks["agent_repo"].find_by_workspace.assert_not_called()

    async def test_mentions_not_matching_agents_returns_early(self) -> None:
        agent = _make_agent("agent-99", "Other")
        router, mocks = _build_router(agents=[agent])
        msg = _make_message(mentions=["agent-nonexistent"])
        await router.route_mentions(
            workspace_id="ws-1", message=msg, tenant_id="t-1", project_id="p-1", user_id="user-1"
        )
        mocks["conversation_repo"].find_by_id.assert_not_called()


@pytest.mark.unit
class TestRouterTriggerAgent:
    @patch(
        "src.configuration.factories.create_llm_client",
        new_callable=AsyncMock,
    )
    async def test_trigger_agent_creates_conversation_and_posts_response(
        self, mock_create_llm: AsyncMock
    ) -> None:
        mock_create_llm.return_value = MagicMock()
        agent = _make_agent("agent-1", "Bot")
        router, mocks = _build_router(agents=[agent], existing_conversation=None)
        msg = _make_message(mentions=["agent-1"])

        await router.route_mentions(
            workspace_id="ws-1", message=msg, tenant_id="t-1", project_id="p-1", user_id="user-1"
        )

        mocks["conversation_repo"].save.assert_called_once()
        mocks["message_service"].send_message.assert_called_once()
        call_kwargs = mocks["message_service"].send_message.call_args.kwargs
        assert call_kwargs["sender_id"] == "agent-1"
        assert call_kwargs["sender_type"] == MessageSenderType.AGENT
        assert call_kwargs["content"] == "Agent response"

    @patch(
        "src.configuration.factories.create_llm_client",
        new_callable=AsyncMock,
    )
    async def test_trigger_agent_reuses_existing_conversation(
        self, mock_create_llm: AsyncMock
    ) -> None:
        mock_create_llm.return_value = MagicMock()
        existing_conv = MagicMock()
        agent = _make_agent("agent-1", "Bot")
        router, mocks = _build_router(agents=[agent], existing_conversation=existing_conv)
        msg = _make_message(mentions=["agent-1"])

        await router.route_mentions(
            workspace_id="ws-1", message=msg, tenant_id="t-1", project_id="p-1", user_id="user-1"
        )

        mocks["conversation_repo"].save.assert_not_called()

    @patch(
        "src.configuration.factories.create_llm_client",
        new_callable=AsyncMock,
    )
    async def test_trigger_agent_handles_error_event(self, mock_create_llm: AsyncMock) -> None:
        mock_create_llm.return_value = MagicMock()
        agent = _make_agent("agent-1", "Bot")
        error_events = [{"type": "error", "data": {"message": "LLM timeout"}}]
        router, mocks = _build_router(
            agents=[agent], stream_events=error_events, existing_conversation=MagicMock()
        )
        msg = _make_message(mentions=["agent-1"])

        await router.route_mentions(
            workspace_id="ws-1", message=msg, tenant_id="t-1", project_id="p-1", user_id="user-1"
        )

        mocks["message_service"].send_message.assert_called_once()
        call_kwargs = mocks["message_service"].send_message.call_args.kwargs
        assert "[Error]" in call_kwargs["content"]
        assert "LLM timeout" in call_kwargs["content"]

    @patch(
        "src.configuration.factories.create_llm_client",
        new_callable=AsyncMock,
    )
    async def test_trigger_agent_exception_posts_error(self, mock_create_llm: AsyncMock) -> None:
        mock_create_llm.side_effect = RuntimeError("LLM init failed")
        agent = _make_agent("agent-1", "Bot")
        router, mocks = _build_router(agents=[agent], existing_conversation=MagicMock())
        msg = _make_message(mentions=["agent-1"])

        await router.route_mentions(
            workspace_id="ws-1", message=msg, tenant_id="t-1", project_id="p-1", user_id="user-1"
        )

        mocks["message_service"].send_message.assert_called_once()
        call_kwargs = mocks["message_service"].send_message.call_args.kwargs
        assert "[Error]" in call_kwargs["content"]

    @patch(
        "src.configuration.factories.create_llm_client",
        new_callable=AsyncMock,
    )
    async def test_trigger_agent_uses_scoped_objective_conversation_and_activation_text(
        self, mock_create_llm: AsyncMock
    ) -> None:
        from src.infrastructure.agent.workspace.workspace_goal_runtime import (
            should_activate_workspace_authority,
        )

        mock_create_llm.return_value = MagicMock()
        agent = _make_agent("agent-1", "Leader Agent")
        router, mocks = _build_router(agents=[agent], existing_conversation=None)
        captured: dict[str, Any] = {}

        async def _capturing_stream(**kwargs: Any) -> AsyncIterator[dict[str, Any]]:
            captured.update(kwargs)
            yield {"type": "complete", "data": {"content": "Agent response"}}

        mocks["agent_service"].stream_chat_v2 = _capturing_stream
        msg = _make_message(
            mentions=["agent-1"],
            content='@"Leader Agent" 中央黑板新增目标：Ship browser test objective。'
            "请将这个 objective 转化为 workspace task，拆解并自主执行，直到完成。 "
            "Please decompose this objective into child tasks, execute it, and complete it.",
        )
        msg.metadata["conversation_scope"] = "objective:obj-1"

        await router.route_mentions(
            workspace_id="ws-1", message=msg, tenant_id="t-1", project_id="p-1", user_id="user-1"
        )

        assert captured["conversation_id"] == WorkspaceMentionRouter.workspace_conversation_id(
            "ws-1",
            "agent-1",
            conversation_scope="objective:obj-1",
        )
        assert should_activate_workspace_authority(captured["user_message"]) is True


@pytest.mark.unit
class TestFireAndForget:
    async def test_fire_and_forget_creates_background_task(self) -> None:
        router, _ = _build_router()
        msg = _make_message(mentions=[])

        router.fire_and_forget(workspace_id="ws-1", message=msg, tenant_id="t-1", project_id="p-1", user_id="user-1")

        # Give the background task time to complete (no-op since no mentions)
        await asyncio.sleep(0.05)


@pytest.mark.unit
class TestWorkspaceConversationId:
    def test_deterministic_id(self) -> None:
        id1 = WorkspaceMentionRouter.workspace_conversation_id("ws-1", "agent-1")
        id2 = WorkspaceMentionRouter.workspace_conversation_id("ws-1", "agent-1")
        assert id1 == id2
        uuid.UUID(id1)

    def test_different_agents_get_different_ids(self) -> None:
        id1 = WorkspaceMentionRouter.workspace_conversation_id("ws-1", "agent-1")
        id2 = WorkspaceMentionRouter.workspace_conversation_id("ws-1", "agent-2")
        assert id1 != id2

    def test_conversation_scope_changes_workspace_conversation_id(self) -> None:
        base = WorkspaceMentionRouter.workspace_conversation_id("ws-1", "agent-1")
        scoped = WorkspaceMentionRouter.workspace_conversation_id(
            "ws-1",
            "agent-1",
            conversation_scope="objective:obj-1",
        )
        assert base != scoped
        uuid.UUID(scoped)


@pytest.mark.unit
class TestMultipleAgentMentions:
    @patch(
        "src.configuration.factories.create_llm_client",
        new_callable=AsyncMock,
    )
    async def test_triggers_multiple_agents_sequentially(self, mock_create_llm: AsyncMock) -> None:
        mock_create_llm.return_value = MagicMock()
        agent1 = _make_agent("agent-1", "Bot1")
        agent2 = _make_agent("agent-2", "Bot2")
        router, mocks = _build_router(agents=[agent1, agent2], existing_conversation=MagicMock())
        msg = _make_message(mentions=["agent-1", "agent-2"])

        await router.route_mentions(
            workspace_id="ws-1", message=msg, tenant_id="t-1", project_id="p-1", user_id="user-1"
        )

        assert mocks["message_service"].send_message.call_count == 2
