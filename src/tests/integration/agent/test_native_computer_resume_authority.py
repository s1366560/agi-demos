"""Explicit native resume revalidates authority without replaying completed work."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from src.infrastructure.adapters.primary.web.routers.agent import computer_use_device as routes
from src.infrastructure.agent.native_computer_use.store import DeviceBridgeError, control_key
from src.infrastructure.plugins.v2.builtin_agent_http_routes import agent_route_definitions_v2
from src.infrastructure.plugins.v2.http_routes import install_route_definitions_v2
from src.tests.integration.agent.test_native_computer_bridge import (
    bridge as _bridge,
    settle,
    start_request,
)
from src.tests.integration.agent.test_native_computer_claims import application, authority

pytestmark = pytest.mark.integration
bridge = _bridge


async def completed_request(bridge):
    task, request_id = await start_request(bridge)
    await settle(bridge, request_id)
    await task
    return request_id


async def resume(app, request_id, **body):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post(
            f"/api/v1/agent/device/requests/{request_id}/resume-authority",
            json={"device_id": "d", "session_id": "session", **body},
        )


async def test_completed_request_gets_fresh_resume_only_authority_without_mutation(
    bridge, monkeypatch
):
    request_id = await completed_request(bridge)
    key = routes.request_key(request_id)
    await bridge.update(key, lambda value: {**value, "expires_at": 1})
    before = await bridge.read(key)
    controls = await bridge.redis.xrange(control_key("connection"))
    app, _, loader = application(bridge, monkeypatch)
    started = int(time.time())

    response = await resume(app, request_id)

    assert response.status_code == 200
    assert response.json() == {
        "request_id": request_id,
        "user_id": "u",
        "tenant_id": "t",
        "project_id": "p",
        "device_id": "d",
        "conversation_id": "conversation",
        "run_id": "run",
        "session_id": "session",
        "authorization_revision": 1,
        "expires_at": response.json()["expires_at"],
    }
    assert started < response.json()["expires_at"] <= int(time.time()) + 30
    assert loader.await_count == 2
    assert loader.call_args.kwargs["lock"] is True
    assert await bridge.read(key) == before
    assert await bridge.redis.xrange(control_key("connection")) == controls


@pytest.mark.parametrize(
    "changed",
    [
        {"status": "requested"},
        {"status": "claimed"},
        {"status": "receiving"},
        {"status": "unknown"},
        {"cancelled": True},
        {"is_error": True},
    ],
)
async def test_only_successful_completed_uncancelled_requests_can_resume(
    bridge, monkeypatch, changed
):
    request_id = await completed_request(bridge)
    await bridge.update(routes.request_key(request_id), lambda value: {**value, **changed})
    app, _, loader = application(bridge, monkeypatch)
    response = await resume(app, request_id)
    assert response.status_code == 409
    loader.assert_not_awaited()


@pytest.mark.parametrize("body", [{"device_id": "foreign"}, {"session_id": "foreign"}])
async def test_resume_requires_exact_device_and_engine_session(bridge, monkeypatch, body):
    request_id = await completed_request(bridge)
    app, _, loader = application(bridge, monkeypatch)
    assert (await resume(app, request_id, **body)).status_code == 409
    loader.assert_not_awaited()


async def test_foreign_user_cannot_resume(bridge, monkeypatch):
    request_id = await completed_request(bridge)
    app, _, loader = application(bridge, monkeypatch, user_id="other")
    assert (await resume(app, request_id)).status_code == 409
    loader.assert_not_awaited()


@pytest.mark.parametrize(
    "changed",
    [
        {"status": "queued"},
        {"status": "paused"},
        {"status": "cancelled"},
        {"status": "completed"},
        {"status": "ready_review"},
        {"status": "failed"},
        {"revision": 2},
        {"permission_profile": "full_access"},
        {"project_id": "other"},
        {"authorization_snapshot": {"cancellation_receipt": {"expected_revision": 1}}},
    ],
)
async def test_resume_rejects_inactive_or_changed_parent_authority(bridge, monkeypatch, changed):
    request_id = await completed_request(bridge)
    app, _, _ = application(bridge, monkeypatch, run=authority(**changed))
    assert (await resume(app, request_id)).status_code == 409


async def test_resume_rejects_disconnected_device(bridge, monkeypatch):
    request_id = await completed_request(bridge)
    app, _, _ = application(bridge, monkeypatch)
    await bridge.devices.disconnect("connection")
    assert (await resume(app, request_id)).status_code == 409


async def test_cancelled_completed_result_remains_cached_but_cannot_resume(bridge, monkeypatch):
    request_id = await completed_request(bridge)
    before = await bridge.read(routes.request_key(request_id))
    await bridge.cancel_request(request_id)
    after = await bridge.read(routes.request_key(request_id))
    assert after == {**before, "cancelled": True}
    app, _, _ = application(bridge, monkeypatch)
    assert (await resume(app, request_id)).status_code == 409
    assert (await bridge.result(after)).output == before["output_json"]


async def test_revocation_while_authority_is_checked_rejects_resume(bridge, monkeypatch):
    request_id = await completed_request(bridge)
    app, _, loader = application(bridge, monkeypatch)
    loader.side_effect = [
        (authority(), SimpleNamespace(workspace_id=None)),
        (authority(revision=2), SimpleNamespace(workspace_id=None)),
    ]
    assert (await resume(app, request_id)).status_code == 409


async def test_cancellation_during_policy_io_is_seen_before_resume(bridge, monkeypatch):
    request_id = await completed_request(bridge)
    app, _, _ = application(bridge, monkeypatch)

    async def cancelled_policy(_conversation):
        await bridge.cancel_request(request_id)
        return {"permission_mode": "ask"}

    monkeypatch.setattr(routes, "load_chat_permission_policy", cancelled_policy)
    assert (await resume(app, request_id)).status_code == 409


async def test_resume_rechecks_workspace_binding(bridge, monkeypatch):
    request_id = await completed_request(bridge)
    app, _, loader = application(bridge, monkeypatch)
    loader.return_value = (authority(), SimpleNamespace(workspace_id="other"))
    assert (await resume(app, request_id)).status_code == 409


async def test_resume_rechecks_child_authority(bridge, monkeypatch):
    request_id = await completed_request(bridge)
    app, _, _ = application(bridge, monkeypatch)
    monkeypatch.setattr(
        routes,
        "require_child_owner",
        AsyncMock(side_effect=DeviceBridgeError("computer_use_child_authority_revoked")),
    )
    assert (await resume(app, request_id)).status_code == 409


async def test_live_child_cannot_resume_after_parent_finishes(bridge, monkeypatch):
    request_id = await completed_request(bridge)
    app, _, _ = application(bridge, monkeypatch, run=authority(status="completed"))
    monkeypatch.setattr(routes, "require_child_owner", AsyncMock(return_value=True))
    assert (await resume(app, request_id)).status_code == 409


async def test_workspace_switch_during_authority_check_rejects_resume(bridge, monkeypatch):
    request_id = await completed_request(bridge)
    app, _, loader = application(bridge, monkeypatch)
    loader.side_effect = [
        (authority(), SimpleNamespace(workspace_id=None)),
        (authority(), SimpleNamespace(workspace_id="other")),
    ]
    assert (await resume(app, request_id)).status_code == 409


async def test_identity_mapped_workspace_refresh_cannot_hide_changed_binding(bridge, monkeypatch):
    request_id = await completed_request(bridge)
    app, _, loader = application(bridge, monkeypatch)
    conversation = SimpleNamespace(workspace_id=None)

    async def refreshed_conversation(*_args, **kwargs):
        if kwargs.get("lock"):
            conversation.workspace_id = "other"
        return authority(), conversation

    loader.side_effect = refreshed_conversation
    assert (await resume(app, request_id)).status_code == 409


async def test_policy_revision_change_during_authority_check_rejects_resume(bridge, monkeypatch):
    request_id = await completed_request(bridge)
    app, _, _ = application(bridge, monkeypatch)
    monkeypatch.setattr(
        routes,
        "load_chat_permission_policy",
        AsyncMock(
            side_effect=[
                {"permission_mode": "ask", "revision": 1},
                {"permission_mode": "ask", "revision": 2},
            ]
        ),
    )
    assert (await resume(app, request_id)).status_code == 409


async def test_removed_tool_contract_rejects_resume(bridge, monkeypatch):
    request_id = await completed_request(bridge)
    app, _, _ = application(bridge, monkeypatch)
    from src.infrastructure.agent.native_computer_use.contracts import DeviceScope

    await bridge.devices.register(
        DeviceScope(user_id="u", tenant_id="t", project_id="p", device_id="d"),
        "connection",
        [],
    )
    assert (await resume(app, request_id)).status_code == 409


async def test_current_policy_ceiling_rejects_previous_full_access(bridge, monkeypatch):
    request_id = await completed_request(bridge)
    await bridge.update(
        routes.request_key(request_id),
        lambda value: {**value, "permission_profile": "full_access"},
    )
    run = authority(permission_profile="full_access")
    run.authorization_snapshot["effective_permission_mode"] = "full_access"
    app, _, _ = application(bridge, monkeypatch, run=run, policy={"permission_mode": "ask"})
    assert (await resume(app, request_id)).status_code == 409


async def test_production_v2_routes_dispatch_status_claim_and_explicit_resume(bridge, monkeypatch):
    baseline, _, _ = application(bridge, monkeypatch)
    app = FastAPI()
    app.state.container = baseline.state.container
    app.dependency_overrides.update(baseline.dependency_overrides)
    install_route_definitions_v2(app, agent_route_definitions_v2())
    task, request_id = await start_request(bridge)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        status = await client.get(
            "/api/v1/agent/device/status",
            params={"device_id": "d", "tenant_id": "t", "project_id": "p"},
        )
        assert status.status_code == 200 and status.json()["ready"] is True
        claim = await client.post(
            f"/api/v1/agent/device/requests/{request_id}/claim", json={"device_id": "d"}
        )
        assert claim.status_code == 200 and claim.json()["request_id"] == request_id
        await bridge.receive_result(
            "connection",
            {"request_id": request_id, "output_json": "{}", "is_error": False, "media": []},
        )
        await task
        authority_response = await resume(app, request_id)
        assert authority_response.status_code == 200
        assert authority_response.json()["session_id"] == "session"
