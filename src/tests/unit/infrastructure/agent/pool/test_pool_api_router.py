from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException, status
from httpx import ASGITransport, AsyncClient

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.agent.pool.api import router


class _FailingInstance:
    status = SimpleNamespace(value="ready")

    async def pause(self) -> None:
        raise RuntimeError("secret pause backend reason")


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


def _pool_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router.create_pool_router())
    return app


@pytest.mark.unit
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/admin/pool/status"),
        ("GET", "/api/v1/admin/pool/instances"),
        ("GET", "/api/v1/admin/pool/instances/tenant:project:agent"),
        ("POST", "/api/v1/admin/pool/instances/tenant:project:agent/pause"),
        ("POST", "/api/v1/admin/pool/instances/tenant:project:agent/resume"),
        ("DELETE", "/api/v1/admin/pool/instances/tenant:project:agent"),
        ("GET", "/api/v1/admin/pool/projects/project/tier?tenant_id=tenant"),
        ("POST", "/api/v1/admin/pool/projects/project/tier?tenant_id=tenant"),
        ("GET", "/api/v1/admin/pool/metrics"),
        ("GET", "/api/v1/admin/pool/metrics/prometheus"),
    ],
)
async def test_every_pool_endpoint_requires_authentication(method: str, path: str) -> None:
    app = _pool_test_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.request(method, path, json={"tier": "hot"})

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.unit
async def test_pool_endpoint_rejects_authenticated_non_global_admin() -> None:
    app = _pool_test_app()
    current_user = SimpleNamespace(id="member-1", is_superuser=False, roles=[])
    db = AsyncMock()
    db_result = SimpleNamespace(scalar_one_or_none=lambda: None)
    db.execute.return_value = db_result
    app.dependency_overrides[get_current_user] = lambda: current_user
    app.dependency_overrides[get_db] = lambda: db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/admin/pool/status")

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.json() == {"detail": "Global admin access required"}


@pytest.mark.unit
async def test_global_admin_must_use_a_structurally_valid_scope() -> None:
    app = _pool_test_app()
    current_user = SimpleNamespace(id="admin-1", is_superuser=True, roles=[])
    app.dependency_overrides[get_current_user] = lambda: current_user
    app.dependency_overrides[get_db] = lambda: AsyncMock()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        valid = await client.get("/api/v1/admin/pool/status?scope=global")
        rebound = await client.get("/api/v1/admin/pool/status?scope=global&tenant_id=tenant-a")
        missing_tenant = await client.get("/api/v1/admin/pool/status?scope=tenant")

    assert valid.status_code == status.HTTP_200_OK
    assert valid.json()["resolved_scope"] == "global"
    assert rebound.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert missing_tenant.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.unit
async def test_implicit_global_scope_returns_deprecation_headers() -> None:
    app = _pool_test_app()
    current_user = SimpleNamespace(id="admin-1", is_superuser=True, roles=[])
    app.dependency_overrides[get_current_user] = lambda: current_user
    app.dependency_overrides[get_db] = lambda: AsyncMock()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/admin/pool/status")

    assert response.status_code == status.HTTP_200_OK
    assert response.headers["deprecation"] == "true"
    assert response.headers["sunset"] == "Sat, 01 Nov 2026 00:00:00 GMT"
    assert response.json()["resolved_scope"] == "global"


@pytest.mark.unit
async def test_tenant_scope_rejects_unknown_tenant() -> None:
    app = _pool_test_app()
    current_user = SimpleNamespace(id="admin-1", is_superuser=True, roles=[])
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: None)
    app.dependency_overrides[get_current_user] = lambda: current_user
    app.dependency_overrides[get_db] = lambda: db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/v1/admin/pool/status?scope=tenant&tenant_id=missing-tenant"
        )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json() == {"detail": "Tenant not found"}


@pytest.mark.unit
async def test_tenant_scope_filters_before_total_and_pagination() -> None:
    manager = SimpleNamespace(
        _instances={
            "stored-a": _instance("tenant-a", "project-a"),
            "stored-b": _instance("tenant-b", "project-b"),
        }
    )
    resolved_scope = router.PoolAuthorityScope(
        scope=router.PoolScope.TENANT,
        tenant_id="tenant-a",
    )

    response = await router._list_instances(
        manager=manager,
        resolved_scope=resolved_scope,
        tier=None,
        status=None,
        page=1,
        page_size=1,
    )

    assert response.total == 1
    assert [item.tenant_id for item in response.instances] == ["tenant-a"]
    assert response.resolved_scope == "tenant"
    assert response.tenant_id == "tenant-a"


@pytest.mark.unit
async def test_tenant_status_and_metrics_do_not_disclose_global_capacity(monkeypatch) -> None:
    tenant_instance = _instance("tenant-a", "project-a")
    cross_tenant_instance = _instance("tenant-b", "project-b")
    cross_tenant_instance._metrics.memory_used_mb = 4096.0
    manager = SimpleNamespace(
        _instances={
            "stored-a": tenant_instance,
            "stored-b": cross_tenant_instance,
        },
        get_stats=lambda: pytest.fail("tenant scope must not read global pool stats"),
    )
    resolved_scope = router.PoolAuthorityScope(
        scope=router.PoolScope.TENANT,
        tenant_id="tenant-a",
    )
    monkeypatch.setattr(
        "src.configuration.config.get_settings",
        lambda: SimpleNamespace(agent_pool_enabled=True),
    )
    monkeypatch.setattr(router, "_get_pool_manager_optional", AsyncMock(return_value=manager))

    pool_status = await router._get_pool_status(resolved_scope=resolved_scope)
    metrics = await router._get_metrics_json(
        manager=manager,
        resolved_scope=resolved_scope,
    )

    assert pool_status.total_instances == 1
    assert pool_status.prewarm_pool is None
    assert pool_status.resource_usage is None
    assert pool_status.reason_code == "global_pool_capacity_not_available_in_tenant_scope"
    assert metrics.instances["total"] == 1
    assert metrics.prewarm is None
    assert metrics.reason_code == "global_pool_capacity_not_available_in_tenant_scope"


@pytest.mark.unit
async def test_tenant_scope_hides_cross_tenant_instance_detail() -> None:
    manager = SimpleNamespace(_instances={"misleading-tenant-a-key": _instance("tenant-b", "p")})
    resolved_scope = router.PoolAuthorityScope(
        scope=router.PoolScope.TENANT,
        tenant_id="tenant-a",
    )

    with pytest.raises(HTTPException) as exc_info:
        await router._get_instance(
            "misleading-tenant-a-key",
            manager=manager,
            resolved_scope=resolved_scope,
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "Instance not found"


@pytest.mark.unit
async def test_tenant_scope_blocks_cross_tenant_lifecycle_without_mutation() -> None:
    instance = _instance("tenant-b", "project-b")
    instance.pause = AsyncMock()
    manager = SimpleNamespace(_instances={"stored-b": instance})
    resolved_scope = router.PoolAuthorityScope(
        scope=router.PoolScope.TENANT,
        tenant_id="tenant-a",
    )

    with pytest.raises(HTTPException) as exc_info:
        await router._pause_instance(
            "stored-b",
            manager=manager,
            resolved_scope=resolved_scope,
            current_user=SimpleNamespace(id="admin-1"),
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    instance.pause.assert_not_awaited()


@pytest.mark.unit
async def test_pause_returns_conflict_when_instance_state_cannot_pause() -> None:
    instance = _instance("tenant-a", "project-a")
    instance.status = SimpleNamespace(value="paused")
    instance.pause = AsyncMock()
    manager = SimpleNamespace(_instances={"stored-a": instance})

    with pytest.raises(HTTPException) as exc_info:
        await router._pause_instance(
            "stored-a",
            manager=manager,
            resolved_scope=router.PoolAuthorityScope(scope=router.PoolScope.GLOBAL),
            current_user=SimpleNamespace(id="admin-1"),
        )

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert exc_info.value.detail == "Pool instance state conflict"
    instance.pause.assert_not_awaited()


@pytest.mark.unit
async def test_successful_lifecycle_mutation_records_structured_audit(monkeypatch) -> None:
    instance = _instance("tenant-a", "project-a")
    instance.pause = AsyncMock()
    manager = SimpleNamespace(_instances={"stored-a": instance})
    audit_service = SimpleNamespace(log_event=AsyncMock())
    monkeypatch.setattr(router, "get_audit_service", lambda: audit_service)
    resolved_scope = router.PoolAuthorityScope(
        scope=router.PoolScope.TENANT,
        tenant_id="tenant-a",
    )

    response = await router._pause_instance(
        "stored-a",
        manager=manager,
        resolved_scope=resolved_scope,
        current_user=SimpleNamespace(id="admin-1"),
    )

    assert response.success is True
    audit_service.log_event.assert_awaited_once_with(
        action="runtime_pool.instance.paused",
        resource_type="runtime_pool_instance",
        resource_id="stored-a",
        actor="admin-1",
        tenant_id="tenant-a",
        details={
            "scope": "tenant",
            "project_id": "project-a",
            "agent_mode": "chat",
            "result": "success",
        },
    )


@pytest.mark.unit
async def test_get_instance_sanitizes_missing_instance_key() -> None:
    manager = SimpleNamespace(_instances={})
    resolved_scope = router.PoolAuthorityScope(scope=router.PoolScope.GLOBAL)

    with pytest.raises(HTTPException) as exc_info:
        await router._get_instance(
            "tenant:project:secret-instance",
            manager=manager,
            resolved_scope=resolved_scope,
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "Instance not found"
    assert "secret-instance" not in exc_info.value.detail


@pytest.mark.unit
async def test_pause_instance_sanitizes_backend_error() -> None:
    manager = SimpleNamespace(_instances={"tenant:project:secret-instance": _FailingInstance()})
    resolved_scope = router.PoolAuthorityScope(scope=router.PoolScope.GLOBAL)

    with pytest.raises(HTTPException) as exc_info:
        await router._pause_instance(
            "tenant:project:secret-instance",
            manager=manager,
            resolved_scope=resolved_scope,
            current_user=SimpleNamespace(id="admin-1"),
        )

    assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert exc_info.value.detail == "Failed to pause instance"
    assert "secret pause backend reason" not in exc_info.value.detail


@pytest.mark.unit
async def test_set_project_tier_sanitizes_invalid_tier() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await router._set_project_tier(
            project_id="project-1",
            request=router.SetTierRequest(tier="secret-tier"),
            tenant_id="tenant-1",
            manager=SimpleNamespace(),
            resolved_scope=router.PoolAuthorityScope(
                scope=router.PoolScope.TENANT,
                tenant_id="tenant-1",
            ),
            current_user=SimpleNamespace(id="admin-1"),
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc_info.value.detail == "Invalid project tier"
    assert "secret-tier" not in exc_info.value.detail
