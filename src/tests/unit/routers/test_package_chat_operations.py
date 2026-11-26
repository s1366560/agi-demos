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
        await send("thought", run_id="other", data={"thought": "other turn", "thought_level": 1})
        await send("thought", run_id="r", data={"thought": "reason", "thought_level": 1})
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
        {"type": "thought", "text": "reason"},
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
        (ops.follow, {"conversation_id": "other", "from_time_us": 0}),
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


async def test_history_keeps_turn_order_and_reasoning_without_tool_arguments(
    db_session, monkeypatch
):
    from plugins.business.agent.backend import chat_operations as operations

    ctx = context(FastAPI(), db_session)

    async def owned(*_args):
        return None

    requests = []

    async def canonical(_ctx, method, path, **kwargs):
        assert (method, path) == ("GET", "conversations/c/messages")
        requests.append(kwargs["query"])
        return {
            "has_more": False,
            "timeline": [
                {
                    "id": "u1",
                    "type": "user_message",
                    "content": "hi",
                    "eventTimeUs": 10,
                    "eventCounter": 0,
                    "timestamp": 1,
                },
                {"id": "t1", "type": "thought", "content": "reason", "eventTimeUs": 11},
                {
                    "id": "a1",
                    "type": "act",
                    "toolName": "bash",
                    "toolInput": {"command": "pwd"},
                    "eventTimeUs": 12,
                },
                {
                    "id": "m1",
                    "type": "assistant_message",
                    "content": "done",
                    "eventTimeUs": 14,
                    "eventCounter": 1,
                    "timestamp": 2,
                    "metadata": {
                        "executionSummary": {
                            "step_count": 3,
                            "call_count": 3,
                            "total_cost": 0.110761,
                            "total_cost_formatted": "$0.110761",
                            "total_tokens": {"input": 78409, "output": 443, "total": 79115},
                            "agent_loop": {"plugin_id": "memstack-kernel"},
                        },
                        "internal": "kept on the server",
                    },
                },
            ],
        }

    monkeypatch.setattr(operations, "_own_conversation", owned)
    monkeypatch.setattr(operations, "_canonical", canonical)

    result = await operations.history(ctx, {"conversation_id": "c", "limit": 500}, None)

    assert requests == [{"limit": 500}]
    assert result["before"] is None
    assert result["messages"] == [
        {
            "id": "u1",
            "role": "user_message",
            "content": "hi",
            "timestamp": 1,
            "eventTimeUs": 10,
            "eventCounter": 0,
        },
        {
            "id": "m1",
            "role": "assistant_message",
            "content": "done",
            "timestamp": 2,
            "eventTimeUs": 14,
            "eventCounter": 1,
            # The transcript shows the counters of a finished answer above it,
            # under the same names whether storage kept snake case or camel case.
            "summary": {
                "stepCount": 3,
                "callCount": 3,
                "totalCost": 0.110761,
                "totalCostFormatted": "$0.110761",
                "totalTokens": {"input": 78409, "output": 443, "total": 79115},
            },
        },
    ]
    # Reasoning is part of the visible transcript; tool arguments belong to the
    # interactions capability, and other message metadata stays on the server.
    assert result["thoughts"] == [{"id": "t1", "content": "reason", "eventTimeUs": 11}]
    assert "toolInput" not in str(result)
    assert "agent_loop" not in str(result)
    assert "internal" not in str(result)


async def test_interactions_keep_every_event_in_order_and_show_only_what_a_transcript_reads(
    db_session, monkeypatch
):
    from plugins.business.agent.backend import workbench

    ctx = context(FastAPI(), db_session)

    async def owned(*_args):
        return None

    async def canonical(_ctx, method, path, **_kwargs):
        assert method == "GET"
        if path.endswith("/pending"):
            return {
                "requests": [
                    {
                        "id": "env-pending",
                        "request_type": "env_var",
                        "question": "",
                        "options": [],
                        "created_at": "2026-11-26T00:00:00",
                        "expires_at": "2026-11-26T00:05:00",
                        "authority_revision": 3,
                        "context": {"requested_variables": ["TOKEN"]},
                        "metadata": {"internal": "kept on the server"},
                    },
                    {
                        "id": "native",
                        "request_type": "permission",
                        "native_binding": {"device_id": "private"},
                    },
                    {"id": "other", "request_type": "plan_approval"},
                ]
            }
        return {
            "timeline": [
                {
                    "id": "u1",
                    "type": "user_message",
                    "content": "private question",
                    "metadata": {"fileMetadata": [{"filename": "a.txt"}]},
                    "eventTimeUs": 1,
                },
                {
                    "id": "t1",
                    "type": "thought",
                    "content": "private reasoning",
                    "eventTimeUs": 2,
                },
                {
                    # An argument draft of the call below. The transcript drops it
                    # once the execution is read, by the one field that marks it.
                    "id": "act_delta-2-1",
                    "type": "act",
                    "execution_id": "k1",
                    "call_id": "k1",
                    "message_id": "message-1",
                    "toolName": "bash",
                    "toolInput": {"command": "pwd"},
                    "metadata": {
                        "sourceEventType": "act_delta",
                        "status": "preparing",
                        "internal": "kept on the server",
                    },
                    "eventTimeUs": 2,
                    "eventCounter": 1,
                },
                {
                    "id": "a1",
                    "type": "act",
                    "execution_id": "e1",
                    "call_id": "k1",
                    "message_id": "message-1",
                    "toolName": "bash",
                    "toolInput": {"command": "pwd"},
                    "eventTimeUs": 3,
                    "eventCounter": 0,
                    "execution": {
                        "startTime": 1.0,
                        "endTime": 2.0,
                        "duration": 1000,
                        "status": "success",
                    },
                },
                {
                    "id": "p1",
                    "type": "permission_asked",
                    "requestId": "perm",
                    "toolName": "bash",
                    "riskLevel": "low",
                    "description": "run pwd",
                    "answered": True,
                    "granted": True,
                    # The transcript hides a request that policy allowed by itself.
                    "autoApproved": True,
                    "auto_approved": True,
                    "eventTimeUs": 4,
                    "eventCounter": 0,
                    "context": {"internal": "kept on the server"},
                },
                {
                    "id": "o1",
                    "type": "observe",
                    "execution_id": "e1",
                    "call_id": "k1",
                    "toolName": "bash",
                    "toolOutput": "/workspace",
                    "isError": False,
                    "eventTimeUs": 5,
                    "eventCounter": 0,
                },
                # Not drawn. It still ends the group of tool steps before it, so it
                # keeps its place and nothing else.
                {
                    "id": "k1",
                    "type": "task_updated",
                    "payload": {"tasks": [{"title": "hidden"}]},
                    "eventTimeUs": 6,
                    "eventCounter": 0,
                    "timestamp": 6,
                },
                {
                    "id": "r1",
                    "type": "permission_replied",
                    "requestId": "perm",
                    "granted": True,
                    "autoApproved": True,
                    "auto_approved": True,
                    "preset": "full",
                    "eventTimeUs": 7,
                },
                {
                    "id": "e1",
                    "type": "error",
                    "message": "model override has no provider route",
                    "code": "model_override_route_missing",
                    "eventTimeUs": 8,
                },
                {
                    "id": "v1",
                    "type": "env_var_requested",
                    "requestId": "env",
                    "toolName": "bash",
                    "fields": [{"name": "TOKEN", "label": "Token"}],
                    "message": "",
                    "context": {"save_scope": "tenant", "internal": "kept on the server"},
                    "answered": True,
                    "values": {"TOKEN": "fixture-secret-value"},
                    "providedVariables": ["TOKEN"],
                    "eventTimeUs": 9,
                },
                {
                    "id": "s1",
                    "type": "selection_trace",
                    "payload": {"hidden": True},
                    "eventTimeUs": 10,
                },
                {
                    "id": "mr1",
                    "type": "memory_recalled",
                    "memories": [
                        {
                            "content": "Earlier report",
                            "score": 0.82,
                            "source": "memory_index",
                            "category": "decision",
                            "source_id": "mem-1",
                            "embedding": [0.1, 0.2],
                        }
                    ],
                    "count": 1,
                    "searchMs": 1350,
                    "payload": {"plugin_generation": {"digest": "kept on the server"}},
                    "eventTimeUs": 11,
                },
                {
                    "id": "mc1",
                    "type": "memory_captured",
                    "capturedCount": 2,
                    "categories": ["entity", "episode"],
                    "payload": {"agent_id": "builtin:all-access"},
                    "eventTimeUs": 12,
                },
            ]
        }

    monkeypatch.setattr(workbench, "_own_conversation", owned)
    monkeypatch.setattr(workbench, "_canonical", canonical)

    result = await workbench.interactions(ctx, {"conversation_id": "c"}, None)

    execution = {"startTime": 1.0, "endTime": 2.0, "duration": 1000, "status": "success"}
    assert result == {
        # An environment-variable request waits here to be answered; a request bound
        # to a device and one of another kind are not this page's to answer.
        "requests": [
            {
                "id": "env-pending",
                "request_type": "env_var",
                "question": "",
                "options": [],
                "created_at": "2026-11-26T00:00:00",
                "expires_at": "2026-11-26T00:05:00",
                "authority_revision": 3,
            }
        ],
        "events": [
            {"id": "u1", "type": "user_message", "eventTimeUs": 1},
            {"id": "t1", "type": "thought", "eventTimeUs": 2},
            {
                "id": "act_delta-2-1",
                "type": "act",
                "execution_id": "k1",
                "call_id": "k1",
                "message_id": "message-1",
                "toolName": "bash",
                "toolInput": {"command": "pwd"},
                "metadata": {"sourceEventType": "act_delta"},
                "eventTimeUs": 2,
                "eventCounter": 1,
            },
            {
                "id": "a1",
                "type": "act",
                "execution_id": "e1",
                "call_id": "k1",
                "message_id": "message-1",
                "toolName": "bash",
                "toolInput": {"command": "pwd"},
                "eventTimeUs": 3,
                "eventCounter": 0,
                "execution": execution,
            },
            {
                "id": "p1",
                "type": "permission_asked",
                "requestId": "perm",
                "toolName": "bash",
                "riskLevel": "low",
                "description": "run pwd",
                "answered": True,
                "granted": True,
                "autoApproved": True,
                "auto_approved": True,
                "eventTimeUs": 4,
                "eventCounter": 0,
            },
            {
                "id": "o1",
                "type": "observe",
                "execution_id": "e1",
                "call_id": "k1",
                "toolName": "bash",
                "toolOutput": "/workspace",
                "isError": False,
                "eventTimeUs": 5,
                "eventCounter": 0,
            },
            {
                "id": "k1",
                "type": "task_updated",
                "eventTimeUs": 6,
                "eventCounter": 0,
                "timestamp": 6,
            },
            {
                "id": "r1",
                "type": "permission_replied",
                "requestId": "perm",
                "granted": True,
                "autoApproved": True,
                "auto_approved": True,
                "eventTimeUs": 7,
            },
            {
                "id": "e1",
                "type": "error",
                "message": "model override has no provider route",
                "code": "model_override_route_missing",
                "eventTimeUs": 8,
            },
            {
                "id": "v1",
                "type": "env_var_requested",
                "requestId": "env",
                "toolName": "bash",
                "fields": [{"name": "TOKEN", "label": "Token"}],
                "message": "",
                "answered": True,
                "providedVariables": ["TOKEN"],
                "eventTimeUs": 9,
            },
            {"id": "s1", "type": "selection_trace", "eventTimeUs": 10},
            {
                # A recalled memory is shown with its text, score, source and category.
                "id": "mr1",
                "type": "memory_recalled",
                "memories": [
                    {
                        "content": "Earlier report",
                        "score": 0.82,
                        "source": "memory_index",
                        "category": "decision",
                    }
                ],
                "count": 1,
                "searchMs": 1350,
                "eventTimeUs": 11,
            },
            {
                "id": "mc1",
                "type": "memory_captured",
                "capturedCount": 2,
                "categories": ["entity", "episode"],
                "eventTimeUs": 12,
            },
        ],
    }
    # Message text, event payloads and the values of an environment-variable answer
    # stay on the server.
    for kept in (
        "private question",
        "private reasoning",
        "fileMetadata",
        "executionSummary",
        "payload",
        "hidden",
        "context",
        "values",
        "secret",
        "preset",
        "embedding",
        "source_id",
        "digest",
        "builtin",
        "preparing",
        "synthesizeObserve",
        "internal",
    ):
        assert kept not in str(result)


async def test_follow_streams_the_running_turn_and_ends_when_it_ends(monkeypatch):
    """Opening a conversation while its turn runs follows it, as the original workbench does."""
    from plugins.business.agent.backend import chat_operations as operations

    app = FastAPI()
    inbound = []

    @app.websocket("/api/v1/agent/ws")
    async def socket(ws: WebSocket):
        await ws.accept()
        await ws.send_json({"type": "connected", "data": {"user_id": "u"}})
        inbound.append(await ws.receive_json())

        async def send(kind, **fields):
            await ws.send_json({"type": kind, "conversation_id": "c", **fields})

        await send("ack", action="subscribe")
        # Another conversation's events do not reach the page.
        await ws.send_json(
            {"type": "text_delta", "conversation_id": "other", "data": {"delta": "x"}}
        )
        await send("thought", data={"thought": "reason"})
        await send("text_delta", data={"delta": "text"})
        await send("complete")
        await ws.receive()

    frames = []

    async def progress(frame):
        frames.append(frame)

    async def owned(*_args):
        return None

    requests = []

    async def canonical(_ctx, method, path, **_kwargs):
        requests.append((method, path))
        return {"active_run": {"id": "r", "revision": 3, "status": "running"}}

    monkeypatch.setattr(operations, "_own_conversation", owned)
    monkeypatch.setattr(operations, "_canonical", canonical)

    result = await operations.follow(
        context(app), {"conversation_id": "c", "from_time_us": 5, "from_counter": 1}, progress
    )

    assert requests == [("GET", "conversations/c/active-run")]
    assert inbound == [
        {"type": "subscribe", "conversation_id": "c", "from_time_us": 5, "from_counter": 1}
    ]
    assert frames == [
        {"type": "accepted", "run_id": "r", "revision": 3},
        {"type": "thought", "text": "reason"},
        {"type": "text_delta", "text": "text"},
    ]
    assert result == {"status": "complete", "run_id": "r"}


async def test_follow_without_a_running_turn_returns_at_once(monkeypatch):
    from plugins.business.agent.backend import chat_operations as operations

    app = FastAPI()
    opened = []

    @app.websocket("/api/v1/agent/ws")
    async def socket(ws: WebSocket):
        opened.append(1)
        await ws.accept()

    async def owned(*_args):
        return None

    async def canonical(*_args, **_kwargs):
        return {"active_run": None, "reason_code": "no_active_run"}

    monkeypatch.setattr(operations, "_own_conversation", owned)
    monkeypatch.setattr(operations, "_canonical", canonical)

    result = await operations.follow(
        context(app), {"conversation_id": "c", "from_time_us": 0}, None
    )

    assert result == {"status": "idle"}
    assert opened == []


async def test_follow_that_hears_nothing_checks_whether_the_turn_still_runs(monkeypatch):
    """A turn can end between the status read and the subscription."""
    from plugins.business.agent.backend import chat_operations as operations, chat_stream

    app = FastAPI()
    inbound = []

    @app.websocket("/api/v1/agent/ws")
    async def socket(ws: WebSocket):
        await ws.accept()
        await ws.send_json({"type": "connected", "data": {"user_id": "u"}})
        inbound.append(await ws.receive_json())
        # Nothing follows: the turn already ended.
        await ws.receive()

    async def owned(*_args):
        return None

    reads = []

    async def canonical(*_args, **_kwargs):
        reads.append(1)
        running = len(reads) == 1
        return {"active_run": {"id": "r", "revision": 1} if running else None}

    monkeypatch.setattr(operations, "_own_conversation", owned)
    monkeypatch.setattr(operations, "_canonical", canonical)
    monkeypatch.setattr(chat_stream, "FOLLOW_FIRST_IDLE_SECONDS", 0.05)

    result = await operations.follow(
        context(app), {"conversation_id": "c", "from_time_us": 0}, None
    )

    assert result == {"status": "complete", "run_id": "r"}
    assert len(inbound) == 1
    assert len(reads) == 2
