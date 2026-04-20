"""Workspace-agent autonomy metadata helpers."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from src.application.schemas.workspace_agent_autonomy import (
    AUTONOMY_SCHEMA_VERSION,
    CompletionEvidenceModel,
    ExecutionTaskMetadataModel,
    GoalCandidateRecordModel,
    RootGoalMetadataModel,
    has_autonomy_metadata,
)
from src.domain.model.workspace.cyber_objective import CyberObjective
from src.domain.model.workspace.workspace_task import WorkspaceTask, WorkspaceTaskStatus
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    AUTONOMY_SCHEMA_VERSION_KEY,
    REMEDIATION_STATUS,
    REMEDIATION_SUMMARY,
    REPLAN_ATTEMPT_COUNT,
    TASK_ROLE,
)

_PROTECTED_ROOT_METADATA_KEYS = {
    AUTONOMY_SCHEMA_VERSION_KEY,
    TASK_ROLE,
    "goal_origin",
    "goal_source_refs",
    "goal_formalization_reason",
    "objective_id",
    "root_goal_policy",
    "goal_evidence_bundle",
}


def validate_autonomy_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    normalized = dict(metadata or {})
    if not has_autonomy_metadata(normalized):
        return normalized

    task_role = normalized.get(TASK_ROLE)
    if task_role == "goal_root":
        return RootGoalMetadataModel.model_validate(normalized).model_dump(mode="python")
    if task_role == "execution_task":
        return ExecutionTaskMetadataModel.model_validate(normalized).model_dump(mode="python")
    raise ValueError("Autonomy metadata must declare a supported task_role")


def is_goal_root_task(task: WorkspaceTask) -> bool:
    return task.metadata.get(TASK_ROLE) == "goal_root"


def is_execution_task(task: WorkspaceTask) -> bool:
    return task.metadata.get(TASK_ROLE) == "execution_task"


def is_autonomy_task(task: WorkspaceTask) -> bool:
    return is_goal_root_task(task) or is_execution_task(task)


def is_agent_inferred_root_task(task: WorkspaceTask) -> bool:
    return is_goal_root_task(task) and task.metadata.get("goal_origin") == "agent_inferred"


def is_mutable_by_agent(task: WorkspaceTask) -> bool:
    if not is_goal_root_task(task):
        return True
    policy = task.metadata.get("root_goal_policy")
    if isinstance(policy, Mapping):
        mutable = policy.get("mutable_by_agent")
        if isinstance(mutable, bool):
            return mutable
    return task.metadata.get("goal_origin") == "agent_inferred"


def ensure_root_goal_mutation_allowed(
    task: WorkspaceTask,
    *,
    title: str | None,
    description: str | None,
    metadata: Mapping[str, Any] | None,
) -> None:
    if not is_goal_root_task(task) or is_mutable_by_agent(task):
        return

    if title is not None and title != task.title:
        raise ValueError("Cannot rewrite immutable root goal title")
    if description is not None and description != task.description:
        raise ValueError("Cannot rewrite immutable root goal description")

    if metadata is None:
        return

    next_metadata = dict(metadata)
    for key in _PROTECTED_ROOT_METADATA_KEYS:
        if next_metadata.get(key) != task.metadata.get(key):
            raise ValueError(f"Cannot rewrite immutable root goal metadata field: {key}")


def ensure_goal_completion_allowed(task: WorkspaceTask) -> None:
    if not is_goal_root_task(task):
        return

    goal_evidence = task.metadata.get("goal_evidence")
    if not isinstance(goal_evidence, Mapping):
        raise ValueError("Root goal completion requires metadata.goal_evidence")

    evidence = CompletionEvidenceModel.model_validate(goal_evidence)
    if evidence.goal_text_snapshot != task.title:
        raise ValueError("goal_evidence.goal_text_snapshot must match immutable root goal title")
    policy = task.metadata.get("root_goal_policy")
    requires_external_proof = is_agent_inferred_root_task(task)
    if isinstance(policy, Mapping):
        maybe_requires_external = policy.get("completion_requires_external_proof")
        if isinstance(maybe_requires_external, bool):
            requires_external_proof = maybe_requires_external
    if requires_external_proof and not evidence.artifacts:
        raise ValueError(
            "Root goals requiring external proof must include proof artifacts before completion"
        )


def build_projected_objective_root_metadata(objective: CyberObjective) -> dict[str, Any]:
    return {
        AUTONOMY_SCHEMA_VERSION_KEY: AUTONOMY_SCHEMA_VERSION,
        TASK_ROLE: "goal_root",
        "goal_origin": "existing_objective",
        "goal_source_refs": [f"objective:{objective.id}"],
        "objective_id": objective.id,
        "goal_formalization_reason": "selected workspace objective projected into execution root",
        "root_goal_policy": {
            "mutable_by_agent": False,
            "completion_requires_external_proof": True,
        },
        "goal_health": "healthy",
        REPLAN_ATTEMPT_COUNT: 0,
    }


def build_inferred_goal_root_metadata(candidate: GoalCandidateRecordModel) -> dict[str, Any]:
    return {
        AUTONOMY_SCHEMA_VERSION_KEY: AUTONOMY_SCHEMA_VERSION,
        TASK_ROLE: "goal_root",
        "goal_origin": "agent_inferred",
        "goal_source_refs": list(candidate.source_refs),
        "goal_formalization_reason": "workspace goal candidate formalized from explicit evidence",
        "goal_evidence_bundle": {
            "score": candidate.evidence_strength,
            "signals": [
                {
                    "source_type": signal.source_type,
                    "ref": signal.ref or "",
                    "score": signal.score,
                }
                for signal in candidate.source_breakdown
                if signal.ref
            ],
            "formalized_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        },
        "root_goal_policy": {
            "mutable_by_agent": False,
            "completion_requires_external_proof": True,
        },
        "goal_health": "healthy",
        REPLAN_ATTEMPT_COUNT: 0,
    }


def record_task_actor(
    task: WorkspaceTask,
    *,
    action: str,
    actor_user_id: str,
    actor_type: str = "human",
    actor_agent_id: str | None = None,
    workspace_agent_binding_id: str | None = None,
    reason: str | None = None,
) -> None:
    metadata = dict(task.metadata)
    metadata["last_mutation_actor"] = {
        "action": action,
        "actor_type": actor_type,
        "actor_user_id": actor_user_id,
        "actor_agent_id": actor_agent_id,
        "workspace_agent_binding_id": workspace_agent_binding_id,
        "reason": reason or f"workspace_task.{action}",
    }
    task.metadata = validate_autonomy_metadata(metadata)


def merge_validated_metadata(
    existing_metadata: Mapping[str, Any] | None,
    patch_metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    merged = deepcopy(dict(existing_metadata or {}))
    if patch_metadata is None:
        return validate_autonomy_metadata(merged)
    merged.update(dict(patch_metadata))
    return validate_autonomy_metadata(merged)


def synthesize_goal_evidence_from_children(
    *,
    root_task: WorkspaceTask,
    child_tasks: list[WorkspaceTask],
    generated_by_agent_id: str,
) -> dict[str, Any] | None:
    if not child_tasks:
        return None
    if any(task.status != WorkspaceTaskStatus.DONE for task in child_tasks):
        return None

    completed_children = [task for task in child_tasks if task.completed_at is not None]
    recorded_at = max(
        (
            task.completed_at or task.updated_at or task.created_at
            for task in completed_children or child_tasks
        ),
        default=datetime.now(UTC),
    )
    artifacts: list[str] = []
    verifications: list[str] = []
    evidence_rich_children = 0
    for task in child_tasks:
        evidence_refs = task.metadata.get("evidence_refs")
        if isinstance(evidence_refs, list):
            normalized_refs = [str(ref) for ref in evidence_refs if ref]
            artifacts.extend(normalized_refs)
            if normalized_refs:
                evidence_rich_children += 1
        else:
            artifacts.append(f"workspace_task:{task.id}")

        verifications.append(f"workspace_task_completed:{task.id}")
        execution_verifications = task.metadata.get("execution_verifications")
        if isinstance(execution_verifications, list):
            verifications.extend(str(item) for item in execution_verifications if item)
        last_mutation_actor = task.metadata.get("last_mutation_actor")
        if isinstance(last_mutation_actor, Mapping):
            reason = last_mutation_actor.get("reason")
            if isinstance(reason, str) and reason.strip():
                verifications.append(f"actor_reason:{reason.strip()}")

    dedup_artifacts = list(dict.fromkeys(artifacts))
    dedup_verifications = list(dict.fromkeys(verifications))
    verification_grade = (
        "pass"
        if evidence_rich_children == len(child_tasks)
        and len(dedup_verifications) >= len(child_tasks) * 2
        else "warn"
    )

    return CompletionEvidenceModel(
        goal_task_id=root_task.id,
        goal_text_snapshot=root_task.title,
        outcome_status="achieved",
        summary=(
            f"Auto-generated from {len(child_tasks)} completed execution task(s): "
            + ", ".join(task.title for task in child_tasks[:3])
        ),
        artifacts=dedup_artifacts,
        verifications=dedup_verifications,
        generated_by_agent_id=generated_by_agent_id,
        recorded_at=recorded_at.isoformat().replace("+00:00", "Z"),
        verification_grade=verification_grade,
    ).model_dump(mode="python")


async def reconcile_root_goal_progress(
    *,
    task_repo: Any,  # noqa: ANN401
    workspace_id: str,
    root_goal_task_id: str,
) -> WorkspaceTask | None:
    root_task = await task_repo.find_by_id(root_goal_task_id)
    if (
        root_task is None
        or root_task.workspace_id != workspace_id
        or not is_goal_root_task(root_task)
    ):
        return None

    child_tasks = await task_repo.find_by_root_goal_task_id(workspace_id, root_goal_task_id)
    active_child_task_ids = [
        task.id
        for task in child_tasks
        if task.status != WorkspaceTaskStatus.DONE and task.archived_at is None
    ]
    blocked_tasks = [task for task in child_tasks if task.status == WorkspaceTaskStatus.BLOCKED]
    blocked_child_task_ids = [task.id for task in blocked_tasks]
    in_progress_count = sum(
        1 for task in child_tasks if task.status == WorkspaceTaskStatus.IN_PROGRESS
    )
    done_count = sum(1 for task in child_tasks if task.status == WorkspaceTaskStatus.DONE)
    assigned_count = sum(
        1 for task in child_tasks if task.assignee_agent_id or task.assignee_user_id
    )
    total_count = len(child_tasks)

    if blocked_tasks:
        goal_health = "blocked"
        blocked_reason = blocked_tasks[0].blocker_reason or blocked_tasks[0].title
        remediation_status = "replan_required"
        remediation_summary = (
            f"{len(blocked_tasks)} child task(s) blocked; root goal requires replan or intervention"
        )
    elif in_progress_count > 0:
        goal_health = "healthy"
        blocked_reason = None
        remediation_status = "none"
        remediation_summary = None
    elif total_count > 0 and done_count == total_count:
        goal_health = "achieved"
        blocked_reason = None
        remediation_status = "ready_for_completion"
        remediation_summary = (
            "All child tasks are done; root goal should now validate completion evidence"
        )
    else:
        goal_health = "healthy"
        blocked_reason = None
        remediation_status = "none"
        remediation_summary = None

    progress_summary = (
        f"{done_count}/{total_count} child tasks done; "
        f"{in_progress_count} in progress; {len(blocked_tasks)} blocked; "
        f"{assigned_count}/{total_count} assigned"
    )

    metadata = dict(root_task.metadata)
    metadata.update(
        {
            "goal_progress_summary": progress_summary,
            "last_progress_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "active_child_task_ids": active_child_task_ids,
            "blocked_child_task_ids": blocked_child_task_ids,
            "blocked_reason": blocked_reason,
            "goal_health": goal_health,
            REMEDIATION_STATUS: remediation_status,
            REMEDIATION_SUMMARY: remediation_summary,
        }
    )
    root_task.metadata = validate_autonomy_metadata(metadata)
    root_task.updated_at = datetime.now(UTC)
    return await task_repo.save(root_task)
