"""Unit tests for M2–M7 infrastructure adapters + supervisor + orchestrator.

Everything here is deterministic and in-memory — no LLM, no sandbox, no Ray.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from src.domain.model.workspace_plan import (
    AcceptanceCriterion,
    Capability,
    CriterionKind,
    Plan,
    PlanNode,
    PlanNodeId,
    PlanNodeKind,
    PlanStatus,
    TaskExecution,
    TaskIntent,
    VerificationReport,
)
from src.domain.ports.services.task_allocator_port import WorkspaceAgent
from src.domain.ports.services.verifier_port import VerificationContext
from src.infrastructure.agent.workspace_plan.adapter import (
    LegacyTaskView,
    legacy_status_for,
    plan_node_from_task,
)
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
# Adapter (PlanNode <-> legacy WorkspaceTask)
# ---------------------------------------------------------------------------


class TestAdapter:
    def test_legacy_status_roundtrip(self) -> None:
        task = LegacyTaskView(
            id="t1",
            workspace_id="ws",
            title="do it",
            description="",
            status="executing",
            priority=2,
            metadata={"x": 1},
        )
        node = plan_node_from_task(task, plan_id="p", parent_id=PlanNodeId("goal"))
        assert node.intent is TaskIntent.IN_PROGRESS
        assert node.workspace_task_id == "t1"
        assert node.metadata["x"] == 1
        assert legacy_status_for(node) == "in_progress"


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


# ---------------------------------------------------------------------------
# Orchestrator feature-flag behavior
# ---------------------------------------------------------------------------


class TestOrchestratorFeatureFlag:
    async def test_disabled_by_default_rejects_start(self) -> None:
        repo = InMemoryPlanRepository()
        orch = WorkspaceOrchestrator(
            planner=LLMGoalPlanner(decomposer=None),
            allocator=CapabilityAllocator(),
            verifier=_AlwaysPassVerifier(),
            projector=ProgressProjector(),
            supervisor=_NoopSupervisor(),
            plan_repo=repo,
            config=OrchestratorConfig(enabled=False),
        )
        with pytest.raises(RuntimeError):
            await orch.start_goal(workspace_id="ws", title="x")

    async def test_enabled_creates_plan_and_starts_supervisor(self) -> None:
        repo = InMemoryPlanRepository()
        sup = _NoopSupervisor()
        orch = WorkspaceOrchestrator(
            planner=LLMGoalPlanner(decomposer=None),
            allocator=CapabilityAllocator(),
            verifier=_AlwaysPassVerifier(),
            projector=ProgressProjector(),
            supervisor=sup,
            plan_repo=repo,
            config=OrchestratorConfig(enabled=True),
        )
        plan = await orch.start_goal(workspace_id="ws", title="goal")
        assert plan.workspace_id == "ws"
        assert sup.started == ["ws"]


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


def _leaf_node(*, criteria: tuple[AcceptanceCriterion, ...] = ()) -> PlanNode:
    return PlanNode(
        id="n1",
        plan_id="p",
        parent_id=PlanNodeId("goal"),
        kind=PlanNodeKind.TASK,
        title="x",
        acceptance_criteria=criteria,
    )
