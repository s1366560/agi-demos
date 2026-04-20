"""Per-status adjudication handlers (P2d M4).

Replaces the ``if/elif`` chain in
``workspace_goal_runtime.adjudicate_workspace_worker_report`` with a
dispatch table keyed on :class:`LeaderVerdict` status.

Each handler:

* takes a ``LeaderVerdict`` + :class:`AttemptAdjudicationContext` + the
  attempt service;
* makes the necessary async calls to the attempt service;
* returns an :class:`AttemptAdjudicationOutcome` — a bag of
  ``metadata_updates`` (merged into the task metadata by the caller) and an
  optional ``retry_launch_request`` (used to relaunch the worker when the
  leader asks for rework).

Behavior is byte-for-byte equivalent to the legacy code for the three
statuses that had branches (DONE / BLOCKED / IN_PROGRESS). TODO (and any
other status, though :class:`LeaderVerdict` rejects those) produces a
no-op outcome.

The caller remains responsible for persisting the merged metadata via
``command_service.update_task`` and for post-metadata side effects (e.g.
restarting the root task when IN_PROGRESS forces a replan). This module
only owns the attempt-lifecycle calls.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from src.application.services.workspace_task_session_attempt_service import (
    WorkspaceTaskSessionAttemptService,
)
from src.domain.model.workspace.workspace_task import WorkspaceTaskStatus
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    CURRENT_ATTEMPT_ID,
    ROOT_GOAL_TASK_ID,
)

from .leader_verdict import LEADER_VERDICT_STATUSES, LeaderVerdict

__all__ = [
    "AttemptAdjudicationContext",
    "AttemptAdjudicationOutcome",
    "dispatch_attempt_adjudication",
]


@dataclass(frozen=True, kw_only=True)
class AttemptAdjudicationContext:
    """Immutable context for attempt-lifecycle calls during adjudication.

    Pulled from ``WorkspaceTask.metadata`` and the surrounding coroutine by
    the caller; handlers treat it as read-only.
    """

    workspace_id: str
    task_id: str
    task_title: str
    root_goal_task_id: str
    worker_agent_id: str | None
    current_attempt_id: str

    def __post_init__(self) -> None:
        if not self.workspace_id:
            raise ValueError("AttemptAdjudicationContext.workspace_id required")
        if not self.task_id:
            raise ValueError("AttemptAdjudicationContext.task_id required")
        if not self.current_attempt_id:
            raise ValueError("AttemptAdjudicationContext.current_attempt_id required")


@dataclass(frozen=True, kw_only=True)
class AttemptAdjudicationOutcome:
    """Result of a per-status handler.

    ``metadata_updates`` is **merged** into the task metadata by the caller
    (``metadata.update(outcome.metadata_updates)``). ``retry_launch_request``
    is passed upstream to ``_launch_worker_attempt_after_retry`` when
    present; ``None`` means "no relaunch".
    """

    metadata_updates: dict[str, Any] = field(default_factory=dict)
    retry_launch_request: dict[str, str] | None = None


_Handler = Callable[
    [LeaderVerdict, AttemptAdjudicationContext, WorkspaceTaskSessionAttemptService],
    Awaitable[AttemptAdjudicationOutcome],
]


async def _handle_done(
    verdict: LeaderVerdict,
    ctx: AttemptAdjudicationContext,
    attempt_service: WorkspaceTaskSessionAttemptService,
) -> AttemptAdjudicationOutcome:
    accepted = await attempt_service.accept(
        ctx.current_attempt_id,
        leader_feedback=verdict.summary or None,
    )
    return AttemptAdjudicationOutcome(
        metadata_updates={
            "last_attempt_status": accepted.status.value,
            "last_attempt_id": accepted.id,
            CURRENT_ATTEMPT_ID: accepted.id,
        }
    )


async def _handle_blocked(
    verdict: LeaderVerdict,
    ctx: AttemptAdjudicationContext,
    attempt_service: WorkspaceTaskSessionAttemptService,
) -> AttemptAdjudicationOutcome:
    blocked = await attempt_service.block(
        ctx.current_attempt_id,
        leader_feedback=verdict.summary or ctx.task_title,
        adjudication_reason="leader_blocked",
    )
    return AttemptAdjudicationOutcome(
        metadata_updates={
            "last_attempt_status": blocked.status.value,
            "last_attempt_id": blocked.id,
            CURRENT_ATTEMPT_ID: blocked.id,
        }
    )


async def _handle_in_progress(
    verdict: LeaderVerdict,
    ctx: AttemptAdjudicationContext,
    attempt_service: WorkspaceTaskSessionAttemptService,
) -> AttemptAdjudicationOutcome:
    rejected = await attempt_service.reject(
        ctx.current_attempt_id,
        leader_feedback=verdict.summary or ctx.task_title,
        adjudication_reason="leader_rework_required",
    )
    new_attempt = await attempt_service.create_attempt(
        workspace_task_id=ctx.task_id,
        root_goal_task_id=ctx.root_goal_task_id,
        workspace_id=ctx.workspace_id,
        worker_agent_id=ctx.worker_agent_id,
        leader_agent_id=verdict.leader_agent_id,
    )
    updates: dict[str, Any] = {
        "last_attempt_status": rejected.status.value,
        "last_attempt_id": rejected.id,
        CURRENT_ATTEMPT_ID: new_attempt.id,
        "current_attempt_number": new_attempt.attempt_number,
    }
    retry_request: dict[str, str] | None = None
    if verdict.leader_agent_id and ctx.worker_agent_id:
        retry_request = {
            "workspace_id": ctx.workspace_id,
            ROOT_GOAL_TASK_ID: ctx.root_goal_task_id,
            "workspace_task_id": ctx.task_id,
            "attempt_id": new_attempt.id,
            "actor_user_id": verdict.actor_user_id,
            "leader_agent_id": verdict.leader_agent_id,
            "retry_feedback": verdict.summary or ctx.task_title,
        }
    return AttemptAdjudicationOutcome(
        metadata_updates=updates,
        retry_launch_request=retry_request,
    )


_HANDLERS: Mapping[WorkspaceTaskStatus, _Handler] = {
    WorkspaceTaskStatus.DONE: _handle_done,
    WorkspaceTaskStatus.BLOCKED: _handle_blocked,
    WorkspaceTaskStatus.IN_PROGRESS: _handle_in_progress,
    # TODO: no handler — legacy simply falls through with no attempt-service
    # side effect; this is a replan/reprioritize that the caller handles via
    # the separate "start root task" path.
}


async def dispatch_attempt_adjudication(
    *,
    verdict: LeaderVerdict,
    context: AttemptAdjudicationContext,
    attempt_service: WorkspaceTaskSessionAttemptService,
) -> AttemptAdjudicationOutcome:
    """Dispatch by ``verdict.status`` to the appropriate attempt handler.

    Statuses without a registered handler (currently only TODO) return an
    empty outcome — this matches legacy behavior exactly.
    """
    if verdict.status not in LEADER_VERDICT_STATUSES:
        # Defense in depth; LeaderVerdict validates this at construction.
        raise ValueError(f"verdict.status {verdict.status!r} is not a leader-verdict status")
    handler = _HANDLERS.get(verdict.status)
    if handler is None:
        return AttemptAdjudicationOutcome()
    return await handler(verdict, context, attempt_service)
