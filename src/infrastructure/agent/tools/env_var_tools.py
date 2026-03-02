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
from collections.abc import Callable
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


# ---------------------------------------------------------------------------
# Helper: get a usable repository (session_factory path or injected repo)
# ---------------------------------------------------------------------------


async def _get_env_var(
    tenant_id: str,
    tool_name: str,
    variable_name: str,
    project_id: str | None,
) -> ToolEnvironmentVariable | None:
    """Retrieve a single env var via session_factory or injected repo."""
    if _session_factory_ref:
        from src.infrastructure.adapters.secondary.persistence.sql_tool_environment_variable_repository import (
            SqlToolEnvironmentVariableRepository,
        )

        async with _session_factory_ref() as db_session:
            repo = SqlToolEnvironmentVariableRepository(db_session)
            return await repo.get(
                tenant_id=tenant_id,
                tool_name=tool_name,
                variable_name=variable_name,
                project_id=project_id,
            )

    if _env_var_repo is None:
        return None
    return await _env_var_repo.get(
        tenant_id=tenant_id,
        tool_name=tool_name,
        variable_name=variable_name,
        project_id=project_id,
    )


async def _get_env_vars_for_tool(
    tenant_id: str,
    tool_name: str,
    project_id: str | None,
) -> list[ToolEnvironmentVariable]:
    """Retrieve all env vars for a tool via session_factory or injected repo."""
    if _session_factory_ref:
        from src.infrastructure.adapters.secondary.persistence.sql_tool_environment_variable_repository import (
            SqlToolEnvironmentVariableRepository,
        )

        async with _session_factory_ref() as db_session:
            repo = SqlToolEnvironmentVariableRepository(db_session)
            return await repo.get_for_tool(
                tenant_id=tenant_id,
                tool_name=tool_name,
                project_id=project_id,
            )

    if _env_var_repo is None:
        return []
    return await _env_var_repo.get_for_tool(
        tenant_id=tenant_id,
        tool_name=tool_name,
        project_id=project_id,
    )


# ---------------------------------------------------------------------------
# Helper: save env vars (used by request_env_var_tool)
# ---------------------------------------------------------------------------


async def _upsert_env_vars_to_repo(
    repository: Any,
    tenant_id: str,
    tool_name: str,
    values: dict[str, str],
    field_specs: dict[str, dict[str, Any]],
    scope: EnvVarScope,
    project_id: str | None,
) -> list[str]:
    """Encrypt and upsert each env var value, returning saved names."""
    assert _encryption_svc is not None, "encryption_service not configured"
    saved: list[str] = []
    for var_name, var_value in values.items():
        if not var_value:
            continue
        spec = field_specs.get(var_name, {})
        encrypted_value = _encryption_svc.encrypt(var_value)
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
) -> list[str]:
    """Encrypt and persist env var values using session_factory or repo."""
    if _session_factory_ref:
        from src.infrastructure.adapters.secondary.persistence.sql_tool_environment_variable_repository import (
            SqlToolEnvironmentVariableRepository,
        )

        async with _session_factory_ref() as db_session:
            repo = SqlToolEnvironmentVariableRepository(db_session)
            saved = await _upsert_env_vars_to_repo(
                repo, tenant_id, tool_name, values,
                field_specs, scope, project_id,
            )
            await db_session.commit()
            return saved

    if _env_var_repo is not None:
        return await _upsert_env_vars_to_repo(
            _env_var_repo, tenant_id, tool_name, values,
            field_specs, scope, project_id,
        )
    return []


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
                "description": (
                    "Name of the tool that needs the environment variable"
                ),
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
    _ = ctx  # unused — no events or permissions needed
    tenant_id = _tenant_id_ref
    if not tenant_id:
        return ToolResult(
            output=json.dumps({
                "status": "error",
                "message": "Invalid arguments or missing tenant context",
            }),
            is_error=True,
        )

    try:
        env_var = await _get_env_var(
            tenant_id, tool_name, variable_name, _project_id_ref,
        )

        if env_var:
            assert _encryption_svc is not None
            decrypted = _encryption_svc.decrypt(env_var.encrypted_value)
            log_val = "***" if env_var.is_secret else decrypted[:20] + "..."
            logger.info(
                "Retrieved env var %s/%s: %s",
                tool_name, variable_name, log_val,
            )
            return ToolResult(
                output=json.dumps({
                    "status": "found",
                    "variable_name": variable_name,
                    "value": decrypted,
                    "is_secret": env_var.is_secret,
                    "scope": env_var.scope.value,
                }),
            )

        logger.info("Env var not found: %s/%s", tool_name, variable_name)
        return ToolResult(
            output=json.dumps({
                "status": "not_found",
                "variable_name": variable_name,
                "message": (
                    f"Environment variable '{variable_name}' "
                    f"not configured for tool '{tool_name}'"
                ),
            }),
        )

    except Exception as exc:
        logger.error(
            "Error getting env var %s/%s: %s", tool_name, variable_name, exc,
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
                "description": (
                    "Name of the tool that needs the environment variables"
                ),
            },
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "variable_name": {
                            "type": "string",
                            "description": (
                                "Name of the environment variable"
                            ),
                        },
                        "display_name": {
                            "type": "string",
                            "description": "Human-readable name",
                        },
                        "description": {
                            "type": "string",
                            "description": "What this variable is for",
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
                "description": (
                    "List of env var fields to request from the user"
                ),
            },
            "context": {
                "type": "object",
                "description": "Additional context information",
            },
            "save_to_project": {
                "type": "boolean",
                "description": (
                    "If true, save at project level; otherwise tenant level"
                ),
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
    _ = ctx  # unused — HITL handler manages SSE events directly
    tenant_id = _tenant_id_ref
    if not tenant_id or not fields:
        return ToolResult(
            output=json.dumps({
                "status": "error",
                "message": "Invalid arguments or missing tenant context",
            }),
            is_error=True,
        )

    if _hitl_handler_ref is None:
        return ToolResult(
            output=json.dumps({
                "status": "error",
                "message": "HITL handler not configured",
            }),
            is_error=True,
        )

    return await _request_env_var_impl(
        tenant_id=tenant_id,
        tool_name=tool_name,
        fields=fields,
        context=context,
        save_to_project=save_to_project,
        timeout=timeout,
    )


async def _request_env_var_impl(
    *,
    tenant_id: str,
    tool_name: str,
    fields: list[dict[str, Any]],
    context: dict[str, Any] | None,
    save_to_project: bool,
    timeout: float,
) -> ToolResult:
    """Inner implementation for request_env_var_tool (split for complexity)."""
    assert _hitl_handler_ref is not None

    # Convert fields to HITL format
    hitl_fields: list[dict[str, Any]] = []
    field_specs: dict[str, dict[str, Any]] = {}
    for f in fields:
        input_type = f.get("input_type", "text")
        is_secret = f.get("is_secret", True)
        if input_type == "password" or is_secret:
            input_type = "password"

        hitl_fields.append({
            "name": f["variable_name"],
            "label": f.get("display_name", f["variable_name"]),
            "description": f.get("description"),
            "required": f.get("is_required", True),
            "secret": is_secret,
            "input_type": input_type,
            "default_value": f.get("default_value"),
            "placeholder": f.get("placeholder"),
        })
        field_specs[f["variable_name"]] = {
            "description": f.get("description"),
            "is_required": f.get("is_required", True),
            "is_secret": is_secret,
        }

    logger.info(
        "Requesting env vars for tool=%s: %s",
        tool_name, [fld["name"] for fld in hitl_fields],
    )

    try:
        values = await _hitl_handler_ref.request_env_vars(
            tool_name=tool_name,
            fields=hitl_fields,
            message=context.get("message") if context else None,
            timeout_seconds=timeout,
            allow_save=True,
        )

        if not values:
            return ToolResult(
                output=json.dumps({
                    "status": "cancelled",
                    "message": (
                        "User did not provide the requested "
                        "environment variables"
                    ),
                }),
            )

        scope = (
            EnvVarScope.PROJECT
            if save_to_project and _project_id_ref
            else EnvVarScope.TENANT
        )
        proj_id = _project_id_ref if save_to_project else None

        assert _tenant_id_ref is not None
        saved = await _save_env_vars_impl(
            _tenant_id_ref, tool_name, values,
            field_specs, scope, proj_id,
        )

        return ToolResult(
            output=json.dumps({
                "status": "success",
                "saved_variables": saved,
                "scope": scope.value,
            }),
        )

    except TimeoutError:
        logger.warning("Env var request for %s timed out", tool_name)
        return ToolResult(
            output=json.dumps({
                "status": "timeout",
                "message": (
                    "User did not provide the requested "
                    "environment variables in time"
                ),
            }),
        )

    except Exception as exc:
        logger.error(
            "Error in env var request for %s: %s", tool_name, exc,
        )
        return ToolResult(
            output=json.dumps({"status": "error", "message": str(exc)}),
            is_error=True,
        )


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
                "description": (
                    "Name of the tool to check environment variables for"
                ),
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
    _ = ctx  # unused — read-only check, no events or permissions
    tenant_id = _tenant_id_ref
    if not tenant_id:
        return ToolResult(
            output=json.dumps({
                "status": "error",
                "message": "Invalid arguments or missing tenant context",
            }),
            is_error=True,
        )

    try:
        env_vars = await _get_env_vars_for_tool(
            tenant_id, tool_name, _project_id_ref,
        )
        configured = {ev.variable_name for ev in env_vars}
        available = [v for v in required_vars if v in configured]
        missing = [v for v in required_vars if v not in configured]

        return ToolResult(
            output=json.dumps({
                "status": "checked",
                "tool_name": tool_name,
                "available": available,
                "missing": missing,
                "all_available": len(missing) == 0,
            }),
        )

    except Exception as exc:
        logger.error(
            "Error checking env vars for %s: %s", tool_name, exc,
        )
        return ToolResult(
            output=json.dumps({"status": "error", "message": str(exc)}),
            is_error=True,
        )
