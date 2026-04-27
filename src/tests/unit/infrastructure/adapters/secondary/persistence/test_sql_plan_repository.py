"""Round-trip tests for :class:`SqlPlanRepository`."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace_plan import (
    AcceptanceCriterion,
    Capability,
    CriterionKind,
    FeatureCheckpoint,
    HandoffPackage,
    HandoffReason,
    Plan,
    PlanNode,
    PlanNodeId,
    PlanNodeKind,
    PlanStatus,
    TaskExecution,
    TaskIntent,
)
from src.domain.model.workspace_plan.plan_node import Effort, Progress
from src.infrastructure.adapters.secondary.persistence.models import WorkspaceModel
from src.infrastructure.adapters.secondary.persistence.sql_plan_repository import (
    SqlPlanRepository,
)


@pytest.fixture
async def seeded_workspace(db_session: AsyncSession) -> str:
    """Seed minimum FK rows so ``workspace_plans`` inserts pass."""
    from src.infrastructure.adapters.secondary.persistence.models import (
        Project as DBProject,
        Tenant as DBTenant,
        User as DBUser,
    )

    db_session.add_all(
        [
            DBUser(
                id="plan-user",
                email="plan-user@example.com",
                full_name="Plan User",
                hashed_password="hash",
                is_active=True,
            ),
            DBTenant(
                id="plan-tenant",
                name="Plan Tenant",
                slug="plan-tenant",
                description="",
                owner_id="plan-user",
                plan="free",
                max_projects=10,
                max_users=10,
                max_storage=1,
            ),
            DBProject(
                id="plan-project",
                tenant_id="plan-tenant",
                name="Plan Project",
                description="",
                owner_id="plan-user",
                memory_rules={},
                graph_config={},
                sandbox_type="cloud",
                sandbox_config={},
                is_public=False,
            ),
            WorkspaceModel(
                id="ws-plan-1",
                tenant_id="plan-tenant",
                project_id="plan-project",
                name="WS Plan 1",
                description="",
                created_by="plan-user",
                is_archived=False,
                metadata_json={},
            ),
        ]
    )
    await db_session.flush()
    return "ws-plan-1"


def _make_plan(workspace_id: str) -> Plan:
    goal_id = PlanNodeId(value="goal-1")
    plan = Plan(
        id="plan-1",
        workspace_id=workspace_id,
        goal_id=goal_id,
        status=PlanStatus.DRAFT,
        created_at=datetime.now(UTC),
    )
    plan.nodes[goal_id] = PlanNode(
        id=goal_id.value,
        plan_id=plan.id,
        kind=PlanNodeKind.GOAL,
        title="Build thing",
        description="Top-level goal",
        intent=TaskIntent.TODO,
        execution=TaskExecution.IDLE,
    )
    task_id = PlanNodeId(value="task-1")
    plan.nodes[task_id] = PlanNode(
        id=task_id.value,
        plan_id=plan.id,
        parent_id=goal_id,
        kind=PlanNodeKind.TASK,
        title="Do research",
        description="Gather info",
        depends_on=frozenset(),
        acceptance_criteria=(
            AcceptanceCriterion(
                kind=CriterionKind.CMD,
                spec={"cmd": "pytest -q", "max_exit": 0},
                required=True,
                description="tests pass",
            ),
            AcceptanceCriterion(
                kind=CriterionKind.FILE_EXISTS,
                spec={"path": "out.json"},
                required=False,
                description="output file",
            ),
        ),
        feature_checkpoint=FeatureCheckpoint(
            feature_id="feature-001-task-1",
            sequence=1,
            title="Do research",
            init_command="make init",
            test_commands=("pytest -q",),
            expected_artifacts=("out.json",),
            worktree_path="${sandbox_code_root}/../.memstack/worktrees/attempt-1",
            branch_name="workspace/task-1-attempt-1",
            base_ref="HEAD",
            commit_ref="abc123",
        ),
        handoff_package=HandoffPackage(
            reason=HandoffReason.CONTEXT_LIMIT,
            summary="Research is started; continue with tests.",
            next_steps=("run pytest -q",),
            completed_steps=("created out.json",),
            changed_files=("out.json",),
            git_head="abc123",
            git_diff_summary="1 file changed",
            test_commands=("pytest -q",),
            verification_notes="No known failures.",
            created_at=datetime(2026, 4, 27, tzinfo=UTC),
        ),
        recommended_capabilities=(
            Capability(name="web_search", weight=1.5),
            Capability(name="codegen"),
        ),
        estimated_effort=Effort(minutes=42, confidence=0.8),
        priority=7,
        intent=TaskIntent.IN_PROGRESS,
        execution=TaskExecution.RUNNING,
        progress=Progress(percent=25.0, confidence=0.9, note="starting"),
        assignee_agent_id="agent-x",
        workspace_task_id="wt-42",
        metadata={"foo": "bar"},
    )
    return plan


@pytest.mark.asyncio
async def test_save_and_get_roundtrips_every_field(
    db_session: AsyncSession, seeded_workspace: str
) -> None:
    repo = SqlPlanRepository(db_session)
    original = _make_plan(seeded_workspace)

    await repo.save(original)
    await db_session.commit()

    loaded = await repo.get("plan-1")
    assert loaded is not None
    assert loaded.workspace_id == seeded_workspace
    assert loaded.goal_id == PlanNodeId(value="goal-1")
    assert loaded.status is PlanStatus.DRAFT
    assert len(loaded.nodes) == 2

    task = loaded.nodes[PlanNodeId(value="task-1")]
    assert task.kind is PlanNodeKind.TASK
    assert task.parent_id == PlanNodeId(value="goal-1")
    assert task.intent is TaskIntent.IN_PROGRESS
    assert task.execution is TaskExecution.RUNNING
    assert task.priority == 7
    assert task.estimated_effort == Effort(minutes=42, confidence=0.8)
    assert task.progress.percent == 25.0
    assert task.progress.note == "starting"
    assert task.assignee_agent_id == "agent-x"
    assert task.workspace_task_id == "wt-42"
    assert task.metadata == {"foo": "bar"}
    assert task.feature_checkpoint is not None
    assert task.feature_checkpoint.feature_id == "feature-001-task-1"
    assert task.feature_checkpoint.test_commands == ("pytest -q",)
    assert task.feature_checkpoint.worktree_path == (
        "${sandbox_code_root}/../.memstack/worktrees/attempt-1"
    )
    assert task.feature_checkpoint.branch_name == "workspace/task-1-attempt-1"
    assert task.handoff_package is not None
    assert task.handoff_package.reason is HandoffReason.CONTEXT_LIMIT
    assert task.handoff_package.next_steps == ("run pytest -q",)

    names = sorted(c.name for c in task.recommended_capabilities)
    assert names == ["codegen", "web_search"]
    weights = {c.name: c.weight for c in task.recommended_capabilities}
    assert weights["web_search"] == 1.5

    assert len(task.acceptance_criteria) == 2
    ac0, ac1 = task.acceptance_criteria
    assert ac0.kind is CriterionKind.CMD
    assert ac0.spec["cmd"] == "pytest -q"
    assert ac0.required is True
    assert ac1.kind is CriterionKind.FILE_EXISTS
    assert ac1.required is False


@pytest.mark.asyncio
async def test_save_replaces_existing_nodes(
    db_session: AsyncSession, seeded_workspace: str
) -> None:
    repo = SqlPlanRepository(db_session)
    original = _make_plan(seeded_workspace)
    await repo.save(original)
    await db_session.commit()

    # Remove the task node, re-save.
    del original.nodes[PlanNodeId(value="task-1")]
    original.status = PlanStatus.ACTIVE
    original.updated_at = datetime.now(UTC)
    await repo.save(original)
    await db_session.commit()

    loaded = await repo.get("plan-1")
    assert loaded is not None
    assert loaded.status is PlanStatus.ACTIVE
    assert len(loaded.nodes) == 1
    assert PlanNodeId(value="task-1") not in loaded.nodes


@pytest.mark.asyncio
async def test_get_by_workspace_returns_latest(
    db_session: AsyncSession, seeded_workspace: str
) -> None:
    repo = SqlPlanRepository(db_session)
    plan = _make_plan(seeded_workspace)
    await repo.save(plan)
    await db_session.commit()

    fetched = await repo.get_by_workspace(seeded_workspace)
    assert fetched is not None
    assert fetched.id == "plan-1"


@pytest.mark.asyncio
async def test_delete_removes_plan_and_cascades_nodes(
    db_session: AsyncSession, seeded_workspace: str
) -> None:
    repo = SqlPlanRepository(db_session)
    plan = _make_plan(seeded_workspace)
    await repo.save(plan)
    await db_session.commit()

    await repo.delete(plan.id)
    await db_session.commit()

    assert await repo.get(plan.id) is None
    assert await repo.get_by_workspace(seeded_workspace) is None
