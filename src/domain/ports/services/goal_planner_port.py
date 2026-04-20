"""Port: goal planner — LLM-backed decomposer of goals into Plan DAGs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from src.domain.model.workspace_plan import Plan, PlanNode


@dataclass(frozen=True)
class GoalSpec:
    """User-expressed goal with optional metadata the planner can use."""

    workspace_id: str
    title: str
    description: str = ""
    created_by: str = ""
    existing_artifacts: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PlanningContext:
    """Environment facts passed to the planner."""

    available_agent_names: tuple[str, ...] = field(default_factory=tuple)
    available_capabilities: tuple[str, ...] = field(default_factory=tuple)
    max_subtasks: int = 8
    max_depth: int = 2  # recursion limit to prevent runaway LLM
    conversation_context: str | None = None


@dataclass(frozen=True)
class ReplanTrigger:
    """Why we are asking the planner to modify an existing plan."""

    kind: str  # e.g. "verification_failed", "blocked", "user_edit"
    node_id: str | None = None
    detail: str = ""


class GoalPlannerPort(Protocol):
    """Decomposes goals into :class:`Plan` instances; can also replan in place."""

    async def plan(self, goal: GoalSpec, ctx: PlanningContext) -> Plan:
        """Produce a new plan from a goal spec."""
        ...

    async def replan(self, plan: Plan, trigger: ReplanTrigger) -> Plan:
        """Mutate an existing plan in response to failures or new info.

        Returns the (possibly new) plan. Implementations MAY return the same
        instance if mutation is done in place.
        """
        ...

    async def expand(self, plan: Plan, node: PlanNode, ctx: PlanningContext) -> Plan:
        """Recursively expand a single node into a sub-DAG.

        Called by the supervisor when a TASK node advertises
        ``metadata["has_subplan"] is True`` or when the LLM decides a node
        is too coarse. Must respect ``ctx.max_depth``.
        """
        ...
