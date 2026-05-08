"""Tests for durable V2 plan kickoff — see ``goal_runtime/v2_bridge.py``."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import TenantAgentConfig
from src.domain.model.workspace_plan import PlanNode, PlanStatus, TaskExecution, TaskIntent
from src.domain.ports.services.task_allocator_port import Allocation, WorkspaceAgent
from src.infrastructure.adapters.primary.web.routers import workspace_plans
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    Project as DBProject,
    Tenant as DBTenant,
    User as DBUser,
    WorkspaceModel,
    WorkspacePlanEventModel,
    WorkspacePlanOutboxModel,
    WorkspaceTaskModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_plan_repository import SqlPlanRepository
from src.infrastructure.agent.core.react_agent_profile import AgentRuntimeProfile
from src.infrastructure.agent.core.react_agent_tool_policy import (
    with_workspace_worker_tool_allowlist,
)
from src.infrastructure.agent.sisyphus.builtin_agent import build_builtin_workspace_planner_agent
from src.infrastructure.agent.subagent.task_decomposer import DecompositionResult, SubTask
from src.infrastructure.agent.tools import workspace_planning_contract as planning_contract_tools
from src.infrastructure.agent.tools.workspace_planning_contract import (
    WORKSPACE_SUBMIT_PLANNING_CONTRACT_TOOL_NAME,
)
from src.infrastructure.agent.workspace.goal_runtime import v2_bridge
from src.infrastructure.agent.workspace.goal_runtime.v2_bridge import (
    kickoff_v2_plan,
    reset_orchestrator_singleton_for_testing,
    set_orchestrator_singleton_for_testing,
)
from src.infrastructure.agent.workspace.planner_agent_decomposer import (
    WorkspacePlannerAgentDecomposer,
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


def test_workspace_decomposer_max_subtasks_uses_software_iteration_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WORKSPACE_V2_SOFTWARE_MAX_SUBTASKS", raising=False)

    assert (
        v2_bridge._workspace_decomposer_max_subtasks(
            root_metadata={"workspace_type": "software_development"},
            workspace_metadata={},
        )
        == 6
    )

    monkeypatch.setenv("WORKSPACE_V2_SOFTWARE_MAX_SUBTASKS", "5")
    assert (
        v2_bridge._workspace_decomposer_max_subtasks(
            root_metadata={"workspace_type": "software_development"},
            workspace_metadata={},
        )
        == 5
    )


def test_workspace_decomposer_max_subtasks_bounds_invalid_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKSPACE_V2_MAX_SUBTASKS", "not-an-int")
    assert v2_bridge._workspace_decomposer_max_subtasks() == 8

    monkeypatch.setenv("WORKSPACE_V2_MAX_SUBTASKS", "99")
    assert v2_bridge._workspace_decomposer_max_subtasks() == 12


def test_builtin_workspace_planner_worker_profile_keeps_read_only_contract_tools() -> None:
    planner = build_builtin_workspace_planner_agent(tenant_id="tenant-1", project_id="project-1")
    profile = AgentRuntimeProfile(
        selected_agent=planner,
        tenant_agent_config=TenantAgentConfig.create_default("tenant-1"),
        available_skills=[],
        allow_tools=list(planner.allowed_tools),
        deny_tools=[],
        effective_model="default",
        effective_temperature=0.0,
        effective_max_tokens=8192,
        effective_max_steps=12,
    )

    scoped = with_workspace_worker_tool_allowlist(profile)

    assert set(scoped.allow_tools) == {
        "read",
        "grep",
        "glob",
        "bash",
        WORKSPACE_SUBMIT_PLANNING_CONTRACT_TOOL_NAME,
    }
    assert "write" not in scoped.allow_tools
    assert "edit" not in scoped.allow_tools
    assert "todoread" not in scoped.allow_tools
    assert "workspace_report_complete" not in scoped.allow_tools


@pytest.mark.asyncio
async def test_workspace_planner_agent_decomposer_adds_iteration_context() -> None:
    captured: dict[str, Any] = {}

    class _PlannerLLM:
        async def generate(self, **kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return _planner_tool_response(
                subtasks=[{"id": "research", "description": "Research"}],
                services=[],
            )

    decomposer = WorkspacePlannerAgentDecomposer(
        llm_client=cast(Any, _PlannerLLM()),
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id="ws-1",
        extra_context="Software workspace planning contract",
    )

    await decomposer.decompose(query="Ship feature", conversation_context="Existing context")

    prompt = captured["messages"][1]["content"]
    assert "builtin workspace planner contract" in prompt
    assert "Software workspace planning contract" in prompt
    assert "Existing context" in prompt


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


async def test_build_workspace_task_decomposer_uses_builtin_planner_agent(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_workspace(db_session)
    _patch_planner_llm(monkeypatch)

    decomposer = await v2_bridge._build_workspace_task_decomposer(
        db_session,
        "ws-abc",
        root_task_id="root-bridge-1",
        extra_context="Software workspace planning contract",
    )

    assert isinstance(decomposer, WorkspacePlannerAgentDecomposer)


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


def _planner_tool_response(
    *,
    subtasks: list[dict[str, Any]] | None = None,
    services: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = {
        "task_graph": {
            "subtasks": subtasks
            or [
                {"id": "api", "description": "Define API contract", "priority": 10},
                {
                    "id": "tests",
                    "description": "Write tests for the API contract",
                    "depends_on": ["api"],
                    "priority": 5,
                },
            ]
        },
        "delivery_cicd": {
            "auto_deploy": True,
            "services": services
            if services is not None
            else [
                {
                    "service_id": "frontend",
                    "name": "Frontend",
                    "start_command": "npm run dev -- --host 0.0.0.0 --port 5173",
                    "internal_port": 5173,
                    "health_path": "/",
                    "required": True,
                    "auto_open": True,
                },
                {
                    "service_id": "backend",
                    "name": "Backend API",
                    "start_command": "uv run uvicorn app:app --host 0.0.0.0 --port 8000",
                    "internal_port": 8000,
                    "health_path": "/health",
                    "required": True,
                    "auto_open": False,
                },
            ],
        },
        "reasoning": "Planner read package and backend health route evidence.",
        "evidence_refs": ["read:package.json", "grep:backend health route"],
        "confidence": 0.91,
    }
    return {
        "tool_calls": [
            {
                "function": {
                    "name": "workspace_submit_planning_contract",
                    "arguments": json.dumps(payload),
                }
            }
        ]
    }


def _patch_planner_llm(monkeypatch: pytest.MonkeyPatch, *, response: dict[str, Any] | None = None):
    from src.infrastructure.llm import provider_factory

    class _FakePlannerLLM:
        async def generate(self, **_kwargs: Any) -> dict[str, Any]:
            return response or _planner_tool_response()

    class _FakePlannerTurnRunner:
        async def run_planning_turn(self, **_kwargs: Any) -> dict[str, Any]:
            raw_response = response or _planner_tool_response()
            arguments = json.loads(raw_response["tool_calls"][0]["function"]["arguments"])
            return planning_contract_tools.normalize_workspace_planning_contract(
                task_graph=arguments["task_graph"],
                delivery_cicd=arguments["delivery_cicd"],
                reasoning=arguments["reasoning"],
                evidence_refs=arguments["evidence_refs"],
                confidence=arguments["confidence"],
                actor_user_id="bridge-user-1",
            )

    class _FakeAIServiceFactory:
        async def resolve_provider(self, *_args: Any, **_kwargs: Any) -> object:
            return object()

        def create_unified_llm_client(self, *_args: Any, **_kwargs: Any) -> _FakePlannerLLM:
            return _FakePlannerLLM()

    monkeypatch.setattr(provider_factory, "AIServiceFactory", _FakeAIServiceFactory)
    monkeypatch.setattr(
        v2_bridge,
        "_build_workspace_planner_agent_turn_runner",
        lambda **_kwargs: _FakePlannerTurnRunner(),
    )


def _patch_planner_llm_with_turn_runner(
    monkeypatch: pytest.MonkeyPatch,
    *,
    turn_runner: object,
) -> None:
    from src.infrastructure.llm import provider_factory

    class _FakePlannerLLM:
        async def generate(self, **_kwargs: Any) -> dict[str, Any]:
            return _planner_tool_response()

    class _FakeAIServiceFactory:
        async def resolve_provider(self, *_args: Any, **_kwargs: Any) -> object:
            return object()

        def create_unified_llm_client(self, *_args: Any, **_kwargs: Any) -> _FakePlannerLLM:
            return _FakePlannerLLM()

    monkeypatch.setattr(provider_factory, "AIServiceFactory", _FakeAIServiceFactory)
    monkeypatch.setattr(
        v2_bridge,
        "_build_workspace_planner_agent_turn_runner",
        lambda **_kwargs: turn_runner,
    )


class _MissingContractTurnRunner:
    def __init__(self) -> None:
        self.calls: list[bool] = []
        self._last_diagnostics: dict[str, Any] = {}

    @property
    def last_diagnostics(self) -> dict[str, Any]:
        return dict(self._last_diagnostics)

    async def run_planning_turn(self, **kwargs: Any) -> dict[str, Any] | None:
        contract_only = bool(kwargs.get("contract_only", False))
        self.calls.append(contract_only)
        self._last_diagnostics = {
            "conversation_id": f"planner-turn-{len(self.calls)}",
            "contract_only": contract_only,
            "event_count": 3,
            "observed_tools": ["bash"],
            "evidence_summaries": ["bash: package.json and backend route were inspected"],
            "contract_submitted": False,
        }
        return None


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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_workspace(db_session)
    _patch_planner_llm(monkeypatch)
    monkeypatch.setattr(planning_contract_tools, "_publish_workspace_updated_event", AsyncMock())

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
    workspace = await db_session.get(WorkspaceModel, "ws-abc")
    assert workspace is not None
    delivery = dict((workspace.metadata_json or {}).get("delivery_cicd") or {})
    assert delivery["contract_source"] == "planner_agent_code_analysis"
    assert [service["service_id"] for service in delivery["services"]] == [
        "frontend",
        "backend",
    ]
    root_metadata = dict(plan.goal_node.metadata or {})
    assert root_metadata["decomposition_source"] == "planner_agent_code_analysis"
    assert root_metadata["planning_contract"]["evidence_refs"] == [
        "read:package.json",
        "grep:backend health route",
    ]


async def test_kickoff_suspends_software_workspace_when_planner_contract_missing(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_workspace(db_session)
    workspace = await db_session.get(WorkspaceModel, "ws-abc")
    assert workspace is not None
    workspace.metadata_json = {
        "workspace_type": "software_development",
        "code_context": {"sandbox_code_root": "/workspace/my-evo"},
    }
    await db_session.flush()
    runner = _MissingContractTurnRunner()
    _patch_planner_llm_with_turn_runner(monkeypatch, turn_runner=runner)

    with _patch_session_factory(db_session):
        started = await kickoff_v2_plan(
            workspace_id="ws-abc",
            title="Build frontend and backend",
            description="Ship the full-stack preview.",
            created_by="bridge-user-1",
            root_task_id="root-bridge-1",
        )

    assert started is True
    assert runner.calls == [False, True]
    plan = await SqlPlanRepository(db_session).get_by_workspace("ws-abc")
    assert plan is not None
    assert plan.status is PlanStatus.SUSPENDED
    assert plan.leaf_tasks() == []
    assert plan.goal_node.intent is TaskIntent.BLOCKED
    assert plan.goal_node.metadata["planner_contract_missing"] is True
    assert plan.goal_node.metadata["retry_count"] == 1

    outbox_items = (
        (await db_session.execute(select(WorkspacePlanOutboxModel))).scalars().all()
    )
    assert outbox_items == []
    events = (
        (
            await db_session.execute(
                select(WorkspacePlanEventModel).where(
                    WorkspacePlanEventModel.plan_id == plan.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert [event.event_type for event in events] == ["planner_contract_missing"]
    assert events[0].payload_json["failure_reason"].startswith("builtin workspace planner")


async def test_kickoff_passes_software_context_to_planner_for_pipeline_gate(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace(db_session)
    workspace = await db_session.get(WorkspaceModel, "ws-abc")
    assert workspace is not None
    workspace.metadata_json = {
        "workspace_type": "software_development",
        "workspace_use_case": "programming",
    }
    await db_session.flush()

    class _SprintDecomposer:
        async def decompose(
            self,
            query: str,
            conversation_context: str | None = None,
        ) -> DecompositionResult:
            return DecompositionResult(
                subtasks=(
                    SubTask(id="research", description="Research current state"),
                    SubTask(id="plan", description="Plan a bounded change"),
                    SubTask(id="implement", description="Implement the code change"),
                    SubTask(id="test", description="Run the verification pipeline"),
                ),
                reasoning=f"query={query}; context={conversation_context}",
                is_decomposed=True,
            )

    with (
        _patch_session_factory(db_session),
        patch.object(
            v2_bridge,
            "_build_workspace_task_decomposer",
            new=AsyncMock(return_value=_SprintDecomposer()),
        ) as decomposer_builder,
    ):
        started = await kickoff_v2_plan(
            workspace_id="ws-abc",
            title="Ship a software change",
            description="Run CI evidence before review",
            created_by="bridge-user-1",
            root_task_id="root-bridge-1",
        )

    assert started is True
    extra_context = decomposer_builder.await_args.kwargs["extra_context"]
    assert "Software workspace planning contract:" in extra_context
    plan = await SqlPlanRepository(db_session).get_by_workspace("ws-abc")
    assert plan is not None
    task_nodes = [node for node in plan.nodes.values() if node.parent_id == plan.goal_id]
    assert {
        node.metadata.get("iteration_phase"): node.metadata.get("pipeline_required")
        for node in task_nodes
    } == {
        "research": None,
        "plan": None,
        "implement": True,
        "test": True,
    }


async def test_kickoff_skips_duplicate_plan_for_completed_root(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_workspace(db_session)
    _patch_planner_llm(monkeypatch)
    monkeypatch.setattr(planning_contract_tools, "_publish_workspace_updated_event", AsyncMock())

    with _patch_session_factory(db_session):
        started = await kickoff_v2_plan(
            workspace_id="ws-abc",
            title="Build a CRUD blog",
            description="Ship the first vertical slice",
            created_by="bridge-user-1",
            root_task_id="root-bridge-1",
        )

    assert started is True
    repo = SqlPlanRepository(db_session)
    plan = await repo.get_by_workspace("ws-abc")
    assert plan is not None
    await repo.save(replace(plan, status=PlanStatus.COMPLETED))
    db_session.add(
        WorkspaceTaskModel(
            id="plan-child-task-1",
            workspace_id="ws-abc",
            title="Projected plan child",
            created_by="bridge-user-1",
            status="done",
            priority=0,
            metadata_json={
                "task_role": "execution_task",
                "root_goal_task_id": "root-bridge-1",
                "workspace_plan_id": plan.id,
                "workspace_plan_node_id": "node-1",
            },
        )
    )
    await db_session.execute(delete(WorkspacePlanOutboxModel))
    await db_session.flush()

    with (
        _patch_session_factory(db_session),
        patch.object(
            v2_bridge,
            "_build_workspace_task_decomposer",
            new=AsyncMock(return_value=_FakeDecomposer()),
        ) as decomposer_builder,
    ):
        duplicate_started = await kickoff_v2_plan(
            workspace_id="ws-abc",
            title="Build a CRUD blog",
            description="Ship the first vertical slice",
            created_by="bridge-user-1",
            root_task_id="root-bridge-1",
        )

    assert duplicate_started is True
    decomposer_builder.assert_not_awaited()
    plans = (
        (
            await db_session.execute(
                select(WorkspacePlanOutboxModel).order_by(WorkspacePlanOutboxModel.id)
            )
        )
        .scalars()
        .all()
    )
    assert plans == []


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
    _patch_planner_llm(monkeypatch)
    monkeypatch.setattr(planning_contract_tools, "_publish_workspace_updated_event", AsyncMock())

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
        started = await kickoff_v2_plan(
            workspace_id="ws-x", title="T", description="", created_by=""
        )

    assert started is False
