# pyright: reportUninitializedInstanceVariable=false
"""Pure helpers for parsing workspace runtime context + bindings.

Extracted from ``react_agent.py`` (PR-7a phase 2). Every function here is
referentially transparent: it consumes only its arguments and module-level
constants, and produces a value with no side effects beyond the shared
``logger.warning`` call on JSON parse failures.

The class methods on :class:`ReActAgent` delegate here so that test fixtures
which patch ``ReActAgent._workspace_*`` keep working unchanged.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any

from src.infrastructure.agent.workspace.runtime_role_contract import (
    WORKSPACE_TOOL_MODE_KEY,
    WORKSPACE_TOOL_MODE_TASK_LEDGER_ONLY,
    WORKSPACE_TURN_TYPE_KEY,
    WORKSPACE_TURN_TYPE_LEADER_REPLAN,
)

logger = logging.getLogger(__name__)


def workspace_runtime_context(
    conversation_context: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    """Return hidden workspace worker app context injected as system metadata."""
    for message in reversed(conversation_context):
        if message.get("role") != "system":
            continue
        content = message.get("content")
        if not isinstance(content, str) or "workspace_worker_runtime" not in content:
            continue
        json_start = content.find("{")
        if json_start < 0:
            continue
        try:
            payload = json.loads(content[json_start:])
        except json.JSONDecodeError:
            logger.warning(
                "[ReActAgent] Failed to parse workspace runtime app context",
                exc_info=True,
            )
            continue
        if (
            isinstance(payload, Mapping)
            and payload.get("context_type") == "workspace_worker_runtime"
        ):
            return payload
    return None


def is_workspace_leader_replan_context(payload: Mapping[str, Any] | None) -> bool:
    """Detect task-ledger-only leader remediation turns from structured app context."""
    if not isinstance(payload, Mapping):
        return False
    return (
        payload.get(WORKSPACE_TURN_TYPE_KEY) == WORKSPACE_TURN_TYPE_LEADER_REPLAN
        or payload.get(WORKSPACE_TOOL_MODE_KEY) == WORKSPACE_TOOL_MODE_TASK_LEDGER_ONLY
    )


def has_workspace_runtime_context(
    conversation_context: Sequence[Mapping[str, Any]],
) -> bool:
    """Detect hidden workspace worker app context injected as system metadata."""
    return workspace_runtime_context(conversation_context) is not None


def normalize_workspace_binding(raw: Mapping[str, Any] | None) -> dict[str, str] | None:
    if not isinstance(raw, Mapping):
        return None
    binding = {
        str(key): str(value).strip()
        for key, value in raw.items()
        if isinstance(key, str) and value is not None and str(value).strip()
    }
    if not binding.get("workspace_id"):
        return None
    return binding


def workspace_binding_from_context(
    conversation_context: Sequence[Mapping[str, Any]],
) -> dict[str, str] | None:
    payload = workspace_runtime_context(conversation_context)
    raw_binding = payload.get("workspace_binding") if isinstance(payload, Mapping) else None
    return normalize_workspace_binding(raw_binding)


def workspace_binding_from_text(text: str | None) -> dict[str, str] | None:
    """Parse the structural workspace binding block from worker task briefs."""
    if not isinstance(text, str) or "[workspace-task-binding]" not in text:
        return None
    in_block = False
    raw: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "[workspace-task-binding]":
            in_block = True
            continue
        if stripped == "[/workspace-task-binding]":
            break
        if not in_block or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip()
        if key and value:
            raw[key] = value
    return normalize_workspace_binding(raw)


__all__ = [
    "has_workspace_runtime_context",
    "is_workspace_leader_replan_context",
    "normalize_workspace_binding",
    "workspace_binding_from_context",
    "workspace_binding_from_text",
    "workspace_runtime_context",
]
