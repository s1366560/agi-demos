"""Tests for the typed unknown-message-type router rejection."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.adapters.primary.web.websocket.message_router import MessageRouter

pytestmark = pytest.mark.unit


async def test_unknown_message_type_echoes_code_and_message_id() -> None:
    router = MessageRouter()
    context = SimpleNamespace(send_json=AsyncMock(), send_error=AsyncMock())

    await router.route(
        context,
        {
            "type": "steer_message",
            "conversation_id": "conversation-1",
            "message_id": "desktop-steer-1",
        },
    )

    context.send_error.assert_awaited_once_with(
        "Unknown message type: steer_message",
        code="UNKNOWN_MESSAGE_TYPE",
        conversation_id="conversation-1",
        extra={"message_id": "desktop-steer-1"},
    )


async def test_unknown_message_type_without_message_id_omits_extra() -> None:
    router = MessageRouter()
    context = SimpleNamespace(send_json=AsyncMock(), send_error=AsyncMock())

    await router.route(context, {"type": "does_not_exist"})

    context.send_error.assert_awaited_once_with(
        "Unknown message type: does_not_exist",
        code="UNKNOWN_MESSAGE_TYPE",
        conversation_id=None,
        extra=None,
    )


async def test_unknown_message_type_ignores_non_string_message_id() -> None:
    router = MessageRouter()
    context = SimpleNamespace(send_json=AsyncMock(), send_error=AsyncMock())

    await router.route(context, {"type": "does_not_exist", "message_id": 42})

    context.send_error.assert_awaited_once_with(
        "Unknown message type: does_not_exist",
        code="UNKNOWN_MESSAGE_TYPE",
        conversation_id=None,
        extra=None,
    )
