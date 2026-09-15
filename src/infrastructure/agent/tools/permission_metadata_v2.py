"""Resolve effects from trusted tool definitions and structured call arguments."""

from __future__ import annotations

from typing import Any

from src.infrastructure.plugins.v2.runtime import RuntimeV2Error


def resolve_tool_permission_v2(tool: object, arguments: dict[str, Any]) -> str | None:
    resolver = getattr(tool, "permission_resolver", None)
    try:
        permission = (
            resolver(arguments) if callable(resolver) else getattr(tool, "permission", None)
        )
    except Exception as exc:
        raise RuntimeV2Error(
            "tool_permission_metadata_invalid", "Tool permission metadata is invalid"
        ) from exc
    if (resolver is not None and not callable(resolver)) or (
        permission is not None and not isinstance(permission, str)
    ):
        raise RuntimeV2Error(
            "tool_permission_metadata_invalid", "Tool permission metadata is invalid"
        )
    return permission
