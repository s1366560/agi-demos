"""Tenant agent configuration endpoints for Agent API.

Provides read/write operations for tenant-level agent configuration:
- get_tenant_agent_config: Get config for a tenant
- update_tenant_agent_config: Update config (admin only)
"""

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.tenant_agent_config import TenantAgentConfig
from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import UserTenant
from src.infrastructure.adapters.secondary.persistence.sql_tenant_agent_config_repository import (
    SqlTenantAgentConfigRepository,
)

from .schemas import (
    TenantAgentConfigResponse,
    UpdateTenantAgentConfigRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/config/can-modify")
async def check_config_modify_permission(
    tenant_id: str = Query(..., description="Tenant ID to check permission for"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Check if current user can modify tenant agent configuration.

    Returns:
        dict: {"can_modify": bool} indicating if user has admin access
    """
    try:
        # Check if user is tenant admin or global admin
        result = await db.execute(
            select(UserTenant).where(
                UserTenant.user_id == current_user.id,
                UserTenant.tenant_id == tenant_id,
            )
        )
        user_tenant = result.scalar_one_or_none()

        is_global_admin = any(r.role.name == "admin" for r in current_user.roles)  # type: ignore[attr-defined]
        is_tenant_admin = user_tenant and user_tenant.role in ["admin", "owner"]

        return {"can_modify": is_global_admin or is_tenant_admin}

    except Exception as e:
        logger.error(f"Error checking config modify permission: {e}")
        return {"can_modify": False}


@router.get("/config", response_model=TenantAgentConfigResponse)
async def get_tenant_agent_config(
    tenant_id: str = Query(..., description="Tenant ID to get config for"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request | None = None,
) -> TenantAgentConfigResponse:
    """
    Get tenant-level agent configuration (T096).

    All authenticated users can read the configuration (FR-021).
    """
    try:
        # Create repository with the session from request
        config_repo = SqlTenantAgentConfigRepository(db)

        # Get config or return default
        config = await config_repo.get_by_tenant(tenant_id)
        if not config:
            # Return default config
            config = TenantAgentConfig.create_default(tenant_id=tenant_id)

        return TenantAgentConfigResponse(
            id=config.id,
            tenant_id=config.tenant_id,
            config_type=config.config_type.value,
            llm_model=config.llm_model,
            llm_temperature=config.llm_temperature,
            pattern_learning_enabled=config.pattern_learning_enabled,
            multi_level_thinking_enabled=config.multi_level_thinking_enabled,
            max_work_plan_steps=config.max_work_plan_steps,
            tool_timeout_seconds=config.tool_timeout_seconds,
            enabled_tools=config.enabled_tools,
            disabled_tools=config.disabled_tools,
            created_at=config.created_at.isoformat(),
            updated_at=config.updated_at.isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting tenant agent config: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get tenant agent config: {e!s}"
        ) from e


@router.put("/config", response_model=TenantAgentConfigResponse)
async def update_tenant_agent_config(
    update_request: UpdateTenantAgentConfigRequest,
    tenant_id: str = Query(..., description="Tenant ID to update config for"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request | None = None,
) -> TenantAgentConfigResponse:
    """
    Update tenant-level agent configuration (T097) - Admin only.

    Only tenant admins can modify the configuration (FR-022).
    """
    try:
        # Verify tenant admin access
        result = await db.execute(
            select(UserTenant).where(
                UserTenant.user_id == current_user.id,
                UserTenant.tenant_id == tenant_id,
            )
        )
        user_tenant = result.scalar_one_or_none()

        # Check if user is tenant admin or global admin
        is_global_admin = any(r.role.name == "admin" for r in current_user.roles)  # type: ignore[attr-defined]
        is_tenant_admin = user_tenant and user_tenant.role in ["admin", "owner"]

        if not is_global_admin and not is_tenant_admin:
            raise HTTPException(status_code=403, detail="Admin access required")

        # Create repository with the session from request
        config_repo = SqlTenantAgentConfigRepository(db)

        # Get existing config or create default
        config = await config_repo.get_by_tenant(tenant_id)
        if not config:
            config = TenantAgentConfig.create_default(tenant_id=tenant_id)

        # Apply updates - collect all parameters
        llm_model = (
            update_request.llm_model if update_request.llm_model is not None else config.llm_model
        )
        llm_temperature = (
            update_request.llm_temperature
            if update_request.llm_temperature is not None
            else config.llm_temperature
        )
        pattern_learning_enabled = (
            update_request.pattern_learning_enabled
            if update_request.pattern_learning_enabled is not None
            else config.pattern_learning_enabled
        )
        multi_level_thinking_enabled = (
            update_request.multi_level_thinking_enabled
            if update_request.multi_level_thinking_enabled is not None
            else config.multi_level_thinking_enabled
        )
        max_work_plan_steps = (
            update_request.max_work_plan_steps
            if update_request.max_work_plan_steps is not None
            else config.max_work_plan_steps
        )
        tool_timeout_seconds = (
            update_request.tool_timeout_seconds
            if update_request.tool_timeout_seconds is not None
            else config.tool_timeout_seconds
        )
        enabled_tools = (
            update_request.enabled_tools
            if update_request.enabled_tools is not None
            else list(config.enabled_tools)
        )
        disabled_tools = (
            update_request.disabled_tools
            if update_request.disabled_tools is not None
            else list(config.disabled_tools)
        )

        # Create updated config
        updated_config = TenantAgentConfig(
            id=config.id,
            tenant_id=config.tenant_id,
            config_type=config.config_type,
            llm_model=llm_model,
            llm_temperature=llm_temperature,
            pattern_learning_enabled=pattern_learning_enabled,
            multi_level_thinking_enabled=multi_level_thinking_enabled,
            max_work_plan_steps=max_work_plan_steps,
            tool_timeout_seconds=tool_timeout_seconds,
            enabled_tools=enabled_tools,
            disabled_tools=disabled_tools,
            created_at=config.created_at,
            updated_at=datetime.now(UTC),
        )

        # Save updated config
        saved_config = await config_repo.save(updated_config)

        return TenantAgentConfigResponse(
            id=saved_config.id,
            tenant_id=saved_config.tenant_id,
            config_type=saved_config.config_type.value,
            llm_model=saved_config.llm_model,
            llm_temperature=saved_config.llm_temperature,
            pattern_learning_enabled=saved_config.pattern_learning_enabled,
            multi_level_thinking_enabled=saved_config.multi_level_thinking_enabled,
            max_work_plan_steps=saved_config.max_work_plan_steps,
            tool_timeout_seconds=saved_config.tool_timeout_seconds,
            enabled_tools=saved_config.enabled_tools,
            disabled_tools=saved_config.disabled_tools,
            created_at=saved_config.created_at.isoformat(),
            updated_at=saved_config.updated_at.isoformat(),
        )

    except HTTPException:
        raise
    except ValueError as e:
        # Validation error from entity
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Error updating tenant agent config: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to update tenant agent config: {e!s}"
        ) from e
