"""Shared runtime-role helpers for workspace leader/worker sessions."""

from __future__ import annotations

from typing import Final

from src.infrastructure.agent.tools.context import ToolContext

WORKSPACE_SESSION_ROLE_KEY: Final[str] = "workspace_session_role"
WORKSPACE_ID_KEY: Final[str] = "workspace_id"
WORKSPACE_TOOL_MODE_KEY: Final[str] = "workspace_tool_mode"
WORKSPACE_TURN_TYPE_KEY: Final[str] = "workspace_turn_type"

WORKSPACE_ROLE_LEADER: Final[str] = "leader"
WORKSPACE_ROLE_WORKER: Final[str] = "worker"
WORKSPACE_TOOL_MODE_TASK_LEDGER_ONLY: Final[str] = "task_ledger_only"
WORKSPACE_TURN_TYPE_LEADER_REPLAN: Final[str] = "leader_replan"


def derive_workspace_session_role(*, has_workspace_binding: bool) -> str:
    return WORKSPACE_ROLE_WORKER if has_workspace_binding else WORKSPACE_ROLE_LEADER


def runtime_context_string(ctx: ToolContext, key: str) -> str:
    value = ctx.runtime_context.get(key)
    return value.strip() if isinstance(value, str) else ""


def require_workspace_session_role(
    ctx: ToolContext,
    *,
    expected_role: str,
    action_label: str,
) -> str | None:
    role = runtime_context_string(ctx, WORKSPACE_SESSION_ROLE_KEY)
    if role != expected_role:
        return (
            f"{action_label} may only be called from a workspace {expected_role} session "
            f"(current role: {role or 'none'})"
        )
    if not runtime_context_string(ctx, WORKSPACE_ID_KEY):
        return "workspace_id is missing from runtime_context — is this a workspace session?"
    return None
