"""Plan aggregate: a typed DAG of PlanNodes with a single goal root."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from src.domain.model.workspace_plan.plan_node import (
    PlanNode,
    PlanNodeId,
    PlanNodeKind,
    TaskIntent,
)
from src.domain.shared_kernel import Entity


class PlanStatus(str, Enum):
    """Lifecycle of a plan as a whole."""

    DRAFT = "draft"  # freshly planned, not yet started
    ACTIVE = "active"  # supervisor is driving it
    SUSPENDED = "suspended"  # paused (human or error)
    COMPLETED = "completed"  # goal node DONE
    ABANDONED = "abandoned"  # user canceled or goal unachievable


@dataclass(kw_only=True)
class Plan(Entity):
    """A goal DAG. Single goal root, zero-to-many milestones/tasks/verifies.

    Invariants (enforced on mutation helpers, best-effort on construction):

    * exactly one node with ``kind == GOAL`` and ``parent_id is None``
    * every non-goal node has a ``parent_id`` that resolves to a node in this plan
    * ``depends_on`` entries must all resolve to nodes in this plan (no cross-plan deps)
    * the graph must be acyclic (checked by :meth:`validate`)
    """

    workspace_id: str
    goal_id: PlanNodeId
    nodes: dict[PlanNodeId, PlanNode] = field(default_factory=dict)
    status: PlanStatus = PlanStatus.DRAFT
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.workspace_id:
            raise ValueError("Plan.workspace_id cannot be empty")
        if not isinstance(self.goal_id, PlanNodeId):
            raise ValueError("Plan.goal_id must be PlanNodeId")

    # --- Construction ---------------------------------------------------

    def add_node(self, node: PlanNode) -> None:
        """Add a node. Enforces structural invariants."""
        if node.node_id in self.nodes:
            raise ValueError(f"duplicate node id: {node.id}")
        if node.plan_id != self.id:
            raise ValueError(f"node.plan_id={node.plan_id} does not belong to this plan {self.id}")
        if node.kind is PlanNodeKind.GOAL:
            existing_goal = self._find_goal()
            if existing_goal is not None and existing_goal.node_id != node.node_id:
                raise ValueError("plan already has a goal node")
            if node.node_id != self.goal_id:
                raise ValueError("goal node id must equal plan.goal_id")
        else:
            if node.parent_id is None or node.parent_id not in self.nodes:
                raise ValueError(f"parent_id {node.parent_id} not found in plan {self.id}")
        for dep in node.depends_on:
            if dep not in self.nodes and dep != node.node_id:
                raise ValueError(f"dep {dep} not found in plan {self.id}")
        self.nodes[node.node_id] = node

    def replace_node(self, node: PlanNode) -> None:
        """Replace an existing node (used for state updates)."""
        if node.node_id not in self.nodes:
            raise ValueError(f"node {node.id} not found in plan {self.id}")
        self.nodes[node.node_id] = node
        self.updated_at = datetime.now(UTC)

    # --- Queries --------------------------------------------------------

    @property
    def goal_node(self) -> PlanNode:
        """The single goal root. Raises if missing (invariant)."""
        node = self.nodes.get(self.goal_id)
        if node is None:
            raise ValueError(f"plan {self.id} has no goal node")
        return node

    def _find_goal(self) -> PlanNode | None:
        for n in self.nodes.values():
            if n.kind is PlanNodeKind.GOAL:
                return n
        return None

    def children_of(self, node_id: PlanNodeId) -> list[PlanNode]:
        return [n for n in self.nodes.values() if n.parent_id == node_id]

    def descendants_of(self, node_id: PlanNodeId) -> list[PlanNode]:
        """All transitive descendants in BFS order."""
        out: list[PlanNode] = []
        stack: list[PlanNodeId] = [c.node_id for c in self.children_of(node_id)]
        while stack:
            nid = stack.pop(0)
            node = self.nodes.get(nid)
            if node is None:
                continue
            out.append(node)
            stack.extend(c.node_id for c in self.children_of(nid))
        return out

    def leaf_tasks(self) -> list[PlanNode]:
        """All nodes with no children and kind TASK/VERIFY (executable leaves)."""
        children_count: dict[PlanNodeId, int] = {}
        for n in self.nodes.values():
            if n.parent_id is not None:
                children_count[n.parent_id] = children_count.get(n.parent_id, 0) + 1
        return [
            n
            for n in self.nodes.values()
            if children_count.get(n.node_id, 0) == 0
            and n.kind in (PlanNodeKind.TASK, PlanNodeKind.VERIFY)
        ]

    def ready_nodes(self) -> list[PlanNode]:
        """Leaf executable nodes whose deps are all done — the schedule frontier."""
        done_ids = frozenset(n.node_id for n in self.nodes.values() if n.intent is TaskIntent.DONE)
        return [n for n in self.leaf_tasks() if n.is_ready(done_ids)]

    def topological_order(self) -> list[PlanNode]:
        """Kahn's algorithm. Raises ``ValueError`` on cycles."""
        in_deg: dict[PlanNodeId, int] = dict.fromkeys(self.nodes, 0)
        for n in self.nodes.values():
            for dep in n.depends_on:
                if dep in in_deg:
                    in_deg[n.node_id] = in_deg.get(n.node_id, 0) + 1
        q = [nid for nid, d in in_deg.items() if d == 0]
        order: list[PlanNode] = []
        while q:
            q.sort(key=lambda nid: self.nodes[nid].priority, reverse=True)
            nid = q.pop(0)
            order.append(self.nodes[nid])
            for m in self.nodes.values():
                if nid in m.depends_on:
                    in_deg[m.node_id] -= 1
                    if in_deg[m.node_id] == 0:
                        q.append(m.node_id)
        if len(order) != len(self.nodes):
            raise ValueError(f"plan {self.id} has a cycle in depends_on")
        return order

    def validate(self) -> list[str]:
        """Return a list of structural violations (empty = valid)."""
        errors: list[str] = []
        if self._find_goal() is None:
            errors.append("missing goal node")
        try:
            self.topological_order()
        except ValueError as exc:
            errors.append(str(exc))
        for n in self.nodes.values():
            if n.parent_id is not None and n.parent_id not in self.nodes:
                errors.append(f"node {n.id}: parent {n.parent_id} missing")
            for dep in n.depends_on:
                if dep not in self.nodes:
                    errors.append(f"node {n.id}: dep {dep} missing")
        return errors
