"""Unit tests for AgentService, focusing on authorization."""

import logging
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from src.application.services.agent_service import AgentService
from src.domain.model.agent import Conversation, ConversationStatus
from src.domain.model.agent.agent_execution_event import (
    USER_MESSAGE,  # Timeline-specific event type values
    AgentExecutionEvent,
)


class MockAgentService(AgentService):
    """Concrete implementation of AgentService for testing."""

    async def get_available_tools(self):
        """Return available tools."""
        return []

    async def get_conversation_context(self, conversation_id: str):
        """Get conversation context."""
        return []


class TestAgentServiceAuthorization:
    """Test authorization in AgentService methods."""

    @pytest.fixture
    def mock_conversation_repo(self):
        """Create a mock conversation repository."""
        repo = AsyncMock()
        return repo

    @pytest.fixture
    def mock_agent_execution_event_repo(self):
        """Create a mock agent execution event repository."""
        repo = AsyncMock()
        return repo

    @pytest.fixture
    def mock_execution_repo(self):
        """Create a mock execution repository."""
        repo = AsyncMock()
        return repo

    @pytest.fixture
    def mock_graph_service(self):
        """Create a mock graph service."""
        service = AsyncMock()
        return service

    @pytest.fixture
    def mock_llm(self):
        """Create a mock LLM."""
        llm = AsyncMock()
        return llm

    @pytest.fixture
    def mock_neo4j_client(self):
        """Create a mock Neo4j client."""
        client = AsyncMock()
        return client

    @pytest.fixture
    def agent_service(
        self,
        mock_conversation_repo,
        mock_agent_execution_event_repo,
        mock_execution_repo,
        mock_graph_service,
        mock_llm,
        mock_neo4j_client,
    ):
        """Create an AgentService with mocked dependencies."""
        return MockAgentService(
            conversation_repository=mock_conversation_repo,
            execution_repository=mock_execution_repo,
            graph_service=mock_graph_service,
            llm=mock_llm,
            neo4j_client=mock_neo4j_client,
            agent_execution_event_repository=mock_agent_execution_event_repo,
        )

    @pytest.fixture
    def sample_conversation(self):
        """Create a sample conversation."""
        return Conversation(
            id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            user_id="user-1",
            title="Test Conversation",
            status=ConversationStatus.ACTIVE,
        )

    @pytest.mark.asyncio
    async def test_create_conversation_logs_do_not_include_identifiers_or_title(
        self,
        agent_service,
        mock_conversation_repo,
        caplog,
    ):
        """Conversation creation logs must not expose IDs or title content."""
        secret_project_id = "project-secret-create-123"
        secret_user_id = "user-secret-create-456"
        secret_tenant_id = "tenant-secret-create-789"
        secret_title = "Customer Confidential Incident"
        caplog.set_level(
            logging.INFO,
            logger="src.application.services.agent.conversation_manager",
        )

        conversation = await agent_service.create_conversation(
            project_id=secret_project_id,
            user_id=secret_user_id,
            tenant_id=secret_tenant_id,
            title=secret_title,
            agent_config={"model": "private-model"},
        )

        mock_conversation_repo.save.assert_called_once()
        assert conversation.id not in caplog.text
        assert secret_project_id not in caplog.text
        assert secret_user_id not in caplog.text
        assert secret_tenant_id not in caplog.text
        assert secret_title not in caplog.text
        assert "title_len=30" in caplog.text
        assert "agent_config_present=True" in caplog.text

    @pytest.mark.asyncio
    async def test_get_conversation_owner_can_access(
        self, agent_service, mock_conversation_repo, sample_conversation
    ):
        """Test that conversation owner can access their conversation."""
        mock_conversation_repo.find_by_id.return_value = sample_conversation

        result = await agent_service.get_conversation(
            conversation_id="conv-1",
            project_id="proj-1",
            user_id="user-1",
        )

        assert result is not None
        assert result.id == "conv-1"
        mock_conversation_repo.find_by_id.assert_called_once_with("conv-1")

    @pytest.mark.asyncio
    async def test_get_conversation_unauthorized_user_cannot_access(
        self, agent_service, mock_conversation_repo, sample_conversation
    ):
        """Test that unauthorized user cannot access another user's conversation."""
        mock_conversation_repo.find_by_id.return_value = sample_conversation

        result = await agent_service.get_conversation(
            conversation_id="conv-1",
            project_id="proj-1",  # Correct project
            user_id="user-2",  # Different user
        )

        # Should return None for unauthorized access
        assert result is None

    @pytest.mark.asyncio
    async def test_get_conversation_unauthorized_logs_do_not_include_identifiers(
        self,
        agent_service,
        mock_conversation_repo,
        sample_conversation,
        caplog,
    ):
        """Unauthorized conversation access logs must not expose scoped IDs."""
        secret_conversation_id = "conversation-secret-unauthorized"
        secret_project_id = "project-secret-unauthorized"
        secret_user_id = "user-secret-unauthorized"
        sample_conversation.id = secret_conversation_id
        sample_conversation.project_id = secret_project_id
        sample_conversation.user_id = "owner-secret-user"
        mock_conversation_repo.find_by_id.return_value = sample_conversation
        caplog.set_level(
            logging.WARNING,
            logger="src.application.services.agent.conversation_manager",
        )

        result = await agent_service.get_conversation(
            conversation_id=secret_conversation_id,
            project_id=secret_project_id,
            user_id=secret_user_id,
        )

        assert result is None
        assert secret_conversation_id not in caplog.text
        assert secret_project_id not in caplog.text
        assert secret_user_id not in caplog.text
        assert "Unauthorized access attempt to conversation" in caplog.text

    @pytest.mark.asyncio
    async def test_get_conversation_wrong_project_cannot_access(
        self, agent_service, mock_conversation_repo, sample_conversation
    ):
        """Test that user from another project cannot access conversation."""
        mock_conversation_repo.find_by_id.return_value = sample_conversation

        result = await agent_service.get_conversation(
            conversation_id="conv-1",
            project_id="proj-2",  # Different project
            user_id="user-1",  # Correct user
        )

        # Should return None for unauthorized access
        assert result is None

    @pytest.mark.asyncio
    async def test_get_conversation_nonexistent_returns_none(
        self, agent_service, mock_conversation_repo
    ):
        """Test that requesting a non-existent conversation returns None."""
        mock_conversation_repo.find_by_id.return_value = None

        result = await agent_service.get_conversation(
            conversation_id="nonexistent",
            project_id="proj-1",
            user_id="user-1",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_conversation_owner_can_delete(
        self,
        agent_service,
        mock_conversation_repo,
        mock_execution_repo,
        sample_conversation,
    ):
        """Test that conversation owner can delete their conversation."""
        mock_conversation_repo.find_by_id.return_value = sample_conversation

        result = await agent_service.delete_conversation(
            conversation_id="conv-1",
            project_id="proj-1",
            user_id="user-1",
        )

        assert result is True
        mock_execution_repo.delete_by_conversation.assert_called_once_with("conv-1")
        mock_conversation_repo.delete.assert_called_once_with("conv-1")

    @pytest.mark.asyncio
    async def test_delete_conversation_success_logs_do_not_include_identifiers(
        self,
        agent_service,
        mock_conversation_repo,
        sample_conversation,
        caplog,
    ):
        """Successful conversation delete logs must not expose conversation IDs."""
        secret_conversation_id = "conversation-secret-delete"
        secret_project_id = "project-secret-delete"
        secret_user_id = "user-secret-delete"
        sample_conversation.id = secret_conversation_id
        sample_conversation.project_id = secret_project_id
        sample_conversation.user_id = secret_user_id
        mock_conversation_repo.find_by_id.return_value = sample_conversation
        caplog.set_level(
            logging.INFO,
            logger="src.application.services.agent.conversation_manager",
        )

        result = await agent_service.delete_conversation(
            conversation_id=secret_conversation_id,
            project_id=secret_project_id,
            user_id=secret_user_id,
        )

        assert result is True
        assert secret_conversation_id not in caplog.text
        assert secret_project_id not in caplog.text
        assert secret_user_id not in caplog.text
        assert "Deleted conversation" in caplog.text

    @pytest.mark.asyncio
    async def test_delete_conversation_unauthorized_user_cannot_delete(
        self,
        agent_service,
        mock_conversation_repo,
        mock_execution_repo,
        sample_conversation,
    ):
        """Test that unauthorized user cannot delete another user's conversation."""
        mock_conversation_repo.find_by_id.return_value = sample_conversation

        result = await agent_service.delete_conversation(
            conversation_id="conv-1",
            project_id="proj-1",
            user_id="user-2",  # Different user
        )

        assert result is False
        # Should not call delete methods
        mock_execution_repo.delete_by_conversation.assert_not_called()
        mock_conversation_repo.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_conversation_unauthorized_logs_do_not_include_identifiers(
        self,
        agent_service,
        mock_conversation_repo,
        sample_conversation,
        caplog,
    ):
        """Unauthorized conversation delete logs must not expose scoped IDs."""
        secret_conversation_id = "conversation-secret-delete-denied"
        secret_project_id = "project-secret-delete-denied"
        secret_user_id = "user-secret-delete-denied"
        sample_conversation.id = secret_conversation_id
        sample_conversation.project_id = secret_project_id
        sample_conversation.user_id = "owner-secret-delete"
        mock_conversation_repo.find_by_id.return_value = sample_conversation
        caplog.set_level(
            logging.WARNING,
            logger="src.application.services.agent.conversation_manager",
        )

        result = await agent_service.delete_conversation(
            conversation_id=secret_conversation_id,
            project_id=secret_project_id,
            user_id=secret_user_id,
        )

        assert result is False
        assert secret_conversation_id not in caplog.text
        assert secret_project_id not in caplog.text
        assert secret_user_id not in caplog.text
        assert "project_match=True" in caplog.text
        assert "user_match=False" in caplog.text

    @pytest.mark.asyncio
    async def test_delete_conversation_missing_logs_do_not_include_identifier(
        self,
        agent_service,
        mock_conversation_repo,
        caplog,
    ):
        """Missing conversation delete logs must not expose the requested ID."""
        secret_conversation_id = "conversation-secret-delete-missing"
        mock_conversation_repo.find_by_id.return_value = None
        caplog.set_level(
            logging.WARNING,
            logger="src.application.services.agent.conversation_manager",
        )

        result = await agent_service.delete_conversation(
            conversation_id=secret_conversation_id,
            project_id="project-secret-delete-missing",
            user_id="user-secret-delete-missing",
        )

        assert result is False
        assert secret_conversation_id not in caplog.text
        assert "conversation_exists=False" in caplog.text

    @pytest.mark.asyncio
    async def test_get_conversation_messages_owner_can_access(
        self,
        agent_service,
        mock_conversation_repo,
        mock_agent_execution_event_repo,
        sample_conversation,
    ):
        """Test that conversation owner can get their messages."""
        mock_conversation_repo.find_by_id.return_value = sample_conversation
        mock_agent_execution_event_repo.get_message_events.return_value = [
            AgentExecutionEvent(
                id="event-1",
                conversation_id="conv-1",
                message_id="",
                event_type=USER_MESSAGE,  # Timeline-specific event type
                event_data={"role": "user", "content": "Hello"},
                event_time_us=1000000,
                event_counter=0,
                created_at=datetime.now(),
            )
        ]

        result = await agent_service.get_conversation_messages(
            conversation_id="conv-1",
            project_id="proj-1",
            user_id="user-1",
            limit=100,
        )

        assert len(result) == 1
        assert result[0].id == "event-1"
        mock_agent_execution_event_repo.get_message_events.assert_called_once_with(
            conversation_id="conv-1", limit=100
        )

    @pytest.mark.asyncio
    async def test_get_conversation_messages_unauthorized_returns_empty(
        self,
        agent_service,
        mock_conversation_repo,
        mock_agent_execution_event_repo,
        sample_conversation,
    ):
        """Test that unauthorized user cannot get conversation messages."""
        mock_conversation_repo.find_by_id.return_value = sample_conversation

        result = await agent_service.get_conversation_messages(
            conversation_id="conv-1",
            project_id="proj-1",
            user_id="user-2",  # Different user
            limit=100,
        )

        # Should return empty list for unauthorized access
        assert result == []
        # Should not call event repository
        mock_agent_execution_event_repo.get_message_events.assert_not_called()


class TestAgentServiceStreamChatAuthorization:
    """Test authorization in AgentService.stream_chat."""

    @pytest.fixture
    def mock_repos(self):
        """Create mock repositories."""
        return {
            "conversation": AsyncMock(),
            "agent_execution_event": AsyncMock(),
            "execution": AsyncMock(),
        }

    @pytest.fixture
    def mock_dependencies(self):
        """Create mock dependencies."""
        return {
            "graph_service": AsyncMock(),
            "llm": AsyncMock(),
            "neo4j_client": AsyncMock(),
        }

    @pytest.fixture
    def agent_service(self, mock_repos, mock_dependencies):
        """Create an AgentService with mocked dependencies."""
        return MockAgentService(
            conversation_repository=mock_repos["conversation"],
            execution_repository=mock_repos["execution"],
            graph_service=mock_dependencies["graph_service"],
            llm=mock_dependencies["llm"],
            neo4j_client=mock_dependencies["neo4j_client"],
            agent_execution_event_repository=mock_repos["agent_execution_event"],
        )

    @pytest.fixture
    def sample_conversation(self):
        """Create a sample conversation."""
        return Conversation(
            id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            user_id="user-1",
            title="Test Conversation",
            status=ConversationStatus.ACTIVE,
        )

    @pytest.mark.asyncio
    async def test_stream_chat_unauthorized_user_gets_error(
        self, agent_service, mock_repos, sample_conversation
    ):
        """Test that unauthorized user gets error when trying to chat."""
        mock_repos["conversation"].find_by_id.return_value = sample_conversation

        events = []
        async for event in agent_service.stream_chat_v2(
            conversation_id="conv-1",
            user_message="Hello",
            project_id="proj-1",
            user_id="user-2",  # Different user
            tenant_id="tenant-1",
        ):
            events.append(event)

        # Should get an error event
        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert "permission" in events[0]["data"]["message"].lower()
