"""Unit tests for M2–M7 infrastructure adapters + supervisor + orchestrator.

Everything here is deterministic and in-memory — no LLM, no sandbox, no Ray.
"""

from __future__ import annotations

import asyncio
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
from src.infrastructure.agent.workspace_plan.allocator import CapabilityAllocator
from src.infrastructure.agent.workspace_plan.blackboard import InMemoryBlackboard
from src.infrastructure.agent.workspace_plan.orchestrator import (
    OrchestratorConfig,
    WorkspaceOrchestrator,
)
from src.infrastructure.agent.workspace_plan.planner import LLMGoalPlanner
from src.infrastructure.agent.workspace_plan.progress import ProgressProjector
from src.infrastructure.agent.workspace_plan.repository import InMemoryPlanRepository
from src.infrastructure.agent.workspace_plan.supervisor import WorkspaceSupervisor
from src.infrastructure.agent.workspace_plan.verifier import (
    AcceptanceCriterionVerifier,
    BrowserE2ECriterionRunner,
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


# ---------------------------------------------------------------------------
# M5 verifier
# ---------------------------------------------------------------------------


class TestVerifier:
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
            metadata={"write_set": ["src/app.py"]},
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


class _StaticIterationReviewer:
    def __init__(self, verdict: IterationReviewVerdict) -> None:
        self.verdict = verdict
        self.contexts: list[IterationReviewContext] = []

    async def review(self, context: IterationReviewContext) -> IterationReviewVerdict:
        self.contexts.append(context)
        return self.verdict


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
) -> WorkspaceSupervisor:
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
        from dataclasses import replace

        a = reloaded.nodes[PlanNodeId("a")]
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
    criteria: tuple[AcceptanceCriterion, ...] = (),
    metadata: dict[str, Any] | None = None,
    feature_checkpoint: FeatureCheckpoint | None = None,
) -> PlanNode:
    return PlanNode(
        id="n1",
        plan_id="p",
        parent_id=PlanNodeId("goal"),
        kind=PlanNodeKind.TASK,
        title="x",
        acceptance_criteria=criteria,
        feature_checkpoint=feature_checkpoint,
        metadata=metadata or {},
    )
