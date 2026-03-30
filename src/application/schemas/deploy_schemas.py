"""Deploy record data models."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DeployCreate(BaseModel):
    """Request model for creating a deploy record."""

    instance_id: str = Field(..., description="Instance ID to deploy")
    action: str = Field(
        default="create",
        description="Deploy action type",
        max_length=50,
    )
    image_version: str | None = Field(default=None, description="Target image version")
    replicas: int | None = Field(default=None, ge=0, description="Target replica count")
    config_snapshot: dict[str, Any] = Field(
        default_factory=dict,
        description="Configuration snapshot at deploy time",
    )
    triggered_by: str | None = Field(
        default=None, description="User or system that triggered the deploy"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "instance_id": "inst_550e8400",
                "action": "update",
                "image_version": "1.3.0",
                "replicas": 3,
                "config_snapshot": {
                    "cpu_limit": "1000m",
                    "mem_limit": "1Gi",
                },
                "triggered_by": "user_123",
            }
        }
    )


class DeployResponse(BaseModel):
    """Response model for deploy record operations."""

    id: str = Field(..., description="Deploy record unique identifier")
    instance_id: str = Field(..., description="Instance ID")
    action: str = Field(..., description="Deploy action type")
    revision: int = Field(..., description="Deploy revision number")
    status: str = Field(default="pending", description="Deploy status")
    message: str | None = Field(default=None, description="Status message or error detail")
    image_version: str | None = Field(default=None, description="Target image version")
    replicas: int | None = Field(default=None, description="Target replica count")
    config_snapshot: dict[str, Any] = Field(
        default_factory=dict,
        description="Configuration snapshot at deploy time",
    )
    triggered_by: str | None = Field(
        default=None,
        description="User or system that triggered the deploy",
    )
    started_at: datetime | None = Field(default=None, description="Deploy start timestamp")
    finished_at: datetime | None = Field(default=None, description="Deploy finish timestamp")
    created_at: datetime = Field(..., description="Creation timestamp")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "deploy_abc123",
                "instance_id": "inst_550e8400",
                "action": "update",
                "revision": 5,
                "status": "completed",
                "message": "Deploy completed successfully",
                "image_version": "1.3.0",
                "replicas": 3,
                "config_snapshot": {
                    "cpu_limit": "1000m",
                    "mem_limit": "1Gi",
                },
                "triggered_by": "user_123",
                "started_at": "2024-01-15T10:30:00Z",
                "finished_at": "2024-01-15T10:32:00Z",
                "created_at": "2024-01-15T10:30:00Z",
            }
        },
    )


class DeployListResponse(BaseModel):
    """Response model for deploy record list operations."""

    deploys: list[DeployResponse] = Field(..., description="List of deploy records")
    total: int = Field(..., description="Total number of deploy records")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Page size")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "deploys": [
                    {
                        "id": "deploy_abc123",
                        "instance_id": "inst_550e8400",
                        "action": "update",
                        "revision": 5,
                        "status": "completed",
                        "triggered_by": "user_123",
                        "created_at": "2024-01-15T10:30:00Z",
                    }
                ],
                "total": 1,
                "page": 1,
                "page_size": 20,
            }
        }
    )
