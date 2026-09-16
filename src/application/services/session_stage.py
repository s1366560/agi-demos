"""Derive the session execution stage from persisted authority statuses only.

The derivation is deterministic and monotone: when several rules match, the
later stage wins. A pending HITL request never changes the stage. The rules
read only enumerated persisted statuses already present on the authority
snapshot; no desktop runtime records are invented here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from src.application.services.conversation_session_projection_service import (
        ConversationSessionAuthoritySnapshot,
    )

ExecutionStage = Literal["understand", "implement", "verify", "review"]

_ACTIVE_RUN_STATUSES = frozenset({"queued", "running"})
_REVIEW_RUN_STATUSES = frozenset({"ready_review", "completed"})
_FAILED_RUN_STATUSES = frozenset({"failed", "cancelled"})
_ADJUDICATED_ATTEMPT_STATUSES = frozenset({"accepted", "rejected"})
_ACTIVE_ATTEMPT_STATUSES = frozenset(
    {"pending", "running", "awaiting_leader_adjudication", "blocked"}
)
_INCOMPLETE_TASK_STATUSES = frozenset({"pending", "in_progress"})


def derive_execution_stage(
    snapshot: ConversationSessionAuthoritySnapshot,
) -> ExecutionStage | None:
    """Map persisted session authority to the current execution stage.

    Rules are evaluated in priority order and the first match wins, so
    conflicts resolve toward the later stage. ``None`` means there is nothing
    honest to show: a fresh session without runs/plans/tasks, or a terminally
    failed/cancelled run with no reviewable artifacts and no active attempt.
    """
    conversation = snapshot.conversation
    latest_attempt = snapshot.attempts[0] if snapshot.attempts else None
    latest_run = snapshot.runs[0] if snapshot.runs else None
    current_plan = snapshot.plan_versions[0] if snapshot.plan_versions else None

    candidate_artifact_ref_count = sum(
        len(attempt.candidate_artifact_refs) for attempt in snapshot.attempts
    )
    candidate_verification_ref_count = sum(
        len(attempt.candidate_verification_refs) for attempt in snapshot.attempts
    )
    has_reviewable_artifacts = bool(snapshot.artifact_records) or candidate_artifact_ref_count > 0
    run_active = latest_run is not None and latest_run.status in _ACTIVE_RUN_STATUSES
    run_reviewable = latest_run is not None and latest_run.status in _REVIEW_RUN_STATUSES
    run_failed = latest_run is not None and latest_run.status in _FAILED_RUN_STATUSES
    attempt_active = (
        latest_attempt is not None and latest_attempt.status in _ACTIVE_ATTEMPT_STATUSES
    )
    attempt_adjudicated = latest_attempt is not None and (
        latest_attempt.status in _ADJUDICATED_ATTEMPT_STATUSES
        or latest_attempt.completed_at is not None
    )
    approved_plan_has_incomplete_tasks = any(
        plan.status == "approved" for plan in snapshot.plan_versions
    ) and any(task.status in _INCOMPLETE_TASK_STATUSES for task in snapshot.conversation_tasks)

    # A matched rule yielding None suppresses the stepper entirely; later
    # rules must not resurrect a stage for a quiet terminal failure.
    rules: tuple[tuple[bool, ExecutionStage | None], ...] = (
        (attempt_adjudicated, "review"),
        (run_reviewable and has_reviewable_artifacts, "review"),
        (run_failed and not attempt_active and not has_reviewable_artifacts, None),
        (
            attempt_active
            and latest_attempt is not None
            and bool(latest_attempt.candidate_verification_refs),
            "verify",
        ),
        (candidate_verification_ref_count > 0 and run_active, "verify"),
        (run_failed and has_reviewable_artifacts, "review"),
        (run_active, "implement"),
        (approved_plan_has_incomplete_tasks, "implement"),
        (conversation.current_mode == "build", "implement"),
        (
            conversation.current_mode == "plan"
            and current_plan is not None
            and current_plan.status == "draft",
            "understand",
        ),
        (_has_conversation_activity(snapshot), "understand"),
    )
    return next((stage for matched, stage in rules if matched), None)


def _has_conversation_activity(snapshot: ConversationSessionAuthoritySnapshot) -> bool:
    return bool(
        snapshot.conversation.message_count > 0
        or snapshot.runs
        or snapshot.plan_versions
        or snapshot.conversation_tasks
        or snapshot.attempts
        or snapshot.artifact_records
        or snapshot.tool_executions.total > 0
    )


__all__ = ["ExecutionStage", "derive_execution_stage"]
