"""A subscribed recovery stream survives a persisted ASK answered over HTTP."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.domain.model.agent.hitl.hitl_types import HITLType
from src.infrastructure.adapters.primary.web.routers.agent import hitl
from src.infrastructure.adapters.primary.web.websocket import connection_manager
from src.infrastructure.adapters.primary.web.websocket.handlers.chat_handler import (
    stream_hitl_response_to_websocket,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    ToolExecutionRecord,
)
from src.infrastructure.agent.hitl import coordinator
from src.infrastructure.agent.hitl.hitl_strategies import PermissionStrategy
from src.infrastructure.plugins.v2 import session_event_log_store
from src.tests.unit.services.test_agent_service_connect_chat_stream import _build_service


@pytest.mark.unit
async def test_reconnected_permission_stream_delivers_observe_and_final_after_http_allow(  # noqa: PLR0915
    test_db,
    test_engine,
    test_user,
    test_project_db,
    monkeypatch,
):
    cid = "reconnected-permission-conversation"
    test_db.add(
        Conversation(
            id=cid,
            tenant_id=test_project_db.tenant_id,
            project_id=test_project_db.id,
            user_id=test_user.id,
            title="Reconnect",
            current_mode="build",
        )
    )
    await test_db.commit()
    request = PermissionStrategy().create_request(
        conversation_id=cid,
        request_data={
            "tool_name": "agent_spawn",
            "action": "execute",
            "description": "Start scoped child",
            "risk_level": "medium",
            "allow_remember": False,
        },
    )
    monkeypatch.setattr(
        coordinator,
        "async_session_factory",
        async_sessionmaker(test_engine, expire_on_commit=False),
    )
    await coordinator._persist_hitl_request(
        request_id=request.request_id,
        hitl_type=HITLType.PERMISSION,
        conversation_id=cid,
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        message_id=None,
        timeout_seconds=60,
        type_data=request.type_specific_data,
        created_at=datetime.now(UTC),
    )
    # Match PostgreSQL timezone-aware DateTime behavior at the SQLite adapter seam.
    from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
        SqlHITLRequestRepository,
    )

    original_to_domain = SqlHITLRequestRepository._to_domain

    def aware_request(self, record):
        result = original_to_domain(self, record)
        if result.expires_at is not None and result.expires_at.tzinfo is None:
            result.expires_at = result.expires_at.replace(tzinfo=UTC)
        return result

    monkeypatch.setattr(SqlHITLRequestRepository, "_to_domain", aware_request)
    asked = asyncio.Event()
    resumed = asyncio.Event()
    frames = []

    async def broadcast(session_id, conversation_id, event, **kwargs):
        assert session_id == "socket"
        assert conversation_id == cid
        frames.append(event)
        if event["type"] == "permission_asked":
            asked.set()

    manager = SimpleNamespace(
        is_subscribed=lambda sid, conversation: sid == "socket" and conversation == cid,
        broadcast_to_conversation=broadcast,
        send_to_session=AsyncMock(),
        send_agent_stream_event=broadcast,
    )
    monkeypatch.setattr(connection_manager, "get_connection_manager", lambda: manager)

    monkeypatch.setattr(
        session_event_log_store,
        "async_session_factory",
        async_sessionmaker(test_engine, expire_on_commit=False),
    )
    producer = session_event_log_store.SqlSessionEventLogStoreV2()

    async def stream(*args, **kwargs):
        for count, kind in enumerate(("permission_asked", "observe", "text_end", "complete")):
            if kind == "observe":
                await resumed.wait()
            event = {
                "type": kind,
                "data": {
                    "request_id": request.request_id,
                    "execution_id": "same-call",
                    "message_id": "original-turn",
                    "conversation_id": cid,
                    "tool_execution_id": "reconnected-tool",
                    "call_id": "same-call",
                    "tool_name": "agent_spawn",
                    "result": "child started",
                    "status": "success",
                    "full_text": "Actual final",
                    "content": "Actual final",
                },
                "event_time_us": 1000,
                "event_counter": count,
            }
            await producer.append_stream_events(
                conversation_id=cid, message_id="original-turn", events=[event], correlation_id=None
            )
            yield {"id": f"1000-{count}", "data": event}

    async def publish(**payload):
        assert payload["tenant_id"] == test_project_db.tenant_id
        assert payload["project_id"] == test_project_db.id
        assert payload["conversation_id"] == cid
        assert payload["request_id"] == request.request_id
        resumed.set()
        return True

    monkeypatch.setattr(hitl, "_publish_hitl_response_to_redis", publish)
    app = FastAPI()
    app.include_router(hitl.router, prefix="/hitl")
    app.dependency_overrides[hitl.get_current_user] = lambda: test_user
    app.dependency_overrides[hitl.get_current_user_tenant] = lambda: test_project_db.tenant_id
    app.dependency_overrides[hitl.get_db] = lambda: test_db
    service = _build_service()
    service._event_bus.stream_read = stream
    service._read_delayed_events = AsyncMock(return_value=[])
    bridge = asyncio.create_task(
        stream_hitl_response_to_websocket(
            service,
            "socket",
            cid,
            message_id="original-turn",
            replay_from_db=False,
        )
    )
    try:
        await asyncio.wait_for(asked.wait(), 1)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            result = await client.post(
                "/hitl/respond",
                json={
                    "request_id": request.request_id,
                    "hitl_type": "permission",
                    "expected_revision": 1,
                    "idempotency_key": "reconnect-http-allow",
                    "response_data": {"action": "allow", "granted": True, "scope": "once"},
                },
            )
        assert result.status_code == 200, result.text
        await asyncio.wait_for(bridge, 1)
        assert [event["type"] for event in frames] == [
            "permission_asked",
            "observe",
            "text_end",
            "complete",
        ]
        assert [event["event_counter"] for event in frames] == [0, 1, 2, 3]
        test_db.expire_all()
        record = await test_db.get(ToolExecutionRecord, "reconnected-tool")
        assert record.status == "success"
        assert record.tool_output == "child started"
        assert record.message_id == "original-turn"
    finally:
        bridge.cancel()
        await asyncio.gather(bridge, return_exceptions=True)
