"""Instance and InstanceMember data models."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class InstanceCreate(BaseModel):
    """Request model for creating an instance."""

    name: str = Field(..., description="Instance name", min_length=1, max_length=255)
    slug: str = Field(
        ...,
        description="URL-friendly instance identifier",
        min_length=1,
        max_length=255,
    )
    tenant_id: str = Field(..., description="Tenant ID")
    cluster_id: str | None = Field(default=None, description="Cluster ID to deploy to")
    namespace: str | None = Field(default=None, description="Kubernetes namespace", max_length=255)
    image_version: str = Field(default="latest", description="Container image version")
    replicas: int = Field(default=1, ge=0, description="Number of replicas")
    cpu_request: str = Field(default="100m", description="CPU request", max_length=50)
    cpu_limit: str = Field(default="500m", description="CPU limit", max_length=50)
    mem_request: str = Field(default="256Mi", description="Memory request", max_length=50)
    mem_limit: str = Field(default="512Mi", description="Memory limit", max_length=50)
    service_type: str = Field(
        default="ClusterIP",
        description="Kubernetes service type",
        max_length=50,
    )
    ingress_domain: str | None = Field(default=None, description="Ingress domain name")
    env_vars: dict[str, Any] = Field(default_factory=dict, description="Environment variables")
    quota_cpu: str | None = Field(default=None, description="CPU quota", max_length=50)
    quota_memory: str | None = Field(default=None, description="Memory quota", max_length=50)
    quota_max_pods: int | None = Field(default=None, description="Maximum pods quota")
    storage_class: str | None = Field(
        default=None, description="Storage class name", max_length=255
    )
    storage_size: str | None = Field(default=None, description="Storage size", max_length=50)
    advanced_config: dict[str, Any] = Field(
        default_factory=dict, description="Advanced configuration"
    )
    llm_providers: dict[str, Any] = Field(
        default_factory=dict, description="LLM provider configurations"
    )
    compute_provider: str | None = Field(default=None, description="Compute provider identifier")
    runtime: str = Field(
        default="default",
        description="Runtime environment",
        max_length=100,
    )
    workspace_id: str | None = Field(default=None, description="Workspace ID")
    hex_position_q: int | None = Field(default=None, description="Hex grid position Q coordinate")
    hex_position_r: int | None = Field(default=None, description="Hex grid position R coordinate")
    agent_display_name: str | None = Field(
        default=None,
        description="Agent display name",
        max_length=255,
    )
    agent_label: str | None = Field(default=None, description="Agent label", max_length=255)
    theme_color: str | None = Field(
        default=None,
        description="Theme color hex code",
        max_length=7,
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Production Instance",
                "slug": "production-instance",
                "tenant_id": "tenant_123",
                "cluster_id": "cluster_456",
                "namespace": "production",
                "image_version": "1.2.0",
                "replicas": 2,
                "cpu_request": "200m",
                "cpu_limit": "1000m",
                "mem_request": "512Mi",
                "mem_limit": "1Gi",
                "service_type": "ClusterIP",
                "runtime": "default",
            }
        }
    )


class InstanceUpdate(BaseModel):
    """Request model for updating an instance."""

    name: str | None = Field(
        default=None,
        description="Instance name",
        min_length=1,
        max_length=255,
    )
    slug: str | None = Field(
        default=None,
        description="URL-friendly instance identifier",
        min_length=1,
        max_length=255,
    )
    cluster_id: str | None = Field(default=None, description="Cluster ID to deploy to")
    namespace: str | None = Field(default=None, description="Kubernetes namespace", max_length=255)
    image_version: str | None = Field(default=None, description="Container image version")
    replicas: int | None = Field(default=None, ge=0, description="Number of replicas")
    cpu_request: str | None = Field(default=None, description="CPU request", max_length=50)
    cpu_limit: str | None = Field(default=None, description="CPU limit", max_length=50)
    mem_request: str | None = Field(default=None, description="Memory request", max_length=50)
    mem_limit: str | None = Field(default=None, description="Memory limit", max_length=50)
    service_type: str | None = Field(
        default=None,
        description="Kubernetes service type",
        max_length=50,
    )
    ingress_domain: str | None = Field(default=None, description="Ingress domain name")
    env_vars: dict[str, Any] | None = Field(default=None, description="Environment variables")
    quota_cpu: str | None = Field(default=None, description="CPU quota", max_length=50)
    quota_memory: str | None = Field(default=None, description="Memory quota", max_length=50)
    quota_max_pods: int | None = Field(default=None, description="Maximum pods quota")
    storage_class: str | None = Field(
        default=None, description="Storage class name", max_length=255
    )
    storage_size: str | None = Field(default=None, description="Storage size", max_length=50)
    advanced_config: dict[str, Any] | None = Field(
        default=None, description="Advanced configuration"
    )
    llm_providers: dict[str, Any] | None = Field(
        default=None, description="LLM provider configurations"
    )
    compute_provider: str | None = Field(default=None, description="Compute provider identifier")
    runtime: str | None = Field(
        default=None,
        description="Runtime environment",
        max_length=100,
    )
    workspace_id: str | None = Field(default=None, description="Workspace ID")
    hex_position_q: int | None = Field(default=None, description="Hex grid position Q coordinate")
    hex_position_r: int | None = Field(default=None, description="Hex grid position R coordinate")
    agent_display_name: str | None = Field(
        default=None,
        description="Agent display name",
        max_length=255,
    )
    agent_label: str | None = Field(default=None, description="Agent label", max_length=255)
    theme_color: str | None = Field(
        default=None,
        description="Theme color hex code",
        max_length=7,
    )


class InstanceResponse(BaseModel):
    """Response model for instance operations."""

    id: str = Field(..., description="Instance unique identifier")
    name: str = Field(..., description="Instance name")
    slug: str = Field(..., description="URL-friendly instance identifier")
    tenant_id: str = Field(..., description="Tenant ID")
    cluster_id: str | None = Field(default=None, description="Cluster ID")
    namespace: str | None = Field(default=None, description="Kubernetes namespace")
    image_version: str = Field(default="latest", description="Container image version")
    replicas: int = Field(default=1, description="Desired number of replicas")
    cpu_request: str = Field(default="100m", description="CPU request")
    cpu_limit: str = Field(default="500m", description="CPU limit")
    mem_request: str = Field(default="256Mi", description="Memory request")
    mem_limit: str = Field(default="512Mi", description="Memory limit")
    service_type: str = Field(default="ClusterIP", description="Kubernetes service type")
    ingress_domain: str | None = Field(default=None, description="Ingress domain name")
    env_vars: dict[str, Any] = Field(default_factory=dict, description="Environment variables")
    quota_cpu: str | None = Field(default=None, description="CPU quota")
    quota_memory: str | None = Field(default=None, description="Memory quota")
    quota_max_pods: int | None = Field(default=None, description="Maximum pods quota")
    storage_class: str | None = Field(default=None, description="Storage class name")
    storage_size: str | None = Field(default=None, description="Storage size")
    advanced_config: dict[str, Any] = Field(
        default_factory=dict, description="Advanced configuration"
    )
    llm_providers: dict[str, Any] = Field(
        default_factory=dict, description="LLM provider configurations"
    )
    compute_provider: str | None = Field(default=None, description="Compute provider identifier")
    runtime: str = Field(default="default", description="Runtime environment")
    workspace_id: str | None = Field(default=None, description="Workspace ID")
    hex_position_q: int | None = Field(default=None, description="Hex grid position Q coordinate")
    hex_position_r: int | None = Field(default=None, description="Hex grid position R coordinate")
    agent_display_name: str | None = Field(default=None, description="Agent display name")
    agent_label: str | None = Field(default=None, description="Agent label")
    theme_color: str | None = Field(default=None, description="Theme color hex code")
    status: str = Field(default="pending", description="Instance status")
    health_status: str | None = Field(default=None, description="Instance health status")
    current_revision: int | None = Field(default=None, description="Current deployment revision")
    available_replicas: int | None = Field(default=None, description="Number of available replicas")
    proxy_token: str | None = Field(default=None, description="Proxy authentication token")
    pending_config: dict[str, Any] | None = Field(
        default=None, description="Pending configuration changes"
    )
    created_by: str | None = Field(default=None, description="User ID who created the instance")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime | None = Field(default=None, description="Last update timestamp")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "inst_550e8400",
                "name": "Production Instance",
                "slug": "production-instance",
                "tenant_id": "tenant_123",
                "cluster_id": "cluster_456",
                "namespace": "production",
                "image_version": "1.2.0",
                "replicas": 2,
                "cpu_request": "200m",
                "cpu_limit": "1000m",
                "mem_request": "512Mi",
                "mem_limit": "1Gi",
                "service_type": "ClusterIP",
                "status": "running",
                "health_status": "healthy",
                "current_revision": 3,
                "available_replicas": 2,
                "runtime": "default",
                "created_by": "user_123",
                "created_at": "2024-01-15T10:30:00Z",
                "updated_at": "2024-01-15T12:45:00Z",
            }
        },
    )


class InstanceListResponse(BaseModel):
    """Response model for instance list operations."""

    instances: list[InstanceResponse] = Field(..., description="List of instances")
    total: int = Field(..., description="Total number of instances")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Page size")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "instances": [
                    {
                        "id": "inst_550e8400",
                        "name": "Production Instance",
                        "slug": "production-instance",
                        "tenant_id": "tenant_123",
                        "status": "running",
                        "replicas": 2,
                        "created_at": "2024-01-15T10:30:00Z",
                        "updated_at": "2024-01-15T12:45:00Z",
                    }
                ],
                "total": 1,
                "page": 1,
                "page_size": 20,
            }
        }
    )


class InstanceMemberCreate(BaseModel):
    """Request model for adding an instance member."""

    instance_id: str = Field(..., description="Instance ID")
    user_id: str = Field(..., description="User ID to add")
    role: str = Field(
        default="viewer",
        description="Member role (admin, editor, viewer)",
        max_length=50,
    )


class InstanceMemberResponse(BaseModel):
    """Response model for instance member operations."""

    id: str = Field(..., description="Instance member unique identifier")
    instance_id: str = Field(..., description="Instance ID")
    user_id: str = Field(..., description="User ID")
    role: str = Field(..., description="Member role")
    user_name: str | None = Field(default=None, description="User display name")
    user_email: str | None = Field(default=None, description="User email address")
    user_avatar_url: str | None = Field(default=None, description="User avatar URL")
    created_at: datetime = Field(..., description="Creation timestamp")

    model_config = ConfigDict(from_attributes=True)


class InstanceMemberUpdate(BaseModel):
    """Request model for updating an instance member role."""

    role: str = Field(
        ...,
        description="New member role (admin, editor, user, viewer)",
        max_length=50,
    )


class UserSearchResult(BaseModel):
    """Response model for user search results."""

    id: str = Field(..., description="User ID")
    email: str = Field(..., description="User email")
    full_name: str | None = Field(default=None, description="User full name")
