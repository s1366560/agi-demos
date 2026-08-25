"""
Tenant Skill Config API endpoints.

Provides REST API for managing tenant-level skill configurations,
allowing tenants to disable or override system skills.
"""

import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.tenant_skill_config import TenantSkillAction, TenantSkillConfig
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_current_user_tenant,
)
from src.infrastructure.adapters.primary.web.routers.agent.access import require_tenant_access
from src.infrastructure.adapters.primary.web.tenant_skill_config_application_authority_v2 import (
    TenantSkillConfigApplicationAuthorityV2,
    tenant_skill_config_application_authority_context_v2,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.i18n import gettext as _

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tenant/skills/config", tags=["Tenant Skill Config"])


async def _get_selected_tenant_id(
    selected_tenant_id: str | None = Query(
        None,
        alias="tenant_id",
        min_length=1,
        description="Explicit tenant scope for multi-tenant callers",
    ),
    fallback_tenant_id: str = Depends(get_current_user_tenant),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> str:
    """Resolve tenant skill config scope and validate explicit tenant access."""
    if selected_tenant_id is None:
        return fallback_tenant_id

    await require_tenant_access(db, cast(Any, current_user), selected_tenant_id)
    return selected_tenant_id


async def tenant_skill_config_application_authority_dependency_v2(
    request: Request,
    tenant_id: str = Depends(_get_selected_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[TenantSkillConfigApplicationAuthorityV2]:
    """Yield tenant-authorized services from the pinned generation."""
    async with tenant_skill_config_application_authority_context_v2(
        request=request,
        current_user=current_user,
        tenant_id=tenant_id,
        db=db,
    ) as authority:
        yield authority


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


def _invalid_skill_config_request_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=_("Invalid tenant skill config request"),
    )


# === API Endpoints ===


@router.get("/", response_model=TenantSkillConfigListResponse)
async def list_tenant_skill_configs(
    authority: TenantSkillConfigApplicationAuthorityV2 = Depends(
        tenant_skill_config_application_authority_dependency_v2
    ),
) -> TenantSkillConfigListResponse:
    """
    List all skill configurations for the current tenant.

    Returns all disabled and overridden system skills.
    """
    tenant_id = authority.tenant_id
    repo = authority.services.configs

    configs = await repo.list_by_tenant(tenant_id)
    total = await repo.count_by_tenant(tenant_id)

    return TenantSkillConfigListResponse(
        configs=[config_to_response(c) for c in configs],
        total=total,
    )


@router.get("/{system_skill_name}", response_model=TenantSkillConfigResponse)
async def get_tenant_skill_config(
    system_skill_name: str,
    authority: TenantSkillConfigApplicationAuthorityV2 = Depends(
        tenant_skill_config_application_authority_dependency_v2
    ),
) -> TenantSkillConfigResponse:
    """
    Get a specific tenant skill configuration.

    Returns the config for a specific system skill.
    """
    tenant_id = authority.tenant_id
    repo = authority.services.configs

    config = await repo.get_by_tenant_and_skill(tenant_id, system_skill_name)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Skill configuration not found"),
        )

    return config_to_response(config)


@router.post(
    "/disable", response_model=TenantSkillConfigResponse, status_code=status.HTTP_201_CREATED
)
async def disable_system_skill(
    data: DisableSkillRequest,
    authority: TenantSkillConfigApplicationAuthorityV2 = Depends(
        tenant_skill_config_application_authority_dependency_v2
    ),
) -> TenantSkillConfigResponse:
    """
    Disable a system skill for this tenant.

    The system skill will not be loaded for this tenant.
    """
    try:
        tenant_id = authority.tenant_id
        repo = authority.services.configs

        # Check if config already exists
        existing = await repo.get_by_tenant_and_skill(tenant_id, data.system_skill_name)
        if existing:
            # Update existing config
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

        await authority.db.commit()

        logger.info(f"System skill disabled: {data.system_skill_name} for tenant {tenant_id}")
        return config_to_response(config)

    except ValueError as e:
        raise _invalid_skill_config_request_error() from e


@router.post(
    "/override", response_model=TenantSkillConfigResponse, status_code=status.HTTP_201_CREATED
)
async def override_system_skill(
    data: OverrideSkillRequest,
    authority: TenantSkillConfigApplicationAuthorityV2 = Depends(
        tenant_skill_config_application_authority_dependency_v2
    ),
) -> TenantSkillConfigResponse:
    """
    Override a system skill with a tenant skill.

    The specified tenant skill will be used instead of the system skill.
    """
    try:
        tenant_id = authority.tenant_id
        repo = authority.services.configs
        skill_repo = authority.services.skills

        # Verify override skill exists and belongs to this tenant
        override_skill = await skill_repo.get_by_id(data.override_skill_id)
        if not override_skill:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=_("Override skill not found"),
            )
        if override_skill.tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=_("Override skill must belong to your tenant"),
            )

        # Check if config already exists
        existing = await repo.get_by_tenant_and_skill(tenant_id, data.system_skill_name)
        if existing:
            # Update existing config
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

        await authority.db.commit()

        logger.info(
            f"System skill overridden: {data.system_skill_name} -> {data.override_skill_id} "
            f"for tenant {tenant_id}"
        )
        return config_to_response(config)

    except HTTPException:
        raise
    except ValueError as e:
        raise _invalid_skill_config_request_error() from e


@router.post("/enable", status_code=status.HTTP_204_NO_CONTENT)
async def enable_system_skill(
    data: EnableSkillRequest,
    authority: TenantSkillConfigApplicationAuthorityV2 = Depends(
        tenant_skill_config_application_authority_dependency_v2
    ),
) -> None:
    """
    Re-enable a previously disabled or overridden system skill.

    Removes the tenant configuration, restoring default behavior.
    """
    tenant_id = authority.tenant_id
    repo = authority.services.configs

    # Check if config exists
    existing = await repo.get_by_tenant_and_skill(tenant_id, data.system_skill_name)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Skill configuration not found"),
        )

    await repo.delete_by_tenant_and_skill(tenant_id, data.system_skill_name)
    await authority.db.commit()

    logger.info(f"System skill enabled: {data.system_skill_name} for tenant {tenant_id}")


@router.delete("/{system_skill_name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant_skill_config(
    system_skill_name: str,
    authority: TenantSkillConfigApplicationAuthorityV2 = Depends(
        tenant_skill_config_application_authority_dependency_v2
    ),
) -> None:
    """
    Delete a tenant skill configuration.

    Same as enabling - removes any disable/override config.
    """
    tenant_id = authority.tenant_id
    repo = authority.services.configs

    # Check if config exists
    existing = await repo.get_by_tenant_and_skill(tenant_id, system_skill_name)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Skill configuration not found"),
        )

    _deleted = await repo.delete(existing.id)
    await authority.db.commit()

    logger.info(f"Tenant skill config deleted: {system_skill_name} for tenant {tenant_id}")


@router.get("/status/{system_skill_name}")
async def get_skill_status(
    system_skill_name: str,
    authority: TenantSkillConfigApplicationAuthorityV2 = Depends(
        tenant_skill_config_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    """
    Get the status of a system skill for this tenant.

    Returns whether the skill is enabled, disabled, or overridden.
    """
    tenant_id = authority.tenant_id
    repo = authority.services.configs

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
