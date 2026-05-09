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
from src.domain.ports.services.workspace_verification_judge_port import (
    WorkspaceVerificationJudgeRequest,
    WorkspaceVerificationJudgeResult,
    WorkspaceVerificationJudgeVerdict,
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
    _node_with_verification_evidence,
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

        assert len(runner.calls) == 1
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
        leaf = plan.leaf_tasks()[0]
        from dataclasses import replace

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
        assert repair.metadata["allow_verification_script_changes"] is True
        assert repair.metadata["iteration_phase"] == "implement"
        assert repair.metadata["repair_source"] == "verification_judge_create_repair_node"
        assert "active attempt worktree only" in repair.description
        assert "do not require or attempt edits, merges" in repair.description
        assert repair.description.index("active attempt worktree only") < repair.description.index(
            "Make E2E report paths worktree-relative"
        )
        assert reset.intent is TaskIntent.TODO
        assert reset.execution is TaskExecution.IDLE
        assert reset.current_attempt_id is None
        assert repair.node_id in reset.depends_on
        assert reset.metadata["blocked_by_repair_node_id"] == repair.id

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

    def test_iteration_reviewer_prompt_preserves_attempt_worktree_contract(self) -> None:
        prompt = build_builtin_workspace_iteration_reviewer_agent(
            tenant_id="tenant-1",
            project_id="project-1",
        ).system_prompt

        assert "attempt worktree isolation as an intentional execution contract" in prompt
        assert "Do not propose main-checkout" in prompt
        assert "Do not create next tasks whose only purpose is merging worker commits" in prompt
        assert "environment-configurable" in prompt

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
                )
            )
        )

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
        isolation_policy = " ".join(payload["policy"]["attempt_worktree_isolation"])
        assert "sandbox.worktree_path is the active execution root" in isolation_policy
        assert "not a transient retry_infrastructure condition" in isolation_policy
        assert "Do not recommend running from the main checkout" in isolation_policy
        assert "reported commit_refs" in isolation_policy
        assert "active attempt worktree branch" in isolation_policy
        assert "environment-configurable" in isolation_policy
        assert payload["policy"]["next_action_kinds"]["create_repair_node"].startswith("Use when")
        assert "same node can fix" in payload["policy"]["next_action_kinds"]["retry_same_node"]
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

    async def test_verifier_does_not_call_judge_for_explicit_blocked_worker_report(
        self,
    ) -> None:
        judge = _RecordingVerificationJudge(
            WorkspaceVerificationJudgeResult(
                verdict=WorkspaceVerificationJudgeVerdict.ACCEPTED,
                rationale="would accept if called",
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

        assert judge.requests == []
        assert not rep.passed
        assert rep.hard_fail
        assert "outside the active attempt worktree" in rep.summary()

    async def test_verifier_soft_fails_retryable_infrastructure_blocker(self) -> None:
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
                    required=True,
                ),
            )
        )
        ctx = VerificationContext(
            workspace_id="ws",
            node=node,
            stdout="litellm.APIConnectionError: Executor shutdown has been called",
            artifacts={
                "last_worker_report_type": "blocked",
                "last_worker_report_summary": (
                    "litellm.APIConnectionError: Executor shutdown has been called"
                ),
            },
        )
        rep = await verifier.verify(ctx)

        assert not rep.passed
        assert not rep.hard_fail
        assert "retryable infrastructure failure" in rep.summary()

    async def test_verifier_soft_fails_litellm_internal_server_blocker(self) -> None:
        verifier = AcceptanceCriterionVerifier()
        node = _leaf_node()
        summary = (
            "litellm.InternalServerError: AnthropicException - 400, "
            'message="Expected HTTP/, RTSP/ or ICE/"'
        )
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

        assert not rep.passed
        assert not rep.hard_fail
        assert "retryable infrastructure failure" in rep.summary()

    async def test_verifier_soft_fails_rate_limit_blocker(self) -> None:
        verifier = AcceptanceCriterionVerifier()
        node = _leaf_node()
        ctx = VerificationContext(
            workspace_id="ws",
            node=node,
            stdout="Rate limit exceeded. Please wait a moment and try again.",
            artifacts={
                "last_worker_report_type": "blocked",
                "last_worker_report_summary": (
                    "Rate limit exceeded. Please wait a moment and try again."
                ),
            },
        )
        rep = await verifier.verify(ctx)

        assert not rep.passed
        assert not rep.hard_fail
        assert "retryable infrastructure failure" in rep.summary()

    async def test_verifier_soft_fails_sandbox_tool_timeout_blocker(self) -> None:
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
            stdout="Tool execution failed after 1 attempts: 工具执行超时: bash",
            artifacts={
                "last_worker_report_type": "blocked",
                "last_worker_report_summary": (
                    "All tool operations are timing out; filesystem appears to be unresponsive"
                ),
            },
        )
        rep = await verifier.verify(ctx)

        assert not rep.passed
        assert not rep.hard_fail
        assert "retryable infrastructure failure" in rep.summary()
        assert "missing preflight evidence" not in rep.summary()

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
        assert judge.requests[0].recent_git_status == ""
        assert any(
            result["name"] == "clean_worktree_after_commit" and result["passed"] is True
            for result in judge.requests[0].latest_verification_results
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
                        },
                        required=True,
                    ),
                    passed=False,
                    confidence=0.5,
                    message="judge verdict=retry_infrastructure; retry verification judge",
                ),
            ),
        )


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
                metadata={
                    "last_verification_passed": True,
                    "pipeline_status": "success",
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
        assert events == [
            (
                "dependency_invalidated",
                "b",
                {
                    "summary": "node reset because one or more dependencies are no longer done",
                    "missing_dependency_ids": ["a"],
                    "previous_attempt_id": "attempt-b",
                    "previous_intent": "in_progress",
                    "previous_execution": "running",
                },
            )
        ]

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
            return [
                WorkspaceAgent(
                    agent_id="ag-search",
                    display_name="S",
                    capabilities=frozenset({"web_search"}),
                )
            ]

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
            return [
                WorkspaceAgent(
                    agent_id="ag-search",
                    display_name="S",
                    capabilities=frozenset({"web_search"}),
                )
            ]

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
        retry_events = [event for event in events if event[0] == "verification_retry_scheduled"]
        assert len(retry_events) == 1
        assert retry_events[0][2]["retry_verification_only"] is True

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
        assert repair.metadata["allow_verification_script_changes"] is True
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
