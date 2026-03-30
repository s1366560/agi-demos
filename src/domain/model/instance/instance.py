"""Instance and InstanceMember domain entities."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.domain.shared_kernel import Entity

from .enums import InstanceRole, InstanceStatus, ServiceType


@dataclass(kw_only=True)
class Instance(Entity):
    """Managed agent instance within a tenant."""

    name: str
    slug: str
    tenant_id: str
    cluster_id: str | None = None
    namespace: str | None = None
    image_version: str = "latest"
    replicas: int = 1
    cpu_request: str = "100m"
    cpu_limit: str = "500m"
    mem_request: str = "256Mi"
    mem_limit: str = "512Mi"
    service_type: ServiceType = ServiceType.cluster_ip
    ingress_domain: str | None = None
    proxy_token: str | None = None
    env_vars: dict[str, Any] = field(default_factory=dict)
    quota_cpu: str | None = None
    quota_memory: str | None = None
    quota_max_pods: int | None = None
    storage_class: str | None = None
    storage_size: str | None = None
    advanced_config: dict[str, Any] = field(default_factory=dict)
    llm_providers: dict[str, Any] = field(default_factory=dict)
    pending_config: dict[str, Any] = field(default_factory=dict)
    available_replicas: int = 0
    status: InstanceStatus = InstanceStatus.creating
    health_status: str | None = None
    current_revision: int = 0
    compute_provider: str | None = None
    runtime: str = "default"
    created_by: str = ""
    workspace_id: str | None = None
    hex_position_q: int | None = None
    hex_position_r: int | None = None
    agent_display_name: str | None = None
    agent_label: str | None = None
    theme_color: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None
    deleted_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Instance name cannot be empty")
        if not self.slug:
            raise ValueError("Instance slug cannot be empty")
        if not self.tenant_id:
            raise ValueError("Instance tenant_id cannot be empty")
        if self.replicas < 0:
            raise ValueError("Instance replicas must be >= 0")

    def is_running(self) -> bool:
        return self.status == InstanceStatus.running

    def is_deployable(self) -> bool:
        return self.status != InstanceStatus.deleting

    def soft_delete(self) -> None:
        self.deleted_at = datetime.now(UTC)


@dataclass(kw_only=True)
class InstanceMember(Entity):
    """Membership linking a user to an Instance with a specific role."""

    instance_id: str
    user_id: str
    role: InstanceRole = InstanceRole.viewer
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    deleted_at: datetime | None = None
