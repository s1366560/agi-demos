"""Agent-facing bridge to the MemStack HTTP API surface."""

from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)

_HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
_PATH_PARAM_RE = re.compile(r"{([^{}]+)}")
_API_KEY_RE = re.compile(r"\bms_sk_[A-Za-z0-9_-]{8,}\b")
_AUTH_VALUE_RE = re.compile(r"\b(Bearer|Token)\s+([A-Za-z0-9._~+/=-]{8,})", re.IGNORECASE)
_SENSITIVE_KEYS = {
    "authorization",
    "api_key",
    "api-key",
    "access_token",
    "refresh_token",
    "token",
    "password",
    "secret",
}


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str, sort_keys=True)


def _redact_text(value: str) -> str:
    redacted = _AUTH_VALUE_RE.sub(lambda match: f"{match.group(1)} [REDACTED]", value)
    return _API_KEY_RE.sub("ms_sk_[REDACTED]", redacted)


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in _SENSITIVE_KEYS:
                result[key_text] = "[REDACTED]"
            else:
                result[key_text] = _redact_value(item)
        return result
    return value


@lru_cache(maxsize=1)
def _get_openapi_schema() -> dict[str, Any]:
    from src.infrastructure.adapters.primary.web.main import app

    schema = app.openapi()
    return schema if isinstance(schema, dict) else {}


def _operation_tags(operation: dict[str, Any]) -> list[str]:
    tags = operation.get("tags")
    if not isinstance(tags, list):
        return []
    return [str(tag) for tag in tags]


def _operation_parameters(operation: dict[str, Any]) -> list[dict[str, Any]]:
    raw_params = operation.get("parameters")
    if not isinstance(raw_params, list):
        return []

    parameters: list[dict[str, Any]] = []
    for param in raw_params:
        if not isinstance(param, dict):
            continue
        parameters.append(
            {
                "name": str(param.get("name", "")),
                "in": str(param.get("in", "")),
                "required": bool(param.get("required", False)),
                "description": param.get("description"),
                "schema": param.get("schema"),
            }
        )
    return parameters


def _public_operation(entry: dict[str, Any], *, include_schema: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "operation_id": entry["operation_id"],
        "method": entry["method"],
        "path_template": entry["path_template"],
        "summary": entry["summary"],
        "tags": entry["tags"],
        "has_request_body": entry["has_request_body"],
        "parameters": entry["parameters"],
    }
    if include_schema:
        result["request_body"] = entry["request_body"]
        result["description"] = entry["description"]
    return result


def _operation_catalog() -> list[dict[str, Any]]:
    schema = _get_openapi_schema()
    paths = schema.get("paths", {})
    if not isinstance(paths, dict):
        return []

    catalog: list[dict[str, Any]] = []
    for path_template, path_item in sorted(paths.items()):
        if not isinstance(path_template, str) or not path_template.startswith("/api/"):
            continue
        if not isinstance(path_item, dict):
            continue

        for method, operation in path_item.items():
            method_name = str(method).lower()
            if method_name not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            operation_id = str(
                operation.get("operationId")
                or f"{method_name}:{path_template}"
            )
            catalog.append(
                {
                    "operation_id": operation_id,
                    "method": method_name.upper(),
                    "path_template": path_template,
                    "summary": str(operation.get("summary") or "").strip(),
                    "description": operation.get("description"),
                    "tags": _operation_tags(operation),
                    "parameters": _operation_parameters(operation),
                    "has_request_body": "requestBody" in operation,
                    "request_body": operation.get("requestBody"),
                }
            )
    return catalog


def _catalog_by_operation() -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for entry in _operation_catalog():
        by_id.setdefault(str(entry["operation_id"]), entry)
    return by_id


def _clamp_limit(limit: int | None) -> int:
    if limit is None:
        return 50
    return max(1, min(int(limit), 200))


def _filter_operations(
    *,
    search: str | None,
    tag: str | None,
    limit: int | None,
) -> list[dict[str, Any]]:
    query = (search or "").strip().lower()
    tag_query = (tag or "").strip().lower()
    filtered: list[dict[str, Any]] = []

    for entry in _operation_catalog():
        tags = [str(item).lower() for item in entry["tags"]]
        if tag_query and tag_query not in tags:
            continue
        haystack = " ".join(
            [
                str(entry["operation_id"]),
                str(entry["method"]),
                str(entry["path_template"]),
                str(entry["summary"]),
                " ".join(tags),
            ]
        ).lower()
        if query and query not in haystack:
            continue
        filtered.append(_public_operation(entry))

    return filtered[: _clamp_limit(limit)]


def _base_url() -> str:
    configured = (
        os.getenv("MEMSTACK_INTERNAL_API_BASE_URL")
        or os.getenv("MEMSTACK_API_BASE_URL")
        or ""
    ).strip()
    if configured:
        return configured.rstrip("/")

    from src.configuration.config import get_settings

    settings = get_settings()
    return f"http://127.0.0.1:{settings.api_port}"


def _build_url(path: str) -> str:
    base = _base_url().rstrip("/")
    parsed = urlsplit(base)
    base_path = parsed.path.rstrip("/")
    request_path = path if path.startswith("/") else f"/{path}"
    if base_path and request_path.startswith(f"{base_path}/"):
        request_path = request_path[len(base_path) :]
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            f"{base_path}{request_path}",
            "",
            "",
        )
    )


def _auth_header_value(token: str) -> str:
    value = token.strip()
    if value.lower().startswith(("bearer ", "token ")):
        return value
    return f"Bearer {value}"


def _auth_token(ctx: ToolContext) -> str | None:
    for candidate in (
        ctx.api_auth_token,
        os.getenv("MEMSTACK_AGENT_API_KEY"),
        os.getenv("MEMSTACK_API_KEY"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _render_path(
    path_template: str,
    path_params: dict[str, Any] | None,
) -> tuple[str | None, ToolResult | None]:
    params = path_params or {}
    missing = [
        name
        for name in _PATH_PARAM_RE.findall(path_template)
        if name not in params or params[name] is None
    ]
    if missing:
        return None, ToolResult(
            output=_json({"error": "missing_path_params", "missing": missing}),
            title="System API request failed",
            is_error=True,
        )

    def _replace(match: re.Match[str]) -> str:
        value = str(params[match.group(1)])
        return quote(value, safe="")

    return _PATH_PARAM_RE.sub(_replace, path_template), None


def _mapping_or_error(value: Any, name: str) -> tuple[dict[str, Any] | None, ToolResult | None]:
    if value is None:
        return None, None
    if isinstance(value, dict):
        return value, None
    return None, ToolResult(
        output=_json({"error": f"{name}_must_be_object"}),
        title="System API request failed",
        is_error=True,
    )


async def _request_operation(
    ctx: ToolContext,
    *,
    operation_id: str,
    path_params: dict[str, Any] | None,
    query: dict[str, Any] | None,
    body: Any,
    timeout_seconds: float | None,
) -> ToolResult:
    operation = _catalog_by_operation().get(operation_id)
    if operation is None:
        return ToolResult(
            output=_json({"error": "unknown_operation_id", "operation_id": operation_id}),
            title="System API request failed",
            is_error=True,
        )

    rendered_path, path_error = _render_path(str(operation["path_template"]), path_params)
    if path_error is not None:
        return path_error

    token = _auth_token(ctx)
    if not token:
        return ToolResult(
            output=_json(
                {
                    "error": "api_auth_unavailable",
                    "message": (
                        "Current-user API authentication is unavailable. "
                        "Use an authenticated chat session or configure MEMSTACK_AGENT_API_KEY."
                    ),
                }
            ),
            title="System API request failed",
            is_error=True,
        )

    request_timeout = max(1.0, min(float(timeout_seconds or 30.0), 120.0))
    headers = {
        "Authorization": _auth_header_value(token),
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(
            timeout=request_timeout,
            follow_redirects=False,
        ) as client:
            response = await ctx.race(
                client.request(
                    str(operation["method"]),
                    _build_url(rendered_path or ""),
                    headers=headers,
                    params=query,
                    json=body if body is not None else None,
                ),
                timeout=request_timeout + 1.0,
            )
    except Exception as exc:
        logger.warning("system_api request failed: %s", exc)
        return ToolResult(
            output=_json(
                _redact_value(
                    {
                        "error": "request_failed",
                        "operation_id": operation_id,
                        "message": str(exc),
                    }
                )
            ),
            title="System API request failed",
            is_error=True,
        )

    try:
        response_body: Any = response.json() if response.content else None
    except ValueError:
        response_body = response.text[:8000]

    payload = _redact_value(
        {
            "operation_id": operation_id,
            "method": operation["method"],
            "path": rendered_path,
            "status_code": response.status_code,
            "ok": 200 <= response.status_code < 400,
            "response": response_body,
        }
    )
    return ToolResult(
        output=_json(payload),
        title=f"System API {operation['method']} {rendered_path}",
        metadata={"status_code": response.status_code, "operation_id": operation_id},
        is_error=not bool(payload["ok"]),
    )


@tool_define(
    name="system_api",
    description=(
        "List, describe, or call MemStack HTTP API operations using current-user API auth. "
        "Use this when a capability exists as an application API but not as a dedicated tool."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "describe", "request"],
                "description": "Operation to perform.",
            },
            "operation_id": {
                "type": "string",
                "description": "OpenAPI operationId for describe/request.",
            },
            "search": {
                "type": "string",
                "description": "Optional text filter for list.",
            },
            "tag": {
                "type": "string",
                "description": "Optional OpenAPI tag filter for list.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum operations to return for list (1-200).",
                "default": 50,
            },
            "path_params": {
                "type": "object",
                "description": "Values for path template placeholders.",
                "additionalProperties": True,
            },
            "query": {
                "type": "object",
                "description": "Query parameters for request.",
                "additionalProperties": True,
            },
            "body": {
                "description": "JSON request body for request actions.",
            },
            "timeout_seconds": {
                "type": "number",
                "description": "Request timeout in seconds (1-120).",
                "default": 30,
            },
        },
        "required": ["action"],
    },
    permission="system_api",
    category="system",
)
async def system_api_tool(  # noqa: PLR0911
    ctx: ToolContext,
    *,
    action: str,
    operation_id: str | None = None,
    search: str | None = None,
    tag: str | None = None,
    limit: int | None = 50,
    path_params: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
    body: Any | None = None,
    timeout_seconds: float | None = 30.0,
) -> ToolResult:
    """List, describe, or invoke a MemStack API operation."""
    if action == "list":
        operations = _filter_operations(search=search, tag=tag, limit=limit)
        payload = {
            "total_operations": len(_operation_catalog()),
            "returned_operations": len(operations),
            "operations": operations,
        }
        return ToolResult(output=_json(payload), title="System API operations")

    if not operation_id:
        return ToolResult(
            output=_json({"error": "operation_id_required", "action": action}),
            title="System API failed",
            is_error=True,
        )

    if action == "describe":
        operation = _catalog_by_operation().get(operation_id)
        if operation is None:
            return ToolResult(
                output=_json({"error": "unknown_operation_id", "operation_id": operation_id}),
                title="System API operation not found",
                is_error=True,
            )
        return ToolResult(
            output=_json(_public_operation(operation, include_schema=True)),
            title=f"System API operation {operation_id}",
        )

    if action == "request":
        checked_path_params, path_params_error = _mapping_or_error(path_params, "path_params")
        if path_params_error is not None:
            return path_params_error
        checked_query, query_error = _mapping_or_error(query, "query")
        if query_error is not None:
            return query_error
        return await _request_operation(
            ctx,
            operation_id=operation_id,
            path_params=checked_path_params,
            query=checked_query,
            body=body,
            timeout_seconds=timeout_seconds,
        )

    return ToolResult(
        output=_json(
            {
                "error": "unknown_action",
                "action": action,
                "allowed_actions": ["list", "describe", "request"],
            }
        ),
        title="System API failed",
        is_error=True,
    )
