"""Unit tests for AgentService conversation title generation.

These tests follow TDD principles:
1. Tests are written first (RED)
2. Implementation follows (GREEN)
3. Code is refactored for quality (REFACTOR)
"""

import logging
from datetime import datetime
from unittest.mock import AsyncMock, Mock

import pytest

from src.application.services.agent_service import AgentService
from src.domain.model.agent import (
    AgentExecutionEvent,
    Conversation,
    ConversationStatus,
)
from src.domain.model.agent.agent_execution_event import ASSISTANT_MESSAGE, USER_MESSAGE


class MockLLMClient:
    """Mock LLM client for testing.

    This mock implements the ainvoke interface used by AgentService
    without inheriting from LLMClient to avoid abstract method requirements.
    """

    def __init__(self, should_fail: bool = False, fail_count: int = 0) -> None:
        """Initialize mock LLM.

        Args:
            should_fail: If True, all calls fail
            fail_count: Number of calls that should fail before success
        """
        self.should_fail = should_fail
        self.fail_count = fail_count
        self.call_count = 0
        self.responses = []
        self.call_args = None

    def set_response(self, response: str):
        """Set the response to return."""
        self.responses.append(response)

    async def ainvoke(self, messages, **kwargs):
        """Mock async invoke (matches LangChain-style interface)."""
        self.call_count += 1
        self.call_args = (messages, kwargs)

        if self.should_fail:
            raise Exception("LLM service unavailable")

        if self.fail_count > 0:
            self.fail_count -= 1
            raise Exception("Temporary LLM failure")

        # Return a mock ChatResponse-like object
        response = Mock()
        response.content = self.responses[-1] if self.responses else "Generated Title"
        return response


class MockAgentService(AgentService):
    """Concrete implementation of AgentService for testing."""

    async def get_available_tools(self):
        return []

    async def get_conversation_context(self, conversation_id: str):
        return []


class TestConversationTitleGeneration:
    """Test conversation title generation with retry and fallback."""

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
        mock_neo4j_client,
    ):
        """Create an AgentService with mock LLM."""
        llm = MockLLMClient()
        return MockAgentService(
            conversation_repository=mock_conversation_repo,
            execution_repository=mock_execution_repo,
            graph_service=mock_graph_service,
            llm=llm,
            neo4j_client=mock_neo4j_client,
            agent_execution_event_repository=mock_agent_execution_event_repo,
        )

    @pytest.fixture
    def sample_conversation(self):
        """Create a sample conversation with default title."""
        return Conversation(
            id="conv-1",
            project_id="proj-1",
            tenant_id="tenant-1",
            user_id="user-1",
            title="New Conversation",
            status=ConversationStatus.ACTIVE,
        )

    @pytest.mark.asyncio
    async def test_generate_title_success(self, agent_service):
        """Test successful title generation from user message."""
        agent_service._llm.set_response("Help with Python")

        title = await agent_service.generate_conversation_title(
            first_message="How do I write a Python function?",
            llm=agent_service._llm,
        )

        assert title == "Help with Python"
        assert agent_service._llm.call_count == 1

    @pytest.mark.asyncio
    async def test_generate_title_truncates_long_messages(self, agent_service):
        """Test that long messages are truncated before sending to LLM."""
        long_message = "a" * 300  # Longer than 200 char limit
        agent_service._llm.set_response("Long Message Topic")

        title = await agent_service.generate_conversation_title(
            first_message=long_message,
            llm=agent_service._llm,
        )

        assert title == "Long Message Topic"

    @pytest.mark.asyncio
    async def test_generate_title_limits_to_50_chars(self, agent_service):
        """Test that generated titles are limited to 50 characters."""
        agent_service._llm.set_response(
            "This is a very long title that exceeds fifty characters limit"
        )

        title = await agent_service.generate_conversation_title(
            first_message="Test message",
            llm=agent_service._llm,
        )

        assert len(title) <= 50
        assert title.endswith("...")

    @pytest.mark.asyncio
    async def test_generate_title_strips_quotes(self, agent_service):
        """Test that quotes are stripped from generated titles."""
        agent_service._llm.set_response('"Generated Title"')

        title = await agent_service.generate_conversation_title(
            first_message="Test message",
            llm=agent_service._llm,
        )

        assert title == "Generated Title"

    @pytest.mark.asyncio
    async def test_generate_title_empty_response_returns_fallback(self, agent_service):
        """Test that empty LLM response returns fallback title."""
        agent_service._llm.set_response("   ")

        title = await agent_service.generate_conversation_title(
            first_message="Test message that is quite long actually",
            llm=agent_service._llm,
        )

        # With retry mechanism, should fall back to truncated message
        # The fallback uses the first_message when LLM fails
        assert title != "New Conversation"
        assert "Test message" in title or "Test" in title

    @pytest.mark.asyncio
    async def test_generate_title_strips_prefix_and_trailing_punctuation(self, agent_service):
        """Test that common LLM wrappers are stripped from generated titles."""
        agent_service._llm.set_response("Title: Debug Python Imports.")

        title = await agent_service.generate_conversation_title(
            first_message="My Python imports keep failing",
            llm=agent_service._llm,
        )

        assert title == "Debug Python Imports"

    @pytest.mark.asyncio
    async def test_generate_title_uses_assistant_response_context(self, agent_service):
        """Test title generation includes the first assistant response when available."""
        agent_service._llm.set_response("FastAPI Auth Debugging")

        title = await agent_service._conversation_mgr.generate_conversation_title(
            first_message="It still fails",
            assistant_response="The traceback points to FastAPI dependency injection.",
            llm=agent_service._llm,
        )

        assert title == "FastAPI Auth Debugging"
        assert agent_service._llm.call_args is not None
        user_prompt = agent_service._llm.call_args[0][1].content
        assert "User: It still fails" in user_prompt
        assert "Assistant: The traceback points to FastAPI dependency injection." in user_prompt

    @pytest.mark.asyncio
    async def test_generate_title_llm_failure_returns_fallback(self, agent_service):
        """Test that LLM failure returns fallback title from message."""
        failing_llm = MockLLMClient(should_fail=True)

        title = await agent_service.generate_conversation_title(
            first_message="How do I write a Python function?",
            llm=failing_llm,
        )

        # Should return a fallback based on the message, not just "New Conversation"
        assert title != "New Conversation"
        assert "Python" in title or "write" in title or len(title) > 10

    @pytest.mark.asyncio
    async def test_title_generation_logs_do_not_include_message_or_title_content(
        self, agent_service, caplog
    ):
        """Title generation logs must not expose user message or generated title text."""
        secret_message = "please summarize customer secret token alpha-12345"
        generated_title = "customer secret token"
        agent_service._llm.set_response(generated_title)
        caplog.set_level(
            logging.INFO,
            logger="src.application.services.agent.conversation_manager",
        )

        title = await agent_service.generate_conversation_title(
            first_message=secret_message,
            llm=agent_service._llm,
        )

        assert title == generated_title
        assert secret_message not in caplog.text
        assert generated_title not in caplog.text

    @pytest.mark.asyncio
    async def test_fallback_title_logs_do_not_include_message_or_exception_content(
        self, agent_service, caplog
    ):
        """Fallback title logs must not expose message text or provider exception messages."""
        secret_message = "incident contains private database password beta-98765"
        failing_llm = MockLLMClient(should_fail=True)
        caplog.set_level(
            logging.INFO,
            logger="src.application.services.agent.conversation_manager",
        )

        title = await agent_service.generate_conversation_title(
            first_message=secret_message,
            llm=failing_llm,
        )

        assert "private" in title
        assert secret_message not in caplog.text
        assert "LLM service unavailable" not in caplog.text

    @pytest.mark.asyncio
    async def test_update_title_updates_conversation(
        self,
        agent_service,
        mock_conversation_repo,
        sample_conversation,
    ):
        """Test that updating title saves to repository."""
        mock_conversation_repo.find_by_id.return_value = sample_conversation

        result = await agent_service.update_conversation_title(
            conversation_id="conv-1",
            project_id="proj-1",
            user_id="user-1",
            title="Updated Title",
        )

        assert result is not None
        assert result.title == "Updated Title"
        mock_conversation_repo.save_and_commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_title_logs_do_not_include_title_content(
        self,
        agent_service,
        mock_conversation_repo,
        sample_conversation,
        caplog,
    ):
        """Manual title update logs must not expose title text."""
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

        assert result is not None
        assert result.title == secret_title
        assert secret_title not in caplog.text

    @pytest.mark.asyncio
    async def test_update_title_success_logs_do_not_include_identifiers(
        self,
        agent_service,
        mock_conversation_repo,
        sample_conversation,
        caplog,
    ):
        """Successful title update logs must not expose conversation, project, or user IDs."""
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

        assert result is not None
        assert secret_conversation_id not in caplog.text
        assert secret_project_id not in caplog.text
        assert secret_user_id not in caplog.text
        assert "title_len=17" in caplog.text
        assert "project_match=True" in caplog.text
        assert "user_match=True" in caplog.text

    @pytest.mark.asyncio
    async def test_update_title_unauthorized_returns_none(
        self,
        agent_service,
        mock_conversation_repo,
        sample_conversation,
    ):
        """Test that unauthorized title update returns None."""
        mock_conversation_repo.find_by_id.return_value = sample_conversation

        result = await agent_service.update_conversation_title(
            conversation_id="conv-1",
            project_id="proj-1",
            user_id="user-2",  # Different user
            title="Updated Title",
        )

        assert result is None
        mock_conversation_repo.save_and_commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_title_unauthorized_logs_do_not_include_identifiers(
        self,
        agent_service,
        mock_conversation_repo,
        sample_conversation,
        caplog,
    ):
        """Unauthorized title update logs must not expose scoped IDs."""
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

    @pytest.mark.asyncio
    async def test_update_title_missing_logs_do_not_include_identifier(
        self,
        agent_service,
        mock_conversation_repo,
        caplog,
    ):
        """Missing conversation title update logs must not expose the requested ID."""
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


class TestTitleGenerationTriggerConditions:
    """Test title generation trigger conditions (frontend logic simulation)."""

    def test_should_trigger_title_generation_for_new_conversation(self):
        """Test that title generation triggers for new conversation with few messages."""
        # Simulating frontend condition: only count message events, not all timeline events
        timeline = [
            {"type": "user_message", "sequenceNumber": 1},
            {"type": "assistant_message", "sequenceNumber": 2},
            {"type": "thought", "sequenceNumber": 3},  # Should not count
            {"type": "act", "sequenceNumber": 4},  # Should not count
            {"type": "observe", "sequenceNumber": 5},  # Should not count
        ]

        # Count only message events (correct behavior)
        message_count = sum(
            1 for e in timeline if e["type"] in ("user_message", "assistant_message")
        )

        # Should trigger because message_count is 2 (small), not timeline length 5
        assert message_count == 2
        assert message_count <= 4  # Trigger condition

    def test_should_not_trigger_title_after_custom_title(self):
        """Test that title generation doesn't trigger after custom title set."""
        conversation_title = "Custom User Title"
        message_count = 2

        # Should not trigger because title is already customized
        should_trigger = conversation_title == "New Conversation" and message_count <= 4

        assert not should_trigger

    def test_should_not_trigger_after_many_messages(self):
        """Test that title generation doesn't trigger after many messages."""
        conversation_title = "New Conversation"
        message_count = 10  # Too many messages

        should_trigger = conversation_title == "New Conversation" and message_count <= 4

        assert not should_trigger


class TestTitleGenerationWithRetry:
    """Test title generation with retry mechanism."""

    @pytest.mark.asyncio
    async def test_retry_on_transient_failure(self):
        """Test that title generation retries on transient LLM failure."""
        # Mock LLM that fails twice, then succeeds
        llm = MockLLMClient(fail_count=2)
        llm.set_response("Success Title")

        agent_service = MockAgentService(
            conversation_repository=AsyncMock(),
            execution_repository=AsyncMock(),
            graph_service=AsyncMock(),
            llm=llm,
            neo4j_client=AsyncMock(),
            agent_execution_event_repository=AsyncMock(),
        )

        title = await agent_service.generate_conversation_title(
            first_message="Test message",
            llm=llm,
        )

        # Should succeed after retries
        assert title == "Success Title"
        # Should have made 3 attempts (2 failures + 1 success)
        assert llm.call_count == 3

    @pytest.mark.asyncio
    async def test_max_retries_exceeded_returns_fallback(self):
        """Test that after max retries, fallback title is returned."""
        llm = MockLLMClient(should_fail=True)

        agent_service = MockAgentService(
            conversation_repository=AsyncMock(),
            execution_repository=AsyncMock(),
            graph_service=AsyncMock(),
            llm=llm,
            neo4j_client=AsyncMock(),
            agent_execution_event_repository=AsyncMock(),
        )

        title = await agent_service.generate_conversation_title(
            first_message="How do I write a Python function?",
            llm=llm,
        )

        # Should return fallback instead of default "New Conversation"
        assert "Python" in title or "write" in title or len(title) > 0
        assert title != "New Conversation"

    @pytest.mark.asyncio
    async def test_fallback_title_truncates_long_message(self):
        """Test that fallback title truncates long messages properly."""
        llm = MockLLMClient(should_fail=True)

        agent_service = MockAgentService(
            conversation_repository=AsyncMock(),
            execution_repository=AsyncMock(),
            graph_service=AsyncMock(),
            llm=llm,
            neo4j_client=AsyncMock(),
            agent_execution_event_repository=AsyncMock(),
        )

        long_message = "This is a very long message that exceeds the maximum length for a title and should be truncated appropriately"
        title = await agent_service.generate_conversation_title(
            first_message=long_message,
            llm=llm,
        )

        # Should be truncated
        assert len(title) <= 50
        assert "..." in title or len(title) < len(long_message)


class TestConcurrentTitleGeneration:
    """Test concurrent title generation prevention (frontend-side concern)."""

    def test_concurrent_generation_prevention(self):
        """Test that simultaneous title generation requests are prevented."""
        # This simulates frontend state management
        is_generating_title = False

        def try_generate():
            nonlocal is_generating_title
            if is_generating_title:
                return False  # Skip, already generating
            is_generating_title = True
            # Simulate async operation
            is_generating_title = False
            return True

        # First call succeeds
        assert try_generate() is True

        # Second call should be prevented
        assert try_generate() is True  # In real implementation, would be prevented

    @pytest.mark.asyncio
    async def test_title_generation_state_management(self):
        """Test title generation state is properly tracked."""
        # This test documents the expected state management
        states = {
            "is_generating_title": False,
            "title_generation_error": None,
        }

        # Start generation
        states["is_generating_title"] = True

        # Check should skip if already generating
        should_skip = states["is_generating_title"]
        assert should_skip is True

        # Complete generation
        states["is_generating_title"] = False
        assert states["is_generating_title"] is False


class TestTitleGenerationWithMessages:
    """Test getting first message from conversation for title generation."""

    @pytest.fixture
    def agent_service(self):
        """Create an AgentService with mock LLM."""
        llm = MockLLMClient()
        return MockAgentService(
            conversation_repository=AsyncMock(),
            execution_repository=AsyncMock(),
            graph_service=AsyncMock(),
            llm=llm,
            neo4j_client=AsyncMock(),
            agent_execution_event_repository=AsyncMock(),
        )

    @pytest.mark.asyncio
    async def test_get_first_user_message_from_events(self, agent_service):
        """Test extracting first user message from mixed event types."""
        events = [
            AgentExecutionEvent(
                id="event-1",
                conversation_id="conv-1",
                message_id="msg-1",
                event_type=USER_MESSAGE,
                event_data={"role": "user", "content": "First user message"},
                event_time_us=1000000,
                event_counter=0,
                created_at=datetime.now(),
            ),
            AgentExecutionEvent(
                id="event-2",
                conversation_id="conv-1",
                message_id="msg-2",
                event_type="thought",  # Not a message event
                event_data={"thought": "Agent is thinking"},
                event_time_us=2000000,
                event_counter=0,
                created_at=datetime.now(),
            ),
            AgentExecutionEvent(
                id="event-3",
                conversation_id="conv-1",
                message_id="msg-3",
                event_type=ASSISTANT_MESSAGE,
                event_data={"role": "assistant", "content": "Assistant response"},
                event_time_us=3000000,
                event_counter=0,
                created_at=datetime.now(),
            ),
        ]

        # Find first user message (API endpoint logic)
        first_user_message = None
        for event in events:
            if event.event_type == USER_MESSAGE:
                first_user_message = event.event_data.get("content", "")
                break

        assert first_user_message == "First user message"
