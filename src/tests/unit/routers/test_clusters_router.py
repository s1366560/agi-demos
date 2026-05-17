from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status

from src.application.schemas.cluster_schemas import ClusterUpdate
from src.infrastructure.adapters.primary.web.routers import clusters as router


class _FailingClusterService:
    async def get_cluster(self, *_args: object, **_kwargs: object) -> object | None:
        return None

    async def update_cluster(self, **_kwargs: object) -> object:
        raise ValueError("Cluster cluster-secret not found")

    async def delete_cluster(self, *_args: object, **_kwargs: object) -> None:
        raise ValueError("Cluster cluster-secret not found")

    async def update_health_status(self, **_kwargs: object) -> object:
        raise ValueError("Cluster cluster-secret not found")


class _Container:
    def __init__(self) -> None:
        self.service = _FailingClusterService()

    def cluster_service(self) -> _FailingClusterService:
        return self.service


@pytest.fixture(autouse=True)
def failing_container(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(router, "get_container_with_db", lambda *_args: _Container())


@pytest.fixture
def db() -> SimpleNamespace:
    return SimpleNamespace(commit=AsyncMock())


@pytest.mark.unit
@pytest.mark.parametrize(
    ("call_name", "call_args"),
    [
        (
            "get_cluster",
            {
                "request": SimpleNamespace(),
                "cluster_id": "cluster-secret",
                "tenant_id": "tenant-1",
            },
        ),
        (
            "update_cluster",
            {
                "request": SimpleNamespace(),
                "cluster_id": "cluster-secret",
                "data": ClusterUpdate(name="Updated"),
                "tenant_id": "tenant-1",
            },
        ),
        (
            "delete_cluster",
            {
                "request": SimpleNamespace(),
                "cluster_id": "cluster-secret",
                "tenant_id": "tenant-1",
            },
        ),
        (
            "get_cluster_health",
            {
                "request": SimpleNamespace(),
                "cluster_id": "cluster-secret",
                "tenant_id": "tenant-1",
            },
        ),
        (
            "update_health_status",
            {
                "request": SimpleNamespace(),
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
                "tenant_id": "tenant-1",
            },
        ),
    ],
)
async def test_cluster_routes_sanitize_not_found_errors(
    call_name: str,
    call_args: dict[str, object],
    db: SimpleNamespace,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await getattr(router, call_name)(**call_args, db=db)

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "Cluster not found"
    assert "secret" not in exc_info.value.detail
