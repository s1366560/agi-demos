"""Mutation guard utilities for self-modifying tool flows."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_MUTATING_TOOL_NAMES = {
    "write",
    "edit",
    "apply_patch",
    "bash",
    "exec",
    "register_mcp_server",
    "skill_installer",
    "skill_sync",
    "plugin_manager",
}

_READ_ONLY_ACTIONS = {
    "get",
    "list",
    "read",
    "status",
    "show",
    "fetch",
    "search",
    "query",
    "view",
    "poll",
    "check",
    "probe",
}

_PLUGIN_MANAGER_MUTATING_ACTIONS = {
    "install",
    "enable",
    "disable",
    "reload",
    "uninstall",
}


def is_mutating_tool_call(tool_name: str, args: Mapping[str, Any] | None = None) -> bool:
    """Return True when a tool invocation can mutate runtime or persisted state."""
    normalized_tool = (tool_name or "").strip().lower()
    if not normalized_tool:
        return False
    if normalized_tool in {"write", "edit", "apply_patch", "bash", "exec"}:
        return True
    if normalized_tool in {"register_mcp_server", "skill_installer", "skill_sync"}:
        return True
    if normalized_tool == "plugin_manager":
        action = _normalize_action((args or {}).get("action"))
        return action in _PLUGIN_MANAGER_MUTATING_ACTIONS
    if normalized_tool in _MUTATING_TOOL_NAMES:
        action = _normalize_action((args or {}).get("action"))
        return action is None or action not in _READ_ONLY_ACTIONS
    return False


def build_mutation_fingerprint(
    tool_name: str,
    args: Mapping[str, Any] | None = None,
    *,
    meta: str | None = None,
) -> str | None:
    """Build a stable fingerprint for mutation deduplication and audit logs."""
    payload = dict(args or {})
    if not is_mutating_tool_call(tool_name, payload):
        return None

    normalized_tool = (tool_name or "").strip().lower()
    action = _normalize_action(payload.get("action"))
    parts = [f"tool={normalized_tool}"]
    if action:
        parts.append(f"action={action}")

    has_stable_target = False
    for key in (
        "plugin_name",
        "requirement",
        "tenant_id",
        "project_id",
        "path",
        "server_name",
        "name",
    ):
        value = _normalize_fingerprint_value(payload.get(key))
        if value:
            parts.append(f"{key}={value}")
            has_stable_target = True

    normalized_meta = _normalize_fingerprint_value(meta)
    if normalized_meta and not has_stable_target:
        parts.append(f"meta={normalized_meta}")

    return "|".join(parts)


def _normalize_action(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace("-", "_")
    return normalized or None


def _normalize_fingerprint_value(value: Any) -> str | None:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized.lower() if normalized else None
    if isinstance(value, (int, float, bool)):
        return str(value).lower()
    return None
