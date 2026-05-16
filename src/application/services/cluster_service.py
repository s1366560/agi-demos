"""
ClusterService: Business logic for cluster management.

This service handles cluster CRUD operations and health tracking,
following the hexagonal architecture pattern.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from src.domain.model.cluster.cluster import Cluster
from src.domain.model.cluster.enums import ClusterProvider, ClusterStatus
from src.domain.ports.repositories.cluster_repository import (
    ClusterRepository,
)

logger = logging.getLogger(__name__)


class ClusterService:
    """Service for managing compute clusters."""

    def __init__(self, cluster_repo: ClusterRepository) -> None:
        self._cluster_repo = cluster_repo

    async def create_cluster(
        self,
        name: str,
        tenant_id: str,
        created_by: str,
        compute_provider: str = "docker",
        proxy_endpoint: str | None = None,
        provider_config: dict[str, Any] | None = None,
        credentials_encrypted: str | None = None,
    ) -> Cluster:
        """
        Create a new cluster.

        Args:
            name: Human-readable cluster name.
            tenant_id: Owning tenant ID.
            created_by: User ID of the creator.
            compute_provider: Infrastructure provider (default: docker).
            proxy_endpoint: K8s API proxy endpoint URL (optional).
            provider_config: Provider-specific configuration (optional).
            credentials_encrypted: Encrypted credentials (optional).

        Returns:
            Created cluster.
        """
        cluster = Cluster(
            id=Cluster.generate_id(),
            name=name,
            tenant_id=tenant_id,
            created_by=created_by,
            compute_provider=ClusterProvider(compute_provider),
            proxy_endpoint=proxy_endpoint,
            provider_config=provider_config or {},
            credentials_encrypted=credentials_encrypted,
            created_at=datetime.now(UTC),
        )

        await self._cluster_repo.save(cluster)
        logger.info(f"Created cluster {cluster.id} for tenant {tenant_id}")
        return cluster

    async def get_cluster(self, cluster_id: str, tenant_id: str | None = None) -> Cluster | None:
        """
        Retrieve a cluster by ID.

        Args:
            cluster_id: Cluster ID.
            tenant_id: Optional tenant guard.

        Returns:
            Cluster if found, None otherwise.
        """
        cluster = await self._cluster_repo.find_by_id(cluster_id)
        if cluster is None or (tenant_id is not None and cluster.tenant_id != tenant_id):
            return None
        return cluster

    async def list_clusters(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Cluster]:
        """
        List clusters for a tenant.

        Args:
            tenant_id: Tenant ID to filter by.
            limit: Maximum number of results.
            offset: Number of results to skip.

        Returns:
            List of clusters.
        """
        return await self._cluster_repo.find_by_tenant(tenant_id, limit=limit, offset=offset)

    async def update_cluster(
        self,
        cluster_id: str,
        name: str | None = None,
        compute_provider: str | None = None,
        proxy_endpoint: str | None = None,
        provider_config: dict[str, Any] | None = None,
        credentials_encrypted: str | None = None,
        tenant_id: str | None = None,
    ) -> Cluster:
        """
        Update cluster properties.

        Args:
            cluster_id: Cluster ID.
            name: New name (optional).
            compute_provider: New compute provider (optional).
            proxy_endpoint: New proxy endpoint (optional).
            provider_config: New provider config (optional).
            credentials_encrypted: New credentials (optional).
            tenant_id: Optional tenant guard.

        Returns:
            Updated cluster.

        Raises:
            ValueError: If cluster does not exist.
        """
        cluster = await self.get_cluster(cluster_id, tenant_id=tenant_id)
        if not cluster:
            raise ValueError(f"Cluster {cluster_id} not found")

        if name is not None:
            cluster.name = name
        if compute_provider is not None:
            cluster.compute_provider = ClusterProvider(compute_provider)
        if proxy_endpoint is not None:
            cluster.proxy_endpoint = proxy_endpoint
        if provider_config is not None:
            cluster.provider_config = provider_config
        if credentials_encrypted is not None:
            cluster.credentials_encrypted = credentials_encrypted

        cluster.updated_at = datetime.now(UTC)

        await self._cluster_repo.save(cluster)
        logger.info(f"Updated cluster {cluster_id}")
        return cluster

    async def delete_cluster(self, cluster_id: str, tenant_id: str | None = None) -> None:
        """
        Soft-delete a cluster.

        Args:
            cluster_id: Cluster ID.
            tenant_id: Optional tenant guard.

        Raises:
            ValueError: If cluster does not exist.
        """
        cluster = await self.get_cluster(cluster_id, tenant_id=tenant_id)
        if not cluster:
            raise ValueError(f"Cluster {cluster_id} not found")

        cluster.soft_delete()

        await self._cluster_repo.save(cluster)
        logger.info(f"Soft-deleted cluster {cluster_id}")

    async def update_health_status(
        self,
        cluster_id: str,
        status: ClusterStatus,
        health_status: str | None = None,
        total_nodes: int | None = None,
        active_nodes: int | None = None,
        total_cpu: float | None = None,
        used_cpu: float | None = None,
        total_memory_gb: float | None = None,
        used_memory_gb: float | None = None,
        tenant_id: str | None = None,
    ) -> Cluster:
        """
        Update cluster connectivity status and health information.

        Args:
            cluster_id: Cluster ID.
            status: New cluster status.
            health_status: Free-form health description (optional).
            total_nodes: Total number of cluster nodes (optional).
            active_nodes: Number of active nodes (optional).
            total_cpu: Total CPU capacity (optional).
            used_cpu: Used CPU capacity (optional).
            total_memory_gb: Total memory in GB (optional).
            used_memory_gb: Used memory in GB (optional).
            tenant_id: Optional tenant guard.

        Returns:
            Updated cluster.

        Raises:
            ValueError: If cluster does not exist.
        """
        cluster = await self.get_cluster(cluster_id, tenant_id=tenant_id)
        if not cluster:
            raise ValueError(f"Cluster {cluster_id} not found")

        checked_at = datetime.now(UTC)
        cluster.status = status
        cluster.health_status = health_status
        cluster.last_health_check = checked_at
        cluster.updated_at = checked_at
        if any(
            value is not None
            for value in (
                total_nodes,
                active_nodes,
                total_cpu,
                used_cpu,
                total_memory_gb,
                used_memory_gb,
            )
        ):
            cluster.provider_config = {
                **cluster.provider_config,
                "health": {
                    **self._existing_health_config(cluster.provider_config),
                    "total_nodes": total_nodes,
                    "active_nodes": active_nodes,
                    "total_cpu": total_cpu,
                    "used_cpu": used_cpu,
                    "total_memory_gb": total_memory_gb,
                    "used_memory_gb": used_memory_gb,
                    "checked_at": checked_at.isoformat(),
                },
            }

        await self._cluster_repo.save(cluster)
        logger.info(f"Updated cluster {cluster_id} health: status={status.value}")
        return cluster

    @staticmethod
    def _existing_health_config(provider_config: dict[str, Any]) -> dict[str, Any]:
        health = provider_config.get("health")
        return dict(health) if isinstance(health, dict) else {}
