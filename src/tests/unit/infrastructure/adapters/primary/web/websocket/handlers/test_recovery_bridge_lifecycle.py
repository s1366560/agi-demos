"""Real manager cancellation owns a paused bridge, independent of HITL transport."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.adapters.primary.web.websocket import connection_manager
from src.infrastructure.adapters.primary.web.websocket.handlers.chat_handler import (
    stream_hitl_response_to_websocket,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    "asked_type", ["permission_asked", "decision_asked", "clarification_asked", "env_var_requested"]
)
@pytest.mark.parametrize("action", ["unsubscribe", "replace"])
async def test_paused_bridge_lives_until_manager_cancels(asked_type, action, monkeypatch):
    dispatcher = SimpleNamespace(enqueue=AsyncMock(return_value=True))
    manager = connection_manager.ConnectionManager(
        dispatcher_manager=SimpleNamespace(get_dispatcher=AsyncMock(return_value=dispatcher))
    )
    socket = SimpleNamespace(send_json=AsyncMock())
    manager.active_connections["socket"] = socket
    await manager.subscribe("socket", "cid")
    monkeypatch.setattr(connection_manager, "get_connection_manager", lambda: manager)
    waiting = asyncio.Event()
    closed = asyncio.Event()
    blocker = asyncio.Event()

    async def stream(**kwargs):
        assert kwargs["message_id"] == "original"
        try:
            yield {"type": asked_type, "data": {"request_id": "exact-request"}}
            waiting.set()
            await blocker.wait()
            yield {"type": "observe", "data": {"result": "must not arrive"}}
        finally:
            closed.set()

    def factory():
        return asyncio.create_task(
            stream_hitl_response_to_websocket(
                SimpleNamespace(connect_chat_stream=stream), "socket", "cid", message_id="original"
            )
        )

    assert await manager.try_start_bridge_task(
        "socket", "cid", factory, bridge_message_id="original"
    )
    original = manager.bridge_tasks["socket"]["cid"]
    replacement = None
    try:
        await asyncio.wait_for(waiting.wait(), 1)
        assert not original.done()
        assert not await manager.try_start_bridge_task(
            "socket", "cid", factory, bridge_message_id="original"
        )
        if action == "unsubscribe":
            await manager.unsubscribe("socket", "cid")
        else:

            def replace():
                return asyncio.create_task(blocker.wait())

            assert await manager.try_start_bridge_task(
                "socket", "cid", replace, bridge_message_id="new-turn"
            )
            replacement = manager.bridge_tasks["socket"]["cid"]
        await asyncio.wait_for(closed.wait(), 1)
        await original
        assert [call.args[0]["type"] for call in dispatcher.enqueue.await_args_list] == [asked_type]
    finally:
        original.cancel()
        if replacement:
            replacement.cancel()
        await asyncio.gather(
            original, *([replacement] if replacement else []), return_exceptions=True
        )


@pytest.mark.unit
@pytest.mark.parametrize("terminal", ["complete", "error"])
async def test_bridge_stops_only_at_real_terminal(terminal, monkeypatch):
    manager = SimpleNamespace(
        is_subscribed=lambda *args: True,
        broadcast_to_conversation=AsyncMock(),
        send_agent_stream_event=AsyncMock(),
        send_to_session=AsyncMock(),
    )
    monkeypatch.setattr(connection_manager, "get_connection_manager", lambda: manager)

    async def stream(**kwargs):
        for kind in ["permission_asked", terminal, "observe"]:
            yield {"type": kind, "data": {}}

    await stream_hitl_response_to_websocket(
        SimpleNamespace(connect_chat_stream=stream), "socket", "cid"
    )
    assert [call.args[2]["type"] for call in manager.send_agent_stream_event.await_args_list] == [
        "permission_asked",
        terminal,
    ]


@pytest.mark.unit
async def test_revoked_scope_stops_recovery_before_next_payload(
    test_db, test_user, test_project_db, monkeypatch
):
    from sqlalchemy import delete

    from src.infrastructure.adapters.primary.web.websocket.scoped_session_admission_v2 import (
        authorize_existing_scoped_session_v2,
    )
    from src.infrastructure.adapters.secondary.persistence.models import Conversation, UserProject

    cid = "revocation-stream"
    test_db.add(
        Conversation(
            id=cid,
            user_id=test_user.id,
            tenant_id=test_project_db.tenant_id,
            project_id=test_project_db.id,
            title="Scope",
        )
    )
    await test_db.commit()
    context = SimpleNamespace(db=test_db, user_id=test_user.id, tenant_id=test_project_db.tenant_id)

    async def authorize():
        await authorize_existing_scoped_session_v2(
            context, conversation_id=cid, project_id=test_project_db.id
        )

    manager = SimpleNamespace(
        is_subscribed=lambda *args: True,
        send_agent_stream_event=AsyncMock(),
        send_to_session=AsyncMock(),
    )
    monkeypatch.setattr(connection_manager, "get_connection_manager", lambda: manager)

    async def stream(**kwargs):
        yield {"type": "permission_asked", "data": {"request_id": "permission"}}
        await test_db.execute(
            delete(UserProject).where(
                UserProject.user_id == test_user.id, UserProject.project_id == test_project_db.id
            )
        )
        await test_db.commit()
        yield {"type": "observe", "data": {"result": "must remain private"}}
        yield {"type": "complete", "data": {"content": "private final"}}

    await stream_hitl_response_to_websocket(
        SimpleNamespace(connect_chat_stream=stream), "socket", cid, authorize_delivery=authorize
    )
    assert [call.args[2]["type"] for call in manager.send_agent_stream_event.await_args_list] == [
        "permission_asked"
    ]
    assert manager.send_to_session.await_count == 1
