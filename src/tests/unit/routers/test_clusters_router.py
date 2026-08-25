from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status

from src.application.schemas.cluster_schemas import ClusterCreate, ClusterUpdate
from src.infrastructure.adapters.primary.web.routers import clusters as router


class _FailingClusterService:
    async def list_clusters_with_total(
        self, *_args: object, **_kwargs: object
    ) -> tuple[list[object], int]:
        return [], 0

    async def get_cluster(self, *_args: object, **_kwargs: object) -> object | None:
        return None

    async def update_cluster(self, **_kwargs: object) -> object:
        raise ValueError("Cluster cluster-secret not found")

    async def delete_cluster(self, *_args: object, **_kwargs: object) -> None:
        raise ValueError("Cluster cluster-secret not found")

    async def update_health_status(self, **_kwargs: object) -> object:
        raise ValueError("Cluster cluster-secret not found")


def _authority(
    *,
    service: object,
    db: object,
    user: object,
    runner_pools: object | None = None,
    tenant_id: str = "tenant-1",
) -> SimpleNamespace:
    return SimpleNamespace(
        db=db,
        current_user=user,
        tenant_id=tenant_id,
        services=SimpleNamespace(
            clusters=service,
            runner_pools=runner_pools or SimpleNamespace(),
        ),
    )


@pytest.fixture(autouse=True)
def allow_cluster_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    async def require_access(
        db: object,
        user: object,
        tenant_id: str,
        *,
        require_admin: bool = False,
    ) -> None:
        return None

    monkeypatch.setattr(router, "require_tenant_access", require_access)


@pytest.fixture
def db() -> SimpleNamespace:
    return SimpleNamespace(commit=AsyncMock())


@pytest.fixture
def user() -> SimpleNamespace:
    return SimpleNamespace(id="user-1")


@pytest.fixture
def authority(db: SimpleNamespace, user: SimpleNamespace) -> SimpleNamespace:
    return _authority(service=_FailingClusterService(), db=db, user=user)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("call_name", "call_args"),
    [
        (
            "get_cluster",
            {
                "cluster_id": "cluster-secret",
            },
        ),
        (
            "update_cluster",
            {
                "cluster_id": "cluster-secret",
                "data": ClusterUpdate(name="Updated"),
            },
        ),
        (
            "delete_cluster",
            {
                "cluster_id": "cluster-secret",
            },
        ),
        (
            "get_cluster_health",
            {
                "cluster_id": "cluster-secret",
            },
        ),
        (
            "update_health_status",
            {
                "cluster_id": "cluster-secret",
                "data": router.HealthStatusUpdate(
                    health_status="unreachable",
                    total_nodes=1,
                    active_nodes=0,
                    total_cpu=8,
                    used_cpu=1,
                    total_memory_gb=16,
                    used_memory_gb=2,
                ),
            },
        ),
    ],
)
async def test_cluster_routes_sanitize_not_found_errors(
    call_name: str,
    call_args: dict[str, object],
    authority: SimpleNamespace,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await getattr(router, call_name)(**call_args, authority=authority)

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "Cluster not found"
    assert "secret" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.parametrize(
    ("call_name", "call_args"),
    [
        (
            "create_cluster",
            {
                "data": ClusterCreate(name="Cluster"),
            },
        ),
        (
            "update_cluster",
            {
                "cluster_id": "cluster-secret",
                "data": ClusterUpdate(name="Updated"),
            },
        ),
        (
            "delete_cluster",
            {
                "cluster_id": "cluster-secret",
            },
        ),
        (
            "update_health_status",
            {
                "cluster_id": "cluster-secret",
                "data": router.HealthStatusUpdate(
                    health_status="unreachable",
                    total_nodes=1,
                    active_nodes=0,
                    total_cpu=8,
                    used_cpu=1,
                    total_memory_gb=16,
                    used_memory_gb=2,
                ),
            },
        ),
    ],
)
async def test_cluster_write_routes_require_admin_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
    call_name: str,
    call_args: dict[str, object],
    authority: SimpleNamespace,
) -> None:
    async def deny_admin(
        *_args: object,
        **_kwargs: object,
    ) -> None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    monkeypatch.setattr(router, "require_tenant_access", deny_admin)

    with pytest.raises(HTTPException) as exc_info:
        await getattr(router, call_name)(**call_args, authority=authority)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert exc_info.value.detail == "Admin access required"
    authority.db.commit.assert_not_awaited()


@pytest.mark.unit
async def test_list_clusters_returns_full_total(
    db: SimpleNamespace,
    user: SimpleNamespace,
) -> None:
    page_cluster = SimpleNamespace(
        id="cluster-page-1",
        name="Cluster Page 1",
        tenant_id="tenant-1",
        compute_provider="docker",
        proxy_endpoint=None,
        provider_config={},
        credentials_encrypted=None,
        status="disconnected",
        health_status=None,
        last_health_check=None,
        created_by="user-1",
        created_at=datetime.now(UTC),
        updated_at=None,
    )

    class ClusterService:
        async def list_clusters_with_total(
            self,
            *_args: object,
            **_kwargs: object,
        ) -> tuple[list[object], int]:
            return [page_cluster], 21

    response = await router.list_clusters(
        page=2,
        page_size=1,
        authority=_authority(service=ClusterService(), db=db, user=user),
    )

    assert len(response.clusters) == 1
    assert response.total == 21
    assert response.page == 2
    assert response.page_size == 1
