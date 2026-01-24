"""Tenant data models."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class TenantCreate(BaseModel):
    """Request model for creating a tenant."""

    name: str = Field(..., description="Tenant name", min_length=1, max_length=255)
    description: Optional[str] = Field(
        default=None, description="Tenant description", max_length=1000
    )
    plan: str = Field(default="free", description="Tenant plan")
    max_projects: int = Field(default=3, ge=1, le=100, description="Maximum number of projects")
    max_users: int = Field(default=10, ge=1, le=1000, description="Maximum number of users")
    max_storage: int = Field(default=1073741824, ge=0, description="Maximum storage in bytes")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Acme Corporation",
                "description": "Enterprise knowledge management platform",
                "plan": "premium",
                "max_projects": 10,
                "max_users": 50,
                "max_storage": 5368709120,  # 5GB
            }
        }
    )


class TenantUpdate(BaseModel):
    """Request model for updating a tenant."""

    name: Optional[str] = Field(
        default=None, description="Tenant name", min_length=1, max_length=255
    )
    description: Optional[str] = Field(
        default=None, description="Tenant description", max_length=1000
    )
    plan: Optional[str] = Field(default=None, description="Tenant plan")
    max_projects: Optional[int] = Field(
        default=None, ge=1, le=100, description="Maximum number of projects"
    )
    max_users: Optional[int] = Field(
        default=None, ge=1, le=1000, description="Maximum number of users"
    )
    max_storage: Optional[int] = Field(default=None, ge=0, description="Maximum storage in bytes")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Acme Corporation Updated",
                "description": "Updated enterprise platform",
                "plan": "enterprise",
                "max_projects": 20,
                "max_users": 100,
                "max_storage": 10737418240,  # 10GB
            }
        }
    )


class TenantResponse(BaseModel):
    """Response model for tenant operations."""

    id: str = Field(..., description="Tenant unique identifier")
    name: str = Field(..., description="Tenant name")
    description: Optional[str] = Field(default=None, description="Tenant description")
    owner_id: str = Field(..., description="Owner user ID")
    plan: str = Field(default="free", description="Tenant plan")
    max_projects: int = Field(default=3, description="Maximum number of projects")
    max_users: int = Field(default=10, description="Maximum number of users")
    max_storage: int = Field(default=1073741824, description="Maximum storage in bytes")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: Optional[datetime] = Field(default=None, description="Last update timestamp")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "name": "Acme Corporation",
                "description": "Enterprise knowledge management platform",
                "owner_id": "user_123",
                "plan": "premium",
                "max_projects": 10,
                "max_users": 50,
                "max_storage": 5368709120,
                "created_at": "2024-01-15T10:30:00Z",
                "updated_at": "2024-01-15T12:45:00Z",
            }
        },
    )


class TenantListResponse(BaseModel):
    """Response model for tenant list operations."""

    tenants: list[TenantResponse] = Field(..., description="List of tenants")
    total: int = Field(..., description="Total number of tenants")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Page size")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "tenants": [
                    {
                        "id": "550e8400-e29b-41d4-a716-446655440000",
                        "name": "Acme Corporation",
                        "description": "Enterprise platform",
                        "owner_id": "user_123",
                        "plan": "premium",
                        "max_projects": 10,
                        "max_users": 50,
                        "max_storage": 5368709120,
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
