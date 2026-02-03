"""
Tests for V2 SqlAgentExecutionEventRepository using BaseRepository.

TDD Approach: RED -> GREEN -> REFACTOR

These tests verify that the migrated repository maintains 100% compatibility
with the original implementation while leveraging the BaseRepository.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import AgentExecutionEvent
from src.infrastructure.adapters.secondary.persistence.v2_sql_agent_execution_event_repository import (
    V2SqlAgentExecutionEventRepository,
)


@pytest.fixture
async def v2_event_repo(db_session: AsyncSession) -> V2SqlAgentExecutionEventRepository:
    """Create a V2 agent execution event repository for testing."""
    return V2SqlAgentExecutionEventRepository(db_session)


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


class TestV2SqlAgentExecutionEventRepositorySave:
    """Tests for saving events."""

    @pytest.mark.asyncio
    async def test_save_new_event(self, v2_event_repo: V2SqlAgentExecutionEventRepository):
        """Test saving a new event."""
        event = AgentExecutionEvent(
            id="event-test-1",
            conversation_id="conv-test-1",
            message_id="msg-test-1",
            event_type="user_message",
            event_data={"content": "Hello"},
            sequence_number=1,
            created_at=datetime.now(timezone.utc),
        )

        await v2_event_repo.save(event)

        # Verify event was saved
        events = await v2_event_repo.get_events("conv-test-1")
        assert len(events) == 1
        assert events[0].id == "event-test-1"
        assert events[0].event_type == "user_message"

    @pytest.mark.asyncio
    async def test_save_idempotent(self, v2_event_repo: V2SqlAgentExecutionEventRepository):
        """Test that saving the same event twice is idempotent."""
        event = AgentExecutionEvent(
            id="event-idem-1",
            conversation_id="conv-test-1",
            message_id="msg-idem-1",
            event_type="user_message",
            event_data={"content": "Idempotent test"},
            sequence_number=1,
            created_at=datetime.now(timezone.utc),
        )

        # Save twice
        await v2_event_repo.save(event)
        await v2_event_repo.save(event)

        # Should only have one event
        events = await v2_event_repo.get_events("conv-test-1")
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_save_and_commit(self, v2_event_repo: V2SqlAgentExecutionEventRepository):
        """Test save_and_commit commits immediately."""
        event = AgentExecutionEvent(
            id="event-commit-1",
            conversation_id="conv-test-1",
            message_id="msg-commit-1",
            event_type="assistant_message",
            event_data={"content": "Commit test"},
            sequence_number=1,
            created_at=datetime.now(timezone.utc),
        )

        await v2_event_repo.save_and_commit(event)

        # Verify committed
        events = await v2_event_repo.get_events("conv-test-1")
        assert len(events) == 1


class TestV2SqlAgentExecutionEventRepositorySaveBatch:
    """Tests for batch saving events."""

    @pytest.mark.asyncio
    async def test_save_batch(self, v2_event_repo: V2SqlAgentExecutionEventRepository):
        """Test saving multiple events efficiently."""
        events = [
            AgentExecutionEvent(
                id=f"event-batch-{i}",
                conversation_id="conv-test-1",
                message_id=f"msg-batch-{i}",
                event_type="user_message",
                event_data={"index": i},
                sequence_number=i,
                created_at=datetime.now(timezone.utc),
            )
            for i in range(5)
        ]

        await v2_event_repo.save_batch(events)

        # Verify all saved
        retrieved = await v2_event_repo.get_events("conv-test-1")
        assert len(retrieved) == 5

    @pytest.mark.asyncio
    async def test_save_batch_empty(self, v2_event_repo: V2SqlAgentExecutionEventRepository):
        """Test saving an empty batch does nothing."""
        await v2_event_repo.save_batch([])

        # Should not raise error


class TestV2SqlAgentExecutionEventRepositoryGetEvents:
    """Tests for retrieving events."""

    @pytest.mark.asyncio
    async def test_get_events_forward_pagination(
        self, v2_event_repo: V2SqlAgentExecutionEventRepository
    ):
        """Test getting events with forward pagination."""
        # Create events
        for i in range(10):
            event = AgentExecutionEvent(
                id=f"event-fwd-{i}",
                conversation_id="conv-test-1",
                message_id=f"msg-fwd-{i}",
                event_type="user_message",
                event_data={"index": i},
                sequence_number=i,
                created_at=datetime.now(timezone.utc),
            )
            await v2_event_repo.save(event)

        # Get from sequence 5 onwards
        events = await v2_event_repo.get_events("conv-test-1", from_sequence=5, limit=10)
        assert len(events) == 5
        assert events[0].sequence_number == 5

    @pytest.mark.asyncio
    async def test_get_events_backward_pagination(
        self, v2_event_repo: V2SqlAgentExecutionEventRepository
    ):
        """Test getting events with backward pagination."""
        # Create events
        for i in range(10):
            event = AgentExecutionEvent(
                id=f"event-back-{i}",
                conversation_id="conv-test-1",
                message_id=f"msg-back-{i}",
                event_type="user_message",
                event_data={"index": i},
                sequence_number=i,
                created_at=datetime.now(timezone.utc),
            )
            await v2_event_repo.save(event)

        # Get events before sequence 7 (should get 0-6)
        events = await v2_event_repo.get_events(
            "conv-test-1", limit=10, before_sequence=7
        )
        assert len(events) == 7
        assert events[-1].sequence_number == 6

    @pytest.mark.asyncio
    async def test_get_events_with_type_filter(
        self, v2_event_repo: V2SqlAgentExecutionEventRepository
    ):
        """Test getting events filtered by type."""
        # Create mixed events
        for i in range(6):
            event = AgentExecutionEvent(
                id=f"event-type-{i}",
                conversation_id="conv-test-1",
                message_id=f"msg-type-{i}",
                event_type="user_message" if i % 2 == 0 else "tool_call",
                event_data={"index": i},
                sequence_number=i,
                created_at=datetime.now(timezone.utc),
            )
            await v2_event_repo.save(event)

        # Get only user_message events
        events = await v2_event_repo.get_events(
            "conv-test-1",
            event_types={"user_message"},
        )
        assert len(events) == 3
        for event in events:
            assert event.event_type == "user_message"

    @pytest.mark.asyncio
    async def test_get_events_ordered(self, v2_event_repo: V2SqlAgentExecutionEventRepository):
        """Test that events are returned in sequence order."""
        # Create events out of order
        event1 = AgentExecutionEvent(
            id="event-order-1",
            conversation_id="conv-test-1",
            message_id="msg-order-1",
            event_type="user_message",
            event_data={},
            sequence_number=2,
            created_at=datetime.now(timezone.utc),
        )
        event2 = AgentExecutionEvent(
            id="event-order-2",
            conversation_id="conv-test-1",
            message_id="msg-order-2",
            event_type="user_message",
            event_data={},
            sequence_number=1,
            created_at=datetime.now(timezone.utc),
        )
        await v2_event_repo.save(event1)
        await v2_event_repo.save(event2)

        events = await v2_event_repo.get_events("conv-test-1")
        assert events[0].sequence_number == 1
        assert events[1].sequence_number == 2


class TestV2SqlAgentExecutionEventRepositoryGetLastSequence:
    """Tests for getting last sequence number."""

    @pytest.mark.asyncio
    async def test_get_last_sequence_empty(self, v2_event_repo: V2SqlAgentExecutionEventRepository):
        """Test getting last sequence when no events exist."""
        last_seq = await v2_event_repo.get_last_sequence("conv-test-1")
        assert last_seq == 0

    @pytest.mark.asyncio
    async def test_get_last_sequence_with_events(
        self, v2_event_repo: V2SqlAgentExecutionEventRepository
    ):
        """Test getting last sequence when events exist."""
        # Create events
        for i in range(1, 6):
            event = AgentExecutionEvent(
                id=f"event-seq-{i}",
                conversation_id="conv-test-1",
                message_id=f"msg-seq-{i}",
                event_type="user_message",
                event_data={},
                sequence_number=i,
                created_at=datetime.now(timezone.utc),
            )
            await v2_event_repo.save(event)

        last_seq = await v2_event_repo.get_last_sequence("conv-test-1")
        assert last_seq == 5


class TestV2SqlAgentExecutionEventRepositoryGetEventsByMessage:
    """Tests for getting events by message."""

    @pytest.mark.asyncio
    async def test_get_events_by_message(
        self, v2_event_repo: V2SqlAgentExecutionEventRepository
    ):
        """Test getting all events for a specific message."""
        # Create events for different messages
        for i in range(3):
            event = AgentExecutionEvent(
                id=f"event-msg-{i}",
                conversation_id="conv-test-1",
                message_id="msg-target-1",
                event_type="tool_call",
                event_data={"index": i},
                sequence_number=i,
                created_at=datetime.now(timezone.utc),
            )
            await v2_event_repo.save(event)

        # Create event for different message
        other_event = AgentExecutionEvent(
            id="event-other-1",
            conversation_id="conv-test-1",
            message_id="msg-other-1",
            event_type="user_message",
            event_data={},
            sequence_number=3,
            created_at=datetime.now(timezone.utc),
        )
        await v2_event_repo.save(other_event)

        # Get events for target message
        events = await v2_event_repo.get_events_by_message("msg-target-1")
        assert len(events) == 3


class TestV2SqlAgentExecutionEventRepositoryDeleteByConversation:
    """Tests for deleting events by conversation."""

    @pytest.mark.asyncio
    async def test_delete_by_conversation(
        self, v2_event_repo: V2SqlAgentExecutionEventRepository
    ):
        """Test deleting all events for a conversation."""
        # Create events
        for i in range(5):
            event = AgentExecutionEvent(
                id=f"event-del-{i}",
                conversation_id="conv-test-1",
                message_id=f"msg-del-{i}",
                event_type="user_message",
                event_data={},
                sequence_number=i,
                created_at=datetime.now(timezone.utc),
            )
            await v2_event_repo.save(event)

        # Delete all events
        await v2_event_repo.delete_by_conversation("conv-test-1")

        # Verify deleted
        events = await v2_event_repo.get_events("conv-test-1")
        assert len(events) == 0


class TestV2SqlAgentExecutionEventRepositoryListByConversation:
    """Tests for list_by_conversation method."""

    @pytest.mark.asyncio
    async def test_list_by_conversation(
        self, v2_event_repo: V2SqlAgentExecutionEventRepository
    ):
        """Test listing all events for a conversation."""
        # Create events
        for i in range(5):
            event = AgentExecutionEvent(
                id=f"event-list-{i}",
                conversation_id="conv-test-1",
                message_id=f"msg-list-{i}",
                event_type="user_message",
                event_data={},
                sequence_number=i,
                created_at=datetime.now(timezone.utc),
            )
            await v2_event_repo.save(event)

        # List events
        events = await v2_event_repo.list_by_conversation("conv-test-1")
        assert len(events) == 5


class TestV2SqlAgentExecutionEventRepositoryGetMessageEvents:
    """Tests for getting message events."""

    @pytest.mark.asyncio
    async def test_get_message_events(
        self, v2_event_repo: V2SqlAgentExecutionEventRepository
    ):
        """Test getting user_message and assistant_message events."""
        # Create mixed events
        events_data = [
            ("user_message", 1),
            ("tool_call", 2),
            ("assistant_message", 3),
            ("tool_call", 4),
            ("user_message", 5),
        ]
        for event_type, seq in events_data:
            event = AgentExecutionEvent(
                id=f"event-msgtype-{seq}",
                conversation_id="conv-test-1",
                message_id=f"msg-msgtype-{seq}",
                event_type=event_type,
                event_data={},
                sequence_number=seq,
                created_at=datetime.now(timezone.utc),
            )
            await v2_event_repo.save(event)

        # Get only message events
        events = await v2_event_repo.get_message_events("conv-test-1", limit=10)
        assert len(events) == 3
        for event in events:
            assert event.event_type in ["user_message", "assistant_message"]


class TestV2SqlAgentExecutionEventRepositoryCountMessages:
    """Tests for counting messages."""

    @pytest.mark.asyncio
    async def test_count_messages(self, v2_event_repo: V2SqlAgentExecutionEventRepository):
        """Test counting message events in a conversation."""
        # Create mixed events
        for i in range(10):
            event_type = "user_message" if i % 2 == 0 else "tool_call"
            event = AgentExecutionEvent(
                id=f"event-count-{i}",
                conversation_id="conv-test-1",
                message_id=f"msg-count-{i}",
                event_type=event_type,
                event_data={},
                sequence_number=i,
                created_at=datetime.now(timezone.utc),
            )
            await v2_event_repo.save(event)

        # Count only message events
        count = await v2_event_repo.count_messages("conv-test-1")
        assert count == 5


class TestV2SqlAgentExecutionEventRepositoryToDomain:
    """Tests for _to_domain conversion."""

    @pytest.mark.asyncio
    async def test_to_domain_converts_all_fields(
        self, v2_event_repo: V2SqlAgentExecutionEventRepository
    ):
        """Test that _to_domain correctly converts all DB fields."""
        event = AgentExecutionEvent(
            id="event-domain-1",
            conversation_id="conv-test-1",
            message_id="msg-domain-1",
            event_type="tool_call",
            event_data={"tool": "search", "args": {"query": "test"}},
            sequence_number=42,
            created_at=datetime.now(timezone.utc),
        )
        await v2_event_repo.save(event)

        events = await v2_event_repo.get_events("conv-test-1")
        assert len(events) == 1
        assert events[0].id == "event-domain-1"
        assert events[0].event_type == "tool_call"
        assert events[0].event_data["tool"] == "search"
        assert events[0].sequence_number == 42

    @pytest.mark.asyncio
    async def test_to_domain_with_none_db_model(
        self, v2_event_repo: V2SqlAgentExecutionEventRepository
    ):
        """Test that _to_domain returns None for None input."""
        result = v2_event_repo._to_domain(None)
        assert result is None
