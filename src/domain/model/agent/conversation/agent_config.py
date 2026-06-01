"""Helpers for conversation-scoped agent configuration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SELECTED_AGENT_ID_KEY = "selected_agent_id"
LEGACY_AGENT_DEFINITION_ID_KEY = "agent_definition_id"


def selected_agent_id_from_config(agent_config: Mapping[str, Any] | None) -> str | None:
    """Return the canonical selected agent id, accepting the legacy alias."""
    if not isinstance(agent_config, Mapping):
        return None
    return _non_empty_string(agent_config.get(SELECTED_AGENT_ID_KEY)) or _non_empty_string(
        agent_config.get(LEGACY_AGENT_DEFINITION_ID_KEY)
    )


def normalize_agent_config(agent_config: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a copy with ``selected_agent_id`` canonicalized and legacy alias removed."""
    if not isinstance(agent_config, Mapping):
        return {}
    normalized = dict(agent_config)
    normalized.pop(LEGACY_AGENT_DEFINITION_ID_KEY, None)
    selected_agent_id = selected_agent_id_from_config(agent_config)
    if selected_agent_id:
        normalized[SELECTED_AGENT_ID_KEY] = selected_agent_id
    else:
        normalized.pop(SELECTED_AGENT_ID_KEY, None)
    return normalized


def _non_empty_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
