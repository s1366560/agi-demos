"""The package sees only text and receipts from its authenticated project and turn."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request, WebSocket
from pydantic import ValidationError

from plugins.business.agent.backend import chat_operations as ops
from plugins.business.agent.backend.chat_stream import stream_turn
from src.host.operations.application_commands import PackageOperationContext
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
        (ops.rename, {"conversation_id": "other", "title": "new title"}),
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


async def test_device_conversation_rename_survives_history_refresh(db_session):
    from src.host.operations.device_conversations import create_owned, list_owned, rename_owned

    ctx = context(FastAPI(), db_session)
    conversation = await create_owned(ctx, {"title": "Original", "execution_target": "local"}, None)
    result = await rename_owned(
        ctx, {"conversation_id": conversation["id"], "title": "  New  "}, None
    )
    assert result == {"id": conversation["id"], "title": "New"}
    assert (await list_owned(ctx, {}, None))["items"] == [
        {**conversation, "title": "New"},
    ]


async def test_workspace_scoped_create_and_list_are_bound_to_device_owner(db_session, monkeypatch):
    from src.host.operations.device_conversations import create_owned, list_owned
    from src.infrastructure.adapters.primary.web import workspace_authority

    ctx = context(FastAPI(), db_session)
    ctx.user.is_superuser = False
    checked = []

    async def require_scope(request, **scope):
        checked.append(scope)
        if scope["workspace_id"] != "mine":
            raise OptionalBusinessError("forbidden", "workspace unavailable")

    monkeypatch.setattr(workspace_authority, "require_workspace_scope", require_scope)
    await create_owned(ctx, {"title": "Unbound"}, None)
    created = await create_owned(ctx, {"title": "In workspace", "workspace_id": "mine"}, None)
    result = await list_owned(ctx, {"workspace_id": "mine", "conversation_id": created["id"]}, None)
    assert result["items"] == [created]
    with pytest.raises(OptionalBusinessError, match="workspace unavailable"):
        await create_owned(ctx, {"title": "Denied", "workspace_id": "other"}, None)
    assert [scope["workspace_id"] for scope in checked] == ["mine", "mine", "other"]
    assert all(
        scope["tenant_id"] == "t" and scope["project_id"] == "p" and scope["user_id"] == "u"
        for scope in checked
    )


async def test_cloud_workspace_chat_uses_canonical_link_and_handles_deep_bookmark(
    monkeypatch, db_session
):
    ctx = context(FastAPI(), db_session)
    pinned = "workspace-chat:mine:old-conversation"
    requests = []

    async def canonical(_ctx, method, path, **kwargs):
        requests.append((method, path, kwargs))
        if path == "conversations" and method == "GET":
            return {"items": []}
        return {
            "id": pinned,
            "workspace_id": "mine",
            "title": "Pinned",
            "execution_target": "cloud",
        }

    async def owned(_ctx, identifier):
        assert identifier == pinned

    monkeypatch.setattr(ops, "_canonical", canonical)
    monkeypatch.setattr(ops, "_own_conversation", owned)
    await ops.create(ctx, {"title": "Pinned", "workspace_id": "mine"}, None)
    assert requests[-1] == (
        "POST",
        "conversations",
        {
            "body": {
                "project_id": "p",
                "title": "Pinned",
                "workspace_id": "mine",
                "agent_config": {"capability_mode": "work"},
            }
        },
    )
    result = await ops.list_conversations(
        ctx, {"workspace_id": "mine", "conversation_id": pinned}, None
    )
    assert result["items"][0]["id"] == pinned
    assert ("GET", "conversations", {"query": {"workspace_id": "mine"}}) in requests
    with pytest.raises(OptionalBusinessError, match="this workspace"):
        await ops.list_conversations(
            ctx, {"workspace_id": "other", "conversation_id": pinned}, None
        )
