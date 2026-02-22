"""Channel configuration API endpoints."""

import logging
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from jsonschema import Draft7Validator
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, desc, func, nullslast, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.roles import RoleDefinition
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.startup import (
    get_channel_manager,
    reload_channel_manager_connections,
)
from src.infrastructure.adapters.secondary.persistence.channel_models import (
    ChannelConfigModel,
    ChannelOutboxModel,
    ChannelSessionBindingModel,
)
from src.infrastructure.adapters.secondary.persistence.channel_repository import (
    ChannelConfigRepository,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    Role,
    User,
    UserProject,
    UserRole,
    UserTenant,
)
from src.infrastructure.agent.plugins.manager import get_plugin_runtime_manager
from src.infrastructure.agent.plugins.registry import get_plugin_registry
from src.infrastructure.security.encryption_service import get_encryption_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/channels", tags=["channels"])


async def verify_project_access(
    project_id: str,
    user: User,
    db: AsyncSession,
    required_role: Optional[List[str]] = None,
):
    """Verify that user has access to the project.

    Args:
        project_id: Project ID to check access for
        user: Current user
        db: Database session
        required_role: Optional list of required roles (e.g., ["owner", "admin"])

    Raises:
        HTTPException: 403 if access denied
    """
    query = select(UserProject).where(
        and_(UserProject.user_id == user.id, UserProject.project_id == project_id)
    )
    if required_role:
        query = query.where(UserProject.role.in_(required_role))

    result = await db.execute(query)
    user_project = result.scalar_one_or_none()

    if not user_project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to project"
        )
    return user_project


async def verify_tenant_access(
    tenant_id: str,
    user: User,
    db: AsyncSession,
    required_role: Optional[List[str]] = None,
):
    """Verify that user has access to the tenant."""
    if user.is_superuser:
        return True

    query = select(UserTenant).where(
        and_(UserTenant.user_id == user.id, UserTenant.tenant_id == tenant_id)
    )
    if required_role:
        query = query.where(UserTenant.role.in_(required_role))

    result = await db.execute(query)
    user_tenant = result.scalar_one_or_none()
    if not user_tenant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to tenant",
        )
    return True


async def _resolve_project_tenant_id(project_id: str, db: AsyncSession) -> Optional[str]:
    """Resolve tenant_id for project-scoped compatibility routes."""
    try:
        result = await db.execute(select(Project.tenant_id).where(Project.id == project_id))
    except Exception as exc:
        logger.warning("Failed to resolve tenant_id for project=%s: %s", project_id, exc)
        return None
    return result.scalar_one_or_none()


# Pydantic schemas


class ChannelConfigCreate(BaseModel):
    """Schema for creating channel configuration."""

    channel_type: str = Field(
        ...,
        description="Channel type (plugin-provided, e.g. feishu)",
        pattern=r"^[a-z][a-z0-9_-]{1,63}$",
    )
    name: str = Field(..., description="Display name")
    enabled: bool = Field(True, description="Whether enabled")
    connection_mode: str = Field("websocket", description="websocket or webhook")

    # Credentials
    app_id: Optional[str] = Field(None, description="App ID")
    app_secret: Optional[str] = Field(None, description="App secret")
    encrypt_key: Optional[str] = Field(None, description="Encrypt key")
    verification_token: Optional[str] = Field(None, description="Verification token")

    # Webhook
    webhook_url: Optional[str] = Field(None, description="Webhook URL")
    webhook_port: Optional[int] = Field(None, ge=1, le=65535, description="Webhook port")
    webhook_path: Optional[str] = Field(None, description="Webhook path")

    # Access control
    dm_policy: str = Field(
        "open",
        description="DM policy: open, allowlist, disabled",
        pattern=r"^(open|allowlist|disabled)$",
    )
    group_policy: str = Field(
        "open",
        description="Group policy: open, allowlist, disabled",
        pattern=r"^(open|allowlist|disabled)$",
    )
    allow_from: Optional[List[str]] = Field(
        None, description="Allowlist of user IDs (wildcard * = all)"
    )
    group_allow_from: Optional[List[str]] = Field(
        None, description="Allowlist of group/chat IDs"
    )
    rate_limit_per_minute: int = Field(
        60, ge=0, description="Max messages per minute per chat (0 = unlimited)"
    )

    # Settings
    domain: Optional[str] = Field("feishu", description="Domain")
    extra_settings: Optional[dict] = Field(None, description="Extra settings")
    description: Optional[str] = Field(None, description="Description")

    @model_validator(mode="after")
    def _validate_webhook_requires_token(self) -> "ChannelConfigCreate":
        token = self.verification_token
        if not token and isinstance(self.extra_settings, dict):
            token = self.extra_settings.get("verification_token")
        if self.connection_mode == "webhook" and not token:
            raise ValueError(
                "verification_token is required when connection_mode is 'webhook'"
            )
        return self


class ChannelConfigUpdate(BaseModel):
    """Schema for updating channel configuration."""

    name: Optional[str] = None
    enabled: Optional[bool] = None
    connection_mode: Optional[str] = None
    app_id: Optional[str] = None
    app_secret: Optional[str] = None
    encrypt_key: Optional[str] = None
    verification_token: Optional[str] = None
    webhook_url: Optional[str] = None
    webhook_port: Optional[int] = Field(None, ge=1, le=65535)
    webhook_path: Optional[str] = None
    domain: Optional[str] = None
    extra_settings: Optional[dict] = None
    description: Optional[str] = None
    dm_policy: Optional[str] = Field(
        None, pattern=r"^(open|allowlist|disabled)$"
    )
    group_policy: Optional[str] = Field(
        None, pattern=r"^(open|allowlist|disabled)$"
    )
    allow_from: Optional[List[str]] = None
    group_allow_from: Optional[List[str]] = None
    rate_limit_per_minute: Optional[int] = Field(None, ge=0)


class ChannelConfigResponse(BaseModel):
    """Schema for channel configuration response."""

    id: str
    project_id: str
    channel_type: str
    name: str
    enabled: bool
    connection_mode: str
    app_id: Optional[str] = None
    # app_secret is excluded for security
    webhook_url: Optional[str] = None
    webhook_port: Optional[int] = None
    webhook_path: Optional[str] = None
    domain: Optional[str] = None
    extra_settings: Optional[dict] = None
    dm_policy: str = "open"
    group_policy: str = "open"
    allow_from: Optional[List[str]] = None
    group_allow_from: Optional[List[str]] = None
    rate_limit_per_minute: int = 60
    status: str
    last_error: Optional[str] = None
    description: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


class ChannelConfigList(BaseModel):
    """Schema for listing channel configurations."""

    items: List[ChannelConfigResponse]
    total: int


class PluginDiagnosticResponse(BaseModel):
    """Plugin runtime diagnostic entry."""

    plugin_name: str
    code: str
    message: str
    level: str = "warning"


class RuntimePluginResponse(BaseModel):
    """Plugin runtime record for UI management."""

    name: str
    source: str
    package: Optional[str] = None
    version: Optional[str] = None
    enabled: bool = True
    discovered: bool = True
    channel_types: List[str] = Field(default_factory=list)


class RuntimePluginListResponse(BaseModel):
    """List of runtime plugins and diagnostics."""

    items: List[RuntimePluginResponse]
    diagnostics: List[PluginDiagnosticResponse] = Field(default_factory=list)


class PluginInstallRequest(BaseModel):
    """Plugin install request body."""

    requirement: str = Field(..., min_length=1, description="PyPI requirement string")


class PluginActionResponse(BaseModel):
    """Plugin action response payload."""

    success: bool
    message: str
    details: Optional[Dict[str, Any]] = None


class ChannelPluginCatalogItemResponse(BaseModel):
    """Channel type catalog item sourced from plugin registry."""

    channel_type: str
    plugin_name: str
    source: str
    package: Optional[str] = None
    version: Optional[str] = None
    enabled: bool = True
    discovered: bool = True
    schema_supported: bool = False


class ChannelPluginConfigSchemaResponse(BaseModel):
    """Config schema payload for a plugin-provided channel type."""

    channel_type: str
    plugin_name: str
    source: str
    package: Optional[str] = None
    version: Optional[str] = None
    schema_supported: bool = False
    config_schema: Optional[Dict[str, Any]] = None
    config_ui_hints: Optional[Dict[str, Any]] = None
    defaults: Optional[Dict[str, Any]] = None
    secret_paths: List[str] = Field(default_factory=list)


class ChannelPluginCatalogResponse(BaseModel):
    """Catalog response for channel-capable plugins."""

    items: List[ChannelPluginCatalogItemResponse]


_CHANNEL_SETTING_FIELDS = {
    "app_id",
    "app_secret",
    "encrypt_key",
    "verification_token",
    "connection_mode",
    "webhook_url",
    "webhook_port",
    "webhook_path",
    "domain",
}
_SECRET_UNCHANGED_SENTINEL = "__MEMSTACK_SECRET_UNCHANGED__"


def _resolve_channel_metadata(channel_type: str) -> Any | None:
    normalized = (channel_type or "").strip().lower()
    if not normalized:
        return None
    return get_plugin_registry().list_channel_type_metadata().get(normalized)


def _resolve_secret_paths(metadata: Any | None) -> List[str]:
    secret_paths = getattr(metadata, "secret_paths", None) if metadata is not None else None
    if not isinstance(secret_paths, list):
        return []
    normalized: List[str] = []
    for path in secret_paths:
        if isinstance(path, str) and path.strip():
            normalized.append(path.strip())
    return normalized


def _decrypt_app_secret(encrypted_value: Optional[str]) -> Optional[str]:
    if not encrypted_value:
        return None
    encryption_service = get_encryption_service()
    try:
        return encryption_service.decrypt(encrypted_value)
    except Exception:
        logger.warning("Failed to decrypt app_secret while building plugin settings", exc_info=True)
        return encrypted_value


def _split_path(path: str) -> List[str]:
    return [segment for segment in path.split(".") if segment]


_MISSING = object()


def _get_path_value(data: Dict[str, Any], path: str) -> Any:
    current: Any = data
    for segment in _split_path(path):
        if not isinstance(current, dict) or segment not in current:
            return _MISSING
        current = current[segment]
    return current


def _set_path_value(data: Dict[str, Any], path: str, value: Any) -> None:
    segments = _split_path(path)
    if not segments:
        return
    current: Dict[str, Any] = data
    for segment in segments[:-1]:
        child = current.get(segment)
        if not isinstance(child, dict):
            child = {}
            current[segment] = child
        current = child
    current[segments[-1]] = value


def _collect_settings_from_config(
    config: ChannelConfigModel,
    *,
    secret_paths: Optional[List[str]] = None,
) -> Dict[str, Any]:
    settings: Dict[str, Any] = {}
    for field in _CHANNEL_SETTING_FIELDS:
        value = getattr(config, field, None)
        if value is not None:
            settings[field] = value
    if isinstance(config.extra_settings, dict):
        for key, value in config.extra_settings.items():
            if value is not None:
                settings[key] = value

    resolved_secret_paths = secret_paths or ["app_secret"]
    if "app_secret" in settings:
        decrypted_secret = _decrypt_app_secret(settings.get("app_secret"))
        if decrypted_secret is not None:
            settings["app_secret"] = decrypted_secret
    settings = _decrypt_secret_values(settings, resolved_secret_paths)
    return settings


def _build_plugin_settings_payload(
    *,
    payload: Dict[str, Any],
    metadata: Any | None,
    existing_config: Optional[ChannelConfigModel] = None,
    secret_paths: Optional[List[str]] = None,
    apply_defaults: bool = False,
) -> Dict[str, Any]:
    settings: Dict[str, Any] = {}
    if existing_config is not None:
        settings.update(_collect_settings_from_config(existing_config, secret_paths=secret_paths))
    if apply_defaults and isinstance(getattr(metadata, "defaults", None), dict):
        settings.update(metadata.defaults)

    incoming_extra = payload.get("extra_settings")
    if isinstance(incoming_extra, dict):
        settings.update(incoming_extra)

    for field in _CHANNEL_SETTING_FIELDS:
        if field in payload:
            settings[field] = payload.get(field)
    return settings


def _apply_secret_sentinel(
    *,
    settings: Dict[str, Any],
    secret_paths: List[str],
    existing_settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    normalized = dict(settings)
    for path in secret_paths:
        value = _get_path_value(normalized, path)
        if value != _SECRET_UNCHANGED_SENTINEL:
            continue
        existing_value = (
            _get_path_value(existing_settings, path) if isinstance(existing_settings, dict) else _MISSING
        )
        if existing_value is _MISSING:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "message": "Secret sentinel is only valid for existing configs",
                    "errors": [{"path": path, "message": "No existing secret value found"}],
                },
            )
        _set_path_value(normalized, path, existing_value)
    return normalized


def _decrypt_secret_values(settings: Dict[str, Any], secret_paths: List[str]) -> Dict[str, Any]:
    if not secret_paths:
        return dict(settings)
    decrypted = dict(settings)
    encryption_service = get_encryption_service()
    for path in secret_paths:
        value = _get_path_value(decrypted, path)
        if value in (_MISSING, None, "") or not isinstance(value, str):
            continue
        if value == _SECRET_UNCHANGED_SENTINEL:
            continue
        try:
            _set_path_value(decrypted, path, encryption_service.decrypt(value))
        except Exception:
            # Keep original value when already plaintext or not decryptable.
            continue
    return decrypted


def _encrypt_secret_values(settings: Dict[str, Any], secret_paths: List[str]) -> Dict[str, Any]:
    if not secret_paths:
        return dict(settings)
    encrypted = dict(settings)
    encryption_service = get_encryption_service()
    for path in secret_paths:
        value = _get_path_value(encrypted, path)
        if value in (_MISSING, None, ""):
            continue
        if value == _SECRET_UNCHANGED_SENTINEL:
            continue
        _set_path_value(encrypted, path, encryption_service.encrypt(str(value)))
    return encrypted


def _mask_secret_values_for_response(
    settings: Optional[Dict[str, Any]],
    secret_paths: List[str],
) -> Optional[Dict[str, Any]]:
    if not isinstance(settings, dict):
        return settings
    if not secret_paths:
        return dict(settings)
    masked = dict(settings)
    for path in secret_paths:
        if path in _CHANNEL_SETTING_FIELDS:
            continue
        if _get_path_value(masked, path) is not _MISSING:
            _set_path_value(masked, path, _SECRET_UNCHANGED_SENTINEL)
    return masked


def _validate_plugin_settings_schema(
    *,
    channel_type: str,
    metadata: Any | None,
    settings: Dict[str, Any],
) -> None:
    schema = getattr(metadata, "config_schema", None) if metadata is not None else None
    if not isinstance(schema, dict):
        return

    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(settings), key=lambda item: list(item.path))
    if not errors:
        return

    formatted_errors = []
    for error in errors:
        path = ".".join(str(segment) for segment in error.path) or "$"
        formatted_errors.append({"path": path, "message": error.message})

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "message": f"Invalid channel settings for channel_type={channel_type}",
            "errors": formatted_errors,
        },
    )


def _split_settings_to_model_fields(settings: Dict[str, Any]) -> tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    model_fields = {key: settings.get(key) for key in _CHANNEL_SETTING_FIELDS if key in settings}
    extras = {key: value for key, value in settings.items() if key not in _CHANNEL_SETTING_FIELDS}
    return model_fields, extras or None


# Helper function to convert model to response (excluding sensitive data)
def to_response(config: ChannelConfigModel) -> ChannelConfigResponse:
    metadata = _resolve_channel_metadata(config.channel_type)
    secret_paths = _resolve_secret_paths(metadata)
    masked_extra_settings = _mask_secret_values_for_response(config.extra_settings, secret_paths)
    return ChannelConfigResponse(
        id=config.id,
        project_id=config.project_id,
        channel_type=config.channel_type,
        name=config.name,
        enabled=config.enabled,
        connection_mode=config.connection_mode,
        app_id=config.app_id,
        webhook_url=config.webhook_url,
        webhook_port=config.webhook_port,
        webhook_path=config.webhook_path,
        domain=config.domain,
        extra_settings=masked_extra_settings,
        dm_policy=getattr(config, "dm_policy", None) or "open",
        group_policy=getattr(config, "group_policy", None) or "open",
        allow_from=getattr(config, "allow_from", None),
        group_allow_from=getattr(config, "group_allow_from", None),
        rate_limit_per_minute=getattr(config, "rate_limit_per_minute", None) or 60,
        status=config.status,
        last_error=config.last_error,
        description=config.description,
        created_at=config.created_at.isoformat(),
        updated_at=config.updated_at.isoformat() if config.updated_at else None,
    )


def _serialize_plugin_diagnostics(diagnostics: List[Any]) -> List[PluginDiagnosticResponse]:
    """Serialize plugin diagnostics into API response models."""
    serialized: List[PluginDiagnosticResponse] = []
    for diagnostic in diagnostics:
        serialized.append(
            PluginDiagnosticResponse(
                plugin_name=str(getattr(diagnostic, "plugin_name", "unknown")),
                code=str(getattr(diagnostic, "code", "unknown")),
                message=str(getattr(diagnostic, "message", "")),
                level=str(getattr(diagnostic, "level", "warning")),
            )
        )
    return serialized


async def _load_runtime_plugins(
    *,
    tenant_id: Optional[str] = None,
) -> tuple[
    List[Dict[str, Any]],
    List[PluginDiagnosticResponse],
    Dict[str, List[str]],
]:
    """Load plugin runtime view enriched with channel adapter ownership."""
    runtime_manager = get_plugin_runtime_manager()
    await runtime_manager.ensure_loaded()
    plugin_records, diagnostics = runtime_manager.list_plugins(tenant_id=tenant_id)
    channel_factories = get_plugin_registry().list_channel_adapter_factories()

    channel_types_by_plugin: Dict[str, List[str]] = {}
    for channel_type, (plugin_name, _factory) in channel_factories.items():
        channel_types_by_plugin.setdefault(plugin_name, []).append(channel_type)

    for plugin_name, channel_types in channel_types_by_plugin.items():
        channel_types_by_plugin[plugin_name] = sorted(set(channel_types))

    for record in plugin_records:
        record["channel_types"] = channel_types_by_plugin.get(record["name"], [])

    return plugin_records, _serialize_plugin_diagnostics(diagnostics), channel_types_by_plugin


async def _ensure_channel_plugin_enabled_for_project(
    *,
    project_id: str,
    channel_type: str,
    db: AsyncSession,
) -> None:
    """Ensure plugin backing channel_type is enabled for the project's tenant."""
    metadata = _resolve_channel_metadata(channel_type)
    if metadata is None:
        return

    tenant_id = await _resolve_project_tenant_id(project_id, db)
    if not tenant_id:
        return

    plugin_name = str(getattr(metadata, "plugin_name", "")).strip()
    if not plugin_name:
        return

    runtime_manager = get_plugin_runtime_manager()
    plugin_records, _ = runtime_manager.list_plugins(tenant_id=tenant_id)
    plugin_record = next((item for item in plugin_records if item.get("name") == plugin_name), None)
    if plugin_record and not bool(plugin_record.get("enabled", True)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Plugin '{plugin_name}' is disabled for tenant '{tenant_id}'. "
                f"Enable it before configuring channel_type '{channel_type}'."
            ),
        )


async def _reconcile_channel_runtime_after_plugin_change() -> Optional[Dict[str, int]]:
    """Reconcile running channel connections after plugin runtime changes."""
    if get_channel_manager() is None:
        return None
    try:
        reload_plan = await reload_channel_manager_connections(apply_changes=True)
    except Exception as exc:
        logger.warning("Failed to reconcile channel runtime after plugin change: %s", exc)
        return None
    return reload_plan.summary() if reload_plan else None


def _build_channel_catalog_items(
    *,
    plugin_records: List[Dict[str, Any]],
) -> List[ChannelPluginCatalogItemResponse]:
    plugin_by_name = {record["name"]: record for record in plugin_records}
    plugin_registry = get_plugin_registry()
    channel_factories = plugin_registry.list_channel_adapter_factories()
    channel_metadata = plugin_registry.list_channel_type_metadata()

    items: List[ChannelPluginCatalogItemResponse] = []
    for channel_type, (plugin_name, _factory) in sorted(channel_factories.items()):
        plugin_record = plugin_by_name.get(plugin_name, {})
        metadata = channel_metadata.get(channel_type)
        items.append(
            ChannelPluginCatalogItemResponse(
                channel_type=channel_type,
                plugin_name=plugin_name,
                source=str(plugin_record.get("source", "entrypoint")),
                package=plugin_record.get("package"),
                version=plugin_record.get("version"),
                enabled=bool(plugin_record.get("enabled", True)),
                discovered=bool(plugin_record.get("discovered", True)),
                schema_supported=bool(metadata and metadata.config_schema),
            )
        )
    return items


# API Endpoints


@router.get(
    "/projects/{project_id}/plugins",
    response_model=RuntimePluginListResponse,
)
async def list_project_plugins(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List runtime plugins available to the current deployment."""
    await verify_project_access(project_id, current_user, db)
    project_tenant_id = await _resolve_project_tenant_id(project_id, db)
    plugin_records, diagnostics, _ = await _load_runtime_plugins(tenant_id=project_tenant_id)
    return RuntimePluginListResponse(
        items=[RuntimePluginResponse(**record) for record in plugin_records],
        diagnostics=diagnostics,
    )


@router.get(
    "/tenants/{tenant_id}/plugins",
    response_model=RuntimePluginListResponse,
)
async def list_tenant_plugins(
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List runtime plugins for tenant-scoped plugin hub."""
    await verify_tenant_access(tenant_id, current_user, db)
    plugin_records, diagnostics, _ = await _load_runtime_plugins(tenant_id=tenant_id)
    return RuntimePluginListResponse(
        items=[RuntimePluginResponse(**record) for record in plugin_records],
        diagnostics=diagnostics,
    )


@router.get(
    "/tenants/{tenant_id}/plugins/channel-catalog",
    response_model=ChannelPluginCatalogResponse,
)
async def list_tenant_channel_plugin_catalog(
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List channel plugin catalog for tenant-scoped plugin hub."""
    await verify_tenant_access(tenant_id, current_user, db)
    plugin_records, _, _ = await _load_runtime_plugins(tenant_id=tenant_id)
    return ChannelPluginCatalogResponse(items=_build_channel_catalog_items(plugin_records=plugin_records))


@router.get(
    "/tenants/{tenant_id}/plugins/channel-catalog/{channel_type}/schema",
    response_model=ChannelPluginConfigSchemaResponse,
)
async def get_tenant_channel_plugin_schema(
    tenant_id: str,
    channel_type: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return plugin channel schema metadata for tenant-scoped plugin hub."""
    await verify_tenant_access(tenant_id, current_user, db)
    plugin_records, _, _ = await _load_runtime_plugins(tenant_id=tenant_id)
    plugin_by_name = {record["name"]: record for record in plugin_records}
    metadata = get_plugin_registry().list_channel_type_metadata().get(channel_type)
    if metadata is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Channel type not found in plugin catalog: {channel_type}",
        )

    plugin_record = plugin_by_name.get(metadata.plugin_name, {})
    return ChannelPluginConfigSchemaResponse(
        channel_type=metadata.channel_type,
        plugin_name=metadata.plugin_name,
        source=str(plugin_record.get("source", "entrypoint")),
        package=plugin_record.get("package"),
        version=plugin_record.get("version"),
        schema_supported=bool(metadata.config_schema),
        config_schema=metadata.config_schema,
        config_ui_hints=metadata.config_ui_hints,
        defaults=metadata.defaults,
        secret_paths=list(metadata.secret_paths),
    )


@router.post(
    "/tenants/{tenant_id}/plugins/install",
    response_model=PluginActionResponse,
)
async def install_tenant_plugin(
    tenant_id: str,
    data: PluginInstallRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Install plugin package from tenant-scoped plugin hub."""
    await verify_tenant_access(tenant_id, current_user, db, ["owner", "admin"])
    manager = get_plugin_runtime_manager()
    result = await manager.install_plugin(data.requirement)
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "Plugin install failed"),
        )
    channel_reload_plan = await _reconcile_channel_runtime_after_plugin_change()
    details = dict(result)
    if channel_reload_plan is not None:
        details["channel_reload_plan"] = channel_reload_plan
    return PluginActionResponse(
        success=True,
        message=f"Installed plugin requirement: {data.requirement}",
        details=details,
    )


@router.post(
    "/tenants/{tenant_id}/plugins/{plugin_name}/enable",
    response_model=PluginActionResponse,
)
async def enable_tenant_plugin(
    tenant_id: str,
    plugin_name: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Enable plugin from tenant-scoped plugin hub."""
    await verify_tenant_access(tenant_id, current_user, db, ["owner", "admin"])
    manager = get_plugin_runtime_manager()
    diagnostics = await manager.set_plugin_enabled(
        plugin_name,
        enabled=True,
        tenant_id=tenant_id,
    )
    channel_reload_plan = await _reconcile_channel_runtime_after_plugin_change()
    details: Dict[str, Any] = {
        "diagnostics": [item.model_dump() for item in _serialize_plugin_diagnostics(diagnostics)]
    }
    if channel_reload_plan is not None:
        details["channel_reload_plan"] = channel_reload_plan
    return PluginActionResponse(
        success=True,
        message=f"Enabled plugin: {plugin_name}",
        details=details,
    )


@router.post(
    "/tenants/{tenant_id}/plugins/{plugin_name}/disable",
    response_model=PluginActionResponse,
)
async def disable_tenant_plugin(
    tenant_id: str,
    plugin_name: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Disable plugin from tenant-scoped plugin hub."""
    await verify_tenant_access(tenant_id, current_user, db, ["owner", "admin"])
    manager = get_plugin_runtime_manager()
    diagnostics = await manager.set_plugin_enabled(
        plugin_name,
        enabled=False,
        tenant_id=tenant_id,
    )
    channel_reload_plan = await _reconcile_channel_runtime_after_plugin_change()
    details: Dict[str, Any] = {
        "diagnostics": [item.model_dump() for item in _serialize_plugin_diagnostics(diagnostics)]
    }
    if channel_reload_plan is not None:
        details["channel_reload_plan"] = channel_reload_plan
    return PluginActionResponse(
        success=True,
        message=f"Disabled plugin: {plugin_name}",
        details=details,
    )


@router.post(
    "/tenants/{tenant_id}/plugins/{plugin_name}/uninstall",
    response_model=PluginActionResponse,
)
async def uninstall_tenant_plugin(
    tenant_id: str,
    plugin_name: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Uninstall plugin package from tenant-scoped plugin hub."""
    await verify_tenant_access(tenant_id, current_user, db, ["owner", "admin"])
    manager = get_plugin_runtime_manager()
    result = await manager.uninstall_plugin(plugin_name)
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "Plugin uninstall failed"),
        )
    channel_reload_plan = await _reconcile_channel_runtime_after_plugin_change()
    details = dict(result)
    if channel_reload_plan is not None:
        details["channel_reload_plan"] = channel_reload_plan
    return PluginActionResponse(
        success=True,
        message=f"Uninstalled plugin: {plugin_name}",
        details=details,
    )


@router.post(
    "/tenants/{tenant_id}/plugins/reload",
    response_model=PluginActionResponse,
)
async def reload_tenant_plugins(
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reload plugins from tenant-scoped plugin hub."""
    await verify_tenant_access(tenant_id, current_user, db, ["owner", "admin"])
    manager = get_plugin_runtime_manager()
    diagnostics = await manager.reload()
    channel_reload_plan = await _reconcile_channel_runtime_after_plugin_change()
    details: Dict[str, Any] = {
        "diagnostics": [item.model_dump() for item in _serialize_plugin_diagnostics(diagnostics)]
    }
    if channel_reload_plan is not None:
        details["channel_reload_plan"] = channel_reload_plan
    return PluginActionResponse(
        success=True,
        message="Plugin runtime reloaded",
        details=details,
    )


@router.get(
    "/projects/{project_id}/plugins/channel-catalog",
    response_model=ChannelPluginCatalogResponse,
)
async def list_project_channel_plugin_catalog(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List channel types currently provided by loaded plugins."""
    await verify_project_access(project_id, current_user, db)
    project_tenant_id = await _resolve_project_tenant_id(project_id, db)
    plugin_records, _, _ = await _load_runtime_plugins(tenant_id=project_tenant_id)
    return ChannelPluginCatalogResponse(items=_build_channel_catalog_items(plugin_records=plugin_records))


@router.get(
    "/projects/{project_id}/plugins/channel-catalog/{channel_type}/schema",
    response_model=ChannelPluginConfigSchemaResponse,
)
async def get_project_channel_plugin_schema(
    project_id: str,
    channel_type: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return config schema metadata for a plugin-provided channel type."""
    await verify_project_access(project_id, current_user, db)
    project_tenant_id = await _resolve_project_tenant_id(project_id, db)
    plugin_records, _, _ = await _load_runtime_plugins(tenant_id=project_tenant_id)
    plugin_by_name = {record["name"]: record for record in plugin_records}
    metadata = get_plugin_registry().list_channel_type_metadata().get(channel_type)

    if metadata is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Channel type not found in plugin catalog: {channel_type}",
        )

    plugin_record = plugin_by_name.get(metadata.plugin_name, {})
    return ChannelPluginConfigSchemaResponse(
        channel_type=metadata.channel_type,
        plugin_name=metadata.plugin_name,
        source=str(plugin_record.get("source", "entrypoint")),
        package=plugin_record.get("package"),
        version=plugin_record.get("version"),
        schema_supported=bool(metadata.config_schema),
        config_schema=metadata.config_schema,
        config_ui_hints=metadata.config_ui_hints,
        defaults=metadata.defaults,
        secret_paths=list(metadata.secret_paths),
    )


@router.post(
    "/projects/{project_id}/plugins/install",
    response_model=PluginActionResponse,
)
async def install_project_plugin(
    project_id: str,
    data: PluginInstallRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Install a plugin package and reload runtime plugin registry."""
    await verify_project_access(project_id, current_user, db, ["owner", "admin"])
    manager = get_plugin_runtime_manager()
    result = await manager.install_plugin(data.requirement)
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "Plugin install failed"),
        )
    channel_reload_plan = await _reconcile_channel_runtime_after_plugin_change()
    details = dict(result)
    if channel_reload_plan is not None:
        details["channel_reload_plan"] = channel_reload_plan
    return PluginActionResponse(
        success=True,
        message=f"Installed plugin requirement: {data.requirement}",
        details=details,
    )


@router.post(
    "/projects/{project_id}/plugins/{plugin_name}/enable",
    response_model=PluginActionResponse,
)
async def enable_project_plugin(
    project_id: str,
    plugin_name: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Enable plugin and reload runtime plugin registry."""
    await verify_project_access(project_id, current_user, db, ["owner", "admin"])
    manager = get_plugin_runtime_manager()
    project_tenant_id = await _resolve_project_tenant_id(project_id, db)
    diagnostics = await manager.set_plugin_enabled(
        plugin_name,
        enabled=True,
        tenant_id=project_tenant_id,
    )
    channel_reload_plan = await _reconcile_channel_runtime_after_plugin_change()
    details: Dict[str, Any] = {
        "diagnostics": [item.model_dump() for item in _serialize_plugin_diagnostics(diagnostics)]
    }
    if channel_reload_plan is not None:
        details["channel_reload_plan"] = channel_reload_plan
    return PluginActionResponse(
        success=True,
        message=f"Enabled plugin: {plugin_name}",
        details=details,
    )


@router.post(
    "/projects/{project_id}/plugins/{plugin_name}/disable",
    response_model=PluginActionResponse,
)
async def disable_project_plugin(
    project_id: str,
    plugin_name: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Disable plugin and reload runtime plugin registry."""
    await verify_project_access(project_id, current_user, db, ["owner", "admin"])
    manager = get_plugin_runtime_manager()
    project_tenant_id = await _resolve_project_tenant_id(project_id, db)
    diagnostics = await manager.set_plugin_enabled(
        plugin_name,
        enabled=False,
        tenant_id=project_tenant_id,
    )
    channel_reload_plan = await _reconcile_channel_runtime_after_plugin_change()
    details: Dict[str, Any] = {
        "diagnostics": [item.model_dump() for item in _serialize_plugin_diagnostics(diagnostics)]
    }
    if channel_reload_plan is not None:
        details["channel_reload_plan"] = channel_reload_plan
    return PluginActionResponse(
        success=True,
        message=f"Disabled plugin: {plugin_name}",
        details=details,
    )


@router.post(
    "/projects/{project_id}/plugins/{plugin_name}/uninstall",
    response_model=PluginActionResponse,
)
async def uninstall_project_plugin(
    project_id: str,
    plugin_name: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Uninstall plugin package and reload runtime plugin registry."""
    await verify_project_access(project_id, current_user, db, ["owner", "admin"])
    manager = get_plugin_runtime_manager()
    result = await manager.uninstall_plugin(plugin_name)
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "Plugin uninstall failed"),
        )
    channel_reload_plan = await _reconcile_channel_runtime_after_plugin_change()
    details = dict(result)
    if channel_reload_plan is not None:
        details["channel_reload_plan"] = channel_reload_plan
    return PluginActionResponse(
        success=True,
        message=f"Uninstalled plugin: {plugin_name}",
        details=details,
    )


@router.post(
    "/projects/{project_id}/plugins/reload",
    response_model=PluginActionResponse,
)
async def reload_project_plugins(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reload runtime plugin discovery and registrations."""
    await verify_project_access(project_id, current_user, db, ["owner", "admin"])
    manager = get_plugin_runtime_manager()
    diagnostics = await manager.reload()
    channel_reload_plan = await _reconcile_channel_runtime_after_plugin_change()
    details: Dict[str, Any] = {
        "diagnostics": [item.model_dump() for item in _serialize_plugin_diagnostics(diagnostics)]
    }
    if channel_reload_plan is not None:
        details["channel_reload_plan"] = channel_reload_plan
    return PluginActionResponse(
        success=True,
        message="Plugin runtime reloaded",
        details=details,
    )


@router.post(
    "/projects/{project_id}/configs",
    response_model=ChannelConfigResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_config(
    project_id: str,
    data: ChannelConfigCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new channel configuration for a project."""
    # Verify project access (requires admin or owner role)
    await verify_project_access(project_id, current_user, db, ["owner", "admin"])
    await _ensure_channel_plugin_enabled_for_project(
        project_id=project_id,
        channel_type=data.channel_type,
        db=db,
    )

    repo = ChannelConfigRepository(db)
    metadata = _resolve_channel_metadata(data.channel_type)
    payload = data.model_dump(exclude_unset=True)
    model_settings: Dict[str, Any] = {}
    normalized_extra_settings = data.extra_settings

    if metadata and isinstance(getattr(metadata, "config_schema", None), dict):
        secret_paths = _resolve_secret_paths(metadata)
        settings_payload = _build_plugin_settings_payload(
            payload=payload,
            metadata=metadata,
            secret_paths=secret_paths,
            apply_defaults=True,
        )
        settings_payload = _apply_secret_sentinel(
            settings=settings_payload,
            secret_paths=secret_paths,
        )
        _validate_plugin_settings_schema(
            channel_type=data.channel_type,
            metadata=metadata,
            settings=settings_payload,
        )
        encrypted_settings = _encrypt_secret_values(settings_payload, secret_paths)
        model_settings, normalized_extra_settings = _split_settings_to_model_fields(encrypted_settings)
    else:
        # Backward-compatible encryption for legacy non-schema channels.
        encryption_service = get_encryption_service()
        encrypted_secret = None
        if data.app_secret:
            encrypted_secret = encryption_service.encrypt(data.app_secret)
        model_settings["app_secret"] = encrypted_secret

    config = ChannelConfigModel(
        project_id=project_id,
        channel_type=data.channel_type,
        name=data.name,
        enabled=data.enabled,
        connection_mode=str(model_settings.get("connection_mode", data.connection_mode)),
        app_id=model_settings.get("app_id", data.app_id),
        app_secret=model_settings.get("app_secret"),  # Encrypted for schema channels
        encrypt_key=model_settings.get("encrypt_key", data.encrypt_key),
        verification_token=model_settings.get("verification_token", data.verification_token),
        webhook_url=model_settings.get("webhook_url", data.webhook_url),
        webhook_port=model_settings.get("webhook_port", data.webhook_port),
        webhook_path=model_settings.get("webhook_path", data.webhook_path),
        domain=model_settings.get("domain", data.domain),
        extra_settings=normalized_extra_settings,
        dm_policy=data.dm_policy,
        group_policy=data.group_policy,
        allow_from=data.allow_from,
        group_allow_from=data.group_allow_from,
        rate_limit_per_minute=data.rate_limit_per_minute,
        description=data.description,
        created_by=current_user.id,
    )

    created = await repo.create(config)
    await db.commit()

    # Auto-connect if enabled
    if created.enabled:
        channel_manager = get_channel_manager()
        if channel_manager:
            try:
                await channel_manager.add_connection(created)
                logger.info(f"[Channels] Auto-connected channel {created.id}")
            except Exception as e:
                logger.warning(f"[Channels] Failed to auto-connect channel {created.id}: {e}")

    return to_response(created)


@router.get("/projects/{project_id}/configs", response_model=ChannelConfigList)
async def list_configs(
    project_id: str,
    channel_type: Optional[str] = None,
    enabled_only: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List channel configurations for a project."""
    # Verify project access
    await verify_project_access(project_id, current_user, db)

    repo = ChannelConfigRepository(db)
    configs = await repo.list_by_project(
        project_id, channel_type=channel_type, enabled_only=enabled_only
    )

    return ChannelConfigList(items=[to_response(c) for c in configs], total=len(configs))


@router.get("/configs/{config_id}", response_model=ChannelConfigResponse)
async def get_config(
    config_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a channel configuration by ID."""
    repo = ChannelConfigRepository(db)
    config = await repo.get_by_id(config_id)

    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configuration not found")

    # Verify project access
    await verify_project_access(config.project_id, current_user, db)

    return to_response(config)


@router.put("/configs/{config_id}", response_model=ChannelConfigResponse)
async def update_config(
    config_id: str,
    data: ChannelConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a channel configuration."""
    repo = ChannelConfigRepository(db)
    config = await repo.get_by_id(config_id)

    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configuration not found")

    # Verify project access (requires admin or owner role)
    await verify_project_access(config.project_id, current_user, db, ["owner", "admin"])
    await _ensure_channel_plugin_enabled_for_project(
        project_id=config.project_id,
        channel_type=config.channel_type,
        db=db,
    )

    update_data = data.model_dump(exclude_unset=True)
    metadata = _resolve_channel_metadata(config.channel_type)
    if metadata and isinstance(getattr(metadata, "config_schema", None), dict):
        secret_paths = _resolve_secret_paths(metadata)
        existing_settings = _collect_settings_from_config(config, secret_paths=secret_paths)
        settings_payload = _build_plugin_settings_payload(
            payload=update_data,
            metadata=metadata,
            existing_config=config,
            secret_paths=secret_paths,
            apply_defaults=False,
        )
        settings_payload = _apply_secret_sentinel(
            settings=settings_payload,
            secret_paths=secret_paths,
            existing_settings=existing_settings,
        )
        _validate_plugin_settings_schema(
            channel_type=config.channel_type,
            metadata=metadata,
            settings=settings_payload,
        )
        encrypted_settings = _encrypt_secret_values(settings_payload, secret_paths)
        model_settings, normalized_extra_settings = _split_settings_to_model_fields(encrypted_settings)

        for field, value in update_data.items():
            if field in _CHANNEL_SETTING_FIELDS or field == "extra_settings":
                continue
            setattr(config, field, value)

        for field, new_value in model_settings.items():
            setattr(config, field, new_value)

        existing_extra_settings = config.extra_settings if isinstance(config.extra_settings, dict) else None
        if normalized_extra_settings != existing_extra_settings:
            config.extra_settings = normalized_extra_settings
    else:
        # Update fields
        # Encrypt app_secret if provided
        if update_data.get("app_secret"):
            encryption_service = get_encryption_service()
            update_data["app_secret"] = encryption_service.encrypt(update_data["app_secret"])

        for field, value in update_data.items():
            setattr(config, field, value)

    updated = await repo.update(config)
    await db.commit()

    # Restart connection if manager is available
    channel_manager = get_channel_manager()
    if channel_manager:
        try:
            await channel_manager.restart_connection(config_id)
            logger.info(f"[Channels] Restarted connection for channel {config_id}")
        except Exception as e:
            logger.warning(f"[Channels] Failed to restart connection {config_id}: {e}")

    return to_response(updated)


@router.delete("/configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_config(
    config_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a channel configuration."""
    repo = ChannelConfigRepository(db)
    config = await repo.get_by_id(config_id)

    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configuration not found")

    # Verify project access (requires admin or owner role)
    await verify_project_access(config.project_id, current_user, db, ["owner", "admin"])

    # Disconnect channel if connected
    channel_manager = get_channel_manager()
    if channel_manager:
        try:
            await channel_manager.remove_connection(config_id)
            logger.info(f"[Channels] Disconnected channel {config_id}")
        except Exception as e:
            logger.warning(f"[Channels] Failed to disconnect channel {config_id}: {e}")

    deleted = await repo.delete(config_id)
    await db.commit()

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete configuration",
        )

    return None


@router.post("/configs/{config_id}/test", response_model=dict)
async def test_config(
    config_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Test a channel configuration by attempting to connect."""
    repo = ChannelConfigRepository(db)
    config = await repo.get_by_id(config_id)

    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configuration not found")

    # Verify project access
    await verify_project_access(config.project_id, current_user, db)

    # Decrypt credentials for testing
    encryption_service = get_encryption_service()
    app_secret = ""
    if config.app_secret:
        try:
            app_secret = encryption_service.decrypt(config.app_secret)
        except Exception as e:
            logger.warning(f"Failed to decrypt app_secret: {e}")
            return {"success": False, "message": "Failed to decrypt credentials"}

    # Test connection based on channel type
    try:
        if config.channel_type == "feishu":
            from src.infrastructure.adapters.secondary.channels.feishu import (
                FeishuClient,
            )

            # Create client to validate credentials
            FeishuClient(
                app_id=config.app_id or "",
                app_secret=app_secret,
                domain=config.domain or "feishu",
            )

            # Try to get bot info as a test
            # This will fail if credentials are invalid
            # await client.get_bot_info()

            await repo.update_status(config_id, "connected")
            await db.commit()

            return {"success": True, "message": "Connection successful"}
        else:
            return {
                "success": False,
                "message": f"Testing not implemented for {config.channel_type}",
            }

    except Exception as e:
        await repo.update_status(config_id, "error", str(e))
        await db.commit()

        return {"success": False, "message": str(e)}


class ChannelStatusResponse(BaseModel):
    """Schema for channel connection status response."""

    config_id: str
    project_id: str
    channel_type: str
    status: str
    connected: bool
    last_heartbeat: Optional[str] = None
    last_error: Optional[str] = None
    reconnect_attempts: int = 0


class ChannelObservabilitySummaryResponse(BaseModel):
    """Project-level channel routing and delivery summary."""

    project_id: str
    session_bindings_total: int
    outbox_total: int
    outbox_by_status: Dict[str, int]
    active_connections: int
    connected_config_ids: List[str]
    latest_delivery_error: Optional[str] = None


class ChannelOutboxItemResponse(BaseModel):
    """Outbox queue item response."""

    id: str
    channel_config_id: str
    conversation_id: str
    chat_id: str
    status: str
    attempt_count: int
    max_attempts: int
    sent_channel_message_id: Optional[str] = None
    last_error: Optional[str] = None
    next_retry_at: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None


class ChannelOutboxListResponse(BaseModel):
    """Paginated outbox list response."""

    items: List[ChannelOutboxItemResponse]
    total: int


class ChannelSessionBindingItemResponse(BaseModel):
    """Session binding item response."""

    id: str
    channel_config_id: str
    conversation_id: str
    channel_type: str
    chat_id: str
    chat_type: str
    thread_id: Optional[str] = None
    topic_id: Optional[str] = None
    session_key: str
    created_at: str
    updated_at: Optional[str] = None


class ChannelSessionBindingListResponse(BaseModel):
    """Paginated session binding list response."""

    items: List[ChannelSessionBindingItemResponse]
    total: int


@router.get(
    "/projects/{project_id}/observability/summary",
    response_model=ChannelObservabilitySummaryResponse,
)
async def get_project_channel_observability_summary(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get project-level channel routing and delivery observability summary."""
    await verify_project_access(project_id, current_user, db, ["owner", "admin"])

    bindings_total_result = await db.execute(
        select(func.count())
        .select_from(ChannelSessionBindingModel)
        .where(ChannelSessionBindingModel.project_id == project_id)
    )
    session_bindings_total = int(bindings_total_result.scalar() or 0)

    outbox_total_result = await db.execute(
        select(func.count())
        .select_from(ChannelOutboxModel)
        .where(ChannelOutboxModel.project_id == project_id)
    )
    outbox_total = int(outbox_total_result.scalar() or 0)

    outbox_by_status_result = await db.execute(
        select(ChannelOutboxModel.status, func.count())
        .where(ChannelOutboxModel.project_id == project_id)
        .group_by(ChannelOutboxModel.status)
    )
    outbox_by_status: Dict[str, int] = {
        status_name: int(status_count)
        for status_name, status_count in outbox_by_status_result.all()
    }

    latest_error_result = await db.execute(
        select(ChannelOutboxModel.last_error)
        .where(
            ChannelOutboxModel.project_id == project_id,
            ChannelOutboxModel.last_error.isnot(None),
            ChannelOutboxModel.status.in_(["failed", "dead_letter"]),
        )
        .order_by(
            nullslast(desc(ChannelOutboxModel.updated_at)), desc(ChannelOutboxModel.created_at)
        )
        .limit(1)
    )
    latest_delivery_error = latest_error_result.scalar_one_or_none()

    active_connections = 0
    connected_config_ids: List[str] = []
    channel_manager = get_channel_manager()
    if channel_manager:
        for connection in channel_manager.connections.values():
            if connection.project_id == project_id and connection.status == "connected":
                active_connections += 1
                connected_config_ids.append(connection.config_id)

    return ChannelObservabilitySummaryResponse(
        project_id=project_id,
        session_bindings_total=session_bindings_total,
        outbox_total=outbox_total,
        outbox_by_status=outbox_by_status,
        active_connections=active_connections,
        connected_config_ids=connected_config_ids,
        latest_delivery_error=latest_delivery_error,
    )


@router.get(
    "/projects/{project_id}/observability/outbox",
    response_model=ChannelOutboxListResponse,
)
async def list_project_channel_outbox(
    project_id: str,
    status_filter: Optional[Literal["pending", "failed", "sent", "dead_letter"]] = Query(
        None, alias="status", description="Filter by outbox status"
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List outbound queue items for a project."""
    await verify_project_access(project_id, current_user, db, ["owner", "admin"])

    query = select(ChannelOutboxModel).where(ChannelOutboxModel.project_id == project_id)
    count_query = (
        select(func.count())
        .select_from(ChannelOutboxModel)
        .where(ChannelOutboxModel.project_id == project_id)
    )
    if status_filter:
        query = query.where(ChannelOutboxModel.status == status_filter)
        count_query = count_query.where(ChannelOutboxModel.status == status_filter)

    query = query.order_by(desc(ChannelOutboxModel.created_at)).limit(limit).offset(offset)
    result = await db.execute(query)
    items = result.scalars().all()

    total_result = await db.execute(count_query)
    total = int(total_result.scalar() or 0)

    return ChannelOutboxListResponse(
        items=[
            ChannelOutboxItemResponse(
                id=item.id,
                channel_config_id=item.channel_config_id,
                conversation_id=item.conversation_id,
                chat_id=item.chat_id,
                status=item.status,
                attempt_count=item.attempt_count,
                max_attempts=item.max_attempts,
                sent_channel_message_id=item.sent_channel_message_id,
                last_error=item.last_error,
                next_retry_at=item.next_retry_at.isoformat() if item.next_retry_at else None,
                created_at=item.created_at.isoformat(),
                updated_at=item.updated_at.isoformat() if item.updated_at else None,
            )
            for item in items
        ],
        total=total,
    )


@router.get(
    "/projects/{project_id}/observability/session-bindings",
    response_model=ChannelSessionBindingListResponse,
)
async def list_project_channel_session_bindings(
    project_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List deterministic channel session bindings for a project."""
    await verify_project_access(project_id, current_user, db, ["owner", "admin"])

    query = (
        select(ChannelSessionBindingModel)
        .where(ChannelSessionBindingModel.project_id == project_id)
        .order_by(desc(ChannelSessionBindingModel.created_at))
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(query)
    items = result.scalars().all()

    total_result = await db.execute(
        select(func.count())
        .select_from(ChannelSessionBindingModel)
        .where(ChannelSessionBindingModel.project_id == project_id)
    )
    total = int(total_result.scalar() or 0)

    return ChannelSessionBindingListResponse(
        items=[
            ChannelSessionBindingItemResponse(
                id=item.id,
                channel_config_id=item.channel_config_id,
                conversation_id=item.conversation_id,
                channel_type=item.channel_type,
                chat_id=item.chat_id,
                chat_type=item.chat_type,
                thread_id=item.thread_id,
                topic_id=item.topic_id,
                session_key=item.session_key,
                created_at=item.created_at.isoformat(),
                updated_at=item.updated_at.isoformat() if item.updated_at else None,
            )
            for item in items
        ],
        total=total,
    )


@router.get("/configs/{config_id}/status", response_model=ChannelStatusResponse)
async def get_connection_status(
    config_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get real-time connection status for a channel configuration.

    This endpoint returns the live connection status from the
    ChannelConnectionManager, including:
    - Current connection status (connected/disconnected/error)
    - Last heartbeat timestamp
    - Last error message if any
    - Number of reconnection attempts
    """
    repo = ChannelConfigRepository(db)
    config = await repo.get_by_id(config_id)

    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configuration not found")

    # Verify project access
    await verify_project_access(config.project_id, current_user, db)

    # Get real-time status from connection manager
    channel_manager = get_channel_manager()
    if channel_manager:
        status_data = channel_manager.get_status(config_id)
        if status_data:
            return ChannelStatusResponse(
                config_id=status_data["config_id"],
                project_id=status_data["project_id"],
                channel_type=status_data["channel_type"],
                status=status_data["status"],
                connected=status_data["connected"],
                last_heartbeat=status_data.get("last_heartbeat"),
                last_error=status_data.get("last_error"),
                reconnect_attempts=status_data.get("reconnect_attempts", 0),
            )

    # Fall back to database status if not in connection manager
    return ChannelStatusResponse(
        config_id=config.id,
        project_id=config.project_id,
        channel_type=config.channel_type,
        status=config.status,
        connected=config.status == "connected",
        last_heartbeat=None,
        last_error=config.last_error,
        reconnect_attempts=0,
    )


@router.get("/status", response_model=List[ChannelStatusResponse])
async def list_all_connection_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get connection status for all channels.

    Returns a list of all channel connection statuses.
    Requires admin role.
    """
    # Only admins can view all statuses
    has_admin_role = False
    if not current_user.is_superuser:
        role_result = await db.execute(
            select(func.count())
            .select_from(UserRole)
            .join(Role, UserRole.role_id == Role.id)
            .where(
                UserRole.user_id == current_user.id,
                Role.name.in_([RoleDefinition.SYSTEM_ADMIN, "admin", "super_admin"]),
                UserRole.tenant_id.is_(None),
            )
        )
        has_admin_role = bool(role_result.scalar())

    if not current_user.is_superuser and not has_admin_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )

    channel_manager = get_channel_manager()
    if channel_manager:
        statuses = channel_manager.get_all_status()
        return [
            ChannelStatusResponse(
                config_id=s["config_id"],
                project_id=s["project_id"],
                channel_type=s["channel_type"],
                status=s["status"],
                connected=s["connected"],
                last_heartbeat=s.get("last_heartbeat"),
                last_error=s.get("last_error"),
                reconnect_attempts=s.get("reconnect_attempts", 0),
            )
            for s in statuses
        ]

    return []


# ------------------------------------------------------------------
# Push API — agent-initiated outbound messages
# ------------------------------------------------------------------


class PushMessageRequest(BaseModel):
    """Request body for pushing a message to a bound channel."""

    content: str = Field(..., max_length=4000, description="Text content to send")
    content_type: Literal["text", "markdown", "card"] = Field(
        default="text",
        description="Content format: text, markdown, or card (JSON)",
    )
    card: Optional[Dict] = Field(
        default=None,
        description="Card JSON payload (required when content_type is 'card')",
    )


class PushMessageResponse(BaseModel):
    success: bool
    message: str


@router.post(
    "/conversations/{conversation_id}/push",
    response_model=PushMessageResponse,
    summary="Push message to channel",
    description="Send an agent-initiated message to the channel bound to a conversation.",
)
async def push_message_to_channel(
    conversation_id: str,
    body: PushMessageRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PushMessageResponse:
    """Push a message to the channel bound to a conversation."""
    # Verify conversation exists and user has access
    binding = await db.execute(
        select(ChannelSessionBindingModel).where(
            ChannelSessionBindingModel.conversation_id == conversation_id
        )
    )
    binding_row = binding.scalar_one_or_none()
    if not binding_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No channel binding found for this conversation",
        )

    # Verify user has access to the channel's project
    config = await db.execute(
        select(ChannelConfigModel).where(
            ChannelConfigModel.id == binding_row.channel_config_id
        )
    )
    config_row = config.scalar_one_or_none()
    if config_row:
        await verify_project_access(config_row.project_id, user, db)

    from src.application.services.channels.channel_message_router import (
        get_channel_message_router,
    )

    router_instance = get_channel_message_router()
    success = await router_instance.send_to_channel(
        conversation_id=conversation_id,
        content=body.content,
        content_type=body.content_type,
        card=body.card,
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to deliver message to channel",
        )

    return PushMessageResponse(success=True, message="Message sent")
