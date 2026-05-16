from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports.services.workspace_supervisor_port import TickReport
from src.infrastructure.adapters.secondary.persistence.models import (
    PlanModel,
    PlanNodeModel,
    Project,
    Tenant,
    User,
    WorkspaceModel,
    WorkspacePlanOutboxModel,
    WorkspaceTaskModel,
    WorkspaceTaskSessionAttemptModel,
)
from src.infrastructure.agent.workspace_plan.run_controller import WorkspaceRunController


async def _seed_workspace_plan(db_session: AsyncSession, *, plan_status: str = "completed") -> None:
    db_session.add_all(
        [
            User(
                id="run-user-1",
                email="run-user-1@example.com",
                full_name="Run User",
                hashed_password="hash",
                is_active=True,
            ),
            Tenant(
                id="run-tenant-1",
                name="Run Tenant",
                slug="run-tenant",
                description="",
                owner_id="run-user-1",
                plan="free",
                max_projects=10,
                max_users=10,
                max_storage=1,
            ),
            Project(
                id="run-project-1",
                tenant_id="run-tenant-1",
                name="Run Project",
                description="",
                owner_id="run-user-1",
                memory_rules={},
                graph_config={},
                sandbox_type="cloud",
                sandbox_config={},
                is_public=False,
            ),
            WorkspaceModel(
                id="run-workspace-1",
                tenant_id="run-tenant-1",
                project_id="run-project-1",
                name="Run Workspace",
                description="",
                created_by="run-user-1",
                metadata_json={"workspace_run_contract": {"concurrency": 2}},
            ),
            PlanModel(
                id="run-plan-1",
                workspace_id="run-workspace-1",
                goal_id="run-goal-1",
                status=plan_status,
                updated_at=datetime.now(UTC),
            ),
            PlanNodeModel(
                id="run-goal-1",
                plan_id="run-plan-1",
                parent_id=None,
                kind="goal",
                title="Run goal",
                description="",
                depends_on=[],
                inputs_schema={},
                outputs_schema={},
                acceptance_criteria=[{"kind": "cmd", "spec": {"cmd": "pytest"}, "required": True}],
                feature_checkpoint=None,
                handoff_package=None,
                recommended_capabilities=[],
                estimated_effort={},
                priority=0,
                intent="done",
                execution="idle",
                progress={},
                metadata_json={
                    "last_verification_passed": True,
                    "last_verification_summary": "pytest passed",
                    "verification_evidence_refs": ["test_run:pytest"],
                },
            ),
        ]
    )
    await db_session.flush()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_controller_tick_wraps_runner_and_records_completion_gate(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_plan(db_session)
    calls = 0

    async def runner() -> TickReport:
        nonlocal calls
        calls += 1
        return TickReport(workspace_id="run-workspace-1", nodes_completed=1)

    result = await WorkspaceRunController(db_session).tick(
        plan_id="run-plan-1",
        reason="unit_test",
        actor_id="actor-1",
        runner=runner,
    )

    assert calls == 1
    assert result.contract.concurrency == 2
    assert result.tick_report is not None
    assert result.tick_report.nodes_completed == 1
    assert result.completion_gate["allowed"] is True
    assert result.last_reconciliation["reason"] == "unit_test"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_controller_completion_gate_blocks_on_retry_queue(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_plan(db_session)
    db_session.add(
        WorkspacePlanOutboxModel(
            id="outbox-1",
            plan_id="run-plan-1",
            workspace_id="run-workspace-1",
            event_type="worker_launch",
            status="pending",
            payload_json={"node_id": "run-goal-1"},
            metadata_json={},
        )
    )
    await db_session.flush()

    result = await WorkspaceRunController(db_session).tick(
        workspace_id="run-workspace-1",
        reason="unit_test",
        runner=lambda: _tick_report(),
    )

    assert result.completion_gate["allowed"] is False
    assert result.blocked_reason == "active or retryable outbox items remain"
    assert result.retry_queue[0]["outbox_id"] == "outbox-1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_controller_completion_gate_blocks_on_active_attempt(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_plan(db_session)
    db_session.add(
        WorkspaceTaskModel(
            id="run-task-1",
            workspace_id="run-workspace-1",
            title="Run task",
            description="",
            created_by="run-user-1",
            status="in_progress",
            priority=0,
            metadata_json={},
        )
    )
    db_session.add(
        WorkspaceTaskSessionAttemptModel(
            id="attempt-1",
            workspace_task_id="run-task-1",
            root_goal_task_id="run-task-1",
            workspace_id="run-workspace-1",
            attempt_number=1,
            status="running",
            candidate_artifacts_json=[],
            candidate_verifications_json=[],
        )
    )
    await db_session.flush()

    result = await WorkspaceRunController(db_session).tick(
        plan_id="run-plan-1",
        reason="unit_test",
        runner=lambda: _tick_report(),
    )

    assert result.completion_gate["allowed"] is False
    assert result.blocked_reason == "running workspace task attempts remain"
    assert result.active_attempts[0]["attempt_id"] == "attempt-1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_controller_completion_gate_blocks_unintegrated_accepted_worktree(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_plan(db_session)
    node = await db_session.get(PlanNodeModel, "run-goal-1")
    assert node is not None
    node.metadata_json = {
        **dict(node.metadata_json or {}),
        "last_verification_passed": True,
        "last_verification_summary": "pytest passed",
        "verification_evidence_refs": ["test_run:pytest"],
        "verified_commit_ref": "abc1234",
        "worktree_integration_status": "blocked_dirty_main",
        "worktree_integration_worktree_path": "/workspace/.memstack/worktrees/attempt-1",
        "worktree_integration_dirty_signature": "dirty-sig",
    }
    await db_session.flush()

    result = await WorkspaceRunController(db_session).tick(
        plan_id="run-plan-1",
        reason="unit_test",
        runner=lambda: _tick_report(),
    )

    assert result.completion_gate["allowed"] is False
    assert result.blocked_reason == "accepted worktree integration is incomplete"
    assert result.completion_gate["checks"]["worktrees_integrated"] is False
    assert result.completion_gate["worktree_integration_gaps"][0]["status"] == (
        "blocked_dirty_main"
    )


async def _tick_report() -> TickReport:
    return TickReport(workspace_id="run-workspace-1")
