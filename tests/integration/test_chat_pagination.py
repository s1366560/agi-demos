"""
Integration tests for chat history pagination.

TDD RED Phase: Tests written first for pagination feature.

Requirements:
1. Default limit should be 50 (not 100)
2. API should return has_more for backward pagination
3. Frontend should support loading earlier messages on scroll up
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
@pytest.mark.integration
class TestChatPagination:
    """Test chat history pagination API."""

    async def test_get_messages_default_limit_is_50(
        self,
        async_client: AsyncClient,
        test_token_headers: dict[str, str],
        test_conversation: str,
        test_project: str,
    ):
        """Test that default limit for getting messages is 50."""
        response = await async_client.get(
            f"/api/v1/agent/conversations/{test_conversation}/messages",
            headers=test_token_headers,
            params={"project_id": test_project},
        )

        assert response.status_code == 200
        data = response.json()

        # Should return pagination metadata
        assert "timeline" in data
        assert "total" in data
        assert "has_more" in data
        assert "first_sequence" in data
        assert "last_sequence" in data

        # With limit=50 default, we should get at most 50 events
        assert data["total"] <= 50

    async def test_get_messages_with_custom_limit(
        self,
        async_client: AsyncClient,
        test_token_headers: dict[str, str],
        test_conversation: str,
        test_project: str,
    ):
        """Test that custom limit parameter works."""
        response = await async_client.get(
            f"/api/v1/agent/conversations/{test_conversation}/messages",
            headers=test_token_headers,
            params={"project_id": test_project, "limit": 10},
        )

        assert response.status_code == 200
        data = response.json()

        # Should return at most 10 events
        assert data["total"] <= 10

    async def test_get_messages_backward_pagination_with_before_sequence(
        self,
        async_client: AsyncClient,
        test_token_headers: dict[str, str],
        test_conversation: str,
        test_project: str,
    ):
        """Test backward pagination using before_sequence parameter."""
        # First, get the initial page to find a sequence number
        initial_response = await async_client.get(
            f"/api/v1/agent/conversations/{test_conversation}/messages",
            headers=test_token_headers,
            params={"project_id": test_project, "limit": 10},
        )

        assert initial_response.status_code == 200
        initial_data = initial_response.json()

        if initial_data["timeline"] and initial_data["first_sequence"]:
            # Get events before the first sequence
            first_sequence = initial_data["first_sequence"]
            response = await async_client.get(
                f"/api/v1/agent/conversations/{test_conversation}/messages",
                headers=test_token_headers,
                params={
                    "project_id": test_project,
                    "limit": 10,
                    "before_sequence": first_sequence,
                },
            )

            assert response.status_code == 200
            data = response.json()

            # All returned events should have sequence < before_sequence
            for event in data["timeline"]:
                assert event["sequenceNumber"] < first_sequence

    async def test_get_messages_has_more_indicates_earlier_messages(
        self,
        async_client: AsyncClient,
        test_token_headers: dict[str, str],
        test_conversation: str,
        test_project: str,
    ):
        """Test that has_more correctly indicates if there are earlier messages."""
        response = await async_client.get(
            f"/api/v1/agent/conversations/{test_conversation}/messages",
            headers=test_token_headers,
            params={"project_id": test_project, "limit": 10},
        )

        assert response.status_code == 200
        data = response.json()

        # has_more should be a boolean
        assert isinstance(data["has_more"], bool)

        # If first_sequence > 0, there should be has_more=True
        # If first_sequence == 0 or None, has_more should be False
        if data["first_sequence"] is not None and data["first_sequence"] > 0:
            assert data["has_more"] is True
        else:
            assert data["has_more"] is False

    async def test_get_messages_forward_pagination_with_from_sequence(
        self,
        async_client: AsyncClient,
        test_token_headers: dict[str, str],
        test_conversation: str,
        test_project: str,
    ):
        """Test forward pagination using from_sequence parameter."""
        # Get events starting from sequence 0
        response = await async_client.get(
            f"/api/v1/agent/conversations/{test_conversation}/messages",
            headers=test_token_headers,
            params={
                "project_id": test_project,
                "limit": 10,
                "from_sequence": 0,
            },
        )

        assert response.status_code == 200
        data = response.json()

        # All returned events should have sequence >= from_sequence
        for event in data["timeline"]:
            assert event["sequenceNumber"] >= 0

        # Should be ordered by sequence ascending
        sequences = [e["sequenceNumber"] for e in data["timeline"]]
        assert sequences == sorted(sequences)

    async def test_get_messages_pagination_metadata(
        self,
        async_client: AsyncClient,
        test_token_headers: dict[str, str],
        test_conversation: str,
        test_project: str,
    ):
        """Test that pagination metadata is correctly calculated."""
        response = await async_client.get(
            f"/api/v1/agent/conversations/{test_conversation}/messages",
            headers=test_token_headers,
            params={"project_id": test_project, "limit": 10},
        )

        assert response.status_code == 200
        data = response.json()

        if data["timeline"]:
            # first_sequence should match the first event's sequence
            assert data["first_sequence"] == data["timeline"][0]["sequenceNumber"]

            # last_sequence should match the last event's sequence
            assert data["last_sequence"] == data["timeline"][-1]["sequenceNumber"]

            # total should match the number of events returned
            assert data["total"] == len(data["timeline"])
        else:
            # Empty timeline should have null sequence values
            assert data["first_sequence"] is None
            assert data["last_sequence"] is None
            assert data["total"] == 0


@pytest.mark.asyncio
@pytest.mark.integration
class TestChatPaginationEdgeCases:
    """Test edge cases for chat pagination."""

    async def test_empty_conversation_returns_empty_timeline(
        self,
        async_client: AsyncClient,
        test_token_headers: dict[str, str],
        test_project: str,
        create_test_conversation,
    ):
        """Test that a new conversation returns empty timeline."""
        conv_id = await create_test_conversation(test_project)

        response = await async_client.get(
            f"/api/v1/agent/conversations/{conv_id}/messages",
            headers=test_token_headers,
            params={"project_id": test_project},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["timeline"] == []
        assert data["total"] == 0
        assert data["has_more"] is False
        assert data["first_sequence"] is None
        assert data["last_sequence"] is None

    async def test_limit_validation_max_500(
        self,
        async_client: AsyncClient,
        test_token_headers: dict[str, str],
        test_conversation: str,
        test_project: str,
    ):
        """Test that limit max is 500."""
        response = await async_client.get(
            f"/api/v1/agent/conversations/{test_conversation}/messages",
            headers=test_token_headers,
            params={"project_id": test_project, "limit": 1000},
        )

        # Should return validation error for limit > 500
        assert response.status_code == 422

    async def test_limit_validation_min_1(
        self,
        async_client: AsyncClient,
        test_token_headers: dict[str, str],
        test_conversation: str,
        test_project: str,
    ):
        """Test that limit min is 1."""
        response = await async_client.get(
            f"/api/v1/agent/conversations/{test_conversation}/messages",
            headers=test_token_headers,
            params={"project_id": test_project, "limit": 0},
        )

        # Should return validation error for limit < 1
        assert response.status_code == 422

    async def test_backward_pagination_at_beginning(
        self,
        async_client: AsyncClient,
        test_token_headers: dict[str, str],
        test_conversation: str,
        test_project: str,
    ):
        """Test backward pagination when already at the beginning."""
        # Request events before sequence 1 (should return empty or very few)
        response = await async_client.get(
            f"/api/v1/agent/conversations/{test_conversation}/messages",
            headers=test_token_headers,
            params={
                "project_id": test_project,
                "limit": 10,
                "before_sequence": 1,
            },
        )

        assert response.status_code == 200
        data = response.json()

        # Should not crash, may return empty or events with sequence 0
        assert isinstance(data["timeline"], list)

        # has_more should be False since we're near the beginning
        assert data["has_more"] is False

    async def test_initial_load_fetches_latest_messages(
        self,
        async_client: AsyncClient,
        test_token_headers: dict[str, str],
        test_project: str,
        create_test_conversation,
    ):
        """Test that initial load (from_sequence=0, before_sequence=None) fetches the latest messages.

        When there are many messages, initial load should return the most recent ones,
        not the oldest ones.
        """
        from src.domain.model.agent import AgentExecutionEvent, EventType
        from src.configuration.di_container import DIContainer
        from src.infrastructure.adapters.secondary.persistence.database import get_db
        from datetime import datetime

        # Create a conversation
        conv_id = await create_test_conversation(test_project)

        # Add 100 events to the conversation
        async for db in get_db():
            container = DIContainer(db=db)
            event_repo = container.agent_execution_event_repository()

            for i in range(100):
                event = AgentExecutionEvent(
                    id=f"test-event-{i}",
                    conversation_id=conv_id,
                    message_id=f"test-msg-{i}",
                    event_type=EventType.USER_MESSAGE if i % 2 == 0 else EventType.ASSISTANT_MESSAGE,
                    event_data={"content": f"Test message {i}", "role": "user" if i % 2 == 0 else "assistant"},
                    sequence_number=i + 1,  # Sequences 1-100
                    created_at=datetime.now(),
                )
                await event_repo.save(event)
            await db.commit()

        # Now fetch messages with default parameters (should get latest 50)
        response = await async_client.get(
            f"/api/v1/agent/conversations/{conv_id}/messages",
            headers=test_token_headers,
            params={"project_id": test_project},
        )

        assert response.status_code == 200
        data = response.json()

        # Should return 50 events
        assert data["total"] == 50

        # The events should be the latest ones (sequences 51-100, not 1-50)
        # first_sequence should be around 51 (or higher if there are gaps)
        # last_sequence should be around 100
        assert data["first_sequence"] >= 51, f"Expected first_sequence >= 51, got {data['first_sequence']}"
        assert data["last_sequence"] == 100, f"Expected last_sequence = 100, got {data['last_sequence']}"

        # has_more should be True because there are messages before sequence 51
        assert data["has_more"] is True
