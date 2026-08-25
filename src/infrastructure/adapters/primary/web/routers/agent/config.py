"""Tenant agent configuration endpoints for Agent API."""

import logging
from datetime import UTC, datetime
from typing import Any, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.config import get_settings
from src.domain.model.agent.tenant_agent_config import (
    ConfigType,
    TenantAgentConfig,
)
from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
)
from src.infrastructure.adapters.primary.web.tenant_agent_config_application_authority_v2 import (
    tenant_agent_config_application_authority_context_v2,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.sql_tenant_agent_config_authority_repository import (
    TenantAgentConfigRevisionConflictError,
)
from src.infrastructure.agent.state.agent_session_pool import invalidate_agent_session
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v1_retirement import (
    PLUGIN_MARKETPLACE_V2_PATH,
    PLUGIN_PROTOCOL_V1_RETIRED_CODE,
)
from src.infrastructure.plugins.v2.boundary import current_generation_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_hook_catalog import runtime_hook_catalog_v2

from .access import has_tenant_admin_access, require_tenant_access
from .schemas import (
    HookCatalogEntryResponse,
    HookCatalogResponse,
    RuntimeHookConfigResponse,
    TenantAgentConfigAuthorityRevisionResponse,
    TenantAgentConfigResponse,
    UpdateTenantAgentConfigRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_TOOL_POLICY_ITEMS = 128
MAX_TOOL_NAME_LENGTH = 128
INTERNAL_ERROR_DETAIL = "Internal server error"


def _build_config_response(
    config: TenantAgentConfig,
    *,
    authority_revision: int = 1,
    redact_runtime_hook_settings: bool = False,
) -> TenantAgentConfigResponse:
    """Convert domain config into API response payload."""
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
        runtime_hooks=[
            RuntimeHookConfigResponse(
                hook_name=item.hook_name,
                plugin_name=item.plugin_name,
                hook_family=item.hook_family,
                executor_kind=item.executor_kind,
                source_ref=item.source_ref,
                entrypoint=item.entrypoint,
                enabled=item.enabled,
                priority=item.priority,
                settings={} if redact_runtime_hook_settings else dict(item.settings),
            )
            for item in config.runtime_hooks
        ],
        runtime_hook_settings_redacted=redact_runtime_hook_settings,
        multi_agent_enabled=get_settings().multi_agent_enabled,
        authority_revision=authority_revision,
        created_at=config.created_at.isoformat(),
        updated_at=config.updated_at.isoformat(),
    )


def _raise_runtime_hook_v1_retired() -> NoReturn:
    """Reject mutation of runtime hooks that are now V2 Profile entries."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "code": PLUGIN_PROTOCOL_V1_RETIRED_CODE,
            "message": _(
                "Runtime hook V1 mutation is retired; manage lifecycle modules through V2 Profiles"
            ),
            "migration_target": PLUGIN_MARKETPLACE_V2_PATH,
        },
    )


def _raise_tenant_agent_config_runtime_unavailable(error: RuntimeV2Error) -> NoReturn:
    """Preserve the structured V2 failure code at the HTTP boundary."""
    logger.warning("Tenant agent config V2 authority unavailable: code=%s", error.code)
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": error.code,
            "message": _("Tenant agent config service is unavailable"),
        },
    ) from error


def _raise_tenant_agent_config_persistence_unavailable(error: SQLAlchemyError) -> NoReturn:
    """Return a stable failure shape without leaking database diagnostics."""
    logger.exception("Tenant agent config persistence failed")
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "tenant_agent_config_persistence_failed",
            "message": _("Tenant agent config persistence is unavailable"),
        },
    ) from error


def _normalize_tool_policy_list(
    tools: list[str],
    *,
    field_name: str,
) -> list[str]:
    """Validate and normalize a tool allow/deny list."""
    if len(tools) > MAX_TOOL_POLICY_ITEMS:
        raise HTTPException(
            status_code=422,
            detail=_("Tool policy cannot exceed the maximum number of entries"),
        )

    normalized: list[str] = []
    seen: set[str] = set()
    for raw_name in tools:
        tool_name = raw_name.strip()
        if not tool_name:
            raise HTTPException(status_code=422, detail=_("Tool policy cannot contain empty tools"))
        if len(tool_name) > MAX_TOOL_NAME_LENGTH:
            raise HTTPException(
                status_code=422,
                detail=_("Tool names cannot exceed the maximum length"),
            )
        if tool_name in seen:
            raise HTTPException(
                status_code=422,
                detail=_("Tool policy contains duplicate tool"),
            )
        seen.add(tool_name)
        normalized.append(tool_name)
    return normalized


def _validate_tool_policy(
    enabled_tools: list[str],
    disabled_tools: list[str],
) -> tuple[list[str], list[str]]:
    """Validate tool allow/deny policy lists before persistence."""
    normalized_enabled = _normalize_tool_policy_list(enabled_tools, field_name="enabled_tools")
    normalized_disabled = _normalize_tool_policy_list(disabled_tools, field_name="disabled_tools")

    overlap = sorted(set(normalized_enabled) & set(normalized_disabled))
    if overlap:
        raise HTTPException(
            status_code=422,
            detail=_("Tools cannot be both enabled and disabled"),
        )
    return normalized_enabled, normalized_disabled


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
        await require_tenant_access(db, current_user, tenant_id, require_admin=True)
        return {"can_modify": True}

    except HTTPException as exc:
        if exc.status_code in {403, 404}:
            return {"can_modify": False}
        raise
    except Exception as e:
        logger.error(f"Error checking config modify permission: {e}")
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL) from e


@router.get("/config", response_model=TenantAgentConfigResponse)
async def get_tenant_agent_config(
    request: Request,
    tenant_id: str = Query(..., description="Tenant ID to get config for"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantAgentConfigResponse:
    """
    Get tenant-level agent configuration (T096).

    All authenticated users can read the configuration (FR-021).
    """
    try:
        async with tenant_agent_config_application_authority_context_v2(
            request=request,
            current_user=current_user,
            tenant_id=tenant_id,
            db=db,
        ) as authority:
            await require_tenant_access(
                authority.db,
                authority.current_user,
                authority.tenant_id,
            )

            config = await authority.services.configs.get_by_tenant(authority.tenant_id)
            if not config:
                config = TenantAgentConfig.create_default(tenant_id=authority.tenant_id)

            can_view_runtime_hook_settings = await has_tenant_admin_access(
                authority.db,
                authority.current_user,
                authority.tenant_id,
            )
            return _build_config_response(
                config,
                authority_revision=await authority.services.authority.get_revision(
                    authority.tenant_id
                ),
                redact_runtime_hook_settings=not can_view_runtime_hook_settings,
            )

    except HTTPException:
        raise
    except RuntimeV2Error as e:
        _raise_tenant_agent_config_runtime_unavailable(e)
    except SQLAlchemyError as e:
        _raise_tenant_agent_config_persistence_unavailable(e)
    except Exception as e:
        logger.error(f"Error getting tenant agent config: {e}")
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL) from e


@router.get(
    "/config/authority-revision",
    response_model=TenantAgentConfigAuthorityRevisionResponse,
)
async def get_tenant_agent_config_authority_revision(
    request: Request,
    tenant_id: str = Query(..., description="Tenant ID to get config revision for"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantAgentConfigAuthorityRevisionResponse:
    """Return the current tenant agent configuration authority revision."""
    try:
        async with tenant_agent_config_application_authority_context_v2(
            request=request,
            current_user=current_user,
            tenant_id=tenant_id,
            db=db,
        ) as authority:
            await require_tenant_access(
                authority.db,
                authority.current_user,
                authority.tenant_id,
            )
            authority_revision = await authority.services.authority.get_revision(
                authority.tenant_id
            )
            return TenantAgentConfigAuthorityRevisionResponse(
                tenant_id=authority.tenant_id,
                authority_revision=authority_revision,
            )
    except HTTPException:
        raise
    except RuntimeV2Error as e:
        _raise_tenant_agent_config_runtime_unavailable(e)
    except SQLAlchemyError as e:
        _raise_tenant_agent_config_persistence_unavailable(e)
    except Exception as e:
        logger.error(f"Error getting tenant agent config authority revision: {e}")
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL) from e


@router.get("/config/hooks/catalog", response_model=HookCatalogResponse)
async def get_hook_catalog(
    tenant_id: str = Query(..., description="Tenant ID to get hook catalog for"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HookCatalogResponse:
    """Return lifecycle modules active in the request's pinned V2 generation."""
    await require_tenant_access(db, current_user, tenant_id, require_admin=True)
    hooks = [
        HookCatalogEntryResponse(
            plugin_name=entry.plugin_name,
            hook_name=entry.hook_name,
            hook_family=entry.hook_family,
            display_name=entry.display_name,
            description=entry.description,
            default_priority=entry.default_priority,
            default_enabled=True,
            default_executor_kind="builtin",
            default_source_ref=entry.module_ref,
            default_entrypoint=None,
            default_settings=dict(entry.default_settings),
            settings_schema=dict(entry.settings_schema),
        )
        for entry in runtime_hook_catalog_v2(current_generation_v2())
    ]
    return HookCatalogResponse(hooks=hooks)


@router.put("/config", response_model=TenantAgentConfigResponse)
async def update_tenant_agent_config(
    update_request: UpdateTenantAgentConfigRequest,
    request: Request,
    tenant_id: str = Query(..., description="Tenant ID to update config for"),
    expected_revision: int = Query(
        ...,
        ge=1,
        description="Authority revision returned by the latest config read",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantAgentConfigResponse:
    """
    Update tenant-level agent configuration (T097) - Admin only.

    Only tenant admins can modify the configuration (FR-022).
    """
    try:
        async with tenant_agent_config_application_authority_context_v2(
            request=request,
            current_user=current_user,
            tenant_id=tenant_id,
            db=db,
        ) as authority:
            await require_tenant_access(
                authority.db,
                authority.current_user,
                authority.tenant_id,
                require_admin=True,
            )
            if update_request.runtime_hooks is not None:
                _raise_runtime_hook_v1_retired()

            snapshot = await authority.services.authority.lock_for_update(
                authority.tenant_id,
                expected_revision=expected_revision,
            )
            config = snapshot.config
            if not config:
                config = TenantAgentConfig.create_default(tenant_id=authority.tenant_id)

            llm_model = (
                update_request.llm_model
                if update_request.llm_model is not None
                else config.llm_model
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
            enabled_tools, disabled_tools = _validate_tool_policy(enabled_tools, disabled_tools)
            runtime_hooks = list(config.runtime_hooks)

            updated_config = TenantAgentConfig(
                id=config.id,
                tenant_id=config.tenant_id,
                config_type=ConfigType.CUSTOM,
                llm_model=llm_model,
                llm_temperature=llm_temperature,
                pattern_learning_enabled=pattern_learning_enabled,
                multi_level_thinking_enabled=multi_level_thinking_enabled,
                max_work_plan_steps=max_work_plan_steps,
                tool_timeout_seconds=tool_timeout_seconds,
                enabled_tools=enabled_tools,
                disabled_tools=disabled_tools,
                runtime_hooks=runtime_hooks,
                created_at=config.created_at,
                updated_at=datetime.now(UTC),
            )

            write = await authority.services.authority.persist(snapshot, updated_config)
            await authority.db.commit()
            invalidate_agent_session(tenant_id=authority.tenant_id)
            return _build_config_response(
                write.config,
                authority_revision=write.authority_revision,
            )

    except HTTPException:
        raise
    except TenantAgentConfigRevisionConflictError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "reason_code": "tenant_agent_config_revision_conflict",
                "expected_revision": e.expected_revision,
                "authority_revision": e.authority_revision,
            },
        ) from e
    except RuntimeV2Error as e:
        _raise_tenant_agent_config_runtime_unavailable(e)
    except SQLAlchemyError as e:
        _raise_tenant_agent_config_persistence_unavailable(e)
    except ValueError as e:
        # Validation error from entity
        raise HTTPException(status_code=422, detail=_("Invalid tenant agent config")) from e
    except Exception as e:
        logger.error(f"Error updating tenant agent config: {e}")
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL) from e
