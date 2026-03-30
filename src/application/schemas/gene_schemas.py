"""Gene, Genome, GeneRating, and GenomeRating data models."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GeneCreate(BaseModel):
    """Request model for creating a gene."""

    name: str = Field(..., description="Gene name", min_length=1, max_length=255)
    slug: str = Field(
        ...,
        description="URL-friendly gene identifier",
        min_length=1,
        max_length=255,
    )
    tenant_id: str | None = Field(default=None, description="Tenant ID (None for global genes)")
    description: str | None = Field(default=None, description="Gene description", max_length=2000)
    short_description: str | None = Field(
        default=None, description="Short description", max_length=500
    )
    category: str | None = Field(default=None, description="Gene category", max_length=100)
    tags: list[str] = Field(default_factory=list, description="Gene tags")
    source: str = Field(default="official", description="Gene source", max_length=100)
    source_ref: str | None = Field(default=None, description="Source reference URL or ID")
    icon: str | None = Field(default=None, description="Icon URL or identifier")
    version: str = Field(default="1.0.0", description="Gene version", max_length=50)
    manifest: dict[str, Any] = Field(
        default_factory=dict, description="Gene manifest configuration"
    )
    dependencies: list[str] = Field(default_factory=list, description="Gene dependency slugs")
    synergies: list[str] = Field(
        default_factory=list,
        description="Gene synergy slugs for complementary effects",
    )
    parent_gene_id: str | None = Field(default=None, description="Parent gene ID for inheritance")
    visibility: str = Field(
        default="public",
        description="Visibility level",
        max_length=50,
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Code Review Gene",
                "slug": "code-review",
                "description": "Enables systematic code review",
                "short_description": "Code review capabilities",
                "category": "development",
                "tags": ["code", "review", "quality"],
                "source": "official",
                "version": "1.0.0",
                "manifest": {"tools": ["lint", "analyze"]},
                "dependencies": [],
                "visibility": "public",
            }
        }
    )


class GeneUpdate(BaseModel):
    """Request model for updating a gene."""

    name: str | None = Field(
        default=None,
        description="Gene name",
        min_length=1,
        max_length=255,
    )
    slug: str | None = Field(
        default=None,
        description="URL-friendly gene identifier",
        min_length=1,
        max_length=255,
    )
    description: str | None = Field(default=None, description="Gene description", max_length=2000)
    short_description: str | None = Field(
        default=None, description="Short description", max_length=500
    )
    category: str | None = Field(default=None, description="Gene category", max_length=100)
    tags: list[str] | None = Field(default=None, description="Gene tags")
    source: str | None = Field(default=None, description="Gene source", max_length=100)
    source_ref: str | None = Field(default=None, description="Source reference URL or ID")
    icon: str | None = Field(default=None, description="Icon URL or identifier")
    version: str | None = Field(default=None, description="Gene version", max_length=50)
    manifest: dict[str, Any] | None = Field(default=None, description="Gene manifest configuration")
    dependencies: list[str] | None = Field(default=None, description="Gene dependency slugs")
    synergies: list[str] | None = Field(
        default=None,
        description="Gene synergy slugs for complementary effects",
    )
    parent_gene_id: str | None = Field(default=None, description="Parent gene ID for inheritance")
    visibility: str | None = Field(default=None, description="Visibility level", max_length=50)


class GeneResponse(BaseModel):
    """Response model for gene operations."""

    id: str = Field(..., description="Gene unique identifier")
    name: str = Field(..., description="Gene name")
    slug: str = Field(..., description="URL-friendly gene identifier")
    tenant_id: str | None = Field(default=None, description="Tenant ID")
    description: str | None = Field(default=None, description="Gene description")
    short_description: str | None = Field(default=None, description="Short description")
    category: str | None = Field(default=None, description="Gene category")
    tags: list[str] = Field(default_factory=list, description="Gene tags")
    source: str = Field(default="official", description="Gene source")
    source_ref: str | None = Field(default=None, description="Source reference URL or ID")
    icon: str | None = Field(default=None, description="Icon URL or identifier")
    version: str = Field(default="1.0.0", description="Gene version")
    manifest: dict[str, Any] = Field(
        default_factory=dict, description="Gene manifest configuration"
    )
    dependencies: list[str] = Field(default_factory=list, description="Gene dependency slugs")
    synergies: list[str] = Field(default_factory=list, description="Gene synergy slugs")
    parent_gene_id: str | None = Field(default=None, description="Parent gene ID")
    visibility: str = Field(default="public", description="Visibility level")
    install_count: int = Field(default=0, description="Number of installations")
    avg_rating: float | None = Field(default=None, description="Average user rating")
    effectiveness_score: float | None = Field(default=None, description="Effectiveness score")
    is_featured: bool = Field(default=False, description="Whether gene is featured")
    review_status: str | None = Field(default=None, description="Review status")
    is_published: bool = Field(default=False, description="Whether gene is published")
    created_by: str | None = Field(default=None, description="User ID who created the gene")
    created_by_instance_id: str | None = Field(
        default=None,
        description="Instance ID that created the gene",
    )
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime | None = Field(default=None, description="Last update timestamp")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "gene_550e8400",
                "name": "Code Review Gene",
                "slug": "code-review",
                "description": "Enables systematic code review",
                "short_description": "Code review capabilities",
                "category": "development",
                "tags": ["code", "review", "quality"],
                "source": "official",
                "version": "1.0.0",
                "manifest": {"tools": ["lint", "analyze"]},
                "visibility": "public",
                "install_count": 42,
                "avg_rating": 4.5,
                "is_featured": True,
                "is_published": True,
                "created_by": "user_123",
                "created_at": "2024-01-15T10:30:00Z",
                "updated_at": "2024-01-15T12:45:00Z",
            }
        },
    )


class GeneListResponse(BaseModel):
    """Response model for gene list operations."""

    genes: list[GeneResponse] = Field(..., description="List of genes")
    total: int = Field(..., description="Total number of genes")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Page size")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "genes": [
                    {
                        "id": "gene_550e8400",
                        "name": "Code Review Gene",
                        "slug": "code-review",
                        "category": "development",
                        "visibility": "public",
                        "install_count": 42,
                        "is_published": True,
                        "created_at": "2024-01-15T10:30:00Z",
                    }
                ],
                "total": 1,
                "page": 1,
                "page_size": 20,
            }
        }
    )


class GenomeCreate(BaseModel):
    """Request model for creating a genome."""

    name: str = Field(
        ...,
        description="Genome name",
        min_length=1,
        max_length=255,
    )
    slug: str = Field(
        ...,
        description="URL-friendly genome identifier",
        min_length=1,
        max_length=255,
    )
    tenant_id: str | None = Field(
        default=None,
        description="Tenant ID (None for global genomes)",
    )
    description: str | None = Field(
        default=None,
        description="Genome description",
        max_length=2000,
    )
    short_description: str | None = Field(
        default=None,
        description="Short description",
        max_length=500,
    )
    icon: str | None = Field(default=None, description="Icon URL or identifier")
    gene_slugs: list[str] = Field(
        default_factory=list,
        description="List of gene slugs in this genome",
    )
    config_override: dict[str, Any] = Field(
        default_factory=dict,
        description="Per-gene configuration overrides",
    )
    visibility: str = Field(
        default="public",
        description="Visibility level",
        max_length=50,
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Full Stack Developer Genome",
                "slug": "full-stack-developer",
                "description": "Complete gene set for full stack dev",
                "short_description": "Full stack capabilities",
                "gene_slugs": ["code-review", "testing", "deployment"],
                "config_override": {},
                "visibility": "public",
            }
        }
    )


class GenomeUpdate(BaseModel):
    """Request model for updating a genome."""

    name: str | None = Field(
        default=None,
        description="Genome name",
        min_length=1,
        max_length=255,
    )
    slug: str | None = Field(
        default=None,
        description="URL-friendly genome identifier",
        min_length=1,
        max_length=255,
    )
    description: str | None = Field(
        default=None,
        description="Genome description",
        max_length=2000,
    )
    short_description: str | None = Field(
        default=None,
        description="Short description",
        max_length=500,
    )
    icon: str | None = Field(default=None, description="Icon URL or identifier")
    gene_slugs: list[str] | None = Field(
        default=None,
        description="List of gene slugs in this genome",
    )
    config_override: dict[str, Any] | None = Field(
        default=None,
        description="Per-gene configuration overrides",
    )
    visibility: str | None = Field(
        default=None,
        description="Visibility level",
        max_length=50,
    )


class GenomeResponse(BaseModel):
    """Response model for genome operations."""

    id: str = Field(..., description="Genome unique identifier")
    name: str = Field(..., description="Genome name")
    slug: str = Field(..., description="URL-friendly genome identifier")
    tenant_id: str | None = Field(default=None, description="Tenant ID")
    description: str | None = Field(default=None, description="Genome description")
    short_description: str | None = Field(default=None, description="Short description")
    icon: str | None = Field(default=None, description="Icon URL or identifier")
    gene_slugs: list[str] = Field(
        default_factory=list,
        description="List of gene slugs in this genome",
    )
    config_override: dict[str, Any] = Field(
        default_factory=dict,
        description="Per-gene configuration overrides",
    )
    visibility: str = Field(default="public", description="Visibility level")
    install_count: int = Field(default=0, description="Number of installations")
    avg_rating: float | None = Field(default=None, description="Average user rating")
    is_featured: bool = Field(default=False, description="Whether genome is featured")
    is_published: bool = Field(default=False, description="Whether genome is published")
    created_by: str | None = Field(default=None, description="User ID who created the genome")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime | None = Field(default=None, description="Last update timestamp")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "genome_550e8400",
                "name": "Full Stack Developer Genome",
                "slug": "full-stack-developer",
                "description": "Complete gene set for full stack dev",
                "gene_slugs": ["code-review", "testing", "deployment"],
                "visibility": "public",
                "install_count": 15,
                "avg_rating": 4.7,
                "is_featured": False,
                "is_published": True,
                "created_by": "user_123",
                "created_at": "2024-01-15T10:30:00Z",
                "updated_at": "2024-01-15T12:45:00Z",
            }
        },
    )


class GenomeListResponse(BaseModel):
    """Response model for genome list operations."""

    genomes: list[GenomeResponse] = Field(..., description="List of genomes")
    total: int = Field(..., description="Total number of genomes")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Page size")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "genomes": [
                    {
                        "id": "genome_550e8400",
                        "name": "Full Stack Developer Genome",
                        "slug": "full-stack-developer",
                        "visibility": "public",
                        "install_count": 15,
                        "is_published": True,
                        "created_at": "2024-01-15T10:30:00Z",
                    }
                ],
                "total": 1,
                "page": 1,
                "page_size": 20,
            }
        }
    )


class GeneRatingCreate(BaseModel):
    """Request model for rating a gene."""

    gene_id: str = Field(..., description="Gene ID to rate")
    rating: int = Field(..., ge=1, le=5, description="Rating value (1-5)")
    comment: str | None = Field(
        default=None,
        description="Rating comment",
        max_length=1000,
    )


class GeneRatingResponse(BaseModel):
    """Response model for gene rating operations."""

    id: str = Field(..., description="Rating unique identifier")
    gene_id: str = Field(..., description="Gene ID")
    user_id: str = Field(..., description="User ID who rated")
    rating: int = Field(..., description="Rating value (1-5)")
    comment: str | None = Field(default=None, description="Rating comment")
    created_at: datetime = Field(..., description="Creation timestamp")

    model_config = ConfigDict(from_attributes=True)


class GenomeRatingCreate(BaseModel):
    """Request model for rating a genome."""

    genome_id: str = Field(..., description="Genome ID to rate")
    rating: int = Field(..., ge=1, le=5, description="Rating value (1-5)")
    comment: str | None = Field(
        default=None,
        description="Rating comment",
        max_length=1000,
    )


class GenomeRatingResponse(BaseModel):
    """Response model for genome rating operations."""

    id: str = Field(..., description="Rating unique identifier")
    genome_id: str = Field(..., description="Genome ID")
    user_id: str = Field(..., description="User ID who rated")
    rating: int = Field(..., description="Rating value (1-5)")
    comment: str | None = Field(default=None, description="Rating comment")
    created_at: datetime = Field(..., description="Creation timestamp")

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Gene Reviews
# ---------------------------------------------------------------------------


class GeneReviewCreate(BaseModel):
    rating: int = Field(..., ge=1, le=5, description="Rating value (1-5)")
    content: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Review text content",
    )


class GeneReviewResponse(BaseModel):
    id: str
    gene_id: str
    user_id: str
    rating: int
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GeneReviewListResponse(BaseModel):
    items: list[GeneReviewResponse]
    total: int
    page: int
    page_size: int
