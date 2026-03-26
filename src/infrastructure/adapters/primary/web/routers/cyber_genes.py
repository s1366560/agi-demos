from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.workspace_cyber_schemas import (
    CyberGeneCreate,
    CyberGeneListResponse,
    CyberGeneResponse,
    CyberGeneUpdate,
)
from src.domain.model.workspace.cyber_gene import (
    CyberGene,
    CyberGeneCategory,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.agent.utils import (
    get_container_with_db,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User

router = APIRouter(
    prefix=("/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/genes"),
    tags=["cyber-genes"],
)


def _to_response(gene: CyberGene) -> CyberGeneResponse:
    return CyberGeneResponse(
        id=gene.id,
        workspace_id=gene.workspace_id,
        name=gene.name,
        category=gene.category,
        description=gene.description,
        config_json=gene.config_json,
        version=gene.version,
        is_active=gene.is_active,
        created_by=gene.created_by,
        created_at=gene.created_at,
        updated_at=gene.updated_at,
    )


@router.post(
    "",
    response_model=CyberGeneResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_gene(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    payload: CyberGeneCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CyberGeneResponse:
    container = get_container_with_db(request, db)
    repo = container.cyber_gene_repository()
    gene = CyberGene(
        workspace_id=workspace_id,
        name=payload.name,
        category=payload.category,
        description=payload.description,
        config_json=payload.config_json,
        version=payload.version,
        is_active=payload.is_active,
        created_by=current_user.id,
    )
    saved = await repo.save(gene)
    await db.commit()
    return _to_response(saved)


@router.get("", response_model=CyberGeneListResponse)
async def list_genes(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    request: Request,
    category: CyberGeneCategory | None = None,
    is_active: bool | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CyberGeneListResponse:
    container = get_container_with_db(request, db)
    repo = container.cyber_gene_repository()
    category_str = category.value if category is not None else None
    items = await repo.find_by_workspace(
        workspace_id=workspace_id,
        category=category_str,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )
    return CyberGeneListResponse(
        items=[_to_response(item) for item in items],
        total=len(items),
    )


@router.get("/{gene_id}", response_model=CyberGeneResponse)
async def get_gene(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    gene_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CyberGeneResponse:
    container = get_container_with_db(request, db)
    repo = container.cyber_gene_repository()
    gene = await repo.find_by_id(gene_id)
    if gene is None or gene.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gene not found",
        )
    return _to_response(gene)


@router.patch("/{gene_id}", response_model=CyberGeneResponse)
async def update_gene(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    gene_id: str,
    payload: CyberGeneUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CyberGeneResponse:
    container = get_container_with_db(request, db)
    repo = container.cyber_gene_repository()
    gene = await repo.find_by_id(gene_id)
    if gene is None or gene.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gene not found",
        )
    if payload.name is not None:
        gene.name = payload.name
    if payload.category is not None:
        gene.category = payload.category
    if payload.description is not None:
        gene.description = payload.description
    if payload.config_json is not None:
        gene.config_json = payload.config_json
    if payload.version is not None:
        gene.version = payload.version
    if payload.is_active is not None:
        gene.is_active = payload.is_active
    gene.updated_at = datetime.now(UTC)
    saved = await repo.save(gene)
    await db.commit()
    return _to_response(saved)


@router.delete(
    "/{gene_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_gene(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    gene_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    container = get_container_with_db(request, db)
    repo = container.cyber_gene_repository()
    gene = await repo.find_by_id(gene_id)
    if gene is None or gene.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gene not found",
        )
    await repo.delete(gene_id)
    await db.commit()
