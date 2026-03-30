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

    async def get_cluster(self, cluster_id: str) -> Cluster | None:
        """
        Retrieve a cluster by ID.

        Args:
            cluster_id: Cluster ID.

        Returns:
            Cluster if found, None otherwise.
        """
        return await self._cluster_repo.find_by_id(cluster_id)

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
        proxy_endpoint: str | None = None,
        provider_config: dict[str, Any] | None = None,
        credentials_encrypted: str | None = None,
    ) -> Cluster:
        """
        Update cluster properties.

        Args:
            cluster_id: Cluster ID.
            name: New name (optional).
            proxy_endpoint: New proxy endpoint (optional).
            provider_config: New provider config (optional).
            credentials_encrypted: New credentials (optional).

        Returns:
            Updated cluster.

        Raises:
            ValueError: If cluster does not exist.
        """
        cluster = await self._cluster_repo.find_by_id(cluster_id)
        if not cluster:
            raise ValueError(f"Cluster {cluster_id} not found")

        if name is not None:
            cluster.name = name
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

    async def delete_cluster(self, cluster_id: str) -> None:
        """
        Soft-delete a cluster.

        Args:
            cluster_id: Cluster ID.

        Raises:
            ValueError: If cluster does not exist.
        """
        cluster = await self._cluster_repo.find_by_id(cluster_id)
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
    ) -> Cluster:
        """
        Update cluster connectivity status and health information.

        Args:
            cluster_id: Cluster ID.
            status: New cluster status.
            health_status: Free-form health description (optional).

        Returns:
            Updated cluster.

        Raises:
            ValueError: If cluster does not exist.
        """
        cluster = await self._cluster_repo.find_by_id(cluster_id)
        if not cluster:
            raise ValueError(f"Cluster {cluster_id} not found")

        cluster.status = status
        cluster.health_status = health_status
        cluster.last_health_check = datetime.now(UTC)
        cluster.updated_at = datetime.now(UTC)

        await self._cluster_repo.save(cluster)
        logger.info(f"Updated cluster {cluster_id} health: status={status.value}")
        return cluster
