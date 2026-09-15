"""Actual HTTP validation, fresh membership, and exact child registry identity."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from src.infrastructure.adapters.primary.web.routers.agent import (
    subagent_execution_control as routes,
)
from src.infrastructure.agent.subagent.owner_lease_v2 import OWNER_PROTOCOL_V2
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry

pytestmark = pytest.mark.unit


@pytest.fixture
async def boundary(monkeypatch):
    registry = SubAgentRunRegistry(sync_across_processes=False, recover_inflight_on_boot=False)
    registry.create_run(
        "conversation",
        "worker",
        "task",
        run_id="child",
        metadata={"execution_protocol": OWNER_PROTOCOL_V2},
    )
    registry.mark_running("conversation", "child")
    service = SimpleNamespace(request_cancel=AsyncMock(), request_steer=AsyncMock())
    db = SimpleNamespace(scalar=AsyncMock(return_value="user"))
    access = AsyncMock(return_value=SimpleNamespace(tenant_id="tenant", project_id="project"))
    monkeypatch.setattr(routes, "_get_accessible_conversation", access)
    monkeypatch.setattr(routes, "current_subagent_run_registry_v2", lambda: registry)
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1/agent")
    app.dependency_overrides[routes.get_current_user] = lambda: SimpleNamespace(id="user")
    app.dependency_overrides[routes.get_db] = lambda: db
    app.dependency_overrides[
        routes.agent_subagent_control_http_application_authority_dependency_v2
    ] = lambda: SimpleNamespace(service=service)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, registry, service, db, access


async def test_http_snapshot_and_versioned_control_allow_detached_child(boundary):
    client, registry, service, _, _ = boundary
    prefix = "/api/v1/agent/conversations/conversation"
    query = "?tenant_id=tenant&project_id=project"
    response = await client.get(prefix + "/subagent-controls" + query)
    assert response.status_code == 200
    assert response.json()["controls"][0]["run_id"] == "child"
    body = {
        "action": "steer",
        "expected_control_revision": 0,
        "idempotency_key": "command",
        "instruction": "test",
    }
    path = prefix + "/subagents/child/control" + query
    assert (await client.post(path, json=body)).status_code == 200
    registry.mark_completed("conversation", "child", summary="owner finished")
    assert (await client.post(path, json=body)).json()["duplicate"] is True
    service.request_steer.assert_awaited_once()
    body["idempotency_key"] = "new"
    assert (await client.post(path, json=body)).status_code == 409


@pytest.mark.parametrize(
    "case", ["tenant", "project", "membership", "conversation", "resource-id", "parent-revision"]
)
async def test_untrusted_scope_and_contract_cannot_send_control(boundary, case):
    client, _, service, db, access = boundary
    tenant, project, run = "tenant", "project", "child"
    body = {
        "action": "steer",
        "expected_control_revision": 0,
        "idempotency_key": "command",
        "instruction": "test",
    }
    if case == "tenant":
        tenant = "other"
    if case == "project":
        project = "other"
    if case == "membership":
        db.scalar.return_value = None
    if case == "conversation":
        access.side_effect = HTTPException(404, "not found")
    if case == "resource-id":
        run = "worker"
    if case == "parent-revision":
        body["expected_run_revision"] = 1
    response = await client.post(
        f"/api/v1/agent/conversations/conversation/subagents/{run}/control?tenant_id={tenant}&project_id={project}",
        json=body,
    )
    assert response.status_code in {404, 409, 422}
    service.request_steer.assert_not_awaited()
    service.request_cancel.assert_not_awaited()
