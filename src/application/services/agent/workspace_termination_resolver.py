"""Workspace-aware termination context builder (Phase-5 · G3).

When a :class:`Conversation` is linked to a :class:`WorkspaceTask` via
``linked_workspace_task_id`` (see G2), the canonical source of goal-
completion and budget caps is the workspace task itself, NOT anything
stored on the conversation.  This module bridges the two worlds:

1. If the linked task has transitioned to
   :attr:`WorkspaceTaskStatus.DONE`, the resolver populates
   ``goal_completed_*`` fields on the :class:`TerminationContext` — the
   3-gate service treats that as the goal gate firing.
2. Budget caps (``max_turns`` / ``max_usd`` / ``max_wall_seconds``) are
   lifted from ``workspace_task.metadata`` when present.  ``None`` on
   any axis means unbounded.

The resolver is **Agent First**: it performs only set-membership (status
enum check) and dict lookups.  It never infers completion from message
content or task title.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, SupportsInt

from src.application.services.agent.termination_service import TerminationContext
from src.domain.model.agent.conversation.termination import BudgetCounters
from src.domain.model.workspace.workspace_task import WorkspaceTaskStatus

if TYPE_CHECKING:
    from src.domain.model.agent.conversation.conversation import Conversation
    from src.domain.model.agent.conversation.verdict_status import VerdictStatus
    from src.domain.model.workspace.workspace_task import WorkspaceTask
    from src.domain.ports.repositories.workspace.workspace_task_repository import (
        WorkspaceTaskRepository,
    )


_BUDGET_META_KEYS: tuple[str, ...] = ("max_turns", "max_usd", "max_wall_seconds")


def _coerce_int(raw: object) -> int | None:
    if raw is None:
        return None
    if not isinstance(raw, str | bytes | bytearray | SupportsInt):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _coerce_float(raw: object) -> float | None:
    if raw is None:
        return None
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _extract_budgets(metadata: dict[str, Any] | None) -> dict[str, Any]:
    meta = metadata or {}
    return {
        "max_turns": _coerce_int(meta.get("max_turns")),
        "max_usd": _coerce_float(meta.get("max_usd")),
        "max_wall_seconds": _coerce_int(meta.get("max_wall_seconds")),
    }


def build_context_from_task(
    *,
    conversation_id: str,
    user_id: str,
    task: WorkspaceTask | None,
    counters: BudgetCounters | None = None,
    latest_verdict: VerdictStatus | str | None = None,
    latest_verdict_rationale: str = "",
    supervisor_actor: str = "supervisor",
    doom_loop_triggered: bool = False,
) -> TerminationContext:
    """Compose a :class:`TerminationContext` using a workspace task as
    the goal + budget source.

    ``task`` of ``None`` means either the conversation is not linked to a
    task (ad-hoc autonomy) or the link dangled (task deleted) — in that
    case the context carries the caller-supplied counters but no
    workspace-derived budgets or goal signal.  Non-autonomous conversations
    never call into this resolver.
    """

    budgets: dict[str, Any] = (
        _extract_budgets(task.metadata) if task is not None else _extract_budgets(None)
    )

    goal_completed_event_id = ""
    goal_completed_summary = ""
    goal_completed_actor = "coordinator"
    goal_completed_artifacts: list[str] = []

    if task is not None and task.status is WorkspaceTaskStatus.DONE:
        goal_completed_event_id = f"workspace_task:{task.id}:done"
        title = (task.title or "").strip()
        goal_completed_summary = title[:500] if title else "workspace task completed"
        goal_completed_actor = task.assignee_agent_id or "coordinator"

    return TerminationContext(
        conversation_id=conversation_id,
        user_id=user_id,
        max_turns=budgets["max_turns"],
        max_usd=budgets["max_usd"],
        max_wall_seconds=budgets["max_wall_seconds"],
        counters=counters or BudgetCounters(),
        latest_verdict=latest_verdict,
        latest_verdict_rationale=latest_verdict_rationale,
        supervisor_actor=supervisor_actor,
        doom_loop_triggered=doom_loop_triggered,
        goal_completed_event_id=goal_completed_event_id,
        goal_completed_summary=goal_completed_summary,
        goal_completed_actor=goal_completed_actor,
        goal_completed_artifacts=goal_completed_artifacts,
    )


class WorkspaceTerminationResolver:
    """Resolve a :class:`TerminationContext` for a conversation by
    reading its linked :class:`WorkspaceTask` (when present).

    The resolver is a thin composition of
    ``WorkspaceTaskRepository.find_by_id`` + :func:`build_context_from_task`
    — it exists as a class so the application layer can wire it via DI
    and swap the repository in tests.
    """

    def __init__(self, *, task_repository: WorkspaceTaskRepository) -> None:
        self._tasks = task_repository

    async def resolve(
        self,
        conversation: Conversation,
        *,
        counters: BudgetCounters | None = None,
        latest_verdict: VerdictStatus | str | None = None,
        latest_verdict_rationale: str = "",
        supervisor_actor: str = "supervisor",
        doom_loop_triggered: bool = False,
    ) -> TerminationContext:
        task: WorkspaceTask | None = None
        if conversation.linked_workspace_task_id:
            task = await self._tasks.find_by_id(conversation.linked_workspace_task_id)

        return build_context_from_task(
            conversation_id=conversation.id,
            user_id=conversation.user_id,
            task=task,
            counters=counters,
            latest_verdict=latest_verdict,
            latest_verdict_rationale=latest_verdict_rationale,
            supervisor_actor=supervisor_actor,
            doom_loop_triggered=doom_loop_triggered,
        )


__all__ = [
    "WorkspaceTerminationResolver",
    "build_context_from_task",
]
