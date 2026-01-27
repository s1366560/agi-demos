"""
Unit tests for SqlAlchemyAgentExecutionEventRepository pagination functionality.

TDD: Tests written first (RED phase) for backward pagination support.
"""

import pytest
from datetime import datetime, timezone

from src.domain.model.agent import AgentExecutionEvent
from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_event_repository import (
    SqlAlchemyAgentExecutionEventRepository,
)


@pytest.mark.unit
class TestAgentExecutionEventRepositoryPagination:
    """Test cases for backward pagination in AgentExecutionEventRepository"""

    @pytest.fixture
    def repo(self, test_db):
        """Create repository instance"""
        return SqlAlchemyAgentExecutionEventRepository(test_db)

    @pytest.fixture
    async def populated_conversation(self, repo, test_db):
        """Create a conversation with multiple events for pagination testing"""
        conversation_id = "conv_test_pagination"
        message_id = "msg_test_1"

        # Create 20 events with sequence numbers 1-20
        events = []
        for i in range(1, 21):
            event = AgentExecutionEvent(
                id=f"event_{i}",
                conversation_id=conversation_id,
                message_id=message_id,
                event_type="user_message" if i % 2 == 1 else "assistant_message",
                event_data={"content": f"Message {i}", "sequence": i},
                sequence_number=i,
                created_at=datetime.now(timezone.utc),
            )
            events.append(event)
            await repo.save(event)

        await test_db.commit()
        return {"conversation_id": conversation_id, "message_id": message_id, "total": 20}

    @pytest.mark.asyncio
    async def test_get_events_forward_from_sequence(self, repo, populated_conversation):
        """Test getting events starting from a sequence number (forward pagination)"""
        # Arrange
        conversation_id = populated_conversation["conversation_id"]

        # Act - Get events from sequence 11 onwards
        events = await repo.get_events(
            conversation_id=conversation_id,
            from_sequence=11,
            limit=10,
        )

        # Assert
        assert len(events) == 10
        assert events[0].sequence_number == 11
        assert events[-1].sequence_number == 20
        # Verify order is ascending
        for i in range(len(events) - 1):
            assert events[i].sequence_number < events[i + 1].sequence_number

    @pytest.mark.asyncio
    async def test_get_events_backward_before_sequence(self, repo, populated_conversation):
        """Test getting events before a sequence number (backward pagination)"""
        # Arrange
        conversation_id = populated_conversation["conversation_id"]

        # Act - Get events before sequence 10
        events = await repo.get_events(
            conversation_id=conversation_id,
            from_sequence=0,
            limit=10,
            before_sequence=10,
        )

        # Assert
        assert len(events) == 9  # sequences 1-9 (before 10)
        assert events[0].sequence_number == 1
        assert events[-1].sequence_number == 9
        # Verify order is ascending (chronological)
        for i in range(len(events) - 1):
            assert events[i].sequence_number < events[i + 1].sequence_number

    @pytest.mark.asyncio
    async def test_get_events_backward_with_limit(self, repo, populated_conversation):
        """Test backward pagination respects limit parameter"""
        # Arrange
        conversation_id = populated_conversation["conversation_id"]

        # Act - Get 5 events before sequence 15
        events = await repo.get_events(
            conversation_id=conversation_id,
            from_sequence=0,
            limit=5,
            before_sequence=15,
        )

        # Assert - Should get the 5 most recent events before 15: 14, 13, 12, 11, 10
        # But returned in chronological order: 10, 11, 12, 13, 14
        assert len(events) == 5
        assert events[0].sequence_number == 10
        assert events[-1].sequence_number == 14

    @pytest.mark.asyncio
    async def test_get_events_backward_at_boundary(self, repo, populated_conversation):
        """Test backward pagination when before_sequence is at the start"""
        # Arrange
        conversation_id = populated_conversation["conversation_id"]

        # Act - Get events before sequence 3
        events = await repo.get_events(
            conversation_id=conversation_id,
            from_sequence=0,
            limit=10,
            before_sequence=3,
        )

        # Assert - Should only get sequences 1-2
        assert len(events) == 2
        assert events[0].sequence_number == 1
        assert events[-1].sequence_number == 2

    @pytest.mark.asyncio
    async def test_get_events_backward_no_results(self, repo, populated_conversation):
        """Test backward pagination when no events exist before sequence"""
        # Arrange
        conversation_id = populated_conversation["conversation_id"]

        # Act - Get events before sequence 2 (only sequence 1 exists before it)
        events = await repo.get_events(
            conversation_id=conversation_id,
            from_sequence=0,
            limit=10,
            before_sequence=2,
        )

        # Assert - Should only get sequence 1
        assert len(events) == 1
        assert events[0].sequence_number == 1

    @pytest.mark.asyncio
    async def test_get_events_backward_before_sequence_1(self, repo, populated_conversation):
        """Test backward pagination when before_sequence is 1 (no results)"""
        # Arrange
        conversation_id = populated_conversation["conversation_id"]

        # Act - Get events before sequence 1
        events = await repo.get_events(
            conversation_id=conversation_id,
            from_sequence=0,
            limit=10,
            before_sequence=1,
        )

        # Assert - Should return empty list
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_get_events_with_event_types_filter(self, repo, populated_conversation):
        """Test that event_types filter still works with backward pagination"""
        # Arrange
        conversation_id = populated_conversation["conversation_id"]

        # Act - Get only user_message events before sequence 15
        events = await repo.get_events(
            conversation_id=conversation_id,
            from_sequence=0,
            limit=10,
            before_sequence=15,
            event_types={"user_message"},
        )

        # Assert - Should get user messages (odd sequences) before 15: 1, 3, 5, 7, 9, 11, 13
        assert len(events) == 7
        # All should be user_message type
        for event in events:
            assert event.event_type == "user_message"
        # Verify sequences are odd numbers
        expected_sequences = [1, 3, 5, 7, 9, 11, 13]
        actual_sequences = [e.sequence_number for e in events]
        assert actual_sequences == expected_sequences

    @pytest.mark.asyncio
    async def test_get_events_without_before_sequence_default(self, repo, populated_conversation):
        """Test that default behavior (without before_sequence) still works"""
        # Arrange
        conversation_id = populated_conversation["conversation_id"]

        # Act - Get events from start without before_sequence
        events = await repo.get_events(
            conversation_id=conversation_id,
            from_sequence=0,
            limit=10,
        )

        # Assert - Should get first 10 events (sequences 1-10)
        assert len(events) == 10
        assert events[0].sequence_number == 1
        assert events[-1].sequence_number == 10

    @pytest.mark.asyncio
    async def test_get_events_backward_large_limit(self, repo, populated_conversation):
        """Test backward pagination when limit exceeds available events"""
        # Arrange
        conversation_id = populated_conversation["conversation_id"]

        # Act - Request more events than exist before sequence 15
        events = await repo.get_events(
            conversation_id=conversation_id,
            from_sequence=0,
            limit=100,  # More than 14 available
            before_sequence=15,
        )

        # Assert - Should return all available events (14 at most)
        assert len(events) == 14  # sequences 1-14
        assert events[0].sequence_number == 1
        assert events[-1].sequence_number == 14

    @pytest.mark.asyncio
    async def test_get_events_backward_consecutive_pages(self, repo, populated_conversation):
        """Test consecutive backward pagination requests work correctly"""
        # Arrange
        conversation_id = populated_conversation["conversation_id"]

        # Act - First page: get events before 21 (end)
        page1 = await repo.get_events(
            conversation_id=conversation_id,
            from_sequence=0,
            limit=10,
            before_sequence=21,
        )

        # Second page: get events before page1's first sequence
        first_seq_page1 = page1[0].sequence_number
        page2 = await repo.get_events(
            conversation_id=conversation_id,
            from_sequence=0,
            limit=10,
            before_sequence=first_seq_page1,
        )

        # Assert
        # Page 1 should have sequences 11-20
        assert len(page1) == 10
        assert page1[0].sequence_number == 11
        assert page1[-1].sequence_number == 20

        # Page 2 should have sequences 1-10
        assert len(page2) == 10
        assert page2[0].sequence_number == 1
        assert page2[-1].sequence_number == 10

        # No overlap between pages
        page1_sequences = {e.sequence_number for e in page1}
        page2_sequences = {e.sequence_number for e in page2}
        assert page1_sequences.isdisjoint(page2_sequences)
