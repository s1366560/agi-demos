from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from src.application.schemas.workspace_cyber_schemas import (
    CyberGeneCreate,
    CyberGeneListResponse,
    CyberGeneResponse,
    CyberGeneUpdate,
)
from src.domain.model.workspace.cyber_gene import CyberGeneCategory
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.workspace_authority import (
    workspace_core_unavailable_error,
)
from src.infrastructure.adapters.secondary.persistence.models import User

router = APIRouter(
    prefix=("/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/genes"),
    tags=["cyber-genes"],
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
    current_user: User = Depends(get_current_user),
) -> CyberGeneResponse:
    raise workspace_core_unavailable_error()


@router.get("", response_model=CyberGeneListResponse)
async def list_genes(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    category: CyberGeneCategory | None = None,
    is_active: bool | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
) -> CyberGeneListResponse:
    raise workspace_core_unavailable_error()


@router.get("/{gene_id}", response_model=CyberGeneResponse)
async def get_gene(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    gene_id: str,
    current_user: User = Depends(get_current_user),
) -> CyberGeneResponse:
    raise workspace_core_unavailable_error()


@router.patch("/{gene_id}", response_model=CyberGeneResponse)
async def update_gene(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    gene_id: str,
    payload: CyberGeneUpdate,
    current_user: User = Depends(get_current_user),
) -> CyberGeneResponse:
    raise workspace_core_unavailable_error()


@router.delete(
    "/{gene_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_gene(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    gene_id: str,
    current_user: User = Depends(get_current_user),
) -> None:
    raise workspace_core_unavailable_error()
