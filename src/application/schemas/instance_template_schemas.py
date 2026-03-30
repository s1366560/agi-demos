"""Instance template and template item data models."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class InstanceTemplateCreate(BaseModel):
    """Request model for creating an instance template."""

    name: str = Field(
        ...,
        description="Template name",
        min_length=1,
        max_length=255,
    )
    slug: str = Field(
        ...,
        description="URL-friendly template identifier",
        min_length=1,
        max_length=255,
    )
    tenant_id: str | None = Field(
        default=None,
        description="Tenant ID (None for global templates)",
    )
    description: str | None = Field(
        default=None,
        description="Template description",
        max_length=2000,
    )
    icon: str | None = Field(default=None, description="Icon URL or identifier")
    image_version: str | None = Field(default=None, description="Default image version")
    default_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Default instance configuration",
    )
    is_published: bool = Field(
        default=False,
        description="Whether the template is published",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Starter Template",
                "slug": "starter-template",
                "description": "Basic starter template for new instances",
                "image_version": "1.0.0",
                "default_config": {
                    "replicas": 1,
                    "cpu_limit": "500m",
                    "mem_limit": "512Mi",
                },
                "is_published": True,
            }
        }
    )


class InstanceTemplateUpdate(BaseModel):
    """Request model for updating an instance template."""

    name: str | None = Field(
        default=None,
        description="Template name",
        min_length=1,
        max_length=255,
    )
    slug: str | None = Field(
        default=None,
        description="URL-friendly template identifier",
        min_length=1,
        max_length=255,
    )
    description: str | None = Field(
        default=None,
        description="Template description",
        max_length=2000,
    )
    icon: str | None = Field(default=None, description="Icon URL or identifier")
    image_version: str | None = Field(default=None, description="Default image version")
    default_config: dict[str, Any] | None = Field(
        default=None,
        description="Default instance configuration",
    )
    is_published: bool | None = Field(
        default=None,
        description="Whether the template is published",
    )


class InstanceTemplateResponse(BaseModel):
    """Response model for instance template operations."""

    id: str = Field(..., description="Template unique identifier")
    name: str = Field(..., description="Template name")
    slug: str = Field(..., description="URL-friendly template identifier")
    tenant_id: str | None = Field(default=None, description="Tenant ID")
    description: str | None = Field(default=None, description="Template description")
    icon: str | None = Field(default=None, description="Icon URL or identifier")
    image_version: str | None = Field(default=None, description="Default image version")
    default_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Default instance configuration",
    )
    is_published: bool = Field(
        default=False,
        description="Whether the template is published",
    )
    is_featured: bool = Field(
        default=False,
        description="Whether the template is featured",
    )
    install_count: int = Field(default=0, description="Number of installations")
    created_by: str | None = Field(
        default=None,
        description="User ID who created the template",
    )
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime | None = Field(default=None, description="Last update timestamp")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "tmpl_550e8400",
                "name": "Starter Template",
                "slug": "starter-template",
                "description": "Basic starter template",
                "image_version": "1.0.0",
                "default_config": {
                    "replicas": 1,
                    "cpu_limit": "500m",
                    "mem_limit": "512Mi",
                },
                "is_published": True,
                "is_featured": False,
                "install_count": 28,
                "created_by": "user_123",
                "created_at": "2024-01-15T10:30:00Z",
                "updated_at": "2024-01-15T12:45:00Z",
            }
        },
    )


class InstanceTemplateListResponse(BaseModel):
    """Response model for instance template list operations."""

    templates: list[InstanceTemplateResponse] = Field(..., description="List of instance templates")
    total: int = Field(..., description="Total number of templates")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Page size")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "templates": [
                    {
                        "id": "tmpl_550e8400",
                        "name": "Starter Template",
                        "slug": "starter-template",
                        "is_published": True,
                        "install_count": 28,
                        "created_at": "2024-01-15T10:30:00Z",
                    }
                ],
                "total": 1,
                "page": 1,
                "page_size": 20,
            }
        }
    )


class TemplateItemCreate(BaseModel):
    """Request model for adding an item to a template."""

    template_id: str = Field(..., description="Template ID")
    item_type: str = Field(
        default="gene",
        description="Item type (gene or genome)",
        max_length=50,
    )
    item_slug: str = Field(
        ...,
        description="Slug of the gene or genome",
        max_length=255,
    )
    display_order: int = Field(default=0, description="Display order within the template")


class TemplateItemResponse(BaseModel):
    """Response model for template item operations."""

    id: str = Field(..., description="Template item unique identifier")
    template_id: str = Field(..., description="Template ID")
    item_type: str = Field(..., description="Item type")
    item_slug: str = Field(..., description="Slug of the gene or genome")
    display_order: int = Field(default=0, description="Display order within the template")
    created_at: datetime = Field(..., description="Creation timestamp")

    model_config = ConfigDict(from_attributes=True)
