"""
Tests for V2 SqlMessageRepository using BaseRepository.

TDD Approach: RED -> GREEN -> REFACTOR

These tests verify that the migrated repository maintains 100% compatibility
with the original implementation while leveraging the BaseRepository.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import Message, MessageRole, MessageType, ToolCall, ToolResult
from src.infrastructure.adapters.secondary.persistence.models import Message as DBMessage
from src.infrastructure.adapters.secondary.persistence.v2_sql_message_repository import (
    V2SqlMessageRepository,
)


@pytest.fixture
async def v2_message_repo(
    db_session: AsyncSession, test_conversation_db: DBMessage
) -> V2SqlMessageRepository:
    """Create a V2 message repository for testing."""
    return V2SqlMessageRepository(db_session)


@pytest.fixture
async def test_conversation_db(db_session: AsyncSession):
    """Create a test conversation in the database."""
    from src.infrastructure.adapters.secondary.persistence.models import Conversation

    conv = Conversation(
        id="conv-test-1",
        project_id="proj-test-1",
        tenant_id="tenant-test-1",
        user_id="user-test-1",
        title="Test Conversation",
        status="active",
    )
    db_session.add(conv)
    await db_session.flush()
    return conv


class TestV2SqlMessageRepositorySave:
    """Tests for saving messages."""

    @pytest.mark.asyncio
    async def test_save_new_message(self, v2_message_repo: V2SqlMessageRepository, test_conversation_db):
        """Test saving a new message."""
        message = Message(
            id="msg-test-1",
            conversation_id="conv-test-1",
            role=MessageRole.USER,
            content="Hello, world!",
            message_type=MessageType.TEXT,
            created_at=datetime.now(timezone.utc),
        )

        await v2_message_repo.save(message)

        # Verify message was saved
        retrieved = await v2_message_repo.find_by_id("msg-test-1")
        assert retrieved is not None
        assert retrieved.id == "msg-test-1"
        assert retrieved.content == "Hello, world!"
        assert retrieved.role == MessageRole.USER

    @pytest.mark.asyncio
    async def test_save_message_with_tool_calls(self, v2_message_repo: V2SqlMessageRepository):
        """Test saving a message with tool calls."""
        message = Message(
            id="msg-tool-1",
            conversation_id="conv-test-1",
            role=MessageRole.ASSISTANT,
            content="Let me check that.",
            message_type=MessageType.TEXT,
            tool_calls=[
                ToolCall(name="search", arguments={"query": "test"}, call_id="call-1"),
                ToolCall(name="calculate", arguments={"x": 1, "y": 2}, call_id="call-2"),
            ],
            created_at=datetime.now(timezone.utc),
        )

        await v2_message_repo.save(message)

        retrieved = await v2_message_repo.find_by_id("msg-tool-1")
        assert retrieved is not None
        assert len(retrieved.tool_calls) == 2
        assert retrieved.tool_calls[0].name == "search"
        assert retrieved.tool_calls[0].arguments == {"query": "test"}
        assert retrieved.tool_calls[0].call_id == "call-1"

    @pytest.mark.asyncio
    async def test_save_message_with_tool_results(self, v2_message_repo: V2SqlMessageRepository):
        """Test saving a message with tool results (must have matching tool_calls)."""
        # Message requires tool_results to have matching tool_calls
        message = Message(
            id="msg-result-1",
            conversation_id="conv-test-1",
            role=MessageRole.ASSISTANT,
            content="Here are the results.",
            message_type=MessageType.TEXT,
            tool_calls=[
                ToolCall(name="search", arguments={"query": "test"}, call_id="call-1"),
                ToolCall(name="calculate", arguments={"x": 1, "y": 2}, call_id="call-2"),
            ],
            tool_results=[
                ToolResult(
                    tool_call_id="call-1",
                    result="Search completed",
                    is_error=False,
                ),
                ToolResult(
                    tool_call_id="call-2",
                    result="Error: Invalid input",
                    is_error=True,
                    error_message="Invalid input",
                ),
            ],
            created_at=datetime.now(timezone.utc),
        )

        await v2_message_repo.save(message)

        retrieved = await v2_message_repo.find_by_id("msg-result-1")
        assert retrieved is not None
        assert len(retrieved.tool_results) == 2
        assert retrieved.tool_results[0].result == "Search completed"
        assert retrieved.tool_results[1].is_error is True
        assert retrieved.tool_results[1].error_message == "Invalid input"

    @pytest.mark.asyncio
    async def test_save_and_commit(self, v2_message_repo: V2SqlMessageRepository):
        """Test save_and_commit commits immediately."""
        message = Message(
            id="msg-commit-1",
            conversation_id="conv-test-1",
            role=MessageRole.USER,
            content="Commit test",
            message_type=MessageType.TEXT,
            created_at=datetime.now(timezone.utc),
        )

        await v2_message_repo.save_and_commit(message)

        # Verify committed - new query should see it
        retrieved = await v2_message_repo.find_by_id("msg-commit-1")
        assert retrieved is not None


class TestV2SqlMessageRepositoryFind:
    """Tests for finding messages."""

    @pytest.mark.asyncio
    async def test_find_by_id_existing(self, v2_message_repo: V2SqlMessageRepository):
        """Test finding an existing message by ID."""
        message = Message(
            id="msg-find-1",
            conversation_id="conv-test-1",
            role=MessageRole.USER,
            content="Find me",
            message_type=MessageType.TEXT,
            created_at=datetime.now(timezone.utc),
        )
        await v2_message_repo.save(message)

        retrieved = await v2_message_repo.find_by_id("msg-find-1")
        assert retrieved is not None
        assert retrieved.id == "msg-find-1"
        assert retrieved.content == "Find me"

    @pytest.mark.asyncio
    async def test_find_by_id_not_found(self, v2_message_repo: V2SqlMessageRepository):
        """Test finding a non-existent message returns None."""
        retrieved = await v2_message_repo.find_by_id("non-existent")
        assert retrieved is None


class TestV2SqlMessageRepositoryList:
    """Tests for listing messages."""

    @pytest.mark.asyncio
    async def test_list_by_conversation(self, v2_message_repo: V2SqlMessageRepository):
        """Test listing messages for a conversation."""
        # Create multiple messages
        for i in range(3):
            message = Message(
                id=f"msg-list-{i}",
                conversation_id="conv-test-1",
                role=MessageRole.USER,
                content=f"Message {i}",
                message_type=MessageType.TEXT,
                created_at=datetime.now(timezone.utc),
            )
            await v2_message_repo.save(message)

        # List messages
        messages = await v2_message_repo.list_by_conversation("conv-test-1")
        assert len(messages) == 3

    @pytest.mark.asyncio
    async def test_list_by_conversation_ordered(self, v2_message_repo: V2SqlMessageRepository):
        """Test that messages are ordered by created_at."""
        import time

        # Create messages with delays
        msg1 = Message(
            id="msg-ordered-1",
            conversation_id="conv-test-1",
            role=MessageRole.USER,
            content="First",
            message_type=MessageType.TEXT,
            created_at=datetime.now(timezone.utc),
        )
        await v2_message_repo.save(msg1)
        time.sleep(0.01)

        msg2 = Message(
            id="msg-ordered-2",
            conversation_id="conv-test-1",
            role=MessageRole.USER,
            content="Second",
            message_type=MessageType.TEXT,
            created_at=datetime.now(timezone.utc),
        )
        await v2_message_repo.save(msg2)

        messages = await v2_message_repo.list_by_conversation("conv-test-1")
        # Should be in chronological order
        assert messages[0].id == "msg-ordered-1"
        assert messages[1].id == "msg-ordered-2"

    @pytest.mark.asyncio
    async def test_list_by_conversation_with_pagination(self, v2_message_repo: V2SqlMessageRepository):
        """Test listing messages with pagination."""
        # Create 5 messages
        for i in range(5):
            message = Message(
                id=f"msg-page-{i}",
                conversation_id="conv-test-1",
                role=MessageRole.USER,
                content=f"Page {i}",
                message_type=MessageType.TEXT,
                created_at=datetime.now(timezone.utc),
            )
            await v2_message_repo.save(message)

        # Get first page
        page1 = await v2_message_repo.list_by_conversation("conv-test-1", limit=2, offset=0)
        assert len(page1) == 2

        # Get second page
        page2 = await v2_message_repo.list_by_conversation("conv-test-1", limit=2, offset=2)
        assert len(page2) == 2

    @pytest.mark.asyncio
    async def test_list_recent_by_project(self, v2_message_repo: V2SqlMessageRepository):
        """Test listing recent messages across conversations in a project."""
        # Create messages for our test conversation
        for i in range(3):
            message = Message(
                id=f"msg-recent-{i}",
                conversation_id="conv-test-1",
                role=MessageRole.USER,
                content=f"Recent {i}",
                message_type=MessageType.TEXT,
                created_at=datetime.now(timezone.utc),
            )
            await v2_message_repo.save(message)

        # List recent by project
        messages = await v2_message_repo.list_recent_by_project("proj-test-1", limit=10)
        assert len(messages) >= 3


class TestV2SqlMessageRepositoryCount:
    """Tests for counting messages."""

    @pytest.mark.asyncio
    async def test_count_by_conversation(self, v2_message_repo: V2SqlMessageRepository):
        """Test counting messages in a conversation."""
        # Initially empty
        count = await v2_message_repo.count_by_conversation("conv-test-1")
        assert count == 0

        # Add messages
        for i in range(3):
            message = Message(
                id=f"msg-count-{i}",
                conversation_id="conv-test-1",
                role=MessageRole.USER,
                content=f"Count {i}",
                message_type=MessageType.TEXT,
                created_at=datetime.now(timezone.utc),
            )
            await v2_message_repo.save(message)

        count = await v2_message_repo.count_by_conversation("conv-test-1")
        assert count == 3


class TestV2SqlMessageRepositoryDelete:
    """Tests for deleting messages."""

    @pytest.mark.asyncio
    async def test_delete_by_conversation(self, v2_message_repo: V2SqlMessageRepository):
        """Test deleting all messages in a conversation."""
        # Create messages
        for i in range(3):
            message = Message(
                id=f"msg-delete-{i}",
                conversation_id="conv-test-1",
                role=MessageRole.USER,
                content=f"Delete {i}",
                message_type=MessageType.TEXT,
                created_at=datetime.now(timezone.utc),
            )
            await v2_message_repo.save(message)

        # Delete all messages in conversation
        await v2_message_repo.delete_by_conversation("conv-test-1")

        # Verify deleted
        messages = await v2_message_repo.list_by_conversation("conv-test-1")
        assert len(messages) == 0


class TestV2SqlMessageRepositoryToDomain:
    """Tests for _to_domain conversion."""

    @pytest.mark.asyncio
    async def test_to_domain_converts_all_fields(self, v2_message_repo: V2SqlMessageRepository):
        """Test that _to_domain correctly converts all DB fields."""
        message = Message(
            id="msg-domain-1",
            conversation_id="conv-test-1",
            role=MessageRole.ASSISTANT,
            content="Domain test",
            message_type=MessageType.TEXT,
            tool_calls=[
                ToolCall(name="test_tool", arguments={"arg": "value"}, call_id="call-123")
            ],
            tool_results=[
                ToolResult(tool_call_id="call-123", result="Success", is_error=False)
            ],
            metadata={"key": "value"},
            created_at=datetime.now(timezone.utc),
        )
        await v2_message_repo.save(message)

        retrieved = await v2_message_repo.find_by_id("msg-domain-1")
        assert retrieved.id == "msg-domain-1"
        assert retrieved.role == MessageRole.ASSISTANT
        assert retrieved.message_type == MessageType.TEXT
        assert len(retrieved.tool_calls) == 1
        assert retrieved.tool_calls[0].name == "test_tool"
        assert len(retrieved.tool_results) == 1
        assert retrieved.tool_results[0].result == "Success"
        assert retrieved.metadata == {"key": "value"}

    @pytest.mark.asyncio
    async def test_to_domain_with_none_db_model(self, v2_message_repo: V2SqlMessageRepository):
        """Test that _to_domain returns None for None input."""
        result = v2_message_repo._to_domain(None)
        assert result is None


class TestV2SqlMessageRepositoryTransaction:
    """Tests for transaction support."""

    @pytest.mark.asyncio
    async def test_transaction_context_manager(self, v2_message_repo: V2SqlMessageRepository):
        """Test using transaction context manager."""
        async with v2_message_repo.transaction():
            msg1 = Message(
                id="msg-tx-1",
                conversation_id="conv-test-1",
                role=MessageRole.USER,
                content="TX 1",
                message_type=MessageType.TEXT,
                created_at=datetime.now(timezone.utc),
            )
            await v2_message_repo.save(msg1)

            msg2 = Message(
                id="msg-tx-2",
                conversation_id="conv-test-1",
                role=MessageRole.USER,
                content="TX 2",
                message_type=MessageType.TEXT,
                created_at=datetime.now(timezone.utc),
            )
            await v2_message_repo.save(msg2)

        # Verify both were saved
        m1 = await v2_message_repo.find_by_id("msg-tx-1")
        m2 = await v2_message_repo.find_by_id("msg-tx-2")
        assert m1 is not None
        assert m2 is not None

    @pytest.mark.asyncio
    async def test_transaction_rollback_on_error(self, v2_message_repo: V2SqlMessageRepository):
        """Test that transaction rolls back on error."""
        try:
            async with v2_message_repo.transaction():
                msg1 = Message(
                    id="msg-tx-rollback-1",
                    conversation_id="conv-test-1",
                    role=MessageRole.USER,
                    content="Rollback",
                    message_type=MessageType.TEXT,
                    created_at=datetime.now(timezone.utc),
                )
                await v2_message_repo.save(msg1)

                # Raise error to trigger rollback
                raise ValueError("Test error")
        except ValueError:
            pass

        # Verify rollback occurred
        m1 = await v2_message_repo.find_by_id("msg-tx-rollback-1")
        assert m1 is None
