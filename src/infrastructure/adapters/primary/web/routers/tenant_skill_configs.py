"""
Tenant Skill Config API endpoints.

Provides REST API for managing tenant-level skill configurations,
allowing tenants to disable or override system skills.
"""

import logging
from datetime import UTC
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.di_container import DIContainer
from src.domain.model.agent.tenant_skill_config import TenantSkillAction, TenantSkillConfig
from src.infrastructure.adapters.primary.web.dependencies import get_current_user_tenant
from src.infrastructure.adapters.secondary.persistence.database import get_db


def get_container_with_db(request: Request, db: AsyncSession) -> DIContainer:
    """Get DI container with database session for the current request."""
    app_container = request.app.state.container
    return DIContainer(
        db=db,
        graph_service=app_container.graph_service,
        redis_client=app_container._redis_client,
    )


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tenant/skills/config", tags=["Tenant Skill Config"])


# === Pydantic Models ===


class TenantSkillConfigResponse(BaseModel):
    """Schema for tenant skill config response."""

    id: str
    tenant_id: str
    system_skill_name: str
    action: str
    override_skill_id: str | None
    created_at: str
    updated_at: str


class TenantSkillConfigListResponse(BaseModel):
    """Schema for tenant skill config list response."""

    configs: list[TenantSkillConfigResponse]
    total: int


class DisableSkillRequest(BaseModel):
    """Schema for disabling a system skill."""

    system_skill_name: str = Field(
        ..., min_length=1, description="Name of the system skill to disable"
    )


class OverrideSkillRequest(BaseModel):
    """Schema for overriding a system skill."""

    system_skill_name: str = Field(
        ..., min_length=1, description="Name of the system skill to override"
    )
    override_skill_id: str = Field(
        ..., min_length=1, description="ID of the tenant skill to use instead"
    )


class EnableSkillRequest(BaseModel):
    """Schema for re-enabling a system skill."""

    system_skill_name: str = Field(
        ..., min_length=1, description="Name of the system skill to enable"
    )


# === Helper Functions ===


def config_to_response(config: TenantSkillConfig) -> TenantSkillConfigResponse:
    """Convert domain TenantSkillConfig to response model."""
    return TenantSkillConfigResponse(
        id=config.id,
        tenant_id=config.tenant_id,
        system_skill_name=config.system_skill_name,
        action=config.action.value,
        override_skill_id=config.override_skill_id,
        created_at=config.created_at.isoformat(),
        updated_at=config.updated_at.isoformat(),
    )


# === API Endpoints ===


@router.get("/", response_model=TenantSkillConfigListResponse)
async def list_tenant_skill_configs(
    request: Request,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> TenantSkillConfigListResponse:
    """
    List all skill configurations for the current tenant.

    Returns all disabled and overridden system skills.
    """
    container = get_container_with_db(request, db)
    repo = container.tenant_skill_config_repository()

    configs = await repo.list_by_tenant(tenant_id)
    total = await repo.count_by_tenant(tenant_id)

    return TenantSkillConfigListResponse(
        configs=[config_to_response(c) for c in configs],
        total=total,
    )


@router.get("/{system_skill_name}", response_model=TenantSkillConfigResponse)
async def get_tenant_skill_config(
    request: Request,
    system_skill_name: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> config_to_response:
    """
    Get a specific tenant skill configuration.

    Returns the config for a specific system skill.
    """
    container = get_container_with_db(request, db)
    repo = container.tenant_skill_config_repository()

    config = await repo.get_by_tenant_and_skill(tenant_id, system_skill_name)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No configuration found for system skill: {system_skill_name}",
        )

    return config_to_response(config)


@router.post(
    "/disable", response_model=TenantSkillConfigResponse, status_code=status.HTTP_201_CREATED
)
async def disable_system_skill(
    request: Request,
    data: DisableSkillRequest,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> config_to_response:
    """
    Disable a system skill for this tenant.

    The system skill will not be loaded for this tenant.
    """
    try:
        container = get_container_with_db(request, db)
        repo = container.tenant_skill_config_repository()

        # Check if config already exists
        existing = await repo.get_by_tenant_and_skill(tenant_id, data.system_skill_name)
        if existing:
            # Update existing config
            from datetime import datetime

            existing.action = TenantSkillAction.DISABLE
            existing.override_skill_id = None
            existing.updated_at = datetime.now(UTC)
            config = await repo.update(existing)
        else:
            # Create new config
            config = TenantSkillConfig.create_disable(
                tenant_id=tenant_id,
                system_skill_name=data.system_skill_name,
            )
            config = await repo.create(config)

        await db.commit()

        logger.info(f"System skill disabled: {data.system_skill_name} for tenant {tenant_id}")
        return config_to_response(config)

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.post(
    "/override", response_model=TenantSkillConfigResponse, status_code=status.HTTP_201_CREATED
)
async def override_system_skill(
    request: Request,
    data: OverrideSkillRequest,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> config_to_response:
    """
    Override a system skill with a tenant skill.

    The specified tenant skill will be used instead of the system skill.
    """
    try:
        container = get_container_with_db(request, db)
        repo = container.tenant_skill_config_repository()
        skill_repo = container.skill_repository()

        # Verify override skill exists and belongs to this tenant
        override_skill = await skill_repo.get_by_id(data.override_skill_id)
        if not override_skill:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Override skill not found: {data.override_skill_id}",
            )
        if override_skill.tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Override skill must belong to your tenant",
            )

        # Check if config already exists
        existing = await repo.get_by_tenant_and_skill(tenant_id, data.system_skill_name)
        if existing:
            # Update existing config
            from datetime import datetime

            existing.action = TenantSkillAction.OVERRIDE
            existing.override_skill_id = data.override_skill_id
            existing.updated_at = datetime.now(UTC)
            config = await repo.update(existing)
        else:
            # Create new config
            config = TenantSkillConfig.create_override(
                tenant_id=tenant_id,
                system_skill_name=data.system_skill_name,
                override_skill_id=data.override_skill_id,
            )
            config = await repo.create(config)

        await db.commit()

        logger.info(
            f"System skill overridden: {data.system_skill_name} -> {data.override_skill_id} "
            f"for tenant {tenant_id}"
        )
        return config_to_response(config)

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.post("/enable", status_code=status.HTTP_204_NO_CONTENT)
async def enable_system_skill(
    request: Request,
    data: EnableSkillRequest,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Re-enable a previously disabled or overridden system skill.

    Removes the tenant configuration, restoring default behavior.
    """
    container = get_container_with_db(request, db)
    repo = container.tenant_skill_config_repository()

    # Check if config exists
    existing = await repo.get_by_tenant_and_skill(tenant_id, data.system_skill_name)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No configuration found for system skill: {data.system_skill_name}",
        )

    await repo.delete_by_tenant_and_skill(tenant_id, data.system_skill_name)
    await db.commit()

    logger.info(f"System skill enabled: {data.system_skill_name} for tenant {tenant_id}")


@router.delete("/{system_skill_name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant_skill_config(
    request: Request,
    system_skill_name: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Delete a tenant skill configuration.

    Same as enabling - removes any disable/override config.
    """
    container = get_container_with_db(request, db)
    repo = container.tenant_skill_config_repository()

    # Check if config exists
    existing = await repo.get_by_tenant_and_skill(tenant_id, system_skill_name)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No configuration found for system skill: {system_skill_name}",
        )

    await repo.delete(existing.id)
    await db.commit()

    logger.info(f"Tenant skill config deleted: {system_skill_name} for tenant {tenant_id}")


@router.get("/status/{system_skill_name}")
async def get_skill_status(
    request: Request,
    system_skill_name: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Get the status of a system skill for this tenant.

    Returns whether the skill is enabled, disabled, or overridden.
    """
    container = get_container_with_db(request, db)
    repo = container.tenant_skill_config_repository()

    config = await repo.get_by_tenant_and_skill(tenant_id, system_skill_name)

    if not config:
        return {
            "system_skill_name": system_skill_name,
            "status": "enabled",
            "action": None,
            "override_skill_id": None,
        }

    return {
        "system_skill_name": system_skill_name,
        "status": "disabled" if config.is_disabled() else "overridden",
        "action": config.action.value,
        "override_skill_id": config.override_skill_id,
    }
