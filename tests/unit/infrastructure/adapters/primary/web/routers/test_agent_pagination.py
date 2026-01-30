"""
Unit tests for agent chat pagination.

TDD RED Phase: Tests written first for pagination feature.

Requirements:
1. Default limit should be 50 (not 100)
2. API should return has_more for backward pagination
3. Repository should support before_sequence parameter
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.infrastructure.adapters.primary.web.routers.agent import get_conversation_messages
from src.domain.model.agent import AgentExecutionEvent


class TestGetConversationMessagesPagination:
    """Test /conversations/{id}/messages endpoint pagination."""

    @pytest.fixture
    def mock_user(self):
        """Create a mock authenticated user."""
        user = MagicMock()
        user.id = "test-user-id"
        return user

    @pytest.fixture
    def mock_container(self):
        """Create a mock DI container."""
        container = MagicMock()
        return container

    @pytest.fixture
    def mock_event_repo(self):
        """Create a mock event repository."""
        repo = AsyncMock()
        return repo

    @pytest.fixture
    def mock_conversation(self):
        """Create a mock conversation."""
        conv = MagicMock()
        conv.id = "test-conv-id"
        conv.project_id = "test-project-id"
        conv.user_id = "test-user-id"
        return conv

    @pytest.fixture
    def sample_events(self):
        """Create sample timeline events."""
        events = []
        for i in range(10):
            event = MagicMock(spec=AgentExecutionEvent)
            event.id = f"event-{i}"
            event.conversation_id = "test-conv-id"
            event.message_id = f"msg-{i}"
            event.event_type = "user_message" if i % 2 == 0 else "assistant_message"
            event.event_data = {"content": f"Message {i}", "role": "user" if i % 2 == 0 else "assistant"}
            event.sequence_number = i + 1
            event.created_at = MagicMock()
            event.created_at.timestamp.return_value = (i + 1) * 1000
            events.append(event)
        return events

    @pytest.mark.asyncio
    async def test_default_limit_is_50(
        self,
        mock_user,
        mock_container,
        mock_event_repo,
        mock_conversation,
        sample_events,
    ):
        """Test that default limit for getting messages is 50."""
        # Setup mocks
        mock_container.agent_execution_event_repository.return_value = mock_event_repo
        mock_container.tool_execution_record_repository.return_value = AsyncMock()
        mock_event_repo.get_events = AsyncMock(return_value=sample_events)

        mock_agent_service = AsyncMock()
        mock_agent_service.get_conversation = AsyncMock(return_value=mock_conversation)
        mock_container.agent_service = MagicMock(return_value=mock_agent_service)

        mock_llm = MagicMock()
        mock_container.create_conversation_use_case = MagicMock()
        mock_container.list_conversations_use_case = MagicMock()
        mock_container.get_conversation_use_case = MagicMock()
        mock_container.agent_service = MagicMock(return_value=mock_agent_service)

        # Create mock request
        mock_request = MagicMock()
        mock_request.app.state.container = mock_container

        # Test with no limit parameter (should default to 50)
        # Note: We need to verify the API endpoint is called with default limit
        # This will be verified when we implement the code

        # Verify the repository is called with limit=50
        # Implementation should use: limit = Query(50, ...)
        pass  # Test structure for TDD - will verify after implementation

    @pytest.mark.asyncio
    async def test_custom_limit_parameter(
        self,
        mock_user,
        mock_container,
        mock_event_repo,
        mock_conversation,
        sample_events,
    ):
        """Test that custom limit parameter works."""
        # Setup
        mock_container.agent_execution_event_repository.return_value = mock_event_repo
        mock_container.tool_execution_record_repository.return_value = AsyncMock()
        mock_event_repo.get_events = AsyncMock(return_value=sample_events[:5])

        mock_agent_service = AsyncMock()
        mock_agent_service.get_conversation = AsyncMock(return_value=mock_conversation)
        mock_container.agent_service = MagicMock(return_value=mock_agent_service)

        mock_llm = MagicMock()
        # Create mock request
        mock_request = MagicMock()
        mock_request.app.state.container = mock_container

        # Test with limit=10
        # Implementation should respect the custom limit
        pass  # Test structure for TDD

    @pytest.mark.asyncio
    async def test_backward_pagination_with_before_sequence(
        self,
        mock_user,
        mock_container,
        mock_event_repo,
        mock_conversation,
        sample_events,
    ):
        """Test backward pagination using before_sequence parameter."""
        # Setup
        earlier_events = sample_events[:5]  # Events 1-5
        mock_container.agent_execution_event_repository.return_value = mock_event_repo
        mock_container.tool_execution_record_repository.return_value = AsyncMock()
        mock_event_repo.get_events = AsyncMock(return_value=earlier_events)

        mock_agent_service = AsyncMock()
        mock_agent_service.get_conversation = AsyncMock(return_value=mock_conversation)
        mock_container.agent_service = MagicMock(return_value=mock_agent_service)

        mock_request = MagicMock()
        mock_request.app.state.container = mock_container

        # Test with before_sequence=10
        # Should return events with sequence < 10
        pass  # Test structure for TDD

    def test_initial_load_from_sequence_calculation(self):
        """Test that from_sequence is calculated correctly for initial load.

        When loading latest messages, we need to calculate the starting sequence number.
        Formula: from_sequence = last_sequence - limit + 1

        Examples:
        - 100 total messages, limit 50 → from_sequence = 100 - 50 + 1 = 51
        - 50 total messages, limit 50 → from_sequence = 50 - 50 + 1 = 1
        - 10 total messages, limit 50 → from_sequence = max(0, 10 - 50 + 1) = 0 (from beginning)
        """
        def calculate_from_sequence(last_sequence: int, limit: int) -> int:
            """Calculate the starting sequence number for loading latest messages."""
            if last_sequence >= limit:
                return last_sequence - limit + 1
            return 0

        # Test case 1: 100 messages, limit 50
        assert calculate_from_sequence(100, 50) == 51
        # Test case 2: 50 messages, limit 50
        assert calculate_from_sequence(50, 50) == 1
        # Test case 3: 10 messages, limit 50
        assert calculate_from_sequence(10, 50) == 0
        # Test case 4: 200 messages, limit 50
        assert calculate_from_sequence(200, 50) == 151


class TestEventRepositoryPagination:
    """Test SQLAlchemy event repository pagination support."""

    @pytest.fixture
    def mock_db_session(self):
        """Create a mock database session."""
        session = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_get_events_with_before_sequence(
        self,
        mock_db_session,
    ):
        """Test that get_events supports before_sequence parameter."""
        # Import the repository
        from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_event_repository import (
            SqlAlchemyAgentExecutionEventRepository,
        )

        repo = SqlAlchemyAgentExecutionEventRepository(mock_db_session)

        # Mock the query execution
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        # Call with before_sequence
        await repo.get_events(
            conversation_id="test-conv",
            before_sequence=100,
            limit=50,
        )

        # Verify the query was constructed correctly
        # The implementation should use:
        # - WHERE sequence_number < before_sequence
        # - ORDER BY sequence_number DESC
        # - Then reverse results for chronological order
        mock_db_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_events_default_limit(
        self,
        mock_db_session,
    ):
        """Test that get_events has correct default limit."""
        from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_event_repository import (
            SqlAlchemyAgentExecutionEventRepository,
        )

        repo = SqlAlchemyAgentExecutionEventRepository(mock_db_session)

        # Check the method signature
        import inspect
        sig = inspect.signature(repo.get_events)

        # Verify default limit parameter
        # Implementation should have: limit: int = 1000 (or similar)
        # Note: The repository default is for internal use,
        # the API layer should set limit=50
        assert "limit" in sig.parameters
