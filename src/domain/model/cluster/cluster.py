"""Cluster domain entity."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.domain.shared_kernel import Entity

from .enums import ClusterProvider, ClusterStatus


@dataclass(kw_only=True)
class Cluster(Entity):
    """A compute cluster registered to a tenant.

    Attributes:
        name: Human-readable cluster name.
        tenant_id: Owning tenant identifier.
        compute_provider: Infrastructure provider backing this cluster.
        status: Current connectivity status.
        health_status: Free-form health description (e.g. "healthy", "degraded").
        last_health_check: Timestamp of the most recent health probe.
        proxy_endpoint: K8s API proxy endpoint URL.
        created_by: User ID of the creator.
        provider_config: JSONB provider-specific configuration blob.
        credentials_encrypted: Encrypted kubeconfig or provider credentials.
        created_at: Creation timestamp.
        updated_at: Last-modified timestamp.
        deleted_at: Soft-delete timestamp; non-None means logically deleted.
    """

    name: str
    tenant_id: str
    compute_provider: ClusterProvider = ClusterProvider.docker
    status: ClusterStatus = ClusterStatus.disconnected
    health_status: str | None = None
    last_health_check: datetime | None = None
    proxy_endpoint: str | None = None
    created_by: str = ""
    provider_config: dict[str, Any] = field(default_factory=dict)
    credentials_encrypted: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None
    deleted_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Cluster name cannot be empty")
        if not self.tenant_id:
            raise ValueError("Cluster tenant_id cannot be empty")

    # ------------------------------------------------------------------
    # Domain methods
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        """Return True when the cluster reports a connected status."""
        return self.status == ClusterStatus.connected

    def mark_connected(self) -> None:
        """Transition the cluster to *connected* and record a health check."""
        self.status = ClusterStatus.connected
        self.last_health_check = datetime.now(UTC)

    def mark_disconnected(self) -> None:
        """Transition the cluster to *disconnected*."""
        self.status = ClusterStatus.disconnected

    def soft_delete(self) -> None:
        """Mark this cluster as logically deleted."""
        self.deleted_at = datetime.now(UTC)
