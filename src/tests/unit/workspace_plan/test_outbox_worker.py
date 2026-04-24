"""Tests for the workspace plan outbox worker."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace_plan import PlanNode, TaskExecution, TaskIntent
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
    SUPERVISOR_TICK_EVENT,
    make_supervisor_tick_handler,
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
        config=OrchestratorConfig(enabled=True, heartbeat_seconds=3600),
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
                config=OrchestratorConfig(enabled=True, heartbeat_seconds=3600),
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
        config=OrchestratorConfig(enabled=True, heartbeat_seconds=3600),
    )
    plan = await orchestrator.start_goal(
        workspace_id="workspace-1",
        title="Ship a durable plan",
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

    launched: list[dict[str, object]] = []

    def fake_schedule_worker_session(**kwargs: object) -> None:
        launched.append(kwargs)

    monkeypatch.setattr(
        "src.infrastructure.agent.workspace.worker_launch.schedule_worker_session",
        fake_schedule_worker_session,
    )

    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={
            SUPERVISOR_TICK_EVENT: make_supervisor_tick_handler(
                config=OrchestratorConfig(enabled=True, heartbeat_seconds=3600),
            )
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
    root_task = await SqlWorkspaceTaskRepository(db_session).find_by_id("root-task-1")
    assert root_task is not None
    assert root_task.status.value == "in_progress"
    assert task.metadata[ROOT_GOAL_TASK_ID] == "root-task-1"
    assert task.metadata[WORKSPACE_PLAN_ID] == plan.id
    assert task.metadata[WORKSPACE_PLAN_NODE_ID] == leaf.id
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
        summary="Implemented the durable task and verified it.",
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
    attempt = await db_session.get(WorkspaceTaskSessionAttemptModel, leaf.current_attempt_id)
    assert attempt is not None
    assert attempt.status == "accepted"


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
