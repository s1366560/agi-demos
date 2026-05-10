"""M2 — :class:`GoalPlannerPort` adapter.

Wraps a TaskDecomposerProtocol implementation and promotes its ``SubTask``
output into a full :class:`Plan` DAG while preserving
``target_subagent / dependencies / priority``.

Falls back to a single-task plan if no LLM client is configured — useful for
tests and for bootstrapping without hitting an LLM quota.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import replace
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
    TaskExecution,
    TaskIntent,
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
            r"\.(?:py|tsx|ts|jsx|js|json|md|css|scss|yaml|yml))",
        )
    )
)
_READ_ONLY_PATH_CONTEXT_RE = re.compile(
    r"(?:读取|阅读|查看|参考|根据|基于|read|inspect|review|reference|from)\s*$",
    re.IGNORECASE,
)
_WRITE_PATH_CONTEXT_RE = re.compile(
    r"(?:更新|修改|修复|补充|创建|生成|输出到?|写入|保存到?|"
    r"update|modify|fix|create|generate|write|save(?:\s+to)?|output(?:\s+to)?)\s*$",
    re.IGNORECASE,
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
_REPAIR_TITLE_PREFIX = "Repair verification blockers for "


class PlanningSuspended(Exception):
    """Raised when a planning adapter intentionally suspends kickoff."""

    def __init__(self, metadata: dict[str, object]) -> None:
        super().__init__(str(metadata.get("failure_reason") or "planning suspended"))
        self.metadata = metadata


class LLMGoalPlanner(GoalPlannerPort):
    """Produces :class:`Plan` DAGs by asking a :class:`TaskDecomposer`."""

    def __init__(
        self,
        decomposer: TaskDecomposerProtocol | None = None,
        default_capability_hint: str = "codegen",
    ) -> None:
        self._decomposer = decomposer
        self._default_cap = default_capability_hint
        self._last_decomposition_metadata: dict[str, object] = {}

    async def plan(self, goal: GoalSpec, ctx: PlanningContext) -> Plan:
        plan_id = self._new_id("plan")
        goal_node_id = PlanNodeId(self._new_id("node"))
        pipeline_required = _planning_context_requires_pipeline(ctx)
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

        try:
            decomposition = await self._decompose(goal, ctx)
        except PlanningSuspended as exc:
            failure_metadata = {
                "planning_status": "suspended",
                "planner_contract_missing": True,
                **exc.metadata,
            }
            plan.replace_node(
                replace(
                    goal_node,
                    intent=TaskIntent.BLOCKED,
                    execution=TaskExecution.IDLE,
                    metadata=failure_metadata,
                )
            )
            return replace(plan, status=PlanStatus.SUSPENDED)

        planner_metadata = dict(self._last_decomposition_metadata)
        if planner_metadata:
            plan.replace_node(
                replace(
                    goal_node,
                    metadata={
                        **dict(goal_node.metadata or {}),
                        **_goal_planning_metadata(planner_metadata),
                    },
                )
            )

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
                        f"{goal.title}\n{goal.description}",
                        sequence=1,
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
                        pipeline_required=pipeline_required,
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
                    acceptance_criteria=_default_acceptance_criteria(
                        st.description,
                        sequence=sequence,
                    ),
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
                        pipeline_required=pipeline_required,
                    ),
                )
            )
        return plan

    async def replan(self, plan: Plan, trigger: ReplanTrigger) -> Plan:
        """Replan a failed node while preserving agent-judged next-action contracts.

        Most failures are still a same-node retry. When the verifier agent explicitly
        requests a separate repair node, insert that node before retrying the original
        node so protected test/review nodes do not loop on work they cannot perform.
        """
        if trigger.node_id is None:
            return plan
        nid = PlanNodeId(trigger.node_id)
        node = plan.nodes.get(nid)
        if node is None:
            return plan
        repair_id = _ensure_repair_node_for_verification_failure(
            plan,
            node,
            trigger,
            default_capability_hint=self._default_cap,
        )
        metadata = dict(node.metadata)
        if repair_id is not None:
            metadata.update(
                {
                    "blocked_by_repair_node_id": repair_id.value,
                    "replan_source": "verification_judge_create_repair_node",
                    "replan_trigger": trigger.kind,
                }
            )
            depends_on = frozenset({*node.depends_on, repair_id})
        else:
            depends_on = node.depends_on

        plan.replace_node(
            replace(
                node,
                intent=TaskIntent.TODO,
                execution=TaskExecution.IDLE,
                current_attempt_id=None,
                depends_on=depends_on,
                metadata=metadata,
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
        pipeline_required = _planning_context_requires_pipeline(ctx)
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
                    acceptance_criteria=_default_acceptance_criteria(
                        st.description,
                        sequence=sequence,
                    ),
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
                        pipeline_required=pipeline_required,
                    ),
                )
            )
        return plan

    # --- helpers --------------------------------------------------------

    async def _decompose(self, goal: GoalSpec, ctx: PlanningContext) -> list[SubTaskLike]:
        if self._decomposer is None:
            self._last_decomposition_metadata = {}
            return []
        try:
            result = await self._decomposer.decompose(
                query=f"{goal.title}\n\n{goal.description}".strip(),
                conversation_context=ctx.conversation_context,
            )
            metadata = dict(getattr(result, "metadata", {}) or {})
            self._last_decomposition_metadata = metadata
            if metadata.get("suspend_planning"):
                raise PlanningSuspended(metadata)
        except Exception as exc:
            if isinstance(exc, PlanningSuspended):
                raise
            self._last_decomposition_metadata = {}
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


def _ensure_repair_node_for_verification_failure(
    plan: Plan,
    node: PlanNode,
    trigger: ReplanTrigger,
    *,
    default_capability_hint: str,
) -> PlanNodeId | None:
    if trigger.kind != "verification_failed":
        return None
    if node.metadata.get("last_verification_judge_next_action_kind") != "create_repair_node":
        return None
    existing = _existing_pending_repair_node(plan, node)
    if existing is not None:
        return existing.node_id
    repair_id = PlanNodeId(f"node-{uuid.uuid4().hex[:12]}")
    description = _repair_description(node, trigger)
    sequence = _next_repair_sequence(plan)
    metadata = _planner_node_metadata(description, node_id=repair_id, sequence=sequence)
    metadata.update(
        {
            "iteration_index": _repair_iteration_index(plan, node),
            "iteration_phase": "implement",
            "scrum_artifact": _SCRUM_ARTIFACT_BY_PHASE["implement"],
            "allow_verification_script_changes": True,
            "generated_from_verification_failure": True,
            "repair_for_node_id": node.id,
            "repair_source": "verification_judge_create_repair_node",
            "repair_trigger": trigger.kind,
            "source_verification_attempt_id": node.metadata.get("last_verification_attempt_id"),
            "source_verification_judge_verdict": node.metadata.get(
                "last_verification_judge_verdict"
            ),
            "source_verification_judge_next_action_kind": node.metadata.get(
                "last_verification_judge_next_action_kind"
            ),
        }
    )
    plan.add_node(
        PlanNode(
            id=repair_id.value,
            plan_id=plan.id,
            parent_id=node.parent_id,
            kind=PlanNodeKind.TASK,
            title=_repair_title(node),
            description=description,
            depends_on=node.depends_on,
            acceptance_criteria=_default_acceptance_criteria(description, sequence=sequence),
            feature_checkpoint=_feature_checkpoint_for_task(
                node_id=repair_id,
                title=_repair_title(node),
                description=description,
                sequence=sequence,
            ),
            recommended_capabilities=(Capability(name=default_capability_hint),),
            priority=max(node.priority, 1),
            metadata=metadata,
        )
    )
    return repair_id


def _existing_pending_repair_node(plan: Plan, node: PlanNode) -> PlanNode | None:
    for candidate in plan.nodes.values():
        if candidate.metadata.get("repair_for_node_id") != node.id:
            continue
        if candidate.intent is TaskIntent.DONE:
            continue
        return candidate
    return None


def _repair_iteration_index(plan: Plan, node: PlanNode) -> int:
    goal_metadata = dict(plan.goal_node.metadata or {})
    loop = goal_metadata.get("iteration_loop")
    if isinstance(loop, dict):
        loop_metadata = cast(dict[str, object], loop)
        current_iteration = _positive_iteration_index(loop_metadata.get("current_iteration"))
        if current_iteration is not None:
            return current_iteration
    return _node_iteration_index(node)


def _node_iteration_index(node: PlanNode) -> int:
    return _positive_iteration_index(dict(node.metadata or {}).get("iteration_index")) or 1


def _positive_iteration_index(value: object) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdigit():
        parsed = int(value)
        return parsed if parsed > 0 else None
    return None


def _repair_title(node: PlanNode) -> str:
    return f"{_REPAIR_TITLE_PREFIX}{_repair_subject_title(node)}"[:120]


def _repair_subject_title(node: PlanNode) -> str:
    title = node.title.strip()
    while title.startswith(_REPAIR_TITLE_PREFIX):
        title = title[len(_REPAIR_TITLE_PREFIX) :].strip()
    return title or node.id


def _repair_description(node: PlanNode, trigger: ReplanTrigger) -> str:
    next_action = str(node.metadata.get("last_verification_judge_required_next_action") or "")
    subject_title = _repair_subject_title(node)
    parts = [
        f"Repair the blockers that prevented verification of `{subject_title}`.",
        (
            "Repair execution constraints:\n"
            "- Perform the repair in the active attempt worktree only; do not require or "
            "attempt edits, merges, or artifact copying in the main checkout or sandbox_code_root.\n"
            "- When prior verifier text mentions master, main checkout, code root, or "
            "sandbox_code_root while a worktree is active, interpret it as the current "
            "attempt worktree branch unless an explicit integration node owns merging."
        ),
        next_action.strip(),
        "After the repair is complete, the original verification node will re-run.",
    ]
    if trigger.detail.strip():
        parts.append(f"Verification failure summary:\n{trigger.detail.strip()}")
    return "\n\n".join(part for part in parts if part)


def _next_repair_sequence(plan: Plan) -> int:
    current = 0
    for node in plan.nodes.values():
        if node.feature_checkpoint is not None:
            current = max(current, node.feature_checkpoint.sequence)
    return current + 1


def _default_acceptance_criteria(
    description: str,
    *,
    sequence: int | None = None,
) -> tuple[AcceptanceCriterion, ...]:
    """Build conservative machine checks from structurally obvious task text."""

    criteria = [_default_llm_judge(description)]
    phase = _iteration_phase_for_sequence(sequence)
    commands = _verification_commands_for_phase(description, phase=phase)
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
    pipeline_required: bool = False,
) -> dict[str, object]:
    metadata: dict[str, object] = {"acceptance_source": "planner_structural_v1"}
    phase = _iteration_phase_for_sequence(sequence)
    metadata["iteration_index"] = 1
    metadata["iteration_phase"] = phase
    metadata["iteration_loop"] = "scrum_feedback_loop_v1"
    metadata["scrum_artifact"] = _SCRUM_ARTIFACT_BY_PHASE[phase]
    if pipeline_required and phase in {"implement", "test", "deploy", "review"}:
        metadata["pipeline_required"] = True
        metadata["pipeline_provider"] = "sandbox_native"
        metadata["pipeline_gate"] = "harness_native_cicd_v1"
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
    commands = _verification_commands_for_phase(description, phase=phase)
    metadata["preflight_checks"] = build_harness_preflight_checks(test_commands=commands)
    if commands:
        metadata["verification_commands"] = commands
    return metadata


def _planning_context_requires_pipeline(ctx: PlanningContext) -> bool:
    value = ctx.conversation_context or ""
    return "Software workspace planning contract:" in value


def _goal_planning_metadata(metadata: dict[str, object]) -> dict[str, object]:
    output: dict[str, object] = {}
    source = metadata.get("decomposition_source")
    if source:
        output["decomposition_source"] = source
    planning_contract = metadata.get("planning_contract")
    if isinstance(planning_contract, dict):
        output["planning_contract"] = planning_contract
    return output


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
        test_commands=tuple(
            _verification_commands_for_phase(
                description,
                phase=_iteration_phase_for_sequence(sequence),
            )
        ),
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


def _verification_commands_for_phase(description: str, *, phase: str | None) -> list[str]:
    """Return commands that should be treated as verification evidence.

    Deploy nodes are validated by the sandbox-native pipeline and deployment
    health gates. Backticked service start commands in deploy prose are
    operational instructions, not root-level test commands.
    """

    if phase == "deploy":
        return []
    return _extract_candidate_commands(description)


def _extract_sandbox_root(description: str) -> str | None:
    match = _SANDBOX_ROOT_RE.search(description)
    if not match:
        return None
    return match.group(1).rstrip(".,;:)")


def _infer_write_set(description: str) -> tuple[str, ...]:
    paths = []
    for match in _FILE_PATH_RE.finditer(description):
        prefix = description[max(0, match.start() - 32) : match.start()]
        if _READ_ONLY_PATH_CONTEXT_RE.search(prefix) and not _WRITE_PATH_CONTEXT_RE.search(prefix):
            continue
        paths.append(match.group(1).rstrip(".,;:)"))
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
    reasoning: str
    is_decomposed: bool
    metadata: dict[str, object]
