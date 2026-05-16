from datetime import UTC, datetime

import pytest

from src.application.services.cluster_service import ClusterService
from src.domain.model.cluster.cluster import Cluster
from src.domain.model.cluster.enums import ClusterProvider, ClusterStatus
from src.infrastructure.adapters.primary.web.routers.clusters import _cluster_health_response


class FakeClusterRepository:
    def __init__(self, cluster: Cluster) -> None:
        self.cluster = cluster
        self.saved: list[Cluster] = []

    async def save(self, cluster: Cluster) -> None:
        self.cluster = cluster
        self.saved.append(cluster)

    async def find_by_id(self, cluster_id: str) -> Cluster | None:
        return self.cluster if cluster_id == self.cluster.id else None

    async def find_by_tenant(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Cluster]:
        del limit, offset
        return [self.cluster] if tenant_id == self.cluster.tenant_id else []

    async def find_by_name(self, tenant_id: str, name: str) -> Cluster | None:
        if tenant_id == self.cluster.tenant_id and name == self.cluster.name:
            return self.cluster
        return None


def _cluster() -> Cluster:
    return Cluster(
        id="cluster-1",
        name="Primary",
        tenant_id="tenant-1",
        compute_provider=ClusterProvider.docker,
        status=ClusterStatus.disconnected,
        created_by="user-1",
        created_at=datetime.now(UTC),
    )


@pytest.mark.unit
async def test_update_cluster_persists_compute_provider() -> None:
    repo = FakeClusterRepository(_cluster())
    service = ClusterService(repo)  # type: ignore[arg-type]

    updated = await service.update_cluster("cluster-1", compute_provider="custom")

    assert updated.compute_provider == ClusterProvider.custom
    assert repo.saved[-1].compute_provider == ClusterProvider.custom


@pytest.mark.unit
async def test_get_cluster_returns_none_for_cross_tenant_access() -> None:
    repo = FakeClusterRepository(_cluster())
    service = ClusterService(repo)  # type: ignore[arg-type]

    result = await service.get_cluster("cluster-1", tenant_id="tenant-2")

    assert result is None


@pytest.mark.unit
async def test_update_cluster_rejects_cross_tenant_access() -> None:
    repo = FakeClusterRepository(_cluster())
    service = ClusterService(repo)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="Cluster cluster-1 not found"):
        await service.update_cluster("cluster-1", name="Wrong tenant", tenant_id="tenant-2")

    assert repo.saved == []


@pytest.mark.unit
async def test_update_health_status_persists_metrics_for_health_response() -> None:
    repo = FakeClusterRepository(_cluster())
    service = ClusterService(repo)  # type: ignore[arg-type]

    updated = await service.update_health_status(
        "cluster-1",
        status=ClusterStatus.connected,
        health_status="healthy",
        total_nodes=4,
        active_nodes=3,
        total_cpu=8,
        used_cpu=2,
        total_memory_gb=16,
        used_memory_gb=8,
    )

    assert updated.provider_config["health"]["total_nodes"] == 4
    assert updated.provider_config["health"]["active_nodes"] == 3
    assert updated.last_health_check is not None

    response = _cluster_health_response(updated)
    assert response.status == "healthy"
    assert response.node_count == 4
    assert response.cpu_usage == 25
    assert response.memory_usage == 50
    assert response.checked_at == updated.last_health_check
