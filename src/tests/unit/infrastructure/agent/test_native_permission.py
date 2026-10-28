"""Native human consent preserves structured judgment and exact server-owned pending binding."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.application.services import approved_run_tool_permission_v2 as approved
from src.infrastructure.agent.core.message import ToolPart, ToolState
from src.infrastructure.agent.hitl.coordinator import HITLCoordinator
from src.infrastructure.agent.native_computer_use.permission import (
    bind_native_permission,
    handle_native_permission,
)
from src.infrastructure.agent.native_computer_use.permission_result import input_digest
from src.infrastructure.agent.tools import native_computer_use as native
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.tests.unit.infrastructure.agent.test_native_computer_use import context, setup_guard

pytestmark = pytest.mark.unit


def decision():
    return {
        "action": {
            "name": "observe_application",
            "label": "Allow observing the fixture application",
        },
        "target": {"kind": "computer_app", "id": "native-pending"},
        "data": {"summary": "Capture the fixture window for a visual click."},
        "reason": "The task requires identifying the displayed red shape.",
        "risk": {
            "level": "high",
            "rationale": "Screenshots may reveal content shown in this application.",
        },
        "reversibility": {
            "mode": "partial",
            "recovery": "Revoke observation access from Computer Use settings.",
        },
        "scope": {"kind": "application", "ids": ["ai.memstack.cua.fixture"]},
        "evidence": [
            {
                "kind": "tool_response",
                "id": "native-pending",
                "label": "Application observation permission request",
            }
        ],
    }


def prepare(monkeypatch, *, change=None):
    guard = setup_guard(monkeypatch)
    monkeypatch.setattr(approved, "_identity", lambda _operation: guard.identity)
    monkeypatch.setattr(approved, "_read_run", AsyncMock(return_value=SimpleNamespace(revision=7)))
    ctx = context()
    session_id = native.native_session_id(ctx.session_id, guard.run_id)
    pending = {
        "request_id": "native-pending",
        "session_id": "cua-cloud-native-fixture",
        "engine_session_id": session_id,
        "app": "ai.memstack.cua.fixture",
        "identity_digest": "stable-code-identity",
        "capability": "screenshots",
        "tool_name": "computer_get_app_state",
        "input_digest": "exact-arguments",
    }
    record = {
        "request_id": "cloud-request",
        "status": "completed",
        "user_id": ctx.user_id,
        "tenant_id": ctx.tenant_id,
        "project_id": ctx.project_id,
        "conversation_id": ctx.conversation_id,
        "run_id": guard.run_id,
        "session_id": session_id,
        "device_id": "device",
        "connection_id": "connection",
        "authorization_revision": 7,
        "tool_name": "computer_get_app_state",
        "input_json": '{"app":"fixture"}',
        "output_json": json.dumps(
            {
                "error": "cua_permission_required",
                "request": pending,
                "scopes": ["once", "session", "always"],
            }
        ),
    }
    record["permission_required"] = {
        "kind": "native_consent",
        "binding": {
            "tool_name": record["tool_name"],
            "input_digest": input_digest(record["input_json"]),
            "engine_session_id": session_id,
            "cell_id": None,
            "step_id": None,
        },
        "demand": json.loads(record["output_json"]),
    }
    if change:
        change(record)
    broker = SimpleNamespace(
        members=AsyncMock(return_value={"cloud-request"}), read=AsyncMock(return_value=record)
    )
    monkeypatch.setattr(native, "current_native_computer_broker", lambda: broker)
    return ctx, broker


async def test_native_consent_seals_real_owner_and_origin_call(monkeypatch):
    ctx, _ = prepare(monkeypatch)
    binding, scopes = await bind_native_permission(ctx, decision())
    assert binding == {
        "user_id": "user",
        "tenant_id": "tenant",
        "project_id": "project",
        "conversation_id": "conversation",
        "run_id": "run",
        "session_id": native.native_session_id("engine-session", "run"),
        "device_id": "device",
        "app": "ai.memstack.cua.fixture",
        "identity_digest": "stable-code-identity",
        "capability": "screenshots",
        "tool_name": "computer_get_app_state",
        "input_digest": "exact-arguments",
        "cloud_request_id": "cloud-request",
        "native_request_id": "native-pending",
        "native_session_id": "cua-cloud-native-fixture",
        "authorization_revision": 7,
    }
    assert scopes == ["once", "session", "always"]


async def test_actual_sidecar_consent_fixture_binds_distinct_engine_and_native_sessions(
    monkeypatch,
):
    wire = json.loads(
        (
            Path(__file__).resolve().parents[5] / "shared/fixtures/computer-use-cloud-consent.json"
        ).read_text()
    )

    def replace_demand(record):
        record["output_json"] = json.dumps(wire)
        record["permission_required"]["demand"] = wire

    ctx, _ = prepare(monkeypatch, change=replace_demand)
    judgment = decision()
    judgment["target"]["id"] = wire["request"]["request_id"]
    binding, scopes = await bind_native_permission(ctx, judgment)
    assert binding["session_id"] == wire["request"]["engine_session_id"]
    assert binding["native_session_id"] == wire["request"]["session_id"]
    assert binding["session_id"] != binding["native_session_id"]
    assert binding["native_request_id"] == wire["request"]["request_id"]
    assert scopes == wire["scopes"]


async def test_once_only_connector_consent_cannot_offer_remembered_permission(monkeypatch):
    def once_only(record):
        output = record["permission_required"]["demand"]
        output["scopes"] = ["once"]
        output["request"]["capability"] = "connector_action"
        record["output_json"] = json.dumps(output)

    ctx, _ = prepare(monkeypatch, change=once_only)
    persisted = AsyncMock()
    monkeypatch.setattr(
        "src.infrastructure.agent.hitl.coordinator._persist_hitl_request", persisted
    )
    coordinator = HITLCoordinator(
        conversation_id=ctx.conversation_id, tenant_id=ctx.tenant_id, project_id=ctx.project_id
    )
    part = ToolPart(call_id=ctx.call_id, tool="request_permission", status=ToolState.RUNNING)
    stream = handle_native_permission(coordinator, ctx, decision(), part)
    asked = await anext(stream)
    saved = persisted.call_args.kwargs["type_data"]
    assert saved["scopes"] == ["once"] and saved["allow_remember"] is False
    await stream.aclose()
    coordinator.cancel_request_if_pending(asked.request_id)


@pytest.mark.parametrize(
    "changed",
    [
        {"engine_session_id": "foreign-logical-session"},
        {"engine_session_id": None},
        {"session_id": ""},
        {"session_id": None},
    ],
)
async def test_physical_and_logical_session_bindings_cannot_be_forged_or_omitted(
    monkeypatch, changed
):
    def alter(record):
        output = record["permission_required"]["demand"]
        output["request"].update(changed)
        record["output_json"] = json.dumps(output)

    ctx, _ = prepare(monkeypatch, change=alter)
    with pytest.raises(RuntimeV2Error, match="consent is invalid"):
        await bind_native_permission(ctx, decision())


@pytest.mark.parametrize(
    "change",
    [
        lambda record: record.update({"user_id": "other-user"}),
        lambda record: record.update({"run_id": "other-run"}),
        lambda record: record.update({"session_id": "other-session"}),
        lambda record: record.update({"status": "claimed"}),
        lambda record: record.update({"permission_required": None}),
    ],
)
async def test_forged_or_stale_pending_cannot_become_human_permission(monkeypatch, change):
    ctx, _ = prepare(monkeypatch, change=change)
    with pytest.raises(RuntimeV2Error, match="not pending"):
        await bind_native_permission(ctx, decision())


@pytest.mark.parametrize("payload", [None, [], "allow"])
async def test_permission_rejects_non_object_decision_before_human_request(monkeypatch, payload):
    ctx, _ = prepare(monkeypatch)
    coordinator = SimpleNamespace(prepare_request=AsyncMock())
    part = ToolPart(call_id=ctx.call_id, tool="request_permission", status=ToolState.RUNNING)
    with pytest.raises(RuntimeV2Error, match="complete structured"):
        await anext(handle_native_permission(coordinator, ctx, payload, part))
    coordinator.prepare_request.assert_not_awaited()


async def test_complete_decision_is_required_and_cannot_replace_pending_target(monkeypatch):
    ctx, _ = prepare(monkeypatch)
    invalid = decision()
    invalid.pop("risk")
    with pytest.raises(RuntimeV2Error, match="complete structured"):
        await bind_native_permission(ctx, invalid)
    forged = decision()
    forged["target"]["id"] = "invented-native-pending"
    with pytest.raises(RuntimeV2Error, match="not pending"):
        await bind_native_permission(ctx, forged)


async def test_native_permission_uses_existing_persistent_future_and_keeps_agent_risk(monkeypatch):
    ctx, _ = prepare(monkeypatch)
    persisted = AsyncMock()
    monkeypatch.setattr(
        "src.infrastructure.agent.hitl.coordinator._persist_hitl_request", persisted
    )
    coordinator = HITLCoordinator(
        conversation_id=ctx.conversation_id, tenant_id=ctx.tenant_id, project_id=ctx.project_id
    )
    part = ToolPart(call_id=ctx.call_id, tool="request_permission", status=ToolState.RUNNING)
    stream = handle_native_permission(coordinator, ctx, decision(), part)
    asked = await anext(stream)
    request_id = asked.request_id
    saved = persisted.call_args.kwargs["type_data"]
    assert saved["decision"] == decision()
    assert (
        saved["risk_level"] == "high"
        and asked.metadata["decision"]["risk"]["rationale"] == decision()["risk"]["rationale"]
    )
    assert saved["native_binding"]["native_request_id"] == "native-pending"
    assert saved["authority_revision"] == 1 and saved["scopes"] == ["once", "session", "always"]
    coordinator.resolve(
        request_id,
        {"action": "allow", "granted": True, "scope": "session"},
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        conversation_id=ctx.conversation_id,
    )
    replied = await anext(stream)
    assert replied.granted is True
    observed = await anext(stream)
    assert json.loads(observed.result)["granted"] is True
    assert part.status == ToolState.COMPLETED
    await stream.aclose()
    coordinator.cancel_request_if_pending(request_id)


@pytest.mark.parametrize("scope", ["once", "session", "always"])
def test_native_http_permission_response_accepts_only_stored_native_scopes(scope):
    from src.infrastructure.adapters.primary.web.routers.agent.hitl import (
        _validate_hitl_response_shape,
    )

    _validate_hitl_response_shape(
        hitl_type="permission",
        response_data={"action": "allow", "granted": True, "scope": scope},
        request_data={
            "native_binding": {"native_request_id": "native-pending"},
            "scopes": ["once", "session", "always"],
        },
    )


@pytest.mark.parametrize(
    "response",
    [
        {"action": "allow", "granted": True, "scope": "session"},
        {"action": "allow_always", "granted": True, "scope": "workspace_tool"},
        {"action": "allow", "granted": False, "scope": "once"},
    ],
)
def test_native_response_rejects_unoffered_scope_legacy_workspace_grant_or_contradiction(response):
    from fastapi import HTTPException

    from src.infrastructure.adapters.primary.web.routers.agent.hitl import (
        _validate_hitl_response_shape,
    )

    with pytest.raises(HTTPException):
        _validate_hitl_response_shape(
            hitl_type="permission",
            response_data=response,
            request_data={
                "native_binding": {"native_request_id": "native-pending"},
                "scopes": ["once"],
            },
        )


def test_session_projection_preserves_full_decision_and_binding_for_native_ui():
    from src.application.services.conversation_session_projection_service import (
        ConversationSessionProjectionService,
        PendingHITLAuthority,
    )

    now = datetime.now(UTC)
    metadata = {
        "decision": decision(),
        "native_binding": {"native_request_id": "native-pending"},
        "scopes": ["once", "session"],
        "actions": [{"id": "allow", "label": "Allow"}, {"id": "deny", "label": "Deny"}],
    }
    source = PendingHITLAuthority(
        id="human-request",
        conversation_id="conversation",
        message_id="message",
        request_type="permission",
        question="Observe fixture?",
        options=(),
        context={},
        metadata=metadata,
        authority_revision=1,
        created_at=now,
        expires_at=now + timedelta(minutes=5),
        permission=None,
    )
    projected = ConversationSessionProjectionService._hitl(source).model_dump()
    assert projected["decision"] == decision()
    assert projected["native_binding"] == metadata["native_binding"]
    assert projected["actions"] == metadata["actions"] and projected["scopes"] == [
        "once",
        "session",
    ]


async def test_execution_step_consent_must_match_persisted_exact_step(monkeypatch):
    from src.infrastructure.agent.native_computer_use.steps import ExecutionSteps

    ctx, broker = prepare(monkeypatch)
    record = broker.read.return_value
    value = {
        **{
            key: record[key]
            for key in (
                "user_id",
                "tenant_id",
                "project_id",
                "conversation_id",
                "run_id",
                "session_id",
                "device_id",
            )
        },
        "status": "pending",
        "origin_request_id": "cloud-request",
        "permission_id": "native-pending",
        "cell_id": "cell",
        "step_id": "step",
        "step_key": "private-step",
        "code_digest": "exact-code",
        "catalog_digest": "catalog",
        "target": {"kind": "browser", "id": "iab/1"},
        "tool_name": "browser_write_operation",
        "input_digest": "exact-input",
        "permission_input_digest": input_digest('{"operation":"tab.claim","args":[]}'),
        "current_request_id": "cloud-request",
        "authorization_revision": 7,
        "connection_id": "connection",
    }
    record["output_json"] = json.dumps(
        {
            "error": "cua_permission_required",
            "request": ExecutionSteps.pending(value),
            "scopes": ["once"],
        }
    )
    record["tool_name"] = "cua_repl_js"
    record["permission_required"] = {
        "kind": "cloud_execution_step",
        "binding": {
            "tool_name": value["tool_name"],
            "input_digest": value["permission_input_digest"],
            "engine_session_id": value["session_id"],
            "cell_id": "cell",
            "step_id": "step",
        },
        "demand": json.loads(record["output_json"]),
    }
    broker.members.side_effect = (
        lambda key: {"private-step"} if key.endswith(":steps") else {"cloud-request"}
    )
    broker.read.side_effect = lambda key: value if key == "private-step" else record
    binding, scopes = await bind_native_permission(ctx, decision())
    assert scopes == ["once"]
    assert binding["execution_step"]["step_id"] == "step"
    value["input_digest"] = "changed-input"
    with pytest.raises(RuntimeV2Error, match="consent is invalid"):
        await bind_native_permission(ctx, decision())
