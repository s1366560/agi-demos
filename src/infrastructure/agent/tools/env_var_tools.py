"""
Environment Variable Tools for Agent Tools Configuration.

These tools allow the agent to:
1. get_env_var_tool: Load environment variables from the database
2. request_env_var_tool: Request missing environment variables from the user
3. check_env_vars_tool: Check if required environment variables are configured

Architecture (Ray-based for HITL):
- RequestEnvVarTool uses RayHITLHandler for unified HITL handling
- Redis Streams for response delivery
- SSE events for real-time frontend updates

GetEnvVarTool and CheckEnvVarsTool do NOT use HITL, they just read from database.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.infrastructure.agent.hitl.ray_hitl_handler import RayHITLHandler

from src.domain.model.agent.tool_environment_variable import (
    EnvVarScope,
    ToolEnvironmentVariable,
)
from src.domain.ports.repositories.tool_environment_variable_repository import (
    ToolEnvironmentVariableRepositoryPort,
)
from src.infrastructure.agent.hitl.utils import (
    build_env_var_request_context as _build_shared_env_var_request_context,
    build_stable_hitl_request_id as _build_stable_hitl_request_id,
    contains_secret_like_text as _shared_contains_secret_like_text,
    normalize_env_var_name as _shared_normalize_env_var_name,
    sanitize_env_var_context as _shared_sanitize_env_var_context,
    sanitize_env_var_plain_text as _shared_sanitize_env_var_plain_text,
    sanitize_env_var_text as _shared_sanitize_env_var_text,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.security.encryption_service import (
    EncryptionService,
    get_encryption_service,
)

logger = logging.getLogger(__name__)

__all__ = [
    "check_env_vars_tool",
    "configure_env_var_tools",
    "get_env_var_tool",
    "request_env_var_tool",
]


@dataclass(frozen=True)
class PreparedEnvVarRequest:
    """Normalized HITL env-var request payload reused for ids and execution."""

    hitl_fields: list[dict[str, Any]]
    field_specs: dict[str, dict[str, Any]]
    request_message: str
    request_context: dict[str, Any]
    requested_names: list[str]
    scope_label: str


# ===========================================================================
# Decorator-based tool definitions (@tool_define)
#
# These replace the class-based tools above for the new ToolPipeline.
# Existing classes are preserved for backward compatibility.
# ===========================================================================


# ---------------------------------------------------------------------------
# Module-level DI references (set via configure_env_var_tools)
# ---------------------------------------------------------------------------

_env_var_repo: ToolEnvironmentVariableRepositoryPort | None = None
_encryption_svc: EncryptionService | None = None
_hitl_handler_ref: RayHITLHandler | None = None
_session_factory_ref: Any = None
_tenant_id_ref: str | None = None
_project_id_ref: str | None = None
_event_publisher_ref: Callable[[dict[str, Any]], None] | None = None
_TOOL_NAME_MAX_LEN = 100
_TOOL_NAME_RE = re.compile(rf"^[A-Za-z][A-Za-z0-9_-]{{0,{_TOOL_NAME_MAX_LEN - 1}}}$")


def configure_env_var_tools(
    *,
    repository: ToolEnvironmentVariableRepositoryPort | None = None,
    encryption_service: EncryptionService | None = None,
    hitl_handler: RayHITLHandler | None = None,
    session_factory: Any = None,
    tenant_id: str | None = None,
    project_id: str | None = None,
    event_publisher: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    """Configure all env-var tools with shared dependencies.

    Called at agent startup to inject repository, encryption, HITL handler,
    and tenant/project context for the decorator-based tool functions.
    """
    global _env_var_repo, _encryption_svc, _hitl_handler_ref
    global _session_factory_ref, _tenant_id_ref
    global _project_id_ref, _event_publisher_ref

    _env_var_repo = repository
    _encryption_svc = encryption_service or get_encryption_service()
    _hitl_handler_ref = hitl_handler
    _session_factory_ref = session_factory
    _tenant_id_ref = tenant_id
    _project_id_ref = project_id
    _event_publisher_ref = event_publisher


def _normalize_env_var_name(value: object) -> str:
    """Validate and normalize an environment variable identifier."""
    return _shared_normalize_env_var_name(value)


def _normalize_tool_name(value: object) -> str:
    """Validate and normalize a tool identifier before user-visible use."""
    if not isinstance(value, str):
        return ""
    candidate = value.strip()
    if not candidate:
        return ""
    if not _TOOL_NAME_RE.fullmatch(candidate):
        return ""
    if _contains_secret_like_text(candidate):
        return ""
    return candidate


def _resolve_tool_scope(ctx: ToolContext) -> tuple[str | None, str | None]:
    """Resolve tenant/project scope strictly from the per-call tool context."""
    tenant_id = ctx.tenant_id.strip() or None
    project_id = ctx.project_id.strip() or None
    return tenant_id, project_id


def _scope_env_var_hitl_handler(
    base_handler: Any,
    *,
    tenant_id: str | None,
    project_id: str | None,
    conversation_id: str | None,
    message_id: str | None,
) -> Any:
    """Clone a HITL handler without restoring tenant/project scope from ambient state."""
    if base_handler is None:
        return None

    from src.infrastructure.agent.hitl.ray_hitl_handler import RayHITLHandler

    if not isinstance(base_handler, RayHITLHandler):
        return base_handler

    resolved_conversation_id = conversation_id or base_handler.conversation_id
    resolved_message_id = base_handler.message_id if message_id is None else message_id

    return base_handler.with_scope(
        tenant_id=tenant_id or "",
        project_id=project_id,
        conversation_id=resolved_conversation_id,
        message_id=resolved_message_id,
    )


_scope_hitl_handler = _scope_env_var_hitl_handler


_scope_hitl_handler = _scope_env_var_hitl_handler


def _contains_secret_like_text(value: str) -> bool:
    """Detect secret-like tokens in freeform text before persisting or echoing them."""
    return _shared_contains_secret_like_text(value)


def _sanitize_persisted_description(value: object) -> str | None:
    """Persist descriptions only when they do not contain secret-like content."""
    return _shared_sanitize_env_var_plain_text(value)


def _sanitize_request_message(value: object) -> str | None:
    """Keep only safe custom HITL prompt text."""
    return _sanitize_text_field(value)


def _sanitize_text_field(value: object) -> str | None:
    """Allow only HTML-safe, non-secret strings in HITL payload content."""
    return _shared_sanitize_env_var_text(value)


def _sanitize_request_context(raw_context: dict[str, Any]) -> dict[str, Any]:
    """Filter HITL context to safe scalar or list values only."""
    return _shared_sanitize_env_var_context(raw_context)


def _build_requested_names(fields: list[dict[str, Any]]) -> list[str]:
    """Build safe user-facing field names for HITL messages."""
    return [_safe_field_label_plain(field) for field in fields if _safe_field_label_plain(field)]


def _build_hitl_env_fields(
    fields: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Convert normalized env-var field definitions into HITL payload and validation specs."""
    hitl_fields: list[dict[str, Any]] = []
    field_specs: dict[str, dict[str, Any]] = {}

    for field in fields:
        input_type = field.get("input_type", "text")
        is_secret = bool(field.get("is_secret", True))
        variable_name = _normalize_env_var_name(field.get("variable_name"))
        label = _sanitize_text_field(field.get("display_name")) or variable_name
        sanitized_description = _sanitize_text_field(field.get("description"))
        sanitized_default_value = _sanitize_text_field(field.get("default_value"))
        sanitized_placeholder = _sanitize_text_field(field.get("placeholder"))
        persisted_description = (
            None if is_secret else _sanitize_persisted_description(field.get("description"))
        )
        if input_type == "password" or is_secret:
            input_type = "password"
            sanitized_default_value = None
            sanitized_placeholder = None

        hitl_fields.append(
            {
                "name": variable_name,
                "label": label,
                "description": sanitized_description,
                "required": bool(field.get("is_required", True)),
                "secret": is_secret,
                "input_type": input_type,
                "default_value": sanitized_default_value,
                "placeholder": sanitized_placeholder,
            }
        )
        field_specs[variable_name] = {
            "description": persisted_description,
            "is_required": bool(field.get("is_required", True)),
            "is_secret": is_secret,
        }

    return hitl_fields, field_specs


def _build_env_var_request_id(
    *,
    tenant_id: str,
    project_id: str | None,
    conversation_id: str,
    message_id: str | None,
    call_id: str,
    tool_name: str,
    fields: list[dict[str, Any]],
    message: str,
    context: dict[str, Any] | None,
    allow_save: bool,
) -> str:
    """Build a deterministic request id so resumed HITL can match the original request."""
    payload = {
        "tool_name": tool_name,
        "fields": fields,
        "message": message,
        "context": dict(context or {}),
        "allow_save": allow_save,
    }
    return _build_stable_hitl_request_id(
        "env",
        tenant_id=tenant_id,
        project_id=project_id,
        conversation_id=conversation_id,
        message_id=message_id,
        call_id=call_id,
        payload=payload,
    )


def _safe_field_label(field: dict[str, Any]) -> str:
    """Use a sanitized display name when available, otherwise fall back to the identifier."""
    variable_name = _normalize_env_var_name(field.get("variable_name"))
    return _sanitize_text_field(field.get("display_name")) or variable_name


def _safe_field_label_plain(field: dict[str, Any]) -> str:
    """Use a secret-safe plain label for user-facing summaries and tool results."""
    variable_name = _normalize_env_var_name(field.get("variable_name"))
    return _shared_sanitize_env_var_plain_text(field.get("display_name")) or variable_name


# ---------------------------------------------------------------------------
# Helper: get a usable repository (session_factory path or injected repo)
# ---------------------------------------------------------------------------


async def _get_env_var(
    tenant_id: str,
    tool_name: str,
    variable_name: str,
    project_id: str | None,
    *,
    session_factory: Any,
    repository: ToolEnvironmentVariableRepositoryPort | None,
) -> ToolEnvironmentVariable | None:
    """Retrieve a single env var via session_factory or injected repo."""
    if session_factory:
        from src.infrastructure.adapters.secondary.persistence.sql_tool_environment_variable_repository import (
            SqlToolEnvironmentVariableRepository,
        )

        async with session_factory() as db_session:
            repo = SqlToolEnvironmentVariableRepository(db_session)
            return await repo.get(
                tenant_id=tenant_id,
                tool_name=tool_name,
                variable_name=variable_name,
                project_id=project_id,
            )

    if repository is None:
        return None
    return await repository.get(
        tenant_id=tenant_id,
        tool_name=tool_name,
        variable_name=variable_name,
        project_id=project_id,
    )


async def _get_env_vars_for_tool(
    tenant_id: str,
    tool_name: str,
    project_id: str | None,
    *,
    session_factory: Any,
    repository: ToolEnvironmentVariableRepositoryPort | None,
) -> list[ToolEnvironmentVariable]:
    """Retrieve all env vars for a tool via session_factory or injected repo."""
    if session_factory:
        from src.infrastructure.adapters.secondary.persistence.sql_tool_environment_variable_repository import (
            SqlToolEnvironmentVariableRepository,
        )

        async with session_factory() as db_session:
            repo = SqlToolEnvironmentVariableRepository(db_session)
            return await repo.get_for_tool(
                tenant_id=tenant_id,
                tool_name=tool_name,
                project_id=project_id,
            )

    if repository is None:
        return []
    return await repository.get_for_tool(
        tenant_id=tenant_id,
        tool_name=tool_name,
        project_id=project_id,
    )


# ---------------------------------------------------------------------------
# Helper: save env vars (used by request_env_var_tool)
# ---------------------------------------------------------------------------


async def _upsert_env_vars_to_repo(
    repository: Any,
    encryption_service: EncryptionService,
    tenant_id: str,
    tool_name: str,
    values: dict[str, str],
    field_specs: dict[str, dict[str, Any]],
    scope: EnvVarScope,
    project_id: str | None,
) -> list[str]:
    """Encrypt and upsert each env var value, returning saved names."""
    saved: list[str] = []
    for var_name, var_value in values.items():
        if not var_value:
            continue
        spec = field_specs.get(var_name, {})
        encrypted_value = encryption_service.encrypt(var_value)
        env_var = ToolEnvironmentVariable(
            tenant_id=tenant_id,
            project_id=project_id,
            tool_name=tool_name,
            variable_name=var_name,
            encrypted_value=encrypted_value,
            description=spec.get("description"),
            is_required=spec.get("is_required", True),
            is_secret=spec.get("is_secret", True),
            scope=scope,
        )
        await repository.upsert(env_var)
        saved.append(var_name)
        logger.info("Saved env var: %s/%s", tool_name, var_name)
    return saved


async def _save_env_vars_impl(
    tenant_id: str,
    tool_name: str,
    values: dict[str, str],
    field_specs: dict[str, dict[str, Any]],
    scope: EnvVarScope,
    project_id: str | None,
    *,
    session_factory: Any,
    repository: ToolEnvironmentVariableRepositoryPort | None,
    encryption_service: EncryptionService,
) -> list[str]:
    """Encrypt and persist env var values using session_factory or repo."""
    if session_factory:
        from src.infrastructure.adapters.secondary.persistence.sql_tool_environment_variable_repository import (
            SqlToolEnvironmentVariableRepository,
        )

        async with session_factory() as db_session:
            repo = SqlToolEnvironmentVariableRepository(db_session)
            saved = await _upsert_env_vars_to_repo(
                repo,
                encryption_service,
                tenant_id,
                tool_name,
                values,
                field_specs,
                scope,
                project_id,
            )
            await db_session.commit()
            return saved

    if repository is not None:
        return await _upsert_env_vars_to_repo(
            repository,
            encryption_service,
            tenant_id,
            tool_name,
            values,
            field_specs,
            scope,
            project_id,
        )
    return []


def _build_env_var_request_details(
    *,
    tool_name: str,
    fields: list[dict[str, Any]],
    context: dict[str, Any] | None,
    save_to_project: bool,
    project_id: str | None,
) -> tuple[str, dict[str, Any], list[str], str]:
    """Build user-facing message and context for env var requests."""
    raw_context = dict(context or {})
    requested_names = _build_requested_names(fields)
    request_context, scope_label = _build_shared_env_var_request_context(
        raw_context=raw_context,
        tool_name=tool_name,
        requested_variables=requested_names,
        project_id=project_id if save_to_project else None,
    )
    default_message = (
        f"The tool '{tool_name}' needs environment variables: "
        f"{', '.join(requested_names) or 'unknown variables'}. "
        f"They will be saved at the {scope_label} scope."
    )
    request_message = _sanitize_request_message(raw_context.get("message")) or default_message
    return request_message, request_context, requested_names, scope_label


def _env_request_error_result(message: str) -> ToolResult:
    """Build a standardized error result for env-var request validation."""
    return ToolResult(
        output=json.dumps(
            {
                "status": "error",
                "message": message,
            }
        ),
        is_error=True,
    )


def _validate_request_env_inputs(
    *,
    tenant_id: str | None,
    project_id: str | None,
    fields: list[Any],
    context: object,
    save_to_project: bool,
    hitl_handler: Any,
    session_factory: Any,
    repository: ToolEnvironmentVariableRepositoryPort | None,
    encryption_service: EncryptionService | None,
) -> str | None:
    """Return a validation error message for request_env_var inputs, if any."""
    if not tenant_id or not fields:
        return "Invalid arguments or missing tenant context"
    if context is not None and not isinstance(context, dict):
        return "Invalid context payload"
    if hitl_handler is None or encryption_service is None:
        return "HITL handler not configured"
    if session_factory is None and repository is None:
        return "Environment variable persistence is not configured"
    if save_to_project and not project_id:
        return "Project-scoped environment variables require an active project context"
    return None


def _normalize_request_env_fields(
    fields: list[Any],
) -> tuple[list[dict[str, Any]], str | None]:
    """Normalize env-var request fields and return an error message, if any."""
    normalized_fields: list[dict[str, Any]] = []
    seen_variable_names: set[str] = set()
    for field in fields:
        if not isinstance(field, dict):
            return [], "Invalid field payload"

        normalized_variable_name = _normalize_env_var_name(field.get("variable_name"))
        if not normalized_variable_name:
            return [], "Invalid environment variable name"
        if normalized_variable_name in seen_variable_names:
            return [], "Duplicate environment variable names are not allowed"

        seen_variable_names.add(normalized_variable_name)
        normalized_field = dict(field)
        normalized_field["variable_name"] = normalized_variable_name
        normalized_fields.append(normalized_field)

    return normalized_fields, None


def _normalize_request_env_inputs(
    *,
    tenant_id: str | None,
    project_id: str | None,
    tool_name: str,
    fields: list[dict[str, Any]],
    context: dict[str, Any] | None,
    save_to_project: bool,
    hitl_handler: Any,
    session_factory: Any,
    repository: ToolEnvironmentVariableRepositoryPort | None,
    encryption_service: EncryptionService | None,
) -> tuple[str, list[dict[str, Any]]] | ToolResult:
    """Validate and normalize request_env_var inputs."""
    error_message = _validate_request_env_inputs(
        tenant_id=tenant_id,
        project_id=project_id,
        fields=fields,
        context=context,
        save_to_project=save_to_project,
        hitl_handler=hitl_handler,
        session_factory=session_factory,
        repository=repository,
        encryption_service=encryption_service,
    )

    if error_message:
        return _env_request_error_result(error_message)

    normalized_tool_name = _normalize_tool_name(tool_name)
    if not normalized_tool_name:
        return _env_request_error_result("Invalid tool name")

    normalized_fields, invalid_field_message = _normalize_request_env_fields(fields)
    if invalid_field_message:
        return _env_request_error_result(invalid_field_message)

    return normalized_tool_name, normalized_fields


# ---------------------------------------------------------------------------
# Tool 1: get_env_var_tool
# ---------------------------------------------------------------------------


@tool_define(
    name="get_env_var",
    description=(
        "Load an environment variable needed by a tool. "
        "Returns the decrypted value if found, or indicates if missing."
    ),
    parameters={
        "type": "object",
        "properties": {
            "tool_name": {
                "type": "string",
                "description": ("Name of the tool that needs the environment variable"),
            },
            "variable_name": {
                "type": "string",
                "description": "Name of the environment variable to retrieve",
            },
        },
        "required": ["tool_name", "variable_name"],
    },
    category="environment",
    tags=frozenset({"env", "config"}),
)
async def get_env_var_tool(
    ctx: ToolContext,
    *,
    tool_name: str,
    variable_name: str,
) -> ToolResult:
    """Load an environment variable value for a tool."""
    tenant_id, project_id = _resolve_tool_scope(ctx)
    session_factory = _session_factory_ref
    repository = _env_var_repo
    encryption_service = _encryption_svc
    if not tenant_id:
        return ToolResult(
            output=json.dumps(
                {
                    "status": "error",
                    "message": "Invalid arguments or missing tenant context",
                }
            ),
            is_error=True,
        )
    normalized_tool_name = _normalize_tool_name(tool_name)
    if not normalized_tool_name:
        return ToolResult(
            output=json.dumps(
                {
                    "status": "error",
                    "message": "Invalid tool name",
                }
            ),
            is_error=True,
        )
    normalized_variable_name = _normalize_env_var_name(variable_name)
    if not normalized_variable_name:
        return ToolResult(
            output=json.dumps(
                {
                    "status": "error",
                    "message": "Invalid environment variable name",
                }
            ),
            is_error=True,
        )

    try:
        env_var = await _get_env_var(
            tenant_id,
            normalized_tool_name,
            normalized_variable_name,
            project_id or None,
            session_factory=session_factory,
            repository=repository,
        )

        if env_var:
            assert encryption_service is not None
            decrypted = encryption_service.decrypt(env_var.encrypted_value)
            logger.info(
                "Retrieved env var %s/%s (secret=%s, scope=%s)",
                normalized_tool_name,
                normalized_variable_name,
                env_var.is_secret,
                env_var.scope.value,
            )
            return ToolResult(
                output=json.dumps(
                    {
                        "status": "found",
                        "variable_name": normalized_variable_name,
                        "value": decrypted,
                        "is_secret": env_var.is_secret,
                        "scope": env_var.scope.value,
                    }
                ),
            )

        logger.info("Env var not found: %s/%s", normalized_tool_name, normalized_variable_name)
        return ToolResult(
            output=json.dumps(
                {
                    "status": "not_found",
                    "variable_name": normalized_variable_name,
                    "message": (
                        f"Environment variable '{normalized_variable_name}' "
                        f"not configured for tool '{normalized_tool_name}'. "
                        "Use request_env_var to ask the user for it."
                    ),
                }
            ),
        )

    except Exception as exc:
        logger.error(
            "Error getting env var %s/%s: %s",
            normalized_tool_name,
            normalized_variable_name,
            exc,
        )
        return ToolResult(
            output=json.dumps({"status": "error", "message": str(exc)}),
            is_error=True,
        )


# ---------------------------------------------------------------------------
# Tool 2: request_env_var_tool
# ---------------------------------------------------------------------------


@tool_define(
    name="request_env_var",
    description=(
        "Request environment variables from the user when they are missing. "
        "Prompts the user to input values which are securely stored."
    ),
    parameters={
        "type": "object",
        "properties": {
            "tool_name": {
                "type": "string",
                "description": ("Name of the tool that needs the environment variables"),
            },
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "variable_name": {
                            "type": "string",
                            "description": ("Name of the environment variable"),
                        },
                        "display_name": {
                            "type": "string",
                            "description": "Human-readable name",
                        },
                        "description": {
                            "type": "string",
                            "description": "What this variable is for",
                        },
                        "placeholder": {
                            "type": "string",
                            "description": "Optional helper text shown in the HITL input",
                        },
                        "default_value": {
                            "type": "string",
                            "description": "Optional default value prefilled in the HITL input",
                        },
                        "input_type": {
                            "type": "string",
                            "enum": ["text", "password", "textarea"],
                            "default": "text",
                        },
                        "is_required": {
                            "type": "boolean",
                            "default": True,
                        },
                        "is_secret": {
                            "type": "boolean",
                            "default": True,
                        },
                    },
                    "required": ["variable_name"],
                },
                "description": ("List of env var fields to request from the user"),
            },
            "context": {
                "type": "object",
                "description": "Additional context information",
            },
            "save_to_project": {
                "type": "boolean",
                "description": ("If true, save at project level; otherwise tenant level"),
                "default": False,
            },
        },
        "required": ["tool_name", "fields"],
    },
    category="environment",
    tags=frozenset({"env", "config", "hitl"}),
)
async def request_env_var_tool(
    ctx: ToolContext,
    *,
    tool_name: str,
    fields: list[dict[str, Any]],
    context: dict[str, Any] | None = None,
    save_to_project: bool = False,
    timeout: float = 600.0,
) -> ToolResult:
    """Request environment variables from the user via HITL."""
    tenant_id, current_project_id = _resolve_tool_scope(ctx)
    save_project_id = current_project_id if save_to_project else None
    session_factory = _session_factory_ref
    repository = _env_var_repo
    encryption_service = _encryption_svc
    hitl_handler = _scope_env_var_hitl_handler(
        _hitl_handler_ref,
        tenant_id=tenant_id or "",
        project_id=current_project_id,
        conversation_id=ctx.conversation_id,
        message_id=ctx.message_id,
    )
    normalized_inputs = _normalize_request_env_inputs(
        tenant_id=tenant_id,
        project_id=current_project_id,
        tool_name=tool_name,
        fields=fields,
        context=context,
        save_to_project=save_to_project,
        hitl_handler=hitl_handler,
        session_factory=session_factory,
        repository=repository,
        encryption_service=encryption_service,
    )
    if isinstance(normalized_inputs, ToolResult):
        return normalized_inputs
    assert tenant_id is not None
    assert encryption_service is not None
    assert hitl_handler is not None
    normalized_tool_name, normalized_fields = normalized_inputs
    request_message, request_context, requested_names, scope_label = _build_env_var_request_details(
        tool_name=normalized_tool_name,
        fields=normalized_fields,
        context=context,
        save_to_project=save_to_project,
        project_id=save_project_id,
    )
    hitl_fields, field_specs = _build_hitl_env_fields(normalized_fields)
    prepared_request = PreparedEnvVarRequest(
        hitl_fields=hitl_fields,
        field_specs=field_specs,
        request_message=request_message,
        request_context=request_context,
        requested_names=requested_names,
        scope_label=scope_label,
    )
    request_id = _build_env_var_request_id(
        tenant_id=tenant_id,
        project_id=current_project_id,
        conversation_id=ctx.conversation_id,
        message_id=ctx.message_id,
        call_id=ctx.call_id,
        tool_name=normalized_tool_name,
        fields=prepared_request.hitl_fields,
        message=prepared_request.request_message,
        context=prepared_request.request_context,
        allow_save=True,
    )

    return await _request_env_var_impl(
        tenant_id=tenant_id,
        project_id=save_project_id,
        tool_name=normalized_tool_name,
        timeout=timeout,
        hitl_handler=hitl_handler,
        session_factory=session_factory,
        repository=repository,
        encryption_service=encryption_service,
        request_id=request_id,
        prepared_request=prepared_request,
    )


def _tool_result_payload(payload: dict[str, Any], *, is_error: bool = False) -> ToolResult:
    """Build a serialized ToolResult payload."""
    return ToolResult(output=json.dumps(payload), is_error=is_error)


def _requested_env_var_text(prepared_request: PreparedEnvVarRequest) -> str:
    """Return readable requested variable names for user-facing messages."""
    return ", ".join(prepared_request.requested_names) or "the requested variables"


def _resolve_env_var_tool_response(
    response: object,
    prepared_request: PreparedEnvVarRequest,
) -> dict[str, str] | ToolResult:
    """Normalize the HITL response into env-var values or a terminal ToolResult."""
    if not isinstance(response, dict):
        return _tool_result_payload(
            {
                "status": "error",
                "message": "Invalid environment variable values returned from HITL",
            },
            is_error=True,
        )

    requested_text = _requested_env_var_text(prepared_request)
    if response.get("timeout"):
        return _tool_result_payload(
            {
                "status": "timeout",
                "message": (
                    "User did not provide the requested "
                    f"environment variables in time: {requested_text}"
                ),
            }
        )

    if response.get("cancelled"):
        return _tool_result_payload(
            {
                "status": "cancelled",
                "message": (
                    "User did not provide the requested " f"environment variables: {requested_text}"
                ),
            }
        )

    raw_values = response.get("values", response)
    return _normalize_hitl_env_values(raw_values, prepared_request.field_specs)


async def _request_env_var_impl(
    *,
    tenant_id: str,
    project_id: str | None,
    tool_name: str,
    timeout: float,
    hitl_handler: RayHITLHandler,
    session_factory: Any,
    repository: ToolEnvironmentVariableRepositoryPort | None,
    encryption_service: EncryptionService,
    request_id: str,
    prepared_request: PreparedEnvVarRequest,
) -> ToolResult:
    """Inner implementation for request_env_var_tool (split for complexity)."""
    logger.info(
        "Requesting env vars for tool=%s: %s",
        tool_name,
        [fld["name"] for fld in prepared_request.hitl_fields],
    )

    try:
        response = await hitl_handler.request_env_vars(
            tool_name=tool_name,
            fields=prepared_request.hitl_fields,
            message=prepared_request.request_message,
            context=prepared_request.request_context,
            timeout_seconds=timeout,
            allow_save=True,
            save_project_id=project_id,
            request_id=request_id,
        )

        normalized_values = _resolve_env_var_tool_response(response, prepared_request)
        if isinstance(normalized_values, ToolResult):
            return normalized_values

        scope = EnvVarScope.PROJECT if project_id else EnvVarScope.TENANT
        saved = await _save_env_vars_impl(
            tenant_id,
            tool_name,
            normalized_values,
            prepared_request.field_specs,
            scope,
            project_id,
            session_factory=session_factory,
            repository=repository,
            encryption_service=encryption_service,
        )

        return ToolResult(
            output=json.dumps(
                {
                    "status": "success",
                    "saved_variables": saved,
                    "scope": scope.value,
                    "message": (
                        f"Saved {', '.join(saved) or 'environment variables'} "
                        f"for '{tool_name}' at the {prepared_request.scope_label} scope"
                    ),
                }
            ),
        )

    except TimeoutError:
        logger.warning("Env var request for %s timed out", tool_name)
        return _tool_result_payload(
            {
                "status": "timeout",
                "message": (
                    "User did not provide the requested "
                    f"environment variables in time: {_requested_env_var_text(prepared_request)}"
                ),
            }
        )

    except Exception as exc:
        logger.error(
            "Error in env var request for %s: %s",
            tool_name,
            exc,
        )
        return _tool_result_payload({"status": "error", "message": str(exc)}, is_error=True)


def _normalize_hitl_env_values(
    values: object,
    field_specs: dict[str, dict[str, Any]],
) -> dict[str, str] | ToolResult:
    """Validate and normalize HITL-provided env-var values before persistence."""
    if not isinstance(values, dict):
        return ToolResult(
            output=json.dumps(
                {
                    "status": "error",
                    "message": "Invalid environment variable values returned from HITL",
                }
            ),
            is_error=True,
        )

    normalized_values: dict[str, str] = {}
    for name, raw_value in values.items():
        if not isinstance(raw_value, str):
            return ToolResult(
                output=json.dumps(
                    {
                        "status": "error",
                        "message": "Invalid environment variable values returned from HITL",
                    }
                ),
                is_error=True,
            )
        normalized_value = raw_value.strip()
        if not normalized_value:
            continue
        normalized_values[name] = normalized_value

    unexpected_names = [
        name
        for name in normalized_values
        if _normalize_env_var_name(name) != name or name not in field_specs
    ]
    if unexpected_names:
        return ToolResult(
            output=json.dumps(
                {
                    "status": "error",
                    "message": "Invalid environment variable names returned from HITL",
                }
            ),
            is_error=True,
        )

    missing_required = [
        name
        for name, spec in field_specs.items()
        if spec.get("is_required", True) and not normalized_values.get(name)
    ]
    if missing_required:
        return ToolResult(
            output=json.dumps(
                {
                    "status": "error",
                    "message": (
                        "Missing required environment variables: "
                        f"{', '.join(sorted(missing_required))}"
                    ),
                }
            ),
            is_error=True,
        )

    return normalized_values


# ---------------------------------------------------------------------------
# Tool 3: check_env_vars_tool
# ---------------------------------------------------------------------------


@tool_define(
    name="check_env_vars",
    description=(
        "Check if required environment variables are configured for a tool. "
        "Returns which variables are available and which are missing."
    ),
    parameters={
        "type": "object",
        "properties": {
            "tool_name": {
                "type": "string",
                "description": ("Name of the tool to check environment variables for"),
            },
            "required_vars": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of required variable names to check",
            },
        },
        "required": ["tool_name", "required_vars"],
    },
    category="environment",
    tags=frozenset({"env", "config"}),
)
async def check_env_vars_tool(
    ctx: ToolContext,
    *,
    tool_name: str,
    required_vars: list[str],
) -> ToolResult:
    """Check if required environment variables are available for a tool."""
    tenant_id, project_id = _resolve_tool_scope(ctx)
    session_factory = _session_factory_ref
    repository = _env_var_repo
    if not tenant_id:
        return ToolResult(
            output=json.dumps(
                {
                    "status": "error",
                    "message": "Invalid arguments or missing tenant context",
                }
            ),
            is_error=True,
        )
    normalized_tool_name = _normalize_tool_name(tool_name)
    if not normalized_tool_name:
        return ToolResult(
            output=json.dumps(
                {
                    "status": "error",
                    "message": "Invalid tool name",
                }
            ),
            is_error=True,
        )
    normalized_required_vars = [_normalize_env_var_name(var) for var in required_vars]
    if not normalized_required_vars or any(not var for var in normalized_required_vars):
        return ToolResult(
            output=json.dumps(
                {
                    "status": "error",
                    "message": "Invalid environment variable name",
                }
            ),
            is_error=True,
        )

    try:
        env_vars = await _get_env_vars_for_tool(
            tenant_id,
            normalized_tool_name,
            project_id or None,
            session_factory=session_factory,
            repository=repository,
        )
        configured = {ev.variable_name for ev in env_vars}
        available = [v for v in normalized_required_vars if v in configured]
        missing = [v for v in normalized_required_vars if v not in configured]

        return ToolResult(
            output=json.dumps(
                {
                    "status": "checked",
                    "tool_name": normalized_tool_name,
                    "available": available,
                    "missing": missing,
                    "all_available": len(missing) == 0,
                    "message": (
                        "All required environment variables are configured"
                        if not missing
                        else (
                            f"Missing environment variables for '{normalized_tool_name}': "
                            f"{', '.join(missing)}. Use request_env_var to ask for them."
                        )
                    ),
                }
            ),
        )

    except Exception as exc:
        logger.error(
            "Error checking env vars for %s: %s",
            normalized_tool_name,
            exc,
        )
        return ToolResult(
            output=json.dumps({"status": "error", "message": str(exc)}),
            is_error=True,
        )
