"""Tests for durable V2 plan kickoff — see ``goal_runtime/v2_bridge.py``."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace_plan import PlanNode, TaskExecution, TaskIntent
from src.domain.ports.services.task_allocator_port import Allocation, WorkspaceAgent
from src.infrastructure.adapters.primary.web.routers import workspace_plans
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    Project as DBProject,
    Tenant as DBTenant,
    User as DBUser,
    WorkspaceModel,
    WorkspacePlanOutboxModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_plan_repository import SqlPlanRepository
from src.infrastructure.agent.subagent.task_decomposer import DecompositionResult, SubTask
from src.infrastructure.agent.workspace.goal_runtime import v2_bridge
from src.infrastructure.agent.workspace.goal_runtime.v2_bridge import (
    kickoff_v2_plan,
    reset_orchestrator_singleton_for_testing,
    set_orchestrator_singleton_for_testing,
)
from src.infrastructure.agent.workspace_plan.orchestrator import OrchestratorConfig
from src.infrastructure.agent.workspace_plan.outbox_handlers import (
    SUPERVISOR_TICK_EVENT,
    make_supervisor_tick_handler,
)
from src.infrastructure.agent.workspace_plan.outbox_worker import WorkspacePlanOutboxWorker


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    reset_orchestrator_singleton_for_testing()
    yield
    reset_orchestrator_singleton_for_testing()


def test_workspace_decomposer_max_subtasks_defaults_to_v2_orchestrator_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WORKSPACE_V2_MAX_SUBTASKS", raising=False)

    assert v2_bridge._workspace_decomposer_max_subtasks() == 8


def test_workspace_decomposer_max_subtasks_reads_v2_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSPACE_V2_MAX_SUBTASKS", "6")

    assert v2_bridge._workspace_decomposer_max_subtasks() == 6


def test_workspace_decomposer_max_subtasks_bounds_invalid_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSPACE_V2_MAX_SUBTASKS", "not-an-int")
    assert v2_bridge._workspace_decomposer_max_subtasks() == 8

    monkeypatch.setenv("WORKSPACE_V2_MAX_SUBTASKS", "99")
    assert v2_bridge._workspace_decomposer_max_subtasks() == 12


def test_workspace_decomposer_min_subtasks_defaults_to_one_for_general(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WORKSPACE_V2_SOFTWARE_MIN_SUBTASKS", raising=False)

    assert (
        v2_bridge._workspace_decomposer_min_subtasks(
            root_metadata={},
            workspace_metadata={},
            max_subtasks=8,
        )
        == 1
    )


def test_workspace_decomposer_min_subtasks_uses_software_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_metadata = {"workspace_type": "software_development"}
    monkeypatch.delenv("WORKSPACE_V2_SOFTWARE_MIN_SUBTASKS", raising=False)
    assert (
        v2_bridge._workspace_decomposer_min_subtasks(
            root_metadata=root_metadata,
            workspace_metadata={},
            max_subtasks=8,
        )
        == 6
    )

    monkeypatch.setenv("WORKSPACE_V2_SOFTWARE_MIN_SUBTASKS", "4")
    assert (
        v2_bridge._workspace_decomposer_min_subtasks(
            root_metadata=root_metadata,
            workspace_metadata={},
            max_subtasks=8,
        )
        == 4
    )

    monkeypatch.setenv("WORKSPACE_V2_SOFTWARE_MIN_SUBTASKS", "not-an-int")
    assert (
        v2_bridge._workspace_decomposer_min_subtasks(
            root_metadata=root_metadata,
            workspace_metadata={},
            max_subtasks=8,
        )
        == 6
    )

    monkeypatch.setenv("WORKSPACE_V2_SOFTWARE_MIN_SUBTASKS", "99")
    assert (
        v2_bridge._workspace_decomposer_min_subtasks(
            root_metadata=root_metadata,
            workspace_metadata={},
            max_subtasks=8,
        )
        == 8
    )


async def _seed_workspace(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            DBUser(
                id="bridge-user-1",
                email="bridge-user-1@example.com",
                full_name="Bridge User",
                hashed_password="hash",
                is_active=True,
            ),
            DBTenant(
                id="bridge-tenant-1",
                name="Bridge Tenant",
                slug="bridge-tenant",
                description="",
                owner_id="bridge-user-1",
                plan="free",
                max_projects=10,
                max_users=10,
                max_storage=1,
            ),
            DBProject(
                id="bridge-project-1",
                tenant_id="bridge-tenant-1",
                name="Bridge Project",
                description="",
                owner_id="bridge-user-1",
                memory_rules={},
                graph_config={},
                sandbox_type="cloud",
                sandbox_config={},
                is_public=False,
            ),
            WorkspaceModel(
                id="ws-abc",
                tenant_id="bridge-tenant-1",
                project_id="bridge-project-1",
                name="Bridge Workspace",
                description="",
                created_by="bridge-user-1",
                is_archived=False,
                metadata_json={},
            ),
        ]
    )
    await db_session.flush()


def _patch_session_factory(db_session: AsyncSession):
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    return patch.object(v2_bridge, "async_session_factory", factory)


class _WorkspaceServiceStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def get_workspace(self, *, workspace_id: str, actor_user_id: str) -> object:
        self.calls.append((workspace_id, actor_user_id))
        return object()


class _FakeDecomposer:
    async def decompose(
        self,
        query: str,
        conversation_context: str | None = None,
    ) -> DecompositionResult:
        return DecompositionResult(
            subtasks=(
                SubTask(id="api", description="Define API contract"),
                SubTask(
                    id="tests",
                    description="Write tests for the API contract",
                    dependencies=("api",),
                ),
            ),
            reasoning=f"query={query}; context={conversation_context}",
            is_decomposed=True,
        )


async def test_kickoff_creates_plan_with_injected_orchestrator() -> None:
    from src.infrastructure.agent.workspace_plan import build_default_orchestrator

    orchestrator = build_default_orchestrator()
    set_orchestrator_singleton_for_testing(orchestrator)

    started = await kickoff_v2_plan(
        workspace_id="ws-abc",
        title="Build a CRUD blog",
        description="Ship the first vertical slice",
        created_by="user-42",
    )

    assert started is True
    plan = await orchestrator._repo.get_by_workspace("ws-abc")
    assert plan is not None
    goal_node = plan.nodes[plan.goal_id]
    assert goal_node.title == "Build a CRUD blog"


async def test_kickoff_creates_durable_plan_and_outbox(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace(db_session)

    with _patch_session_factory(db_session):
        started = await kickoff_v2_plan(
            workspace_id="ws-abc",
            title="Build a CRUD blog",
            description="Ship the first vertical slice",
            created_by="bridge-user-1",
            root_task_id="root-bridge-1",
        )

    assert started is True
    plan = await SqlPlanRepository(db_session).get_by_workspace("ws-abc")
    assert plan is not None
    goal_node = plan.nodes[plan.goal_id]
    assert goal_node.title == "Build a CRUD blog"

    result = await db_session.execute(refresh_select_statement(select(WorkspacePlanOutboxModel)))
    outbox_items = list(result.scalars().all())
    assert len(outbox_items) == 1
    assert outbox_items[0].plan_id == plan.id
    assert outbox_items[0].workspace_id == "ws-abc"
    assert outbox_items[0].event_type == "supervisor_tick"
    assert outbox_items[0].status == "pending"
    assert outbox_items[0].payload_json == {
        "workspace_id": "ws-abc",
        "root_task_id": "root-bridge-1",
        "actor_user_id": "bridge-user-1",
        "leader_agent_id": None,
    }
    assert outbox_items[0].metadata_json == {"source": "v2_bridge"}


async def test_kickoff_uses_workspace_decomposer_to_create_dag(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace(db_session)

    with (
        _patch_session_factory(db_session),
        patch.object(
            v2_bridge,
            "_build_workspace_task_decomposer",
            new=AsyncMock(return_value=_FakeDecomposer()),
        ) as decomposer_builder,
    ):
        started = await kickoff_v2_plan(
            workspace_id="ws-abc",
            title="Build a typed feature flag utility",
            description="Plan API contract, implementation, tests, and review as a DAG.",
            created_by="bridge-user-1",
            root_task_id="root-bridge-1",
        )

    assert started is True
    decomposer_builder.assert_awaited_once()
    plan = await SqlPlanRepository(db_session).get_by_workspace("ws-abc")
    assert plan is not None
    task_nodes = plan.leaf_tasks()
    assert len(task_nodes) == 2
    assert sum(len(node.depends_on) for node in task_nodes) == 1


async def test_kickoff_worker_and_snapshot_api_flow_end_to_end(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_workspace(db_session)

    with _patch_session_factory(db_session):
        await kickoff_v2_plan(
            workspace_id="ws-abc",
            title="Build a CRUD blog",
            description="Ship the first vertical slice",
            created_by="bridge-user-1",
            root_task_id="root-bridge-1",
        )

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

    @asynccontextmanager
    async def worker_session_factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    worker = WorkspacePlanOutboxWorker(
        session_factory=worker_session_factory,
        handlers={
            SUPERVISOR_TICK_EVENT: make_supervisor_tick_handler(
                config=OrchestratorConfig(heartbeat_seconds=3600),
                agent_pool=agent_pool,
                dispatcher=dispatcher,
            )
        },
        worker_id="bridge-worker",
    )

    assert await worker.run_once() == 1

    workspace_service = _WorkspaceServiceStub()
    monkeypatch.setattr(
        workspace_plans,
        "_get_workspace_service",
        lambda _request, _db: workspace_service,
    )

    snapshot = await workspace_plans.get_workspace_plan_snapshot(
        workspace_id="ws-abc",
        request=cast(Request, SimpleNamespace()),
        outbox_limit=10,
        event_limit=10,
        current_user=cast(DBUser, SimpleNamespace(id="bridge-user-1")),
        db=db_session,
    )

    assert workspace_service.calls == [("ws-abc", "bridge-user-1")]
    assert snapshot.plan is not None
    leaf_nodes = [node for node in snapshot.plan.nodes if node.kind in {"task", "verify"}]
    assert leaf_nodes
    dispatched_nodes = [
        node for node in leaf_nodes if node.execution == TaskExecution.DISPATCHED.value
    ]
    assert dispatched_nodes
    assert all(node.intent == TaskIntent.IN_PROGRESS.value for node in dispatched_nodes)
    assert all(node.assignee_agent_id == "agent-1" for node in dispatched_nodes)
    assert set(dispatched) == {("agent-1", node.id) for node in dispatched_nodes}
    assert snapshot.outbox[0].event_type == SUPERVISOR_TICK_EVENT
    assert snapshot.outbox[0].status == "completed"


async def test_kickoff_swallows_orchestrator_failures() -> None:
    with (
        patch.object(v2_bridge, "build_sql_orchestrator", side_effect=RuntimeError("boom")),
    ):
        started = await kickoff_v2_plan(workspace_id="ws-x", title="T", description="", created_by="")

    assert started is False
