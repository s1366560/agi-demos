"""Cluster data models."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ClusterCreate(BaseModel):
    """Request model for creating a cluster."""

    name: str = Field(..., description="Cluster name", min_length=1, max_length=255)
    tenant_id: str = Field(..., description="Tenant ID")
    compute_provider: str = Field(
        default="docker",
        description="Compute provider type",
        max_length=50,
    )
    proxy_endpoint: str | None = Field(default=None, description="Proxy endpoint URL")
    provider_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider-specific configuration",
    )
    credentials_encrypted: str | None = Field(
        default=None,
        description="Encrypted provider credentials",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Production Cluster",
                "tenant_id": "tenant_123",
                "compute_provider": "docker",
                "proxy_endpoint": "https://proxy.example.com",
                "provider_config": {
                    "region": "us-east-1",
                    "node_count": 3,
                },
            }
        }
    )


class ClusterUpdate(BaseModel):
    """Request model for updating a cluster."""

    name: str | None = Field(
        default=None,
        description="Cluster name",
        min_length=1,
        max_length=255,
    )
    compute_provider: str | None = Field(
        default=None,
        description="Compute provider type",
        max_length=50,
    )
    proxy_endpoint: str | None = Field(default=None, description="Proxy endpoint URL")
    provider_config: dict[str, Any] | None = Field(
        default=None,
        description="Provider-specific configuration",
    )
    credentials_encrypted: str | None = Field(
        default=None,
        description="Encrypted provider credentials",
    )


class ClusterResponse(BaseModel):
    """Response model for cluster operations."""

    id: str = Field(..., description="Cluster unique identifier")
    name: str = Field(..., description="Cluster name")
    tenant_id: str = Field(..., description="Tenant ID")
    compute_provider: str = Field(default="docker", description="Compute provider type")
    proxy_endpoint: str | None = Field(default=None, description="Proxy endpoint URL")
    provider_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider-specific configuration",
    )
    credentials_encrypted: str | None = Field(
        default=None,
        description="Encrypted provider credentials",
    )
    status: str = Field(default="pending", description="Cluster status")
    health_status: str | None = Field(default=None, description="Cluster health status")
    last_health_check: datetime | None = Field(
        default=None, description="Last health check timestamp"
    )
    created_by: str | None = Field(
        default=None,
        description="User ID who created the cluster",
    )
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime | None = Field(default=None, description="Last update timestamp")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "cluster_550e8400",
                "name": "Production Cluster",
                "tenant_id": "tenant_123",
                "compute_provider": "docker",
                "proxy_endpoint": "https://proxy.example.com",
                "provider_config": {
                    "region": "us-east-1",
                    "node_count": 3,
                },
                "status": "active",
                "health_status": "healthy",
                "last_health_check": "2024-01-15T12:00:00Z",
                "created_by": "user_123",
                "created_at": "2024-01-15T10:30:00Z",
                "updated_at": "2024-01-15T12:45:00Z",
            }
        },
    )


class ClusterListResponse(BaseModel):
    """Response model for cluster list operations."""

    clusters: list[ClusterResponse] = Field(..., description="List of clusters")
    total: int = Field(..., description="Total number of clusters")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Page size")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "clusters": [
                    {
                        "id": "cluster_550e8400",
                        "name": "Production Cluster",
                        "tenant_id": "tenant_123",
                        "compute_provider": "docker",
                        "status": "active",
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
