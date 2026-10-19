"""HTTP claims revalidate live run authority before consuming device work."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.agent import computer_use_device as routes
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.tests.integration.agent.test_native_computer_bridge import (
    bridge as _bridge,
    start_request,
)

pytestmark = pytest.mark.integration
bridge = _bridge


def authority(**changes):
    values = {
        "id": "run",
        "run_kind": "chat",
        "status": "running",
        "revision": 1,
        "tenant_id": "t",
        "project_id": "p",
        "conversation_id": "conversation",
        "permission_profile": "read_only",
        "plan_version_id": None,
        "authorization_snapshot": {
            "source": "chat_admission",
            "schema_version": 1,
            "effective_permission_mode": "ask",
            "workspace_id": None,
        },
    }
    return SimpleNamespace(**{**values, **changes})


def application(broker, monkeypatch, *, run=None, user_id="u", policy=None):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1/agent")
    app.state.container = SimpleNamespace(redis_client=broker.redis)
    db = AsyncMock()
    db.scalar.return_value = "p"
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)
    conversation = SimpleNamespace(workspace_id=None)
    loader = AsyncMock(return_value=(run or authority(), conversation))
    monkeypatch.setattr(routes, "_load_scoped_run", loader)
    monkeypatch.setattr(
        routes,
        "load_chat_permission_policy",
        AsyncMock(return_value=policy or {"permission_mode": "ask"}),
    )
    return app, db, loader


async def test_claim_is_authenticated_single_use_and_reads_authority_twice(bridge, monkeypatch):
    task, request_id = await start_request(bridge)
    app, _, loader = application(bridge, monkeypatch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/v1/agent/device/requests/{request_id}/claim", json={"device_id": "d"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["request_id"] == request_id and body["user_id"] == "u"
        assert body["input_json"] == '{"app": "fixture"}'
        assert isinstance(body["expires_at"], int)
        assert "connection_id" not in body
        assert loader.await_count == 2
        assert loader.call_args.kwargs["lock"] is True
        duplicate = await client.post(
            f"/api/v1/agent/device/requests/{request_id}/claim", json={"device_id": "d"}
        )
        assert duplicate.status_code == 409
    await bridge.receive_result(
        "connection",
        {"request_id": request_id, "output_json": "{}", "is_error": False, "media": []},
    )
    await task


@pytest.mark.parametrize(
    "changed",
    [
        {"revision": 2},
        {"status": "cancelled"},
        {"permission_profile": "full_access"},
        {"project_id": "other"},
        {"authorization_snapshot": {"cancellation_receipt": {"expected_revision": 1}}},
    ],
)
async def test_changed_run_cannot_be_claimed(bridge, monkeypatch, changed):
    task, request_id = await start_request(bridge)
    app, _, _ = application(bridge, monkeypatch, run=authority(**changed))
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                f"/api/v1/agent/device/requests/{request_id}/claim", json={"device_id": "d"}
            )
            assert response.status_code == 409
        value = await bridge.read(routes.request_key(request_id))
        assert value["status"] == "requested"
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_revocation_during_policy_io_rejects_claim(bridge, monkeypatch):
    task, request_id = await start_request(bridge)
    app, _, loader = application(bridge, monkeypatch)
    loader.side_effect = [
        (authority(), SimpleNamespace(workspace_id=None)),
        (authority(revision=2), SimpleNamespace(workspace_id=None)),
    ]
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                f"/api/v1/agent/device/requests/{request_id}/claim", json={"device_id": "d"}
            )
            assert response.status_code == 409
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_other_user_cannot_claim_and_status_requires_project_membership(bridge, monkeypatch):
    task, request_id = await start_request(bridge)
    app, db, loader = application(bridge, monkeypatch, user_id="other")
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                f"/api/v1/agent/device/requests/{request_id}/claim", json={"device_id": "d"}
            )
            assert response.status_code == 409 and loader.await_count == 0
            db.scalar.return_value = None
            status = await client.get(
                "/api/v1/agent/device/status",
                params={"device_id": "d", "tenant_id": "t", "project_id": "p"},
            )
            assert status.status_code == 403
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_device_status_confirms_exact_authenticated_registration(bridge, monkeypatch):
    app, _, _ = application(bridge, monkeypatch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        status = await client.get(
            "/api/v1/agent/device/status",
            params={"device_id": "d", "tenant_id": "t", "project_id": "p"},
        )
        assert status.json() == {
            "ready": True,
            "device_id": "d",
            "user_id": "u",
            "tenant_id": "t",
            "project_id": "p",
        }
