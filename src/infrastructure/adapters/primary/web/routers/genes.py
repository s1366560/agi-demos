"""Gene Marketplace API endpoints.

Provides REST API for managing genes (skill packages), genomes (gene collections),
gene installation on instances, ratings, and evolution events.
This is separate from CyberGenes (workspace-scoped) -- this is tenant-scoped marketplace.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.gene_schemas import (
    GeneCreate,
    GeneListResponse,
    GeneRatingCreate,
    GeneRatingResponse,
    GeneResponse,
    GeneReviewCreate,
    GeneReviewListResponse,
    GeneReviewResponse,
    GeneUpdate,
    GenomeCreate,
    GenomeListResponse,
    GenomeRatingCreate,
    GenomeRatingResponse,
    GenomeResponse,
    GenomeUpdate,
)
from src.configuration.di_container import DIContainer
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db


def get_container_with_db(request: Request, db: AsyncSession) -> DIContainer:
    """Get DI container with database session for the current request."""
    container: DIContainer = request.app.state.container
    return container.with_db(db)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/genes", tags=["Genes"])


# ---------------------------------------------------------------------------
# Inline request/response models (not in gene_schemas.py)
# ---------------------------------------------------------------------------


class InstallGeneRequest(BaseModel):
    """Request to install a gene on an instance."""

    gene_id: str = Field(..., description="Gene to install")
    config: dict[str, Any] | None = Field(None, description="Installation config")


class InstanceGeneResponse(BaseModel):
    """Response model for an installed gene record."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    instance_id: str
    gene_id: str
    genome_id: str | None = None
    status: str
    installed_version: str | None = None
    config_snapshot: dict[str, Any] = Field(default_factory=dict)
    usage_count: int = 0
    installed_at: str | None = None
    created_at: str


class InstanceGeneListResponse(BaseModel):
    """List of installed genes on an instance."""

    items: list[InstanceGeneResponse]
    total: int


class EvolutionEventResponse(BaseModel):
    """Response model for an evolution event."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    instance_id: str
    gene_id: str | None = None
    genome_id: str | None = None
    event_type: str
    gene_name: str = ""
    gene_slug: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class EvolutionEventListResponse(BaseModel):
    """List of evolution events."""

    items: list[EvolutionEventResponse]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Gene CRUD
# ---------------------------------------------------------------------------


@router.post(
    "/",
    response_model=GeneResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_gene(
    request: Request,
    data: GeneCreate,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> GeneResponse:
    """Create a new gene in the marketplace."""
    try:
        container = get_container_with_db(request, db)
        service = container.gene_service()
        gene = await service.create_gene(
            name=data.name,
            slug=data.slug,
            created_by=tenant_id,
            tenant_id=data.tenant_id or tenant_id,
            description=data.description,
            short_description=data.short_description,
            category=data.category,
            tags=data.tags,
            source=data.source,
            icon=data.icon,
            version=data.version,
            manifest=data.manifest,
            dependencies=data.dependencies,
            synergies=data.synergies,
            visibility=data.visibility,
        )
        await db.commit()
        return GeneResponse.model_validate(gene, from_attributes=True)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.get("/", response_model=GeneListResponse)
async def list_genes(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    category: str | None = Query(None, description="Filter by category"),
    is_published: bool | None = Query(None, description="Filter by published status"),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> GeneListResponse:
    """List genes with optional filtering."""
    container = get_container_with_db(request, db)
    service = container.gene_service()
    offset = (page - 1) * page_size
    genes = await service.list_genes(
        tenant_id=tenant_id,
        category=category,
        is_published=is_published,
        limit=page_size,
        offset=offset,
    )
    items = [GeneResponse.model_validate(g, from_attributes=True) for g in genes]
    return GeneListResponse(
        genes=items,
        total=len(items),
        page=page,
        page_size=page_size,
    )


@router.get("/{gene_id}", response_model=GeneResponse)
async def get_gene(
    request: Request,
    gene_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> GeneResponse:
    """Get a gene by ID."""
    container = get_container_with_db(request, db)
    service = container.gene_service()
    gene = await service.get_gene(gene_id)
    if not gene:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Gene {gene_id} not found",
        )
    return GeneResponse.model_validate(gene, from_attributes=True)


@router.put("/{gene_id}", response_model=GeneResponse)
async def update_gene(
    request: Request,
    gene_id: str,
    data: GeneUpdate,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> GeneResponse:
    """Update a gene."""
    try:
        container = get_container_with_db(request, db)
        service = container.gene_service()
        fields = data.model_dump(exclude_unset=True)
        gene = await service.update_gene(gene_id, **fields)
        await db.commit()
        return GeneResponse.model_validate(gene, from_attributes=True)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.delete(
    "/{gene_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_gene(
    request: Request,
    gene_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete (soft-delete) a gene."""
    try:
        container = get_container_with_db(request, db)
        service = container.gene_service()
        await service.delete_gene(gene_id)
        await db.commit()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.post("/{gene_id}/publish", response_model=GeneResponse)
async def publish_gene(
    request: Request,
    gene_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> GeneResponse:
    """Publish a gene to the marketplace."""
    try:
        container = get_container_with_db(request, db)
        service = container.gene_service()
        gene = await service.publish_gene(gene_id)
        await db.commit()
        return GeneResponse.model_validate(gene, from_attributes=True)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.post("/{gene_id}/unpublish", response_model=GeneResponse)
async def unpublish_gene(
    request: Request,
    gene_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> GeneResponse:
    """Remove a gene from the marketplace."""
    try:
        container = get_container_with_db(request, db)
        service = container.gene_service()
        gene = await service.unpublish_gene(gene_id)
        await db.commit()
        return GeneResponse.model_validate(gene, from_attributes=True)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


# ---------------------------------------------------------------------------
# Genome CRUD
# ---------------------------------------------------------------------------


@router.post(
    "/genomes",
    response_model=GenomeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_genome(
    request: Request,
    data: GenomeCreate,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> GenomeResponse:
    """Create a new genome (curated gene bundle)."""
    try:
        container = get_container_with_db(request, db)
        service = container.gene_service()
        genome = await service.create_genome(
            name=data.name,
            slug=data.slug,
            created_by=tenant_id,
            tenant_id=data.tenant_id or tenant_id,
            description=data.description,
            short_description=data.short_description,
            icon=data.icon,
            gene_slugs=data.gene_slugs,
            config_override=data.config_override,
            visibility=data.visibility,
        )
        await db.commit()
        return GenomeResponse.model_validate(genome, from_attributes=True)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.get("/genomes", response_model=GenomeListResponse)
async def list_genomes(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    is_published: bool | None = Query(None, description="Filter by published status"),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> GenomeListResponse:
    """List genomes with optional filtering."""
    container = get_container_with_db(request, db)
    service = container.gene_service()
    offset = (page - 1) * page_size
    genomes = await service.list_genomes(
        tenant_id=tenant_id,
        is_published=is_published,
        limit=page_size,
        offset=offset,
    )
    items = [GenomeResponse.model_validate(g, from_attributes=True) for g in genomes]
    return GenomeListResponse(
        genomes=items,
        total=len(items),
        page=page,
        page_size=page_size,
    )


@router.get("/genomes/{genome_id}", response_model=GenomeResponse)
async def get_genome(
    request: Request,
    genome_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> GenomeResponse:
    """Get a genome by ID."""
    container = get_container_with_db(request, db)
    service = container.gene_service()
    genome = await service.get_genome(genome_id)
    if not genome:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Genome {genome_id} not found",
        )
    return GenomeResponse.model_validate(genome, from_attributes=True)


@router.put(
    "/genomes/{genome_id}",
    response_model=GenomeResponse,
)
async def update_genome(
    request: Request,
    genome_id: str,
    data: GenomeUpdate,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> GenomeResponse:
    """Update a genome."""
    try:
        container = get_container_with_db(request, db)
        service = container.gene_service()
        fields = data.model_dump(exclude_unset=True)
        genome = await service.update_genome(genome_id, **fields)
        await db.commit()
        return GenomeResponse.model_validate(genome, from_attributes=True)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.delete(
    "/genomes/{genome_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_genome(
    request: Request,
    genome_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete (soft-delete) a genome."""
    try:
        container = get_container_with_db(request, db)
        service = container.gene_service()
        await service.delete_genome(genome_id)
        await db.commit()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.post(
    "/genomes/{genome_id}/publish",
    response_model=GenomeResponse,
)
async def publish_genome(
    request: Request,
    genome_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> GenomeResponse:
    """Publish a genome to the marketplace."""
    try:
        container = get_container_with_db(request, db)
        service = container.gene_service()
        genome = await service.publish_genome(genome_id)
        await db.commit()
        return GenomeResponse.model_validate(genome, from_attributes=True)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


# ---------------------------------------------------------------------------
# Gene Installation (instance-scoped)
# ---------------------------------------------------------------------------


@router.post(
    "/instances/{instance_id}/install",
    response_model=InstanceGeneResponse,
    status_code=status.HTTP_201_CREATED,
)
async def install_gene(
    request: Request,
    instance_id: str,
    data: InstallGeneRequest,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> InstanceGeneResponse:
    """Install a gene on an agent instance."""
    try:
        container = get_container_with_db(request, db)
        service = container.gene_service()
        instance_gene = await service.install_gene(
            instance_id=instance_id,
            gene_id=data.gene_id,
            config_snapshot=data.config,
        )
        await db.commit()
        return InstanceGeneResponse(
            id=instance_gene.id,
            instance_id=instance_gene.instance_id,
            gene_id=instance_gene.gene_id,
            genome_id=instance_gene.genome_id,
            status=instance_gene.status.value,
            installed_version=instance_gene.installed_version,
            config_snapshot=instance_gene.config_snapshot,
            usage_count=instance_gene.usage_count,
            installed_at=(
                instance_gene.installed_at.isoformat() if instance_gene.installed_at else None
            ),
            created_at=instance_gene.created_at.isoformat(),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.delete(
    "/instances/{instance_id}/genes/{instance_gene_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def uninstall_gene(
    request: Request,
    instance_id: str,
    instance_gene_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Uninstall a gene from an agent instance."""
    try:
        container = get_container_with_db(request, db)
        service = container.gene_service()
        await service.uninstall_gene(instance_gene_id)
        await db.commit()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.get(
    "/instances/{instance_id}/genes",
    response_model=InstanceGeneListResponse,
)
async def list_instance_genes(
    request: Request,
    instance_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> InstanceGeneListResponse:
    """List all genes installed on an agent instance."""
    container = get_container_with_db(request, db)
    service = container.gene_service()
    instance_genes = await service.list_instance_genes(instance_id)
    items = [
        InstanceGeneResponse(
            id=ig.id,
            instance_id=ig.instance_id,
            gene_id=ig.gene_id,
            genome_id=ig.genome_id,
            status=ig.status.value,
            installed_version=ig.installed_version,
            config_snapshot=ig.config_snapshot,
            usage_count=ig.usage_count,
            installed_at=(ig.installed_at.isoformat() if ig.installed_at else None),
            created_at=ig.created_at.isoformat(),
        )
        for ig in instance_genes
    ]
    return InstanceGeneListResponse(items=items, total=len(items))


@router.get(
    "/instances/{instance_id}/genes/{instance_gene_id}",
    response_model=InstanceGeneResponse,
)
async def get_instance_gene(
    request: Request,
    instance_id: str,
    instance_gene_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> InstanceGeneResponse:
    """Get a specific installed gene record."""
    container = get_container_with_db(request, db)
    service = container.gene_service()
    ig = await service.get_instance_gene(instance_gene_id)
    if not ig:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"InstanceGene {instance_gene_id} not found",
        )
    return InstanceGeneResponse(
        id=ig.id,
        instance_id=ig.instance_id,
        gene_id=ig.gene_id,
        genome_id=ig.genome_id,
        status=ig.status.value,
        installed_version=ig.installed_version,
        config_snapshot=ig.config_snapshot,
        usage_count=ig.usage_count,
        installed_at=(ig.installed_at.isoformat() if ig.installed_at else None),
        created_at=ig.created_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Ratings
# ---------------------------------------------------------------------------


@router.post(
    "/{gene_id}/ratings",
    response_model=GeneRatingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def rate_gene(
    request: Request,
    gene_id: str,
    data: GeneRatingCreate,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> GeneRatingResponse:
    """Rate a gene (creates or updates the user's rating)."""
    try:
        container = get_container_with_db(request, db)
        service = container.gene_service()
        rating = await service.rate_gene(
            gene_id=gene_id,
            user_id=tenant_id,
            rating=data.rating,
            comment=data.comment,
        )
        await db.commit()
        return GeneRatingResponse.model_validate(rating, from_attributes=True)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.get(
    "/{gene_id}/ratings",
    response_model=list[GeneRatingResponse],
)
async def list_gene_ratings(
    request: Request,
    gene_id: str,
    limit: int = Query(50, ge=1, le=200, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset"),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[GeneRatingResponse]:
    """List ratings for a gene."""
    container = get_container_with_db(request, db)
    service = container.gene_service()
    ratings = await service.list_gene_ratings(
        gene_id=gene_id,
        limit=limit,
        offset=offset,
    )
    return [GeneRatingResponse.model_validate(r, from_attributes=True) for r in ratings]


@router.post(
    "/genomes/{genome_id}/ratings",
    response_model=GenomeRatingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def rate_genome(
    request: Request,
    genome_id: str,
    data: GenomeRatingCreate,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> GenomeRatingResponse:
    """Rate a genome (creates or updates the user's rating)."""
    try:
        container = get_container_with_db(request, db)
        service = container.gene_service()
        rating = await service.rate_genome(
            genome_id=genome_id,
            user_id=tenant_id,
            rating=data.rating,
            comment=data.comment,
        )
        await db.commit()
        return GenomeRatingResponse.model_validate(rating, from_attributes=True)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


# ---------------------------------------------------------------------------
# Evolution Events
# ---------------------------------------------------------------------------


@router.get(
    "/evolution",
    response_model=EvolutionEventListResponse,
)
async def list_evolution_events(
    request: Request,
    instance_id: str = Query(..., description="Agent instance ID to query"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> EvolutionEventListResponse:
    """List evolution events for an agent instance."""
    container = get_container_with_db(request, db)
    service = container.gene_service()
    offset = (page - 1) * page_size
    events = await service.list_evolution_events(
        instance_id=instance_id,
        limit=page_size,
        offset=offset,
    )
    items = [
        EvolutionEventResponse(
            id=ev.id,
            instance_id=ev.instance_id,
            gene_id=ev.gene_id,
            genome_id=ev.genome_id,
            event_type=ev.event_type.value,
            gene_name=ev.gene_name,
            gene_slug=ev.gene_slug,
            details=ev.details,
            created_at=ev.created_at.isoformat(),
        )
        for ev in events
    ]
    return EvolutionEventListResponse(
        items=items,
        total=len(items),
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{gene_id}/reviews",
    response_model=GeneReviewListResponse,
    summary="List gene reviews",
)
async def list_gene_reviews(
    request: Request,
    gene_id: str,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=100, description="Items per page"),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> GeneReviewListResponse:
    container = get_container_with_db(request, db)
    service = container.gene_service()
    reviews, total = await service.list_gene_reviews(
        gene_id=gene_id,
        page=page,
        page_size=page_size,
        tenant_id=tenant_id,
    )
    return GeneReviewListResponse(
        items=[GeneReviewResponse.model_validate(r, from_attributes=True) for r in reviews],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/{gene_id}/reviews",
    response_model=GeneReviewResponse,
    summary="Create gene review",
)
async def create_gene_review(
    request: Request,
    gene_id: str,
    data: GeneReviewCreate,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> GeneReviewResponse:
    try:
        container = get_container_with_db(request, db)
        service = container.gene_service()
        review = await service.create_gene_review(
            gene_id=gene_id,
            user_id=tenant_id,
            rating=data.rating,
            content=data.content,
            tenant_id=tenant_id,
        )
        await db.commit()
        return GeneReviewResponse.model_validate(review, from_attributes=True)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.delete(
    "/{gene_id}/reviews/{review_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete gene review",
)
async def delete_gene_review(
    request: Request,
    gene_id: str,
    review_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        container = get_container_with_db(request, db)
        service = container.gene_service()
        await service.delete_gene_review(
            review_id=review_id,
            user_id=tenant_id,
            tenant_id=tenant_id,
        )
        await db.commit()
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from e
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
