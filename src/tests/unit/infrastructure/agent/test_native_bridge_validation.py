"""Adversarial admission cases for the native bridge, without network retrieval or OS actions."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.agent import computer_use_device as routes
from src.infrastructure.adapters.primary.web.websocket.handlers import (
    computer_use_handler as handler,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.agent.native_computer_use.broker import NativeComputerBroker
from src.infrastructure.agent.native_computer_use.schema import validator
from src.infrastructure.agent.native_computer_use.store import DeviceBridgeError, identifier, record
from src.tests.integration.agent.test_native_computer_bridge import authorization

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("keyword", ["$ref", "$dynamicRef", "$recursiveRef"])
@pytest.mark.parametrize(
    "reference", ["https://schema.example.test/private", "file:///private/schema.json"]
)
def test_device_schema_cannot_retrieve_network_or_local_files(monkeypatch, keyword, reference):
    fetch = Mock(side_effect=AssertionError("schema retrieval must not happen"))
    monkeypatch.setattr("urllib.request.urlopen", fetch)
    schema = {"type": "object", "properties": {"target": {keyword: reference}}}
    with pytest.raises(DeviceBridgeError, match="external_schema_reference"):
        validator(schema)
    fetch.assert_not_called()


def test_local_schema_reference_validates_exact_input_without_network(monkeypatch):
    fetch = Mock(side_effect=AssertionError("schema retrieval must not happen"))
    monkeypatch.setattr("urllib.request.urlopen", fetch)
    schema = {
        "type": "object",
        "$defs": {"app": {"type": "string", "minLength": 1}},
        "properties": {"app": {"$ref": "#/$defs/app"}},
        "required": ["app"],
        "additionalProperties": False,
    }
    checked = validator(schema)
    assert checked.is_valid({"app": "pid:12"})
    assert not checked.is_valid({"app": ""})
    assert not checked.is_valid({"app": "pid:12", "run_id": "forged"})
    fetch.assert_not_called()


@pytest.mark.parametrize("schema", [{"type": "object", "required": "app"}, {"type": "invented"}])
def test_invalid_device_schema_fails_before_tools_are_advertised(schema):
    with pytest.raises(DeviceBridgeError, match="invalid_schema"):
        validator(schema)


def test_connector_mutation_cannot_inherit_read_permission_or_unknown_tool_prefix():
    with pytest.raises(DeviceBridgeError, match="permission_denied"):
        NativeComputerBroker._validate_authorization(authorization(), "computer_connector_call")
    with pytest.raises(DeviceBridgeError, match="unknown_tool"):
        NativeComputerBroker._validate_authorization(authorization(), "computer_fake_safe_read")
    approved = authorization(approved_tools=("computer_connector_call",))
    NativeComputerBroker._validate_authorization(approved, "computer_connector_call")


@pytest.mark.parametrize("value", ["[]", "null", "{bad", 12, b"\xff"])
def test_corrupt_private_records_are_rejected_without_interpreting_them(value):
    with pytest.raises(DeviceBridgeError, match="invalid_record"):
        record(value)
    assert record(None) is None


@pytest.mark.parametrize("value", [None, "", 42, "x" * 257])
def test_owner_identifiers_are_structural_nonempty_bounded_strings(value):
    with pytest.raises(DeviceBridgeError, match="invalid_identifier"):
        identifier(value)


async def test_transport_error_never_echoes_or_logs_private_payload(monkeypatch, caplog):
    context = SimpleNamespace(
        container=SimpleNamespace(redis_client=object()),
        tenant_id="t",
        user_id="u",
        websocket=SimpleNamespace(scope={}),
        db=AsyncMock(),
        send_error=AsyncMock(),
        send_json=AsyncMock(),
    )
    monkeypatch.setattr(
        routes,
        "require_project_access",
        AsyncMock(side_effect=RuntimeError("private-image-and-input")),
    )
    await handler.ComputerUseHandler("computer_use_device").handle(
        context,
        {
            "scope": {"tenant_id": "t", "project_id": "p"},
            "device_id": "d",
            "tool_definitions": [],
        },
    )
    assert context.send_error.call_args.kwargs["code"] == "computer_use_transport_unavailable"
    assert "private-image-and-input" not in str(context.send_error.call_args) + caplog.text


@pytest.mark.parametrize(
    "kind,message,expected",
    [
        (
            "computer_use_device",
            {"scope": {"tenant_id": "other", "project_id": "p"}},
            "computer_use_scope_denied",
        ),
        ("computer_use_device", {"scope": "not-object"}, "computer_use_scope_denied"),
        (
            "computer_use_result",
            {"output_json": "private content"},
            "computer_use_device_not_registered",
        ),
    ],
)
async def test_websocket_admission_denials_do_not_start_device_control(kind, message, expected):
    context = SimpleNamespace(
        container=SimpleNamespace(redis_client=object()),
        tenant_id="t",
        user_id="u",
        websocket=SimpleNamespace(scope={}),
        db=AsyncMock(),
        send_error=AsyncMock(),
        send_json=AsyncMock(),
    )
    await handler.ComputerUseHandler(kind).handle(context, message)
    assert context.send_error.call_args.kwargs["code"] == expected
    context.send_json.assert_not_awaited()
    context.db.scalar.assert_not_awaited()


def plan_application(monkeypatch, *, change=None, policy_mode="full_access"):
    approval = {
        "schema_version": 1,
        "tenant_id": "t",
        "user_id": "u",
        "request": {
            "permission_profile": "full_access",
            "conversation_id": "conversation",
            "project_id": "p",
            "plan_version_id": "version",
        },
    }
    source = SimpleNamespace(
        id="run",
        status="running",
        permission_profile="full_access",
        conversation_id="conversation",
        project_id="p",
        plan_version_id="version",
        authorization_snapshot={"approval_request": deepcopy(approval)},
    )
    run = SimpleNamespace(
        id="run",
        run_kind="plan",
        status="running",
        revision=1,
        tenant_id="t",
        project_id="p",
        conversation_id="conversation",
        permission_profile="full_access",
        plan_version_id="version",
        plan_run_id="run",
        authorization_snapshot={"approval_request": deepcopy(approval)},
    )
    if change is not None:
        change(run, source)
    payload = asdict(
        authorization(run_kind="plan", permission_profile="full_access", plan_version_id="version")
    ) | {
        "request_id": "request",
        "device_id": "d",
        "connection_id": "connection",
        "status": "requested",
        "input_json": "{}",
        "tool_name": "computer_get_app_state",
    }
    broker = SimpleNamespace(
        read=AsyncMock(return_value=payload),
        claim=AsyncMock(return_value=payload),
        devices=SimpleNamespace(
            list=AsyncMock(
                return_value=[
                    {
                        "device_id": "d",
                        "connection_id": "connection",
                        "tool_definitions": [
                            {
                                "name": "computer_get_app_state",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {},
                                    "additionalProperties": False,
                                },
                            }
                        ],
                    }
                ]
            )
        ),
    )
    db = AsyncMock()
    db.get.return_value = source
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u")
    app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(routes, "broker_from_request", lambda _request: broker)
    monkeypatch.setattr(
        routes,
        "_load_scoped_run",
        AsyncMock(return_value=(run, SimpleNamespace(workspace_id=None))),
    )
    monkeypatch.setattr(
        routes,
        "load_chat_permission_policy",
        AsyncMock(return_value={"permission_mode": policy_mode}),
    )
    return app, broker


async def test_matching_plan_authority_can_be_claimed(monkeypatch):
    app, broker = plan_application(monkeypatch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/device/requests/request/claim", json={"device_id": "d"})
    assert response.status_code == 200
    broker.claim.assert_awaited_once_with("request", user_id="u", device_id="d")


@pytest.mark.parametrize(
    "change",
    [
        lambda _run, source: setattr(source, "plan_version_id", "other-version"),
        lambda _run, source: setattr(source, "project_id", "other-project"),
        lambda run, source: [
            snapshot["approval_request"]["request"].update(
                {"conversation_id": "other-conversation"}
            )
            for snapshot in (run.authorization_snapshot, source.authorization_snapshot)
        ],
        lambda run, source: [
            snapshot["approval_request"].update({"schema_version": 2})
            for snapshot in (run.authorization_snapshot, source.authorization_snapshot)
        ],
    ],
)
async def test_plan_claim_rejects_confused_source_or_approval_provenance(monkeypatch, change):
    app, broker = plan_application(monkeypatch, change=change)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/device/requests/request/claim", json={"device_id": "d"})
    assert response.status_code == 409
    broker.claim.assert_not_awaited()


async def test_plan_action_respects_current_policy_ceiling(monkeypatch):
    app, broker = plan_application(monkeypatch, policy_mode="ask")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/device/requests/request/claim", json={"device_id": "d"})
    assert response.status_code == 409
    broker.claim.assert_not_awaited()


@pytest.mark.parametrize(
    "metadata",
    [
        {"chat_permission_run_id": "another-parent", "chat_permission_mode": "ask"},
        {"chat_permission_run_id": "run", "chat_permission_mode": "full_access"},
        {
            "chat_permission_run_id": "run",
            "chat_permission_mode": "ask",
            "approved_plan_run_id": "run",
        },
    ],
)
async def test_child_cannot_claim_under_another_parent_or_broader_mode(monkeypatch, metadata):
    from src.infrastructure.adapters.secondary.persistence.subagent_owner_model_v2 import (
        SubAgentOwnerLeaseV2,
    )
    from src.infrastructure.agent.subagent import owner_lease_v2

    now = datetime.now(UTC)
    owner = SimpleNamespace(
        state="active", owner_token="fixture-token", expires_at=now + timedelta(seconds=30)
    )
    snapshot = SimpleNamespace(
        tenant_id="t", project_id="p", runs={"child": {"status": "running", "metadata": metadata}}
    )
    db = AsyncMock()
    db.get.side_effect = (
        lambda model, *_args, **_kwargs: owner if model is SubAgentOwnerLeaseV2 else snapshot
    )
    monkeypatch.setattr(owner_lease_v2, "database_now_v2", AsyncMock(return_value=now))
    value = asdict(
        authorization(
            child_run_id="child", child_owner_digest=hashlib.sha256(b"fixture-token").hexdigest()
        )
    )
    with pytest.raises(DeviceBridgeError, match="parent_authority_changed"):
        await routes.require_child_owner(db, value)
