"""Shared runtime-role helpers for workspace leader/worker sessions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

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


def is_workspace_conversation(payload: Mapping[str, Any] | None) -> bool:
    """Authoritative predicate: is this turn bound to a workspace?

    A conversation is workspace-bound iff one of:
    - ``context_type == "workspace_worker_runtime"`` is set on the payload
      (canonical marker emitted by every workspace dispatch path: the
      mention router, the planner agent decomposer, iteration review, and
      verification judge)
    - ``runtime_context.task_authority == "workspace"`` (worker dispatch path)
    - both ``runtime_context.workspace_id`` and
      ``runtime_context.workspace_session_role`` are present (leader or worker
      session explicitly tagged with a workspace role)

    Anything else (e.g. project-scoped chat in a project that happens to host
    a workspace) is NOT a workspace conversation and must not receive
    workspace-scoped prompt content, tools, or skills.

    The argument may be either the raw runtime_context mapping or a payload
    that has a nested ``runtime_context`` mapping (mirrors the dual shape
    accepted by plugin hooks).
    """
    if not isinstance(payload, Mapping):
        return False
    # Canonical marker — present on every workspace dispatch shape, including
    # the planner/review/verification paths that nest workspace_id inside
    # ``workspace_binding`` instead of placing it at the top level.
    if payload.get("context_type") == "workspace_worker_runtime":
        return True
    nested = payload.get("runtime_context")
    runtime_context = nested if isinstance(nested, Mapping) else payload
    if runtime_context.get("task_authority") == "workspace":
        return True
    if runtime_context.get(WORKSPACE_ID_KEY) and runtime_context.get(
        WORKSPACE_SESSION_ROLE_KEY
    ):
        return True
    # Fallback: caller passed a payload (not nested runtime_context) where the
    # top-level key carries authority. Mirrors the existing plugin behavior.
    return isinstance(nested, Mapping) and payload.get("task_authority") == "workspace"
