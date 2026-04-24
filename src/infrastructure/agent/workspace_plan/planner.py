"""M2 — LLM-backed :class:`GoalPlannerPort` adapter.

Wraps the existing :class:`~src.infrastructure.agent.subagent.task_decomposer.TaskDecomposer`
and promotes its :class:`SubTask` output into a full :class:`Plan` DAG. Unlike
the legacy ``_decompose_root_goal`` call site (which discarded
``target_subagent / dependencies / priority``), this adapter preserves them.

Falls back to a single-task plan if no LLM client is configured — useful for
tests and for bootstrapping without hitting an LLM quota.
"""

from __future__ import annotations

import logging
import uuid
from typing import Protocol, cast

from src.domain.model.workspace_plan import (
    AcceptanceCriterion,
    Capability,
    CriterionKind,
    Plan,
    PlanNode,
    PlanNodeId,
    PlanNodeKind,
    PlanStatus,
)
from src.domain.ports.services.goal_planner_port import (
    GoalPlannerPort,
    GoalSpec,
    PlanningContext,
    ReplanTrigger,
)

logger = logging.getLogger(__name__)


class LLMGoalPlanner(GoalPlannerPort):
    """Produces :class:`Plan` DAGs by asking a :class:`TaskDecomposer`."""

    def __init__(
        self,
        decomposer: TaskDecomposerProtocol | None = None,
        default_capability_hint: str = "codegen",
    ) -> None:
        self._decomposer = decomposer
        self._default_cap = default_capability_hint

    async def plan(self, goal: GoalSpec, ctx: PlanningContext) -> Plan:
        plan_id = self._new_id("plan")
        goal_node_id = PlanNodeId(self._new_id("node"))
        plan = Plan(
            id=plan_id,
            workspace_id=goal.workspace_id,
            goal_id=goal_node_id,
            status=PlanStatus.ACTIVE,
        )
        goal_node = PlanNode(
            id=goal_node_id.value,
            plan_id=plan_id,
            parent_id=None,
            kind=PlanNodeKind.GOAL,
            title=goal.title,
            description=goal.description,
        )
        plan.add_node(goal_node)

        decomposition = await self._decompose(goal, ctx)

        if not decomposition:
            # Single-task fallback under the goal.
            plan.add_node(
                PlanNode(
                    id=self._new_id("node"),
                    plan_id=plan_id,
                    parent_id=goal_node_id,
                    kind=PlanNodeKind.TASK,
                    title=goal.title,
                    description=goal.description,
                    recommended_capabilities=(Capability(name=self._default_cap),),
                    acceptance_criteria=(_default_llm_judge(goal.title),),
                )
            )
            return plan

        # Map subtask.id -> PlanNodeId so depends_on is properly resolved.
        id_map: dict[str, PlanNodeId] = {}
        for st in decomposition:
            nid = PlanNodeId(self._new_id("node"))
            id_map[st.id] = nid

        for st in decomposition:
            nid = id_map[st.id]
            deps = frozenset(id_map[d] for d in st.dependencies if d in id_map)
            caps: tuple[Capability, ...] = ()
            if st.target_subagent:
                caps = (Capability(name=f"agent:{st.target_subagent}", weight=2.0),)
            plan.add_node(
                PlanNode(
                    id=nid.value,
                    plan_id=plan_id,
                    parent_id=goal_node_id,
                    kind=PlanNodeKind.TASK,
                    title=st.description[:120] or f"Task {st.id}",
                    description=st.description,
                    depends_on=deps,
                    preferred_agent_id=st.target_subagent,
                    recommended_capabilities=caps,
                    priority=max(0, int(getattr(st, "priority", 0))),
                    acceptance_criteria=(_default_llm_judge(st.description),),
                )
            )
        return plan

    async def replan(self, plan: Plan, trigger: ReplanTrigger) -> Plan:
        """Minimal replan: mark the triggering node TODO and clear its attempt.

        Full structural replanning (regenerating a sub-DAG) is deferred to
        :meth:`expand`; for ``verification_failed`` / ``blocked`` we simply
        reset and let the supervisor redispatch.
        """
        if trigger.node_id is None:
            return plan
        nid = PlanNodeId(trigger.node_id)
        node = plan.nodes.get(nid)
        if node is None:
            return plan
        from dataclasses import replace

        from src.domain.model.workspace_plan import TaskExecution, TaskIntent

        plan.replace_node(
            replace(
                node,
                intent=TaskIntent.TODO,
                execution=TaskExecution.IDLE,
                current_attempt_id=None,
            )
        )
        return plan

    async def expand(self, plan: Plan, node: PlanNode, ctx: PlanningContext) -> Plan:
        """Recursively expand ``node`` into its own sub-DAG.

        Respects ``ctx.max_depth``: we walk up the parent chain and abort if
        depth is exceeded — prevents LLM-driven runaway expansion.
        """
        depth = self._depth_of(plan, node)
        if depth >= ctx.max_depth:
            logger.debug("expand aborted: depth %s >= max %s", depth, ctx.max_depth)
            return plan
        sub = await self._decompose(
            GoalSpec(
                workspace_id=plan.workspace_id,
                title=node.title,
                description=node.description,
            ),
            ctx,
        )
        if not sub or len(sub) < 2:
            return plan
        id_map: dict[str, PlanNodeId] = {st.id: PlanNodeId(self._new_id("node")) for st in sub}
        for st in sub:
            nid = id_map[st.id]
            deps = frozenset(id_map[d] for d in st.dependencies if d in id_map)
            caps: tuple[Capability, ...] = ()
            if st.target_subagent:
                caps = (Capability(name=f"agent:{st.target_subagent}", weight=2.0),)
            plan.add_node(
                PlanNode(
                    id=nid.value,
                    plan_id=plan.id,
                    parent_id=node.node_id,
                    kind=PlanNodeKind.TASK,
                    title=st.description[:120] or f"Task {st.id}",
                    description=st.description,
                    depends_on=deps,
                    preferred_agent_id=st.target_subagent,
                    recommended_capabilities=caps,
                    priority=max(0, int(getattr(st, "priority", 0))),
                    acceptance_criteria=(_default_llm_judge(st.description),),
                )
            )
        return plan

    # --- helpers --------------------------------------------------------

    async def _decompose(self, goal: GoalSpec, ctx: PlanningContext) -> list[SubTaskLike]:
        if self._decomposer is None:
            return []
        try:
            result = await self._decomposer.decompose(
                query=f"{goal.title}\n\n{goal.description}".strip(),
                conversation_context=ctx.conversation_context,
            )
        except Exception as exc:
            logger.warning("LLMGoalPlanner decompose failed: %s", exc)
            return []
        subs = [cast(SubTaskLike, sub) for sub in (getattr(result, "subtasks", ()) or ())]
        if len(subs) <= 1:
            # "No decomposition" means one big task — still return it so caller
            # treats the goal as a single-leaf plan.
            return list(subs) if subs else []
        return subs

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex[:12]}"

    def _depth_of(self, plan: Plan, node: PlanNode) -> int:
        depth = 0
        current: PlanNode | None = node
        while current is not None and current.parent_id is not None:
            depth += 1
            current = plan.nodes.get(current.parent_id)
        return depth


def _default_llm_judge(description: str) -> AcceptanceCriterion:
    """Fallback criterion — require a non-empty worker report.

    Concrete tasks should override this with ``cmd`` / ``file_exists`` /
    ``schema`` criteria. Having at least one criterion means the verifier
    can always run — no silent green. The production attempt context feeds
    terminal worker summaries into ``stdout``.
    """
    _ = description
    return AcceptanceCriterion(
        kind=CriterionKind.REGEX,
        spec={
            "pattern": r"\S",
            "source": "stdout",
        },
        description="worker report is present",
        required=True,
    )


# Structural typing shims — we don't import TaskDecomposer directly to keep
# this adapter free of heavy dependencies; real wiring is done in the DI
# container. These protocols match the public surface used above.


class SubTaskLike(Protocol):
    id: str
    description: str
    target_subagent: str | None
    dependencies: tuple[str, ...]
    priority: int


class TaskDecomposerProtocol(Protocol):  # pragma: no cover - typing only
    async def decompose(
        self, *, query: str, conversation_context: str | None = None
    ) -> DecompositionResultLike: ...


class DecompositionResultLike(Protocol):  # pragma: no cover
    subtasks: tuple[SubTaskLike, ...]
