"""Stopping execution must preserve the bridge that delivers its terminal event."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.application.services.agent import runtime_cancellation
from src.infrastructure.adapters.primary.web.websocket.handlers import chat_handler


@pytest.mark.unit
@pytest.mark.parametrize("runtime_stopped", [True, False])
async def test_stop_preserves_subscription_and_requires_real_execution(
    monkeypatch: pytest.MonkeyPatch, runtime_stopped: bool
) -> None:
    conversation = SimpleNamespace(id="c", tenant_id="t", user_id="u")

    @asynccontextmanager
    async def authority(*_args, **_kwargs):
        yield SimpleNamespace(
            service=SimpleNamespace(find_by_id=AsyncMock(return_value=conversation))
        )

    monkeypatch.setattr(chat_handler, "conversation_access_application_authority_v2", authority)
    monkeypatch.setattr(
        runtime_cancellation,
        "cancel_conversation_runtime",
        AsyncMock(return_value=SimpleNamespace(cancelled=runtime_stopped, ray_error=None)),
    )
    bridge = Mock()
    manager = SimpleNamespace(bridge_tasks={"s": {"c": bridge}})
    context = SimpleNamespace(
        session_id="s",
        tenant_id="t",
        user_id="u",
        connection_manager=manager,
        send_ack=AsyncMock(),
        send_error=AsyncMock(),
    )
    await chat_handler.StopSessionHandler().handle(context, {"conversation_id": "c"})
    bridge.cancel.assert_not_called()
    assert manager.bridge_tasks["s"]["c"] is bridge
    assert context.send_ack.await_count == int(runtime_stopped)
    assert context.send_error.await_count == int(not runtime_stopped)
