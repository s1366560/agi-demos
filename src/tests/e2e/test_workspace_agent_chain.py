from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.application.services.workspace_mention_router import WorkspaceMentionRouter
from src.application.services.workspace_message_service import WorkspaceMessageService
from src.domain.model.workspace.workspace_message import MessageSenderType, WorkspaceMessage


def _make_agent(agent_id: str, display_name: str) -> MagicMock:
    agent = MagicMock()
    agent.agent_id = agent_id
    agent.display_name = display_name
    return agent


def _make_message(mentions: list[str], content: str) -> WorkspaceMessage:
    return WorkspaceMessage(
        workspace_id="ws-1",
        sender_id="user-1",
        sender_type=MessageSenderType.HUMAN,
        content=content,
        mentions=mentions,
        metadata={"sender_name": "User"},
    )


def _build_test_env(agents: list[MagicMock], agent_responses: dict[str, list[str]]):
    mock_db = AsyncMock()

    @asynccontextmanager
    async def db_session_factory() -> AsyncIterator[AsyncMock]:
        yield mock_db

    agent_repo = AsyncMock()
    agent_repo.find_by_workspace.return_value = agents

    member_repo = AsyncMock()
    member_repo.find_by_workspace.return_value = []

    message_repo = AsyncMock()

    async def mock_save(msg: WorkspaceMessage) -> WorkspaceMessage:
        if not getattr(msg, "id", None):
            msg.id = "msg-mock"
        # Record the message to help assertions
        mock_save.messages.append(msg)
        return msg

    mock_save.messages = []
    message_repo.save.side_effect = mock_save

    conversation_repo = AsyncMock()
    conversation_repo.find_by_id.return_value = MagicMock()  # Mock existing conversation

    message_service = WorkspaceMessageService(
        message_repo=message_repo,
        member_repo=member_repo,
        agent_repo=agent_repo,
    )

    def message_service_factory(db: Any, event_publisher: Any = None) -> WorkspaceMessageService:
        return message_service

    # State for tracking agent calls
    agent_service = MagicMock()
    agent_service.call_counts = {}

    async def stream_chat_v2(**kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        agent_id = kwargs.get("agent_id")
        if agent_id not in agent_service.call_counts:
            agent_service.call_counts[agent_id] = 0

        idx = agent_service.call_counts[agent_id]
        agent_service.call_counts[agent_id] += 1

        responses = agent_responses.get(agent_id, [])
        content = responses[idx] if idx < len(responses) else "Default response"

        yield {"type": "complete", "data": {"content": content}}

    agent_service.stream_chat_v2 = stream_chat_v2

    router = WorkspaceMentionRouter(
        agent_repo_factory=lambda db: agent_repo,
        agent_service_factory=lambda db, llm: agent_service,
        message_service_factory=message_service_factory,
        conversation_repo_factory=lambda db: conversation_repo,
        db_session_factory=db_session_factory,
    )

    return router, message_repo, agent_service, mock_save.messages


@pytest.mark.integration
class TestWorkspaceAgentChain:
    @patch("src.configuration.factories.create_llm_client", new_callable=AsyncMock)
    async def test_single_mention_triggers_agent(self, mock_create_llm: AsyncMock) -> None:
        mock_create_llm.return_value = MagicMock()
        agents = [_make_agent("agent-oracle", "oracle")]
        agent_responses = {"agent-oracle": ["Hello from oracle!"]}

        router, _message_repo, agent_service, messages = _build_test_env(agents, agent_responses)
        msg = _make_message(mentions=["agent-oracle"], content="@oracle help")

        await router.route_mentions(
            workspace_id="ws-1", message=msg, tenant_id="t-1", project_id="p-1", user_id="u-1"
        )

        assert agent_service.call_counts.get("agent-oracle", 0) == 1
        assert len(messages) == 1
        assert messages[0].content == "Hello from oracle!"
        assert messages[0].sender_id == "agent-oracle"

    @patch("src.configuration.factories.create_llm_client", new_callable=AsyncMock)
    async def test_chain_depth_limit_respected(self, mock_create_llm: AsyncMock) -> None:
        mock_create_llm.return_value = MagicMock()
        agents = [_make_agent("a-1", "oracle"), _make_agent("a-2", "explorer")]

        # oracle calls explorer, explorer calls oracle, creating an infinite loop
        agent_responses = {
            "a-1": [
                "@explorer please analyze",
                "@explorer please analyze again",
                "@explorer stop",
                "@explorer stop",
            ],
            "a-2": ["@oracle done", "@oracle done again", "@oracle done", "@oracle done"],
        }

        router, _message_repo, agent_service, messages = _build_test_env(agents, agent_responses)
        msg = _make_message(mentions=["a-1"], content="@oracle start chain")

        await router.route_mentions(
            workspace_id="ws-1", message=msg, tenant_id="t-1", project_id="p-1", user_id="u-1"
        )

        # Depth limit is 3.
        # Initial call depth 0: oracle responds "@explorer please analyze"
        # Chained call depth 1: explorer responds "@oracle done"
        # Chained call depth 2: oracle responds "@explorer please analyze again"
        # Chained call depth 3: explorer responds "@oracle done again"
        # Max depth reached, chain stops. Total 4 agent calls.
        total_calls = sum(agent_service.call_counts.values())
        assert total_calls == 4
        assert len(messages) == 4

    @patch("src.configuration.factories.create_llm_client", new_callable=AsyncMock)
    async def test_mention_nonexistent_agent_ignored(self, mock_create_llm: AsyncMock) -> None:
        mock_create_llm.return_value = MagicMock()
        agents = [_make_agent("a-1", "oracle")]
        agent_responses = {}

        router, _message_repo, agent_service, messages = _build_test_env(agents, agent_responses)

        # Mentions are resolved before this is called in actual flow, but here we pass the unresolvable ID
        msg = _make_message(mentions=["nonexistent"], content="@nonexistent you there?")

        await router.route_mentions(
            workspace_id="ws-1", message=msg, tenant_id="t-1", project_id="p-1", user_id="u-1"
        )

        assert len(agent_service.call_counts) == 0
        assert len(messages) == 0

    @patch("src.configuration.factories.create_llm_client", new_callable=AsyncMock)
    async def test_multiple_mentions_in_single_message(self, mock_create_llm: AsyncMock) -> None:
        mock_create_llm.return_value = MagicMock()
        agents = [_make_agent("a-1", "oracle"), _make_agent("a-2", "explorer")]
        agent_responses = {"a-1": ["Oracle response"], "a-2": ["Explorer response"]}

        router, _message_repo, agent_service, messages = _build_test_env(agents, agent_responses)
        msg = _make_message(mentions=["a-1", "a-2"], content="@oracle @explorer go!")

        await router.route_mentions(
            workspace_id="ws-1", message=msg, tenant_id="t-1", project_id="p-1", user_id="u-1"
        )

        assert agent_service.call_counts.get("a-1", 0) == 1
        assert agent_service.call_counts.get("a-2", 0) == 1
        assert len(messages) == 2
        assert {m.sender_id for m in messages} == {"a-1", "a-2"}
