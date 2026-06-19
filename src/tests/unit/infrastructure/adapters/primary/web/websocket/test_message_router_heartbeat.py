"""Tests for agent websocket heartbeat routing."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.infrastructure.adapters.primary.web.websocket.message_router import MessageRouter


async def test_message_router_accepts_heartbeat_and_ping_alias() -> None:
    router = MessageRouter()
    context = SimpleNamespace(send_json=AsyncMock(), send_error=AsyncMock())

    await router.route(context, {"type": "heartbeat"})
    await router.route(context, {"type": "ping"})

    assert context.send_json.await_count == 2
    sent_messages = [call.args[0] for call in context.send_json.await_args_list]
    assert [message["type"] for message in sent_messages] == ["pong", "pong"]
    context.send_error.assert_not_awaited()
