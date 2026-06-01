"""Unit tests for M2–M7 infrastructure adapters + supervisor + orchestrator.

Everything here is deterministic and in-memory — no LLM, no sandbox, no Ray.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field, replace
from typing import Any

import pytest

from src.domain.model.workspace_plan import (
    AcceptanceCriterion,
    Capability,
    CriterionKind,
    CriterionResult,
    FeatureCheckpoint,
    Plan,
    PlanNode,
    PlanNodeId,
    PlanNodeKind,
    PlanStatus,
    TaskExecution,
    TaskIntent,
    VerificationReport,
)
from src.domain.ports.services.iteration_review_port import (
    IterationNextTask,
    IterationReviewContext,
    IterationReviewVerdict,
)
from src.domain.ports.services.task_allocator_port import WorkspaceAgent
from src.domain.ports.services.verifier_port import VerificationContext
from src.domain.ports.services.workspace_supervisor_decision_port import (
    WorkspaceSupervisorDecisionAction,
    WorkspaceSupervisorDecisionRequest,
    WorkspaceSupervisorDecisionResult,
)
from src.domain.ports.services.workspace_verification_judge_port import (
    WorkspaceVerificationFeedbackItem,
    WorkspaceVerificationFeedbackKind,
    WorkspaceVerificationFeedbackSeverity,
    WorkspaceVerificationFeedbackTargetLayer,
    WorkspaceVerificationJudgeRequest,
    WorkspaceVerificationJudgeResult,
    WorkspaceVerificationJudgeVerdict,
    WorkspaceVerificationNextActionKind,
    WorkspaceVerificationRecommendedAction,
)
from src.infrastructure.agent.sisyphus.builtin_agent import (
    build_builtin_workspace_iteration_reviewer_agent,
    build_builtin_workspace_verifier_agent,
)
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    LAST_WORKER_REPORT_ATTEMPT_ID,
)
from src.infrastructure.agent.workspace_plan import factory as workspace_plan_factory
from src.infrastructure.agent.workspace_plan.allocator import CapabilityAllocator
from src.infrastructure.agent.workspace_plan.blackboard import InMemoryBlackboard
from src.infrastructure.agent.workspace_plan.iteration_review import (
    WorkspaceIterationReviewAgentProvider,
)
from src.infrastructure.agent.workspace_plan.orchestrator import (
    OrchestratorConfig,
    WorkspaceOrchestrator,
)
from src.infrastructure.agent.workspace_plan.planner import LLMGoalPlanner
from src.infrastructure.agent.workspace_plan.progress import ProgressProjector
from src.infrastructure.agent.workspace_plan.repository import InMemoryPlanRepository
from src.infrastructure.agent.workspace_plan.supervisor import (
    WorkspaceSupervisor,
    _accept_ready_nodes_with_completed_repair_alternatives,
    _node_with_verification_evidence,
    _reopen_done_nodes_with_failed_pipeline,
    _reopen_done_nodes_with_failed_worktree_integration,
)
from src.infrastructure.agent.workspace_plan.verification_judge import (
    _request_payload,
)
from src.infrastructure.agent.workspace_plan.verifier import (
    AcceptanceCriterionVerifier,
    BrowserE2ECriterionRunner,
    CmdCriterionRunner,
    FileExistsCriterionRunner,
    RegexCriterionRunner,
    SchemaCriterionRunner,
    _reported_changed_paths,
)

# ---------------------------------------------------------------------------
# Fakes & helpers
# ---------------------------------------------------------------------------


@dataclass
class _FakeSubTask:
    """Structural match of subagent.task_decomposer.SubTask."""

    id: str
    description: str
    target_subagent: str | None = None
    dependencies: list[str] = field(default_factory=list)
    priority: int = 0


@dataclass
class _FakeDecomposer:
    """Structural match of TaskDecomposerProtocol."""

    result: list[_FakeSubTask]

    async def decompose(
        self,
        *,
        query: str,
        conversation_context: str | None = None,
    ) -> Any:
        from types import SimpleNamespace

        return SimpleNamespace(subtasks=list(self.result))


class _RecordingVerificationJudge:
    def __init__(self, result: WorkspaceVerificationJudgeResult) -> None:
        self.result = result
        self.requests: list[WorkspaceVerificationJudgeRequest] = []

    async def judge(
        self,
        request: WorkspaceVerificationJudgeRequest,
    ) -> WorkspaceVerificationJudgeResult:
        self.requests.append(request)
        return self.result


@dataclass
class _CapturingIterationReviewRunner:
    response: dict[str, Any]
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def run_review_turn(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.response


def _plan_with_two_tasks() -> Plan:
    plan_id = "plan-1"
    goal_id = PlanNodeId("goal-1")
    plan = Plan(
        id=plan_id,
        workspace_id="ws-1",
        goal_id=goal_id,
        status=PlanStatus.ACTIVE,
    )
    plan.add_node(
        PlanNode(
            id="goal-1",
            plan_id=plan_id,
            parent_id=None,
            kind=PlanNodeKind.GOAL,
            title="root",
        )
    )
    plan.add_node(
        PlanNode(
            id="a",
            plan_id=plan_id,
            parent_id=goal_id,
            kind=PlanNodeKind.TASK,
            title="task a",
            recommended_capabilities=(Capability(name="web_search"),),
        )
    )
    plan.add_node(
        PlanNode(
            id="b",
            plan_id=plan_id,
            parent_id=goal_id,
            kind=PlanNodeKind.TASK,
            title="task b",
            depends_on=frozenset({PlanNodeId("a")}),
            recommended_capabilities=(Capability(name="codegen"),),
        )
    )
    return plan


# ---------------------------------------------------------------------------
# M2 planner
# ---------------------------------------------------------------------------


class TestWorkspaceIterationReviewAgentProvider:
    async def test_prompt_treats_actionable_evidence_gaps_as_next_sprint_work(self) -> None:
        runner = _CapturingIterationReviewRunner(
            response={
                "verdict": "continue_next_iteration",
                "confidence": 0.82,
                "summary": "A browser parity pass is still actionable.",
                "next_sprint_goal": "Verify product parity.",
                "next_tasks": [
                    {
                        "id": "parity-1",
                        "description": "Run browser parity verification.",
                        "phase": "test",
                    }
                ],
            }
        )
        provider = WorkspaceIterationReviewAgentProvider(
            tenant_id="tenant-1",
            project_id="project-1",
            max_next_tasks=6,
            turn_runner=runner,
        )

        verdict = await provider.review(
            IterationReviewContext(
                workspace_id="ws-1",
                plan_id="plan-1",
                iteration_index=3,
                goal_title="Clone evomap.ai",
                goal_description="Verify the clone against the reference product.",
                max_next_tasks=6,
            )
        )

        agent_prompt = build_builtin_workspace_iteration_reviewer_agent(
            tenant_id="tenant-1",
            project_id="project-1",
        ).system_prompt
        user_prompt = runner.calls[0]["user_prompt"]
        user_payload = json.loads(user_prompt.split("\n\n", 1)[1].split("\n\nMaximum", 1)[0])
        assert "Missing evidence is normally next-sprint work" in agent_prompt
        assert "fix all gaps" in agent_prompt
        assert "one functional area" in agent_prompt
        assert "workspace_submit_iteration_review" in user_prompt
        assert (
            "browser_e2e workflows with screenshots and console capture"
            in (user_payload["review_policy"]["available_next_sprint_capabilities"])
        )
        assert verdict.verdict == "continue_next_iteration"
        assert verdict.next_tasks[0].description == "Run browser parity verification."

    async def test_missing_contract_submission_requires_human_review(self) -> None:
        runner = _CapturingIterationReviewRunner(response={})
        provider = WorkspaceIterationReviewAgentProvider(
            tenant_id="tenant-1",
            project_id="project-1",
            max_next_tasks=6,
            turn_runner=runner,
        )

        verdict = await provider.review(
            IterationReviewContext(
                workspace_id="ws-1",
                plan_id="plan-1",
                iteration_index=5,
                goal_title="Clone evomap.ai",
                goal_description="Verify the clone against the reference product.",
                max_next_tasks=6,
            )
        )

        assert len(runner.calls) == 2
        assert "Contract retry" in runner.calls[1]["user_prompt"]
        assert verdict.verdict == "needs_human_review"
        assert "did not submit iteration review" in verdict.summary


class TestLLMGoalPlanner:
    async def test_fallback_single_task_when_no_decomposer(self) -> None:
        planner = LLMGoalPlanner(decomposer=None)
        plan = await planner.plan(
            _goal("build a blog"),
            _ctx(),
        )
        assert plan.status is PlanStatus.ACTIVE
        assert plan._find_goal() is not None
        leaves = plan.leaf_tasks()
        assert len(leaves) == 1
        assert leaves[0].acceptance_criteria  # has at least LLM judge

    async def test_software_workspace_goal_requests_next_iteration(self) -> None:
        from src.domain.ports.services.goal_planner_port import PlanningContext

        planner = LLMGoalPlanner(decomposer=None)
        plan = await planner.plan(
            _goal("build a product"),
            PlanningContext(
                max_subtasks=4,
                max_depth=2,
                conversation_context="Software workspace planning contract: current sprint only.",
            ),
        )

        loop = plan.goal_node.metadata["iteration_loop"]
        assert loop["mode"] == "auto"
        assert loop["loop_status"] == "active"
        assert loop["current_iteration"] == 1
        assert loop["current_sprint_goal"] == "build a product"
        assert loop["operator_action"]["action"] == "operator_iteration_next_requested"
        assert loop["operator_action"]["source"] == "software_workspace_planning_contract"

    async def test_preserves_target_subagent_and_deps(self) -> None:
        sub = [
            _FakeSubTask(id="s1", description="research", target_subagent="researcher"),
            _FakeSubTask(
                id="s2",
                description="write code",
                target_subagent="coder",
                dependencies=["s1"],
                priority=5,
            ),
        ]
        planner = LLMGoalPlanner(decomposer=_FakeDecomposer(sub))
        plan = await planner.plan(_goal("build"), _ctx())
        leaves = plan.leaf_tasks()
        assert len(leaves) == 2
        assert any(n.preferred_agent_id == "researcher" for n in leaves)
        assert any(n.preferred_agent_id == "coder" for n in leaves)
        coder_node = next(n for n in leaves if n.preferred_agent_id == "coder")
        assert coder_node.priority == 5
        assert len(coder_node.depends_on) == 1  # dep on s1

    async def test_replan_resets_node_to_todo(self) -> None:
        planner = LLMGoalPlanner(decomposer=None)
        plan = await planner.plan(_goal("x"), _ctx())
        leaf = plan.leaf_tasks()[0]
        from dataclasses import replace

        plan.replace_node(
            replace(
                leaf,
                intent=TaskIntent.BLOCKED,
                execution=TaskExecution.REPORTED,
                current_attempt_id="att-1",
            )
        )
        from src.domain.ports.services.goal_planner_port import ReplanTrigger

        await planner.replan(plan, ReplanTrigger(kind="verification_failed", node_id=leaf.id))
        reset = plan.nodes[leaf.node_id]
        assert reset.intent is TaskIntent.TODO
        assert reset.execution is TaskExecution.IDLE
        assert reset.current_attempt_id is None

    async def test_replan_inserts_repair_node_when_judge_requests_one(self) -> None:
        planner = LLMGoalPlanner(decomposer=None)
        plan = await planner.plan(_goal("x"), _ctx())
        from dataclasses import replace

        plan.replace_node(
            replace(
                plan.goal_node,
                metadata={
                    **plan.goal_node.metadata,
                    "iteration_loop": {
                        "current_iteration": 5,
                        "max_iterations": 8,
                        "loop_status": "active",
                    },
                },
            )
        )
        leaf = plan.leaf_tasks()[0]
        plan.replace_node(
            replace(
                leaf,
                intent=TaskIntent.BLOCKED,
                execution=TaskExecution.REPORTED,
                current_attempt_id="att-1",
                metadata={
                    **leaf.metadata,
                    "iteration_index": 4,
                    "iteration_phase": "test",
                    "last_verification_attempt_id": "att-1",
                    "last_verification_judge_verdict": "needs_rework",
                    "last_verification_judge_next_action_kind": "create_repair_node",
                    "last_verification_judge_required_next_action": (
                        "Make E2E report paths worktree-relative before retrying."
                    ),
                },
            )
        )
        from src.domain.ports.services.goal_planner_port import ReplanTrigger

        await planner.replan(
            plan,
            ReplanTrigger(
                kind="verification_failed",
                node_id=leaf.id,
                detail="judge verdict=needs_rework",
            ),
        )

        reset = plan.nodes[leaf.node_id]
        repair_nodes = [
            node
            for node in plan.nodes.values()
            if node.metadata.get("repair_for_node_id") == leaf.id
        ]
        assert len(repair_nodes) == 1
        repair = repair_nodes[0]
        assert repair.intent is TaskIntent.TODO
        assert repair.metadata.get("allow_verification_script_changes") is not True
        assert repair.metadata["iteration_index"] == 5
        assert repair.metadata["iteration_phase"] == "test"
        assert repair.metadata["repair_source_iteration_phase"] == "test"
        assert repair.metadata["repair_source"] == "verification_judge_create_repair_node"
        assert "active attempt worktree only" in repair.description
        assert "do not require or attempt edits, merges" in repair.description
        assert "code root" in repair.description
        assert "sandbox_code_root" in repair.description
        assert repair.description.index("active attempt worktree only") < repair.description.index(
            "Make E2E report paths worktree-relative"
        )
        assert reset.intent is TaskIntent.TODO
        assert reset.execution is TaskExecution.IDLE
        assert reset.current_attempt_id is None
        assert repair.node_id in reset.depends_on
        assert reset.metadata["blocked_by_repair_node_id"] == repair.id

    async def test_replan_does_not_create_repair_node_for_stale_planner_feedback(self) -> None:
        planner = LLMGoalPlanner(decomposer=None)
        plan = await planner.plan(_goal("x"), _ctx())
        leaf = plan.leaf_tasks()[0]
        plan.replace_node(
            replace(
                leaf,
                intent=TaskIntent.BLOCKED,
                execution=TaskExecution.REPORTED,
                current_attempt_id="att-1",
                metadata={
                    **leaf.metadata,
                    "last_verification_attempt_id": "att-1",
                    "last_verification_judge_verdict": "needs_rework",
                    "last_verification_judge_next_action_kind": "create_repair_node",
                    "last_verification_feedback_items": [
                        {
                            "target_layer": "planner",
                            "feedback_kind": "stale_or_invalid_task_target",
                            "severity": "blocking",
                            "recommended_action": "obsolete_node",
                            "failure_signature": "missing-test-target:old-e2e",
                        }
                    ],
                },
            )
        )
        from src.domain.ports.services.goal_planner_port import ReplanTrigger

        await planner.replan(
            plan,
            ReplanTrigger(
                kind="verification_failed",
                node_id=leaf.id,
                detail="stale target should not spawn repair chain",
            ),
        )

        repair_nodes = [
            node
            for node in plan.nodes.values()
            if node.metadata.get("repair_for_node_id") == leaf.id
        ]
        reset = plan.nodes[leaf.node_id]
        assert repair_nodes == []
        assert reset.intent is TaskIntent.TODO
        assert reset.execution is TaskExecution.IDLE
        assert reset.current_attempt_id is None

    async def test_replan_creates_repair_node_for_sandbox_docker_runtime_feedback(self) -> None:
        planner = LLMGoalPlanner(decomposer=None)
        plan = await planner.plan(_goal("x"), _ctx())
        leaf = plan.leaf_tasks()[0]
        plan.replace_node(
            replace(
                leaf,
                intent=TaskIntent.BLOCKED,
                execution=TaskExecution.REPORTED,
                current_attempt_id="att-1",
                metadata={
                    **leaf.metadata,
                    "last_verification_attempt_id": "att-1",
                    "last_verification_judge_verdict": "needs_rework",
                    "last_verification_judge_next_action_kind": "create_repair_node",
                    "last_verification_feedback_items": [
                        {
                            "target_layer": "planner",
                            "feedback_kind": "stale_or_invalid_task_target",
                            "severity": "blocking",
                            "recommended_action": "revise_plan_node",
                            "failure_signature": "docker-runtime-unavailable-sandbox-permanent",
                        }
                    ],
                },
            )
        )
        from src.domain.ports.services.goal_planner_port import ReplanTrigger

        await planner.replan(
            plan,
            ReplanTrigger(
                kind="verification_failed",
                node_id=leaf.id,
                detail="sandbox docker runtime is unavailable",
            ),
        )

        repair = next(
            node
            for node in plan.nodes.values()
            if node.metadata.get("repair_for_node_id") == leaf.id
        )
        reset = plan.nodes[leaf.node_id]
        assert reset.metadata["blocked_by_repair_node_id"] == repair.id
        assert repair.metadata["repair_failure_signature"] == (
            "docker-runtime-unavailable-sandbox-permanent"
        )

    async def test_replan_repair_node_title_collapses_nested_repair_prefixes(self) -> None:
        planner = LLMGoalPlanner(decomposer=None)
        plan = await planner.plan(_goal("x"), _ctx())
        leaf = plan.leaf_tasks()[0]
        from dataclasses import replace

        noisy_title = (
            "Repair verification blockers for Repair verification blockers for "
            "Publish final evidence ledger"
        )
        plan.replace_node(
            replace(
                leaf,
                title=noisy_title,
                intent=TaskIntent.BLOCKED,
                execution=TaskExecution.REPORTED,
                current_attempt_id="att-1",
                metadata={
                    **leaf.metadata,
                    "iteration_index": "3",
                    "last_verification_attempt_id": "att-1",
                    "last_verification_judge_verdict": "needs_rework",
                    "last_verification_judge_next_action_kind": "create_repair_node",
                },
            )
        )
        from src.domain.ports.services.goal_planner_port import ReplanTrigger

        await planner.replan(
            plan,
            ReplanTrigger(kind="verification_failed", node_id=leaf.id),
        )

        repair = next(
            node
            for node in plan.nodes.values()
            if node.metadata.get("repair_for_node_id") == leaf.id
        )
        assert repair.title == "Repair verification blockers for Publish final evidence ledger"
        assert (
            "Repair the blockers that prevented verification of `Publish final evidence ledger`."
            in repair.description
        )
        assert "Repair verification blockers for Repair verification blockers" not in repair.title
        assert (
            "Repair verification blockers for Repair verification blockers"
            not in repair.description
        )
        assert repair.metadata["iteration_index"] == 3

    async def test_structural_checks_and_write_set_are_inferred_from_task_text(self) -> None:
        sub = [
            _FakeSubTask(
                id="s1",
                description=(
                    "Update src/sandbox/routes.ts and src/sandbox/routes.test.ts, "
                    "then run `npm test -- src/sandbox/routes.test.ts --runInBand "
                    "--coverage=false` in /workspace/my-evo."
                ),
                target_subagent="coder",
            ),
        ]
        planner = LLMGoalPlanner(decomposer=_FakeDecomposer(sub))
        plan = await planner.plan(_goal("ship route fix"), _ctx())
        leaf = plan.leaf_tasks()[0]

        assert leaf.feature_checkpoint is not None
        assert leaf.feature_checkpoint.feature_id == leaf.metadata["feature_id"]
        assert leaf.metadata["harness_feature_id"] == leaf.feature_checkpoint.feature_id
        assert leaf.metadata["iteration_index"] == 1
        assert leaf.metadata["iteration_phase"] == "research"
        assert leaf.metadata["iteration_loop"] == "scrum_feedback_loop_v1"
        assert leaf.metadata["scrum_artifact"] == "product_discovery"
        assert leaf.feature_checkpoint.sequence == 1
        assert leaf.feature_checkpoint.test_commands == (
            "cd /workspace/my-evo && npm test -- src/sandbox/routes.test.ts --runInBand --coverage=false",
        )
        assert leaf.feature_checkpoint.expected_artifacts == (
            "src/sandbox/routes.ts",
            "src/sandbox/routes.test.ts",
        )
        assert leaf.metadata["write_set"] == [
            "src/sandbox/routes.ts",
            "src/sandbox/routes.test.ts",
        ]
        commands = leaf.metadata["verification_commands"]
        assert commands == [
            "cd /workspace/my-evo && npm test -- src/sandbox/routes.test.ts --runInBand --coverage=false"
        ]
        assert [check["check_id"] for check in leaf.metadata["preflight_checks"]] == [
            "read-progress",
            "git-status",
            "test-command-1",
        ]
        assert any(crit.kind is CriterionKind.CMD for crit in leaf.acceptance_criteria)

    async def test_deploy_start_commands_are_not_treated_as_test_commands(self) -> None:
        sub = [
            _FakeSubTask(id="s1", description="Audit remaining gaps."),
            _FakeSubTask(id="s2", description="Plan the implementation."),
            _FakeSubTask(id="s3", description="Implement frontend and backend changes."),
            _FakeSubTask(
                id="s4",
                description="Run `npm test -- --runInBand` in /workspace/my-evo.",
            ),
            _FakeSubTask(
                id="s5",
                description=(
                    "Run backend `npm run dev` on port 3001, frontend `npm run dev` "
                    "on port 3002. Verify both services healthy via /health and browser."
                ),
            ),
        ]
        planner = LLMGoalPlanner(decomposer=_FakeDecomposer(sub))
        plan = await planner.plan(_goal("ship multi-service app"), _ctx())
        leaves = sorted(plan.leaf_tasks(), key=lambda node: node.priority)
        test_leaf = leaves[3]
        deploy_leaf = leaves[4]

        assert test_leaf.metadata["iteration_phase"] == "test"
        assert test_leaf.feature_checkpoint is not None
        assert test_leaf.feature_checkpoint.test_commands == (
            "cd /workspace/my-evo && npm test -- --runInBand",
        )

        assert deploy_leaf.metadata["iteration_phase"] == "deploy"
        assert deploy_leaf.feature_checkpoint is not None
        assert deploy_leaf.feature_checkpoint.test_commands == ()
        assert "verification_commands" not in deploy_leaf.metadata
        assert [check["check_id"] for check in deploy_leaf.metadata["preflight_checks"]] == [
            "read-progress",
            "git-status",
        ]
        assert not any(crit.kind is CriterionKind.CMD for crit in deploy_leaf.acceptance_criteria)

    async def test_read_only_reference_paths_are_not_inferred_as_write_sets(self) -> None:
        sub = [
            _FakeSubTask(
                id="s1",
                description=(
                    "读取 docs/GAP-EXTRACT-P0-P1.md，评估未完成项，"
                    "更新 src/components/Dashboard.tsx。"
                ),
                target_subagent="coder",
            ),
        ]
        planner = LLMGoalPlanner(decomposer=_FakeDecomposer(sub))
        plan = await planner.plan(_goal("ship gap fix"), _ctx())
        leaf = plan.leaf_tasks()[0]

        assert leaf.feature_checkpoint is not None
        assert leaf.metadata["write_set"] == ["src/components/Dashboard.tsx"]
        assert leaf.feature_checkpoint.expected_artifacts == ("src/components/Dashboard.tsx",)
        default_report_criteria = [
            crit
            for crit in leaf.acceptance_criteria
            if crit.description == "worker report is present"
        ]
        assert default_report_criteria[0].spec["requires_terminal_worker_report"] is True


# ---------------------------------------------------------------------------
# M3 allocator
# ---------------------------------------------------------------------------


class TestCapabilityAllocator:
    async def test_invalid_weights_raise(self) -> None:
        with pytest.raises(ValueError):
            CapabilityAllocator(skill_weight=0.5, tool_weight=0.5, load_weight=0.5)

    async def test_capability_match_beats_round_robin(self) -> None:
        plan = _plan_with_two_tasks()
        alloc = CapabilityAllocator()
        task_a = plan.nodes[PlanNodeId("a")]  # wants web_search
        searcher = WorkspaceAgent(
            agent_id="ag-search",
            display_name="Search",
            capabilities=frozenset({"web_search"}),
        )
        coder = WorkspaceAgent(
            agent_id="ag-code",
            display_name="Coder",
            capabilities=frozenset({"codegen"}),
        )
        out = await alloc.allocate([task_a], [searcher, coder])
        assert len(out) == 1
        assert out[0].agent_id == "ag-search"

    async def test_filters_leader_and_unavailable(self) -> None:
        plan = _plan_with_two_tasks()
        task_a = plan.nodes[PlanNodeId("a")]
        leader = WorkspaceAgent(
            agent_id="lead",
            display_name="L",
            capabilities=frozenset({"web_search"}),
            is_leader=True,
        )
        off = WorkspaceAgent(
            agent_id="off",
            display_name="O",
            capabilities=frozenset({"web_search"}),
            is_available=False,
        )
        out = await CapabilityAllocator().allocate([task_a], [leader, off])
        assert out == []

    async def test_preferred_agent_wins_on_affinity(self) -> None:
        plan = _plan_with_two_tasks()
        from dataclasses import replace

        node = replace(plan.nodes[PlanNodeId("a")], preferred_agent_id="ag-b")
        a1 = WorkspaceAgent(
            agent_id="ag-a",
            display_name="A",
            capabilities=frozenset({"web_search"}),
        )
        a2 = WorkspaceAgent(
            agent_id="ag-b",
            display_name="B",
            capabilities=frozenset({"web_search"}),
        )
        out = await CapabilityAllocator().allocate([node], [a1, a2])
        assert out[0].agent_id == "ag-b"

    async def test_missing_capabilities_prefers_general_execution_worker(self) -> None:
        node = PlanNode(
            id="unclear-node",
            plan_id="plan-1",
            parent_id=PlanNodeId("goal-1"),
            kind=PlanNodeKind.TASK,
            title="Unannotated execution task",
        )
        builder = WorkspaceAgent(
            agent_id="builder",
            display_name="Builder",
            capabilities=frozenset(
                {
                    "backend",
                    "codegen",
                    "file_edit",
                    "frontend",
                    "shell",
                    "software_development",
                    "testing",
                }
            ),
        )
        verifier = WorkspaceAgent(
            agent_id="verifier",
            display_name="Verifier",
            capabilities=frozenset({"browser_e2e", "evidence", "shell", "testing"}),
        )

        out = await CapabilityAllocator().allocate([node], [verifier, builder])

        assert len(out) == 1
        assert out[0].agent_id == "builder"

    async def test_generic_worker_capability_prefers_general_execution_worker(self) -> None:
        node = PlanNode(
            id="generic-worker-node",
            plan_id="plan-1",
            parent_id=PlanNodeId("goal-1"),
            kind=PlanNodeKind.TASK,
            title="Implement frontend and backend changes",
            recommended_capabilities=(Capability(name="agent:worker"),),
        )
        builder = WorkspaceAgent(
            agent_id="builder",
            display_name="Builder",
            capabilities=frozenset(
                {
                    "agent:worker",
                    "backend",
                    "codegen",
                    "file_edit",
                    "frontend",
                    "shell",
                    "software_development",
                    "testing",
                }
            ),
        )
        verifier = WorkspaceAgent(
            agent_id="verifier",
            display_name="Verifier",
            capabilities=frozenset({"agent:worker", "browser_e2e", "evidence", "shell"}),
        )

        out = await CapabilityAllocator().allocate([node], [verifier, builder])

        assert len(out) == 1
        assert out[0].agent_id == "builder"


# ---------------------------------------------------------------------------
# M5 verifier
# ---------------------------------------------------------------------------


class TestVerifier:
    def test_verification_judge_prompt_enforces_repository_guidance(self) -> None:
        prompt = build_builtin_workspace_verifier_agent(
            tenant_id="tenant-1",
            project_id="project-1",
        ).system_prompt

        assert "AGENTS.md and project guidance" in prompt
        assert "prove the node goal" in prompt
        assert "project-guidance noncompliance" in prompt
        assert "cross-task commit contamination" in prompt
        assert "cannot fail" in prompt
        assert "synthetic evidence" in prompt
        assert "failed or failing tests" in prompt
        assert "weaken, replace, delete, or bypass" in prompt
        assert "Attempt worktree isolation is an intentional execution contract" in prompt
        assert "Do not recommend running from the main checkout" in prompt
        assert "Do not require commit_refs to already be merged into" in prompt
        assert "active attempt worktree branch" in prompt
        assert "environment-configurable" in prompt
        assert "next_action_kind=create_repair_node" in prompt
        assert "next_action_kind=retry_same_node" in prompt
        assert "workspace_submit_verification_judgment" in prompt
        assert "feedback_items" in prompt
        assert "target_layer=planner" in prompt
        assert "failure_signature" in prompt
        assert "satisfied_guard_failures" in prompt
        assert "not an automatic rejection" in prompt
        assert "stale, nonexistent, or no longer applicable" in prompt
        assert "terminal_worker_report_completed" in prompt

    def test_iteration_reviewer_prompt_preserves_attempt_worktree_contract(self) -> None:
        prompt = build_builtin_workspace_iteration_reviewer_agent(
            tenant_id="tenant-1",
            project_id="project-1",
        ).system_prompt

        assert "attempt worktree isolation as an intentional execution contract" in prompt
        assert "Do not propose main-checkout" in prompt
        assert "Do not create next tasks whose only purpose is merging worker commits" in prompt
        assert "environment-configurable" in prompt
        assert "Keep evidence inspection bounded" in prompt

    def test_verification_judge_payload_policy_requires_guidance_evidence(self) -> None:
        payload = json.loads(
            _request_payload(
                WorkspaceVerificationJudgeRequest(
                    workspace_id="ws",
                    node_id="node-1",
                    attempt_id="att-1",
                    node_title="Implement software feature",
                    node_description="Change code and docs.",
                    task_metadata={
                        "code_context": {
                            "loaded_agents_files": ["/workspace/app/AGENTS.md"],
                            "agents_excerpt": "No generated docs without evidence.",
                        }
                    },
                    sandbox_code_root="/workspace/my-evo",
                    worktree_path="/workspace/.memstack/worktrees/attempt-1",
                    active_execution_root="/workspace/.memstack/worktrees/attempt-1",
                    worktree_isolation_active=True,
                )
            )
        )

        assert payload["sandbox"]["active_execution_root"] == (
            "/workspace/.memstack/worktrees/attempt-1"
        )
        assert payload["sandbox"]["worktree_isolation_active"] is True
        assert payload["sandbox"]["code_root_role"] == "baseline_only_when_worktree_is_active"
        assert payload["sandbox"]["verification_scope"] == "current_attempt_worktree"
        assert payload["task_metadata"]["code_context"]["loaded_agents_files"] == [
            "/workspace/app/AGENTS.md"
        ]
        guidance_policy = " ".join(payload["policy"]["repository_guidance"])
        assert "project_guidance:checked" in guidance_policy
        assert "agents_excerpt" in guidance_policy
        commit_policy = " ".join(payload["policy"]["commit_isolation"])
        assert "shared worktrees" in commit_policy
        assert "another node's artifact" in commit_policy
        assert "recent_git_status" in commit_policy
        assert "prior failure text" in commit_policy
        assert "latest_verification_results" in commit_policy
        quality_policy = " ".join(payload["policy"]["quality_evidence"])
        assert "Tests must contain assertions or checks that can fail" in quality_policy
        assert "weaker or substituted assertions" in quality_policy
        assert "bounded path, environment, or worktree-compatibility repairs" in quality_policy
        assert any(
            "allow_verification_script_changes" in item
            for item in payload["policy"]["needs_rework_for"]
        )
        assert "Performance evidence must distinguish HTTP response timing" in quality_policy
        rework_policy = " ".join(payload["policy"]["needs_rework_for"])
        assert "every branch records success" in rework_policy
        assert "synthetic benchmarks" in rework_policy
        assert "non-zero failed or failing test count" in rework_policy
        report_policy = " ".join(payload["policy"]["terminal_worker_reports"])
        assert "not an automatic verdict" in report_policy
        assert "stale, nonexistent, or no longer applicable" in report_policy
        assert "terminal_worker_report_completed" in report_policy
        isolation_policy = " ".join(payload["policy"]["attempt_worktree_isolation"])
        assert "sandbox.worktree_path is the active execution root" in isolation_policy
        assert "sandbox.active_execution_root is the only current acceptance root" in (
            isolation_policy
        )
        assert "Do not fail because sandbox.code_root" in isolation_policy
        assert "not a transient retry_infrastructure condition" in isolation_policy
        assert "Do not recommend running from the main checkout" in isolation_policy
        assert "reported commit_refs" in isolation_policy
        assert "copy or re-apply current attempt worktree commits" in isolation_policy
        assert "repair descriptions" in isolation_policy
        assert "active attempt worktree branch" in isolation_policy
        assert "environment-configurable" in isolation_policy
        assert payload["policy"]["next_action_kinds"]["create_repair_node"].startswith("Use when")
        assert "same node can fix" in payload["policy"]["next_action_kinds"]["retry_same_node"]
        feedback_policy = " ".join(payload["policy"]["feedback_routing"]["rules"])
        assert "target_layer=planner" in feedback_policy
        assert "obsolete_node" in feedback_policy
        assert "failure_signature" in feedback_policy
        repair_policy = " ".join(payload["policy"]["repair_brief_contract"])
        assert "compact repair_brief object" in repair_policy
        assert "current-attempt failures" in repair_policy

    async def test_file_exists_passes_when_artifact_present(self, tmp_path: Any) -> None:
        target = tmp_path / "out.json"
        target.write_text("{}", encoding="utf-8")
        runner = FileExistsCriterionRunner()
        crit = AcceptanceCriterion(kind=CriterionKind.FILE_EXISTS, spec={"path": str(target)})
        node = _leaf_node()
        ctx = VerificationContext(workspace_id="ws", node=node, artifacts={}, stdout="")
        result = await runner.run(crit, ctx)
        assert result.passed

    async def test_regex_matches_stdout(self) -> None:
        runner = RegexCriterionRunner()
        crit = AcceptanceCriterion(
            kind=CriterionKind.REGEX, spec={"pattern": r"OK\b", "source": "stdout"}
        )
        node = _leaf_node()
        ctx = VerificationContext(workspace_id="ws", node=node, stdout="result: OK done")
        result = await runner.run(crit, ctx)
        assert result.passed

    async def test_schema_validates_artifact(self) -> None:
        runner = SchemaCriterionRunner()
        crit = AcceptanceCriterion(
            kind=CriterionKind.SCHEMA,
            spec={
                "schema": {
                    "type": "object",
                    "required": ["foo"],
                    "properties": {"foo": {"type": "string"}},
                },
                "artifact": "payload",
            },
        )
        node = _leaf_node()
        ctx = VerificationContext(
            workspace_id="ws", node=node, artifacts={"payload": {"foo": "bar"}}
        )
        assert (await runner.run(crit, ctx)).passed
        ctx2 = VerificationContext(workspace_id="ws", node=node, artifacts={"payload": {"bar": 1}})
        assert not (await runner.run(crit, ctx2)).passed

    async def test_browser_e2e_requires_structured_browser_evidence(self) -> None:
        runner = BrowserE2ECriterionRunner()
        crit = AcceptanceCriterion(
            kind=CriterionKind.BROWSER_E2E,
            spec={"name": "checkout-flow"},
        )
        node = _leaf_node()
        ctx = VerificationContext(
            workspace_id="ws",
            node=node,
            artifacts={
                "execution_verifications": ["browser_e2e:checkout-flow"],
                "evidence_refs": ["screenshot:/tmp/checkout.png", "console_errors:0"],
            },
        )

        result = await runner.run(crit, ctx)

        assert result.passed
        assert {e.ref for e in result.evidence} == {
            "browser_e2e:checkout-flow",
            "screenshot:/tmp/checkout.png",
            "console_errors:0",
        }

    async def test_browser_e2e_rejects_missing_screenshot_or_console_evidence(self) -> None:
        runner = BrowserE2ECriterionRunner()
        crit = AcceptanceCriterion(
            kind=CriterionKind.BROWSER_E2E,
            spec={"name": "checkout-flow"},
        )
        node = _leaf_node()
        ctx = VerificationContext(
            workspace_id="ws",
            node=node,
            artifacts={"execution_verifications": ["browser_e2e:checkout-flow"]},
        )

        result = await runner.run(crit, ctx)

        assert not result.passed
        assert "screenshot evidence" in result.message
        assert "console_errors:0" in result.message

    async def test_browser_e2e_kind_requires_name_or_path(self) -> None:
        with pytest.raises(ValueError, match="BROWSER_E2E"):
            AcceptanceCriterion(kind=CriterionKind.BROWSER_E2E)

    async def test_verifier_aggregates_and_hard_fails(self) -> None:
        verifier = AcceptanceCriterionVerifier()
        node = _leaf_node(
            criteria=(
                AcceptanceCriterion(
                    kind=CriterionKind.REGEX,
                    spec={"pattern": r"SUCCESS", "source": "stdout"},
                    required=True,
                ),
            )
        )
        ctx = VerificationContext(workspace_id="ws", node=node, stdout="it said FAIL")
        rep = await verifier.verify(ctx)
        assert not rep.passed
        assert rep.hard_fail  # regex is deterministic, confidence == 1.0

    async def test_verifier_rejects_blocked_worker_report_even_with_stdout(self) -> None:
        verifier = AcceptanceCriterionVerifier()
        node = _leaf_node(
            criteria=(
                AcceptanceCriterion(
                    kind=CriterionKind.REGEX,
                    spec={"pattern": r"\S", "source": "stdout"},
                    required=True,
                ),
            )
        )
        ctx = VerificationContext(
            workspace_id="ws",
            node=node,
            stdout="recovered_stale_no_heartbeat",
            artifacts={
                "last_worker_report_type": "blocked",
                "last_worker_report_summary": "recovered_stale_no_heartbeat",
            },
        )
        rep = await verifier.verify(ctx)

        assert not rep.passed
        assert rep.hard_fail
        assert "not a completion report" in rep.summary()

    async def test_verifier_routes_explicit_blocked_worker_report_to_judge(
        self,
    ) -> None:
        judge = _RecordingVerificationJudge(
            WorkspaceVerificationJudgeResult(
                verdict=WorkspaceVerificationJudgeVerdict.NEEDS_REWORK,
                rationale="blocked report is locally repairable",
                failed_criteria=("terminal_worker_report_completed",),
                next_action_kind=WorkspaceVerificationNextActionKind.RETRY_SAME_NODE,
                confidence=0.9,
            )
        )
        verifier = AcceptanceCriterionVerifier(verification_judge=judge)
        node = _leaf_node()
        rep = await verifier.verify(
            VerificationContext(
                workspace_id="ws",
                node=node,
                artifacts={
                    "last_worker_report_type": "blocked",
                    "last_worker_report_summary": (
                        "write access outside the active attempt worktree is blocked"
                    ),
                },
            )
        )

        assert len(judge.requests) == 1
        assert not rep.passed
        assert not rep.hard_fail
        assert "judge verdict=needs_rework" in rep.summary()

    async def test_verification_judge_feedback_is_preserved_in_report_metadata(self) -> None:
        judge = _RecordingVerificationJudge(
            WorkspaceVerificationJudgeResult(
                verdict=WorkspaceVerificationJudgeVerdict.NEEDS_REWORK,
                rationale="commit evidence is missing",
                failed_criteria=("missing_evidence",),
                next_action_kind=WorkspaceVerificationNextActionKind.RETRY_SAME_NODE,
                feedback_items=(
                    WorkspaceVerificationFeedbackItem(
                        target_layer=WorkspaceVerificationFeedbackTargetLayer.WORKER,
                        feedback_kind=WorkspaceVerificationFeedbackKind.MISSING_EVIDENCE,
                        severity=WorkspaceVerificationFeedbackSeverity.BLOCKING,
                        recommended_action=WorkspaceVerificationRecommendedAction.RETRY_WORKER,
                        summary="Report a fresh commit_ref and test output.",
                        evidence_refs=("worker_report:missing_commit_ref",),
                        failure_signature="missing-commit-ref",
                    ),
                ),
                confidence=0.86,
            )
        )
        verifier = AcceptanceCriterionVerifier(verification_judge=judge)
        node = _leaf_node()

        rep = await verifier.verify(VerificationContext(workspace_id="ws", node=node))

        judge_result = next(
            result
            for result in rep.results
            if result.criterion.spec.get("name") == "workspace_verification_judge"
        )
        assert judge_result.criterion.spec["feedback_items"] == [
            {
                "target_layer": "worker",
                "feedback_kind": "missing_evidence",
                "severity": "blocking",
                "recommended_action": "retry_worker",
                "summary": "Report a fresh commit_ref and test output.",
                "evidence_refs": ["worker_report:missing_commit_ref"],
                "failure_signature": "missing-commit-ref",
            }
        ]
        evidenced = _node_with_verification_evidence(node, rep)
        assert evidenced.metadata["last_verification_feedback_items"][0]["target_layer"] == "worker"

    @pytest.mark.parametrize(
        "summary",
        [
            "litellm.APIConnectionError: Executor shutdown has been called",
            (
                "litellm.InternalServerError: AnthropicException - 400, "
                'message="Expected HTTP/, RTSP/ or ICE/"'
            ),
            "Rate limit exceeded. Please wait a moment and try again.",
            "All tool operations are timing out; filesystem appears to be unresponsive",
        ],
    )
    async def test_verifier_uses_judge_for_infrastructure_blocker_classification(
        self,
        summary: str,
    ) -> None:
        judge = _RecordingVerificationJudge(
            WorkspaceVerificationJudgeResult(
                verdict=WorkspaceVerificationJudgeVerdict.RETRY_INFRASTRUCTURE,
                rationale="structured judge classified infrastructure retry",
                failed_criteria=("terminal_worker_report_completed",),
                next_action_kind=WorkspaceVerificationNextActionKind.RETRY_SAME_NODE,
                confidence=0.8,
            )
        )
        verifier = AcceptanceCriterionVerifier(verification_judge=judge)
        node = _leaf_node()
        ctx = VerificationContext(
            workspace_id="ws",
            node=node,
            stdout=summary,
            artifacts={
                "last_worker_report_type": "blocked",
                "last_worker_report_summary": summary,
            },
        )
        rep = await verifier.verify(ctx)

        assert len(judge.requests) == 1
        assert not rep.passed
        assert not rep.hard_fail
        assert "judge verdict=retry_infrastructure" in rep.summary()

    async def test_verifier_rejects_default_report_criterion_without_completed_report(
        self,
    ) -> None:
        verifier = AcceptanceCriterionVerifier()
        node = _leaf_node(
            criteria=(
                AcceptanceCriterion(
                    kind=CriterionKind.REGEX,
                    spec={
                        "pattern": r"\S",
                        "source": "stdout",
                        "requires_terminal_worker_report": True,
                    },
                    description="worker report is present",
                    required=True,
                ),
            )
        )
        ctx = VerificationContext(workspace_id="ws", node=node, stdout="looks complete")
        rep = await verifier.verify(ctx)

        assert not rep.passed
        assert rep.hard_fail
        assert "missing completed worker report" in rep.summary()

    async def test_verifier_rejects_worker_report_from_prior_attempt(self) -> None:
        verifier = AcceptanceCriterionVerifier()
        node = _leaf_node(
            criteria=(
                AcceptanceCriterion(
                    kind=CriterionKind.REGEX,
                    spec={
                        "pattern": r"\S",
                        "source": "stdout",
                        "requires_terminal_worker_report": True,
                    },
                    description="worker report is present",
                    required=True,
                ),
            )
        )
        ctx = VerificationContext(
            workspace_id="ws",
            node=node,
            attempt_id="attempt-current",
            stdout="old report says complete",
            artifacts={
                "last_worker_report_type": "completed",
                LAST_WORKER_REPORT_ATTEMPT_ID: "attempt-old",
            },
        )

        rep = await verifier.verify(ctx)

        assert not rep.passed
        assert rep.hard_fail
        assert "not current attempt 'attempt-current'" in rep.summary()

    async def test_verifier_rejects_missing_preflight_evidence(self) -> None:
        verifier = AcceptanceCriterionVerifier()
        node = _leaf_node(
            metadata={
                "preflight_checks": [
                    {"check_id": "read-progress", "kind": "read_progress", "required": True},
                    {"check_id": "git-status", "kind": "git_status", "required": True},
                ]
            }
        )
        ctx = VerificationContext(
            workspace_id="ws",
            node=node,
            artifacts={
                "last_worker_report_type": "completed",
                "execution_verifications": ["preflight:read-progress"],
            },
        )
        rep = await verifier.verify(ctx)

        assert not rep.passed
        assert rep.hard_fail
        assert "missing preflight evidence: git-status" in rep.summary()

    async def test_verifier_accepts_structured_preflight_evidence(self) -> None:
        verifier = AcceptanceCriterionVerifier()
        node = _leaf_node(
            metadata={
                "preflight_checks": [
                    {"check_id": "read-progress", "kind": "read_progress", "required": True},
                    {"check_id": "git-status", "kind": "git_status", "required": True},
                    {"check_id": "optional", "kind": "custom", "required": False},
                ]
            }
        )
        ctx = VerificationContext(
            workspace_id="ws",
            node=node,
            artifacts={
                "last_worker_report_type": "completed",
                "execution_verifications": ["preflight:read-progress"],
                "last_worker_report_verifications": ["preflight:git-status"],
            },
        )
        rep = await verifier.verify(ctx)

        assert rep.passed
        assert any(result.message == "preflight evidence recorded" for result in rep.results)

    async def test_verifier_accepts_test_run_as_test_command_preflight_evidence(self) -> None:
        verifier = AcceptanceCriterionVerifier()
        node = _leaf_node(
            metadata={
                "preflight_checks": [
                    {"check_id": "read-progress", "kind": "read_progress", "required": True},
                    {"check_id": "git-status", "kind": "git_status", "required": True},
                    {
                        "check_id": "test-command-1",
                        "kind": "test_command",
                        "command": "npm test",
                        "required": True,
                    },
                ]
            }
        )
        ctx = VerificationContext(
            workspace_id="ws",
            node=node,
            artifacts={
                "last_worker_report_type": "completed",
                "execution_verifications": [
                    "preflight:read-progress",
                    "preflight:git-status",
                    "test_run:cd backend && jest --no-coverage -> 120 passed",
                ],
            },
        )
        rep = await verifier.verify(ctx)

        assert rep.passed
        assert any(
            result.message == "preflight evidence recorded"
            and any(evidence.ref.startswith("test_run:") for evidence in result.evidence)
            for result in rep.results
        )

    async def test_verifier_accepts_preflight_evidence_with_details(self) -> None:
        verifier = AcceptanceCriterionVerifier()
        node = _leaf_node(
            metadata={
                "preflight_checks": [
                    {"check_id": "read-progress", "kind": "read_progress", "required": True},
                    {"check_id": "git-status", "kind": "git_status", "required": True},
                ]
            }
        )
        ctx = VerificationContext(
            workspace_id="ws",
            node=node,
            artifacts={
                "last_worker_report_type": "completed",
                "last_worker_report_verifications": [
                    "preflight:read-progress:report created at /workspace/my-evo/docs/report.md",
                    "preflight:git-status:clean worktree at commit f124e8d",
                ],
            },
        )
        rep = await verifier.verify(ctx)

        assert rep.passed
        assert any(result.message == "preflight evidence recorded" for result in rep.results)

    async def test_cmd_criterion_accepts_current_structured_test_run_without_rerun(self) -> None:
        class _Sandbox:
            calls = 0

            async def run_command(self, command: str, *, timeout: int = 60) -> dict[str, Any]:
                _ = command, timeout
                self.calls += 1
                return {"exit_code": 1, "stdout": "", "stderr": "should not rerun"}

        sandbox = _Sandbox()
        verifier = AcceptanceCriterionVerifier()
        node = _leaf_node(
            criteria=(
                AcceptanceCriterion(
                    kind=CriterionKind.CMD,
                    spec={"cmd": "npm test", "max_exit": 0, "timeout": 180},
                    required=True,
                    description="command succeeds: npm test",
                ),
            )
        )
        ctx = VerificationContext(
            workspace_id="ws",
            node=node,
            sandbox=sandbox,
            artifacts={
                "execution_verifications": [
                    "test_run:cd frontend && jest --no-coverage -> 57 passed"
                ],
            },
        )

        rep = await verifier.verify(ctx)

        assert rep.passed
        assert sandbox.calls == 0
        assert any(
            result.message == "structured verification evidence recorded for cmd"
            for result in rep.results
        )

    async def test_verifier_routes_drone_docker_build_exit_one_to_worker_without_judge(
        self,
    ) -> None:
        judge = _RecordingVerificationJudge(
            WorkspaceVerificationJudgeResult(
                verdict=WorkspaceVerificationJudgeVerdict.ACCEPTED,
                rationale="should not be called for deterministic Drone build failures",
                confidence=0.99,
            )
        )
        verifier = AcceptanceCriterionVerifier(verification_judge=judge)
        node = _leaf_node(
            criteria=(
                AcceptanceCriterion(
                    kind=CriterionKind.CI_PIPELINE,
                    required=True,
                    description="Drone pipeline must pass",
                ),
            ),
            metadata={
                "pipeline_required": True,
                "pipeline_status": "failed",
                "pipeline_failure_summary": (
                    "Drone build s1366560/my-evo#88 finished with status failure; "
                    "failing stage workspace-ci/docker-build-frontend exited 1; "
                    "Next.js stack trace: npm run build failed in Dockerfile"
                ),
            },
        )
        ctx = VerificationContext(
            workspace_id="ws",
            node=node,
            attempt_id="attempt-1",
            artifacts={"candidate_artifacts": ["commit_ref:abc1234"]},
        )

        rep = await verifier.verify(ctx)

        assert not rep.passed
        assert judge.requests == []
        judge_result = next(
            result
            for result in rep.results
            if result.criterion.spec.get("name") == "workspace_verification_judge"
        )
        spec = judge_result.criterion.spec
        assert spec["judge_verdict"] == "needs_rework"
        assert "drone_docker_build_stage_failed" in spec["failed_criteria"]
        assert spec["feedback_items"][0]["target_layer"] == "worker"
        assert spec["feedback_items"][0]["failure_signature"] == "drone-docker-build-stage-failed"

    async def test_verifier_accepts_preflight_evidence_with_human_summary_separator(
        self,
    ) -> None:
        verifier = AcceptanceCriterionVerifier()
        node = _leaf_node(
            metadata={
                "preflight_checks": [
                    {"check_id": "read-progress", "kind": "read_progress", "required": True},
                    {"check_id": "git-status", "kind": "git_status", "required": True},
                ]
            }
        )
        ctx = VerificationContext(
            workspace_id="ws",
            node=node,
            artifacts={
                "last_worker_report_type": "completed",
                "last_worker_report_verifications": [
                    "preflight:read-progress - progress file inspected",
                    "preflight:git-status - clean worktree",
                ],
            },
        )
        rep = await verifier.verify(ctx)

        assert rep.passed
        assert any(result.message == "preflight evidence recorded" for result in rep.results)

    async def test_verifier_rejects_preflight_evidence_prefix_collision(self) -> None:
        verifier = AcceptanceCriterionVerifier()
        node = _leaf_node(
            metadata={
                "preflight_checks": [
                    {"check_id": "read-progress", "kind": "read_progress", "required": True},
                ]
            }
        )
        ctx = VerificationContext(
            workspace_id="ws",
            node=node,
            artifacts={
                "last_worker_report_type": "completed",
                "last_worker_report_verifications": ["preflight:read-progressive"],
            },
        )
        rep = await verifier.verify(ctx)

        assert not rep.passed
        assert "missing preflight evidence: read-progress" in rep.summary()

    async def test_verifier_rejects_missing_feature_checkpoint_evidence(self) -> None:
        verifier = AcceptanceCriterionVerifier()
        node = _leaf_node(
            metadata={
                "write_set": ["src/app.py"],
                "verification_commands": ["uv run pytest src/tests/unit/example.py"],
            },
            feature_checkpoint=FeatureCheckpoint(
                feature_id="feature-1",
                sequence=1,
                title="Feature",
                expected_artifacts=("src/app.py",),
                test_commands=("uv run pytest src/tests/unit/example.py",),
            ),
        )
        ctx = VerificationContext(
            workspace_id="ws",
            node=node,
            artifacts={"last_worker_report_type": "completed"},
        )

        rep = await verifier.verify(ctx)

        assert not rep.passed
        assert rep.hard_fail
        assert "commit_ref or git_diff_summary" in rep.summary()
        assert "test_run evidence" in rep.summary()

    async def test_verifier_accepts_feature_checkpoint_git_and_test_evidence(self) -> None:
        verifier = AcceptanceCriterionVerifier()
        node = _leaf_node(
            metadata={
                "write_set": ["src/app.py"],
                "code_context": {"sandbox_code_root": "/workspace/my-evo"},
            },
            feature_checkpoint=FeatureCheckpoint(
                feature_id="feature-1",
                sequence=1,
                title="Feature",
                expected_artifacts=("src/app.py",),
                test_commands=("uv run pytest src/tests/unit/example.py",),
            ),
        )
        ctx = VerificationContext(
            workspace_id="ws",
            node=node,
            artifacts={
                "last_worker_report_type": "completed",
                "evidence_refs": ["commit_ref:abc123", "git_diff_summary:1 file changed"],
                "execution_verifications": ["test_run:uv run pytest src/tests/unit/example.py"],
            },
        )

        rep = await verifier.verify(ctx)

        assert rep.passed
        checkpoint_result = next(
            result
            for result in rep.results
            if result.message == "feature checkpoint evidence recorded"
        )
        assert {evidence.ref for evidence in checkpoint_result.evidence} == {
            "commit_ref:abc123",
            "git_diff_summary:1 file changed",
            "test_run:uv run pytest src/tests/unit/example.py",
        }

    async def test_verifier_rejects_commit_checkpoint_with_dirty_worktree(self) -> None:
        class DirtySandbox:
            async def run_command(self, command: str, *, timeout: int = 60) -> dict[str, Any]:
                assert command == "git -C /workspace/my-evo status --short"
                assert timeout == 15
                return {
                    "exit_code": 0,
                    "stdout": " M frontend/src/components/auth/LoginForm.tsx\n",
                    "stderr": "",
                }

        verifier = AcceptanceCriterionVerifier()
        node = _leaf_node(
            metadata={
                "write_set": ["frontend/tests/E2E-TEST-RESULTS.md"],
                "code_context": {"sandbox_code_root": "/workspace/my-evo"},
            },
            feature_checkpoint=FeatureCheckpoint(
                feature_id="feature-1",
                sequence=1,
                title="E2E evidence",
                expected_artifacts=("frontend/tests/E2E-TEST-RESULTS.md",),
            ),
        )
        ctx = VerificationContext(
            workspace_id="ws",
            node=node,
            artifacts={
                "last_worker_report_type": "completed",
                "evidence_refs": ["commit_ref:78dacf1", "git_diff_summary:3 files changed"],
            },
            sandbox=DirtySandbox(),
        )

        rep = await verifier.verify(ctx)

        assert not rep.passed
        assert "uncommitted changes remain after commit_ref" in rep.summary()

    async def test_verifier_accepts_commit_checkpoint_with_generated_dirty_worktree(self) -> None:
        class DirtySandbox:
            async def run_command(self, command: str, *, timeout: int = 60) -> dict[str, Any]:
                assert command == "git -C /workspace/my-evo status --short"
                assert timeout == 15
                return {
                    "exit_code": 0,
                    "stdout": (
                        " M frontend/tsconfig.tsbuildinfo\n"
                        "?? frontend/playwright-report/index.html\n"
                    ),
                    "stderr": "",
                }

        verifier = AcceptanceCriterionVerifier()
        node = _leaf_node(
            metadata={
                "write_set": ["frontend/app/page.tsx"],
                "code_context": {"sandbox_code_root": "/workspace/my-evo"},
            },
            feature_checkpoint=FeatureCheckpoint(
                feature_id="feature-1",
                sequence=1,
                title="Generated artifact evidence",
                expected_artifacts=("frontend/app/page.tsx",),
            ),
        )
        ctx = VerificationContext(
            workspace_id="ws",
            node=node,
            artifacts={
                "last_worker_report_type": "completed",
                "evidence_refs": ["commit_ref:78dacf1", "git_diff_summary:1 file changed"],
            },
            sandbox=DirtySandbox(),
        )

        rep = await verifier.verify(ctx)

        assert rep.passed
        clean_result = next(
            result
            for result in rep.results
            if result.criterion.spec["name"] == "clean_worktree_after_commit"
        )
        assert "ignored generated artifacts" in clean_result.message

    async def test_verifier_accepts_commit_checkpoint_with_clean_worktree(self) -> None:
        class CleanSandbox:
            async def run_command(self, command: str, *, timeout: int = 60) -> dict[str, Any]:
                return {"exit_code": 0, "stdout": "", "stderr": ""}

        verifier = AcceptanceCriterionVerifier()
        node = _leaf_node(
            metadata={
                "write_set": ["src/app.py"],
                "code_context": {"sandbox_code_root": "/workspace/my-evo"},
            },
            feature_checkpoint=FeatureCheckpoint(
                feature_id="feature-1",
                sequence=1,
                title="Feature",
                expected_artifacts=("src/app.py",),
            ),
        )
        ctx = VerificationContext(
            workspace_id="ws",
            node=node,
            artifacts={
                "last_worker_report_type": "completed",
                "evidence_refs": ["commit_ref:abc123", "git_diff_summary:1 file changed"],
            },
            sandbox=CleanSandbox(),
        )

        rep = await verifier.verify(ctx)

        assert rep.passed
        assert any(result.message == "clean worktree after commit" for result in rep.results)

    async def test_current_attempt_commit_ref_runs_clean_worktree_guard_without_write_set(
        self,
    ) -> None:
        commands: list[str] = []

        class CleanSandbox:
            async def run_command(self, command: str, *, timeout: int = 60) -> dict[str, Any]:
                commands.append(command)
                return {"exit_code": 0, "stdout": "", "stderr": ""}

        judge = _RecordingVerificationJudge(
            WorkspaceVerificationJudgeResult(
                verdict=WorkspaceVerificationJudgeVerdict.ACCEPTED,
                rationale="current attempt evidence is clean",
                confidence=0.9,
            )
        )
        verifier = AcceptanceCriterionVerifier(verification_judge=judge)
        node = _leaf_node(
            metadata={"code_context": {"sandbox_code_root": "/workspace/my-evo"}},
            feature_checkpoint=FeatureCheckpoint(
                feature_id="feature-1",
                sequence=1,
                title="Repair test environment",
                test_commands=("npm test",),
                worktree_path="${sandbox_code_root}/../.memstack/worktrees/attempt-current",
            ),
        )

        rep = await verifier.verify(
            VerificationContext(
                workspace_id="ws",
                node=node,
                attempt_id="attempt-current",
                artifacts={
                    "last_worker_report_type": "completed",
                    "candidate_verifications": [
                        "preflight:git-status",
                        "test_run:117 passed 0 failed",
                        "commit_ref:abc123",
                    ],
                },
                sandbox=CleanSandbox(),
            )
        )

        assert rep.passed
        assert commands == [
            "git -C /workspace/my-evo/../.memstack/worktrees/attempt-current status --short"
        ]
        assert any(result.message == "clean worktree after commit" for result in rep.results)
        assert len(judge.requests) == 1
        request = judge.requests[0]
        assert request.sandbox_code_root == "/workspace/my-evo"
        assert request.worktree_path == ("/workspace/my-evo/../.memstack/worktrees/attempt-current")
        assert request.active_execution_root == request.worktree_path
        assert request.worktree_isolation_active is True
        assert request.recent_git_status == ""
        assert any(
            result["name"] == "clean_worktree_after_commit" and result["passed"] is True
            for result in request.latest_verification_results
        )

    @pytest.mark.parametrize(
        "stdout",
        ["", "(no output)", "Tool executed successfully (no output)"],
    )
    async def test_verifier_treats_no_output_sentinels_as_clean_worktree(
        self,
        stdout: str,
    ) -> None:
        class SentinelSandbox:
            async def run_command(self, command: str, *, timeout: int = 60) -> dict[str, Any]:
                assert command == "git -C /workspace/my-evo status --short"
                return {"exit_code": 0, "stdout": stdout, "stderr": ""}

        verifier = AcceptanceCriterionVerifier()
        node = _leaf_node(
            metadata={
                "write_set": ["src/app.py"],
                "code_context": {"sandbox_code_root": "/workspace/my-evo"},
            },
            feature_checkpoint=FeatureCheckpoint(
                feature_id="feature-1",
                sequence=1,
                title="Feature",
                expected_artifacts=("src/app.py",),
            ),
        )
        ctx = VerificationContext(
            workspace_id="75b81824-f3a1-40c4-b719-1a79740c748d",
            node=node,
            artifacts={
                "last_worker_report_type": "completed",
                "evidence_refs": ["commit_ref:78dacf1", "git_diff_summary:3 files changed"],
            },
            sandbox=SentinelSandbox(),
        )

        rep = await verifier.verify(ctx)

        assert rep.passed
        assert any(result.message == "clean worktree after commit" for result in rep.results)

    async def test_verification_judge_receives_bounded_node_attempt_and_guard_context(
        self,
    ) -> None:
        judge = _RecordingVerificationJudge(
            WorkspaceVerificationJudgeResult(
                verdict=WorkspaceVerificationJudgeVerdict.ACCEPTED,
                rationale="worker evidence satisfies the node",
                confidence=0.82,
            )
        )
        verifier = AcceptanceCriterionVerifier(verification_judge=judge)
        node = _leaf_node(
            title="Implement API slice",
            description="Wire the endpoint and tests.",
            metadata={
                "write_set": ["src/api.py"],
                "code_context": {"sandbox_code_root": "/workspace/my-evo"},
            },
            criteria=(
                AcceptanceCriterion(
                    kind=CriterionKind.REGEX,
                    spec={"pattern": r"\S", "source": "stdout"},
                    required=True,
                    description="worker report is present",
                ),
            ),
        )
        ctx = VerificationContext(
            workspace_id="ws",
            node=node,
            attempt_id="attempt-1",
            stdout="completed API implementation",
            artifacts={
                "last_worker_report_type": "completed",
                "last_worker_report_summary": "implemented API and tests",
                "candidate_artifacts": ["commit_ref:abc123"],
                "candidate_verifications": ["test_run:uv run pytest src/tests/unit/api.py"],
                "evidence_refs": ["commit_ref:abc123"],
            },
        )

        rep = await verifier.verify(ctx)

        assert rep.passed
        assert len(judge.requests) == 1
        request = judge.requests[0]
        assert request.node_title == "Implement API slice"
        assert request.node_description == "Wire the endpoint and tests."
        assert request.attempt_id == "attempt-1"
        assert "implemented API and tests" in request.worker_summary
        assert "commit_ref:abc123" in request.candidate_artifacts
        assert "test_run:uv run pytest src/tests/unit/api.py" in request.candidate_verifications
        assert request.sandbox_code_root == "/workspace/my-evo"
        assert request.worktree_path == "/workspace/my-evo"
        assert request.active_execution_root == "/workspace/my-evo"
        assert request.worktree_isolation_active is False
        assert request.latest_verification_results

    async def test_verification_judge_cannot_accept_without_required_worker_report(
        self,
    ) -> None:
        judge = _RecordingVerificationJudge(
            WorkspaceVerificationJudgeResult(
                verdict=WorkspaceVerificationJudgeVerdict.ACCEPTED,
                rationale="looks acceptable",
                confidence=0.9,
            )
        )
        verifier = AcceptanceCriterionVerifier(verification_judge=judge)
        node = _leaf_node(
            criteria=(
                AcceptanceCriterion(
                    kind=CriterionKind.REGEX,
                    spec={
                        "pattern": r"\S",
                        "source": "stdout",
                        "requires_terminal_worker_report": True,
                    },
                    required=True,
                ),
            )
        )

        rep = await verifier.verify(VerificationContext(workspace_id="ws", node=node))

        assert not rep.passed
        assert not rep.hard_fail
        assert "terminal_worker_report_completed" in rep.summary()

    async def test_verification_judge_can_accept_current_blocked_stale_target_disposition(
        self,
    ) -> None:
        judge = _RecordingVerificationJudge(
            WorkspaceVerificationJudgeResult(
                verdict=WorkspaceVerificationJudgeVerdict.ACCEPTED,
                rationale=(
                    "Fresh current-attempt grep and test evidence prove the named test target is "
                    "stale while equivalent persistence checks pass."
                ),
                satisfied_guard_failures=("terminal_worker_report_completed",),
                next_action_kind=WorkspaceVerificationNextActionKind.NONE,
                confidence=0.91,
            )
        )
        verifier = AcceptanceCriterionVerifier(verification_judge=judge)
        node = _leaf_node(
            title="Fix User preferences form exists",
            description="Investigate the reported failing selector test.",
            criteria=(
                AcceptanceCriterion(
                    kind=CriterionKind.REGEX,
                    spec={
                        "pattern": r"\S",
                        "source": "stdout",
                        "requires_terminal_worker_report": True,
                    },
                    required=True,
                ),
            ),
        )

        rep = await verifier.verify(
            VerificationContext(
                workspace_id="ws",
                node=node,
                attempt_id="attempt-current",
                stdout="target test is stale; current persistence checks pass",
                artifacts={
                    "last_worker_report_type": "blocked",
                    LAST_WORKER_REPORT_ATTEMPT_ID: "attempt-current",
                    "last_worker_report_summary": (
                        "No test named User preferences form exists exists in the active "
                        "attempt worktree; actual persistence checks pass."
                    ),
                    "candidate_artifacts": [
                        "contract_disposition:stale_target:User preferences form exists",
                        "grep_result:User preferences form exists:0 matches",
                    ],
                    "candidate_verifications": [
                        "test_run:test-data-persistence.js User preferences page accessible passed",
                        "test_run:test-data-persistence.js Local preference keys exist passed",
                    ],
                },
            )
        )

        assert rep.passed
        assert len(judge.requests) == 1
        assert any(
            "worker report type 'blocked' is not a completion report" in item
            for item in judge.requests[0].guard_failures
        )
        terminal_result = next(
            result
            for result in rep.results
            if result.criterion.spec.get("name") == "terminal_worker_report_completed"
        )
        assert terminal_result.criterion.required is False
        judge_result = next(
            result
            for result in rep.results
            if result.criterion.spec.get("name") == "workspace_verification_judge"
        )
        assert judge_result.criterion.spec["satisfied_guard_failures"] == [
            "terminal_worker_report_completed"
        ]

    async def test_verification_judge_cannot_accept_failed_test_evidence(
        self,
    ) -> None:
        judge = _RecordingVerificationJudge(
            WorkspaceVerificationJudgeResult(
                verdict=WorkspaceVerificationJudgeVerdict.ACCEPTED,
                rationale="minor failure is acceptable",
                confidence=0.9,
            )
        )
        verifier = AcceptanceCriterionVerifier(verification_judge=judge)
        node = _leaf_node(title="Run full E2E journey tests")

        rep = await verifier.verify(
            VerificationContext(
                workspace_id="ws",
                node=node,
                artifacts={
                    "last_worker_report_type": "completed",
                    "last_worker_report_summary": (
                        "Results: 22 passed, 1 failed. The single failure is minor."
                    ),
                    "candidate_verifications": [
                        "preflight:read-progress",
                        "preflight:git-status",
                        "test_run:e2e-journey-complete.js 22 passed 1 failed",
                    ],
                },
            )
        )

        assert not rep.passed
        assert "failed_test_evidence" in rep.summary()
        assert len(judge.requests) == 1
        assert any(
            "test evidence reports failing tests" in item
            for item in judge.requests[0].guard_failures
        )

    async def test_verification_judge_cannot_accept_missing_test_execution_evidence(
        self,
    ) -> None:
        judge = _RecordingVerificationJudge(
            WorkspaceVerificationJudgeResult(
                verdict=WorkspaceVerificationJudgeVerdict.ACCEPTED,
                rationale="report totals look acceptable",
                confidence=0.9,
            )
        )
        verifier = AcceptanceCriterionVerifier(verification_judge=judge)
        node = _leaf_node(title="Repair comprehensive E2E evidence")

        rep = await verifier.verify(
            VerificationContext(
                workspace_id="ws",
                node=node,
                artifacts={
                    "last_worker_report_type": "completed",
                    "last_worker_report_summary": (
                        "COMPREHENSIVE-TEST-REPORT.md was regenerated with 204/204 total. "
                        "No actual Playwright/Jest test runs were possible due to missing "
                        "node_modules in the worktree."
                    ),
                    "candidate_verifications": [
                        "preflight:read-progress",
                        "preflight:git-status",
                        "COMPREHENSIVE-TEST-REPORT.md: 204/204 total",
                        (
                            "contract_disposition:no_test_runner_available - node_modules "
                            "absent from worktree; test runs deferred to harness pipeline"
                        ),
                    ],
                },
            )
        )

        assert not rep.passed
        assert "missing_test_execution_evidence" in rep.summary()
        assert len(judge.requests) == 1
        assert any(
            "test execution evidence missing" in item for item in judge.requests[0].guard_failures
        )

    async def test_verification_judge_can_accept_failed_test_evidence_with_satisfied_guard(
        self,
    ) -> None:
        judge = _RecordingVerificationJudge(
            WorkspaceVerificationJudgeResult(
                verdict=WorkspaceVerificationJudgeVerdict.ACCEPTED,
                rationale=(
                    "Current attempt evidence includes explicit known-failure dispositions "
                    "for every remaining failing E2E case."
                ),
                satisfied_guard_failures=("failed_test_evidence",),
                confidence=0.9,
            )
        )
        verifier = AcceptanceCriterionVerifier(verification_judge=judge)
        node = _leaf_node(title="Run full E2E journey tests")

        rep = await verifier.verify(
            VerificationContext(
                workspace_id="ws",
                node=node,
                artifacts={
                    "last_worker_report_type": "completed",
                    "last_worker_report_summary": (
                        "Results: 22 passed, 1 failed with documented known-failure disposition."
                    ),
                    "candidate_verifications": [
                        "preflight:read-progress",
                        "preflight:git-status",
                        "test_run:e2e-journey-complete.js 22 passed 1 failed",
                    ],
                },
            )
        )

        assert rep.passed
        judge_result = next(
            item
            for item in rep.results
            if item.criterion.spec.get("name") == "workspace_verification_judge"
        )
        assert judge_result.criterion.spec["satisfied_guard_failures"] == ["failed_test_evidence"]
        assert len(judge.requests) == 1
        assert any(
            "test evidence reports failing tests" in item
            for item in judge.requests[0].guard_failures
        )

    async def test_verification_judge_requires_disposition_for_partial_test_contract(
        self,
    ) -> None:
        judge = _RecordingVerificationJudge(
            WorkspaceVerificationJudgeResult(
                verdict=WorkspaceVerificationJudgeVerdict.ACCEPTED,
                rationale="document looks acceptable",
                confidence=0.9,
            )
        )
        verifier = AcceptanceCriterionVerifier(verification_judge=judge)
        node = _leaf_node(
            title="Update PRE-PROD report with comprehensive test summary (202/203)",
            description="Document iteration 7 E2E 23/23 and comprehensive test summary 202/203.",
        )

        rep = await verifier.verify(
            VerificationContext(
                workspace_id="ws",
                node=node,
                artifacts={
                    "last_worker_report_type": "completed",
                    "last_worker_report_summary": "Updated release report and committed it.",
                    "candidate_artifacts": [
                        "docs/PRE-PROD-RELEASE-REPORT.md",
                        "commit_ref:9e5a5d2f",
                    ],
                    "candidate_verifications": [
                        "preflight:read-progress",
                        "preflight:git-status",
                        "commit_ref:9e5a5d2f",
                    ],
                },
            )
        )

        assert not rep.passed
        assert "failed_test_evidence" in rep.summary()
        assert len(judge.requests) == 1
        assert any("202/203" in item for item in judge.requests[0].guard_failures)

    async def test_partial_test_contract_accepts_structured_disposition_ref(
        self,
    ) -> None:
        judge = _RecordingVerificationJudge(
            WorkspaceVerificationJudgeResult(
                verdict=WorkspaceVerificationJudgeVerdict.ACCEPTED,
                rationale="explicit disposition is in current evidence",
                confidence=0.9,
            )
        )
        verifier = AcceptanceCriterionVerifier(verification_judge=judge)
        node = _leaf_node(
            title="Update PRE-PROD report with comprehensive test summary (202/203)",
            description="Document iteration 7 E2E 23/23 and comprehensive test summary 202/203.",
        )

        rep = await verifier.verify(
            VerificationContext(
                workspace_id="ws",
                node=node,
                artifacts={
                    "last_worker_report_type": "completed",
                    "last_worker_report_summary": "Updated release report and committed it.",
                    "candidate_artifacts": [
                        "docs/PRE-PROD-RELEASE-REPORT.md",
                        "commit_ref:9e5a5d2f",
                    ],
                    "candidate_verifications": [
                        "preflight:read-progress",
                        "preflight:git-status",
                        "contract_disposition:202/203 accepted by node contract; one known responsive-layout check is deferred",
                        "commit_ref:9e5a5d2f",
                    ],
                },
            )
        )

        assert rep.passed
        assert "failed_test_evidence" not in rep.summary()
        assert len(judge.requests) == 1
        assert not judge.requests[0].guard_failures

    async def test_verification_judge_rejects_partial_test_bucket_without_disposition(
        self,
    ) -> None:
        judge = _RecordingVerificationJudge(
            WorkspaceVerificationJudgeResult(
                verdict=WorkspaceVerificationJudgeVerdict.ACCEPTED,
                rationale="partial checks are informational",
                confidence=0.9,
            )
        )
        verifier = AcceptanceCriterionVerifier(verification_judge=judge)
        node = _leaf_node(title="Generate final project acceptance evidence artifact")

        rep = await verifier.verify(
            VerificationContext(
                workspace_id="ws",
                node=node,
                artifacts={
                    "last_worker_report_type": "completed",
                    "last_worker_report_summary": "Generated final acceptance evidence.",
                    "candidate_verifications": [
                        "preflight:read-progress",
                        "preflight:git-status",
                        "commit_ref:47d4c54c",
                        "test_run:comprehensive E2E 26 passed 4 partial",
                    ],
                },
            )
        )

        assert not rep.passed
        assert "failed_test_evidence" in rep.summary()
        assert len(judge.requests) == 1
        assert any("26 passed 4 partial" in item for item in judge.requests[0].guard_failures)

    async def test_failed_test_guard_allows_historical_failure_explanation_when_current_run_is_green(
        self,
    ) -> None:
        judge = _RecordingVerificationJudge(
            WorkspaceVerificationJudgeResult(
                verdict=WorkspaceVerificationJudgeVerdict.ACCEPTED,
                rationale="current evidence is green",
                confidence=0.9,
            )
        )
        verifier = AcceptanceCriterionVerifier(verification_judge=judge)
        node = _leaf_node(title="Run backend tests")

        rep = await verifier.verify(
            VerificationContext(
                workspace_id="ws",
                node=node,
                artifacts={
                    "last_worker_report_type": "completed",
                    "last_worker_report_summary": (
                        "Repair completed.\n"
                        "Root cause of 33 failing tests: missing worktree database setup.\n"
                        "Test result: npm test -> 6 suites, 117 passed, 0 failed, exit 0."
                    ),
                    "candidate_verifications": [
                        "preflight:read-progress",
                        "preflight:git-status",
                        "test_run:117 passed 0 failed npm test exit 0",
                    ],
                },
            )
        )

        assert rep.passed
        assert "failed_test_evidence" not in rep.summary()
        assert len(judge.requests) == 1
        assert not judge.requests[0].guard_failures

    async def test_failed_test_guard_ignores_stale_node_verifications_for_current_attempt(
        self,
    ) -> None:
        judge = _RecordingVerificationJudge(
            WorkspaceVerificationJudgeResult(
                verdict=WorkspaceVerificationJudgeVerdict.ACCEPTED,
                rationale="current attempt evidence is green",
                confidence=0.9,
            )
        )
        verifier = AcceptanceCriterionVerifier(verification_judge=judge)
        node = _leaf_node(
            title="Repair backend test setup",
            metadata={
                "candidate_verifications": [
                    "preflight:test-command-1 (npm test -> 84 passed 33 failed, exit 0)"
                ],
                "execution_verifications": ["test_run:84 passed 33 failed"],
            },
        )

        rep = await verifier.verify(
            VerificationContext(
                workspace_id="ws",
                node=node,
                attempt_id="attempt-current",
                artifacts={
                    "last_worker_report_type": "completed",
                    "last_worker_report_summary": (
                        "Tests now pass: npm test -> 117 passed, 0 failed, exit 0."
                    ),
                    "candidate_verifications": [
                        "preflight:read-progress",
                        "preflight:git-status",
                        "test_run:117 passed 0 failed npm test exit 0",
                    ],
                },
            )
        )

        assert rep.passed
        assert "failed_test_evidence" not in rep.summary()
        assert len(judge.requests) == 1
        assert judge.requests[0].candidate_verifications == (
            "preflight:git-status",
            "preflight:read-progress",
            "test_run:117 passed 0 failed npm test exit 0",
        )

    async def test_failed_test_guard_ignores_historical_node_description_for_current_attempt(
        self,
    ) -> None:
        judge = _RecordingVerificationJudge(
            WorkspaceVerificationJudgeResult(
                verdict=WorkspaceVerificationJudgeVerdict.ACCEPTED,
                rationale="current attempt evidence is green",
                confidence=0.9,
            )
        )
        verifier = AcceptanceCriterionVerifier(verification_judge=judge)
        node = _leaf_node(
            title="Re-run comprehensive test validation",
            description=(
                "Prior review summary: verification failed: 2/5 required criteria did not pass. "
                "Carry this node forward for a fresh attempt."
            ),
        )

        rep = await verifier.verify(
            VerificationContext(
                workspace_id="ws",
                node=node,
                attempt_id="attempt-current",
                artifacts={
                    "last_worker_report_type": "completed",
                    "last_worker_report_summary": (
                        "Current attempt completed with all required tests green: "
                        "204/204 passed, 0 failed."
                    ),
                    "candidate_verifications": [
                        "preflight:read-progress",
                        "preflight:git-status",
                        "test_run:204/204 passed 0 failed comprehensive suite",
                    ],
                },
            )
        )

        assert rep.passed
        assert "failed_test_evidence" not in rep.summary()
        assert len(judge.requests) == 1
        assert not judge.requests[0].guard_failures

    async def test_failed_test_guard_ignores_deploy_port_mapping_ratio(self) -> None:
        judge = _RecordingVerificationJudge(
            WorkspaceVerificationJudgeResult(
                verdict=WorkspaceVerificationJudgeVerdict.ACCEPTED,
                rationale="deploy repair evidence is green",
                confidence=0.9,
            )
        )
        verifier = AcceptanceCriterionVerifier(verification_judge=judge)
        node = _leaf_node(title="Validate Drone CI/CD pipeline")

        rep = await verifier.verify(
            VerificationContext(
                workspace_id="ws",
                node=node,
                attempt_id="attempt-current",
                artifacts={
                    "last_worker_report_type": "completed",
                    "last_worker_report_summary": (
                        "Validated Drone deploy repair. Root cause of build #185 failure: "
                        "old shell quotes. Fixed port mapping with workspace contract "
                        "(18080/18081), updated e2e-test E2E_BASE_URL, and backend "
                        "77 tests (6 suites) passing."
                    ),
                    "candidate_verifications": [
                        "preflight:read-progress",
                        "preflight:git-status",
                        "test_run:backend 77 tests passed (6 suites)",
                    ],
                },
            )
        )

        assert rep.passed
        assert "failed_test_evidence" not in rep.summary()
        assert len(judge.requests) == 1
        assert not judge.requests[0].guard_failures

    async def test_current_attempt_checkpoint_ignores_aggregated_task_evidence(
        self,
    ) -> None:
        judge = _RecordingVerificationJudge(
            WorkspaceVerificationJudgeResult(
                verdict=WorkspaceVerificationJudgeVerdict.ACCEPTED,
                rationale="current attempt checkpoint evidence is green",
                confidence=0.9,
            )
        )
        verifier = AcceptanceCriterionVerifier(verification_judge=judge)
        node = _leaf_node(
            title="Repair backend test setup",
            feature_checkpoint=FeatureCheckpoint(
                feature_id="feature-1",
                sequence=1,
                title="Feature",
                expected_artifacts=("backend/jest.config.js",),
                test_commands=("npm test",),
            ),
        )

        rep = await verifier.verify(
            VerificationContext(
                workspace_id="ws",
                node=node,
                attempt_id="attempt-current",
                artifacts={
                    "last_worker_report_type": "completed",
                    "last_worker_report_summary": (
                        "Current attempt: npm test -> 117 passed, 0 failed."
                    ),
                    "evidence_refs": [
                        "commit_ref:stale",
                        "test_run:84 passed 33 failed",
                    ],
                    "last_worker_report_artifacts": [
                        "git_diff_summary:stale dirty screenshots",
                    ],
                    "execution_verifications": [
                        "preflight:test-command-1 (npm test -> 84 passed 33 failed)"
                    ],
                    "candidate_artifacts": [
                        "commit_ref:current",
                        "git_diff_summary:backend test setup fixed",
                    ],
                    "candidate_verifications": [
                        "preflight:read-progress",
                        "preflight:git-status",
                        "preflight:test-command-1",
                        "test_run:117 passed 0 failed npm test exit 0",
                    ],
                },
            )
        )

        assert rep.passed
        assert "failed_test_evidence" not in rep.summary()
        checkpoint_result = next(
            result
            for result in rep.results
            if result.message == "feature checkpoint evidence recorded"
        )
        assert {evidence.ref for evidence in checkpoint_result.evidence} == {
            "commit_ref:current",
            "git_diff_summary:backend test setup fixed",
            "test_run:117 passed 0 failed npm test exit 0",
        }
        assert len(judge.requests) == 1
        assert judge.requests[0].candidate_artifacts == (
            "commit_ref:current",
            "git_diff_summary:backend test setup fixed",
        )
        assert "test_run:84 passed 33 failed" not in judge.requests[0].task_evidence_refs
        assert "evidence_refs" not in judge.requests[0].task_metadata
        assert "execution_verifications" not in judge.requests[0].task_metadata
        assert "last_worker_report_artifacts" not in judge.requests[0].task_metadata

    async def test_verification_judge_can_accept_bounded_test_infra_script_changes(
        self,
    ) -> None:
        commands: list[str] = []

        class ScriptChangeSandbox:
            async def run_command(self, command: str, *, timeout: int = 60) -> dict[str, Any]:
                commands.append(command)
                assert timeout == 15
                return {
                    "exit_code": 0,
                    "stdout": " M test-data-persistence.js\n?? fix_persistence_test.py\n",
                    "stderr": "",
                }

        judge = _RecordingVerificationJudge(
            WorkspaceVerificationJudgeResult(
                verdict=WorkspaceVerificationJudgeVerdict.ACCEPTED,
                rationale="all reported tests are green",
                confidence=0.9,
            )
        )
        verifier = AcceptanceCriterionVerifier(verification_judge=judge)
        node = _leaf_node(
            title="Re-run full E2E journey tests",
            metadata={
                "iteration_phase": "test",
                "code_context": {"sandbox_code_root": "/workspace/my-evo"},
            },
            feature_checkpoint=FeatureCheckpoint(
                feature_id="feature-1",
                sequence=1,
                title="Test verification",
                expected_artifacts=("test-results/",),
            ),
        )

        rep = await verifier.verify(
            VerificationContext(
                workspace_id="ws",
                node=node,
                artifacts={
                    "last_worker_report_type": "completed",
                    "candidate_verifications": [
                        "preflight:read-progress",
                        "preflight:git-status",
                        "test_run:test-data-persistence.js 14 passed 0 failed",
                        "git_diff_summary:test-data-persistence.js updated",
                    ],
                },
                sandbox=ScriptChangeSandbox(),
            )
        )

        assert rep.passed
        script_result = next(
            result
            for result in rep.results
            if result.criterion.spec.get("name") == "verification_script_mutation"
        )
        assert not script_result.passed
        assert not script_result.criterion.required
        assert script_result.message.startswith("advisory evidence before judge acceptance")
        assert any(
            "verification/review node changed test or audit scripts" in item
            for item in judge.requests[0].guard_failures
        )
        assert commands == ["git -C /workspace/my-evo status --short"]

    def test_verification_script_guard_ignores_reported_test_run_paths(self) -> None:
        node = _leaf_node(
            metadata={
                "iteration_phase": "test",
                "code_context": {"sandbox_code_root": "/workspace/my-evo"},
            }
        )
        ctx = VerificationContext(
            workspace_id="ws",
            node=node,
            artifacts={
                "candidate_verifications": [
                    "test_run:backend/src/auth/auth.test.ts 13 passed",
                    "git_diff:backend/src/auth/auth.test.ts +0 lines unchanged",
                    "git_diff_summary:no changes - clean worktree",
                    "changed_file:backend/src/auth/auth.test.ts",
                ],
            },
        )

        assert _reported_changed_paths(ctx) == {"backend/src/auth/auth.test.ts"}

    async def test_verification_judge_rejects_weakened_test_script_changes(self) -> None:
        class ScriptChangeSandbox:
            async def run_command(self, command: str, *, timeout: int = 60) -> dict[str, Any]:
                return {
                    "exit_code": 0,
                    "stdout": " M e2e-journey-complete.js\n",
                    "stderr": "",
                }

        judge = _RecordingVerificationJudge(
            WorkspaceVerificationJudgeResult(
                verdict=WorkspaceVerificationJudgeVerdict.NEEDS_REWORK,
                rationale="test script diff replaces failing assertions with unconditional success",
                failed_criteria=("verification_script_mutation",),
                required_next_action="restore assertions before rerunning verification",
                confidence=0.86,
            )
        )
        verifier = AcceptanceCriterionVerifier(verification_judge=judge)
        node = _leaf_node(
            title="Re-run full E2E journey tests",
            metadata={
                "iteration_phase": "test",
                "code_context": {"sandbox_code_root": "/workspace/my-evo"},
            },
            feature_checkpoint=FeatureCheckpoint(
                feature_id="feature-1",
                sequence=1,
                title="Test verification",
                expected_artifacts=("test-results/",),
            ),
        )

        rep = await verifier.verify(
            VerificationContext(
                workspace_id="ws",
                node=node,
                artifacts={
                    "last_worker_report_type": "completed",
                    "candidate_verifications": [
                        "preflight:read-progress",
                        "preflight:git-status",
                        "test_run:e2e-journey-complete.js 23 passed 0 failed",
                    ],
                },
                sandbox=ScriptChangeSandbox(),
            )
        )

        assert not rep.passed
        assert "verification_script_mutation" in rep.summary()
        assert any(
            result.criterion.spec.get("name") == "workspace_verification_judge"
            and result.criterion.spec.get("judge_verdict") == "needs_rework"
            for result in rep.results
        )

    @pytest.mark.parametrize(
        ("verdict", "passed", "hard_fail", "retryable"),
        [
            (WorkspaceVerificationJudgeVerdict.ACCEPTED, True, False, False),
            (WorkspaceVerificationJudgeVerdict.NEEDS_REWORK, False, False, False),
            (WorkspaceVerificationJudgeVerdict.BLOCKED_HUMAN_REQUIRED, False, True, False),
            (WorkspaceVerificationJudgeVerdict.RETRY_INFRASTRUCTURE, False, False, True),
        ],
    )
    async def test_verification_judge_verdict_controls_report_mapping(
        self,
        verdict: WorkspaceVerificationJudgeVerdict,
        passed: bool,
        hard_fail: bool,
        retryable: bool,
    ) -> None:
        judge = _RecordingVerificationJudge(
            WorkspaceVerificationJudgeResult(
                verdict=verdict,
                rationale=f"{verdict.value} rationale",
                failed_criteria=("criterion-a",) if not passed else (),
                required_next_action="next action",
                confidence=0.95,
            )
        )
        verifier = AcceptanceCriterionVerifier(verification_judge=judge)
        node = _leaf_node()

        rep = await verifier.verify(
            VerificationContext(
                workspace_id="ws",
                node=node,
                artifacts={"last_worker_report_type": "completed"},
            )
        )

        assert rep.passed is passed
        assert rep.hard_fail is hard_fail
        assert (
            any(
                result.criterion.spec.get("name") == "retryable_infrastructure_failure"
                for result in rep.results
            )
            is retryable
        )

    async def test_verifier_uses_artifact_code_context_for_clean_worktree(self) -> None:
        commands: list[str] = []

        class CleanSandbox:
            async def run_command(self, command: str, *, timeout: int = 60) -> dict[str, Any]:
                commands.append(command)
                return {"exit_code": 0, "stdout": "", "stderr": ""}

        verifier = AcceptanceCriterionVerifier()
        node = _leaf_node(
            metadata={"write_set": ["src/app.py"]},
            feature_checkpoint=FeatureCheckpoint(
                feature_id="feature-1",
                sequence=1,
                title="Feature",
                expected_artifacts=("src/app.py",),
            ),
        )
        ctx = VerificationContext(
            workspace_id="ws",
            node=node,
            artifacts={
                "last_worker_report_type": "completed",
                "evidence_refs": ["commit_ref:abc123", "git_diff_summary:1 file changed"],
                "code_context": {"sandbox_code_root": "/workspace/my-evo"},
            },
            sandbox=CleanSandbox(),
        )

        rep = await verifier.verify(ctx)

        assert rep.passed
        assert commands == ["git -C /workspace/my-evo status --short"]

    async def test_verifier_prefers_feature_worktree_for_clean_worktree(self) -> None:
        commands: list[str] = []

        class CleanSandbox:
            async def run_command(self, command: str, *, timeout: int = 60) -> dict[str, Any]:
                commands.append(command)
                return {"exit_code": 0, "stdout": "", "stderr": ""}

        verifier = AcceptanceCriterionVerifier()
        node = _leaf_node(
            metadata={
                "write_set": ["src/app.py"],
                "code_context": {"sandbox_code_root": "/workspace/my-evo"},
            },
            feature_checkpoint=FeatureCheckpoint(
                feature_id="feature-1",
                sequence=1,
                title="Feature",
                expected_artifacts=("src/app.py",),
                worktree_path="${sandbox_code_root}/../.memstack/worktrees/attempt-1",
            ),
        )
        ctx = VerificationContext(
            workspace_id="ws",
            node=node,
            artifacts={
                "last_worker_report_type": "completed",
                "evidence_refs": ["commit_ref:abc123", "git_diff_summary:1 file changed"],
            },
            sandbox=CleanSandbox(),
        )

        rep = await verifier.verify(ctx)

        assert rep.passed
        assert commands == [
            "git -C /workspace/my-evo/../.memstack/worktrees/attempt-1 status --short"
        ]

    async def test_cmd_runner_rewrites_code_root_command_to_feature_worktree(self) -> None:
        commands: list[str] = []

        class CleanSandbox:
            async def run_command(self, command: str, *, timeout: int = 60) -> dict[str, Any]:
                commands.append(command)
                return {"exit_code": 0, "stdout": "ok", "stderr": ""}

        node = _leaf_node(
            metadata={"code_context": {"sandbox_code_root": "/workspace/my-evo"}},
            feature_checkpoint=FeatureCheckpoint(
                feature_id="feature-1",
                sequence=1,
                title="Feature",
                expected_artifacts=("src/app.py",),
                worktree_path="${sandbox_code_root}/../.memstack/worktrees/attempt-1",
            ),
        )
        ctx = VerificationContext(
            workspace_id="ws",
            node=node,
            sandbox=CleanSandbox(),
        )
        criterion = AcceptanceCriterion(
            kind=CriterionKind.CMD,
            spec={"cmd": "cd /workspace/my-evo && npm test"},
            required=True,
        )

        result = await CmdCriterionRunner().run(criterion, ctx)

        assert result.passed
        assert commands == ["cd /workspace/my-evo/../.memstack/worktrees/attempt-1 && npm test"]

    async def test_cmd_runner_starts_relative_command_in_feature_worktree(self) -> None:
        commands: list[str] = []

        class CleanSandbox:
            async def run_command(self, command: str, *, timeout: int = 60) -> dict[str, Any]:
                commands.append(command)
                return {"exit_code": 0, "stdout": "ok", "stderr": ""}

        node = _leaf_node(
            metadata={"code_context": {"sandbox_code_root": "/workspace/my-evo"}},
            feature_checkpoint=FeatureCheckpoint(
                feature_id="feature-1",
                sequence=1,
                title="Feature",
                expected_artifacts=("src/app.py",),
                worktree_path="${sandbox_code_root}/../.memstack/worktrees/attempt-1",
            ),
        )
        ctx = VerificationContext(
            workspace_id="ws",
            node=node,
            sandbox=CleanSandbox(),
        )
        criterion = AcceptanceCriterion(
            kind=CriterionKind.CMD,
            spec={"cmd": "npm test"},
            required=True,
        )

        result = await CmdCriterionRunner().run(criterion, ctx)

        assert result.passed
        assert commands == ["cd /workspace/my-evo/../.memstack/worktrees/attempt-1 && npm test"]

    async def test_verifier_does_not_hard_fail_when_clean_worktree_check_unavailable(
        self,
    ) -> None:
        class UnavailableSandbox:
            async def run_command(self, command: str, *, timeout: int = 60) -> dict[str, Any]:
                raise RuntimeError("MCP sandbox adapter is not initialized")

        verifier = AcceptanceCriterionVerifier()
        node = _leaf_node(
            metadata={"write_set": ["src/app.py"]},
            feature_checkpoint=FeatureCheckpoint(
                feature_id="feature-1",
                sequence=1,
                title="Feature",
                expected_artifacts=("src/app.py",),
            ),
        )
        ctx = VerificationContext(
            workspace_id="ws",
            node=node,
            artifacts={
                "last_worker_report_type": "completed",
                "evidence_refs": ["commit_ref:abc123", "git_diff_summary:1 file changed"],
            },
            sandbox=UnavailableSandbox(),
        )

        rep = await verifier.verify(ctx)

        assert rep.passed
        assert any(
            result.message.startswith("clean worktree check skipped") for result in rep.results
        )

    async def test_verifier_skips_broad_clean_worktree_after_pipeline_success_without_code_root(
        self,
    ) -> None:
        class DirtySandbox:
            async def run_command(self, command: str, *, timeout: int = 60) -> dict[str, Any]:
                return {"exit_code": 0, "stdout": " M my-evo\n?? .cache/\n", "stderr": ""}

        verifier = AcceptanceCriterionVerifier()
        node = _leaf_node(
            metadata={
                "write_set": ["docs/pipeline-gate-loaded-code-smoke.md"],
                "pipeline_required": True,
                "pipeline_evidence_refs": ["ci_pipeline:passed"],
            },
            feature_checkpoint=FeatureCheckpoint(
                feature_id="feature-1",
                sequence=1,
                title="Pipeline doc",
                expected_artifacts=("docs/pipeline-gate-loaded-code-smoke.md",),
            ),
        )
        ctx = VerificationContext(
            workspace_id="ws",
            node=node,
            artifacts={
                "last_worker_report_type": "completed",
                "evidence_refs": ["commit_ref:abc123", "git_diff_summary:1 file changed"],
            },
            sandbox=DirtySandbox(),
        )

        rep = await verifier.verify(ctx)

        assert rep.passed
        assert any(
            result.message
            == "clean worktree check skipped: code root unavailable after pipeline success"
            for result in rep.results
        )

    async def test_review_phase_feature_artifacts_do_not_require_git_evidence(self) -> None:
        verifier = AcceptanceCriterionVerifier()
        node = _leaf_node(
            metadata={"iteration_phase": "review"},
            feature_checkpoint=FeatureCheckpoint(
                feature_id="feature-review",
                sequence=1,
                title="Review evidence",
                expected_artifacts=("docs/E2E-ACCEPTANCE-REPORT.md",),
            ),
        )
        ctx = VerificationContext(
            workspace_id="ws",
            node=node,
            artifacts={"last_worker_report_type": "completed"},
        )

        rep = await verifier.verify(ctx)

        assert rep.passed
        assert "missing feature checkpoint evidence" not in rep.summary()


# ---------------------------------------------------------------------------
# M6 progress projector
# ---------------------------------------------------------------------------


class TestProgressProjector:
    def test_excludes_goal_and_milestone_from_denominator(self) -> None:
        plan = _plan_with_two_tasks()
        prog = ProgressProjector().project(plan)
        assert prog.total_nodes == 2  # goal excluded
        assert prog.done_nodes == 0
        assert prog.percent == 0.0

    def test_completion_percent(self) -> None:
        plan = _plan_with_two_tasks()
        from dataclasses import replace

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(replace(a, intent=TaskIntent.DONE))
        prog = ProgressProjector().project(plan)
        assert prog.done_nodes == 1
        assert prog.percent == 50.0
        assert not prog.is_complete

    def test_is_complete_when_all_done(self) -> None:
        plan = _plan_with_two_tasks()
        from dataclasses import replace

        for nid in (PlanNodeId("a"), PlanNodeId("b")):
            plan.replace_node(replace(plan.nodes[nid], intent=TaskIntent.DONE))
        prog = ProgressProjector().project(plan)
        assert prog.is_complete


# ---------------------------------------------------------------------------
# M7 blackboard
# ---------------------------------------------------------------------------


class TestBlackboard:
    async def test_put_get_round_trip(self) -> None:
        from src.domain.ports.services.blackboard_port import BlackboardEntry

        bb = InMemoryBlackboard()
        version = await bb.put(
            BlackboardEntry(plan_id="p", key="artifact:x", value={"v": 1}, published_by="worker")
        )
        got = await bb.get(plan_id="p", key="artifact:x")
        assert got is not None
        assert got.value == {"v": 1}
        assert got.version == version

    async def test_subscribe_receives_updates(self) -> None:
        from src.domain.ports.services.blackboard_port import BlackboardEntry

        bb = InMemoryBlackboard()
        gen = bb.subscribe(plan_id="p")

        async def _next() -> Any:
            return await gen.__anext__()

        # Start consumer then publish.
        fut = asyncio.create_task(_next())
        await asyncio.sleep(0.01)
        await bb.put(BlackboardEntry(plan_id="p", key="k", value=1, published_by="a"))
        entry = await asyncio.wait_for(fut, timeout=0.5)
        assert entry.value == 1
        await gen.aclose()

    async def test_key_filter(self) -> None:
        from src.domain.ports.services.blackboard_port import BlackboardEntry

        bb = InMemoryBlackboard()
        gen = bb.subscribe(plan_id="p", keys=("want",))

        async def _next() -> Any:
            return await gen.__anext__()

        fut = asyncio.create_task(_next())
        await asyncio.sleep(0.01)
        # Publish a non-matching key — should be ignored.
        await bb.put(BlackboardEntry(plan_id="p", key="other", value=1, published_by="a"))
        await bb.put(BlackboardEntry(plan_id="p", key="want", value=2, published_by="a"))
        entry = await asyncio.wait_for(fut, timeout=0.5)
        assert entry.value == 2
        await gen.aclose()


# ---------------------------------------------------------------------------
# M4 supervisor (end-to-end integration — fakes for verifier/dispatch/agents)
# ---------------------------------------------------------------------------


class _AlwaysPassVerifier:
    async def verify(self, ctx: VerificationContext) -> VerificationReport:
        return VerificationReport(
            node_id=ctx.node.id,
            attempt_id=ctx.attempt_id,
            results=(),
        )


@dataclass
class _StaticSupervisorDecisionProvider:
    result: WorkspaceSupervisorDecisionResult
    requests: list[WorkspaceSupervisorDecisionRequest] = field(default_factory=list)

    async def decide(
        self,
        request: WorkspaceSupervisorDecisionRequest,
    ) -> WorkspaceSupervisorDecisionResult:
        self.requests.append(request)
        return self.result


class _RetryableInfrastructureVerifier:
    async def verify(self, ctx: VerificationContext) -> VerificationReport:
        return VerificationReport(
            node_id=ctx.node.id,
            attempt_id=ctx.attempt_id,
            results=(
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CUSTOM,
                        spec={"name": "retryable_infrastructure_failure"},
                        required=True,
                    ),
                    passed=False,
                    confidence=0.5,
                    message="retryable infrastructure failure; redispatch node",
                ),
            ),
        )


class _VerificationJudgeRetryVerifier:
    async def verify(self, ctx: VerificationContext) -> VerificationReport:
        return VerificationReport(
            node_id=ctx.node.id,
            attempt_id=ctx.attempt_id,
            results=(
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CUSTOM,
                        spec={
                            "name": "retryable_infrastructure_failure",
                            "judge_verdict": "retry_infrastructure",
                            "failed_criteria": ["workspace_verification_judge"],
                            "required_next_action": "retry verification judge",
                            "next_action_kind": "retry_same_node",
                        },
                        required=True,
                    ),
                    passed=False,
                    confidence=0.5,
                    message="judge verdict=retry_infrastructure; retry verification judge",
                ),
            ),
        )


class _VerificationJudgeRetryWithGuardFailureVerifier:
    async def verify(self, ctx: VerificationContext) -> VerificationReport:
        return VerificationReport(
            node_id=ctx.node.id,
            attempt_id=ctx.attempt_id,
            results=(
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CUSTOM,
                        spec={"name": "clean_worktree_after_commit"},
                        required=True,
                    ),
                    passed=False,
                    confidence=1.0,
                    message="uncommitted changes remain after commit_ref: ?? test/",
                ),
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CUSTOM,
                        spec={
                            "name": "retryable_infrastructure_failure",
                            "judge_verdict": "retry_infrastructure",
                            "failed_criteria": ["workspace_verification_judge"],
                            "required_next_action": "retry verification judge",
                            "next_action_kind": "retry_same_node",
                        },
                        required=True,
                    ),
                    passed=False,
                    confidence=0.5,
                    message="judge verdict=retry_infrastructure; retry verification judge",
                ),
            ),
        )


class _PipelineRuntimeFailureWithJudgeRetryVerifier:
    async def verify(self, ctx: VerificationContext) -> VerificationReport:
        return VerificationReport(
            node_id=ctx.node.id,
            attempt_id=ctx.attempt_id,
            results=(
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CI_PIPELINE,
                        required=True,
                    ),
                    passed=False,
                    confidence=0.8,
                    message=(
                        "harness-native CI pipeline failed: fatal: unable to access "
                        "'https://github.com/s1366560/my-evo.git/': Failed to connect "
                        "to github.com port 443; failing stage source_publish exited 1"
                    ),
                ),
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CUSTOM,
                        spec={
                            "name": "retryable_infrastructure_failure",
                            "judge_verdict": "retry_infrastructure",
                            "failed_criteria": ["workspace_verification_judge"],
                            "required_next_action": "retry verification judge",
                            "next_action_kind": "retry_same_node",
                            "feedback_items": [
                                {
                                    "target_layer": "runtime",
                                    "feedback_kind": "runtime_infra_failure",
                                    "severity": "warning",
                                    "recommended_action": "retry_infra",
                                    "failure_signature": "workspace_verification_judge_failed",
                                }
                            ],
                        },
                        required=True,
                    ),
                    passed=False,
                    confidence=0.5,
                    message="judge verdict=retry_infrastructure; retry verification judge",
                ),
            ),
        )


class _VerificationJudgeRepairInfrastructureVerifier:
    async def verify(self, ctx: VerificationContext) -> VerificationReport:
        return VerificationReport(
            node_id=ctx.node.id,
            attempt_id=ctx.attempt_id,
            results=(
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CUSTOM,
                        spec={
                            "name": "retryable_infrastructure_failure",
                            "judge_verdict": "retry_infrastructure",
                            "failed_criteria": ["sandbox-no-docker-runtime"],
                            "required_next_action": (
                                "Provide Docker runtime access in sandbox or revise verification "
                                "to use Drone and registry API evidence."
                            ),
                            "next_action_kind": "retry_same_node",
                            "feedback_items": [
                                {
                                    "target_layer": "runtime",
                                    "recommended_action": "retry_infra",
                                    "failure_signature": "sandbox-no-docker-runtime",
                                }
                            ],
                        },
                        required=True,
                    ),
                    passed=False,
                    confidence=0.5,
                    message="judge verdict=retry_infrastructure; sandbox lacks Docker runtime",
                ),
            ),
        )


class _BlockedHumanDockerRuntimeVerifier:
    async def verify(self, ctx: VerificationContext) -> VerificationReport:
        return VerificationReport(
            node_id=ctx.node.id,
            attempt_id=ctx.attempt_id,
            results=(
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CUSTOM,
                        spec={
                            "name": "workspace_verification_judge",
                            "judge_verdict": "blocked_human_required",
                            "failed_criteria": ["terminal_worker_report_completed"],
                            "required_next_action": (
                                "Enable Docker-in-Docker in the sandbox or revise the "
                                "task to use registry evidence."
                            ),
                            "next_action_kind": "retry_same_node",
                            "feedback_items": [
                                {
                                    "target_layer": "runtime",
                                    "recommended_action": "retry_infra",
                                    "failure_signature": "docker-runtime-unavailable-sandbox",
                                    "summary": "Docker runtime is unavailable in the sandbox.",
                                }
                            ],
                        },
                        required=True,
                    ),
                    passed=False,
                    confidence=0.95,
                    message="judge verdict=blocked_human_required; sandbox lacks Docker runtime",
                ),
            ),
        )


class _VerifierShouldNotRun:
    async def verify(self, ctx: VerificationContext) -> VerificationReport:
        raise AssertionError(f"verifier should not run for {ctx.node.id}")


class _VerificationJudgeRepairVerifier:
    async def verify(self, ctx: VerificationContext) -> VerificationReport:
        return VerificationReport(
            node_id=ctx.node.id,
            attempt_id=ctx.attempt_id,
            results=(
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CUSTOM,
                        spec={
                            "name": "workspace_verification_judge",
                            "judge_verdict": "needs_rework",
                            "failed_criteria": ["verification_script_mutation"],
                            "required_next_action": (
                                "Make E2E report paths worktree-relative before retrying."
                            ),
                            "next_action_kind": "create_repair_node",
                        },
                        required=True,
                    ),
                    passed=False,
                    confidence=0.7,
                    message="judge verdict=needs_rework; create repair node",
                ),
            ),
        )


class _VerificationJudgeObsoleteVerifier:
    async def verify(self, ctx: VerificationContext) -> VerificationReport:
        return VerificationReport(
            node_id=ctx.node.id,
            attempt_id=ctx.attempt_id,
            results=(
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CUSTOM,
                        spec={
                            "name": "workspace_verification_judge",
                            "judge_verdict": "needs_rework",
                            "failed_criteria": ["stale_or_invalid_task_target"],
                            "required_next_action": "obsolete this stale test target",
                            "next_action_kind": "retry_same_node",
                            "feedback_items": [
                                {
                                    "target_layer": "planner",
                                    "feedback_kind": "stale_or_invalid_task_target",
                                    "severity": "blocking",
                                    "recommended_action": "obsolete_node",
                                    "failure_signature": "missing-test-target:old-e2e",
                                }
                            ],
                        },
                        required=True,
                    ),
                    passed=False,
                    confidence=0.7,
                    message="judge verdict=needs_rework; planner stale target feedback",
                ),
            ),
        )


class _MixedPipelineAndCustomFailureVerifier:
    async def verify(self, ctx: VerificationContext) -> VerificationReport:
        return VerificationReport(
            node_id=ctx.node.id,
            attempt_id=ctx.attempt_id,
            results=(
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CI_PIPELINE,
                        required=True,
                    ),
                    passed=False,
                    confidence=1.0,
                    message="missing harness-native CI pipeline evidence",
                ),
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CUSTOM,
                        spec={"name": "workspace_judge"},
                        required=True,
                    ),
                    passed=False,
                    confidence=0.95,
                    message="judge verdict=needs_rework",
                ),
            ),
        )


class _PipelineOnlyJudgeFailureVerifier:
    async def verify(self, ctx: VerificationContext) -> VerificationReport:
        return VerificationReport(
            node_id=ctx.node.id,
            attempt_id=ctx.attempt_id,
            results=(
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CI_PIPELINE,
                        required=True,
                    ),
                    passed=False,
                    confidence=0.7,
                    message="missing harness-native CI pipeline evidence",
                ),
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CUSTOM,
                        spec={
                            "name": "workspace_verification_judge",
                            "failed_criteria": ["missing harness-native CI pipeline evidence"],
                            "feedback_items": [
                                {
                                    "target_layer": "planner",
                                    "feedback_kind": "stale_or_invalid_task_target",
                                    "severity": "warning",
                                    "recommended_action": "revise_plan_node",
                                    "summary": "CI/CD pipeline ownership is missing",
                                    "failure_signature": ("ci_ownership_missing"),
                                }
                            ],
                        },
                        required=True,
                    ),
                    passed=False,
                    confidence=0.7,
                    message="judge verdict=needs_rework; missing pipeline evidence",
                ),
            ),
        )


class _StalePipelineWithBlockingWorkerFeedbackVerifier:
    async def verify(self, ctx: VerificationContext) -> VerificationReport:
        return VerificationReport(
            node_id=ctx.node.id,
            attempt_id=ctx.attempt_id,
            results=(
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CI_PIPELINE,
                        required=True,
                    ),
                    passed=False,
                    confidence=0.7,
                    message="Drone build #35 failed for a stale commit",
                ),
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CUSTOM,
                        spec={
                            "name": "workspace_verification_judge",
                            "failed_criteria": ["ci_pipeline"],
                            "feedback_items": [
                                {
                                    "target_layer": "worker",
                                    "feedback_kind": "product_code_failure",
                                    "severity": "blocking",
                                    "recommended_action": "retry_worker",
                                    "summary": "stale Drone run still used localhost registry pull",
                                    "failure_signature": (
                                        "drone-host-socket-localhost-registry-unreachable"
                                    ),
                                },
                                {
                                    "target_layer": "planner",
                                    "feedback_kind": "stale_or_invalid_task_target",
                                    "severity": "info",
                                    "recommended_action": "obsolete_node",
                                    "summary": "Drone failure belongs to an older commit",
                                    "failure_signature": "drone-pipeline-stale-commit",
                                },
                            ],
                        },
                        required=True,
                    ),
                    passed=False,
                    confidence=0.7,
                    message="judge verdict=needs_rework; stale Drone pipeline",
                ),
            ),
        )


class _MissingPipelineEvidenceWithWorkerFeedbackVerifier:
    async def verify(self, ctx: VerificationContext) -> VerificationReport:
        return VerificationReport(
            node_id=ctx.node.id,
            attempt_id=ctx.attempt_id,
            results=(
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CI_PIPELINE,
                        required=True,
                    ),
                    passed=False,
                    confidence=0.7,
                    message="missing harness-native CI pipeline evidence",
                ),
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CUSTOM,
                        spec={
                            "name": "workspace_verification_judge",
                            "failed_criteria": [
                                "missing harness-native CI pipeline evidence",
                                "Drone build #124 failed at workspace-ci/deploy",
                            ],
                            "feedback_items": [
                                {
                                    "target_layer": "worker",
                                    "feedback_kind": "product_code_failure",
                                    "severity": "blocking",
                                    "recommended_action": "retry_worker",
                                    "summary": "Cannot find module '/app/dist/index.js'",
                                    "failure_signature": "module_not_found_dist_index",
                                }
                            ],
                        },
                        required=True,
                    ),
                    passed=False,
                    confidence=0.7,
                    message=(
                        "judge verdict=needs_rework; previous Drone deploy failed with "
                        "Cannot find module '/app/dist/index.js'"
                    ),
                ),
            ),
        )


class _PipelineWorkerActionFailureVerifier:
    async def verify(self, ctx: VerificationContext) -> VerificationReport:
        return VerificationReport(
            node_id=ctx.node.id,
            attempt_id=ctx.attempt_id,
            results=(
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CI_PIPELINE,
                        required=True,
                    ),
                    passed=False,
                    confidence=0.7,
                    message=(
                        "Drone build #40 finished with status killed; "
                        "failing stage workspace-ci/docker-build exited 137"
                    ),
                ),
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CUSTOM,
                        spec={
                            "name": "workspace_verification_judge",
                            "failed_criteria": ["ci_pipeline", "drone_docker_build_timeout"],
                            "feedback_items": [
                                {
                                    "target_layer": "worker",
                                    "feedback_kind": "product_code_failure",
                                    "severity": "blocking",
                                    "recommended_action": "retry_worker",
                                    "summary": "shrink Docker context and update Dockerfile",
                                    "failure_signature": (
                                        "drone-docker-build-timeout-context-or-node"
                                    ),
                                }
                            ],
                        },
                        required=True,
                    ),
                    passed=False,
                    confidence=0.7,
                    message="judge verdict=needs_rework; docker-build requires code changes",
                ),
            ),
        )


class _PipelineWorkerActionDeployPortConflictVerifier:
    async def verify(self, ctx: VerificationContext) -> VerificationReport:
        return VerificationReport(
            node_id=ctx.node.id,
            attempt_id=ctx.attempt_id,
            results=(
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CI_PIPELINE,
                        required=True,
                    ),
                    passed=False,
                    confidence=0.7,
                    message=(
                        "harness-native CI pipeline failed: Drone build #162 failed in "
                        "workspace-ci/deploy: Bind for 0.0.0.0:5432 failed: port is already "
                        "allocated"
                    ),
                ),
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CUSTOM,
                        spec={
                            "name": "workspace_verification_judge",
                            "failed_criteria": [
                                "ci_pipeline",
                                "drone_docker_deploy_host_port_conflict",
                            ],
                            "feedback_items": [
                                {
                                    "target_layer": "worker",
                                    "feedback_kind": "product_code_failure",
                                    "severity": "blocking",
                                    "recommended_action": "retry_worker",
                                    "summary": (
                                        "Confirm app bindings use docker.deploy_host_port and "
                                        "dependency sidecars do not publish reserved host ports "
                                        "through docker compose unless required."
                                    ),
                                    "failure_signature": ("drone-docker-deploy-host-port-conflict"),
                                    "evidence_refs": [
                                        "drone_error:docker_host_port_allocated",
                                        "drone_deploy:reserved_host_port",
                                    ],
                                }
                            ],
                        },
                        required=True,
                    ),
                    passed=False,
                    confidence=0.7,
                    message=(
                        "judge verdict=needs_rework; Drone docker-deploy failed because the "
                        "host-side Docker port mapping collided with a platform service port; "
                        "feedback_targets=worker"
                    ),
                ),
            ),
        )


class _PipelineOnlyJudgeFailureWithoutFeedbackVerifier:
    async def verify(self, ctx: VerificationContext) -> VerificationReport:
        return VerificationReport(
            node_id=ctx.node.id,
            attempt_id=ctx.attempt_id,
            results=(
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CI_PIPELINE,
                        required=True,
                    ),
                    passed=False,
                    confidence=0.7,
                    message="missing harness-native CI pipeline evidence",
                ),
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CUSTOM,
                        spec={
                            "name": "workspace_verification_judge",
                            "failed_criteria": ["missing harness-native CI pipeline evidence"],
                        },
                        required=True,
                    ),
                    passed=False,
                    confidence=0.7,
                    message=(
                        "judge verdict=needs_rework; next_action=Run Drone CI pipeline "
                        "and capture execution output"
                    ),
                ),
            ),
        )


class _PipelineRetryInfrastructureVerifier:
    async def verify(self, ctx: VerificationContext) -> VerificationReport:
        return VerificationReport(
            node_id=ctx.node.id,
            attempt_id=ctx.attempt_id,
            results=(
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CI_PIPELINE,
                        required=True,
                    ),
                    passed=False,
                    confidence=1.0,
                    message="missing harness-native CI pipeline evidence",
                ),
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CUSTOM,
                        spec={
                            "name": "retryable_infrastructure_failure",
                            "judge_verdict": "retry_infrastructure",
                            "failed_criteria": ["ci_pipeline"],
                            "required_next_action": (
                                "Host harness must push the prepared commit and trigger Drone CI/CD."
                            ),
                            "next_action_kind": "retry_infra",
                            "feedback_items": [
                                {
                                    "target_layer": "runtime",
                                    "feedback_kind": "runtime_infra_failure",
                                    "severity": "blocking",
                                    "recommended_action": "retry_infra",
                                    "summary": (
                                        "Drone pipeline trigger is blocked until host harness "
                                        "pushes commit abc1234 with credentials."
                                    ),
                                    "failure_signature": "missing-git-credentials-for-push",
                                    "evidence_refs": ["commit_ref:abc1234", ".drone.yml"],
                                }
                            ],
                        },
                        required=True,
                    ),
                    passed=False,
                    confidence=0.7,
                    message=(
                        "judge verdict=retry_infrastructure; Drone trigger requires host harness"
                    ),
                ),
            ),
        )


class _PipelineHumanPublishRequiredVerifier:
    async def verify(self, ctx: VerificationContext) -> VerificationReport:
        return VerificationReport(
            node_id=ctx.node.id,
            attempt_id=ctx.attempt_id,
            results=(
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CI_PIPELINE,
                        required=True,
                    ),
                    passed=False,
                    confidence=1.0,
                    message=(
                        "missing harness-native CI pipeline evidence for current commit d9184e2"
                    ),
                ),
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CUSTOM,
                        spec={
                            "name": "workspace_verification_judge",
                            "judge_verdict": "blocked_human_required",
                            "failed_criteria": [
                                (
                                    "ci_pipeline: missing harness-native CI pipeline evidence "
                                    "for current commit d9184e2"
                                )
                            ],
                            "required_next_action": (
                                "Platform harness must publish the worktree branch to GitHub "
                                "main so Drone CI/CD is triggered for commit d9184e2."
                            ),
                            "next_action_kind": "human_required",
                            "feedback_items": [
                                {
                                    "target_layer": "runtime",
                                    "feedback_kind": "runtime_infra_failure",
                                    "severity": "blocking",
                                    "recommended_action": "retry_worker",
                                    "summary": (
                                        "Drone docker deploy pipeline not triggered: worktree "
                                        "commit d9184e2 not yet on main branch."
                                    ),
                                    "failure_signature": ("drone_no_pipeline_for_worktree_commit"),
                                    "evidence_refs": [
                                        "commit_ref:d9184e2",
                                        "ci_pipeline:missing",
                                    ],
                                }
                            ],
                        },
                        required=True,
                    ),
                    passed=False,
                    confidence=0.9,
                    message=(
                        "judge verdict=blocked_human_required; platform harness must publish "
                        "the worktree branch to GitHub main"
                    ),
                ),
            ),
        )


class _PipelineHumanPublishRequiredJudgeOnlyVerifier:
    async def verify(self, ctx: VerificationContext) -> VerificationReport:
        return VerificationReport(
            node_id=ctx.node.id,
            attempt_id=ctx.attempt_id,
            results=(
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CUSTOM,
                        spec={
                            "name": "workspace_verification_judge",
                            "judge_verdict": "blocked_human_required",
                            "failed_criteria": [
                                (
                                    "node_description: Sprint 1 feature commits must be "
                                    "merged to memstack-source-publish/main"
                                ),
                                "node_description: trigger a new Drone pipeline build",
                            ],
                            "required_next_action": (
                                "Platform harness must push the worktree branch to "
                                "memstack-source-publish/main using a GITHUB_TOKEN, then "
                                "trigger Drone."
                            ),
                            "next_action_kind": "human_required",
                            "feedback_items": [
                                {
                                    "target_layer": "planner",
                                    "feedback_kind": "stale_or_invalid_task_target",
                                    "severity": "blocking",
                                    "recommended_action": "revise_plan_node",
                                    "summary": (
                                        "Node description requires external GitHub merge and "
                                        "Drone trigger that cannot be executed in sandbox."
                                    ),
                                    "failure_signature": "external_github_merge_not_executed",
                                    "evidence_refs": ["commit_ref:d9184e2"],
                                }
                            ],
                        },
                        required=True,
                    ),
                    passed=False,
                    confidence=0.9,
                    message=(
                        "judge verdict=blocked_human_required; platform harness must publish "
                        "the worktree branch and trigger Drone"
                    ),
                ),
            ),
        )


class _PipelineBlockedWorkerReportWithJudgeTimeoutVerifier:
    async def verify(self, ctx: VerificationContext) -> VerificationReport:
        return VerificationReport(
            node_id=ctx.node.id,
            attempt_id=ctx.attempt_id,
            results=(
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CUSTOM,
                        spec={"name": "terminal_worker_report_completed"},
                        required=True,
                    ),
                    passed=False,
                    confidence=1.0,
                    message=(
                        "worker report type 'blocked' is not a completion report: "
                        "Sandbox lacks GITHUB_TOKEN and DRONE_TOKEN required for "
                        "external GitHub merge and Drone pipeline trigger. All locally "
                        "verifiable work is complete and committed."
                    ),
                ),
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CUSTOM,
                        spec={
                            "name": "retryable_infrastructure_failure",
                            "judge_verdict": "retry_infrastructure",
                            "failed_criteria": ["workspace_verification_judge"],
                            "next_action_kind": "retry_same_node",
                        },
                        required=True,
                    ),
                    passed=False,
                    confidence=0.5,
                    message=(
                        "judge verdict=retry_infrastructure; workspace verification "
                        "judge timed out after 180s"
                    ),
                ),
            ),
        )


class _PipelineEmbeddedMarkerJudgeFailureVerifier:
    async def verify(self, ctx: VerificationContext) -> VerificationReport:
        return VerificationReport(
            node_id=ctx.node.id,
            attempt_id=ctx.attempt_id,
            results=(
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CI_PIPELINE,
                        required=True,
                    ),
                    passed=False,
                    confidence=0.7,
                    message="missing harness-native CI pipeline evidence",
                ),
                CriterionResult(
                    criterion=AcceptanceCriterion(
                        kind=CriterionKind.CUSTOM,
                        spec={
                            "name": "workspace_verification_judge",
                            "failed_criteria": ["ci_pipeline: missing evidence"],
                            "feedback_items": [
                                {
                                    "target_layer": "worker",
                                    "feedback_kind": "missing_evidence",
                                    "severity": "blocking",
                                    "recommended_action": "retry_worker",
                                    "summary": "No CI pipeline evidence was captured.",
                                    "failure_signature": "ci-pipeline-missing-def5678",
                                }
                            ],
                        },
                        required=True,
                    ),
                    passed=False,
                    confidence=0.7,
                    message="judge verdict=needs_rework; missing pipeline evidence",
                ),
            ),
        )


class _StaticIterationReviewer:
    def __init__(self, verdict: IterationReviewVerdict) -> None:
        self.verdict = verdict
        self.contexts: list[IterationReviewContext] = []

    async def review(self, context: IterationReviewContext) -> IterationReviewVerdict:
        self.contexts.append(context)
        return self.verdict


def test_node_with_verification_evidence_prefers_latest_pipeline_artifact_status() -> None:
    node = _leaf_node(
        metadata={
            "pipeline_status": "failed",
            "pipeline_gate_status": "failed",
            "pipeline_run_id": "old-run",
        }
    )
    report = VerificationReport(node_id=node.id, attempt_id=None, results=())

    updated = _node_with_verification_evidence(
        node,
        report,
        artifacts={
            "pipeline_evidence_refs": [
                "pipeline_run:failed:old-run",
                "ci_pipeline:passed",
                "pipeline_run:success:new-run",
            ]
        },
    )

    assert updated.metadata["pipeline_status"] == "success"
    assert updated.metadata["pipeline_gate_status"] == "success"
    assert updated.metadata["pipeline_run_id"] == "new-run"


def test_reopen_done_nodes_with_failed_required_pipeline() -> None:
    plan = _plan_with_two_tasks()
    node = plan.nodes[PlanNodeId("a")]
    plan.replace_node(
        replace(
            node,
            intent=TaskIntent.DONE,
            execution=TaskExecution.IDLE,
            current_attempt_id="attempt-a",
            metadata={
                "pipeline_required": True,
                "pipeline_status": "failed",
                "pipeline_gate_status": "failed",
                "pipeline_run_id": "run-a",
            },
        )
    )

    reopened = _reopen_done_nodes_with_failed_pipeline(plan)

    assert [node.id for node in reopened] == ["a"]
    updated = plan.nodes[PlanNodeId("a")]
    assert updated.intent is TaskIntent.IN_PROGRESS
    assert updated.execution is TaskExecution.REPORTED
    assert updated.current_attempt_id == "attempt-a"
    assert updated.metadata["last_verification_passed"] is False
    assert updated.metadata["pipeline_failed_done_reopened_at"].endswith("Z")


def test_reopen_done_nodes_with_failed_worktree_integration() -> None:
    plan = _plan_with_two_tasks()
    node = plan.nodes[PlanNodeId("a")]
    plan.replace_node(
        replace(
            node,
            intent=TaskIntent.DONE,
            execution=TaskExecution.IDLE,
            current_attempt_id="attempt-a",
            feature_checkpoint=FeatureCheckpoint(
                feature_id="feature-a",
                sequence=1,
                title="task a",
                worktree_path="/workspace/.memstack/worktrees/attempt-a",
                branch_name="workspace/a-attempt-a",
                base_ref="old-base",
                commit_ref="abc1234",
            ),
            metadata={
                "terminal_attempt_status": "accepted",
                "verified_commit_ref": "abc1234",
                "worktree_integration_attempt_id": "attempt-a",
                "worktree_integration_status": "failed",
                "worktree_integration_worktree_path": ("/workspace/.memstack/worktrees/attempt-a"),
                "worktree_integration_dirty_signature": None,
                "worktree_integration_summary": (
                    "Exit code: 128\n"
                    "status=failed\n"
                    "reason=merge_failed_aborted\n"
                    "fatal: refusing to merge unrelated histories"
                ),
            },
        )
    )

    reopened = _reopen_done_nodes_with_failed_worktree_integration(plan)

    assert [node.id for node in reopened] == ["a"]
    updated = plan.nodes[PlanNodeId("a")]
    assert updated.intent is TaskIntent.TODO
    assert updated.execution is TaskExecution.IDLE
    assert updated.current_attempt_id is None
    assert updated.feature_checkpoint is not None
    assert updated.feature_checkpoint.worktree_path is None
    assert updated.feature_checkpoint.branch_name is None
    assert updated.feature_checkpoint.base_ref == "HEAD"
    assert updated.feature_checkpoint.commit_ref is None
    assert updated.metadata["last_verification_passed"] is False
    assert updated.metadata["terminal_attempt_retry_reason"] == "worktree_integration_failed"
    assert updated.metadata["worktree_integration_failed_previous_attempt_id"] == "attempt-a"
    assert updated.metadata["worktree_integration_failed_previous_commit_ref"] == "abc1234"
    assert "worktree_integration_status" not in updated.metadata


def test_node_with_verification_evidence_uses_worker_artifact_commit_refs() -> None:
    node = _leaf_node()
    report = VerificationReport(node_id=node.id, attempt_id="attempt-1", results=())

    updated = _node_with_verification_evidence(
        node,
        report,
        artifacts={
            "candidate_artifacts": [
                "commit_ref:abc123",
                "git_diff_summary:CHANGELOG.md updated",
            ],
            "candidate_verifications": ["preflight:git-status"],
        },
    )

    assert updated.metadata["verified_commit_ref"] == "abc123"
    assert updated.metadata["verified_git_diff_summary"] == "CHANGELOG.md updated"
    assert updated.metadata["verification_evidence_refs"] == [
        "commit_ref:abc123",
        "git_diff_summary:CHANGELOG.md updated",
        "preflight:git-status",
    ]


def test_node_with_verification_evidence_uses_latest_worker_artifact_commit_ref() -> None:
    node = _leaf_node()
    report = VerificationReport(node_id=node.id, attempt_id="attempt-1", results=())

    updated = _node_with_verification_evidence(
        node,
        report,
        artifacts={
            "candidate_artifacts": [
                "commit_ref:bce4286b",
                "git_diff_summary:.drone.yml old deploy fix",
                "commit_ref:13aeda8",
                "git_diff_summary:.drone.yml removed registry pull",
            ],
            "candidate_verifications": ["preflight:git-status"],
        },
    )

    assert updated.metadata["verified_commit_ref"] == "13aeda8"
    assert updated.metadata["verified_git_diff_summary"] == ".drone.yml removed registry pull"


def _mark_plan_tasks_done(plan: Plan) -> Plan:
    for node in list(plan.nodes.values()):
        if node.kind in {PlanNodeKind.TASK, PlanNodeKind.VERIFY}:
            plan.replace_node(
                replace(
                    node,
                    intent=TaskIntent.DONE,
                    execution=TaskExecution.IDLE,
                    metadata={
                        **dict(node.metadata or {}),
                        "iteration_index": 1,
                        "iteration_phase": "implement",
                        "verification_evidence_refs": [f"evidence://{node.id}"],
                    },
                )
            )
    return plan


def _supervisor_for_iteration_review(
    repo: InMemoryPlanRepository,
    reviewer: _StaticIterationReviewer,
    events: list[tuple[str, str, dict[str, Any]]],
    artifacts_by_node: dict[str, dict[str, Any]] | None = None,
) -> WorkspaceSupervisor:
    async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
        return []

    async def dispatcher(_wid: str, _alloc: Any, _node: PlanNode) -> str | None:
        return None

    async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
        return VerificationContext(
            workspace_id=wid,
            node=node,
            attempt_id=node.current_attempt_id,
            artifacts=dict((artifacts_by_node or {}).get(node.id, {})),
        )

    async def event_sink(
        _wid: str,
        node: PlanNode,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        events.append((event_type, node.id, payload))

    return WorkspaceSupervisor(
        plan_repo=repo,
        allocator=CapabilityAllocator(),
        verifier=_AlwaysPassVerifier(),
        projector=ProgressProjector(),
        planner=LLMGoalPlanner(decomposer=None),
        agent_pool=agent_pool,
        dispatcher=dispatcher,
        attempt_context=attempt_ctx,
        event_sink=event_sink,
        iteration_reviewer=reviewer,
        heartbeat_seconds=0.05,
    )


class TestSupervisorTick:
    async def test_tick_applies_agent_supervisor_accept_decision(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-a",
                feature_checkpoint=FeatureCheckpoint(
                    feature_id="feature-a",
                    sequence=2,
                    expected_artifacts=("artifact://a",),
                ),
            )
        )
        await repo.save(plan)

        provider = _StaticSupervisorDecisionProvider(
            WorkspaceSupervisorDecisionResult(
                action=WorkspaceSupervisorDecisionAction.ACCEPT_NODE,
                rationale="verifier failure is already resolved by the linked attempt",
                confidence=0.9,
            )
        )
        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, _alloc: Any, _node: PlanNode) -> str | None:
            raise AssertionError("accepted reported node should not redispatch")

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid, node=node, attempt_id=node.current_attempt_id
            )

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_RetryableInfrastructureVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            supervisor_decision_provider=provider,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 1
        assert report.nodes_completed == 1
        assert provider.requests
        assert provider.requests[0].workspace_id == "ws-1"
        assert provider.requests[0].attempt_id == "attempt-a"
        assert WorkspaceSupervisorDecisionAction.ACCEPT_NODE in provider.requests[0].allowed_actions
        assert provider.requests[0].node_snapshot["feature_checkpoint"] == {
            "feature_id": "feature-a",
            "sequence": 2,
            "expected_artifacts": ["artifact://a"],
        }
        assert any(event[0] == "supervisor_decision_completed" for event in events)
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        node = reloaded.nodes[PlanNodeId("a")]
        assert node.intent is TaskIntent.DONE
        assert node.execution is TaskExecution.IDLE

    async def test_tick_agent_supervisor_pipeline_decision_emits_pipeline_event(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-a",
            )
        )
        await repo.save(plan)

        provider = _StaticSupervisorDecisionProvider(
            WorkspaceSupervisorDecisionResult(
                action=WorkspaceSupervisorDecisionAction.REQUEST_PIPELINE,
                rationale="trigger harness-native CI for the committed attempt",
                confidence=0.9,
            )
        )
        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, _alloc: Any, _node: PlanNode) -> str | None:
            raise AssertionError("pipeline request should not redispatch in the same tick")

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid, node=node, attempt_id=node.current_attempt_id
            )

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_RetryableInfrastructureVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            supervisor_decision_provider=provider,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 1
        pipeline_events = [event for event in events if event[0] == "pipeline_run_requested"]
        assert len(pipeline_events) == 1
        assert pipeline_events[0][1] == "a"
        assert pipeline_events[0][2]["attempt_id"] == "attempt-a"
        assert pipeline_events[0][2]["reason"] == "supervisor_decision_request_pipeline"
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        node = reloaded.nodes[PlanNodeId("a")]
        assert node.metadata["pipeline_status"] == "requested"
        assert node.metadata["pipeline_gate_status"] == "requested"

    async def test_tick_agent_supervisor_retry_decision_schedules_followup_tick(
        self,
    ) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-a",
            )
        )
        await repo.save(plan)

        provider = _StaticSupervisorDecisionProvider(
            WorkspaceSupervisorDecisionResult(
                action=WorkspaceSupervisorDecisionAction.RETRY_SAME_NODE,
                rationale="transient model connection failure; retry the same node",
                confidence=0.8,
            )
        )
        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, _alloc: Any, _node: PlanNode) -> str | None:
            raise AssertionError("retry backoff should not redispatch in the same tick")

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid, node=node, attempt_id=node.current_attempt_id
            )

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_RetryableInfrastructureVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            supervisor_decision_provider=provider,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 1
        assert report.allocations_made == 0
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        node = reloaded.nodes[PlanNodeId("a")]
        assert node.intent is TaskIntent.TODO
        assert node.execution is TaskExecution.IDLE
        assert node.current_attempt_id is None
        assert node.metadata["retry_not_before"].endswith("Z")
        retry_events = [event for event in events if event[0] == "verification_retry_scheduled"]
        assert len(retry_events) == 1
        assert retry_events[0][2]["attempt_id"] == "attempt-a"
        assert retry_events[0][2]["retry_not_before"] == node.metadata["retry_not_before"]

    async def test_tick_does_not_human_block_without_explicit_agent_payload(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-a",
            )
        )
        await repo.save(plan)

        provider = _StaticSupervisorDecisionProvider(
            WorkspaceSupervisorDecisionResult(
                action=WorkspaceSupervisorDecisionAction.MARK_BLOCKED_HUMAN,
                rationale="operator review may be needed",
                confidence=0.8,
                event_payload={"human_required": False},
            )
        )
        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, _alloc: Any, _node: PlanNode) -> str | None:
            raise AssertionError("reported node should be retried, not dispatched immediately")

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid, node=node, attempt_id=node.current_attempt_id
            )

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_RetryableInfrastructureVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            supervisor_decision_provider=provider,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 1
        assert report.nodes_blocked == 0
        assert any(event[0] == "supervisor_decision_human_block_downgraded" for event in events)
        assert any(event[0] == "verification_retry_scheduled" for event in events)
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        node = reloaded.nodes[PlanNodeId("a")]
        assert node.intent is TaskIntent.TODO
        assert node.execution is TaskExecution.IDLE
        assert node.metadata["last_supervisor_decision_action"] == "mark_blocked_human"

    async def test_tick_dispatches_ready_and_verifies_reported(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        stale = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                stale,
                metadata={
                    "last_verification_summary": "verification failed: old attempt",
                    "last_verification_passed": False,
                    "last_verification_attempt_id": "old-attempt",
                    "verification_evidence_refs": ["old-evidence"],
                    "terminal_attempt_status": "blocked",
                    "terminal_attempt_retry_count": 1,
                },
            )
        )
        await repo.save(plan)

        allocator = CapabilityAllocator()
        verifier = _AlwaysPassVerifier()
        projector = ProgressProjector()
        planner = LLMGoalPlanner(decomposer=None)

        dispatched: list[tuple[str, str]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return [
                WorkspaceAgent(
                    agent_id="ag-search",
                    display_name="S",
                    capabilities=frozenset({"web_search"}),
                ),
                WorkspaceAgent(
                    agent_id="ag-code",
                    display_name="C",
                    capabilities=frozenset({"codegen"}),
                ),
            ]

        async def dispatcher(_wid: str, alloc, node) -> str:  # type: ignore[no-untyped-def]
            dispatched.append((alloc.agent_id, node.id))
            return f"attempt-{node.id}"

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid, node=node, attempt_id=node.current_attempt_id
            )

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=allocator,
            verifier=verifier,
            projector=projector,
            planner=planner,
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            heartbeat_seconds=0.05,
        )

        # Tick 1 — only "a" is ready (b depends on a).
        report = await sup.tick("ws-1")
        assert report.allocations_made == 1
        assert any(aid == "ag-search" for aid, _ in dispatched)

        # Simulate worker report for "a".
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None

        a = reloaded.nodes[PlanNodeId("a")]
        assert a.current_attempt_id == "attempt-a"
        assert "last_verification_summary" not in a.metadata
        assert "last_verification_passed" not in a.metadata
        assert "last_verification_attempt_id" not in a.metadata
        assert "verification_evidence_refs" not in a.metadata
        assert "terminal_attempt_status" not in a.metadata
        assert a.metadata["terminal_attempt_retry_count"] == 1
        reloaded.replace_node(replace(a, execution=TaskExecution.REPORTED))
        await repo.save(reloaded)

        # Tick 2 — verify "a" (passes → DONE), then "b" becomes ready.
        report2 = await sup.tick("ws-1")
        assert report2.verifications_ran == 1
        assert report2.nodes_completed == 1
        assert report2.allocations_made == 1  # b now dispatched
        reloaded_after_verify = await repo.get_by_workspace("ws-1")
        assert reloaded_after_verify is not None
        verified_a = reloaded_after_verify.nodes[PlanNodeId("a")]
        assert verified_a.progress.note == "verified (0 criteria passed)"

    async def test_tick_defers_ready_nodes_with_overlapping_write_sets(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        from dataclasses import replace

        a = plan.nodes[PlanNodeId("a")]
        b = plan.nodes[PlanNodeId("b")]
        plan.replace_node(replace(a, metadata={"write_set": ["src/shared.ts"]}))
        plan.replace_node(
            replace(
                b,
                depends_on=frozenset(),
                metadata={"write_set": ["src/shared.ts"]},
            )
        )
        await repo.save(plan)

        dispatched: list[str] = []
        events: list[tuple[str, str]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return [
                WorkspaceAgent(
                    agent_id="ag-code",
                    display_name="C",
                    capabilities=frozenset({"codegen", "web_search"}),
                )
            ]

        async def dispatcher(_wid: str, alloc, node) -> str:  # type: ignore[no-untyped-def]
            dispatched.append(node.id)
            return f"attempt-{node.id}"

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(workspace_id=wid, node=node)

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            _payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_AlwaysPassVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.allocations_made == 1
        assert len(dispatched) == 1
        assert events == [("dispatch_deferred_write_conflict", "b")]

    async def test_tick_defers_ready_node_until_dependency_worktree_integrated(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.DONE,
                execution=TaskExecution.IDLE,
                feature_checkpoint=FeatureCheckpoint(
                    feature_id="feature-a",
                    sequence=1,
                    title="task a",
                    worktree_path="/workspace/.memstack/worktrees/attempt-a",
                    commit_ref="abc123",
                ),
                metadata={"verified_commit_ref": "abc123"},
            )
        )
        await repo.save(plan)

        dispatched: list[str] = []
        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return [
                WorkspaceAgent(
                    agent_id="ag-code",
                    display_name="C",
                    capabilities=frozenset({"codegen", "web_search"}),
                )
            ]

        async def dispatcher(_wid: str, _alloc: Any, node: PlanNode) -> str:
            dispatched.append(node.id)
            return f"attempt-{node.id}"

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(workspace_id=wid, node=node)

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_AlwaysPassVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.allocations_made == 0
        assert dispatched == []
        assert events == [
            (
                "dispatch_deferred_dependency_projection",
                "b",
                {
                    "summary": "node deferred because one or more dependencies are not ready",
                    "missing_dependency_ids": ["a"],
                },
            )
        ]

    async def test_tick_retries_done_node_when_worktree_integration_failed(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.DONE,
                execution=TaskExecution.IDLE,
                current_attempt_id="attempt-a",
                feature_checkpoint=FeatureCheckpoint(
                    feature_id="feature-a",
                    sequence=1,
                    title="task a",
                    worktree_path="/workspace/.memstack/worktrees/attempt-a",
                    branch_name="workspace/a-attempt-a",
                    base_ref="old-base",
                    commit_ref="abc1234",
                ),
                metadata={
                    "terminal_attempt_status": "accepted",
                    "verified_commit_ref": "abc1234",
                    "worktree_integration_attempt_id": "attempt-a",
                    "worktree_integration_status": "failed",
                    "worktree_integration_worktree_path": (
                        "/workspace/.memstack/worktrees/attempt-a"
                    ),
                    "worktree_integration_dirty_signature": None,
                    "worktree_integration_summary": (
                        "Exit code: 128\n"
                        "status=failed\n"
                        "reason=merge_failed_aborted\n"
                        "fatal: refusing to merge unrelated histories"
                    ),
                },
            )
        )
        await repo.save(plan)

        dispatched: list[str] = []
        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return [
                WorkspaceAgent(
                    agent_id="ag-code",
                    display_name="C",
                    capabilities=frozenset({"codegen", "web_search"}),
                )
            ]

        async def dispatcher(_wid: str, _alloc: Any, node: PlanNode) -> str:
            dispatched.append(node.id)
            return f"retry-{node.id}"

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(workspace_id=wid, node=node)

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_AlwaysPassVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.allocations_made == 1
        assert dispatched == ["a"]
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        retried = reloaded.nodes[PlanNodeId("a")]
        assert retried.intent is TaskIntent.IN_PROGRESS
        assert retried.execution is TaskExecution.DISPATCHED
        assert retried.current_attempt_id == "retry-a"
        assert retried.metadata["terminal_attempt_retry_reason"] == ("worktree_integration_failed")
        assert "worktree_integration_status" not in retried.metadata
        assert [(event_type, node_id) for event_type, node_id, _payload in events] == [
            ("worktree_integration_failed_done_node_reopened", "a")
        ]

    async def test_tick_preserves_repair_dependency_when_phase_barriers_repaired(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        blocked = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                blocked,
                depends_on=frozenset(),
                feature_checkpoint=FeatureCheckpoint(
                    feature_id="feature-a",
                    sequence=1,
                    title="task a",
                ),
                metadata={
                    "iteration_index": 2,
                    "iteration_phase": "test",
                    "blocked_by_repair_node_id": "repair-a",
                },
            )
        )
        plan.add_node(
            PlanNode(
                id="repair-a",
                plan_id=plan.id,
                parent_id=plan.goal_id,
                kind=PlanNodeKind.TASK,
                title="Repair task a",
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.RUNNING,
                current_attempt_id="attempt-repair-a",
                feature_checkpoint=FeatureCheckpoint(
                    feature_id="feature-repair-a",
                    sequence=7,
                    title="Repair task a",
                ),
                metadata={
                    "iteration_index": 2,
                    "iteration_phase": "test",
                    "repair_for_node_id": "a",
                },
            )
        )
        b = plan.nodes[PlanNodeId("b")]
        plan.replace_node(
            replace(
                b,
                metadata={
                    "dependency_invalidated_at": "2026-05-21T02:43:51Z",
                    "dependency_invalidated_missing_ids": ["a"],
                    "dependency_invalidated_reason": "dependencies_not_done_or_not_integrated",
                    "dependency_invalidated_previous_attempt_id": "stale-attempt",
                    "dependency_invalidated_previous_intent": "in_progress",
                    "dependency_invalidated_previous_execution": "running",
                },
            )
        )
        await repo.save(plan)

        dispatched: list[str] = []
        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return [
                WorkspaceAgent(
                    agent_id="ag-code",
                    display_name="C",
                    capabilities=frozenset({"codegen", "web_search"}),
                )
            ]

        async def dispatcher(_wid: str, _alloc: Any, node: PlanNode) -> str:
            dispatched.append(node.id)
            return f"attempt-{node.id}"

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(workspace_id=wid, node=node)

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_AlwaysPassVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.allocations_made == 0
        assert dispatched == []
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        repaired_blocked = reloaded.nodes[PlanNodeId("a")]
        assert repaired_blocked.depends_on == frozenset({PlanNodeId("repair-a")})
        assert any(
            event_type == "iteration_phase_barriers_repaired" and node_id == "goal-1"
            for event_type, node_id, _payload in events
        )

    async def test_tick_dispatches_after_dependency_pipeline_published_commit(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        a = plan.nodes[PlanNodeId("a")]
        b = plan.nodes[PlanNodeId("b")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.DONE,
                execution=TaskExecution.IDLE,
                feature_checkpoint=FeatureCheckpoint(
                    feature_id="feature-a",
                    sequence=1,
                    title="task a",
                    worktree_path="/workspace/.memstack/worktrees/attempt-a",
                    commit_ref="abc1234",
                ),
                metadata={
                    "verified_commit_ref": "abc1234",
                    "pipeline_gate_status": "success",
                    "source_publish_status": "published",
                    "source_publish_commit_ref": "abc1234deadbeef",
                },
            )
        )
        plan.replace_node(
            replace(
                b,
                feature_checkpoint=FeatureCheckpoint(
                    feature_id="feature-b",
                    sequence=2,
                    title="task b",
                    base_ref="HEAD",
                ),
            )
        )
        await repo.save(plan)

        dispatched: list[str] = []
        dispatched_base_refs: list[str | None] = []
        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return [
                WorkspaceAgent(
                    agent_id="ag-code",
                    display_name="C",
                    capabilities=frozenset({"codegen", "web_search"}),
                )
            ]

        async def dispatcher(_wid: str, _alloc: Any, node: PlanNode) -> str:
            dispatched.append(node.id)
            dispatched_base_refs.append(
                node.feature_checkpoint.base_ref if node.feature_checkpoint else None
            )
            return f"attempt-{node.id}"

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(workspace_id=wid, node=node)

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_AlwaysPassVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.allocations_made == 1
        assert dispatched == ["b"]
        assert dispatched_base_refs == ["abc1234deadbeef"]
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        dispatched_node = reloaded.nodes[PlanNodeId("b")]
        assert dispatched_node.current_attempt_id == "attempt-b"
        assert dispatched_node.feature_checkpoint is not None
        assert dispatched_node.feature_checkpoint.base_ref == "abc1234deadbeef"
        for stale_key in (
            "dependency_invalidated_at",
            "dependency_invalidated_missing_ids",
            "dependency_invalidated_reason",
            "dependency_invalidated_previous_attempt_id",
            "dependency_invalidated_previous_intent",
            "dependency_invalidated_previous_execution",
        ):
            assert stale_key not in dispatched_node.metadata
        assert not [
            event for event in events if event[0] == "dispatch_deferred_dependency_projection"
        ]

    async def test_tick_dispatches_repair_dependency_from_blocked_dirty_main_commit(
        self,
    ) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                depends_on=frozenset({PlanNodeId("repair-a")}),
                feature_checkpoint=FeatureCheckpoint(
                    feature_id="feature-a",
                    sequence=2,
                    title="task a",
                    base_ref="HEAD",
                ),
                metadata={
                    "blocked_by_repair_node_id": "repair-a",
                    "pipeline_required": True,
                    "pipeline_gate_status": "requested",
                },
            )
        )
        plan.add_node(
            PlanNode(
                id="repair-a",
                plan_id=plan.id,
                parent_id=plan.goal_id,
                kind=PlanNodeKind.TASK,
                title="Repair task a",
                intent=TaskIntent.DONE,
                execution=TaskExecution.IDLE,
                current_attempt_id="attempt-repair-a",
                feature_checkpoint=FeatureCheckpoint(
                    feature_id="feature-repair-a",
                    sequence=1,
                    title="Repair task a",
                    worktree_path="/workspace/.memstack/worktrees/attempt-repair-a",
                    commit_ref="abc1234",
                ),
                metadata={
                    "repair_for_node_id": "a",
                    "repair_source": "verification_judge_create_repair_node",
                    "source_verification_judge_next_action_kind": "create_repair_node",
                    "last_verification_judge_verdict": "accepted",
                    "last_verification_passed": True,
                    "terminal_attempt_status": "accepted",
                    "verified_commit_ref": "abc1234",
                    "worktree_integration_commit_ref": "abc1234",
                    "worktree_integration_status": "blocked_dirty_main",
                    "verification_evidence_refs": [
                        "commit_ref:abc1234",
                        "test_run:uv run pytest src/tests/unit -q",
                        "worker_report:completed",
                    ],
                },
            )
        )
        await repo.save(plan)

        dispatched: list[str] = []
        dispatched_base_refs: list[str | None] = []
        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return [
                WorkspaceAgent(
                    agent_id="ag-code",
                    display_name="C",
                    capabilities=frozenset({"codegen", "web_search"}),
                )
            ]

        async def dispatcher(_wid: str, _alloc: Any, node: PlanNode) -> str:
            dispatched.append(node.id)
            dispatched_base_refs.append(
                node.feature_checkpoint.base_ref if node.feature_checkpoint else None
            )
            return f"attempt-{node.id}"

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(workspace_id=wid, node=node)

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_AlwaysPassVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.allocations_made == 1
        assert dispatched == ["a"]
        assert dispatched_base_refs == ["abc1234"]
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        dispatched_node = reloaded.nodes[PlanNodeId("a")]
        assert dispatched_node.current_attempt_id == "attempt-a"
        assert dispatched_node.feature_checkpoint is not None
        assert dispatched_node.feature_checkpoint.base_ref == "abc1234"
        assert not [
            event for event in events if event[0] == "dispatch_deferred_dependency_projection"
        ]

    async def test_tick_dispatches_followup_repair_from_blocked_dirty_main_commit(
        self,
    ) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        original = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                original,
                depends_on=frozenset({PlanNodeId("repair-b")}),
                metadata={"blocked_by_repair_node_id": "repair-b"},
            )
        )
        plan.add_node(
            PlanNode(
                id="repair-a",
                plan_id=plan.id,
                parent_id=plan.goal_id,
                kind=PlanNodeKind.TASK,
                title="First repair",
                intent=TaskIntent.DONE,
                execution=TaskExecution.IDLE,
                current_attempt_id="attempt-repair-a",
                feature_checkpoint=FeatureCheckpoint(
                    feature_id="feature-repair-a",
                    sequence=1,
                    title="First repair",
                    worktree_path="/workspace/.memstack/worktrees/attempt-repair-a",
                    commit_ref="stale-integration-ref",
                ),
                metadata={
                    "repair_for_node_id": "a",
                    "repair_source": "verification_judge_create_repair_node",
                    "last_verification_passed": True,
                    "terminal_attempt_status": "accepted",
                    "verified_commit_ref": "verified123",
                    "worktree_integration_commit_ref": "stale-integration-ref",
                    "worktree_integration_status": "blocked_dirty_main",
                    "verification_evidence_refs": ["commit_ref:verified123"],
                },
            )
        )
        plan.add_node(
            PlanNode(
                id="repair-b",
                plan_id=plan.id,
                parent_id=plan.goal_id,
                kind=PlanNodeKind.TASK,
                title="Follow-up repair",
                intent=TaskIntent.TODO,
                execution=TaskExecution.IDLE,
                depends_on=frozenset({PlanNodeId("repair-a")}),
                feature_checkpoint=FeatureCheckpoint(
                    feature_id="feature-repair-b",
                    sequence=2,
                    title="Follow-up repair",
                    base_ref="HEAD",
                ),
                metadata={
                    "repair_for_node_id": "a",
                    "repair_source": "verification_judge_create_repair_node",
                    "source_verification_judge_next_action_kind": "create_repair_node",
                },
            )
        )
        await repo.save(plan)

        dispatched: list[str] = []
        dispatched_base_refs: list[str | None] = []
        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return [
                WorkspaceAgent(
                    agent_id="ag-code",
                    display_name="C",
                    capabilities=frozenset({"codegen", "web_search"}),
                )
            ]

        async def dispatcher(_wid: str, _alloc: Any, node: PlanNode) -> str:
            dispatched.append(node.id)
            dispatched_base_refs.append(
                node.feature_checkpoint.base_ref if node.feature_checkpoint else None
            )
            return f"attempt-{node.id}"

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(workspace_id=wid, node=node)

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_AlwaysPassVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.allocations_made == 1
        assert dispatched == ["repair-b"]
        assert dispatched_base_refs == ["verified123"]
        assert not [
            event for event in events if event[0] == "dispatch_deferred_dependency_projection"
        ]

    async def test_tick_dispatches_new_repair_with_blocked_dirty_main_dependencies(
        self,
    ) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        for node_id, commit_ref in (("a", "commit-a"), ("b", "commit-b")):
            node = plan.nodes[PlanNodeId(node_id)]
            plan.replace_node(
                replace(
                    node,
                    intent=TaskIntent.DONE,
                    execution=TaskExecution.IDLE,
                    current_attempt_id=f"attempt-{node_id}",
                    depends_on=frozenset(),
                    feature_checkpoint=FeatureCheckpoint(
                        feature_id=f"feature-{node_id}",
                        sequence=1,
                        title=f"task {node_id}",
                        worktree_path=f"/workspace/.memstack/worktrees/attempt-{node_id}",
                        commit_ref=commit_ref,
                    ),
                    metadata={
                        "terminal_attempt_status": "accepted",
                        "verified_commit_ref": commit_ref,
                        "worktree_integration_commit_ref": commit_ref,
                        "worktree_integration_status": "blocked_dirty_main",
                        "verification_evidence_refs": [f"commit_ref:{commit_ref}"],
                    },
                )
            )
        plan.add_node(
            PlanNode(
                id="repair-a",
                plan_id=plan.id,
                parent_id=plan.goal_id,
                kind=PlanNodeKind.TASK,
                title="Repair verification blockers",
                intent=TaskIntent.TODO,
                execution=TaskExecution.IDLE,
                depends_on=frozenset({PlanNodeId("a"), PlanNodeId("b")}),
                feature_checkpoint=FeatureCheckpoint(
                    feature_id="feature-repair-a",
                    sequence=2,
                    title="Repair verification blockers",
                    base_ref="HEAD",
                ),
                metadata={
                    "repair_for_node_id": "target-node",
                    "repair_source": "verification_judge_create_repair_node",
                    "source_verification_judge_next_action_kind": "create_repair_node",
                },
            )
        )
        await repo.save(plan)

        dispatched: list[str] = []
        dispatched_base_refs: list[str | None] = []
        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return [
                WorkspaceAgent(
                    agent_id="ag-code",
                    display_name="C",
                    capabilities=frozenset({"codegen", "web_search"}),
                )
            ]

        async def dispatcher(_wid: str, _alloc: Any, node: PlanNode) -> str:
            dispatched.append(node.id)
            dispatched_base_refs.append(
                node.feature_checkpoint.base_ref if node.feature_checkpoint else None
            )
            return f"attempt-{node.id}"

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(workspace_id=wid, node=node)

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_AlwaysPassVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.allocations_made == 1
        assert dispatched == ["repair-a"]
        assert dispatched_base_refs == ["commit-b"]
        assert not [
            event for event in events if event[0] == "dispatch_deferred_dependency_projection"
        ]

    async def test_tick_dispatches_review_feedback_with_blocked_dirty_main_dependencies(
        self,
    ) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        for node_id, commit_ref in (("a", "commit-a"), ("b", "commit-b")):
            node = plan.nodes[PlanNodeId(node_id)]
            plan.replace_node(
                replace(
                    node,
                    intent=TaskIntent.DONE,
                    execution=TaskExecution.IDLE,
                    current_attempt_id=f"attempt-{node_id}",
                    depends_on=frozenset(),
                    feature_checkpoint=FeatureCheckpoint(
                        feature_id=f"feature-{node_id}",
                        sequence=1,
                        title=f"task {node_id}",
                        worktree_path=f"/workspace/.memstack/worktrees/attempt-{node_id}",
                        commit_ref=commit_ref,
                    ),
                    metadata={
                        "terminal_attempt_status": "accepted",
                        "verified_commit_ref": commit_ref,
                        "worktree_integration_commit_ref": commit_ref,
                        "worktree_integration_status": "blocked_dirty_main",
                        "verification_evidence_refs": [f"commit_ref:{commit_ref}"],
                    },
                )
            )
        plan.add_node(
            PlanNode(
                id="review",
                plan_id=plan.id,
                parent_id=plan.goal_id,
                kind=PlanNodeKind.TASK,
                title="Final sprint review",
                intent=TaskIntent.TODO,
                execution=TaskExecution.IDLE,
                depends_on=frozenset({PlanNodeId("a"), PlanNodeId("b")}),
                feature_checkpoint=FeatureCheckpoint(
                    feature_id="feature-review",
                    sequence=2,
                    title="Final sprint review",
                    base_ref="HEAD",
                ),
                metadata={
                    "iteration_phase": "review",
                    "scrum_artifact": "feedback",
                },
            )
        )
        await repo.save(plan)

        dispatched: list[str] = []
        dispatched_base_refs: list[str | None] = []
        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return [
                WorkspaceAgent(
                    agent_id="ag-code",
                    display_name="C",
                    capabilities=frozenset({"codegen", "web_search"}),
                )
            ]

        async def dispatcher(_wid: str, _alloc: Any, node: PlanNode) -> str:
            dispatched.append(node.id)
            dispatched_base_refs.append(
                node.feature_checkpoint.base_ref if node.feature_checkpoint else None
            )
            return f"attempt-{node.id}"

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(workspace_id=wid, node=node)

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_AlwaysPassVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.allocations_made == 1
        assert dispatched == ["review"]
        assert dispatched_base_refs == ["commit-b"]
        assert not [
            event for event in events if event[0] == "dispatch_deferred_dependency_projection"
        ]

    async def test_tick_dispatches_plan_backlog_with_blocked_dirty_main_dependencies(
        self,
    ) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        for node_id, commit_ref in (("a", "commit-a"), ("b", "commit-b")):
            node = plan.nodes[PlanNodeId(node_id)]
            plan.replace_node(
                replace(
                    node,
                    intent=TaskIntent.DONE,
                    execution=TaskExecution.IDLE,
                    current_attempt_id=f"attempt-{node_id}",
                    depends_on=frozenset(),
                    feature_checkpoint=FeatureCheckpoint(
                        feature_id=f"feature-{node_id}",
                        sequence=1,
                        title=f"task {node_id}",
                        worktree_path=f"/workspace/.memstack/worktrees/attempt-{node_id}",
                        commit_ref=commit_ref,
                    ),
                    metadata={
                        "terminal_attempt_status": "accepted",
                        "verified_commit_ref": commit_ref,
                        "worktree_integration_commit_ref": commit_ref,
                        "worktree_integration_status": "blocked_dirty_main",
                        "verification_evidence_refs": [f"commit_ref:{commit_ref}"],
                    },
                )
            )
        plan.add_node(
            PlanNode(
                id="backlog",
                plan_id=plan.id,
                parent_id=plan.goal_id,
                kind=PlanNodeKind.TASK,
                title="Implement planned backlog item",
                intent=TaskIntent.TODO,
                execution=TaskExecution.IDLE,
                depends_on=frozenset({PlanNodeId("a"), PlanNodeId("b")}),
                feature_checkpoint=FeatureCheckpoint(
                    feature_id="feature-backlog",
                    sequence=2,
                    title="Implement planned backlog item",
                    base_ref="HEAD",
                ),
                metadata={
                    "iteration_phase": "plan",
                    "scrum_artifact": "sprint_backlog",
                },
            )
        )
        await repo.save(plan)

        dispatched: list[str] = []
        dispatched_base_refs: list[str | None] = []
        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return [
                WorkspaceAgent(
                    agent_id="ag-code",
                    display_name="C",
                    capabilities=frozenset({"codegen", "web_search"}),
                )
            ]

        async def dispatcher(_wid: str, _alloc: Any, node: PlanNode) -> str:
            dispatched.append(node.id)
            dispatched_base_refs.append(
                node.feature_checkpoint.base_ref if node.feature_checkpoint else None
            )
            return f"attempt-{node.id}"

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(workspace_id=wid, node=node)

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_AlwaysPassVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.allocations_made == 1
        assert dispatched == ["backlog"]
        assert dispatched_base_refs == ["commit-b"]
        assert not [
            event for event in events if event[0] == "dispatch_deferred_dependency_projection"
        ]

    async def test_tick_dispatches_test_verification_with_blocked_dirty_main_dependencies(
        self,
    ) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        for node_id, commit_ref in (("a", "commit-a"), ("b", "commit-b")):
            node = plan.nodes[PlanNodeId(node_id)]
            plan.replace_node(
                replace(
                    node,
                    intent=TaskIntent.DONE,
                    execution=TaskExecution.IDLE,
                    current_attempt_id=f"attempt-{node_id}",
                    depends_on=frozenset(),
                    feature_checkpoint=FeatureCheckpoint(
                        feature_id=f"feature-{node_id}",
                        sequence=1,
                        title=f"task {node_id}",
                        worktree_path=f"/workspace/.memstack/worktrees/attempt-{node_id}",
                        commit_ref=commit_ref,
                    ),
                    metadata={
                        "terminal_attempt_status": "accepted",
                        "verified_commit_ref": commit_ref,
                        "worktree_integration_commit_ref": commit_ref,
                        "worktree_integration_status": "blocked_dirty_main",
                        "verification_evidence_refs": [f"commit_ref:{commit_ref}"],
                    },
                )
            )
        plan.add_node(
            PlanNode(
                id="verification",
                plan_id=plan.id,
                parent_id=plan.goal_id,
                kind=PlanNodeKind.TASK,
                title="Run journey verification",
                intent=TaskIntent.TODO,
                execution=TaskExecution.IDLE,
                depends_on=frozenset({PlanNodeId("a"), PlanNodeId("b")}),
                feature_checkpoint=FeatureCheckpoint(
                    feature_id="feature-verification",
                    sequence=2,
                    title="Run journey verification",
                    base_ref="HEAD",
                ),
                metadata={
                    "iteration_phase": "test",
                    "scrum_artifact": "verification",
                },
            )
        )
        await repo.save(plan)

        dispatched: list[str] = []
        dispatched_base_refs: list[str | None] = []
        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return [
                WorkspaceAgent(
                    agent_id="ag-code",
                    display_name="C",
                    capabilities=frozenset({"codegen", "web_search"}),
                )
            ]

        async def dispatcher(_wid: str, _alloc: Any, node: PlanNode) -> str:
            dispatched.append(node.id)
            dispatched_base_refs.append(
                node.feature_checkpoint.base_ref if node.feature_checkpoint else None
            )
            return f"attempt-{node.id}"

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(workspace_id=wid, node=node)

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_AlwaysPassVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.allocations_made == 1
        assert dispatched == ["verification"]
        assert dispatched_base_refs == ["commit-b"]
        assert not [
            event for event in events if event[0] == "dispatch_deferred_dependency_projection"
        ]

    async def test_tick_dispatches_release_candidate_with_blocked_dirty_main_dependencies(
        self,
    ) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        unused_leaf = plan.nodes[PlanNodeId("b")]
        plan.replace_node(
            replace(
                unused_leaf,
                intent=TaskIntent.DONE,
                execution=TaskExecution.IDLE,
                depends_on=frozenset(),
            )
        )
        dependency = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                dependency,
                intent=TaskIntent.DONE,
                execution=TaskExecution.IDLE,
                current_attempt_id="attempt-a",
                depends_on=frozenset(),
                feature_checkpoint=FeatureCheckpoint(
                    feature_id="feature-a",
                    sequence=1,
                    title="publish artifacts",
                    worktree_path="/workspace/.memstack/worktrees/attempt-a",
                    commit_ref="commit-a",
                ),
                metadata={
                    "terminal_attempt_status": "accepted",
                    "verified_commit_ref": "commit-a",
                    "worktree_integration_commit_ref": "commit-a",
                    "worktree_integration_status": "blocked_dirty_main",
                    "verification_evidence_refs": ["commit_ref:commit-a"],
                },
            )
        )
        plan.add_node(
            PlanNode(
                id="deploy",
                plan_id=plan.id,
                parent_id=plan.goal_id,
                kind=PlanNodeKind.TASK,
                title="Trigger pipeline",
                intent=TaskIntent.TODO,
                execution=TaskExecution.IDLE,
                depends_on=frozenset({PlanNodeId("a")}),
                feature_checkpoint=FeatureCheckpoint(
                    feature_id="feature-deploy",
                    sequence=2,
                    title="Trigger pipeline",
                    base_ref="HEAD",
                ),
                metadata={
                    "iteration_phase": "deploy",
                    "scrum_artifact": "release_candidate",
                },
            )
        )
        await repo.save(plan)

        dispatched: list[str] = []
        dispatched_base_refs: list[str | None] = []
        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return [
                WorkspaceAgent(
                    agent_id="ag-code",
                    display_name="C",
                    capabilities=frozenset({"codegen", "web_search"}),
                )
            ]

        async def dispatcher(_wid: str, _alloc: Any, node: PlanNode) -> str:
            dispatched.append(node.id)
            dispatched_base_refs.append(
                node.feature_checkpoint.base_ref if node.feature_checkpoint else None
            )
            return f"attempt-{node.id}"

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(workspace_id=wid, node=node)

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_AlwaysPassVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.allocations_made == 1
        assert dispatched == ["deploy"]
        assert dispatched_base_refs == ["commit-a"]
        assert not [
            event for event in events if event[0] == "dispatch_deferred_dependency_projection"
        ]

    async def test_tick_dispatches_after_supervisor_disposed_dependency(
        self,
    ) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        dependency = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                dependency,
                intent=TaskIntent.DONE,
                execution=TaskExecution.IDLE,
                current_attempt_id="attempt-a",
                depends_on=frozenset(),
                feature_checkpoint=FeatureCheckpoint(
                    feature_id="feature-a",
                    sequence=1,
                    title="stale verification",
                    worktree_path="/workspace/.memstack/worktrees/attempt-a",
                    commit_ref="stale-commit",
                ),
                metadata={
                    "verified_commit_ref": "stale-commit",
                    "verification_feedback_disposition": "supervisor_agent_disposed_node",
                    "last_supervisor_decision_action": "dispose_node",
                    "last_supervisor_decision_rationale": (
                        "stale node structurally superseded by completed sibling"
                    ),
                },
            )
        )
        await repo.save(plan)

        dispatched: list[str] = []
        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return [
                WorkspaceAgent(
                    agent_id="ag-code",
                    display_name="C",
                    capabilities=frozenset({"codegen"}),
                )
            ]

        async def dispatcher(_wid: str, _alloc: Any, node: PlanNode) -> str:
            dispatched.append(node.id)
            return f"attempt-{node.id}"

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(workspace_id=wid, node=node)

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_AlwaysPassVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.allocations_made == 1
        assert dispatched == ["b"]
        assert not [
            event for event in events if event[0] == "dispatch_deferred_dependency_projection"
        ]

    async def test_tick_invalidates_active_downstream_node_when_dependency_regresses(
        self,
    ) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        b = plan.nodes[PlanNodeId("b")]
        plan.replace_node(
            replace(
                b,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.RUNNING,
                current_attempt_id="attempt-b",
                assignee_agent_id="ag-code",
                feature_checkpoint=FeatureCheckpoint(
                    feature_id="feature-b",
                    sequence=2,
                    worktree_path="${sandbox_code_root}/../.memstack/worktrees/attempt-b",
                    branch_name="workspace/b-attempt-b",
                    base_ref="old-base",
                    commit_ref="old-commit",
                ),
                metadata={
                    "candidate_artifacts": ["commit_ref:old-commit"],
                    "deployment_status": "deployed",
                    "evidence_refs": ["ci_pipeline:passed"],
                    "execution_verifications": ["ci_pipeline:passed"],
                    "external_id": "s1366560/my-evo#13",
                    "last_verification_passed": True,
                    "last_worker_report_attempt_id": "attempt-b",
                    "last_worker_report_artifacts": ["commit_ref:old-commit"],
                    "last_worker_report_summary": "old report",
                    "last_worker_report_type": "completed",
                    "last_worker_report_verifications": ["worker_report:completed"],
                    "pipeline_evidence_refs": ["ci_pipeline:passed"],
                    "pipeline_status": "success",
                    "reported_attempt_status": "awaiting_leader_adjudication",
                    "source_publish_commit_ref": "old-commit",
                    "source_publish_status": "published",
                    "terminal_attempt_superseded_attempt_id": "old-parent",
                    "terminal_attempt_superseded_reason": "parent_done",
                    "terminal_attempt_superseded_status": "cancelled",
                    "worktree_integration_commit_ref": "old-commit",
                    "worktree_integration_status": "already_merged",
                },
            )
        )
        await repo.save(plan)

        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, _alloc: Any, _node: PlanNode) -> str | None:
            return None

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(workspace_id=wid, node=node)

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_AlwaysPassVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.allocations_made == 0
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        invalidated = reloaded.nodes[PlanNodeId("b")]
        assert invalidated.intent is TaskIntent.TODO
        assert invalidated.execution is TaskExecution.IDLE
        assert invalidated.current_attempt_id is None
        assert invalidated.assignee_agent_id is None
        assert invalidated.metadata["dependency_invalidated_missing_ids"] == ["a"]
        assert invalidated.metadata["dependency_invalidated_previous_attempt_id"] == "attempt-b"
        assert "last_verification_passed" not in invalidated.metadata
        assert "pipeline_status" not in invalidated.metadata
        assert invalidated.feature_checkpoint is not None
        assert invalidated.feature_checkpoint.worktree_path is None
        assert invalidated.feature_checkpoint.branch_name is None
        assert invalidated.feature_checkpoint.base_ref == "HEAD"
        assert invalidated.feature_checkpoint.commit_ref is None
        for stale_key in (
            "candidate_artifacts",
            "deployment_status",
            "evidence_refs",
            "execution_verifications",
            "external_id",
            "last_worker_report_attempt_id",
            "last_worker_report_artifacts",
            "last_worker_report_summary",
            "last_worker_report_type",
            "last_worker_report_verifications",
            "pipeline_evidence_refs",
            "reported_attempt_status",
            "source_publish_commit_ref",
            "source_publish_status",
            "terminal_attempt_superseded_attempt_id",
            "terminal_attempt_superseded_reason",
            "terminal_attempt_superseded_status",
            "worktree_integration_commit_ref",
            "worktree_integration_status",
        ):
            assert stale_key not in invalidated.metadata
        assert events == [
            (
                "dependency_invalidated",
                "b",
                {
                    "summary": "node reset because one or more dependencies are not ready",
                    "missing_dependency_ids": ["a"],
                    "previous_attempt_id": "attempt-b",
                    "previous_intent": "in_progress",
                    "previous_execution": "running",
                },
            )
        ]

    async def test_tick_accepts_repair_alternative_before_invalidating_dependents(
        self,
    ) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        a = plan.nodes[PlanNodeId("a")]
        b = plan.nodes[PlanNodeId("b")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.BLOCKED,
                execution=TaskExecution.IDLE,
                current_attempt_id=None,
                depends_on=frozenset({PlanNodeId("repair-a")}),
                metadata={
                    "blocked_by_repair_node_id": "repair-a",
                    "last_verification_judge_next_action_kind": "create_repair_node",
                    "last_verification_attempt_id": "stale-attempt-a",
                    "terminal_attempt_status": "rejected",
                    "terminal_attempt_retry_count": 12,
                    "verified_commit_ref": "stale-a",
                    "worktree_integration_status": "pending",
                    "worktree_integration_worktree_path": (
                        "/workspace/.memstack/worktrees/stale-a"
                    ),
                },
            )
        )
        plan.replace_node(
            replace(
                b,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.RUNNING,
                current_attempt_id="attempt-b",
                assignee_agent_id="ag-code",
            )
        )
        plan.add_node(
            PlanNode(
                id="repair-a",
                plan_id=plan.id,
                parent_id=PlanNodeId("goal-1"),
                kind=PlanNodeKind.TASK,
                title="accepted repair",
                intent=TaskIntent.DONE,
                execution=TaskExecution.IDLE,
                metadata={
                    "repair_for_node_id": "a",
                    "repair_source": "verification_judge_create_repair_node",
                    "source_verification_judge_next_action_kind": "create_repair_node",
                    "last_verification_passed": True,
                    "last_verification_judge_verdict": "accepted",
                    "last_verification_summary": "verified corrected target",
                    "verified_commit_ref": "f9264bf",
                    "worktree_integration_commit_ref": "f9264bf",
                    "worktree_integration_status": "merged",
                    "worktree_integration_worktree_path": (
                        "/workspace/.memstack/worktrees/repair-a"
                    ),
                    "verification_evidence_refs": [
                        "preflight:read-progress",
                        "commit_ref:f9264bf",
                        "worker_report:completed",
                    ],
                },
            )
        )
        await repo.save(plan)

        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, _alloc: Any, _node: PlanNode) -> str | None:
            return None

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(workspace_id=wid, node=node)

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_AlwaysPassVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.nodes_completed == 1
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        accepted = reloaded.nodes[PlanNodeId("a")]
        downstream = reloaded.nodes[PlanNodeId("b")]
        assert accepted.intent is TaskIntent.DONE
        assert accepted.metadata["verified_commit_ref"] == "f9264bf"
        assert "last_verification_attempt_id" not in accepted.metadata
        assert "terminal_attempt_status" not in accepted.metadata
        assert "terminal_attempt_retry_count" not in accepted.metadata
        assert downstream.intent is TaskIntent.IN_PROGRESS
        assert downstream.execution is TaskExecution.RUNNING
        assert downstream.current_attempt_id == "attempt-b"
        assert [event for event in events if event[0] == "verification_feedback_disposition"] == [
            (
                "verification_feedback_disposition",
                "a",
                {
                    "attempt_id": None,
                    "disposition": "accepted_via_repair_alternative",
                    "repair_node_id": "repair-a",
                    "feedback_items": [],
                    "summary": accepted.metadata.get("last_verification_summary"),
                },
            )
        ]
        assert not [event for event in events if event[0] == "dependency_invalidated"]

    async def test_tick_invalidates_active_downstream_node_when_dependency_not_integrated(
        self,
    ) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        a = plan.nodes[PlanNodeId("a")]
        b = plan.nodes[PlanNodeId("b")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.DONE,
                execution=TaskExecution.IDLE,
                feature_checkpoint=FeatureCheckpoint(
                    feature_id="feature-a",
                    sequence=1,
                    title="task a",
                    worktree_path="/workspace/.memstack/worktrees/attempt-a",
                    commit_ref="abc123",
                ),
                metadata={"verified_commit_ref": "abc123"},
            )
        )
        plan.replace_node(
            replace(
                b,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.RUNNING,
                current_attempt_id="attempt-b",
                assignee_agent_id="ag-code",
                metadata={"last_verification_passed": True},
            )
        )
        await repo.save(plan)

        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, _alloc: Any, _node: PlanNode) -> str | None:
            return None

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(workspace_id=wid, node=node)

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_AlwaysPassVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.allocations_made == 0
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        invalidated = reloaded.nodes[PlanNodeId("b")]
        assert invalidated.intent is TaskIntent.TODO
        assert invalidated.execution is TaskExecution.IDLE
        assert invalidated.current_attempt_id is None
        assert invalidated.metadata["dependency_invalidated_missing_ids"] == ["a"]
        assert invalidated.metadata["dependency_invalidated_reason"] == (
            "dependencies_not_done_or_not_integrated"
        )
        assert "last_verification_passed" not in invalidated.metadata
        assert events[0][0] == "dependency_invalidated"
        assert events[0][1] == "b"

    async def test_mark_worker_reported_ignores_stale_attempt_after_node_was_invalidated(
        self,
    ) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        b = plan.nodes[PlanNodeId("b")]
        plan.replace_node(
            replace(
                b,
                intent=TaskIntent.TODO,
                execution=TaskExecution.IDLE,
                current_attempt_id=None,
                metadata={"dependency_invalidated_previous_attempt_id": "old-attempt"},
            )
        )
        await repo.save(plan)

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, _alloc: Any, _node: PlanNode) -> str | None:
            return None

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(workspace_id=wid, node=node)

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_AlwaysPassVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            heartbeat_seconds=0.05,
        )
        orch = WorkspaceOrchestrator(
            planner=LLMGoalPlanner(decomposer=None),
            allocator=CapabilityAllocator(),
            verifier=_AlwaysPassVerifier(),
            projector=ProgressProjector(),
            supervisor=sup,
            plan_repo=repo,
        )

        await orch.mark_worker_reported(
            workspace_id="ws-1",
            node_id="b",
            attempt_id="old-attempt",
        )

        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        stale = reloaded.nodes[PlanNodeId("b")]
        assert stale.intent is TaskIntent.TODO
        assert stale.execution is TaskExecution.IDLE
        assert stale.current_attempt_id is None

    async def test_tick_defers_ready_node_overlapping_active_write_set(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        from dataclasses import replace

        a = plan.nodes[PlanNodeId("a")]
        b = plan.nodes[PlanNodeId("b")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.RUNNING,
                current_attempt_id="attempt-a",
                metadata={"write_set": ["src/shared.ts"]},
            )
        )
        plan.replace_node(
            replace(
                b,
                depends_on=frozenset(),
                metadata={"write_set": ["src/shared.ts"]},
            )
        )
        await repo.save(plan)

        dispatched: list[str] = []
        events: list[tuple[str, str]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return [
                WorkspaceAgent(
                    agent_id="ag-code",
                    display_name="C",
                    capabilities=frozenset({"codegen", "web_search"}),
                )
            ]

        async def dispatcher(_wid: str, alloc, node) -> str:  # type: ignore[no-untyped-def]
            dispatched.append(node.id)
            return f"attempt-{node.id}"

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(workspace_id=wid, node=node)

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            _payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_AlwaysPassVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.allocations_made == 0
        assert dispatched == []
        assert events == [("dispatch_deferred_write_conflict", "b")]

    async def test_tick_limits_dispatches_per_tick(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        from dataclasses import replace

        b = plan.nodes[PlanNodeId("b")]
        plan.replace_node(replace(b, depends_on=frozenset()))
        await repo.save(plan)

        dispatched: list[str] = []
        events: list[tuple[str, str, int | None]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return [
                WorkspaceAgent(
                    agent_id="ag-code",
                    display_name="C",
                    capabilities=frozenset({"codegen", "web_search"}),
                )
            ]

        async def dispatcher(_wid: str, alloc, node) -> str:  # type: ignore[no-untyped-def]
            dispatched.append(node.id)
            return f"attempt-{node.id}"

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(workspace_id=wid, node=node)

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload.get("max_dispatches_per_tick")))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_AlwaysPassVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
            max_dispatches_per_tick=1,
        )

        report = await sup.tick("ws-1")

        assert report.allocations_made == 1
        assert len(dispatched) == 1
        assert events == [("dispatch_deferred_concurrency_limit", "b", 1)]

    async def test_retryable_infrastructure_failure_schedules_backoff(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        from dataclasses import replace

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-a",
            )
        )
        await repo.save(plan)

        dispatched: list[str] = []
        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, alloc, node) -> str:  # type: ignore[no-untyped-def]
            dispatched.append(node.id)
            return f"attempt-{node.id}"

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid, node=node, attempt_id=node.current_attempt_id
            )

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_RetryableInfrastructureVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 1
        assert report.nodes_blocked == 0
        assert report.allocations_made == 0
        assert dispatched == []
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        retry_node = reloaded.nodes[PlanNodeId("a")]
        assert retry_node.intent is TaskIntent.TODO
        assert retry_node.execution is TaskExecution.IDLE
        assert retry_node.current_attempt_id is None
        assert retry_node.metadata["retry_count"] == 1
        assert retry_node.metadata["retry_not_before"].endswith("Z")
        assert retry_node.metadata["last_verification_attempt_id"] == "attempt-a"
        assert (
            "retryable infrastructure failure" in retry_node.metadata["last_verification_summary"]
        )
        assert retry_node.metadata["last_verification_passed"] is False
        retry_events = [event for event in events if event[0] == "verification_retry_scheduled"]
        assert len(retry_events) == 1
        assert retry_events[0][2]["retry_count"] == 1

    async def test_verification_judge_infrastructure_retry_keeps_reported_attempt(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        from dataclasses import replace

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-a",
            )
        )
        await repo.save(plan)

        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, alloc, node) -> str:  # type: ignore[no-untyped-def]
            raise AssertionError("verification judge retry must not redispatch worker")

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid,
                node=node,
                attempt_id=node.current_attempt_id,
            )

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_VerificationJudgeRetryVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 1
        assert report.allocations_made == 0
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        retry_node = reloaded.nodes[PlanNodeId("a")]
        assert retry_node.intent is TaskIntent.IN_PROGRESS
        assert retry_node.execution is TaskExecution.REPORTED
        assert retry_node.current_attempt_id == "attempt-a"
        assert retry_node.metadata["retry_count"] == 1
        assert retry_node.metadata["retry_not_before"].endswith("Z")
        assert retry_node.metadata["last_verification_judge_verdict"] == "retry_infrastructure"
        assert retry_node.metadata["retry_verification_only"] is True
        retry_events = [event for event in events if event[0] == "verification_retry_scheduled"]
        assert len(retry_events) == 1
        assert retry_events[0][2]["retry_verification_only"] is True

    async def test_verification_judge_retry_with_guard_failure_redispatches_node(
        self,
    ) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        from dataclasses import replace

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-a",
            )
        )
        await repo.save(plan)

        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, alloc, node) -> str:  # type: ignore[no-untyped-def]
            raise AssertionError("retry backoff should not redispatch in the same tick")

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid,
                node=node,
                attempt_id=node.current_attempt_id,
            )

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_VerificationJudgeRetryWithGuardFailureVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 1
        assert report.allocations_made == 0
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        retry_node = reloaded.nodes[PlanNodeId("a")]
        assert retry_node.intent is TaskIntent.TODO
        assert retry_node.execution is TaskExecution.IDLE
        assert retry_node.current_attempt_id is None
        assert retry_node.metadata["retry_count"] == 1
        assert retry_node.metadata["retry_not_before"].endswith("Z")
        assert retry_node.metadata["last_verification_judge_verdict"] == "retry_infrastructure"
        assert "retry_verification_only" not in retry_node.metadata
        retry_events = [event for event in events if event[0] == "verification_retry_scheduled"]
        assert len(retry_events) == 1
        assert "retry_verification_only" not in retry_events[0][2]

    async def test_pipeline_runtime_failure_with_judge_retry_requests_pipeline(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        from dataclasses import replace

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-a",
                metadata={"pipeline_required": True, "pipeline_status": "failed"},
            )
        )
        await repo.save(plan)

        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, alloc, node) -> str:  # type: ignore[no-untyped-def]
            raise AssertionError("pipeline runtime retry should not redispatch worker")

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid,
                node=node,
                attempt_id=node.current_attempt_id,
            )

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_PipelineRuntimeFailureWithJudgeRetryVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 1
        assert report.allocations_made == 0
        assert any(event[0] == "pipeline_run_requested" for event in events)
        assert not any(event[0] == "verification_retry_scheduled" for event in events)
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        retry_node = reloaded.nodes[PlanNodeId("a")]
        assert retry_node.intent is TaskIntent.IN_PROGRESS
        assert retry_node.execution is TaskExecution.IDLE
        assert retry_node.metadata["pipeline_gate_status"] == "requested"

    async def test_repairable_infrastructure_judge_creates_repair_node(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        from dataclasses import replace

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-a",
            )
        )
        await repo.save(plan)

        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, alloc, node) -> str:  # type: ignore[no-untyped-def]
            raise AssertionError("repairable infrastructure failure must replan, not redispatch")

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid,
                node=node,
                attempt_id=node.current_attempt_id,
            )

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_VerificationJudgeRepairInfrastructureVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 1
        assert report.allocations_made == 0
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        repaired_node = reloaded.nodes[PlanNodeId("a")]
        repair_id = repaired_node.metadata["blocked_by_repair_node_id"]
        repair_node = reloaded.nodes[PlanNodeId(repair_id)]
        assert repaired_node.intent is TaskIntent.TODO
        assert repaired_node.execution is TaskExecution.IDLE
        assert repaired_node.current_attempt_id is None
        assert repaired_node.metadata["last_verification_judge_verdict"] == "retry_infrastructure"
        assert repair_node.metadata["repair_failure_signature"] == "sandbox-no-docker-runtime"
        assert repair_node.metadata["repair_for_node_id"] == "a"
        assert not any(event[0] == "verification_retry_scheduled" for event in events)

    async def test_docker_runtime_hard_fail_creates_repair_node(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        from dataclasses import replace

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-a",
            )
        )
        await repo.save(plan)

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, alloc, node) -> str:  # type: ignore[no-untyped-def]
            raise AssertionError("docker runtime hard-fail should create a repair node")

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid,
                node=node,
                attempt_id=node.current_attempt_id,
            )

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_BlockedHumanDockerRuntimeVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 1
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        repaired_node = reloaded.nodes[PlanNodeId("a")]
        repair_id = repaired_node.metadata["blocked_by_repair_node_id"]
        repair_node = reloaded.nodes[PlanNodeId(repair_id)]
        assert repaired_node.intent is TaskIntent.TODO
        assert repaired_node.execution is TaskExecution.IDLE
        assert repaired_node.current_attempt_id is None
        assert repair_node.metadata["repair_failure_signature"] == (
            "docker-runtime-unavailable-sandbox"
        )

    async def test_followup_sandbox_docker_runtime_human_required_is_disposed(
        self,
    ) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        from dataclasses import replace

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-a",
                metadata={
                    **dict(a.metadata or {}),
                    "iteration_index": 2,
                    "iteration_phase": "test",
                },
            )
        )
        await repo.save(plan)

        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, alloc, node) -> str:  # type: ignore[no-untyped-def]
            raise AssertionError("sandbox Docker runtime limit must not redispatch")

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid,
                node=node,
                attempt_id=node.current_attempt_id,
            )

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_BlockedHumanDockerRuntimeVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 1
        assert report.nodes_completed == 1
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        disposed = reloaded.nodes[PlanNodeId("a")]
        assert disposed.intent is TaskIntent.DONE
        assert disposed.execution is TaskExecution.IDLE
        assert disposed.metadata["verification_feedback_disposition"] == (
            "sandbox_docker_runtime_unavailable"
        )
        assert disposed.metadata["obsolete_by_verifier_feedback"] is False
        repair_nodes = [
            node
            for node in reloaded.nodes.values()
            if node.metadata.get("repair_for_node_id") == "a"
        ]
        assert repair_nodes == []
        disposition_events = [
            event for event in events if event[0] == "verification_feedback_disposition"
        ]
        assert disposition_events[0][2]["disposition"] == ("sandbox_docker_runtime_unavailable")

    async def test_completed_docker_repair_alternative_accepts_original_node(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        from dataclasses import replace

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-a",
            )
        )
        plan.add_node(
            PlanNode(
                id="repair-a",
                plan_id=plan.id,
                parent_id=PlanNodeId("goal-1"),
                kind=PlanNodeKind.TASK,
                title="accepted docker runtime repair",
                intent=TaskIntent.DONE,
                execution=TaskExecution.IDLE,
                metadata={
                    "repair_for_node_id": "a",
                    "last_verification_passed": True,
                    "last_verification_summary": "verified alternative Docker evidence",
                    "verification_evidence_refs": [
                        "contract_disposition:repair_node",
                        "docker_registry_reachability:http://host.docker.internal:5001/v2/my-evo/tags/list",
                        "server:node dist/index.js health endpoint HTTP 200",
                    ],
                },
            )
        )
        await repo.save(plan)

        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, alloc, node) -> str:  # type: ignore[no-untyped-def]
            raise AssertionError("accepted repair alternative must not create another worker")

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid,
                node=node,
                attempt_id=node.current_attempt_id,
            )

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_BlockedHumanDockerRuntimeVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 1
        assert report.nodes_completed == 1
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        accepted = reloaded.nodes[PlanNodeId("a")]
        assert accepted.intent is TaskIntent.DONE
        assert accepted.execution is TaskExecution.IDLE
        assert accepted.metadata["last_verification_passed"] is True
        assert accepted.metadata["verification_feedback_disposition"] == (
            "accepted_via_repair_alternative"
        )
        assert accepted.metadata["accepted_repair_node_id"] == "repair-a"
        repair_nodes = [
            node
            for node in reloaded.nodes.values()
            if node.metadata.get("repair_for_node_id") == "a"
        ]
        assert [node.id for node in repair_nodes] == ["repair-a"]
        disposition_events = [
            event for event in events if event[0] == "verification_feedback_disposition"
        ]
        assert disposition_events[0][2]["disposition"] == "accepted_via_repair_alternative"

    async def test_duplicate_docker_runtime_repair_is_superseded_by_completed_alternative(
        self,
    ) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        from dataclasses import replace

        a = plan.nodes[PlanNodeId("a")]
        duplicate_repair_id = PlanNodeId("repair-duplicate")
        plan.replace_node(
            replace(
                a,
                depends_on=frozenset({duplicate_repair_id}),
                metadata={"blocked_by_repair_node_id": duplicate_repair_id.value},
            )
        )
        plan.add_node(
            PlanNode(
                id="repair-a",
                plan_id=plan.id,
                parent_id=PlanNodeId("goal-1"),
                kind=PlanNodeKind.TASK,
                title="accepted docker runtime repair",
                intent=TaskIntent.DONE,
                execution=TaskExecution.IDLE,
                metadata={
                    "repair_for_node_id": "a",
                    "last_verification_passed": True,
                    "verification_evidence_refs": [
                        "contract_disposition:infrastructure_limitation",
                        "registry_verify:host.docker.internal:5001/my-evo:drone-docker-e2e",
                        "health_check:http://127.0.0.1:3001/health HTTP 200",
                    ],
                },
            )
        )
        plan.add_node(
            PlanNode(
                id=duplicate_repair_id.value,
                plan_id=plan.id,
                parent_id=PlanNodeId("goal-1"),
                kind=PlanNodeKind.TASK,
                title="duplicate docker runtime repair",
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-duplicate",
                metadata={"repair_for_node_id": "a"},
            )
        )
        await repo.save(plan)

        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, alloc, node) -> str:  # type: ignore[no-untyped-def]
            raise AssertionError("duplicate repair must be closed without worker redispatch")

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid,
                node=node,
                attempt_id=node.current_attempt_id,
            )

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_VerifierShouldNotRun(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 0
        assert report.nodes_completed == 2
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        original = reloaded.nodes[PlanNodeId("a")]
        assert original.intent is TaskIntent.DONE
        assert original.execution is TaskExecution.IDLE
        assert original.metadata["verification_feedback_disposition"] == (
            "accepted_via_repair_alternative"
        )
        assert original.metadata["accepted_repair_node_id"] == "repair-a"
        duplicate = reloaded.nodes[duplicate_repair_id]
        assert duplicate.intent is TaskIntent.DONE
        assert duplicate.execution is TaskExecution.IDLE
        assert duplicate.metadata["verification_feedback_disposition"] == (
            "superseded_by_completed_repair_alternative"
        )
        assert duplicate.metadata["accepted_repair_node_id"] == "repair-a"
        nested_repairs = [
            node
            for node in reloaded.nodes.values()
            if node.metadata.get("repair_for_node_id") == duplicate_repair_id.value
        ]
        assert nested_repairs == []
        disposition_events = [
            event for event in events if event[0] == "verification_feedback_disposition"
        ]
        assert disposition_events[0][1] == duplicate_repair_id.value
        assert disposition_events[0][2]["disposition"] == (
            "superseded_by_completed_repair_alternative"
        )

    async def test_ready_docker_runtime_node_accepts_completed_repair_before_dispatch(
        self,
    ) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        from dataclasses import replace

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.TODO,
                execution=TaskExecution.IDLE,
                metadata={
                    "last_verification_feedback_items": [
                        {
                            "failure_signature": "docker-runtime-unavailable-sandbox",
                            "summary": "Docker runtime is unavailable in the sandbox.",
                            "recommended_action": "retry_infra",
                        }
                    ],
                },
            )
        )
        plan.add_node(
            PlanNode(
                id="repair-a",
                plan_id=plan.id,
                parent_id=PlanNodeId("goal-1"),
                kind=PlanNodeKind.TASK,
                title="accepted docker runtime repair",
                intent=TaskIntent.DONE,
                execution=TaskExecution.IDLE,
                metadata={
                    "repair_for_node_id": "a",
                    "last_verification_passed": True,
                    "verification_evidence_refs": [
                        "contract_disposition:repair_node",
                        "docker_registry_reachability:http://host.docker.internal:5001/v2/my-evo/tags/list",
                        "server:node dist/index.js health endpoint HTTP 200",
                    ],
                },
            )
        )
        await repo.save(plan)

        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return [WorkspaceAgent(id="agent-1", capabilities=(Capability(name="codegen"),))]

        async def dispatcher(_wid: str, alloc, node) -> str:  # type: ignore[no-untyped-def]
            raise AssertionError("ready node must be accepted before worker dispatch")

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid, node=node, attempt_id=node.current_attempt_id
            )

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_VerifierShouldNotRun(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 0
        assert report.allocations_made == 0
        assert report.nodes_completed == 1
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        accepted = reloaded.nodes[PlanNodeId("a")]
        assert accepted.intent is TaskIntent.DONE
        assert accepted.execution is TaskExecution.IDLE
        assert accepted.metadata["verification_feedback_disposition"] == (
            "accepted_via_repair_alternative"
        )
        assert accepted.metadata["accepted_repair_node_id"] == "repair-a"
        disposition_events = [
            event for event in events if event[0] == "verification_feedback_disposition"
        ]
        assert disposition_events[0][1] == "a"
        assert disposition_events[0][2]["disposition"] == "accepted_via_repair_alternative"

    async def test_ready_judge_repair_node_accepts_original_before_redispatch(
        self,
    ) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.TODO,
                execution=TaskExecution.IDLE,
                metadata={
                    "blocked_by_repair_node_id": "repair-a",
                    "last_verification_judge_next_action_kind": "create_repair_node",
                    "last_verification_judge_verdict": "needs_rework",
                },
            )
        )
        plan.add_node(
            PlanNode(
                id="repair-a",
                plan_id=plan.id,
                parent_id=PlanNodeId("goal-1"),
                kind=PlanNodeKind.TASK,
                title="accepted stale target repair",
                intent=TaskIntent.DONE,
                execution=TaskExecution.IDLE,
                metadata={
                    "repair_for_node_id": "a",
                    "repair_source": "verification_judge_create_repair_node",
                    "source_verification_judge_next_action_kind": "create_repair_node",
                    "last_verification_passed": True,
                    "last_verification_judge_verdict": "accepted",
                    "last_verification_summary": "verified corrected target",
                    "verification_evidence_refs": [
                        "preflight:read-progress",
                        "preflight:git-status",
                        "test_run:e2e-screenshot-journey.mjs - 18 pages, 0 errors",
                        "commit_ref:852a59fe",
                        "worker_report:completed",
                    ],
                },
            )
        )
        await repo.save(plan)

        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return [WorkspaceAgent(id="agent-1", capabilities=(Capability(name="codegen"),))]

        async def dispatcher(_wid: str, alloc, node) -> str:  # type: ignore[no-untyped-def]
            raise AssertionError("verified repair alternative must not redispatch original node")

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid, node=node, attempt_id=node.current_attempt_id
            )

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_VerifierShouldNotRun(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 0
        assert report.allocations_made == 0
        assert report.nodes_completed == 1
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        accepted = reloaded.nodes[PlanNodeId("a")]
        assert accepted.intent is TaskIntent.DONE
        assert accepted.execution is TaskExecution.IDLE
        assert accepted.metadata["verification_feedback_disposition"] == (
            "accepted_via_repair_alternative"
        )
        assert accepted.metadata["accepted_repair_node_id"] == "repair-a"
        disposition_events = [
            event for event in events if event[0] == "verification_feedback_disposition"
        ]
        assert disposition_events[0][1] == "a"
        assert disposition_events[0][2]["disposition"] == "accepted_via_repair_alternative"

    def test_pipeline_required_node_waits_for_repair_commit_pipeline_success(
        self,
    ) -> None:
        plan = _plan_with_two_tasks()

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.TODO,
                execution=TaskExecution.IDLE,
                metadata={
                    "pipeline_required": True,
                    "pipeline_status": "failed",
                    "source_publish_commit_ref": "41480536",
                },
            )
        )
        plan.add_node(
            PlanNode(
                id="repair-a",
                plan_id=plan.id,
                parent_id=PlanNodeId("goal-1"),
                kind=PlanNodeKind.TASK,
                title="accepted drone repair",
                intent=TaskIntent.DONE,
                execution=TaskExecution.IDLE,
                metadata={
                    "repair_for_node_id": "a",
                    "repair_source": "verification_judge_create_repair_node",
                    "source_verification_judge_next_action_kind": "create_repair_node",
                    "last_verification_passed": True,
                    "last_verification_judge_verdict": "accepted",
                    "verification_evidence_refs": [
                        "preflight:read-progress",
                        "commit_ref:2e83bccd",
                        "worker_report:completed",
                    ],
                },
            )
        )

        accepted = _accept_ready_nodes_with_completed_repair_alternatives(plan)

        assert accepted == []
        assert plan.nodes[PlanNodeId("a")].intent is TaskIntent.TODO

    def test_pipeline_required_node_accepts_repair_after_matching_pipeline_success(
        self,
    ) -> None:
        plan = _plan_with_two_tasks()

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.TODO,
                execution=TaskExecution.IDLE,
                metadata={
                    "pipeline_required": True,
                    "pipeline_status": "success",
                    "source_publish_commit_ref": "2e83bccd1234",
                },
            )
        )
        plan.add_node(
            PlanNode(
                id="repair-a",
                plan_id=plan.id,
                parent_id=PlanNodeId("goal-1"),
                kind=PlanNodeKind.TASK,
                title="accepted drone repair",
                intent=TaskIntent.DONE,
                execution=TaskExecution.IDLE,
                metadata={
                    "repair_for_node_id": "a",
                    "repair_source": "verification_judge_create_repair_node",
                    "source_verification_judge_next_action_kind": "create_repair_node",
                    "last_verification_passed": True,
                    "last_verification_judge_verdict": "accepted",
                    "verification_evidence_refs": [
                        "preflight:read-progress",
                        "commit_ref:2e83bccd",
                        "worker_report:completed",
                    ],
                },
            )
        )

        accepted = _accept_ready_nodes_with_completed_repair_alternatives(plan)

        assert [(node.id, repair.id) for node, repair in accepted] == [("a", "repair-a")]
        assert plan.nodes[PlanNodeId("a")].intent is TaskIntent.DONE

    def test_blocked_node_accepts_completed_repair_alternative_when_dependencies_clear(
        self,
    ) -> None:
        plan = _plan_with_two_tasks()

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.BLOCKED,
                execution=TaskExecution.IDLE,
                depends_on=frozenset({PlanNodeId("repair-a")}),
                current_attempt_id=None,
                feature_checkpoint=FeatureCheckpoint(
                    feature_id="a",
                    worktree_path="/tmp/.memstack/worktrees/stale-a",
                    branch_name="workspace/a-stale",
                    base_ref="2e83bccd",
                    commit_ref="fa20cab",
                ),
                metadata={
                    "blocked_by_repair_node_id": "repair-a",
                    "verification_feedback_disposition": "accepted_via_repair_alternative",
                    "accepted_repair_node_id": "repair-a",
                    "verified_commit_ref": "fa20cab",
                    "worktree_integration_worktree_path": "/tmp/.memstack/worktrees/stale-a",
                    "worktree_integration_status": "pending",
                    "dependency_invalidated_missing_ids": ["repair-a"],
                    "last_verification_attempt_id": "stale-attempt-a",
                    "terminal_attempt_status": "rejected",
                    "terminal_attempt_retry_count": 12,
                    "active_execution_root": "/tmp/.memstack/worktrees/stale-a",
                    "worktree_path": "/tmp/.memstack/worktrees/stale-a",
                    "last_verification_passed": True,
                },
            )
        )
        plan.add_node(
            PlanNode(
                id="repair-a",
                plan_id=plan.id,
                parent_id=PlanNodeId("goal-1"),
                kind=PlanNodeKind.TASK,
                title="accepted stale target repair",
                intent=TaskIntent.DONE,
                execution=TaskExecution.IDLE,
                metadata={
                    "repair_for_node_id": "a",
                    "repair_source": "verification_judge_create_repair_node",
                    "source_verification_judge_next_action_kind": "create_repair_node",
                    "last_verification_passed": True,
                    "last_verification_judge_verdict": "accepted",
                    "last_verification_summary": "verified corrected target",
                    "verified_commit_ref": "f9264bf",
                    "worktree_integration_commit_ref": "f9264bf",
                    "worktree_integration_status": "merged",
                    "worktree_integration_worktree_path": "/tmp/.memstack/worktrees/repair-a",
                    "verification_evidence_refs": [
                        "preflight:read-progress",
                        "preflight:git-status",
                        "test_run:e2e-screenshot-journey.mjs - 18 pages, 0 errors",
                        "commit_ref:852a59fe",
                        "worker_report:completed",
                    ],
                },
            )
        )

        accepted = _accept_ready_nodes_with_completed_repair_alternatives(plan)

        assert [(node.id, repair.id) for node, repair in accepted] == [("a", "repair-a")]
        accepted_node = plan.nodes[PlanNodeId("a")]
        assert accepted_node.intent is TaskIntent.DONE
        assert accepted_node.execution is TaskExecution.IDLE
        assert accepted_node.current_attempt_id is None
        assert accepted_node.metadata["accepted_repair_node_id"] == "repair-a"
        assert accepted_node.metadata["verified_commit_ref"] == "f9264bf"
        assert accepted_node.metadata["worktree_integration_commit_ref"] == "f9264bf"
        assert accepted_node.metadata["worktree_integration_status"] == "merged"
        assert accepted_node.metadata["worktree_integration_worktree_path"] == (
            "/tmp/.memstack/worktrees/repair-a"
        )
        assert "dependency_invalidated_missing_ids" not in accepted_node.metadata
        assert "last_verification_attempt_id" not in accepted_node.metadata
        assert "terminal_attempt_status" not in accepted_node.metadata
        assert "terminal_attempt_retry_count" not in accepted_node.metadata
        assert "active_execution_root" not in accepted_node.metadata
        assert "worktree_path" not in accepted_node.metadata
        assert accepted_node.feature_checkpoint is not None
        assert accepted_node.feature_checkpoint.worktree_path is None
        assert accepted_node.feature_checkpoint.branch_name is None
        assert accepted_node.feature_checkpoint.base_ref == "HEAD"
        assert accepted_node.feature_checkpoint.commit_ref is None

    async def test_clean_stale_commit_integration_failure_does_not_block_dependencies(
        self,
    ) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.DONE,
                execution=TaskExecution.IDLE,
                metadata={
                    "terminal_attempt_status": "accepted",
                    "verified_commit_ref": "852a59fe",
                    "worktree_integration_status": "failed",
                    "worktree_integration_worktree_path": (
                        "/workspace/.memstack/worktrees/attempt-a"
                    ),
                    "worktree_integration_dirty_signature": None,
                    "worktree_integration_summary": (
                        "Exit code: 65\n"
                        "status=failed\n"
                        "reason=commit_ref not found in attempt worktree"
                    ),
                },
            )
        )
        await repo.save(plan)

        dispatched: list[str] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return [
                WorkspaceAgent(
                    agent_id="agent-1",
                    display_name="Agent One",
                    capabilities=frozenset({"codegen"}),
                )
            ]

        async def dispatcher(_wid: str, alloc, node) -> str:  # type: ignore[no-untyped-def]
            dispatched.append(node.id)
            return f"attempt-{node.id}"

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid,
                node=node,
                attempt_id=node.current_attempt_id,
            )

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_VerifierShouldNotRun(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 0
        assert report.allocations_made == 1
        assert dispatched == ["b"]
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        assert reloaded.nodes[PlanNodeId("b")].execution is TaskExecution.DISPATCHED

    async def test_planner_feedback_obsoletes_stale_node_without_worker_retry(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        from dataclasses import replace

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-a",
            )
        )
        await repo.save(plan)

        dispatched: list[str] = []
        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, alloc, node) -> str:  # type: ignore[no-untyped-def]
            dispatched.append(node.id)
            return f"attempt-{node.id}"

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid,
                node=node,
                attempt_id=node.current_attempt_id,
            )

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_VerificationJudgeObsoleteVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 1
        assert report.nodes_completed == 1
        assert dispatched == []
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        obsolete_node = reloaded.nodes[PlanNodeId("a")]
        assert obsolete_node.intent is TaskIntent.DONE
        assert obsolete_node.execution is TaskExecution.IDLE
        assert obsolete_node.current_attempt_id == "attempt-a"
        assert obsolete_node.metadata["obsolete_by_verifier_feedback"] is True
        assert (
            obsolete_node.metadata["obsolete_feedback_items"][0]["recommended_action"]
            == "obsolete_node"
        )
        assert [event[0] for event in events] == [
            "verification_completed",
            "verification_feedback_routed",
            "verification_feedback_disposition",
        ]

    async def test_verification_judge_repair_action_dispatches_repair_node(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        from dataclasses import replace

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-a",
            )
        )
        await repo.save(plan)

        dispatched: list[PlanNode] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return [
                WorkspaceAgent(
                    agent_id="ag-code",
                    display_name="C",
                    capabilities=frozenset({"codegen"}),
                )
            ]

        async def dispatcher(_wid: str, _alloc, node: PlanNode) -> str:
            dispatched.append(node)
            return "attempt-repair"

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid,
                node=node,
                attempt_id=node.current_attempt_id,
            )

        events: list[tuple[str, str, dict[str, Any]]] = []

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_VerificationJudgeRepairVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 1
        assert report.allocations_made == 1
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        original = reloaded.nodes[PlanNodeId("a")]
        repair_nodes = [
            node
            for node in reloaded.nodes.values()
            if node.metadata.get("repair_for_node_id") == "a"
        ]
        assert len(repair_nodes) == 1
        repair = repair_nodes[0]
        assert [node.id for node in dispatched] == [repair.id]
        assert original.intent is TaskIntent.TODO
        assert original.execution is TaskExecution.IDLE
        assert original.current_attempt_id is None
        assert repair.node_id in original.depends_on
        assert repair.intent is TaskIntent.IN_PROGRESS
        assert repair.execution is TaskExecution.DISPATCHED
        assert repair.current_attempt_id == "attempt-repair"
        assert repair.metadata.get("allow_verification_script_changes") is not True
        assert not any(event[0] == "verification_retry_scheduled" for event in events)

    async def test_pipeline_gate_does_not_hide_non_pipeline_verification_failures(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-a",
                metadata={"pipeline_required": True},
            )
        )
        await repo.save(plan)

        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, _alloc: Any, _node: PlanNode) -> str | None:
            raise AssertionError("no node should dispatch while dependency verification failed")

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid,
                node=node,
                attempt_id=node.current_attempt_id,
            )

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_MixedPipelineAndCustomFailureVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 1
        assert report.nodes_blocked == 1
        assert not any(event[0] == "pipeline_run_requested" for event in events)
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        blocked_node = reloaded.nodes[PlanNodeId("a")]
        assert blocked_node.intent is TaskIntent.BLOCKED
        assert blocked_node.execution is TaskExecution.IDLE
        assert blocked_node.metadata["last_verification_summary"].endswith(
            "judge verdict=needs_rework"
        )

    async def test_pipeline_gate_routes_judge_duplicate_pipeline_failure_to_pipeline(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-a",
                metadata={"pipeline_required": True},
            )
        )
        await repo.save(plan)

        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, _alloc: Any, _node: PlanNode) -> str | None:
            raise AssertionError("pipeline gate should run before worker retry")

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid,
                node=node,
                attempt_id=node.current_attempt_id,
                artifacts={"candidate_artifacts": ["commit_ref:abc1234"]},
            )

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_PipelineOnlyJudgeFailureVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 1
        assert report.nodes_blocked == 0
        assert any(event[0] == "pipeline_run_requested" for event in events)
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        node = reloaded.nodes[PlanNodeId("a")]
        assert node.intent is TaskIntent.IN_PROGRESS
        assert node.execution is TaskExecution.IDLE
        assert node.metadata["pipeline_gate_status"] == "requested"
        assert node.metadata["verified_commit_ref"] == "abc1234"
        assert "commit_ref:abc1234" in node.metadata["verification_evidence_refs"]

    async def test_stale_pipeline_feedback_with_worker_blocker_requests_pipeline(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-a",
                metadata={"pipeline_required": True},
            )
        )
        await repo.save(plan)

        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, _alloc: Any, _node: PlanNode) -> str | None:
            raise AssertionError("stale pipeline feedback should request pipeline before retry")

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid,
                node=node,
                attempt_id=node.current_attempt_id,
                artifacts={"candidate_artifacts": ["commit_ref:c817fbc8"]},
            )

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_StalePipelineWithBlockingWorkerFeedbackVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 1
        assert report.nodes_completed == 0
        assert any(event[0] == "pipeline_run_requested" for event in events)
        assert not any(event[0] == "verification_feedback_disposition" for event in events)
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        node = reloaded.nodes[PlanNodeId("a")]
        assert node.intent is TaskIntent.IN_PROGRESS
        assert node.execution is TaskExecution.IDLE
        assert node.metadata["pipeline_gate_status"] == "requested"
        assert node.metadata["verified_commit_ref"] == "c817fbc8"

    async def test_missing_pipeline_evidence_with_worker_feedback_requests_pipeline(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-a",
                metadata={
                    "pipeline_required": True,
                    "pipeline_failed_stage": "workspace-ci/deploy",
                    "pipeline_failure_summary": (
                        "Drone build #124 failed with Cannot find module '/app/dist/index.js'"
                    ),
                },
            )
        )
        await repo.save(plan)

        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, _alloc: Any, _node: PlanNode) -> str | None:
            raise AssertionError("current candidate needs a pipeline run before worker retry")

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid,
                node=node,
                attempt_id=node.current_attempt_id,
                artifacts={"candidate_artifacts": ["commit_ref:f649b2a"]},
            )

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_MissingPipelineEvidenceWithWorkerFeedbackVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 1
        assert report.nodes_completed == 0
        assert any(event[0] == "pipeline_run_requested" for event in events)
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        node = reloaded.nodes[PlanNodeId("a")]
        assert node.intent is TaskIntent.IN_PROGRESS
        assert node.execution is TaskExecution.IDLE
        assert node.metadata["pipeline_gate_status"] == "requested"
        assert node.metadata["verified_commit_ref"] == "f649b2a"

    async def test_pipeline_required_node_ignores_stale_success_when_current_pipeline_failed(
        self,
    ) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-a",
                metadata={
                    "pipeline_required": True,
                    "pipeline_status": "failed",
                    "pipeline_gate_status": "failed",
                    "pipeline_run_id": "old-run",
                    "pipeline_evidence_refs": [
                        "ci_pipeline:passed",
                        "pipeline_run:success:old-run",
                    ],
                    "execution_verifications": ["ci_pipeline:passed"],
                    "source_publish_commit_ref": "old1234",
                },
            )
        )
        await repo.save(plan)

        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, _alloc: Any, _node: PlanNode) -> str | None:
            raise AssertionError("current failed pipeline must request Drone before completion")

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid,
                node=node,
                attempt_id=node.current_attempt_id,
                artifacts={
                    "candidate_artifacts": ["commit_ref:new1234"],
                    "pipeline_status": "failed",
                    "pipeline_evidence_refs": [
                        "ci_pipeline:passed",
                        "pipeline_run:success:old-run",
                    ],
                    "execution_verifications": ["ci_pipeline:passed"],
                },
            )

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_AlwaysPassVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 1
        assert report.nodes_completed == 0
        assert any(event[0] == "pipeline_run_requested" for event in events)
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        node = reloaded.nodes[PlanNodeId("a")]
        assert node.intent is TaskIntent.IN_PROGRESS
        assert node.execution is TaskExecution.IDLE
        assert node.metadata["pipeline_gate_status"] == "requested"
        assert node.metadata["verified_commit_ref"] == "new1234"

    async def test_pipeline_gate_routes_judge_pipeline_text_without_feedback_items(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-a",
                metadata={"pipeline_required": True},
            )
        )
        await repo.save(plan)

        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, _alloc: Any, _node: PlanNode) -> str | None:
            raise AssertionError("pipeline gate should run before worker retry")

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid,
                node=node,
                attempt_id=node.current_attempt_id,
                artifacts={"candidate_artifacts": ["commit_ref:abc1234"]},
            )

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_PipelineOnlyJudgeFailureWithoutFeedbackVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 1
        assert any(event[0] == "pipeline_run_requested" for event in events)
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        node = reloaded.nodes[PlanNodeId("a")]
        assert node.execution is TaskExecution.IDLE
        assert node.metadata["pipeline_gate_status"] == "requested"

    async def test_pipeline_gate_does_not_rerun_when_judge_requires_worker_retry(
        self,
    ) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-a",
                metadata={"pipeline_required": True},
            )
        )
        await repo.save(plan)

        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, _alloc: Any, _node: PlanNode) -> str | None:
            raise AssertionError("worker-actionable CI feedback must not rerun Drone first")

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid,
                node=node,
                attempt_id=node.current_attempt_id,
                artifacts={"candidate_artifacts": ["commit_ref:abc1234"]},
            )

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_PipelineWorkerActionFailureVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 1
        assert not any(event[0] == "pipeline_run_requested" for event in events)
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        node = reloaded.nodes[PlanNodeId("a")]
        assert node.execution is TaskExecution.IDLE
        assert node.metadata.get("last_verification_judge_next_action_kind") is None
        assert node.metadata["verified_commit_ref"] == "abc1234"

    async def test_pipeline_gate_does_not_rerun_deploy_port_conflict_worker_feedback(
        self,
    ) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-a",
                metadata={"pipeline_required": True, "pipeline_gate_status": "failed"},
            )
        )
        await repo.save(plan)

        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, _alloc: Any, _node: PlanNode) -> str | None:
            raise AssertionError("worker-actionable deploy feedback must not rerun Drone first")

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid,
                node=node,
                attempt_id=node.current_attempt_id,
                artifacts={"candidate_artifacts": ["commit_ref:e4d6339"]},
            )

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_PipelineWorkerActionDeployPortConflictVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 1
        assert not any(event[0] == "pipeline_run_requested" for event in events)
        assert any(event[0] == "verification_feedback_routed" for event in events)
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        node = reloaded.nodes[PlanNodeId("a")]
        assert node.execution is TaskExecution.IDLE
        assert node.metadata["verified_commit_ref"] == "e4d6339"

    async def test_pipeline_gate_routes_retry_infra_drone_trigger_to_pipeline(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-a",
                metadata={"pipeline_required": True},
            )
        )
        await repo.save(plan)

        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, _alloc: Any, _node: PlanNode) -> str | None:
            raise AssertionError("pipeline gate should run before worker retry")

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid,
                node=node,
                attempt_id=node.current_attempt_id,
                artifacts={"candidate_artifacts": ["commit_ref:abc1234"]},
            )

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_PipelineRetryInfrastructureVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 1
        assert any(event[0] == "pipeline_run_requested" for event in events)
        assert not any(event[0] == "verification_retry_scheduled" for event in events)
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        node = reloaded.nodes[PlanNodeId("a")]
        assert node.intent is TaskIntent.IN_PROGRESS
        assert node.execution is TaskExecution.IDLE
        assert node.metadata["pipeline_gate_status"] == "requested"
        assert node.metadata["verified_commit_ref"] == "abc1234"

    async def test_pipeline_gate_routes_human_required_publish_gap_to_pipeline(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-a",
                metadata={"pipeline_required": True},
            )
        )
        await repo.save(plan)

        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, _alloc: Any, _node: PlanNode) -> str | None:
            raise AssertionError("platform publish gap should request pipeline, not a worker")

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid,
                node=node,
                attempt_id=node.current_attempt_id,
                artifacts={"candidate_artifacts": ["commit_ref:d9184e2"]},
            )

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_PipelineHumanPublishRequiredVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 1
        assert any(event[0] == "pipeline_run_requested" for event in events)
        assert not any(event[0] == "worker_launch" for event in events)
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        node = reloaded.nodes[PlanNodeId("a")]
        assert node.intent is TaskIntent.IN_PROGRESS
        assert node.execution is TaskExecution.IDLE
        assert node.metadata["pipeline_gate_status"] == "requested"
        assert node.metadata["verified_commit_ref"] == "d9184e2"

    async def test_pipeline_gate_pending_human_required_gap_does_not_block_node(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-a",
                metadata={
                    "pipeline_required": True,
                    "pipeline_gate_status": "requested",
                    "pipeline_status": "requested",
                },
            )
        )
        await repo.save(plan)

        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, _alloc: Any, _node: PlanNode) -> str | None:
            raise AssertionError("pending pipeline gate should not dispatch a worker")

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid,
                node=node,
                attempt_id=node.current_attempt_id,
                artifacts={"candidate_artifacts": ["commit_ref:d9184e2"]},
            )

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_PipelineHumanPublishRequiredVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 1
        assert report.nodes_blocked == 0
        assert not any(event[0] == "pipeline_run_requested" for event in events)
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        node = reloaded.nodes[PlanNodeId("a")]
        assert node.intent is TaskIntent.IN_PROGRESS
        assert node.execution is TaskExecution.REPORTED
        assert node.metadata["pipeline_gate_status"] == "requested"
        assert node.metadata["last_verification_hard_fail"] is False

    async def test_pipeline_gate_routes_judge_only_human_publish_gap_to_pipeline(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-a",
                metadata={
                    "expected_artifacts": [
                        "SANDBOX-PREVIEW-EVIDENCE.md updated",
                        "new pipeline evidence",
                    ],
                },
            )
        )
        await repo.save(plan)

        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, _alloc: Any, _node: PlanNode) -> str | None:
            raise AssertionError("judge-only publish gap should request pipeline, not a worker")

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid,
                node=node,
                attempt_id=node.current_attempt_id,
                artifacts={"candidate_artifacts": ["commit_ref:d9184e2"]},
            )

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_PipelineHumanPublishRequiredJudgeOnlyVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 1
        assert any(event[0] == "pipeline_run_requested" for event in events)
        assert not any(event[0] == "worker_launch" for event in events)
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        node = reloaded.nodes[PlanNodeId("a")]
        assert node.intent is TaskIntent.IN_PROGRESS
        assert node.execution is TaskExecution.IDLE
        assert node.metadata["pipeline_gate_status"] == "requested"
        assert node.metadata["pipeline_required"] is True
        assert node.metadata["verified_commit_ref"] == "d9184e2"

    async def test_pipeline_gate_routes_blocked_publish_report_timeout_to_pipeline(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-a",
            )
        )
        await repo.save(plan)

        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, _alloc: Any, _node: PlanNode) -> str | None:
            raise AssertionError("blocked publish report should request pipeline, not a worker")

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid,
                node=node,
                attempt_id=node.current_attempt_id,
                artifacts={"candidate_artifacts": ["commit_ref:2356af3"]},
            )

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_PipelineBlockedWorkerReportWithJudgeTimeoutVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 1
        assert any(event[0] == "pipeline_run_requested" for event in events)
        assert not any(event[0] == "verification_retry_scheduled" for event in events)
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        node = reloaded.nodes[PlanNodeId("a")]
        assert node.intent is TaskIntent.IN_PROGRESS
        assert node.execution is TaskExecution.IDLE
        assert node.metadata["pipeline_gate_status"] == "requested"
        assert node.metadata["verified_commit_ref"] == "2356af3"

    async def test_pipeline_gate_routes_embedded_ci_pipeline_marker_to_pipeline(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()

        a = plan.nodes[PlanNodeId("a")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-a",
                metadata={"pipeline_required": True},
            )
        )
        await repo.save(plan)

        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, _alloc: Any, _node: PlanNode) -> str | None:
            raise AssertionError("pipeline gate should run before worker retry")

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(
                workspace_id=wid,
                node=node,
                attempt_id=node.current_attempt_id,
                artifacts={"candidate_artifacts": ["commit_ref:def5678"]},
            )

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_PipelineEmbeddedMarkerJudgeFailureVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
        )

        report = await sup.tick("ws-1")

        assert report.verifications_ran == 1
        assert any(event[0] == "pipeline_run_requested" for event in events)
        assert not any(event[0] == "verification_retry_scheduled" for event in events)
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        node = reloaded.nodes[PlanNodeId("a")]
        assert node.metadata["pipeline_gate_status"] == "requested"
        assert node.metadata["verified_commit_ref"] == "def5678"

    async def test_sql_event_sink_schedules_delayed_retry_tick(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        appended_events: list[dict[str, Any]] = []
        enqueued_outbox: list[dict[str, Any]] = []

        class _FakeEventRepo:
            def __init__(self, db: object) -> None:
                self.db = db

            async def append(self, **kwargs: Any) -> object:
                appended_events.append(kwargs)
                return object()

        class _FakeOutboxRepo:
            def __init__(self, db: object) -> None:
                self.db = db

            async def enqueue(self, **kwargs: Any) -> object:
                enqueued_outbox.append(kwargs)
                return object()

        monkeypatch.setattr(
            workspace_plan_factory,
            "SqlWorkspacePlanEventRepository",
            _FakeEventRepo,
        )
        monkeypatch.setattr(
            workspace_plan_factory,
            "SqlWorkspacePlanOutboxRepository",
            _FakeOutboxRepo,
        )

        sink = workspace_plan_factory._make_sql_plan_event_sink(object())
        node = PlanNode(
            id="a",
            plan_id="plan-1",
            parent_id=PlanNodeId("goal-1"),
            kind=PlanNodeKind.TASK,
            title="task a",
        )

        await sink(
            "ws-1",
            node,
            "verification_retry_scheduled",
            {
                "attempt_id": "attempt-1",
                "retry_not_before": "2026-04-29T06:46:46Z",
            },
        )

        assert appended_events
        assert len(enqueued_outbox) == 1
        retry_job = enqueued_outbox[0]
        assert retry_job["event_type"] == "supervisor_tick"
        assert retry_job["plan_id"] == "plan-1"
        assert retry_job["payload"]["retry_node_id"] == "a"
        assert retry_job["next_attempt_at"].isoformat() == "2026-04-29T06:46:46+00:00"

    async def test_sql_event_sink_schedules_next_sprint_dispatch_tick(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        appended_events: list[dict[str, Any]] = []
        enqueued_outbox: list[dict[str, Any]] = []

        class _FakeEventRepo:
            def __init__(self, db: object) -> None:
                self.db = db

            async def append(self, **kwargs: Any) -> object:
                appended_events.append(kwargs)
                return object()

        class _FakeOutboxRepo:
            def __init__(self, db: object) -> None:
                self.db = db

            async def enqueue(self, **kwargs: Any) -> object:
                enqueued_outbox.append(kwargs)
                return object()

        monkeypatch.setattr(
            workspace_plan_factory,
            "SqlWorkspacePlanEventRepository",
            _FakeEventRepo,
        )
        monkeypatch.setattr(
            workspace_plan_factory,
            "SqlWorkspacePlanOutboxRepository",
            _FakeOutboxRepo,
        )

        sink = workspace_plan_factory._make_sql_plan_event_sink(object())
        goal_node = PlanNode(
            id="goal-1",
            plan_id="plan-1",
            parent_id=None,
            kind=PlanNodeKind.GOAL,
            title="root",
        )

        await sink(
            "ws-1",
            goal_node,
            "iteration_next_sprint_planned",
            {
                "iteration_index": 1,
                "next_iteration": 2,
                "task_count": 6,
            },
        )

        assert appended_events
        assert len(enqueued_outbox) == 1
        tick_job = enqueued_outbox[0]
        assert tick_job["event_type"] == "supervisor_tick"
        assert tick_job["plan_id"] == "plan-1"
        assert tick_job["payload"]["iteration_followup"] == "next_sprint_dispatch"
        assert tick_job["payload"]["reviewed_iteration"] == 1
        assert tick_job["payload"]["next_iteration"] == 2

    async def test_sql_event_sink_schedules_followup_for_dispatch_limit(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        appended_events: list[dict[str, Any]] = []
        enqueued_outbox: list[dict[str, Any]] = []

        class _FakeEventRepo:
            def __init__(self, db: object) -> None:
                self.db = db

            async def append(self, **kwargs: Any) -> object:
                appended_events.append(kwargs)
                return object()

        class _FakeOutboxRepo:
            def __init__(self, db: object) -> None:
                self.db = db

            async def enqueue(self, **kwargs: Any) -> object:
                enqueued_outbox.append(kwargs)
                return object()

        monkeypatch.setattr(
            workspace_plan_factory,
            "SqlWorkspacePlanEventRepository",
            _FakeEventRepo,
        )
        monkeypatch.setattr(
            workspace_plan_factory,
            "SqlWorkspacePlanOutboxRepository",
            _FakeOutboxRepo,
        )

        sink = workspace_plan_factory._make_sql_plan_event_sink(object())
        node = PlanNode(
            id="task-3",
            plan_id="plan-1",
            parent_id=PlanNodeId("goal-1"),
            kind=PlanNodeKind.TASK,
            title="third ready task",
        )

        await sink(
            "ws-1",
            node,
            "dispatch_deferred_concurrency_limit",
            {
                "summary": "node deferred because the per-tick dispatch limit was reached",
                "max_dispatches_per_tick": 2,
            },
        )

        assert appended_events
        assert len(enqueued_outbox) == 1
        tick_job = enqueued_outbox[0]
        assert tick_job["event_type"] == "supervisor_tick"
        assert tick_job["plan_id"] == "plan-1"
        assert tick_job["payload"]["deferred_node_id"] == "task-3"
        assert tick_job["payload"]["deferred_reason"] == "dispatch_concurrency_limit"
        assert tick_job["metadata"]["max_dispatches_per_tick"] == 2

    async def test_sql_event_sink_projects_supervisor_decision_completed(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        appended_events: list[dict[str, Any]] = []
        projected: list[tuple[str, dict[str, Any]]] = []

        class _FakeEventRepo:
            def __init__(self, db: object) -> None:
                self.db = db

            async def append(self, **kwargs: Any) -> object:
                appended_events.append(kwargs)
                return object()

        async def _fake_projection(
            db: object,
            node: PlanNode,
            payload: dict[str, Any],
        ) -> bool:
            projected.append((node.id, payload))
            return True

        monkeypatch.setattr(
            workspace_plan_factory,
            "SqlWorkspacePlanEventRepository",
            _FakeEventRepo,
        )
        monkeypatch.setattr(
            workspace_plan_factory,
            "_project_supervisor_decision_to_workspace_task",
            _fake_projection,
        )

        sink = workspace_plan_factory._make_sql_plan_event_sink(object())
        node = PlanNode(
            id="node-a",
            plan_id="plan-1",
            parent_id=PlanNodeId("goal-1"),
            kind=PlanNodeKind.TASK,
            title="task a",
        )

        await sink(
            "ws-1",
            node,
            "supervisor_decision_completed",
            {
                "action": "accept_node",
                "rationale": "agent supervisor accepted current attempt",
            },
        )

        assert appended_events
        assert len(projected) == 1
        projected_node_id, projected_payload = projected[0]
        assert projected_node_id == "node-a"
        assert projected_payload["action"] == "accept_node"

    async def test_completed_iteration_accepts_complete_goal_verdict(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("WORKSPACE_V2_ITERATION_LOOP_ENABLED", "true")
        repo = InMemoryPlanRepository()
        plan = _mark_plan_tasks_done(_plan_with_two_tasks())
        await repo.save(plan)
        events: list[tuple[str, str, dict[str, Any]]] = []
        reviewer = _StaticIterationReviewer(
            IterationReviewVerdict(
                verdict="complete_goal",
                confidence=0.92,
                summary="Goal satisfies the requested scope.",
            )
        )

        report = await _supervisor_for_iteration_review(repo, reviewer, events).tick("ws-1")

        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        assert report.allocations_made == 0
        assert reloaded.status is PlanStatus.COMPLETED
        assert not any(
            dict(node.metadata or {}).get("iteration_index") == 2
            for node in reloaded.nodes.values()
        )
        assert reviewer.contexts[0].iteration_index == 1
        assert reviewer.contexts[0].max_next_tasks == 6
        assert [event[0] for event in events] == [
            "iteration_review_completed",
            "iteration_loop_completed",
        ]
        assert reloaded.goal_node.metadata["iteration_loop"]["loop_status"] == "completed"

    async def test_completed_iteration_suspends_when_iteration_reviewer_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("WORKSPACE_V2_ITERATION_LOOP_ENABLED", "true")
        repo = InMemoryPlanRepository()
        plan = _mark_plan_tasks_done(_plan_with_two_tasks())
        goal = plan.goal_node
        plan.replace_node(
            replace(
                goal,
                metadata={
                    **dict(goal.metadata or {}),
                    "iteration_loop": {
                        "mode": "auto",
                        "loop_status": "active",
                        "current_iteration": 1,
                    },
                },
            )
        )
        await repo.save(plan)
        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return []

        async def dispatcher(_wid: str, _alloc: Any, _node: PlanNode) -> str | None:
            return None

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(workspace_id=wid, node=node)

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        supervisor = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_AlwaysPassVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            iteration_reviewer=None,
            heartbeat_seconds=0.05,
        )

        await supervisor.tick("ws-1")

        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        assert reloaded.status is PlanStatus.SUSPENDED
        loop = reloaded.goal_node.metadata["iteration_loop"]
        assert loop["loop_status"] == "suspended"
        assert loop["stop_reason"] == "iteration review agent is unavailable"
        assert events == [
            (
                "iteration_loop_suspended",
                "goal-1",
                {
                    "iteration_index": 1,
                    "reason": "iteration review agent is unavailable",
                },
            )
        ]

    async def test_iteration_review_context_uses_latest_passed_verification_summary(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("WORKSPACE_V2_ITERATION_LOOP_ENABLED", "true")
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        a = plan.nodes[PlanNodeId("a")]
        b = plan.nodes[PlanNodeId("b")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.DONE,
                execution=TaskExecution.IDLE,
                metadata={"iteration_index": 1, "iteration_phase": "implement"},
            )
        )
        plan.replace_node(
            replace(
                b,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-current",
                metadata={
                    "iteration_index": 1,
                    "iteration_phase": "review",
                    "last_verification_summary": "verification failed: stale attempt",
                },
            )
        )
        await repo.save(plan)
        events: list[tuple[str, str, dict[str, Any]]] = []
        reviewer = _StaticIterationReviewer(
            IterationReviewVerdict(
                verdict="complete_goal",
                confidence=0.9,
                summary="Latest accepted attempt satisfies the goal.",
            )
        )

        await _supervisor_for_iteration_review(repo, reviewer, events).tick("ws-1")

        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        accepted = reloaded.nodes[PlanNodeId("b")]
        assert accepted.metadata["last_verification_summary"] == "verified (0 criteria passed)"
        assert accepted.metadata["last_verification_attempt_id"] == "attempt-current"
        completed = {str(item["id"]): item for item in reviewer.contexts[0].completed_tasks}
        assert completed["b"]["verification_summary"] == "verified (0 criteria passed)"
        assert "stale attempt" not in completed["b"]["verification_summary"]

    async def test_iteration_review_context_includes_verified_attempt_artifacts(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("WORKSPACE_V2_ITERATION_LOOP_ENABLED", "true")
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        a = plan.nodes[PlanNodeId("a")]
        b = plan.nodes[PlanNodeId("b")]
        plan.replace_node(
            replace(
                a,
                intent=TaskIntent.DONE,
                execution=TaskExecution.IDLE,
                metadata={
                    "iteration_index": 1,
                    "iteration_phase": "research",
                    "candidate_artifacts": ["docs/research.md"],
                },
            )
        )
        plan.replace_node(
            replace(
                b,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-current",
                metadata={"iteration_index": 1, "iteration_phase": "review"},
            )
        )
        await repo.save(plan)
        events: list[tuple[str, str, dict[str, Any]]] = []
        reviewer = _StaticIterationReviewer(
            IterationReviewVerdict(
                verdict="complete_goal",
                confidence=0.9,
                summary="Verified artifacts satisfy the goal.",
            )
        )

        await _supervisor_for_iteration_review(
            repo,
            reviewer,
            events,
            artifacts_by_node={
                "b": {
                    "candidate_artifacts": ["src/runtime/supervisor.py"],
                    "candidate_verifications": ["test_run:pytest workspace_plan"],
                }
            },
        ).tick("ws-1")

        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        verified_node = reloaded.nodes[PlanNodeId("b")]
        assert verified_node.metadata["candidate_artifacts"] == ["src/runtime/supervisor.py"]
        assert verified_node.metadata["candidate_verifications"] == [
            "test_run:pytest workspace_plan"
        ]
        assert "docs/research.md" in reviewer.contexts[0].deliverables
        assert "src/runtime/supervisor.py" in reviewer.contexts[0].deliverables
        completed = {str(item["id"]): item for item in reviewer.contexts[0].completed_tasks}
        assert completed["b"]["artifacts"] == ["src/runtime/supervisor.py"]

    async def test_iteration_review_context_suppresses_superseded_terminal_failure_summary(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("WORKSPACE_V2_ITERATION_LOOP_ENABLED", "true")
        repo = InMemoryPlanRepository()
        plan = _mark_plan_tasks_done(_plan_with_two_tasks())
        b = plan.nodes[PlanNodeId("b")]
        plan.replace_node(
            replace(
                b,
                metadata={
                    **dict(b.metadata or {}),
                    "terminal_attempt_status": "accepted",
                    "last_verification_summary": "verification failed: superseded attempt",
                },
            )
        )
        await repo.save(plan)
        events: list[tuple[str, str, dict[str, Any]]] = []
        reviewer = _StaticIterationReviewer(
            IterationReviewVerdict(
                verdict="complete_goal",
                confidence=0.9,
                summary="Terminal accepted attempt satisfies the goal.",
            )
        )

        await _supervisor_for_iteration_review(repo, reviewer, events).tick("ws-1")

        completed = {str(item["id"]): item for item in reviewer.contexts[0].completed_tasks}
        assert completed["b"]["verification_summary"] == "accepted terminal attempt"
        assert reviewer.contexts[0].feedback_items == ()

    async def test_completed_iteration_plans_bounded_next_sprint(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("WORKSPACE_V2_ITERATION_LOOP_ENABLED", "true")
        repo = InMemoryPlanRepository()
        plan = _mark_plan_tasks_done(_plan_with_two_tasks())
        await repo.save(plan)
        events: list[tuple[str, str, dict[str, Any]]] = []
        next_tasks = tuple(
            IterationNextTask(
                id=f"t{index}",
                description=f"Iteration 2 task {index}",
                dependencies=(f"t{index - 1}",) if index > 1 else (),
                phase="implement",
            )
            for index in range(1, 8)
        )
        reviewer = _StaticIterationReviewer(
            IterationReviewVerdict(
                verdict="continue_next_iteration",
                confidence=0.9,
                summary="One more sprint is needed.",
                next_sprint_goal="Close the remaining verification and polish gaps.",
                feedback_items=("Need browser verification.",),
                next_tasks=next_tasks,
            )
        )

        await _supervisor_for_iteration_review(repo, reviewer, events).tick("ws-1")

        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        assert reloaded.status is PlanStatus.ACTIVE
        iteration_two_nodes = [
            node
            for node in reloaded.nodes.values()
            if dict(node.metadata or {}).get("iteration_index") == 2
        ]
        assert len(iteration_two_nodes) == 6
        assert all(node.intent is TaskIntent.TODO for node in iteration_two_nodes)
        assert len(iteration_two_nodes[1].depends_on) == 1
        loop = reloaded.goal_node.metadata["iteration_loop"]
        assert loop["current_iteration"] == 2
        assert loop["loop_status"] == "active"
        assert loop["completed_iterations"] == [1]
        assert loop["current_sprint_goal"] == "Close the remaining verification and polish gaps."
        assert events[-1][0] == "iteration_next_sprint_planned"
        assert events[-1][2]["task_count"] == 6

        await _supervisor_for_iteration_review(repo, reviewer, events).tick("ws-1")
        rerun = await repo.get_by_workspace("ws-1")
        assert rerun is not None
        assert (
            len(
                [
                    node
                    for node in rerun.nodes.values()
                    if dict(node.metadata or {}).get("iteration_index") == 2
                ]
            )
            == 6
        )
        assert len(reviewer.contexts) == 1

    async def test_completed_iteration_adds_phase_barrier_dependencies(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("WORKSPACE_V2_ITERATION_LOOP_ENABLED", "true")
        repo = InMemoryPlanRepository()
        plan = _mark_plan_tasks_done(_plan_with_two_tasks())
        await repo.save(plan)
        events: list[tuple[str, str, dict[str, Any]]] = []
        reviewer = _StaticIterationReviewer(
            IterationReviewVerdict(
                verdict="continue_next_iteration",
                confidence=0.9,
                summary="Continue with ordered implementation, testing, and release work.",
                next_sprint_goal="Ship an ordered follow-up sprint.",
                next_tasks=(
                    IterationNextTask(
                        id="backend",
                        description="Implement backend follow-up.",
                        phase="implement",
                    ),
                    IterationNextTask(
                        id="frontend",
                        description="Implement frontend follow-up.",
                        phase="implement",
                    ),
                    IterationNextTask(
                        id="test",
                        description="Run end-to-end verification.",
                        phase="test",
                    ),
                    IterationNextTask(
                        id="deploy",
                        description="Deploy the verified build.",
                        phase="deploy",
                    ),
                    IterationNextTask(
                        id="review",
                        description="Review sprint outcomes.",
                        phase="review",
                    ),
                ),
            )
        )

        await _supervisor_for_iteration_review(repo, reviewer, events).tick("ws-1")

        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        nodes_by_title = {
            node.title: node
            for node in reloaded.nodes.values()
            if dict(node.metadata or {}).get("iteration_index") == 2
        }
        backend = nodes_by_title["Implement backend follow-up."]
        frontend = nodes_by_title["Implement frontend follow-up."]
        test = nodes_by_title["Run end-to-end verification."]
        deploy = nodes_by_title["Deploy the verified build."]
        review = nodes_by_title["Review sprint outcomes."]

        assert backend.depends_on == frozenset()
        assert frontend.depends_on == frozenset()
        assert test.depends_on == frozenset({PlanNodeId(backend.id), PlanNodeId(frontend.id)})
        assert PlanNodeId(test.id) in deploy.depends_on
        assert PlanNodeId(backend.id) in deploy.depends_on
        assert PlanNodeId(frontend.id) in deploy.depends_on
        assert PlanNodeId(deploy.id) in review.depends_on
        assert PlanNodeId(test.id) in review.depends_on

    async def test_completed_iteration_preserves_out_of_order_agent_phases(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("WORKSPACE_V2_ITERATION_LOOP_ENABLED", "true")
        repo = InMemoryPlanRepository()
        plan = _mark_plan_tasks_done(_plan_with_two_tasks())
        await repo.save(plan)
        events: list[tuple[str, str, dict[str, Any]]] = []
        reviewer = _StaticIterationReviewer(
            IterationReviewVerdict(
                verdict="continue_next_iteration",
                confidence=0.9,
                summary="Continue with a review task listed before implementation.",
                next_sprint_goal="Verify parity and implement gaps.",
                next_tasks=(
                    IterationNextTask(
                        id="review",
                        description="Review browser parity evidence.",
                        dependencies=("implement",),
                        phase="review",
                    ),
                    IterationNextTask(
                        id="implement",
                        description="Implement parity gaps found during review.",
                        phase="implement",
                    ),
                ),
            )
        )

        await _supervisor_for_iteration_review(repo, reviewer, events).tick("ws-1")

        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        nodes_by_title = {
            node.title: node
            for node in reloaded.nodes.values()
            if dict(node.metadata or {}).get("iteration_index") == 2
        }
        review = nodes_by_title["Review browser parity evidence."]
        implement = nodes_by_title["Implement parity gaps found during review."]
        assert review.metadata["iteration_phase"] == "review"
        assert implement.metadata["iteration_phase"] == "implement"
        assert review.depends_on == frozenset({PlanNodeId(implement.id)})
        assert implement.depends_on == frozenset()
        assert reloaded.validate() == []
        assert {node.id for node in reloaded.ready_nodes()} == {implement.id}

    async def test_completed_iteration_rejects_forward_dependency_deadlocks(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("WORKSPACE_V2_ITERATION_LOOP_ENABLED", "true")
        repo = InMemoryPlanRepository()
        plan = _mark_plan_tasks_done(_plan_with_two_tasks())
        await repo.save(plan)
        events: list[tuple[str, str, dict[str, Any]]] = []
        reviewer = _StaticIterationReviewer(
            IterationReviewVerdict(
                verdict="continue_next_iteration",
                confidence=0.9,
                summary="Continue with a bounded release-readiness sprint.",
                next_sprint_goal="Ship an ordered release-readiness sprint.",
                next_tasks=(
                    IterationNextTask(
                        id="triage",
                        description="Read status summary and create the sprint plan.",
                        dependencies=("test", "deploy"),
                        phase="review",
                    ),
                    IterationNextTask(
                        id="test",
                        description="Run focused regression tests.",
                        dependencies=("triage",),
                        phase="test",
                    ),
                    IterationNextTask(
                        id="fix",
                        description="Apply high-impact UI fixes.",
                        dependencies=("triage",),
                        phase="implement",
                    ),
                    IterationNextTask(
                        id="deploy",
                        description="Verify deployment readiness.",
                        dependencies=("test", "fix"),
                        phase="deploy",
                    ),
                ),
            )
        )

        await _supervisor_for_iteration_review(repo, reviewer, events).tick("ws-1")

        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        iteration_nodes = [
            node
            for node in reloaded.nodes.values()
            if dict(node.metadata or {}).get("iteration_index") == 2
        ]
        nodes_by_title = {node.title: node for node in iteration_nodes}
        triage = nodes_by_title["Read status summary and create the sprint plan."]
        test = nodes_by_title["Run focused regression tests."]
        fix = nodes_by_title["Apply high-impact UI fixes."]
        deploy = nodes_by_title["Verify deployment readiness."]
        assert reloaded.validate() == []
        assert {node.id for node in reloaded.ready_nodes()} == {fix.id}
        assert [node.metadata["iteration_phase"] for node in iteration_nodes] == [
            "review",
            "test",
            "implement",
            "deploy",
        ]
        assert triage.depends_on == frozenset(
            {PlanNodeId(test.id), PlanNodeId(fix.id), PlanNodeId(deploy.id)}
        )
        assert test.depends_on == frozenset({PlanNodeId(fix.id)})
        assert fix.depends_on == frozenset()
        assert deploy.depends_on == frozenset({PlanNodeId(test.id), PlanNodeId(fix.id)})

    async def test_tick_repairs_existing_next_iteration_phase_barriers_before_dispatch(
        self,
    ) -> None:
        repo = InMemoryPlanRepository()
        plan_id = "plan-repair"
        goal_id = PlanNodeId("goal-1")
        plan = Plan(
            id=plan_id,
            workspace_id="ws-1",
            goal_id=goal_id,
            status=PlanStatus.ACTIVE,
        )
        plan.add_node(
            PlanNode(
                id=goal_id.value,
                plan_id=plan_id,
                parent_id=None,
                kind=PlanNodeKind.GOAL,
                title="root",
            )
        )
        for node_id, title, phase in (
            ("impl-a", "Implement backend polish", "implement"),
            ("impl-b", "Implement frontend polish", "implement"),
            ("test", "Run acceptance verification", "test"),
            ("deploy", "Prepare release candidate", "deploy"),
            ("review", "Review sprint outcome", "review"),
        ):
            plan.add_node(
                PlanNode(
                    id=node_id,
                    plan_id=plan_id,
                    parent_id=goal_id,
                    kind=PlanNodeKind.TASK,
                    title=title,
                    depends_on=frozenset(),
                    recommended_capabilities=(Capability(name="codegen"),),
                    metadata={"iteration_index": 2, "iteration_phase": phase},
                )
            )
        await repo.save(plan)

        dispatched: list[str] = []
        events: list[tuple[str, str, dict[str, Any]]] = []

        async def agent_pool(_wid: str) -> list[WorkspaceAgent]:
            return [
                WorkspaceAgent(
                    agent_id="ag-code",
                    display_name="C",
                    capabilities=frozenset({"codegen"}),
                )
            ]

        async def dispatcher(_wid: str, _alloc: Any, node: PlanNode) -> str:
            dispatched.append(node.id)
            return f"attempt-{node.id}"

        async def attempt_ctx(wid: str, node: PlanNode) -> VerificationContext:
            return VerificationContext(workspace_id=wid, node=node)

        async def event_sink(
            _wid: str,
            node: PlanNode,
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            events.append((event_type, node.id, payload))

        sup = WorkspaceSupervisor(
            plan_repo=repo,
            allocator=CapabilityAllocator(),
            verifier=_AlwaysPassVerifier(),
            projector=ProgressProjector(),
            planner=LLMGoalPlanner(decomposer=None),
            agent_pool=agent_pool,
            dispatcher=dispatcher,
            attempt_context=attempt_ctx,
            event_sink=event_sink,
            heartbeat_seconds=0.05,
            max_dispatches_per_tick=6,
        )

        report = await sup.tick("ws-1")

        assert report.allocations_made == 2
        assert set(dispatched) == {"impl-a", "impl-b"}
        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        test = reloaded.nodes[PlanNodeId("test")]
        deploy = reloaded.nodes[PlanNodeId("deploy")]
        review = reloaded.nodes[PlanNodeId("review")]
        assert test.depends_on == frozenset({PlanNodeId("impl-a"), PlanNodeId("impl-b")})
        assert PlanNodeId("test") in deploy.depends_on
        assert PlanNodeId("impl-a") in deploy.depends_on
        assert PlanNodeId("impl-b") in deploy.depends_on
        assert PlanNodeId("deploy") in review.depends_on
        assert PlanNodeId("test") in review.depends_on
        repair_events = [
            event for event in events if event[0] == "iteration_phase_barriers_repaired"
        ]
        assert repair_events == [
            (
                "iteration_phase_barriers_repaired",
                "goal-1",
                {
                    "summary": "pending sprint nodes were missing phase barrier dependencies",
                    "node_count": 3,
                },
            )
        ]

    async def test_review_phase_next_sprint_artifacts_do_not_force_change_evidence(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("WORKSPACE_V2_ITERATION_LOOP_ENABLED", "true")
        repo = InMemoryPlanRepository()
        plan = _mark_plan_tasks_done(_plan_with_two_tasks())
        await repo.save(plan)
        events: list[tuple[str, str, dict[str, Any]]] = []
        reviewer = _StaticIterationReviewer(
            IterationReviewVerdict(
                verdict="continue_next_iteration",
                confidence=0.9,
                summary="Need one evidence collection follow-up.",
                next_sprint_goal="Collect acceptance evidence.",
                next_tasks=(
                    IterationNextTask(
                        id="evidence",
                        description="Collect final screenshots and summarize acceptance evidence.",
                        phase="review",
                        expected_artifacts=("docs/E2E-ACCEPTANCE-REPORT.md",),
                    ),
                ),
            )
        )

        await _supervisor_for_iteration_review(repo, reviewer, events).tick("ws-1")

        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        evidence_node = next(
            node
            for node in reloaded.nodes.values()
            if dict(node.metadata or {}).get("iteration_index") == 2
        )
        assert evidence_node.feature_checkpoint is not None
        assert evidence_node.feature_checkpoint.expected_artifacts == ()
        assert evidence_node.metadata["expected_artifacts"] == ["docs/E2E-ACCEPTANCE-REPORT.md"]

    async def test_completed_iteration_suspends_at_max_iterations(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("WORKSPACE_V2_ITERATION_LOOP_ENABLED", "true")
        monkeypatch.setenv("WORKSPACE_V2_MAX_ITERATIONS", "1")
        repo = InMemoryPlanRepository()
        plan = _mark_plan_tasks_done(_plan_with_two_tasks())
        await repo.save(plan)
        events: list[tuple[str, str, dict[str, Any]]] = []
        reviewer = _StaticIterationReviewer(
            IterationReviewVerdict(
                verdict="continue_next_iteration",
                confidence=0.9,
                summary="Needs more work.",
                next_tasks=(IterationNextTask(id="t1", description="Follow up"),),
            )
        )

        await _supervisor_for_iteration_review(repo, reviewer, events).tick("ws-1")

        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        assert reloaded.status is PlanStatus.SUSPENDED
        assert reloaded.goal_node.metadata["iteration_loop"]["stop_reason"] == (
            "max iterations reached: 1"
        )
        assert reviewer.contexts == []
        assert events[-1][0] == "iteration_loop_suspended"

    async def test_completed_iteration_respects_operator_extended_max_iterations(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("WORKSPACE_V2_ITERATION_LOOP_ENABLED", "true")
        monkeypatch.setenv("WORKSPACE_V2_MAX_ITERATIONS", "1")
        repo = InMemoryPlanRepository()
        plan = _mark_plan_tasks_done(_plan_with_two_tasks())
        goal = plan.goal_node
        metadata = dict(goal.metadata or {})
        metadata["iteration_loop"] = {
            "mode": "auto",
            "loop_status": "active",
            "current_iteration": 1,
            "max_iterations": 2,
        }
        plan.replace_node(replace(goal, metadata=metadata))
        await repo.save(plan)
        events: list[tuple[str, str, dict[str, Any]]] = []
        reviewer = _StaticIterationReviewer(
            IterationReviewVerdict(
                verdict="continue_next_iteration",
                confidence=0.9,
                summary="Operator allowed another sprint.",
                next_tasks=(IterationNextTask(id="t1", description="Follow up"),),
            )
        )

        await _supervisor_for_iteration_review(repo, reviewer, events).tick("ws-1")

        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        assert reloaded.status is PlanStatus.ACTIVE
        loop = reloaded.goal_node.metadata["iteration_loop"]
        assert loop["current_iteration"] == 2
        assert loop["max_iterations"] == 2
        assert reviewer.contexts[0].iteration_index == 1
        assert events[-1][0] == "iteration_next_sprint_planned"

    async def test_completed_iteration_suspends_low_confidence_review(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("WORKSPACE_V2_ITERATION_LOOP_ENABLED", "true")
        repo = InMemoryPlanRepository()
        plan = _mark_plan_tasks_done(_plan_with_two_tasks())
        await repo.save(plan)
        events: list[tuple[str, str, dict[str, Any]]] = []
        reviewer = _StaticIterationReviewer(
            IterationReviewVerdict(
                verdict="continue_next_iteration",
                confidence=0.41,
                summary="Evidence is not strong enough to continue automatically.",
                next_tasks=(IterationNextTask(id="t1", description="Follow up"),),
            )
        )

        await _supervisor_for_iteration_review(repo, reviewer, events).tick("ws-1")

        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        assert reloaded.status is PlanStatus.SUSPENDED
        loop = reloaded.goal_node.metadata["iteration_loop"]
        assert loop["loop_status"] == "suspended"
        assert loop["stop_reason"] == "Evidence is not strong enough to continue automatically."
        assert not any(
            dict(node.metadata or {}).get("iteration_index") == 2
            for node in reloaded.nodes.values()
        )
        assert [event[0] for event in events] == [
            "iteration_review_completed",
            "iteration_loop_suspended",
        ]


# ---------------------------------------------------------------------------
# Orchestrator behavior
# ---------------------------------------------------------------------------


class TestOrchestrator:
    async def test_creates_plan_and_starts_supervisor(self) -> None:
        repo = InMemoryPlanRepository()
        sup = _NoopSupervisor()
        orch = WorkspaceOrchestrator(
            planner=LLMGoalPlanner(decomposer=None),
            allocator=CapabilityAllocator(),
            verifier=_AlwaysPassVerifier(),
            projector=ProgressProjector(),
            supervisor=sup,
            plan_repo=repo,
            config=OrchestratorConfig(),
        )
        plan = await orch.start_goal(workspace_id="ws", title="goal")
        assert plan.workspace_id == "ws"
        assert sup.started == ["ws"]

    async def test_start_goal_can_skip_long_lived_supervisor_for_job_scoped_wiring(self) -> None:
        repo = InMemoryPlanRepository()
        sup = _NoopSupervisor()
        orch = WorkspaceOrchestrator(
            planner=LLMGoalPlanner(decomposer=None),
            allocator=CapabilityAllocator(),
            verifier=_AlwaysPassVerifier(),
            projector=ProgressProjector(),
            supervisor=sup,
            plan_repo=repo,
            config=OrchestratorConfig(),
        )

        plan = await orch.start_goal(
            workspace_id="ws",
            title="goal",
            start_supervisor=False,
        )
        report = await orch.tick_once("ws")

        assert plan.workspace_id == "ws"
        assert sup.started == []
        assert report.workspace_id == "ws"

    async def test_mark_worker_reported_ignores_stale_attempt_id(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        node = plan.nodes[PlanNodeId("a")]
        from dataclasses import replace

        plan.replace_node(
            replace(
                node,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.RUNNING,
                current_attempt_id="attempt-current",
            )
        )
        await repo.save(plan)
        orch = WorkspaceOrchestrator(
            planner=LLMGoalPlanner(decomposer=None),
            allocator=CapabilityAllocator(),
            verifier=_AlwaysPassVerifier(),
            projector=ProgressProjector(),
            supervisor=_NoopSupervisor(),
            plan_repo=repo,
            config=OrchestratorConfig(),
        )

        await orch.mark_worker_reported(
            workspace_id="ws-1",
            node_id="a",
            attempt_id="attempt-stale",
        )

        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        unchanged = reloaded.nodes[PlanNodeId("a")]
        assert unchanged.execution is TaskExecution.RUNNING
        assert unchanged.current_attempt_id == "attempt-current"

    async def test_mark_worker_reported_accepts_current_attempt_id(self) -> None:
        repo = InMemoryPlanRepository()
        plan = _plan_with_two_tasks()
        node = plan.nodes[PlanNodeId("a")]
        from dataclasses import replace

        plan.replace_node(
            replace(
                node,
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.RUNNING,
                current_attempt_id="attempt-current",
            )
        )
        await repo.save(plan)
        orch = WorkspaceOrchestrator(
            planner=LLMGoalPlanner(decomposer=None),
            allocator=CapabilityAllocator(),
            verifier=_AlwaysPassVerifier(),
            projector=ProgressProjector(),
            supervisor=_NoopSupervisor(),
            plan_repo=repo,
            config=OrchestratorConfig(),
        )

        await orch.mark_worker_reported(
            workspace_id="ws-1",
            node_id="a",
            attempt_id="attempt-current",
        )

        reloaded = await repo.get_by_workspace("ws-1")
        assert reloaded is not None
        reported = reloaded.nodes[PlanNodeId("a")]
        assert reported.execution is TaskExecution.REPORTED
        assert reported.current_attempt_id == "attempt-current"


class _NoopSupervisor:
    def __init__(self) -> None:
        self.started: list[str] = []
        self.stopped: list[str] = []

    async def start(self, workspace_id: str) -> None:
        self.started.append(workspace_id)

    async def stop(self, workspace_id: str) -> None:
        self.stopped.append(workspace_id)

    async def tick(self, workspace_id: str):  # type: ignore[no-untyped-def]
        from src.domain.ports.services.workspace_supervisor_port import TickReport

        return TickReport(workspace_id=workspace_id)

    async def is_running(self, workspace_id: str) -> bool:
        return workspace_id in self.started

    def kick(self, workspace_id: str) -> None:
        return None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _goal(title: str) -> Any:
    from src.domain.ports.services.goal_planner_port import GoalSpec

    return GoalSpec(workspace_id="ws-1", title=title, description="", created_by="u")


def _ctx() -> Any:
    from src.domain.ports.services.goal_planner_port import PlanningContext

    return PlanningContext(max_subtasks=4, max_depth=2)


def _leaf_node(
    *,
    title: str = "x",
    description: str = "",
    criteria: tuple[AcceptanceCriterion, ...] = (),
    metadata: dict[str, Any] | None = None,
    feature_checkpoint: FeatureCheckpoint | None = None,
) -> PlanNode:
    return PlanNode(
        id="n1",
        plan_id="p",
        parent_id=PlanNodeId("goal"),
        kind=PlanNodeKind.TASK,
        title=title,
        description=description,
        acceptance_criteria=criteria,
        feature_checkpoint=feature_checkpoint,
        metadata=metadata or {},
    )
