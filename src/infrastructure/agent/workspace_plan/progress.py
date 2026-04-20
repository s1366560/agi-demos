"""M6 — :class:`ProgressProjectorPort` implementation.

Aggregates a :class:`Plan`'s nodes into a :class:`GoalProgress` snapshot.
Does not mutate the plan; the supervisor is responsible for persisting /
emitting events with the returned snapshot.

Progress formula (simple, interpretable):

* ``done_nodes``        — count of ``TaskIntent.DONE``
* ``percent``           — ``done_nodes / total_nodes * 100`` (excludes goal/milestone for accuracy)
* ``critical_path_eta`` — longest chain of remaining Effort.minutes along the DAG

The projector intentionally excludes ``GOAL`` nodes from the denominator —
the goal is "done" iff every leaf is done, not if the goal itself is toggled.
Milestones are similarly structural. This prevents progress from jumping to
50% when a synthetic milestone is marked done but its children aren't.
"""

from __future__ import annotations

from src.domain.model.workspace_plan import (
    GoalProgress,
    Plan,
    PlanNodeKind,
    TaskIntent,
)
from src.domain.ports.services.progress_projector_port import ProgressProjectorPort


class ProgressProjector(ProgressProjectorPort):
    """Derives a :class:`GoalProgress` from a :class:`Plan`."""

    def project(self, plan: Plan) -> GoalProgress:
        executable = [
            n for n in plan.nodes.values() if n.kind in (PlanNodeKind.TASK, PlanNodeKind.VERIFY)
        ]
        total = len(executable)
        todo = sum(1 for n in executable if n.intent is TaskIntent.TODO)
        in_prog = sum(1 for n in executable if n.intent is TaskIntent.IN_PROGRESS)
        blocked = sum(1 for n in executable if n.intent is TaskIntent.BLOCKED)
        done = sum(1 for n in executable if n.intent is TaskIntent.DONE)
        percent = (done / total * 100.0) if total else 0.0

        return GoalProgress(
            workspace_id=plan.workspace_id,
            plan_id=plan.id,
            goal_node_id=plan.goal_id.value,
            total_nodes=total,
            todo_nodes=todo,
            in_progress_nodes=in_prog,
            blocked_nodes=blocked,
            done_nodes=done,
            percent=round(percent, 2),
            critical_path_remaining_minutes=self._critical_path_eta(plan),
        )

    def _critical_path_eta(self, plan: Plan) -> int:
        """Longest remaining effort along dependency edges (simple DP).

        Nodes already done contribute 0. Non-executable nodes contribute 0.
        """
        try:
            order = plan.topological_order()
        except ValueError:
            return 0
        eta: dict[str, int] = {}
        for node in order:
            if node.intent is TaskIntent.DONE or node.kind not in (
                PlanNodeKind.TASK,
                PlanNodeKind.VERIFY,
            ):
                base = 0
            else:
                base = max(0, node.estimated_effort.minutes)
            dep_max = 0
            for dep in node.depends_on:
                dep_max = max(dep_max, eta.get(dep.value, 0))
            eta[node.id] = base + dep_max
        return max(eta.values()) if eta else 0
