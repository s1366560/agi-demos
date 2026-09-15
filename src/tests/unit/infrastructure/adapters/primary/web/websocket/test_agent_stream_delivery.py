"""Exact socket/message/cursor delivery across overlapping original and recovery streams."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.adapters.primary.web.websocket.connection_manager import ConnectionManager


async def manager_with_socket():
    dispatcher = SimpleNamespace(enqueue=AsyncMock(return_value=True))
    manager = ConnectionManager(
        SimpleNamespace(
            get_dispatcher=AsyncMock(return_value=dispatcher), cleanup_session=AsyncMock()
        )
    )
    manager.active_connections["socket"] = object()
    await manager.subscribe("socket", "cid")
    await manager.subscribe("socket", "sibling")
    return manager, dispatcher


def frame(counter=1):
    return {
        "type": "text_end",
        "event_time_us": 100,
        "event_counter": counter,
        "data": {"full_text": "real result"},
    }


@pytest.mark.unit
async def test_concurrent_sources_enqueue_exact_cursor_once():
    manager, dispatcher = await manager_with_socket()
    await asyncio.gather(
        manager.broadcast_agent_stream_event("cid", frame(), message_id="turn"),
        manager.send_agent_stream_event("socket", "cid", frame(), message_id="turn"),
    )
    assert dispatcher.enqueue.await_count == 1


@pytest.mark.unit
async def test_late_cursor_and_different_message_or_conversation_are_not_dropped():
    manager, dispatcher = await manager_with_socket()
    for cid, message, counter in [
        ("cid", "turn", 3),
        ("cid", "turn", 1),
        ("cid", "other-turn", 1),
        ("sibling", "turn", 1),
    ]:
        assert await manager.send_agent_stream_event(
            "socket", cid, frame(counter), message_id=message
        )
    assert dispatcher.enqueue.await_count == 4


@pytest.mark.unit
@pytest.mark.parametrize("error", [False, True])
async def test_failed_enqueue_does_not_mark_event_delivered(error):
    manager, dispatcher = await manager_with_socket()
    dispatcher.enqueue.side_effect = [RuntimeError("closed") if error else False, True]
    if error:
        with pytest.raises(RuntimeError):
            await manager.send_agent_stream_event("socket", "cid", frame(), message_id="turn")
    else:
        assert not await manager.send_agent_stream_event(
            "socket", "cid", frame(), message_id="turn"
        )
    assert await manager.send_agent_stream_event("socket", "cid", frame(), message_id="turn")
    assert dispatcher.enqueue.await_count == 2


@pytest.mark.unit
async def test_disconnect_clears_only_its_delivery_state():
    manager, dispatcher = await manager_with_socket()
    await manager.send_agent_stream_event("socket", "cid", frame(), message_id="turn")
    await manager.disconnect("socket")
    assert "socket" not in manager._stream_delivered
    assert "socket" not in manager._stream_delivery_locks
    assert not await manager.send_agent_stream_event("socket", "cid", frame(), message_id="turn")
    assert dispatcher.enqueue.await_count == 1


@pytest.mark.unit
async def test_explicit_cursor_resubscribe_replaces_only_this_socket_consumer():
    manager, _ = await manager_with_socket()
    blocker = asyncio.Event()

    def task():
        return asyncio.create_task(blocker.wait())

    await manager.try_start_bridge_task("socket", "cid", task, bridge_message_id="turn")
    old = manager.bridge_tasks["socket"]["cid"]
    try:
        assert await manager.try_start_bridge_task(
            "socket", "cid", task, bridge_message_id="turn", replace_existing=True
        )
        assert manager.bridge_tasks["socket"]["cid"] is not old
        await asyncio.gather(old, return_exceptions=True)
        assert old.cancelled()
    finally:
        await manager.disconnect("socket")
