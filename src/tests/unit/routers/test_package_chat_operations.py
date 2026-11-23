"""The package sees only text and receipts from its authenticated project and turn."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request, WebSocket
from pydantic import ValidationError

from src.host.operations.application_commands import PackageOperationContext
from src.infrastructure.adapters.primary.web.routers.agent import package_chat_operations as ops
from src.infrastructure.adapters.primary.web.routers.agent.package_chat_stream import stream_turn
from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
    OptionalBusinessError,
    ScopeBindingV2,
)

pytestmark = pytest.mark.unit


def context(app, db=None):
    request = Request(
        {"type": "http", "app": app, "headers": [(b"authorization", b"Bearer fixture-only")]}
    )
    return PackageOperationContext(
        request, db, SimpleNamespace(id="u"), ScopeBindingV2(tenant_id="t", project_id="p")
    )


async def test_turn_stream_dispatches_fixed_cloud_operation_and_projects_own_events():
    app = FastAPI()
    inbound = []

    @app.websocket("/api/v1/agent/ws")
    async def socket(ws: WebSocket):
        assert ws.headers.get("authorization") == "Bearer fixture-only"
        await ws.accept()
        await ws.send_json({"type": "connected", "data": {"user_id": "u"}})
        turn = await ws.receive_json()
        inbound.append(turn)

        async def send(kind, **fields):
            await ws.send_json({"type": kind, "conversation_id": "c", **fields})

        await send("ack", run_id="r", run_revision=1, message_id="m")
        await send("text_delta", run_id="other", data={"delta": "other turn"})
        await send("text_delta", run_id="r", data={"delta": "text", "private": "internal"})
        await send("complete", run_id="r")
        await ws.receive()

    frames = []

    async def progress(frame):
        frames.append(frame)

    result = await stream_turn(
        context(app), {"conversation_id": "c", "message": "test", "message_id": "m"}, progress
    )
    assert result == {"run_id": "r", "status": "complete"}
    assert frames == [
        {"type": "accepted", "revision": 1, "run_id": "r"},
        {"type": "text_delta", "text": "text"},
    ]
    assert inbound == [
        {
            "type": "send_message",
            "project_id": "p",
            "execution_target": "cloud",
            "conversation_id": "c",
            "message": "test",
            "message_id": "m",
        }
    ]


async def test_chat_operations_reject_cross_project_before_calling_handler(db_session):
    ctx = context(FastAPI(), db_session)
    for op, payload in [
        (ops.history, {"conversation_id": "other"}),
        (ops.cancel, {"conversation_id": "other", "run_id": "run", "expected_revision": 1}),
        (ops.turn, {"conversation_id": "other", "message": "hi", "message_id": "m"}),
    ]:
        with pytest.raises(OptionalBusinessError, match="conversation unavailable"):
            await op(ctx, payload, None)
    with pytest.raises(ValidationError):
        await ops.turn(
            ctx,
            {"conversation_id": "c", "message_id": "m", "message": "hi", "permission_mode": "full"},
            None,
        )
    with pytest.raises(ValidationError):
        await ops.history(ctx, {"conversation_id": "../secrets"}, None)
