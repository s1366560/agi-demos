from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from src.application.services.conversation_events import (
    build_conversation_created_payload,
    publish_conversation_created,
)
from src.domain.model.agent import Conversation, ConversationStatus


def _conversation() -> Conversation:
    return Conversation(
        id="conversation-1",
        project_id="project-1",
        tenant_id="tenant-1",
        user_id="user-1",
        title="New Conversation",
        status=ConversationStatus.ACTIVE,
        created_at=datetime(2026, 5, 13, tzinfo=UTC),
    )


@pytest.mark.unit
def test_build_conversation_created_payload() -> None:
    payload = build_conversation_created_payload(_conversation())

    assert payload == {
        "conversation_id": "conversation-1",
        "project_id": "project-1",
        "tenant_id": "tenant-1",
        "title": "New Conversation",
        "status": "active",
        "created_at": "2026-05-13T00:00:00+00:00",
    }


@pytest.mark.unit
async def test_publish_conversation_created_uses_project_stream() -> None:
    conversation = _conversation()
    redis_client = object()

    with patch(
        "src.application.services.conversation_events.RedisUnifiedEventBusAdapter"
    ) as bus_class:
        bus = bus_class.return_value
        bus.publish = AsyncMock()

        await publish_conversation_created(
            redis_client=redis_client,  # type: ignore[arg-type]
            conversation=conversation,
        )

    bus_class.assert_called_once_with(redis_client)
    bus.publish.assert_awaited_once()
    envelope, routing_key = bus.publish.await_args.args
    assert routing_key == "project:project-1:conversation_created"
    assert envelope.event_type == "conversation_created"
    assert envelope.payload["conversation_id"] == "conversation-1"
    assert envelope.payload["project_id"] == "project-1"


@pytest.mark.unit
async def test_publish_conversation_created_is_best_effort() -> None:
    with patch(
        "src.application.services.conversation_events.RedisUnifiedEventBusAdapter"
    ) as bus_class:
        bus = bus_class.return_value
        bus.publish = AsyncMock(side_effect=RuntimeError("redis unavailable"))

        await publish_conversation_created(
            redis_client=object(),  # type: ignore[arg-type]
            conversation=_conversation(),
        )

    bus.publish.assert_awaited_once()
