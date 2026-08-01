from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException, status
from httpx import ASGITransport, AsyncClient

from src.infrastructure.agent.pool.api import project_router


@pytest.mark.unit
async def test_project_pool_endpoint_requires_authentication() -> None:
    app = FastAPI()
    app.include_router(project_router.create_project_pool_router())

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/v1/tenants/tenant-a/projects/project-a/pool/instances/chat"
        )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def _instance(tenant_id: str, project_id: str, agent_mode: str = "chat") -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(
            tenant_id=tenant_id,
            project_id=project_id,
            agent_mode=agent_mode,
            tier=SimpleNamespace(value="hot"),
        ),
        status=SimpleNamespace(value="ready"),
        created_at=None,
        last_request_at=None,
        _metrics=SimpleNamespace(active_requests=0, total_requests=0, memory_used_mb=0.0),
        _last_health_check=SimpleNamespace(status=SimpleNamespace(value="healthy")),
    )


@pytest.mark.unit
async def test_project_pool_read_resolves_only_the_exact_project_instance(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.configuration.config.get_settings",
        lambda: SimpleNamespace(agent_pool_enabled=True),
    )
    exact = _instance("tenant-a", "project-a")
    manager = SimpleNamespace(
        _instances={
            "tenant-a:project-a:chat": exact,
            "tenant-b:project-b:chat": _instance("tenant-b", "project-b"),
        }
    )
    access = project_router.ProjectPoolAccess(
        tenant_id="tenant-a",
        project_id="project-a",
        role="member",
    )

    response = await project_router._get_project_pool_instance(
        tenant_id="tenant-a",
        project_id="project-a",
        agent_mode="chat",
        access=access,
        manager=manager,
    )

    assert response.enabled is True
    assert response.instance is not None
    assert response.instance.tenant_id == "tenant-a"
    assert response.instance.project_id == "project-a"
    assert response.allowed_actions == ["view"]


@pytest.mark.unit
async def test_project_pool_member_cannot_mutate_shared_instance() -> None:
    access = project_router.ProjectPoolAccess(
        tenant_id="tenant-a",
        project_id="project-a",
        role="member",
    )

    with pytest.raises(HTTPException) as exc_info:
        project_router.require_project_pool_lifecycle_access(access)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert exc_info.value.detail == "Project owner or admin access required"


@pytest.mark.unit
async def test_project_pool_non_member_cannot_read_project_authority(monkeypatch) -> None:
    monkeypatch.setattr(
        project_router,
        "has_global_admin_access",
        AsyncMock(return_value=False),
    )
    db = AsyncMock()
    db.execute.side_effect = [
        SimpleNamespace(
            one_or_none=lambda: SimpleNamespace(tenant_id="tenant-a", owner_id="owner-1")
        ),
        SimpleNamespace(scalar_one_or_none=lambda: None),
    ]

    with pytest.raises(HTTPException) as exc_info:
        await project_router.resolve_project_pool_access(
            tenant_id="tenant-a",
            project_id="project-a",
            current_user=SimpleNamespace(id="non-member"),
            db=db,
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert exc_info.value.detail == "Project access required"


@pytest.mark.unit
@pytest.mark.parametrize("role", ["owner", "admin"])
async def test_project_pool_privileged_mutation_records_audit(monkeypatch, role: str) -> None:
    instance = _instance("tenant-a", "project-a")
    instance.pause = AsyncMock()
    manager = SimpleNamespace(_instances={"tenant-a:project-a:chat": instance})
    access = project_router.ProjectPoolAccess(
        tenant_id="tenant-a",
        project_id="project-a",
        role=role,
        actor_id=f"{role}-1",
    )
    audit_service = SimpleNamespace(log_event=AsyncMock())
    monkeypatch.setattr(project_router, "get_audit_service", lambda: audit_service)

    response = await project_router._mutate_project_pool_instance(
        action="pause",
        tenant_id="tenant-a",
        project_id="project-a",
        agent_mode="chat",
        access=access,
        manager=manager,
    )

    assert response.success is True
    assert response.allowed_actions == ["view", "pause", "resume", "terminate"]
    instance.pause.assert_awaited_once_with()
    audit_service.log_event.assert_awaited_once_with(
        action="runtime_pool.project_instance.pause",
        resource_type="runtime_pool_instance",
        resource_id="tenant-a:project-a:chat",
        actor=f"{role}-1",
        tenant_id="tenant-a",
        details={
            "scope": "project",
            "project_id": "project-a",
            "agent_mode": "chat",
            "result": "success",
        },
    )


@pytest.mark.unit
async def test_project_pool_path_scope_cannot_be_rebound() -> None:
    access = project_router.ProjectPoolAccess(
        tenant_id="tenant-b",
        project_id="project-b",
        role="owner",
    )

    with pytest.raises(HTTPException) as exc_info:
        await project_router._get_project_pool_instance(
            tenant_id="tenant-a",
            project_id="project-a",
            agent_mode="chat",
            access=access,
            manager=SimpleNamespace(_instances={}),
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "Pool instance not found"
