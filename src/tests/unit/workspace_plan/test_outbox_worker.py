"""Tests for the workspace plan outbox worker."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace.workspace_task import WorkspaceTask
from src.domain.model.workspace_plan import (
    FeatureCheckpoint,
    PlanNode,
    PlanNodeId,
    TaskExecution,
    TaskIntent,
)
from src.domain.ports.services.task_allocator_port import Allocation, WorkspaceAgent
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentDefinitionModel,
    PlanModel,
    Project as DBProject,
    Tenant as DBTenant,
    User as DBUser,
    WorkspaceAgentModel,
    WorkspaceMemberModel,
    WorkspaceModel,
    WorkspacePlanEventModel,
    WorkspacePlanOutboxModel,
    WorkspaceTaskModel,
    WorkspaceTaskSessionAttemptModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_plan_repository import SqlPlanRepository
from src.infrastructure.adapters.secondary.persistence.sql_workspace_plan_outbox import (
    SqlWorkspacePlanOutboxRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository import (
    SqlWorkspaceTaskRepository,
)
from src.infrastructure.agent.sisyphus.builtin_agent import BUILTIN_SISYPHUS_ID
from src.infrastructure.agent.workspace.workspace_goal_runtime import (
    apply_workspace_worker_report,
)
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    AUTONOMY_SCHEMA_VERSION_KEY,
    CURRENT_ATTEMPT_ID,
    CURRENT_ATTEMPT_WORKER_BINDING_ID,
    EXECUTION_STATE,
    ROOT_GOAL_TASK_ID,
    TASK_ROLE,
    WORKSPACE_PLAN_ID,
    WORKSPACE_PLAN_NODE_ID,
)
from src.infrastructure.agent.workspace_plan.factory import build_sql_orchestrator
from src.infrastructure.agent.workspace_plan.orchestrator import OrchestratorConfig
from src.infrastructure.agent.workspace_plan.outbox_handlers import (
    HANDOFF_RESUME_EVENT,
    SUPERVISOR_TICK_EVENT,
    WORKER_LAUNCH_EVENT,
    _node_allowed_sandbox_commands,
    _WorkspaceSandboxCommandRunner,
    make_handoff_resume_handler,
    make_supervisor_tick_handler,
    make_worker_launch_handler,
)
from src.infrastructure.agent.workspace_plan.outbox_worker import (
    WorkspacePlanOutboxWorker,
    WorkspacePlanSessionFactory,
)


async def _seed_plan(db_session: AsyncSession, workspace_id: str, plan_id: str) -> None:
    db_session.add(
        PlanModel(
            id=plan_id,
            workspace_id=workspace_id,
            goal_id=f"{plan_id}-goal",
            status="active",
        )
    )
    await db_session.flush()


async def _seed_workspace_and_plan(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            DBUser(
                id="worker-user-1",
                email="worker-user-1@example.com",
                full_name="Worker User",
                hashed_password="hash",
                is_active=True,
            ),
            DBTenant(
                id="worker-tenant-1",
                name="Worker Tenant",
                slug="worker-tenant",
                description="",
                owner_id="worker-user-1",
                plan="free",
                max_projects=10,
                max_users=10,
                max_storage=1,
            ),
            DBProject(
                id="worker-project-1",
                tenant_id="worker-tenant-1",
                name="Worker Project",
                description="",
                owner_id="worker-user-1",
                memory_rules={},
                graph_config={},
                sandbox_type="cloud",
                sandbox_config={},
                is_public=False,
            ),
            WorkspaceModel(
                id="workspace-1",
                tenant_id="worker-tenant-1",
                project_id="worker-project-1",
                name="Worker Workspace",
                description="",
                created_by="worker-user-1",
                is_archived=False,
                metadata_json={},
            ),
            WorkspaceMemberModel(
                id="workspace-member-1",
                workspace_id="workspace-1",
                user_id="worker-user-1",
                role="owner",
                invited_by="worker-user-1",
            ),
            AgentDefinitionModel(
                id=BUILTIN_SISYPHUS_ID,
                tenant_id="worker-tenant-1",
                project_id="worker-project-1",
                name="sisyphus",
                display_name="Sisyphus",
                system_prompt="You coordinate workspace execution.",
                allowed_tools=[],
                allowed_skills=[],
                allowed_mcp_servers=[],
            ),
            AgentDefinitionModel(
                id="worker-agent",
                tenant_id="worker-tenant-1",
                project_id="worker-project-1",
                name="worker-agent",
                display_name="Worker Agent",
                system_prompt="You execute workspace tasks.",
                allowed_tools=[],
                allowed_skills=[],
                allowed_mcp_servers=[],
            ),
            WorkspaceAgentModel(
                id="worker-binding-1",
                workspace_id="workspace-1",
                agent_id="worker-agent",
                display_name="Worker Agent",
                description=None,
                config_json={"capabilities": ["codegen"]},
                is_active=True,
            ),
            WorkspaceTaskModel(
                id="root-task-1",
                workspace_id="workspace-1",
                title="Root goal",
                description="Root goal for V2 dispatch",
                created_by="worker-user-1",
                status="in_progress",
                priority=0,
                metadata_json={
                    AUTONOMY_SCHEMA_VERSION_KEY: 1,
                    TASK_ROLE: "goal_root",
                    "goal_origin": "existing_root",
                    "goal_source_refs": [],
                    "root_goal_policy": {
                        "mutable_by_agent": False,
                        "completion_requires_external_proof": True,
                    },
                    "goal_health": "healthy",
                },
            ),
        ]
    )
    await db_session.flush()
    await _seed_plan(db_session, "workspace-1", "worker-plan-1")


def _session_factory(db_session: AsyncSession) -> WorkspacePlanSessionFactory:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    return factory


@pytest.mark.asyncio
async def test_workspace_sandbox_runner_blocks_commands_outside_harness_allowlist() -> None:
    runner = _WorkspaceSandboxCommandRunner(
        project_id="project-1",
        allowed_commands={"uv run pytest src/tests/unit/example.py"},
    )

    result = await runner.run_command("rm -rf /tmp/nope")

    assert result["exit_code"] == 126
    assert result["stdout"] == ""
    assert "not allowed by workspace harness" in result["stderr"]


def test_node_allowed_sandbox_commands_collects_checkpoint_and_preflight_commands() -> None:
    node = PlanNode(
        id="node-1",
        plan_id="plan-1",
        parent_id=PlanNodeId("goal-1"),
        title="Ship checkout flow",
        metadata={
            "verification_commands": ["uv run pytest src/tests/unit/example.py"],
            "preflight_checks": [
                {"check_id": "git-status", "command": "git status --short"},
                {"check_id": "read-progress"},
            ],
        },
        feature_checkpoint=FeatureCheckpoint(
            feature_id="feature-1",
            sequence=1,
            title="Checkout flow",
            init_command="make init",
            test_commands=("uv run pytest src/tests/unit/example.py", "npm test -- checkout"),
        ),
    )

    assert _node_allowed_sandbox_commands(node) == {
        "git status --short",
        "make init",
        "npm test -- checkout",
        "uv run pytest src/tests/unit/example.py",
    }


@pytest.mark.asyncio
async def test_run_once_completes_registered_handler(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_and_plan(db_session)
    repo = SqlWorkspacePlanOutboxRepository(db_session)
    item = await repo.enqueue(
        plan_id="worker-plan-1",
        workspace_id="workspace-1",
        event_type="supervisor_tick",
        payload={"workspace_id": "workspace-1"},
    )
    handled: list[str] = []

    async def handler(outbox_item: WorkspacePlanOutboxModel, session: AsyncSession) -> None:
        handled.append(outbox_item.id)
        assert session is db_session
        assert outbox_item.payload_json == {"workspace_id": "workspace-1"}

    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={"supervisor_tick": handler},
        worker_id="worker-a",
    )

    assert await worker.run_once() == 1

    loaded = await repo.get_by_id(item.id)
    assert handled == [item.id]
    assert loaded is not None
    assert loaded.status == "completed"
    assert loaded.attempt_count == 1
    assert loaded.lease_owner is None
    assert loaded.processed_at is not None


@pytest.mark.asyncio
async def test_run_once_publishes_plan_update_after_handler_completion(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_and_plan(db_session)
    repo = SqlWorkspacePlanOutboxRepository(db_session)
    item = await repo.enqueue(
        plan_id="worker-plan-1",
        workspace_id="workspace-1",
        event_type="supervisor_tick",
        payload={"workspace_id": "workspace-1", "node_id": "node-1"},
    )
    published: list[dict[str, object]] = []

    async def handler(_outbox_item: WorkspacePlanOutboxModel, _session: AsyncSession) -> None:
        return None

    async def event_publisher(payload: dict[str, object]) -> None:
        published.append(payload)

    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={"supervisor_tick": handler},
        worker_id="worker-a",
        event_publisher=event_publisher,
    )

    assert await worker.run_once() == 1

    assert published == [
        {
            "workspace_id": "workspace-1",
            "plan_id": "worker-plan-1",
            "outbox_id": item.id,
            "outbox_event_type": "supervisor_tick",
            "outbox_status": "completed",
            "attempt_count": 1,
            "max_attempts": 5,
            "change": "outbox_completed",
            "node_id": "node-1",
        }
    ]


@pytest.mark.asyncio
async def test_run_once_marks_missing_handler_failed(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_and_plan(db_session)
    repo = SqlWorkspacePlanOutboxRepository(db_session)
    item = await repo.enqueue(
        plan_id="worker-plan-1",
        workspace_id="workspace-1",
        event_type="dispatch_node",
        max_attempts=2,
    )
    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={},
        worker_id="worker-a",
    )

    assert await worker.run_once() == 1

    loaded = await repo.get_by_id(item.id)
    assert loaded is not None
    assert loaded.status == "failed"
    assert loaded.attempt_count == 1
    assert loaded.lease_owner is None
    assert loaded.next_attempt_at is not None
    assert loaded.last_error == "no handler for event_type=dispatch_node"


@pytest.mark.asyncio
async def test_run_once_dead_letters_handler_exception_after_last_attempt(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_and_plan(db_session)
    repo = SqlWorkspacePlanOutboxRepository(db_session)
    item = await repo.enqueue(
        plan_id="worker-plan-1",
        workspace_id="workspace-1",
        event_type="verify_node",
        max_attempts=1,
    )

    async def failing_handler(
        outbox_item: WorkspacePlanOutboxModel,
        session: AsyncSession,
    ) -> None:
        raise RuntimeError(f"boom: {outbox_item.id} {session is db_session}")

    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={"verify_node": failing_handler},
        worker_id="worker-a",
    )

    assert await worker.run_once() == 1

    loaded = await repo.get_by_id(item.id)
    assert loaded is not None
    assert loaded.status == "dead_letter"
    assert loaded.attempt_count == 1
    assert loaded.lease_owner is None
    assert loaded.next_attempt_at is None
    assert loaded.last_error == f"boom: {item.id} True"


@pytest.mark.asyncio
async def test_run_once_returns_zero_when_no_due_items(
    db_session: AsyncSession,
) -> None:
    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={},
        worker_id="worker-a",
    )

    assert await worker.run_once() == 0


@pytest.mark.asyncio
async def test_supervisor_tick_handler_advances_sql_plan_from_outbox(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_only(db_session)
    orchestrator = build_sql_orchestrator(
        db_session,
        config=OrchestratorConfig(heartbeat_seconds=3600),
    )
    plan = await orchestrator.start_goal(
        workspace_id="workspace-1",
        title="Ship a durable plan",
        start_supervisor=False,
    )
    repo = SqlWorkspacePlanOutboxRepository(db_session)
    await repo.enqueue(
        plan_id=plan.id,
        workspace_id="workspace-1",
        event_type=SUPERVISOR_TICK_EVENT,
        payload={"workspace_id": "workspace-1"},
    )
    await db_session.commit()

    dispatched: list[tuple[str, str]] = []

    async def agent_pool(_workspace_id: str) -> list[WorkspaceAgent]:
        return [WorkspaceAgent(agent_id="agent-1", display_name="Agent One")]

    async def dispatcher(
        _workspace_id: str,
        allocation: Allocation,
        node: PlanNode,
    ) -> str:
        dispatched.append((allocation.agent_id, node.id))
        return f"attempt-{node.id}"

    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={
            SUPERVISOR_TICK_EVENT: make_supervisor_tick_handler(
                config=OrchestratorConfig(heartbeat_seconds=3600),
                agent_pool=agent_pool,
                dispatcher=dispatcher,
            )
        },
        worker_id="worker-a",
    )

    assert await worker.run_once() == 1
    loaded = await SqlPlanRepository(db_session).get(plan.id)
    assert loaded is not None
    leaf = loaded.leaf_tasks()[0]
    assert dispatched == [("agent-1", leaf.id)]
    assert leaf.intent is TaskIntent.IN_PROGRESS
    assert leaf.execution is TaskExecution.DISPATCHED
    assert leaf.assignee_agent_id == "agent-1"
    assert leaf.current_attempt_id == f"attempt-{leaf.id}"


@pytest.mark.asyncio
async def test_supervisor_tick_handler_launches_real_worker_and_verifies_report(  # noqa: PLR0915
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_workspace_only(db_session)
    orchestrator = build_sql_orchestrator(
        db_session,
        config=OrchestratorConfig(heartbeat_seconds=3600),
    )
    plan = await orchestrator.start_goal(
        workspace_id="workspace-1",
        title="Ship a durable plan",
        start_supervisor=False,
    )
    planned_leaf = plan.leaf_tasks()[0]
    assert planned_leaf.feature_checkpoint is not None
    plan.replace_node(
        replace(
            planned_leaf,
            feature_checkpoint=replace(
                planned_leaf.feature_checkpoint,
                expected_artifacts=("src/example.py",),
                test_commands=("uv run pytest src/tests/unit/example.py",),
            ),
            metadata={
                **planned_leaf.metadata,
                "write_set": ["src/example.py"],
                "verification_commands": ["uv run pytest src/tests/unit/example.py"],
            },
        )
    )
    await SqlPlanRepository(db_session).save(plan)
    await SqlWorkspacePlanOutboxRepository(db_session).enqueue(
        plan_id=plan.id,
        workspace_id="workspace-1",
        event_type=SUPERVISOR_TICK_EVENT,
        payload={
            "workspace_id": "workspace-1",
            "root_task_id": "root-task-1",
            "actor_user_id": "worker-user-1",
            "leader_agent_id": BUILTIN_SISYPHUS_ID,
        },
    )
    await db_session.commit()

    launched: list[dict[str, object]] = []

    def fake_schedule_worker_session(**kwargs: object) -> None:
        launched.append(kwargs)

    prepared_worktrees: list[tuple[str, str]] = []

    async def fake_worktree_preparer(
        _session: AsyncSession,
        workspace_id: str,
        task: WorkspaceTask,
        extra_instructions: str | None,
    ) -> str:
        assert extra_instructions is not None
        assert "[feature-checkpoint]" in extra_instructions
        prepared_worktrees.append((workspace_id, task.id))
        return "[worktree-setup]\nstatus=prepared\n[/worktree-setup]"

    monkeypatch.setattr(
        "src.infrastructure.agent.workspace.worker_launch.schedule_worker_session",
        fake_schedule_worker_session,
    )

    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={
            SUPERVISOR_TICK_EVENT: make_supervisor_tick_handler(
                config=OrchestratorConfig(heartbeat_seconds=3600),
            ),
            WORKER_LAUNCH_EVENT: make_worker_launch_handler(
                worktree_preparer=fake_worktree_preparer
            ),
        },
        worker_id="worker-a",
    )

    assert await worker.run_once() == 1
    outbox_after_dispatch = list(
        (
            await db_session.execute(
                select(WorkspacePlanOutboxModel).where(
                    WorkspacePlanOutboxModel.event_type == SUPERVISOR_TICK_EVENT
                )
            )
        )
        .scalars()
        .all()
    )
    assert outbox_after_dispatch[0].status == "completed", outbox_after_dispatch[0].last_error
    worker_launch_jobs = list(
        (
            await db_session.execute(
                select(WorkspacePlanOutboxModel).where(
                    WorkspacePlanOutboxModel.event_type == WORKER_LAUNCH_EVENT
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(worker_launch_jobs) == 1
    worker_launch_job_id = worker_launch_jobs[0].id
    assert worker_launch_jobs[0].status == "pending"
    assert not launched
    assert await worker.run_once() == 1
    db_session.expire_all()
    worker_launch_job = await db_session.get(WorkspacePlanOutboxModel, worker_launch_job_id)
    assert worker_launch_job is not None
    assert worker_launch_job.status == "completed", worker_launch_job.last_error
    assert launched
    db_session.expire_all()

    loaded = await SqlPlanRepository(db_session).get(plan.id)
    assert loaded is not None
    leaf = loaded.leaf_tasks()[0]
    assert leaf.intent is TaskIntent.IN_PROGRESS
    assert leaf.execution is TaskExecution.DISPATCHED
    assert leaf.assignee_agent_id == "worker-agent"
    assert leaf.workspace_task_id is not None
    assert leaf.current_attempt_id is not None

    task = await SqlWorkspaceTaskRepository(db_session).find_by_id(leaf.workspace_task_id)
    assert task is not None
    assert task.assignee_agent_id == "worker-agent"
    assert task.status.value == "in_progress"
    assert prepared_worktrees == [("workspace-1", task.id)]
    root_task = await SqlWorkspaceTaskRepository(db_session).find_by_id("root-task-1")
    assert root_task is not None
    assert root_task.status.value == "in_progress"
    assert task.metadata[ROOT_GOAL_TASK_ID] == "root-task-1"
    assert task.metadata[WORKSPACE_PLAN_ID] == plan.id
    assert task.metadata[WORKSPACE_PLAN_NODE_ID] == leaf.id
    assert leaf.feature_checkpoint is not None
    assert task.metadata["harness_feature_id"] == leaf.feature_checkpoint.feature_id
    assert task.metadata["preflight_checks"][0]["check_id"] == "read-progress"
    assert task.metadata["feature_checkpoint"]["feature_id"] == leaf.feature_checkpoint.feature_id
    assert task.metadata["feature_checkpoint"]["worktree_path"] == (
        f"${{sandbox_code_root}}/../.memstack/worktrees/{leaf.current_attempt_id}"
    )
    assert task.metadata["feature_checkpoint"]["branch_name"].startswith(f"workspace/{leaf.id}-")
    assert task.metadata[CURRENT_ATTEMPT_ID] == leaf.current_attempt_id
    assert task.metadata["current_attempt_number"] == 1
    assert task.metadata["current_attempt_worker_agent_id"] == "worker-agent"
    assert task.metadata[CURRENT_ATTEMPT_WORKER_BINDING_ID] == "worker-binding-1"
    assert task.metadata["last_attempt_status"] == "running"
    assert task.metadata[EXECUTION_STATE]["phase"] == "in_progress"
    assert task.metadata[EXECUTION_STATE]["last_agent_reason"] == (
        "workspace_plan.dispatch.project_attempt"
    )
    assert task.metadata[EXECUTION_STATE]["last_agent_action"] == "start"
    assert launched and launched[0]["attempt_id"] == leaf.current_attempt_id
    assert "[feature-checkpoint]" in str(launched[0]["extra_instructions"])
    assert "[preflight-checks]" in str(launched[0]["extra_instructions"])
    assert leaf.feature_checkpoint.feature_id in str(launched[0]["extra_instructions"])
    assert "worktree_path=${sandbox_code_root}/../.memstack/worktrees/" in str(
        launched[0]["extra_instructions"]
    )
    assert "branch_name=workspace/" in str(launched[0]["extra_instructions"])
    assert "[worktree-setup]" in str(launched[0]["extra_instructions"])
    assert "status=prepared" in str(launched[0]["extra_instructions"])

    async def report_session_factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(
        "src.infrastructure.agent.workspace.workspace_goal_runtime.async_session_factory",
        asynccontextmanager(report_session_factory),
    )
    updated = await apply_workspace_worker_report(
        workspace_id="workspace-1",
        root_goal_task_id="root-task-1",
        task_id=task.id,
        attempt_id=leaf.current_attempt_id,
        actor_user_id="worker-user-1",
        worker_agent_id="worker-agent",
        leader_agent_id=BUILTIN_SISYPHUS_ID,
        report_type="completed",
        summary=(
            '{"summary":"Implemented the durable task and verified it.",'
            '"verifications":["preflight:read-progress","preflight:git-status"],'
            '"commit_ref":"abc123",'
            '"git_diff_summary":"1 file changed",'
            '"changed_files":["src/example.py"],'
            '"test_commands":["uv run pytest src/tests/unit/example.py"]}'
        ),
    )
    assert updated is not None
    assert updated.metadata["pending_leader_adjudication"] is False
    assert updated.metadata["last_attempt_status"] == "awaiting_plan_verification"

    assert await worker.run_once() == 1
    db_session.expire_all()
    verified = await SqlPlanRepository(db_session).get(plan.id)
    assert verified is not None
    verified_leaf = verified.leaf_tasks()[0]
    assert verified_leaf.intent is TaskIntent.DONE
    assert verified_leaf.execution is TaskExecution.IDLE
    assert verified_leaf.metadata["verified_commit_ref"] == "abc123"
    assert verified_leaf.metadata["verified_git_diff_summary"] == "1 file changed"
    assert verified_leaf.metadata["verified_test_commands"] == [
        "uv run pytest src/tests/unit/example.py"
    ]
    assert verified_leaf.feature_checkpoint is not None
    assert verified_leaf.feature_checkpoint.commit_ref == "abc123"
    events = list(
        (
            await db_session.execute(
                select(WorkspacePlanEventModel)
                .where(WorkspacePlanEventModel.plan_id == plan.id)
                .order_by(WorkspacePlanEventModel.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    assert [event.event_type for event in events] == [
        "worker_report_terminal",
        "verification_completed",
    ]
    assert events[0].actor_id == "worker-agent"
    assert events[1].payload_json["passed"] is True

    projected_task = await SqlWorkspaceTaskRepository(db_session).find_by_id(task.id)
    assert projected_task is not None
    assert projected_task.status.value == "done"
    assert projected_task.metadata["pending_leader_adjudication"] is False
    assert projected_task.metadata["durable_plan_verdict"] == "accepted"
    assert projected_task.metadata["last_worker_report_type"] == "completed"
    assert projected_task.metadata["last_attempt_status"] == "accepted"
    assert projected_task.metadata["last_attempt_id"] == leaf.current_attempt_id
    assert projected_task.metadata["last_leader_adjudication_status"] == "accepted"
    assert projected_task.metadata["feature_checkpoint"]["commit_ref"] == "abc123"
    assert projected_task.metadata["handoff_package"]["git_head"] == "abc123"
    assert projected_task.metadata["handoff_package"]["git_diff_summary"] == "1 file changed"
    assert projected_task.metadata["handoff_package"]["test_commands"] == [
        "uv run pytest src/tests/unit/example.py"
    ]
    assert projected_task.metadata["progress_events"][-1]["event_type"] == ("verification_accepted")
    assert "Commit: abc123" in projected_task.metadata["next_session_briefing"]
    reconciled_root = await SqlWorkspaceTaskRepository(db_session).find_by_id("root-task-1")
    assert reconciled_root is not None
    assert reconciled_root.metadata["goal_health"] == "achieved"
    assert reconciled_root.metadata["goal_progress_summary"] == (
        "1/1 child tasks done; 0 in progress; 0 blocked; 1/1 assigned"
    )
    assert reconciled_root.metadata["active_child_task_ids"] == []
    assert reconciled_root.metadata["blocked_child_task_ids"] == []
    attempt = await db_session.get(WorkspaceTaskSessionAttemptModel, leaf.current_attempt_id)
    assert attempt is not None
    assert attempt.status == "accepted"


@pytest.mark.asyncio
async def test_handoff_resume_handler_creates_fresh_attempt_and_worker_launch(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_workspace_only(db_session)
    orchestrator = build_sql_orchestrator(
        db_session,
        config=OrchestratorConfig(heartbeat_seconds=3600),
    )
    plan = await orchestrator.start_goal(
        workspace_id="workspace-1",
        title="Ship a resumable durable plan",
        start_supervisor=False,
    )
    await SqlWorkspacePlanOutboxRepository(db_session).enqueue(
        plan_id=plan.id,
        workspace_id="workspace-1",
        event_type=SUPERVISOR_TICK_EVENT,
        payload={
            "workspace_id": "workspace-1",
            "root_task_id": "root-task-1",
            "actor_user_id": "worker-user-1",
            "leader_agent_id": BUILTIN_SISYPHUS_ID,
        },
    )
    await db_session.commit()

    monkeypatch.setattr(
        "src.infrastructure.agent.workspace.worker_launch.schedule_worker_session",
        lambda **_kwargs: None,
    )
    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={
            SUPERVISOR_TICK_EVENT: make_supervisor_tick_handler(
                config=OrchestratorConfig(heartbeat_seconds=3600),
            ),
            WORKER_LAUNCH_EVENT: make_worker_launch_handler(worktree_preparer=_noop_worktree),
        },
        worker_id="worker-a",
    )
    assert await worker.run_once() == 1
    assert await worker.run_once() == 1

    db_session.expire_all()
    dispatched = await SqlPlanRepository(db_session).get(plan.id)
    assert dispatched is not None
    leaf = dispatched.leaf_tasks()[0]
    assert leaf.workspace_task_id is not None
    assert leaf.current_attempt_id is not None
    previous_attempt_id = leaf.current_attempt_id

    task_row = await db_session.get(WorkspaceTaskModel, leaf.workspace_task_id)
    assert task_row is not None
    task_row.status = "blocked"
    task_row.metadata_json = {
        **dict(task_row.metadata_json or {}),
        "evidence_refs": ["commit_ref:abc123", "changed_file:src/example.py"],
        "execution_verifications": ["test_run:uv run pytest src/tests/unit/example.py"],
        "last_worker_report_type": "blocked",
        "last_worker_report_summary": "lost process",
    }
    attempt_row = await db_session.get(WorkspaceTaskSessionAttemptModel, previous_attempt_id)
    assert attempt_row is not None
    attempt_row.status = "blocked"
    await SqlWorkspacePlanOutboxRepository(db_session).enqueue(
        plan_id=plan.id,
        workspace_id="workspace-1",
        event_type=HANDOFF_RESUME_EVENT,
        payload={
            "workspace_id": "workspace-1",
            "task_id": leaf.workspace_task_id,
            "node_id": leaf.id,
            "worker_agent_id": "worker-agent",
            "actor_user_id": "worker-user-1",
            "leader_agent_id": BUILTIN_SISYPHUS_ID,
            "previous_attempt_id": previous_attempt_id,
            "root_goal_task_id": "root-task-1",
            "summary": "resume after restart",
            "force_schedule": True,
        },
    )
    await db_session.commit()

    resume_worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={HANDOFF_RESUME_EVENT: make_handoff_resume_handler()},
        worker_id="worker-b",
    )
    assert await resume_worker.run_once() == 1

    db_session.expire_all()
    resume_items = list(
        (
            await db_session.execute(
                select(WorkspacePlanOutboxModel).where(
                    WorkspacePlanOutboxModel.event_type == HANDOFF_RESUME_EVENT
                )
            )
        )
        .scalars()
        .all()
    )
    assert resume_items[-1].status == "completed", resume_items[-1].last_error
    resumed = await SqlPlanRepository(db_session).get(plan.id)
    assert resumed is not None
    resumed_leaf = resumed.leaf_tasks()[0]
    assert resumed_leaf.current_attempt_id != previous_attempt_id
    assert resumed_leaf.handoff_package is not None
    assert resumed_leaf.handoff_package.git_head == "abc123"
    assert resumed_leaf.handoff_package.changed_files == ("src/example.py",)
    assert resumed_leaf.handoff_package.test_commands == (
        "uv run pytest src/tests/unit/example.py",
    )

    projected_task = await SqlWorkspaceTaskRepository(db_session).find_by_id(leaf.workspace_task_id)
    assert projected_task is not None
    assert projected_task.status.value == "in_progress"
    assert projected_task.metadata["handoff_package"]["summary"] == "resume after restart"
    assert projected_task.metadata[CURRENT_ATTEMPT_ID] == resumed_leaf.current_attempt_id

    launch_jobs = list(
        (
            await db_session.execute(
                select(WorkspacePlanOutboxModel)
                .where(WorkspacePlanOutboxModel.event_type == WORKER_LAUNCH_EVENT)
                .where(WorkspacePlanOutboxModel.status == "pending")
            )
        )
        .scalars()
        .all()
    )
    assert len(launch_jobs) == 1
    assert "[handoff-package]" in str(launch_jobs[0].payload_json["extra_instructions"])
    assert "previous_attempt_id" in str(launch_jobs[0].payload_json["extra_instructions"])


async def _noop_worktree(
    _session: AsyncSession,
    _workspace_id: str,
    _task: WorkspaceTask,
    _extra_instructions: str | None,
) -> str | None:
    return None


async def _seed_workspace_only(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            DBUser(
                id="worker-user-1",
                email="worker-user-1@example.com",
                full_name="Worker User",
                hashed_password="hash",
                is_active=True,
            ),
            DBTenant(
                id="worker-tenant-1",
                name="Worker Tenant",
                slug="worker-tenant",
                description="",
                owner_id="worker-user-1",
                plan="free",
                max_projects=10,
                max_users=10,
                max_storage=1,
            ),
            DBProject(
                id="worker-project-1",
                tenant_id="worker-tenant-1",
                name="Worker Project",
                description="",
                owner_id="worker-user-1",
                memory_rules={},
                graph_config={},
                sandbox_type="cloud",
                sandbox_config={},
                is_public=False,
            ),
            WorkspaceModel(
                id="workspace-1",
                tenant_id="worker-tenant-1",
                project_id="worker-project-1",
                name="Worker Workspace",
                description="",
                created_by="worker-user-1",
                is_archived=False,
                metadata_json={},
            ),
            WorkspaceMemberModel(
                id="workspace-member-1",
                workspace_id="workspace-1",
                user_id="worker-user-1",
                role="owner",
                invited_by="worker-user-1",
            ),
            AgentDefinitionModel(
                id=BUILTIN_SISYPHUS_ID,
                tenant_id="worker-tenant-1",
                project_id="worker-project-1",
                name="sisyphus",
                display_name="Sisyphus",
                system_prompt="You coordinate workspace execution.",
                allowed_tools=[],
                allowed_skills=[],
                allowed_mcp_servers=[],
            ),
            AgentDefinitionModel(
                id="worker-agent",
                tenant_id="worker-tenant-1",
                project_id="worker-project-1",
                name="worker-agent",
                display_name="Worker Agent",
                system_prompt="You execute workspace tasks.",
                allowed_tools=[],
                allowed_skills=[],
                allowed_mcp_servers=[],
            ),
            WorkspaceAgentModel(
                id="worker-binding-1",
                workspace_id="workspace-1",
                agent_id="worker-agent",
                display_name="Worker Agent",
                description=None,
                config_json={"capabilities": ["codegen"]},
                is_active=True,
            ),
            WorkspaceTaskModel(
                id="root-task-1",
                workspace_id="workspace-1",
                title="Root goal",
                description="Root goal for V2 dispatch",
                created_by="worker-user-1",
                status="todo",
                priority=0,
                metadata_json={
                    AUTONOMY_SCHEMA_VERSION_KEY: 1,
                    TASK_ROLE: "goal_root",
                    "goal_origin": "existing_root",
                    "goal_source_refs": [],
                    "root_goal_policy": {
                        "mutable_by_agent": False,
                        "completion_requires_external_proof": True,
                    },
                    "goal_health": "healthy",
                },
            ),
        ]
    )
    await db_session.flush()
