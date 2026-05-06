"""Derived workspace task experience read model."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from src.application.services.workspace_task_command_service import WorkspaceTaskCommandService
from src.application.services.workspace_task_service import WorkspaceTaskService
from src.domain.model.workspace.workspace_task import WorkspaceTask
from src.domain.model.workspace.workspace_task_session_attempt import WorkspaceTaskSessionAttempt
from src.domain.ports.repositories.workspace.workspace_task_session_attempt_repository import (
    WorkspaceTaskSessionAttemptRepository,
)
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    CURRENT_ATTEMPT_ID,
    LAST_WORKER_REPORT_SUMMARY,
    PENDING_LEADER_ADJUDICATION,
    REMEDIATION_STATUS,
    ROOT_GOAL_TASK_ID,
    TASK_ROLE,
)

_MAX_LIST_ITEMS = 20


class WorkspaceTaskExperienceService:
    """Builds the task experience summary shown in workspace UX surfaces."""

    def __init__(
        self,
        *,
        task_service: WorkspaceTaskService,
        attempt_repo: WorkspaceTaskSessionAttemptRepository,
    ) -> None:
        self._task_service = task_service
        self._attempt_repo = attempt_repo

    async def get_summary(
        self,
        *,
        workspace_id: str,
        task_id: str,
        actor_user_id: str,
    ) -> dict[str, Any]:
        task = await self._task_service.get_task(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_user_id=actor_user_id,
        )
        attempts = await self._attempt_repo.find_by_workspace_task_id(
            task.id,
            limit=5,
        )
        return build_workspace_task_experience_summary(task, attempts=attempts)


def build_workspace_task_experience_summary(
    task: WorkspaceTask,
    *,
    attempts: Sequence[WorkspaceTaskSessionAttempt] | None = None,
) -> dict[str, Any]:
    """Return a serializable summary from current task state and known attempts."""

    metadata = _metadata(task)
    attempts = list(attempts or [])
    transition_gates = WorkspaceTaskCommandService.evaluate_transition_gates(task)

    evidence_refs = _strings(metadata.get("evidence_refs"))
    worker_artifacts = _strings(metadata.get("last_worker_report_artifacts"))
    worker_verifications = _strings(metadata.get("last_worker_report_verifications"))
    execution_verifications = _strings(metadata.get("execution_verifications"))
    attempt_artifacts = _unique(
        item for attempt in attempts for item in _strings(attempt.candidate_artifacts)
    )
    attempt_verifications = _unique(
        item for attempt in attempts for item in _strings(attempt.candidate_verifications)
    )
    artifacts = _unique([*worker_artifacts, *attempt_artifacts])
    verifications = _unique(
        [*worker_verifications, *execution_verifications, *attempt_verifications]
    )

    goal_evidence = _dict(metadata.get("goal_evidence"))
    current_attempt = _find_current_attempt(metadata, attempts)
    done_gate = _dict(transition_gates.get("done"))
    blocked_gate = _dict(transition_gates.get("blocked"))
    missing_evidence = _strings(done_gate.get("missing"))
    blocked_requirements = _unique(
        [
            *_strings(done_gate.get("reasons")),
            *_strings(blocked_gate.get("reasons")),
        ]
    )

    return {
        "task_id": task.id,
        "workspace_id": task.workspace_id,
        "readiness": {
            "goal_contract": {
                "task_role": _text(metadata.get(TASK_ROLE)),
                "root_goal_task_id": _text(metadata.get(ROOT_GOAL_TASK_ID)),
                "goal_health": _text(metadata.get("goal_health")),
                "remediation_status": _text(metadata.get(REMEDIATION_STATUS)),
                "goal_progress_summary": _text(metadata.get("goal_progress_summary")),
                "goal_evidence_grade": _text(goal_evidence.get("verification_grade")),
                "description_present": bool(task.description),
            },
            "missing_evidence": missing_evidence,
            "blocked_requirements": blocked_requirements,
            "transition_gates": transition_gates,
        },
        "execution": {
            "assignee_user_id": task.assignee_user_id,
            "assignee_agent_id": task.assignee_agent_id,
            "workspace_agent_id": task.get_workspace_agent_binding_id(),
            "current_attempt_id": _text(metadata.get(CURRENT_ATTEMPT_ID)),
            "current_attempt_number": _int(metadata.get("current_attempt_number")),
            "current_attempt_conversation_id": _text(
                metadata.get("current_attempt_conversation_id")
            ),
            "current_attempt_worker_binding_id": _text(
                metadata.get("current_attempt_worker_binding_id")
            ),
            "current_attempt_worker_agent_id": _text(
                metadata.get("current_attempt_worker_agent_id")
            ),
            "active_attempt": _serialize_attempt(current_attempt) if current_attempt else None,
            "last_attempt_status": _text(metadata.get("last_attempt_status")),
            "launch_state": _text(metadata.get("launch_state")),
        },
        "evidence": {
            "evidence_refs": evidence_refs[:_MAX_LIST_ITEMS],
            "artifacts": artifacts[:_MAX_LIST_ITEMS],
            "verification_summaries": verifications[:_MAX_LIST_ITEMS],
            "goal_evidence_grade": _text(goal_evidence.get("verification_grade")),
            "worker_report": {
                "type": _text(metadata.get("last_worker_report_type")),
                "summary": _text(metadata.get(LAST_WORKER_REPORT_SUMMARY)),
                "id": _text(metadata.get("last_worker_report_id")),
                "fingerprint": _text(metadata.get("last_worker_report_fingerprint")),
            },
        },
        "diagnostics": {
            "blocker_reason": task.blocker_reason,
            "pending_leader_adjudication": metadata.get(PENDING_LEADER_ADJUDICATION) is True,
            "missing_conversation": _missing_conversation(task, metadata),
            "durable_plan_verdict": _text(metadata.get("durable_plan_verdict")),
            "last_attempt_status": _text(metadata.get("last_attempt_status")),
            "transition_gates": transition_gates,
        },
        "activity": _activity(task, metadata, attempts),
    }


def _activity(
    task: WorkspaceTask,
    metadata: Mapping[str, Any],
    attempts: Sequence[WorkspaceTaskSessionAttempt],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = [
        {
            "type": "task_created",
            "at": _datetime(task.created_at),
            "summary": "Task created",
        }
    ]
    if task.updated_at:
        items.append(
            {
                "type": "task_updated",
                "at": _datetime(task.updated_at),
                "summary": f"Status: {task.status.value}",
            }
        )
    if task.completed_at:
        items.append(
            {
                "type": "task_completed",
                "at": _datetime(task.completed_at),
                "summary": "Task completed",
            }
        )
    actor = _dict(metadata.get("last_mutation_actor"))
    action = _text(actor.get("action"))
    if action:
        items.append(
            {
                "type": "last_mutation",
                "at": _text(actor.get("at")),
                "summary": action,
                "actor_user_id": _text(actor.get("actor_user_id")),
                "actor_agent_id": _text(actor.get("actor_agent_id")),
            }
        )
    for attempt in attempts:
        items.append(_serialize_attempt(attempt) | {"type": "attempt"})
    return items[:_MAX_LIST_ITEMS]


def _find_current_attempt(
    metadata: Mapping[str, Any],
    attempts: Sequence[WorkspaceTaskSessionAttempt],
) -> WorkspaceTaskSessionAttempt | None:
    current_attempt_id = _text(metadata.get(CURRENT_ATTEMPT_ID))
    if current_attempt_id:
        for attempt in attempts:
            if attempt.id == current_attempt_id:
                return attempt
    return attempts[0] if attempts else None


def _serialize_attempt(attempt: WorkspaceTaskSessionAttempt) -> dict[str, Any]:
    return {
        "id": attempt.id,
        "attempt_number": attempt.attempt_number,
        "status": attempt.status.value,
        "conversation_id": attempt.conversation_id,
        "worker_agent_id": attempt.worker_agent_id,
        "leader_agent_id": attempt.leader_agent_id,
        "summary": attempt.candidate_summary,
        "artifacts": list(attempt.candidate_artifacts),
        "verifications": list(attempt.candidate_verifications),
        "leader_feedback": attempt.leader_feedback,
        "adjudication_reason": attempt.adjudication_reason,
        "at": _datetime(attempt.updated_at or attempt.created_at),
        "created_at": _datetime(attempt.created_at),
        "updated_at": _datetime(attempt.updated_at),
        "completed_at": _datetime(attempt.completed_at),
    }


def _missing_conversation(task: WorkspaceTask, metadata: Mapping[str, Any]) -> bool:
    current_attempt_id = _text(metadata.get(CURRENT_ATTEMPT_ID))
    current_conversation_id = _text(metadata.get("current_attempt_conversation_id"))
    return bool(
        task.status.value == "in_progress" and current_attempt_id and not current_conversation_id
    )


def _metadata(task: WorkspaceTask) -> dict[str, Any]:
    metadata = getattr(task, "metadata", {}) or {}
    return dict(metadata) if isinstance(metadata, Mapping) else {}


def _dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _unique(items: Iterable[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, str) or not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")
