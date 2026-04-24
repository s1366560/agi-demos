"""Bi-directional bridge between :class:`PlanNode` and legacy ``WorkspaceTask``.

The refactor keeps ``WorkspaceTask`` as the outward-facing DTO (UI, APIs, etc.)
while ``PlanNode`` becomes the internal source of truth. Both representations
live side-by-side during M1–M7; M8 flips the primary and removes dual-writes.

:func:`plan_node_from_task` maps an existing legacy task into a fresh plan node
(used for importing in-flight workspaces). :func:`task_update_from_plan_node`
derives the DTO-level mutations that keep the legacy table consistent.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.model.workspace_plan import (
    PlanNode,
    PlanNodeId,
    PlanNodeKind,
    TaskIntent,
)


@dataclass(frozen=True)
class LegacyTaskView:
    """Minimal subset of :class:`WorkspaceTaskModel` we need for adapters.

    We keep this small on purpose — adapters should not know about SQLAlchemy.
    """

    id: str
    workspace_id: str
    title: str
    description: str | None
    status: str
    priority: int
    metadata: dict[str, object]


_LEGACY_TO_INTENT = {
    "todo": TaskIntent.TODO,
    "in_progress": TaskIntent.IN_PROGRESS,
    "executing": TaskIntent.IN_PROGRESS,
    "dispatched": TaskIntent.IN_PROGRESS,
    "reported": TaskIntent.IN_PROGRESS,
    "adjudicating": TaskIntent.IN_PROGRESS,
    "blocked": TaskIntent.BLOCKED,
    "done": TaskIntent.DONE,
}


_INTENT_TO_LEGACY = {
    TaskIntent.TODO: "todo",
    TaskIntent.IN_PROGRESS: "in_progress",
    TaskIntent.BLOCKED: "blocked",
    TaskIntent.DONE: "done",
}


def plan_node_from_task(
    task: LegacyTaskView,
    *,
    plan_id: str,
    parent_id: PlanNodeId | None,
    kind: PlanNodeKind = PlanNodeKind.TASK,
) -> PlanNode:
    """Build a :class:`PlanNode` that shadows a legacy task (for migration)."""
    intent = _LEGACY_TO_INTENT.get(task.status, TaskIntent.TODO)
    return PlanNode(
        id=task.id,
        plan_id=plan_id,
        parent_id=parent_id,
        kind=kind,
        title=task.title,
        description=task.description or "",
        priority=task.priority,
        intent=intent,
        workspace_task_id=task.id,
        metadata=dict(task.metadata or {}),
    )


def legacy_status_for(node: PlanNode) -> str:
    """Return the string value to persist in ``workspace_tasks.status``."""
    return _INTENT_TO_LEGACY[node.intent]
