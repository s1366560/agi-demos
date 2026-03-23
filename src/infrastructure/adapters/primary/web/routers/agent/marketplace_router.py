"""Marketplace endpoints for Skill catalog browsing and installation."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.skill_marketplace_service import SkillMarketplaceService
from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import (
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db

from .utils import get_container_with_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/marketplace", tags=["Skills Marketplace"])


class PaginatedCatalogResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int


class ActionResponse(BaseModel):
    success: bool
    skill_id: str


@router.get("/skills")
async def list_catalog(
    request: Request,
    category: str | None = Query(None, description="Optional category filter"),
    search: str | None = Query(None, description="Optional search string"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        container = get_container_with_db(request, db)
        service = SkillMarketplaceService(
            skill_repo=container.skill_repository(),
            tenant_skill_config_repo=container.tenant_skill_config_repository(),
        )

        entries, total = await service.list_catalog(
            category=category,
            search=search,
            page=page,
            page_size=page_size,
        )

        return {
            "items": [e.to_dict() for e in entries],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except Exception as e:
        logger.error("Error listing skill catalog: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list skill catalog: {e!s}",
        ) from e


@router.get("/skills/{skill_id}")
async def get_skill_details(
    skill_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        container = get_container_with_db(request, db)
        service = SkillMarketplaceService(
            skill_repo=container.skill_repository(),
            tenant_skill_config_repo=container.tenant_skill_config_repository(),
        )

        entry = await service.get_entry(skill_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Skill not found in catalog")

        return entry.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error getting skill %s details: %s", skill_id, e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get skill details: {e!s}",
        ) from e


@router.post("/skills/{skill_id}/install")
async def install_skill(
    skill_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        container = get_container_with_db(request, db)
        service = SkillMarketplaceService(
            skill_repo=container.skill_repository(),
            tenant_skill_config_repo=container.tenant_skill_config_repository(),
        )

        success = await service.install_skill(tenant_id=tenant_id, skill_id=skill_id)
        if not success:
            raise HTTPException(status_code=404, detail="Skill not found")

        await db.commit()
        return {"success": True, "skill_id": skill_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error installing skill %s: %s", skill_id, e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to install skill: {e!s}",
        ) from e


@router.delete("/skills/{skill_id}/install")
async def uninstall_skill(
    skill_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        container = get_container_with_db(request, db)
        service = SkillMarketplaceService(
            skill_repo=container.skill_repository(),
            tenant_skill_config_repo=container.tenant_skill_config_repository(),
        )

        success = await service.uninstall_skill(tenant_id=tenant_id, skill_id=skill_id)
        if not success:
            raise HTTPException(status_code=404, detail="Skill not found")

        await db.commit()
        return {"success": True, "skill_id": skill_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error uninstalling skill %s: %s", skill_id, e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to uninstall skill: {e!s}",
        ) from e


@router.get("/installed")
async def list_installed_skills(
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    try:
        container = get_container_with_db(request, db)
        service = SkillMarketplaceService(
            skill_repo=container.skill_repository(),
            tenant_skill_config_repo=container.tenant_skill_config_repository(),
        )

        entries = await service.list_installed(tenant_id)
        return [e.to_dict() for e in entries]
    except Exception as e:
        logger.error("Error listing installed skills: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list installed skills: {e!s}",
        ) from e
