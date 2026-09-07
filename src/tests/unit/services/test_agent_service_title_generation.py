"""Manual conversation-title update tests.

Automatic title generation is owned by the optional protocol-v2 lifecycle module and is
covered by ``test_conversation_title_lifecycle_v2.py``.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import pytest

from src.application.services.agent_service import AgentService
from src.domain.model.agent import Conversation, ConversationStatus

pytestmark = pytest.mark.unit


class MockAgentService(AgentService):
    """Concrete AgentService used to exercise the retained manual CRUD surface."""

    async def get_available_tools(self) -> list[object]:
        return []

    async def get_conversation_context(self, conversation_id: str) -> list[object]:
        return []


@pytest.fixture
def mock_conversation_repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def agent_service(mock_conversation_repo: AsyncMock) -> MockAgentService:
    return MockAgentService(
        conversation_repository=mock_conversation_repo,
        execution_repository=AsyncMock(),
        llm=AsyncMock(),
        agent_execution_event_repository=AsyncMock(),
    )


@pytest.fixture
def sample_conversation() -> Conversation:
    return Conversation(
        id="conv-1",
        project_id="proj-1",
        tenant_id="tenant-1",
        user_id="user-1",
        title="New Conversation",
        status=ConversationStatus.ACTIVE,
    )


async def test_update_title_updates_conversation(
    agent_service: MockAgentService,
    mock_conversation_repo: AsyncMock,
    sample_conversation: Conversation,
) -> None:
    mock_conversation_repo.find_by_id.return_value = sample_conversation

    result = await agent_service.update_conversation_title(
        conversation_id="conv-1",
        project_id="proj-1",
        user_id="user-1",
        title="Updated Title",
    )

    assert result is sample_conversation
    assert result.title == "Updated Title"
    mock_conversation_repo.save_and_commit.assert_awaited_once_with(sample_conversation)


async def test_update_title_logs_do_not_include_title_content(
    agent_service: MockAgentService,
    mock_conversation_repo: AsyncMock,
    sample_conversation: Conversation,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_title = "Customer secret escalation alpha-456"
    mock_conversation_repo.find_by_id.return_value = sample_conversation
    caplog.set_level(
        logging.INFO,
        logger="src.application.services.agent.conversation_manager",
    )

    result = await agent_service.update_conversation_title(
        conversation_id="conv-1",
        project_id="proj-1",
        user_id="user-1",
        title=secret_title,
    )

    assert result is sample_conversation
    assert result.title == secret_title
    assert secret_title not in caplog.text


async def test_update_title_success_logs_do_not_include_identifiers(
    agent_service: MockAgentService,
    mock_conversation_repo: AsyncMock,
    sample_conversation: Conversation,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_conversation_id = "conversation-secret-title"
    secret_project_id = "project-secret-title"
    secret_user_id = "user-secret-title"
    sample_conversation.id = secret_conversation_id
    sample_conversation.project_id = secret_project_id
    sample_conversation.user_id = secret_user_id
    mock_conversation_repo.find_by_id.return_value = sample_conversation
    caplog.set_level(
        logging.INFO,
        logger="src.application.services.agent.conversation_manager",
    )

    result = await agent_service.update_conversation_title(
        conversation_id=secret_conversation_id,
        project_id=secret_project_id,
        user_id=secret_user_id,
        title="New private title",
    )

    assert result is sample_conversation
    assert secret_conversation_id not in caplog.text
    assert secret_project_id not in caplog.text
    assert secret_user_id not in caplog.text
    assert "title_len=17" in caplog.text
    assert "project_match=True" in caplog.text
    assert "user_match=True" in caplog.text


async def test_update_title_unauthorized_returns_none(
    agent_service: MockAgentService,
    mock_conversation_repo: AsyncMock,
    sample_conversation: Conversation,
) -> None:
    mock_conversation_repo.find_by_id.return_value = sample_conversation

    result = await agent_service.update_conversation_title(
        conversation_id="conv-1",
        project_id="proj-1",
        user_id="user-2",
        title="Updated Title",
    )

    assert result is None
    mock_conversation_repo.save_and_commit.assert_not_awaited()


async def test_update_title_unauthorized_logs_do_not_include_identifiers(
    agent_service: MockAgentService,
    mock_conversation_repo: AsyncMock,
    sample_conversation: Conversation,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_conversation_id = "conversation-secret-title-denied"
    secret_project_id = "project-secret-title-denied"
    secret_user_id = "user-secret-title-denied"
    sample_conversation.id = secret_conversation_id
    sample_conversation.project_id = secret_project_id
    sample_conversation.user_id = "owner-secret-title"
    mock_conversation_repo.find_by_id.return_value = sample_conversation
    caplog.set_level(
        logging.WARNING,
        logger="src.application.services.agent.conversation_manager",
    )

    result = await agent_service.update_conversation_title(
        conversation_id=secret_conversation_id,
        project_id=secret_project_id,
        user_id=secret_user_id,
        title="Denied private title",
    )

    assert result is None
    assert secret_conversation_id not in caplog.text
    assert secret_project_id not in caplog.text
    assert secret_user_id not in caplog.text
    assert "project_match=True" in caplog.text
    assert "user_match=False" in caplog.text


async def test_update_title_missing_logs_do_not_include_identifier(
    agent_service: MockAgentService,
    mock_conversation_repo: AsyncMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_conversation_id = "conversation-secret-title-missing"
    mock_conversation_repo.find_by_id.return_value = None
    caplog.set_level(
        logging.WARNING,
        logger="src.application.services.agent.conversation_manager",
    )

    result = await agent_service.update_conversation_title(
        conversation_id=secret_conversation_id,
        project_id="project-secret-title-missing",
        user_id="user-secret-title-missing",
        title="Missing private title",
    )

    assert result is None
    assert secret_conversation_id not in caplog.text
    assert "conversation_exists=False" in caplog.text
