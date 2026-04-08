"""Tenant agent configuration endpoints for Agent API."""

import json
import logging
from datetime import UTC, datetime
from typing import Any

import jsonschema
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.config import get_settings
from src.domain.model.agent.tenant_agent_config import (
    ConfigType,
    RuntimeHookConfig,
    TenantAgentConfig,
)
from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.sql_tenant_agent_config_repository import (
    SqlTenantAgentConfigRepository,
)
from src.infrastructure.agent.plugins.registry import RegisteredHookMetadata, get_plugin_registry
from src.infrastructure.agent.state.agent_session_pool import invalidate_agent_session

from .access import has_tenant_admin_access, require_tenant_access
from .schemas import (
    HookCatalogEntryResponse,
    HookCatalogResponse,
    RuntimeHookConfigResponse,
    TenantAgentConfigResponse,
    UpdateTenantAgentConfigRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_RUNTIME_HOOK_OVERRIDES = 32
MAX_RUNTIME_HOOK_SETTINGS_KEYS = 16
MAX_RUNTIME_HOOK_SETTINGS_BYTES = 4096
MAX_RUNTIME_HOOK_PRIORITY = 1000
MAX_TOOL_POLICY_ITEMS = 128
MAX_TOOL_NAME_LENGTH = 128
INTERNAL_ERROR_DETAIL = "Internal server error"


def _build_config_response(
    config: TenantAgentConfig,
    *,
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
                plugin_name=item.plugin_name,
                hook_name=item.hook_name,
                enabled=item.enabled,
                priority=item.priority,
                settings={} if redact_runtime_hook_settings else dict(item.settings),
            )
            for item in config.runtime_hooks
        ],
        runtime_hook_settings_redacted=redact_runtime_hook_settings,
        multi_agent_enabled=get_settings().multi_agent_enabled,
        created_at=config.created_at.isoformat(),
        updated_at=config.updated_at.isoformat(),
    )


def _validate_runtime_hooks(
    runtime_hooks: list[RuntimeHookConfig],
    *,
    allowed_unknown_hook_keys: set[tuple[str, str]] | None = None,
) -> None:
    """Reject invalid runtime hook overrides before they reach execution."""
    if len(runtime_hooks) > MAX_RUNTIME_HOOK_OVERRIDES:
        raise HTTPException(
            status_code=422,
            detail=f"runtime_hooks cannot exceed {MAX_RUNTIME_HOOK_OVERRIDES} entries",
        )

    allowed_unknown_keys = allowed_unknown_hook_keys or set()
    catalog = {
        (entry.plugin_name.strip().lower(), entry.hook_name.strip().lower()): entry
        for entry in get_plugin_registry().list_hook_catalog()
    }
    seen_hooks: set[tuple[str, str]] = set()

    for hook in runtime_hooks:
        _validate_runtime_hook_override(
            hook,
            catalog_entry=catalog.get(hook.key),
            seen_hooks=seen_hooks,
            allowed_unknown_keys=allowed_unknown_keys,
        )


def _validate_runtime_hook_override(
    hook: RuntimeHookConfig,
    *,
    catalog_entry: RegisteredHookMetadata | None,
    seen_hooks: set[tuple[str, str]],
    allowed_unknown_keys: set[tuple[str, str]],
) -> None:
    """Validate one runtime hook override against the catalog."""
    hook_label = f"{hook.plugin_name}:{hook.hook_name}"
    if hook.key in seen_hooks:
        raise HTTPException(
            status_code=422, detail=f"Duplicate runtime hook override: {hook_label}"
        )
    seen_hooks.add(hook.key)

    _validate_runtime_hook_priority(hook, hook_label)
    _validate_runtime_hook_settings_size(hook, hook_label)

    if catalog_entry is None:
        if hook.key not in allowed_unknown_keys:
            raise HTTPException(status_code=422, detail=f"Unknown runtime hook: {hook_label}")
        return

    _validate_runtime_hook_settings_schema(hook, catalog_entry, hook_label)


def _validate_runtime_hook_priority(hook: RuntimeHookConfig, hook_label: str) -> None:
    """Validate runtime hook priority bounds."""
    if hook.priority is None or abs(hook.priority) <= MAX_RUNTIME_HOOK_PRIORITY:
        return

    raise HTTPException(
        status_code=422,
        detail=(
            f"Runtime hook priority for {hook_label} must be between "
            f"-{MAX_RUNTIME_HOOK_PRIORITY} and {MAX_RUNTIME_HOOK_PRIORITY}"
        ),
    )


def _validate_runtime_hook_settings_size(hook: RuntimeHookConfig, hook_label: str) -> None:
    """Validate runtime hook settings size limits."""
    if len(hook.settings) > MAX_RUNTIME_HOOK_SETTINGS_KEYS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Runtime hook settings for {hook_label} cannot exceed "
                f"{MAX_RUNTIME_HOOK_SETTINGS_KEYS} keys"
            ),
        )

    serialized_settings = json.dumps(hook.settings, separators=(",", ":"))
    if len(serialized_settings.encode("utf-8")) > MAX_RUNTIME_HOOK_SETTINGS_BYTES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Runtime hook settings for {hook_label} cannot exceed "
                f"{MAX_RUNTIME_HOOK_SETTINGS_BYTES} bytes"
            ),
        )


def _validate_runtime_hook_settings_schema(
    hook: RuntimeHookConfig,
    catalog_entry: RegisteredHookMetadata,
    hook_label: str,
) -> None:
    """Validate runtime hook settings against the catalog schema."""
    schema = dict(catalog_entry.settings_schema)
    if not schema:
        if hook.settings:
            raise HTTPException(
                status_code=422,
                detail=f"Runtime hook {hook_label} does not accept custom settings",
            )
        return

    try:
        jsonschema.validate(instance=hook.settings, schema=schema)
    except jsonschema.ValidationError as exc:
        message = exc.message or "invalid settings"
        raise HTTPException(
            status_code=422,
            detail=f"Invalid settings for runtime hook {hook_label}: {message}",
        ) from exc
    except jsonschema.SchemaError as exc:
        logger.error("Invalid hook schema for %s: %s", hook_label, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Runtime hook schema is invalid for {hook_label}",
        ) from exc


def _normalize_tool_policy_list(
    tools: list[str],
    *,
    field_name: str,
) -> list[str]:
    """Validate and normalize a tool allow/deny list."""
    if len(tools) > MAX_TOOL_POLICY_ITEMS:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} cannot exceed {MAX_TOOL_POLICY_ITEMS} entries",
        )

    normalized: list[str] = []
    seen: set[str] = set()
    for raw_name in tools:
        tool_name = raw_name.strip()
        if not tool_name:
            raise HTTPException(status_code=422, detail=f"{field_name} cannot contain empty tools")
        if len(tool_name) > MAX_TOOL_NAME_LENGTH:
            raise HTTPException(
                status_code=422,
                detail=f"{field_name} tool names cannot exceed {MAX_TOOL_NAME_LENGTH} characters",
            )
        if tool_name in seen:
            raise HTTPException(
                status_code=422,
                detail=f"{field_name} contains duplicate tool: {tool_name}",
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
            detail=f"Tools cannot be both enabled and disabled: {', '.join(overlap)}",
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
        await require_tenant_access(db, current_user, tenant_id)

        config_repo = SqlTenantAgentConfigRepository(db)

        # Get config or return default
        config = await config_repo.get_by_tenant(tenant_id)
        if not config:
            # Return default config
            config = TenantAgentConfig.create_default(tenant_id=tenant_id)

        can_view_runtime_hook_settings = await has_tenant_admin_access(db, current_user, tenant_id)
        return _build_config_response(
            config,
            redact_runtime_hook_settings=not can_view_runtime_hook_settings,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting tenant agent config: {e}")
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL) from e


@router.get("/config/hooks/catalog", response_model=HookCatalogResponse)
async def get_hook_catalog(
    tenant_id: str = Query(..., description="Tenant ID to get hook catalog for"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HookCatalogResponse:
    """Return the runtime hook catalog for tenant admins."""
    await require_tenant_access(db, current_user, tenant_id, require_admin=True)
    hooks = [
        HookCatalogEntryResponse(
            plugin_name=entry.plugin_name,
            hook_name=entry.hook_name,
            display_name=entry.display_name,
            description=entry.description,
            default_priority=entry.default_priority,
            default_enabled=entry.default_enabled,
            default_settings=dict(entry.default_settings),
            settings_schema=dict(entry.settings_schema),
        )
        for entry in get_plugin_registry().list_hook_catalog()
    ]
    return HookCatalogResponse(hooks=hooks)


@router.put("/config", response_model=TenantAgentConfigResponse)
async def update_tenant_agent_config(
    update_request: UpdateTenantAgentConfigRequest,
    request: Request,
    tenant_id: str = Query(..., description="Tenant ID to update config for"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantAgentConfigResponse:
    """
    Update tenant-level agent configuration (T097) - Admin only.

    Only tenant admins can modify the configuration (FR-022).
    """
    try:
        await require_tenant_access(db, current_user, tenant_id, require_admin=True)
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
        enabled_tools, disabled_tools = _validate_tool_policy(enabled_tools, disabled_tools)
        runtime_hooks = (
            [
                RuntimeHookConfig(
                    plugin_name=item.plugin_name,
                    hook_name=item.hook_name,
                    enabled=item.enabled,
                    priority=item.priority,
                    settings=dict(item.settings),
                )
                for item in update_request.runtime_hooks
            ]
            if update_request.runtime_hooks is not None
            else list(config.runtime_hooks)
        )
        if update_request.runtime_hooks is not None:
            _validate_runtime_hooks(
                runtime_hooks,
                allowed_unknown_hook_keys={hook.key for hook in config.runtime_hooks},
            )

        # Create updated config
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

        # Save updated config
        saved_config = await config_repo.save(updated_config)
        invalidate_agent_session(tenant_id=tenant_id)
        return _build_config_response(saved_config)

    except HTTPException:
        raise
    except ValueError as e:
        # Validation error from entity
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Error updating tenant agent config: {e}")
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL) from e
