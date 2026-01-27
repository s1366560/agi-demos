"""
Integration tests for Agent conversation messages pagination API.

TDD: Tests written first (RED phase) for backward pagination support.
"""

import pytest
from datetime import datetime, timezone

from src.domain.model.agent import AgentExecutionEvent
from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_event_repository import (
    SqlAlchemyAgentExecutionEventRepository,
)


@pytest.mark.integration
class TestAgentMessagesPagination:
    """Test cases for conversation messages pagination API"""

    @pytest.fixture
    async def conversation_with_events(self, test_db, test_project_db, test_tenant_db, test_user):
        """Create a conversation with multiple events for pagination testing"""
        from src.infrastructure.adapters.secondary.persistence.models import Conversation

        # Create conversation record first
        conversation_id = "conv_pagination_test"
        conversation = Conversation(
            id=conversation_id,
            project_id=test_project_db.id,
            tenant_id=test_tenant_db.id,
            user_id=test_user.id,
            title="Pagination Test Conversation",
            status="active",
        )
        test_db.add(conversation)

        # Create events directly in the database
        message_id = "msg_pagination_test"
        repo = SqlAlchemyAgentExecutionEventRepository(test_db)

        # Create 20 events with sequence numbers 1-20
        for i in range(1, 21):
            event = AgentExecutionEvent(
                id=f"event_{conversation_id}_{i}",
                conversation_id=conversation_id,
                message_id=message_id,
                event_type="user_message" if i % 2 == 1 else "assistant_message",
                event_data={"content": f"Message {i}"},
                sequence_number=i,
                created_at=datetime.now(timezone.utc),
            )
            await repo.save(event)

        await test_db.commit()

        return {
            "conversation_id": conversation_id,
            "project_id": test_project_db.id,
            "total_events": 20,
        }

    @pytest.mark.asyncio
    async def test_get_messages_default_limit(self, authenticated_async_client, conversation_with_events):
        """Test getting messages with default limit"""
        # Arrange
        conversation_id = conversation_with_events["conversation_id"]
        project_id = conversation_with_events["project_id"]

        # Act
        response = await authenticated_async_client.get(
            f"/api/v1/agent/conversations/{conversation_id}/messages",
            params={"project_id": project_id},
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert "timeline" in data
        assert "total" in data
        # New pagination metadata fields
        assert "has_more" in data
        assert "first_sequence" in data
        assert "last_sequence" in data
        # Should have messages
        assert len(data["timeline"]) > 0

    @pytest.mark.asyncio
    async def test_get_messages_with_custom_limit(self, authenticated_async_client, conversation_with_events):
        """Test getting messages with custom limit"""
        # Arrange
        conversation_id = conversation_with_events["conversation_id"]
        project_id = conversation_with_events["project_id"]

        # Act - Get only 5 messages
        response = await authenticated_async_client.get(
            f"/api/v1/agent/conversations/{conversation_id}/messages",
            params={"project_id": project_id, "limit": 5},
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert len(data["timeline"]) <= 5

    @pytest.mark.asyncio
    async def test_get_messages_with_before_sequence(self, authenticated_async_client, conversation_with_events):
        """Test backward pagination using before_sequence parameter"""
        # Arrange
        conversation_id = conversation_with_events["conversation_id"]
        project_id = conversation_with_events["project_id"]

        # First, get all messages to find a sequence number
        initial_response = await authenticated_async_client.get(
            f"/api/v1/agent/conversations/{conversation_id}/messages",
            params={"project_id": project_id, "limit": 100},
        )
        initial_data = initial_response.json()
        assert len(initial_data["timeline"]) > 0

        # Get the middle sequence number
        middle_index = len(initial_data["timeline"]) // 2
        before_sequence = initial_data["timeline"][middle_index]["sequenceNumber"]

        # Act - Get messages before the middle sequence
        response = await authenticated_async_client.get(
            f"/api/v1/agent/conversations/{conversation_id}/messages",
            params={
                "project_id": project_id,
                "limit": 10,
                "before_sequence": before_sequence,
            },
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        # All returned events should have sequence < before_sequence
        for event in data["timeline"]:
            assert event["sequenceNumber"] < before_sequence
        # Events should be in chronological order
        sequences = [e["sequenceNumber"] for e in data["timeline"]]
        assert sequences == sorted(sequences)

    @pytest.mark.asyncio
    async def test_get_messages_pagination_metadata(self, authenticated_async_client, conversation_with_events):
        """Test pagination metadata is correctly returned"""
        # Arrange
        conversation_id = conversation_with_events["conversation_id"]
        project_id = conversation_with_events["project_id"]

        # Act
        response = await authenticated_async_client.get(
            f"/api/v1/agent/conversations/{conversation_id}/messages",
            params={"project_id": project_id, "limit": 10},
        )

        # Assert
        assert response.status_code == 200
        data = response.json()

        # Verify pagination metadata structure
        assert isinstance(data["has_more"], bool)
        assert isinstance(data["first_sequence"], int)
        assert isinstance(data["last_sequence"], int)

        # Verify consistency with timeline
        if len(data["timeline"]) > 0:
            assert data["first_sequence"] == data["timeline"][0]["sequenceNumber"]
            assert data["last_sequence"] == data["timeline"][-1]["sequenceNumber"]

    @pytest.mark.asyncio
    async def test_get_messages_consecutive_backward_pages(self, authenticated_async_client, conversation_with_events):
        """Test consecutive backward pagination requests work correctly"""
        # Arrange
        conversation_id = conversation_with_events["conversation_id"]
        project_id = conversation_with_events["project_id"]

        # First page: get latest messages (use before_sequence of a high number)
        page1 = await authenticated_async_client.get(
            f"/api/v1/agent/conversations/{conversation_id}/messages",
            params={"project_id": project_id, "limit": 5, "before_sequence": 100},
        )
        assert page1.status_code == 200
        page1_data = page1.json()

        if not page1_data["has_more"]:
            pytest.skip("Not enough messages for pagination test")

        # Second page: get messages before first page's first sequence
        first_seq = page1_data["first_sequence"]
        page2 = await authenticated_async_client.get(
            f"/api/v1/agent/conversations/{conversation_id}/messages",
            params={
                "project_id": project_id,
                "limit": 5,
                "before_sequence": first_seq,
            },
        )

        # Assert
        assert page2.status_code == 200
        page2_data = page2.json()

        # No overlap between pages
        page1_sequences = {e["sequenceNumber"] for e in page1_data["timeline"]}
        page2_sequences = {e["sequenceNumber"] for e in page2_data["timeline"]}
        assert page1_sequences.isdisjoint(page2_sequences)

        # Page 2 events are all earlier than page 1 events
        if page1_sequences and page2_sequences:
            assert max(page2_sequences) < min(page1_sequences)

    @pytest.mark.asyncio
    async def test_get_messages_limit_validation(self, authenticated_async_client, conversation_with_events):
        """Test that limit parameter is validated"""
        # Arrange
        conversation_id = conversation_with_events["conversation_id"]
        project_id = conversation_with_events["project_id"]

        # Act - Request with limit exceeding maximum
        response = await authenticated_async_client.get(
            f"/api/v1/agent/conversations/{conversation_id}/messages",
            params={"project_id": project_id, "limit": 1000},  # Exceeds max of 500
        )

        # Assert - Should be rejected with validation error
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_get_messages_empty_response(self, authenticated_async_client, test_project_db):
        """Test getting messages from a non-existent conversation"""
        # Arrange
        conversation_id = "nonexistent_conv"

        # Act
        response = await authenticated_async_client.get(
            f"/api/v1/agent/conversations/{conversation_id}/messages",
            params={"project_id": test_project_db.id},
        )

        # Assert - Since conversation doesn't exist, should get 404
        # But if the endpoint creates it implicitly, we expect empty timeline
        # For now, let's check the response status
        # The actual behavior depends on the API design
        if response.status_code == 404:
            assert True  # Expected: conversation not found
        else:
            data = response.json()
            assert "timeline" in data
            assert data["timeline"] == []
