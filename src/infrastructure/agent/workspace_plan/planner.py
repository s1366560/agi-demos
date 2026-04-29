"""M2 — LLM-backed :class:`GoalPlannerPort` adapter.

Wraps the existing :class:`~src.infrastructure.agent.subagent.task_decomposer.TaskDecomposer`
and promotes its :class:`SubTask` output into a full :class:`Plan` DAG while
preserving ``target_subagent / dependencies / priority``.

Falls back to a single-task plan if no LLM client is configured — useful for
tests and for bootstrapping without hitting an LLM quota.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Protocol, cast

from src.application.services.workspace_agent_autonomy import build_harness_preflight_checks
from src.domain.model.workspace_plan import (
    AcceptanceCriterion,
    Capability,
    CriterionKind,
    FeatureCheckpoint,
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

_COMMAND_PREFIXES = (
    "npm ",
    "pnpm ",
    "yarn ",
    "uv ",
    "pytest",
    "python ",
    "python3 ",
    "make ",
)
_SANDBOX_ROOT_RE = re.compile(r"(/workspace/[A-Za-z0-9._/-]+)")
_FILE_PATH_RE = re.compile(
    "".join(
        (
            r"(?<![A-Za-z0-9_./-])",
            r"((?:src|web|tests?|packages?|apps?|docs|scripts)/[A-Za-z0-9_./-]+",
            r"\.(?:py|ts|tsx|js|jsx|json|md|css|scss|yaml|yml))",
        )
    )
)
_ITERATION_PHASES = ("research", "plan", "implement", "test", "deploy", "review")
_SCRUM_ARTIFACT_BY_PHASE = {
    "research": "product_discovery",
    "plan": "sprint_backlog",
    "implement": "increment",
    "test": "verification",
    "deploy": "release_candidate",
    "review": "feedback",
}


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
            node_id = self._new_id("node")
            plan.add_node(
                PlanNode(
                    id=node_id,
                    plan_id=plan_id,
                    parent_id=goal_node_id,
                    kind=PlanNodeKind.TASK,
                    title=goal.title,
                    description=goal.description,
                    recommended_capabilities=(Capability(name=self._default_cap),),
                    acceptance_criteria=_default_acceptance_criteria(
                        f"{goal.title}\n{goal.description}"
                    ),
                    feature_checkpoint=_feature_checkpoint_for_task(
                        node_id=PlanNodeId(node_id),
                        title=goal.title,
                        description=goal.description,
                        sequence=1,
                    ),
                    metadata=_planner_node_metadata(
                        f"{goal.title}\n{goal.description}",
                        node_id=PlanNodeId(node_id),
                        sequence=1,
                    ),
                )
            )
            return plan

        # Map subtask.id -> PlanNodeId so depends_on is properly resolved.
        id_map: dict[str, PlanNodeId] = {}
        for st in decomposition:
            nid = PlanNodeId(self._new_id("node"))
            id_map[st.id] = nid

        for sequence, st in enumerate(decomposition, start=1):
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
                    acceptance_criteria=_default_acceptance_criteria(st.description),
                    feature_checkpoint=_feature_checkpoint_for_task(
                        node_id=nid,
                        title=st.description[:120] or f"Task {st.id}",
                        description=st.description,
                        sequence=sequence,
                    ),
                    metadata=_planner_node_metadata(
                        st.description,
                        node_id=nid,
                        sequence=sequence,
                    ),
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
        for sequence, st in enumerate(sub, start=1):
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
                    acceptance_criteria=_default_acceptance_criteria(st.description),
                    feature_checkpoint=_feature_checkpoint_for_task(
                        node_id=nid,
                        title=st.description[:120] or f"Task {st.id}",
                        description=st.description,
                        sequence=sequence,
                    ),
                    metadata=_planner_node_metadata(
                        st.description,
                        node_id=nid,
                        sequence=sequence,
                    ),
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


def _default_acceptance_criteria(description: str) -> tuple[AcceptanceCriterion, ...]:
    """Build conservative machine checks from structurally obvious task text."""

    criteria = [_default_llm_judge(description)]
    commands = _extract_candidate_commands(description)
    for command in commands:
        criteria.append(
            AcceptanceCriterion(
                kind=CriterionKind.CMD,
                spec={
                    "cmd": command,
                    "max_exit": 0,
                    "timeout": 180,
                },
                description=f"command succeeds: {command}",
                required=True,
            )
        )
    if commands:
        criteria.append(
            AcceptanceCriterion(
                kind=CriterionKind.REGEX,
                spec={"pattern": r"test_run:", "source": "execution_verifications"},
                description="test evidence is recorded",
                required=True,
            )
        )
    if _infer_write_set(description):
        criteria.append(
            AcceptanceCriterion(
                kind=CriterionKind.REGEX,
                spec={
                    "pattern": r"(commit_ref:|git_diff_summary:)",
                    "source": "evidence_refs",
                },
                description="change evidence is recorded",
                required=True,
            )
        )
    return tuple(criteria)


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
            "requires_terminal_worker_report": True,
        },
        description="worker report is present",
        required=True,
    )


def _planner_node_metadata(
    description: str,
    *,
    node_id: PlanNodeId | None = None,
    sequence: int | None = None,
) -> dict[str, object]:
    metadata: dict[str, object] = {"acceptance_source": "planner_structural_v1"}
    phase = _iteration_phase_for_sequence(sequence)
    metadata["iteration_index"] = 1
    metadata["iteration_phase"] = phase
    metadata["iteration_loop"] = "scrum_feedback_loop_v1"
    metadata["scrum_artifact"] = _SCRUM_ARTIFACT_BY_PHASE[phase]
    metadata["next_iteration_policy"] = (
        "After review feedback is recorded, create a new bounded sprint plan instead of "
        "expanding the current plan indefinitely."
    )
    if node_id is not None:
        feature_id = _feature_id(node_id=node_id, sequence=sequence or 0)
        metadata["feature_id"] = feature_id
        metadata["harness_feature_id"] = feature_id
    write_set = _infer_write_set(description)
    if write_set:
        metadata["write_set"] = list(write_set)
    commands = _extract_candidate_commands(description)
    metadata["preflight_checks"] = build_harness_preflight_checks(test_commands=commands)
    if commands:
        metadata["verification_commands"] = commands
    return metadata


def _iteration_phase_for_sequence(sequence: int | None) -> str:
    """Map planner output order to the current sprint lifecycle phase.

    The phase is a structural planning contract, not text classification: the
    decomposer is instructed to emit current-sprint tasks in this order.
    """

    if sequence is None or sequence <= 0:
        return "plan"
    return _ITERATION_PHASES[(sequence - 1) % len(_ITERATION_PHASES)]


def _feature_checkpoint_for_task(
    *,
    node_id: PlanNodeId,
    title: str,
    description: str,
    sequence: int,
) -> FeatureCheckpoint:
    return FeatureCheckpoint(
        feature_id=_feature_id(node_id=node_id, sequence=sequence),
        sequence=sequence,
        title=title,
        test_commands=tuple(_extract_candidate_commands(description)),
        expected_artifacts=_infer_write_set(description),
    )


def _feature_id(*, node_id: PlanNodeId, sequence: int) -> str:
    suffix = node_id.value.removeprefix("node-")
    if sequence > 0:
        return f"feature-{sequence:03d}-{suffix}"
    return f"feature-{suffix}"


def _extract_candidate_commands(description: str) -> list[str]:
    """Extract explicit shell commands without interpreting task intent."""

    sandbox_root = _extract_sandbox_root(description)
    candidates: list[str] = []
    for quoted in re.findall(r"`([^`\n]+)`", description):
        stripped = quoted.strip()
        if stripped.startswith(_COMMAND_PREFIXES):
            candidates.append(stripped)

    lower = description.lower()
    if "npm run typecheck" in lower and not any(
        candidate.startswith("npm run typecheck") for candidate in candidates
    ):
        candidates.append("npm run typecheck")
    if "npm test" in lower and not any(
        candidate.startswith("npm test") for candidate in candidates
    ):
        if "--runinband" in lower or "--runInBand" in description:
            candidates.append("npm test -- --runInBand --coverage=false")
        else:
            candidates.append("npm test")

    normalized: list[str] = []
    for command in candidates:
        command = command.strip()
        if not command:
            continue
        if sandbox_root and not command.startswith("cd "):
            command = f"cd {sandbox_root} && {command}"
        normalized.append(command)
    return list(dict.fromkeys(normalized))


def _extract_sandbox_root(description: str) -> str | None:
    match = _SANDBOX_ROOT_RE.search(description)
    if not match:
        return None
    return match.group(1).rstrip(".,;:)")


def _infer_write_set(description: str) -> tuple[str, ...]:
    paths = [match.group(1).rstrip(".,;:)") for match in _FILE_PATH_RE.finditer(description)]
    return tuple(dict.fromkeys(paths))


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
