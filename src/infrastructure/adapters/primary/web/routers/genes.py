"""Gene Marketplace API endpoints.

Provides REST API for managing genes (skill packages), genomes (gene collections),
gene installation on instances, ratings, and evolution events.
This is separate from CyberGenes (workspace-scoped) -- this is tenant-scoped marketplace.
"""

import logging
from collections.abc import Callable
from typing import Any, Protocol, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
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
from src.domain.model.gene.enums import ContentVisibility, EvolutionEventType
from src.domain.model.gene.instance_gene import EvolutionEvent
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_current_user_tenant,
)
from src.infrastructure.adapters.primary.web.routers.agent.access import require_tenant_access
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import GeneMarketModel, User as DBUser
from src.infrastructure.i18n import gettext as _


def get_container_with_db(request: Request, db: AsyncSession) -> DIContainer:
    """Get DI container with database session for the current request."""
    container: DIContainer = request.app.state.container
    return container.with_db(db)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/genes", tags=["Genes"])


# ---------------------------------------------------------------------------
# Local typing helpers
# ---------------------------------------------------------------------------


class _TenantScopedEntity(Protocol):
    tenant_id: str | None


class _InstanceScopedEntity(Protocol):
    id: str
    instance_id: str
    gene_id: str
    genome_id: str | None
    status: Any
    installed_version: str | None
    config_snapshot: dict[str, Any]
    usage_count: int
    installed_at: Any
    created_at: Any
    deleted_at: Any


class _GeneLookupService(Protocol):
    async def get_gene(self, gene_id: str) -> _TenantScopedEntity | None: ...


class _GenomeLookupService(Protocol):
    async def get_genome(self, genome_id: str) -> _TenantScopedEntity | None: ...


class _InstanceGeneLookupService(Protocol):
    async def get_instance_gene(self, instance_gene_id: str) -> _InstanceScopedEntity | None: ...


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
    gene_name: str | None = None
    gene_description: str | None = None
    gene_category: str | None = None


class InstanceGeneListResponse(BaseModel):
    """List of installed genes on an instance."""

    items: list[InstanceGeneResponse]
    total: int
    active_total: int
    usage_total: int
    limit: int
    offset: int
    has_more: bool


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
    from_version: str | None = None
    to_version: str | None = None
    trigger: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    status: str = "completed"
    created_at: str


class EvolutionEventListResponse(BaseModel):
    """List of evolution events."""

    items: list[EvolutionEventResponse]
    events: list[EvolutionEventResponse]
    total: int
    page: int
    page_size: int


class EvolutionEventCreateRequest(BaseModel):
    """Request model for manually recording an evolution event."""

    instance_id: str
    gene_id: str | None = None
    genome_id: str | None = None
    event_type: EvolutionEventType
    from_version: str | None = None
    to_version: str | None = None
    trigger: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    status: str = "completed"
    gene_name: str = ""
    gene_slug: str | None = None


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _invalid_gene_request_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=_("Invalid gene request"),
    )


def _split_slug_query(value: str | None) -> list[str] | None:
    if value is None:
        return None
    slugs = [slug.strip() for slug in value.split(",") if slug.strip()]
    return slugs or None


def _gene_not_found_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=_("Gene not found"),
    )


def _genome_not_found_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=_("Genome not found"),
    )


def _instance_gene_not_found_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=_("Instance gene not found"),
    )


def _instance_not_found_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=_("Instance not found"),
    )


def _invalid_evolution_event_request_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=_("Invalid evolution event request"),
    )


def _evolution_event_not_found_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=_("Evolution event not found"),
    )


def _gene_review_not_found_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=_("Gene review not found"),
    )


def _gene_review_forbidden_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=_("Access denied"),
    )


def _access_denied_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=_("Access denied"),
    )


async def _get_selected_gene_tenant_id(
    selected_tenant_id: str | None = Query(
        None,
        alias="tenant_id",
        min_length=1,
        description="Explicit tenant scope for multi-tenant callers.",
    ),
    fallback_tenant_id: str = Depends(get_current_user_tenant),
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> str:
    return await _resolve_selected_gene_tenant_id(
        selected_tenant_id=selected_tenant_id,
        fallback_tenant_id=fallback_tenant_id,
        current_user=current_user,
        db=db,
        require_admin=False,
    )


async def _get_selected_gene_admin_tenant_id(
    selected_tenant_id: str | None = Query(
        None,
        alias="tenant_id",
        min_length=1,
        description="Explicit tenant scope for multi-tenant callers.",
    ),
    fallback_tenant_id: str = Depends(get_current_user_tenant),
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> str:
    return await _resolve_selected_gene_tenant_id(
        selected_tenant_id=selected_tenant_id,
        fallback_tenant_id=fallback_tenant_id,
        current_user=current_user,
        db=db,
        require_admin=True,
    )


async def _resolve_selected_gene_tenant_id(
    *,
    selected_tenant_id: str | None,
    fallback_tenant_id: str,
    current_user: DBUser,
    db: AsyncSession,
    require_admin: bool,
) -> str:
    tenant_id = selected_tenant_id or fallback_tenant_id
    if require_admin or selected_tenant_id is not None:
        await require_tenant_access(
            db,
            cast(Any, current_user),
            tenant_id,
            require_admin=require_admin,
        )
    return tenant_id


def _ensure_request_tenant_matches(payload_tenant_id: str | None, tenant_id: str) -> None:
    if payload_tenant_id is not None and payload_tenant_id != tenant_id:
        raise _access_denied_error()


def _evolution_event_response(event: EvolutionEvent) -> EvolutionEventResponse:
    details = event.details or {}
    payload = details.get("payload")
    if not isinstance(payload, dict):
        payload = details
    return EvolutionEventResponse(
        id=event.id,
        instance_id=event.instance_id,
        gene_id=event.gene_id,
        genome_id=event.genome_id,
        event_type=event.event_type.value,
        gene_name=event.gene_name,
        gene_slug=event.gene_slug,
        details=details,
        from_version=_optional_str(details.get("from_version")),
        to_version=_optional_str(details.get("to_version")),
        trigger=_optional_str(details.get("trigger")),
        payload=payload,
        status=_optional_str(details.get("status")) or "completed",
        created_at=event.created_at.isoformat(),
    )


_GeneMetadata = dict[str, str | None]


async def _get_gene_metadata_by_id(
    db: AsyncSession,
    gene_ids: set[str],
    *,
    tenant_id: str,
) -> dict[str, _GeneMetadata]:
    """Return display metadata for installed genes without per-row lookups."""
    if not gene_ids:
        return {}

    result = await db.execute(
        refresh_select_statement(
            select(
                GeneMarketModel.id,
                GeneMarketModel.name,
                GeneMarketModel.description,
                GeneMarketModel.category,
            )
            .where(GeneMarketModel.id.in_(gene_ids))
            .where(
                or_(
                    GeneMarketModel.tenant_id == tenant_id,
                    GeneMarketModel.tenant_id.is_(None),
                )
            )
            .where(GeneMarketModel.deleted_at.is_(None))
        )
    )
    return {
        gene_id: {
            "name": name,
            "description": description,
            "category": category,
        }
        for gene_id, name, description, category in result.all()
    }


def _instance_gene_response(
    instance_gene: _InstanceScopedEntity,
    *,
    gene_metadata: _GeneMetadata | None = None,
) -> InstanceGeneResponse:
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
        gene_name=gene_metadata.get("name") if gene_metadata else None,
        gene_description=gene_metadata.get("description") if gene_metadata else None,
        gene_category=gene_metadata.get("category") if gene_metadata else None,
    )


async def _ensure_instance_tenant_access(
    container: DIContainer,
    *,
    instance_id: str,
    tenant_id: str,
    not_found_error: Callable[[], HTTPException] = _instance_not_found_error,
) -> None:
    instance = await container.instance_service().get_instance(instance_id)
    if (
        instance is None
        or instance.tenant_id != tenant_id
        or getattr(instance, "deleted_at", None) is not None
    ):
        raise not_found_error()


async def _ensure_gene_tenant_access(
    service: _GeneLookupService,
    *,
    gene_id: str,
    tenant_id: str,
    allow_global: bool = False,
) -> _TenantScopedEntity:
    gene = await service.get_gene(gene_id)
    if gene is None or not _tenant_entity_matches(gene, tenant_id, allow_global=allow_global):
        raise _gene_not_found_error()
    return gene


async def _ensure_genome_tenant_access(
    service: _GenomeLookupService,
    *,
    genome_id: str,
    tenant_id: str,
    allow_global: bool = False,
) -> _TenantScopedEntity:
    genome = await service.get_genome(genome_id)
    if genome is None or not _tenant_entity_matches(genome, tenant_id, allow_global=allow_global):
        raise _genome_not_found_error()
    return genome


def _tenant_entity_matches(
    entity: _TenantScopedEntity,
    tenant_id: str,
    *,
    allow_global: bool,
) -> bool:
    if entity.tenant_id == tenant_id:
        return True
    if not allow_global or entity.tenant_id is not None:
        return False
    visibility = getattr(entity, "visibility", None)
    visibility_value = getattr(visibility, "value", visibility)
    return (
        getattr(entity, "is_published", False) is True
        and visibility_value == ContentVisibility.public.value
    )


async def _ensure_instance_gene_tenant_access(
    container: DIContainer,
    service: _InstanceGeneLookupService,
    *,
    instance_id: str,
    instance_gene_id: str,
    tenant_id: str,
) -> _InstanceScopedEntity:
    await _ensure_instance_tenant_access(
        container,
        instance_id=instance_id,
        tenant_id=tenant_id,
        not_found_error=_instance_gene_not_found_error,
    )
    instance_gene = await service.get_instance_gene(instance_gene_id)
    if (
        instance_gene is None
        or instance_gene.instance_id != instance_id
        or getattr(instance_gene, "deleted_at", None) is not None
    ):
        raise _instance_gene_not_found_error()
    return instance_gene


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
    tenant_id: str = Depends(_get_selected_gene_admin_tenant_id),
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GeneResponse:
    """Create a new gene in the marketplace."""
    try:
        _ensure_request_tenant_matches(data.tenant_id, tenant_id)
        container = get_container_with_db(request, db)
        service = container.gene_service()
        gene = await service.create_gene(
            name=data.name,
            slug=data.slug,
            created_by=current_user.id,
            tenant_id=tenant_id,
            description=data.description,
            short_description=data.short_description,
            category=data.category,
            tags=data.tags,
            source=data.source,
            source_ref=data.source_ref,
            icon=data.icon,
            version=data.version,
            manifest=data.manifest,
            dependencies=data.dependencies,
            synergies=data.synergies,
            parent_gene_id=data.parent_gene_id,
            visibility=data.visibility,
        )
        await db.commit()
        return GeneResponse.model_validate(gene, from_attributes=True)
    except ValueError as e:
        raise _invalid_gene_request_error() from e


@router.get("/", response_model=GeneListResponse)
async def list_genes(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    category: str | None = Query(None, description="Filter by category"),
    search: str | None = Query(None, description="Search by name, slug, or description"),
    slugs: str | None = Query(None, description="Comma-separated exact slug filter"),
    visibility: str | None = Query(None, description="Filter by visibility"),
    is_published: bool | None = Query(None, description="Filter by published status"),
    exclude_installed_instance_id: str | None = Query(
        None,
        description="Exclude genes already installed on this instance",
    ),
    tenant_id: str = Depends(_get_selected_gene_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> GeneListResponse:
    """List genes with optional filtering."""
    container = get_container_with_db(request, db)
    service = container.gene_service()
    if exclude_installed_instance_id:
        await _ensure_instance_tenant_access(
            container,
            instance_id=exclude_installed_instance_id,
            tenant_id=tenant_id,
        )
    offset = (page - 1) * page_size
    genes, total = await service.list_genes_with_total(
        tenant_id=tenant_id,
        include_global=True,
        category=category,
        search=search,
        slugs=_split_slug_query(slugs),
        visibility=visibility,
        is_published=is_published,
        exclude_installed_instance_id=exclude_installed_instance_id,
        limit=page_size,
        offset=offset,
    )
    items = [GeneResponse.model_validate(g, from_attributes=True) for g in genes]
    return GeneListResponse(
        genes=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.put("/{gene_id}", response_model=GeneResponse)
async def update_gene(
    request: Request,
    gene_id: str,
    data: GeneUpdate,
    tenant_id: str = Depends(_get_selected_gene_admin_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> GeneResponse:
    """Update a gene."""
    try:
        container = get_container_with_db(request, db)
        service = container.gene_service()
        await _ensure_gene_tenant_access(service, gene_id=gene_id, tenant_id=tenant_id)
        fields = data.model_dump(exclude_unset=True)
        gene = await service.update_gene(gene_id, **fields)
        await db.commit()
        return GeneResponse.model_validate(gene, from_attributes=True)
    except ValueError as e:
        raise _invalid_gene_request_error() from e


@router.delete(
    "/{gene_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_gene(
    request: Request,
    gene_id: str,
    tenant_id: str = Depends(_get_selected_gene_admin_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete (soft-delete) a gene."""
    try:
        container = get_container_with_db(request, db)
        service = container.gene_service()
        await _ensure_gene_tenant_access(service, gene_id=gene_id, tenant_id=tenant_id)
        await service.delete_gene(gene_id)
        await db.commit()
    except ValueError as e:
        raise _gene_not_found_error() from e


@router.post("/{gene_id}/publish", response_model=GeneResponse)
async def publish_gene(
    request: Request,
    gene_id: str,
    tenant_id: str = Depends(_get_selected_gene_admin_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> GeneResponse:
    """Publish a gene to the marketplace."""
    try:
        container = get_container_with_db(request, db)
        service = container.gene_service()
        await _ensure_gene_tenant_access(service, gene_id=gene_id, tenant_id=tenant_id)
        gene = await service.publish_gene(gene_id)
        await db.commit()
        return GeneResponse.model_validate(gene, from_attributes=True)
    except ValueError as e:
        raise _gene_not_found_error() from e


@router.post("/{gene_id}/unpublish", response_model=GeneResponse)
async def unpublish_gene(
    request: Request,
    gene_id: str,
    tenant_id: str = Depends(_get_selected_gene_admin_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> GeneResponse:
    """Remove a gene from the marketplace."""
    try:
        container = get_container_with_db(request, db)
        service = container.gene_service()
        await _ensure_gene_tenant_access(service, gene_id=gene_id, tenant_id=tenant_id)
        gene = await service.unpublish_gene(gene_id)
        await db.commit()
        return GeneResponse.model_validate(gene, from_attributes=True)
    except ValueError as e:
        raise _gene_not_found_error() from e


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
    tenant_id: str = Depends(_get_selected_gene_admin_tenant_id),
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GenomeResponse:
    """Create a new genome (curated gene bundle)."""
    try:
        _ensure_request_tenant_matches(data.tenant_id, tenant_id)
        container = get_container_with_db(request, db)
        service = container.gene_service()
        genome = await service.create_genome(
            name=data.name,
            slug=data.slug,
            created_by=current_user.id,
            tenant_id=tenant_id,
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
        raise _invalid_gene_request_error() from e


@router.get("/genomes", response_model=GenomeListResponse)
async def list_genomes(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    search: str | None = Query(None, description="Search by name, slug, or description"),
    visibility: str | None = Query(None, description="Filter by visibility"),
    is_published: bool | None = Query(None, description="Filter by published status"),
    tenant_id: str = Depends(_get_selected_gene_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> GenomeListResponse:
    """List genomes with optional filtering."""
    container = get_container_with_db(request, db)
    service = container.gene_service()
    offset = (page - 1) * page_size
    genomes, total = await service.list_genomes_with_total(
        tenant_id=tenant_id,
        include_global=True,
        search=search,
        visibility=visibility,
        is_published=is_published,
        limit=page_size,
        offset=offset,
    )
    items = [GenomeResponse.model_validate(g, from_attributes=True) for g in genomes]
    return GenomeListResponse(
        genomes=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/genomes/{genome_id}", response_model=GenomeResponse)
async def get_genome(
    request: Request,
    genome_id: str,
    tenant_id: str = Depends(_get_selected_gene_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> GenomeResponse:
    """Get a genome by ID."""
    container = get_container_with_db(request, db)
    service = container.gene_service()
    genome = await _ensure_genome_tenant_access(
        service,
        genome_id=genome_id,
        tenant_id=tenant_id,
        allow_global=True,
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
    tenant_id: str = Depends(_get_selected_gene_admin_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> GenomeResponse:
    """Update a genome."""
    try:
        container = get_container_with_db(request, db)
        service = container.gene_service()
        await _ensure_genome_tenant_access(service, genome_id=genome_id, tenant_id=tenant_id)
        fields = data.model_dump(exclude_unset=True)
        genome = await service.update_genome(genome_id, **fields)
        await db.commit()
        return GenomeResponse.model_validate(genome, from_attributes=True)
    except ValueError as e:
        raise _invalid_gene_request_error() from e


@router.delete(
    "/genomes/{genome_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_genome(
    request: Request,
    genome_id: str,
    tenant_id: str = Depends(_get_selected_gene_admin_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete (soft-delete) a genome."""
    try:
        container = get_container_with_db(request, db)
        service = container.gene_service()
        await _ensure_genome_tenant_access(service, genome_id=genome_id, tenant_id=tenant_id)
        await service.delete_genome(genome_id)
        await db.commit()
    except ValueError as e:
        raise _genome_not_found_error() from e


@router.post(
    "/genomes/{genome_id}/publish",
    response_model=GenomeResponse,
)
async def publish_genome(
    request: Request,
    genome_id: str,
    tenant_id: str = Depends(_get_selected_gene_admin_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> GenomeResponse:
    """Publish a genome to the marketplace."""
    try:
        container = get_container_with_db(request, db)
        service = container.gene_service()
        await _ensure_genome_tenant_access(service, genome_id=genome_id, tenant_id=tenant_id)
        genome = await service.publish_genome(genome_id)
        await db.commit()
        return GenomeResponse.model_validate(genome, from_attributes=True)
    except ValueError as e:
        raise _genome_not_found_error() from e


@router.post(
    "/genomes/{genome_id}/unpublish",
    response_model=GenomeResponse,
)
async def unpublish_genome(
    request: Request,
    genome_id: str,
    tenant_id: str = Depends(_get_selected_gene_admin_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> GenomeResponse:
    """Remove a genome from the marketplace."""
    try:
        container = get_container_with_db(request, db)
        service = container.gene_service()
        await _ensure_genome_tenant_access(service, genome_id=genome_id, tenant_id=tenant_id)
        genome = await service.unpublish_genome(genome_id)
        await db.commit()
        return GenomeResponse.model_validate(genome, from_attributes=True)
    except ValueError as e:
        raise _genome_not_found_error() from e


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
    tenant_id: str = Depends(_get_selected_gene_admin_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> InstanceGeneResponse:
    """Install a gene on an agent instance."""
    try:
        container = get_container_with_db(request, db)
        service = container.gene_service()
        await _ensure_instance_tenant_access(
            container, instance_id=instance_id, tenant_id=tenant_id
        )
        await _ensure_gene_tenant_access(
            service,
            gene_id=data.gene_id,
            tenant_id=tenant_id,
            allow_global=True,
        )
        instance_gene = await service.install_gene(
            instance_id=instance_id,
            gene_id=data.gene_id,
            config_snapshot=data.config,
        )
        await db.commit()
        return _instance_gene_response(instance_gene)
    except ValueError as e:
        raise _invalid_gene_request_error() from e


@router.delete(
    "/instances/{instance_id}/genes/{instance_gene_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def uninstall_gene(
    request: Request,
    instance_id: str,
    instance_gene_id: str,
    tenant_id: str = Depends(_get_selected_gene_admin_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Uninstall a gene from an agent instance."""
    try:
        container = get_container_with_db(request, db)
        service = container.gene_service()
        await _ensure_instance_gene_tenant_access(
            container,
            service,
            instance_id=instance_id,
            instance_gene_id=instance_gene_id,
            tenant_id=tenant_id,
        )
        await service.uninstall_gene(instance_gene_id)
        await db.commit()
    except ValueError as e:
        raise _instance_gene_not_found_error() from e


@router.get(
    "/instances/{instance_id}/genes",
    response_model=InstanceGeneListResponse,
)
async def list_instance_genes(
    request: Request,
    instance_id: str,
    limit: int = Query(25, ge=1, le=100, description="Max installed genes to return"),
    offset: int = Query(0, ge=0, description="Installed gene offset"),
    search: str | None = Query(None, description="Search installed genes by ID or metadata"),
    tenant_id: str = Depends(_get_selected_gene_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> InstanceGeneListResponse:
    """List all genes installed on an agent instance."""
    container = get_container_with_db(request, db)
    service = container.gene_service()
    await _ensure_instance_tenant_access(container, instance_id=instance_id, tenant_id=tenant_id)
    (
        instance_genes,
        total,
        active_total,
        usage_total,
    ) = await service.list_instance_genes_with_summary(
        instance_id,
        limit=limit,
        offset=offset,
        search=search,
        tenant_id=tenant_id,
    )
    gene_metadata_by_id = await _get_gene_metadata_by_id(
        db,
        {ig.gene_id for ig in instance_genes},
        tenant_id=tenant_id,
    )
    items = [
        _instance_gene_response(
            ig,
            gene_metadata=gene_metadata_by_id.get(ig.gene_id),
        )
        for ig in instance_genes
    ]
    return InstanceGeneListResponse(
        items=items,
        total=total,
        active_total=active_total,
        usage_total=usage_total,
        limit=limit,
        offset=offset,
        has_more=offset + len(items) < total,
    )


@router.get(
    "/instances/{instance_id}/genes/{instance_gene_id}",
    response_model=InstanceGeneResponse,
)
async def get_instance_gene(
    request: Request,
    instance_id: str,
    instance_gene_id: str,
    tenant_id: str = Depends(_get_selected_gene_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> InstanceGeneResponse:
    """Get a specific installed gene record."""
    container = get_container_with_db(request, db)
    service = container.gene_service()
    ig = await _ensure_instance_gene_tenant_access(
        container,
        service,
        instance_id=instance_id,
        instance_gene_id=instance_gene_id,
        tenant_id=tenant_id,
    )
    gene_metadata_by_id = await _get_gene_metadata_by_id(
        db,
        {ig.gene_id},
        tenant_id=tenant_id,
    )
    return _instance_gene_response(
        ig,
        gene_metadata=gene_metadata_by_id.get(ig.gene_id),
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
    tenant_id: str = Depends(_get_selected_gene_tenant_id),
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GeneRatingResponse:
    """Rate a gene (creates or updates the user's rating)."""
    try:
        container = get_container_with_db(request, db)
        service = container.gene_service()
        await _ensure_gene_tenant_access(
            service,
            gene_id=gene_id,
            tenant_id=tenant_id,
            allow_global=True,
        )
        rating = await service.rate_gene(
            gene_id=gene_id,
            user_id=current_user.id,
            rating=data.rating,
            comment=data.comment,
        )
        await db.commit()
        return GeneRatingResponse.model_validate(rating, from_attributes=True)
    except ValueError as e:
        raise _gene_not_found_error() from e


@router.get(
    "/{gene_id}/ratings",
    response_model=list[GeneRatingResponse],
)
async def list_gene_ratings(
    request: Request,
    gene_id: str,
    limit: int = Query(50, ge=1, le=200, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset"),
    tenant_id: str = Depends(_get_selected_gene_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[GeneRatingResponse]:
    """List ratings for a gene."""
    container = get_container_with_db(request, db)
    service = container.gene_service()
    await _ensure_gene_tenant_access(
        service,
        gene_id=gene_id,
        tenant_id=tenant_id,
        allow_global=True,
    )
    ratings = await service.list_gene_ratings(
        gene_id=gene_id,
        limit=limit,
        offset=offset,
    )
    return [GeneRatingResponse.model_validate(r, from_attributes=True) for r in ratings]


@router.get(
    "/genomes/{genome_id}/ratings",
    response_model=list[GenomeRatingResponse],
)
async def list_genome_ratings(
    request: Request,
    genome_id: str,
    limit: int = Query(50, ge=1, le=200, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset"),
    tenant_id: str = Depends(_get_selected_gene_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[GenomeRatingResponse]:
    """List ratings for a genome."""
    container = get_container_with_db(request, db)
    service = container.gene_service()
    await _ensure_genome_tenant_access(
        service,
        genome_id=genome_id,
        tenant_id=tenant_id,
        allow_global=True,
    )
    ratings = await service.list_genome_ratings(
        genome_id=genome_id,
        limit=limit,
        offset=offset,
    )
    return [GenomeRatingResponse.model_validate(r, from_attributes=True) for r in ratings]


@router.post(
    "/genomes/{genome_id}/ratings",
    response_model=GenomeRatingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def rate_genome(
    request: Request,
    genome_id: str,
    data: GenomeRatingCreate,
    tenant_id: str = Depends(_get_selected_gene_tenant_id),
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GenomeRatingResponse:
    """Rate a genome (creates or updates the user's rating)."""
    try:
        container = get_container_with_db(request, db)
        service = container.gene_service()
        await _ensure_genome_tenant_access(
            service,
            genome_id=genome_id,
            tenant_id=tenant_id,
            allow_global=True,
        )
        rating = await service.rate_genome(
            genome_id=genome_id,
            user_id=current_user.id,
            rating=data.rating,
            comment=data.comment,
        )
        await db.commit()
        return GenomeRatingResponse.model_validate(rating, from_attributes=True)
    except ValueError as e:
        raise _genome_not_found_error() from e


# ---------------------------------------------------------------------------
# Evolution Events
# ---------------------------------------------------------------------------


@router.get(
    "/evolution",
    response_model=EvolutionEventListResponse,
)
async def list_evolution_events(
    request: Request,
    instance_id: str | None = Query(None, description="Agent instance ID to query"),
    gene_id: str | None = Query(None, description="Gene ID to query"),
    event_type: EvolutionEventType | None = Query(None, description="Filter by event type"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    tenant_id: str = Depends(_get_selected_gene_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> EvolutionEventListResponse:
    """List evolution events for an agent instance."""
    container = get_container_with_db(request, db)
    service = container.gene_service()
    offset = (page - 1) * page_size
    try:
        if instance_id:
            await _ensure_instance_tenant_access(
                container,
                instance_id=instance_id,
                tenant_id=tenant_id,
                not_found_error=_evolution_event_not_found_error,
            )
        if gene_id:
            await _ensure_gene_tenant_access(
                service,
                gene_id=gene_id,
                tenant_id=tenant_id,
                allow_global=True,
            )
        events, total = await service.list_evolution_events_with_total(
            instance_id=instance_id,
            tenant_id=tenant_id,
            gene_id=gene_id,
            event_type=event_type,
            limit=page_size,
            offset=offset,
        )
    except ValueError as e:
        raise _invalid_evolution_event_request_error() from e
    items = [_evolution_event_response(ev) for ev in events]
    return EvolutionEventListResponse(
        items=items,
        events=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/evolution",
    response_model=EvolutionEventResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_evolution_event(
    request: Request,
    data: EvolutionEventCreateRequest,
    tenant_id: str = Depends(_get_selected_gene_admin_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> EvolutionEventResponse:
    """Create an evolution event record."""
    container = get_container_with_db(request, db)
    service = container.gene_service()
    await _ensure_instance_tenant_access(
        container,
        instance_id=data.instance_id,
        tenant_id=tenant_id,
        not_found_error=_evolution_event_not_found_error,
    )
    if data.gene_id:
        await _ensure_gene_tenant_access(
            service,
            gene_id=data.gene_id,
            tenant_id=tenant_id,
            allow_global=True,
        )
    if data.genome_id:
        await _ensure_genome_tenant_access(
            service,
            genome_id=data.genome_id,
            tenant_id=tenant_id,
            allow_global=True,
        )
    event = await service.create_evolution_event(
        instance_id=data.instance_id,
        gene_id=data.gene_id,
        genome_id=data.genome_id,
        event_type=data.event_type,
        gene_name=data.gene_name,
        gene_slug=data.gene_slug,
        details={
            "from_version": data.from_version,
            "to_version": data.to_version,
            "trigger": data.trigger,
            "payload": data.payload,
            "status": data.status,
        },
    )
    await db.commit()
    return _evolution_event_response(event)


@router.get("/evolution/{event_id}", response_model=EvolutionEventResponse)
async def get_evolution_event(
    request: Request,
    event_id: str,
    tenant_id: str = Depends(_get_selected_gene_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> EvolutionEventResponse:
    """Get a specific evolution event."""
    container = get_container_with_db(request, db)
    service = container.gene_service()
    event = await service.get_evolution_event(event_id)
    if not event:
        raise _evolution_event_not_found_error()
    await _ensure_instance_tenant_access(
        container,
        instance_id=event.instance_id,
        tenant_id=tenant_id,
        not_found_error=_evolution_event_not_found_error,
    )
    return _evolution_event_response(event)


@router.get("/{gene_id}", response_model=GeneResponse)
async def get_gene(
    request: Request,
    gene_id: str,
    tenant_id: str = Depends(_get_selected_gene_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> GeneResponse:
    """Get a gene by ID."""
    container = get_container_with_db(request, db)
    service = container.gene_service()
    gene = await _ensure_gene_tenant_access(
        service,
        gene_id=gene_id,
        tenant_id=tenant_id,
        allow_global=True,
    )
    return GeneResponse.model_validate(gene, from_attributes=True)


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
    tenant_id: str = Depends(_get_selected_gene_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> GeneReviewListResponse:
    container = get_container_with_db(request, db)
    service = container.gene_service()
    await _ensure_gene_tenant_access(
        service,
        gene_id=gene_id,
        tenant_id=tenant_id,
        allow_global=True,
    )
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
    tenant_id: str = Depends(_get_selected_gene_tenant_id),
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GeneReviewResponse:
    try:
        container = get_container_with_db(request, db)
        service = container.gene_service()
        await _ensure_gene_tenant_access(
            service,
            gene_id=gene_id,
            tenant_id=tenant_id,
            allow_global=True,
        )
        review = await service.create_gene_review(
            gene_id=gene_id,
            user_id=current_user.id,
            rating=data.rating,
            content=data.content,
            tenant_id=tenant_id,
        )
        await db.commit()
        return GeneReviewResponse.model_validate(review, from_attributes=True)
    except ValueError as e:
        raise _invalid_gene_request_error() from e


@router.delete(
    "/{gene_id}/reviews/{review_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete gene review",
)
async def delete_gene_review(
    request: Request,
    gene_id: str,
    review_id: str,
    tenant_id: str = Depends(_get_selected_gene_tenant_id),
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        container = get_container_with_db(request, db)
        service = container.gene_service()
        await _ensure_gene_tenant_access(
            service,
            gene_id=gene_id,
            tenant_id=tenant_id,
            allow_global=True,
        )
        await service.delete_gene_review(
            gene_id=gene_id,
            review_id=review_id,
            user_id=current_user.id,
            tenant_id=tenant_id,
        )
        await db.commit()
    except PermissionError as e:
        raise _gene_review_forbidden_error() from e
    except ValueError as e:
        raise _gene_review_not_found_error() from e
