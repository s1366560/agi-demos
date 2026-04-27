"""M1 domain unit tests — plan node, plan DAG, state machines, acceptance."""

from __future__ import annotations

import pytest

from src.domain.model.workspace_plan import (
    AcceptanceCriterion,
    Capability,
    CriterionKind,
    CriterionResult,
    Effort,
    EvidenceRef,
    ExecutionTransitionError,
    FeatureCheckpoint,
    GoalProgress,
    HandoffPackage,
    HandoffReason,
    IntentTransitionError,
    Plan,
    PlanNode,
    PlanNodeId,
    PlanNodeKind,
    PlanStatus,
    Progress,
    TaskExecution,
    TaskIntent,
    VerificationReport,
    allowed_intent_next,
    can_transition_execution,
    can_transition_intent,
    transition_execution,
    transition_intent,
)

pytestmark = pytest.mark.unit


# ---------- value objects ----------


def test_effort_validates_bounds() -> None:
    Effort(minutes=0, confidence=0)
    Effort(minutes=30, confidence=0.8)
    with pytest.raises(ValueError):
        Effort(minutes=-1)
    with pytest.raises(ValueError):
        Effort(minutes=1, confidence=1.1)


def test_progress_bounds() -> None:
    Progress(percent=0)
    Progress(percent=100, confidence=0.5)
    with pytest.raises(ValueError):
        Progress(percent=101)
    with pytest.raises(ValueError):
        Progress(percent=50, confidence=-0.1)


def test_capability_validates() -> None:
    Capability(name="web_search", weight=1.2)
    with pytest.raises(ValueError):
        Capability(name="", weight=1)
    with pytest.raises(ValueError):
        Capability(name="x", weight=0)


def test_plan_node_id_rejects_empty() -> None:
    with pytest.raises(ValueError):
        PlanNodeId("")


def test_feature_checkpoint_normalizes_lists_and_serializes() -> None:
    checkpoint = FeatureCheckpoint(
        feature_id="feature-001",
        sequence=1,
        title="Implement handoff",
        test_commands=("pytest", "pytest", " "),
        expected_artifacts=("src/foo.py", "src/foo.py"),
        worktree_path="${sandbox_code_root}/../.memstack/worktrees/attempt-1",
        branch_name="workspace/node-1-attempt-1",
        base_ref="HEAD",
    )

    assert checkpoint.test_commands == ("pytest",)
    assert checkpoint.expected_artifacts == ("src/foo.py",)
    assert checkpoint.branch_name == "workspace/node-1-attempt-1"
    assert FeatureCheckpoint.from_json(checkpoint.to_json()) == checkpoint


def test_handoff_package_requires_summary_and_serializes() -> None:
    package = HandoffPackage(
        reason=HandoffReason.CONTEXT_LIMIT,
        summary="Context almost full; continue from tests.",
        next_steps=("run pytest",),
        changed_files=("src/foo.py",),
    )

    assert HandoffPackage.from_json(package.to_json()) == package
    with pytest.raises(ValueError):
        HandoffPackage(reason=HandoffReason.MANUAL, summary=" ")


# ---------- PlanNode invariants ----------


def _goal_node(plan_id: str) -> PlanNode:
    return PlanNode(
        plan_id=plan_id,
        parent_id=None,
        kind=PlanNodeKind.GOAL,
        title="Build a blog",
    )


def test_plan_node_goal_must_have_no_parent() -> None:
    pid = "p1"
    with pytest.raises(ValueError):
        PlanNode(
            plan_id=pid,
            parent_id=PlanNodeId("whatever"),
            kind=PlanNodeKind.GOAL,
            title="g",
        )


def test_plan_node_non_goal_requires_parent() -> None:
    with pytest.raises(ValueError):
        PlanNode(
            plan_id="p1",
            parent_id=None,
            kind=PlanNodeKind.TASK,
            title="t",
        )


def test_plan_node_blank_title_rejected() -> None:
    with pytest.raises(ValueError):
        PlanNode(
            plan_id="p1",
            parent_id=PlanNodeId("g1"),
            kind=PlanNodeKind.TASK,
            title="   ",
        )


def test_plan_node_is_ready_respects_deps() -> None:
    n = PlanNode(
        plan_id="p1",
        parent_id=PlanNodeId("g1"),
        title="x",
        depends_on=frozenset({PlanNodeId("a")}),
    )
    assert not n.is_ready(frozenset())
    assert n.is_ready(frozenset({PlanNodeId("a")}))
    in_prog = n.with_intent(TaskIntent.IN_PROGRESS)
    assert not in_prog.is_ready(frozenset({PlanNodeId("a")}))


# ---------- Plan DAG ----------


def _build_plan() -> Plan:
    plan = Plan(id="p1", workspace_id="ws1", goal_id=PlanNodeId("g1"))
    goal = PlanNode(id="g1", plan_id="p1", kind=PlanNodeKind.GOAL, title="G", parent_id=None)
    plan.add_node(goal)
    t1 = PlanNode(
        id="t1",
        plan_id="p1",
        kind=PlanNodeKind.TASK,
        title="T1",
        parent_id=PlanNodeId("g1"),
    )
    plan.add_node(t1)
    t2 = PlanNode(
        id="t2",
        plan_id="p1",
        kind=PlanNodeKind.TASK,
        title="T2",
        parent_id=PlanNodeId("g1"),
        depends_on=frozenset({PlanNodeId("t1")}),
    )
    plan.add_node(t2)
    return plan


def test_plan_add_node_enforces_plan_id() -> None:
    plan = Plan(id="p1", workspace_id="ws1", goal_id=PlanNodeId("g1"))
    plan.add_node(
        _goal_node("p1").__class__(
            id="g1", plan_id="p1", kind=PlanNodeKind.GOAL, title="G", parent_id=None
        )
    )
    bad = PlanNode(
        id="t1",
        plan_id="p2",
        kind=PlanNodeKind.TASK,
        title="T",
        parent_id=PlanNodeId("g1"),
    )
    with pytest.raises(ValueError):
        plan.add_node(bad)


def test_plan_rejects_missing_parent() -> None:
    plan = Plan(id="p1", workspace_id="ws1", goal_id=PlanNodeId("g1"))
    plan.add_node(
        PlanNode(id="g1", plan_id="p1", kind=PlanNodeKind.GOAL, title="G", parent_id=None)
    )
    orphan = PlanNode(
        id="x",
        plan_id="p1",
        kind=PlanNodeKind.TASK,
        title="X",
        parent_id=PlanNodeId("missing"),
    )
    with pytest.raises(ValueError):
        plan.add_node(orphan)


def test_plan_ready_nodes_is_frontier() -> None:
    plan = _build_plan()
    ready = plan.ready_nodes()
    ids = {n.id for n in ready}
    assert ids == {"t1"}  # t2 waits on t1


def test_plan_topological_order() -> None:
    plan = _build_plan()
    order = [n.id for n in plan.topological_order()]
    assert order.index("t1") < order.index("t2")


def test_plan_detects_cycle() -> None:
    plan = Plan(id="p1", workspace_id="ws1", goal_id=PlanNodeId("g1"))
    plan.add_node(
        PlanNode(id="g1", plan_id="p1", kind=PlanNodeKind.GOAL, title="G", parent_id=None)
    )
    plan.add_node(
        PlanNode(
            id="a",
            plan_id="p1",
            kind=PlanNodeKind.TASK,
            title="A",
            parent_id=PlanNodeId("g1"),
        )
    )
    plan.add_node(
        PlanNode(
            id="b",
            plan_id="p1",
            kind=PlanNodeKind.TASK,
            title="B",
            parent_id=PlanNodeId("g1"),
            depends_on=frozenset({PlanNodeId("a")}),
        )
    )
    # Introduce cycle a->b by swapping 'a' to depend on 'b'.
    plan.replace_node(
        PlanNode(
            id="a",
            plan_id="p1",
            kind=PlanNodeKind.TASK,
            title="A",
            parent_id=PlanNodeId("g1"),
            depends_on=frozenset({PlanNodeId("b")}),
        )
    )
    with pytest.raises(ValueError):
        plan.topological_order()
    errors = plan.validate()
    assert any("cycle" in e for e in errors)


# ---------- state machine ----------


def test_intent_transitions_allowed_set() -> None:
    assert TaskIntent.IN_PROGRESS in allowed_intent_next(TaskIntent.TODO)
    assert allowed_intent_next(TaskIntent.DONE) == frozenset()


def test_intent_transition_happy_path() -> None:
    s = TaskIntent.TODO
    s = transition_intent(s, TaskIntent.IN_PROGRESS)
    s = transition_intent(s, TaskIntent.DONE)
    assert s is TaskIntent.DONE


def test_intent_transition_rejects_invalid() -> None:
    with pytest.raises(IntentTransitionError):
        transition_intent(TaskIntent.TODO, TaskIntent.DONE)
    with pytest.raises(IntentTransitionError):
        transition_intent(TaskIntent.DONE, TaskIntent.TODO)


def test_execution_transition_happy_path() -> None:
    s = TaskExecution.IDLE
    s = transition_execution(s, TaskExecution.DISPATCHED)
    s = transition_execution(s, TaskExecution.RUNNING)
    s = transition_execution(s, TaskExecution.REPORTED)
    s = transition_execution(s, TaskExecution.VERIFYING)
    s = transition_execution(s, TaskExecution.IDLE)
    assert s is TaskExecution.IDLE


def test_execution_transition_rejects_invalid() -> None:
    with pytest.raises(ExecutionTransitionError):
        transition_execution(TaskExecution.IDLE, TaskExecution.RUNNING)


def test_execution_noop_rejected() -> None:
    assert not can_transition_execution(TaskExecution.IDLE, TaskExecution.IDLE)
    assert not can_transition_intent(TaskIntent.TODO, TaskIntent.TODO)


# ---------- acceptance criteria ----------


def test_acceptance_criterion_cmd_requires_cmd() -> None:
    AcceptanceCriterion(kind=CriterionKind.CMD, spec={"cmd": "pytest", "max_exit": 0})
    with pytest.raises(ValueError):
        AcceptanceCriterion(kind=CriterionKind.CMD, spec={})


def test_acceptance_criterion_llm_judge_confidence_required() -> None:
    AcceptanceCriterion(
        kind=CriterionKind.LLM_JUDGE,
        spec={"prompt": "is complete?", "min_confidence": 0.8},
    )
    with pytest.raises(ValueError):
        AcceptanceCriterion(kind=CriterionKind.LLM_JUDGE, spec={"prompt": "x"})


def test_verification_report_passed_vs_hard_fail() -> None:
    c1 = AcceptanceCriterion(kind=CriterionKind.FILE_EXISTS, spec={"path": "/tmp/x"})
    c2 = AcceptanceCriterion(kind=CriterionKind.REGEX, spec={"pattern": "ok"}, required=False)

    passed = VerificationReport(
        node_id="n1",
        attempt_id="a1",
        results=(
            CriterionResult(criterion=c1, passed=True),
            CriterionResult(criterion=c2, passed=False, confidence=0.5),
        ),
    )
    assert passed.passed is True
    assert passed.hard_fail is False

    hard = VerificationReport(
        node_id="n1",
        attempt_id="a1",
        results=(CriterionResult(criterion=c1, passed=False, confidence=1.0, message="missing"),),
    )
    assert hard.passed is False
    assert hard.hard_fail is True
    assert "verification failed" in hard.summary()


def test_evidence_ref_requires_fields() -> None:
    EvidenceRef(kind="artifact", ref="s3://bucket/x")
    with pytest.raises(ValueError):
        EvidenceRef(kind="", ref="y")


# ---------- GoalProgress ----------


def test_goal_progress_sum_invariant() -> None:
    GoalProgress(
        workspace_id="ws",
        plan_id="p1",
        goal_node_id="g1",
        total_nodes=3,
        todo_nodes=1,
        in_progress_nodes=1,
        blocked_nodes=0,
        done_nodes=1,
        percent=33.3,
    )
    with pytest.raises(ValueError):
        GoalProgress(
            workspace_id="ws",
            plan_id="p1",
            goal_node_id="g1",
            total_nodes=3,
            todo_nodes=2,
            in_progress_nodes=2,
            blocked_nodes=0,
            done_nodes=0,
            percent=0.0,
        )


def test_goal_progress_stalled_heuristic() -> None:
    gp = GoalProgress(
        workspace_id="ws",
        plan_id="p1",
        goal_node_id="g1",
        total_nodes=2,
        todo_nodes=0,
        in_progress_nodes=0,
        blocked_nodes=2,
        done_nodes=0,
        percent=0.0,
    )
    assert gp.is_stalled is True
    assert gp.is_complete is False


# ---------- PlanStatus smoke ----------


def test_plan_status_values() -> None:
    assert PlanStatus.DRAFT.value == "draft"
    assert {s.value for s in PlanStatus} == {
        "draft",
        "active",
        "suspended",
        "completed",
        "abandoned",
    }
