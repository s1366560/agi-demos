"""A completed parent must see peer terminal events without another model turn."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.domain.model.agent.spawn_record import SpawnRecord
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent,
    AgentRunAuthorityModel,
    Conversation,
)
from src.infrastructure.plugins.v2.session_event_log import SessionEventLogServiceV2
from src.infrastructure.plugins.v2.session_event_log_store import SqlSessionEventLogStoreV2
from src.tests.unit.routers.agent.test_chat_run_permission_guard_v2 import (  # noqa: F401
    chat_guard_case,
    staged,
    verified,
)


@pytest.mark.parametrize(
    ("outcome", "boundary"),
    [
        ("completed", "valid"),
        ("failed", "valid"),
        ("cancelled", "valid"),
        ("completed", "owner"),
        ("completed", "project"),
        ("completed", "spawn-child"),
        ("completed", "spawn-agent"),
        ("completed", "spawn-project"),
        ("completed", "spawn-parent"),
        ("running", "active"),
    ],
)
async def test_peer_terminal_reaches_completed_parent_without_polling(  # noqa: PLR0915
    chat_guard_case,  # noqa: F811
    test_engine,
    test_db,
    monkeypatch,
    outcome,
    boundary,
):
    from src.infrastructure.agent.actor.peer_terminal_projection_v2 import project_peer_terminal_v2
    from src.infrastructure.plugins.v2.boundary import current_operation_context_v2

    async with chat_guard_case() as (child_run, _policy):
        child = await test_db.get(Conversation, child_run.conversation_id)
        parent = Conversation(
            id="parent-peer-terminal",
            tenant_id=child.tenant_id,
            project_id=child.project_id,
            user_id=child.user_id,
            title="Completed parent",
        )
        test_db.add(parent)
        test_db.add(
            AgentRunAuthorityModel(
                id="parent-completed-run",
                tenant_id=parent.tenant_id,
                project_id=parent.project_id,
                conversation_id=parent.id,
                run_kind="chat",
                idempotency_key="parent-completed",
                message_id="parent-completed",
                request_message="Parent already finished",
                status="completed",
                revision=1,
                permission_profile="read_only",
                authorization_snapshot={},
                completed_at=datetime.now(UTC),
            )
        )
        child.meta = {"spawned_agent_id": "child-agent", "spawned_by_agent_id": "parent-agent"}
        child.parent_conversation_id = parent.id
        child_run.status = outcome
        child_run.completed_at = datetime.now(UTC)
        test_db.add(child_run)
        await test_db.commit()
        sessions = async_sessionmaker(test_engine, expire_on_commit=False)
        monkeypatch.setattr(
            "src.infrastructure.plugins.v2.session_event_log_store.async_session_factory", sessions
        )
        operation = current_operation_context_v2()
        store = SessionEventLogServiceV2(
            strategy="ordered-sql-event-log",
            store=SqlSessionEventLogStoreV2(),
            generation_resolver=lambda: operation.descriptor,
        )
        spawn = SpawnRecord(
            parent_agent_id="parent-agent",
            child_agent_id="child-agent",
            child_session_id=child.id,
            project_id=child.project_id,
        )
        from dataclasses import replace

        from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

        if boundary == "owner":
            parent.user_id = "not-the-owner"
        if boundary == "project":
            parent.project_id = "not-the-project"
        replacements = {
            "spawn-child": {"child_session_id": "sibling"},
            "spawn-agent": {"child_agent_id": "sibling-agent"},
            "spawn-project": {"project_id": "other-project"},
            "spawn-parent": {"parent_agent_id": "other-parent"},
        }
        if boundary in replacements:
            spawn = replace(spawn, **replacements[boundary])
        await test_db.commit()
        redis = SimpleNamespace(eval=AsyncMock(return_value=1))
        if boundary not in {"valid", "active"}:
            with pytest.raises(RuntimeV2Error, match="scope mismatch"):
                await project_peer_terminal_v2(
                    run_id=child_run.id,
                    operation=operation,
                    spawn=spawn,
                    event_log=store,
                    redis_client=redis,
                    sessions=sessions,
                )
            assert not redis.eval.called
            assert not list(
                (
                    await test_db.scalars(
                        select(AgentExecutionEvent).where(
                            AgentExecutionEvent.conversation_id == parent.id
                        )
                    )
                ).all()
            )
            return
        if boundary == "active":
            await project_peer_terminal_v2(
                run_id=child_run.id,
                operation=operation,
                spawn=spawn,
                event_log=store,
                redis_client=redis,
                sessions=sessions,
            )
            assert not redis.eval.called
            return
        for _ in range(2):
            await project_peer_terminal_v2(
                run_id=child_run.id,
                operation=operation,
                spawn=spawn,
                event_log=store,
                redis_client=redis,
                sessions=sessions,
            )
        events = list(
            (
                await test_db.scalars(
                    select(AgentExecutionEvent).where(
                        AgentExecutionEvent.conversation_id == parent.id
                    )
                )
            ).all()
        )
        assert len(events) == 1
        data = events[0].event_data
        assert data["child_session_id"] == child.id
        assert data["child_run_id"] == child_run.id
        assert data["spawn_id"] == spawn.id
        assert data["status"] == outcome
        assert data.get("result", "") == ""
        assert redis.eval.await_count == 2  # Redis atomically deduplicates the exact run key.
        frame = json.loads(redis.eval.call_args.args[-2])
        assert frame["conversation_id"] == parent.id
        assert frame["data"]["session_id"] == child.id
        from src.infrastructure.agent.actor.execution import _settle_root_run_authority

        settled_publisher = AsyncMock()
        monkeypatch.setattr(
            "src.infrastructure.agent.actor.execution.async_session_factory", sessions
        )
        monkeypatch.setattr(
            "src.infrastructure.agent.actor.peer_terminal_projection_v2.publish_settled_peer_terminal_v2",
            settled_publisher,
        )
        await _settle_root_run_authority(
            tenant_id=child.tenant_id,
            project_id=child.project_id,
            conversation_id=child.id,
            run_id=child_run.id,
            outcome="success",
        )
        settled_publisher.assert_awaited_once_with(child_run.id)
        async with sessions() as check:
            persisted = await check.get(AgentRunAuthorityModel, child_run.id)
            assert persisted.status == outcome
        settled_publisher.reset_mock()
        await _settle_root_run_authority(
            tenant_id="other-tenant",
            project_id=child.project_id,
            conversation_id=child.id,
            run_id=child_run.id,
            outcome="success",
        )
        settled_publisher.assert_not_called()

        from contextlib import asynccontextmanager

        from src.domain.events.envelope import EventEnvelope
        from src.infrastructure.adapters.primary.web.websocket.lifecycle_stream_bridge_v2 import (
            _relay_lifecycle_v2,
            lifecycle_message_access_v2,
        )

        @asynccontextmanager
        async def fresh():
            yield SimpleNamespace(db=test_db)

        context = SimpleNamespace(
            tenant_id=child.tenant_id,
            user_id=child.user_id,
            fresh_db_context=fresh,
            session_id="test-socket",
            connection_manager=SimpleNamespace(
                status_tasks={}, unsubscribe_lifecycle_state=AsyncMock()
            ),
        )
        serialized = redis.eval.call_args.args[-1]
        envelope = EventEnvelope.from_json(serialized)
        notification = envelope.payload
        from pathlib import Path

        from src.infrastructure.adapters.primary.web.routers.agent.messages import _build_timeline

        history = _build_timeline(events, {}, {}, {}, {}, {}, {})
        assert history[0]["payload"]["child_run_id"] == child_run.id
        assert history[0]["payload"]["spawn_id"] == spawn.id
        if outcome == "completed":
            Path(
                "artifacts/desktop-functional-20260914/cloud-peer-terminal-renderer-fixture.json"
            ).write_text(json.dumps({"envelope": notification, "history": history}, default=str))
        assert await lifecycle_message_access_v2(context, child.project_id, notification)
        corrupted = json.loads(json.dumps(notification))
        corrupted["data"]["data"]["spawn_id"] = "sibling-spawn"
        assert not await lifecycle_message_access_v2(context, child.project_id, corrupted)
        corrupted = json.loads(json.dumps(notification))
        corrupted["data"]["data"]["child_run_id"] = "other-run"
        assert not await lifecycle_message_access_v2(context, child.project_id, corrupted)
        sent = []
        import asyncio

        async def send(payload):
            sent.append(payload)
            raise asyncio.CancelledError

        context.send_json = send
        transport = SimpleNamespace(
            xread=AsyncMock(return_value=[("stream", [("1-0", {"data": serialized})])])
        )
        with pytest.raises(asyncio.CancelledError):
            await _relay_lifecycle_v2(context, child.project_id, transport, "stream", "0-0")
        assert len(sent) == 1
        assert sent[0]["data"]["data"]["child_run_id"] == child_run.id
        if outcome == "completed":
            await _assert_peer_notification_over_real_websocket(
                sessions, child, redis.eval.call_args.args
            )
            next_run = AgentRunAuthorityModel(
                id="later-peer-run",
                tenant_id=child.tenant_id,
                project_id=child.project_id,
                conversation_id=child.id,
                run_kind="chat",
                idempotency_key="next-turn",
                message_id="next-turn",
                request_message="Later turn",
                status="failed",
                revision=1,
                permission_profile="read_only",
                authorization_snapshot={},
                completed_at=datetime.now(UTC),
            )
            test_db.add(next_run)
            await test_db.commit()
            await project_peer_terminal_v2(
                run_id=next_run.id,
                operation=operation,
                spawn=spawn,
                event_log=store,
                redis_client=redis,
                sessions=sessions,
            )
            rows = list(
                (
                    await test_db.scalars(
                        select(AgentExecutionEvent).where(
                            AgentExecutionEvent.conversation_id == parent.id
                        )
                    )
                ).all()
            )
            assert {row.event_data["child_run_id"] for row in rows} == {child_run.id, next_run.id}


async def test_peer_terminal_redis_delivery_is_once_per_run_and_keeps_later_turn():
    from uuid import uuid4

    from redis.asyncio import Redis

    from src.configuration.config import get_settings
    from src.infrastructure.agent.actor.peer_terminal_projection_v2 import _PUBLISH_ONCE

    client = Redis.from_url(get_settings().redis_url)
    namespace = f"qa:peer-terminal:{uuid4()}"
    stream, first, second = f"{namespace}:events", f"{namespace}:run1", f"{namespace}:run2"
    try:
        assert await client.eval(_PUBLISH_ONCE, 2, first, stream, '{"child_run_id":"first"}') == 1
        assert await client.eval(_PUBLISH_ONCE, 2, first, stream, '{"child_run_id":"first"}') == 0
        assert await client.eval(_PUBLISH_ONCE, 2, second, stream, '{"child_run_id":"second"}') == 1
        rows = await client.xrange(stream)
        assert len(rows) == 2
        assert [json.loads(fields[b"data"])["child_run_id"] for _, fields in rows] == [
            "first",
            "second",
        ]
    finally:
        await client.delete(stream, first, second)
        await client.aclose()


async def _assert_peer_notification_over_real_websocket(sessions, child, command):  # noqa: PLR0915
    import asyncio
    import socket
    from uuid import uuid4

    import uvicorn
    import websockets
    from fastapi import FastAPI, WebSocket
    from redis.asyncio import Redis

    from src.configuration.config import get_settings
    from src.infrastructure.adapters.primary.web.websocket.connection_manager import (
        ConnectionManager,
    )
    from src.infrastructure.adapters.primary.web.websocket.lifecycle_stream_bridge_v2 import (
        start_lifecycle_bridge_v2,
        stop_lifecycle_bridge_v2,
    )
    from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext

    client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    manager = ConnectionManager()
    app = FastAPI()
    task_id = str(uuid4())

    class Container:
        def with_db(self, _db):
            return self

        def redis(self):
            return client

    @app.websocket("/events")
    async def endpoint(websocket: WebSocket):
        await websocket.accept()
        async with sessions() as db:
            context = MessageContext(
                websocket=websocket,
                user_id=child.user_id,
                tenant_id=child.tenant_id,
                session_id=task_id,
                db=db,
                container=Container(),
                session_factory=sessions,
                _connection_manager=manager,
            )
            await start_lifecycle_bridge_v2(context, child.project_id)
            await context.send_ack("subscribe_lifecycle_state")
            try:
                await websocket.receive_text()
            finally:
                await stop_lifecycle_bridge_v2(context, child.project_id)

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
    serving = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        while not server.started:
            await asyncio.sleep(0.01)
        async with websockets.connect(f"ws://127.0.0.1:{port}/events") as websocket:
            assert json.loads(await websocket.recv())["type"] == "ack"
            assert await client.eval(*command) == 1
            event = json.loads(await asyncio.wait_for(websocket.recv(), 3))
            assert event["type"] == "agent_lifecycle"
            assert event["data"]["data"]["child_session_id"] == child.id
            assert await client.eval(*command) == 0
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(websocket.recv(), 0.1)
            await websocket.send("done")
    finally:
        server.should_exit = True
        await serving
        # These exact keys belong only to this isolated SQL fixture and its peer turn.
        await client.delete(*command[2:5])
        await client.aclose()
