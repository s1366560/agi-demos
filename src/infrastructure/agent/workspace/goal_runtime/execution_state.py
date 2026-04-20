"""Execution-state metadata helpers (pure functions, no IO)."""

from __future__ import annotations

from datetime import UTC, datetime

from src.infrastructure.agent.workspace.goal_runtime.activation import (
    _WORKSPACE_TASK_ID_PATTERN,
)


def _build_execution_state(
    *,
    phase: str,
    reason: str,
    action: str,
    actor_id: str,
) -> dict[str, str]:
    return {
        "phase": phase,
        "last_agent_reason": reason,
        "last_agent_action": action,
        "updated_by_actor_type": "agent",
        "updated_by_actor_id": actor_id,
        "updated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def _extract_workspace_task_id(task_text: str) -> str | None:
    match = _WORKSPACE_TASK_ID_PATTERN.search(task_text)
    if match:
        return match.group(1)
    return None


__all__ = ["_build_execution_state", "_extract_workspace_task_id"]
