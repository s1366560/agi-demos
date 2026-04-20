"""Root-candidate selection heuristics (pure, no IO)."""

from __future__ import annotations

from collections.abc import Sequence

from src.application.schemas.workspace_agent_autonomy import GoalCandidateRecordModel
from src.application.services.workspace_agent_autonomy import is_goal_root_task
from src.domain.model.workspace.workspace_task import WorkspaceTask, WorkspaceTaskStatus


def _select_existing_root_candidate(
    candidates: Sequence[GoalCandidateRecordModel],
    tasks: list[WorkspaceTask],
) -> GoalCandidateRecordModel | None:
    root_tasks = {
        task.id: task
        for task in tasks
        if is_goal_root_task(task)
        and task.archived_at is None
        and task.status != WorkspaceTaskStatus.DONE
    }
    ranked_candidates: list[tuple[GoalCandidateRecordModel, WorkspaceTask]] = []
    for candidate in candidates:
        decision = getattr(candidate, "decision", None)
        if decision != "adopt_existing_goal":
            continue
        source_refs = getattr(candidate, "source_refs", [])
        task_refs = [
            source_ref.split(":", 1)[1]
            for source_ref in source_refs
            if isinstance(source_ref, str)
            and source_ref.startswith("task:")
            and source_ref.split(":", 1)[1] in root_tasks
        ]
        if not task_refs:
            continue
        root_task = root_tasks[task_refs[0]]
        ranked_candidates.append((candidate, root_task))
    if not ranked_candidates:
        for candidate in candidates:
            decision = getattr(candidate, "decision", None)
            source_refs = getattr(candidate, "source_refs", [])
            if decision == "adopt_existing_goal" and any(
                isinstance(source_ref, str) and source_ref.startswith("task:")
                for source_ref in source_refs
            ):
                return candidate
        return None
    ranked_candidates.sort(key=lambda item: (item[1].id,))
    ranked_candidates.sort(
        key=lambda item: (item[1].created_at,),
        reverse=True,
    )
    ranked_candidates.sort(
        key=lambda item: (item[1].updated_at or item[1].created_at,),
        reverse=True,
    )
    ranked_candidates.sort(
        key=lambda item: (float(getattr(item[0], "freshness", 0.0)),),
        reverse=True,
    )
    ranked_candidates.sort(
        key=lambda item: (float(getattr(item[0], "urgency", 0.0)),),
        reverse=True,
    )
    ranked_candidates.sort(
        key=lambda item: (float(getattr(item[0], "evidence_strength", 0.0)),),
        reverse=True,
    )
    return ranked_candidates[0][0]


__all__ = ["_select_existing_root_candidate"]
