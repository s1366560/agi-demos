"""V2 application seam coverage for Agent graph management."""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.agent.runtime_bootstrapper import AgentRuntimeBootstrapper
from src.domain.model.agent.graph.agent_graph import AgentGraph
from src.domain.model.agent.graph.graph_pattern import GraphPattern
from src.domain.model.agent.graph.graph_run import GraphRun
from src.infrastructure.adapters.primary.web.routers.agent.agent_graph_router import (
    cancel_graph_run,
    create_graph,
    delete_graph,
    get_graph,
    get_graph_run,
    list_graph_runs,
    list_graphs,
    start_graph_run,
    update_graph,
)
from src.infrastructure.agent.orchestration.graph_orchestrator import GraphOrchestrator
from src.infrastructure.plugins.v2.agent_graph_management_services import (
    AGENT_GRAPH_MANAGEMENT_MODULE_V2,
    AgentGraphAccessDeniedV2,
    AgentGraphManagementRepositoriesV2,
    AgentGraphManagementServiceV2,
    AgentGraphProjectGrantV2,
    GenerationAgentGraphOrchestratorFactoryV2,
    SqlAgentGraphProjectAccessV2,
)
from src.infrastructure.plugins.v2.composer import load_profile_document_v2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"


class _ProjectAccess:
    def __init__(self, grant: AgentGraphProjectGrantV2) -> None:
        self.grant = grant
        self.require_access = AsyncMock(return_value=grant)


class _OrchestratorFactory:
    def __init__(self, orchestrator: object) -> None:
        self.orchestrator = orchestrator
        self.build = AsyncMock(return_value=orchestrator)


def _graph(*, tenant_id: str = "tenant-a", project_id: str = "project-a") -> AgentGraph:
    return AgentGraph(
        id="graph-a",
        tenant_id=tenant_id,
        project_id=project_id,
        name="Graph A",
        pattern=GraphPattern.SUPERVISOR,
    )


def _service(
    *,
    graph: AgentGraph | None = None,
    run: GraphRun | None = None,
) -> tuple[AgentGraphManagementServiceV2, SimpleNamespace, SimpleNamespace]:
    graph_repo = SimpleNamespace(
        find_by_id=AsyncMock(return_value=graph),
        list_by_project=AsyncMock(return_value=[]),
        save=AsyncMock(side_effect=lambda item: item),
        delete=AsyncMock(return_value=True),
    )
    run_repo = SimpleNamespace(
        find_by_id=AsyncMock(return_value=run),
        list_by_graph=AsyncMock(return_value=[]),
    )
    grant = AgentGraphProjectGrantV2(
        project_id="project-a",
        tenant_id="tenant-a",
        user_id="user-a",
        role="member",
    )
    project_access = _ProjectAccess(grant)
    orchestrator = SimpleNamespace(
        start_run=AsyncMock(),
        cancel_run=AsyncMock(),
    )
    db = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    service = AgentGraphManagementServiceV2(
        repositories=AgentGraphManagementRepositoriesV2(
            db=db,
            graph=graph_repo,
            run=run_repo,
            project_access=project_access,
        ),
        orchestrator_factory=_OrchestratorFactory(orchestrator),
    )
    return service, graph_repo, orchestrator


async def test_list_graphs_uses_exact_authorized_project_tenant() -> None:
    service, graph_repo, _orchestrator = _service()

    grant = await service.require_project_access(
        project_id="project-a",
        user_id="user-a",
    )
    graphs = await service.list_graphs(grant)

    assert graphs == []
    graph_repo.list_by_project.assert_awaited_once_with(
        tenant_id="tenant-a",
        project_id="project-a",
    )


async def test_create_graph_rejects_grant_scope_mismatch_before_persistence() -> None:
    service, graph_repo, _orchestrator = _service()
    grant = AgentGraphProjectGrantV2(
        project_id="project-a",
        tenant_id="tenant-a",
        user_id="user-a",
        role="member",
    )

    with pytest.raises(AgentGraphAccessDeniedV2):
        await service.create_graph(
            _graph(tenant_id="tenant-other"),
            grant=grant,
        )

    graph_repo.save.assert_not_awaited()


async def test_get_graph_requires_membership_in_the_graph_scope() -> None:
    service, _graph_repo, _orchestrator = _service(graph=_graph())
    service.repositories.project_access.require_access.side_effect = AgentGraphAccessDeniedV2(
        "project-a"
    )

    with pytest.raises(AgentGraphAccessDeniedV2):
        await service.get_graph(
            graph_id="graph-a",
            user_id="user-a",
        )


async def test_start_graph_run_authorizes_before_orchestration_and_commits() -> None:
    graph = _graph()
    run = GraphRun(
        id="run-a",
        graph_id=graph.id,
        conversation_id="conversation-a",
        tenant_id=graph.tenant_id,
        project_id=graph.project_id,
    )
    service, _graph_repo, orchestrator = _service(graph=graph)
    orchestrator.start_run.return_value = (run, [])

    result = await service.start_graph_run(
        graph_id=graph.id,
        expected_project_id=graph.project_id,
        conversation_id=run.conversation_id,
        user_id="user-a",
        initial_context={"request": "test"},
        parent_session_id=None,
        parent_agent_id=None,
    )

    assert result is run
    orchestrator.start_run.assert_awaited_once_with(
        graph_id=graph.id,
        conversation_id=run.conversation_id,
        tenant_id=graph.tenant_id,
        project_id=graph.project_id,
        initial_context={"request": "test"},
        parent_session_id="",
        parent_agent_id="__system__",
    )
    service.repositories.db.commit.assert_awaited_once()


async def test_project_write_access_rejects_a_read_only_role() -> None:
    result = SimpleNamespace(one_or_none=lambda: ("tenant-a", "viewer"))
    db = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    db.execute.return_value = result
    access = SqlAgentGraphProjectAccessV2(db=db)

    with pytest.raises(AgentGraphAccessDeniedV2):
        await access.require_access(
            project_id="project-a",
            user_id="user-a",
            required_roles=("owner", "admin", "member"),
        )


async def test_graph_orchestrator_factory_binds_the_generation_runtime() -> None:
    service, _graph_repo, _orchestrator = _service()
    runtime = SimpleNamespace(bind=AsyncMock(return_value=SimpleNamespace()))
    owner = object()
    bootstrapper = AgentRuntimeBootstrapper()
    factory = GenerationAgentGraphOrchestratorFactoryV2(
        runtime=runtime,
        owner=owner,
        bootstrapper=bootstrapper,
    )

    orchestrator = await factory.build(service.repositories)

    assert isinstance(orchestrator, GraphOrchestrator)
    assert runtime.bind.await_args.kwargs["owner"] is owner
    assert runtime.bind.await_args.kwargs["spawn_executor"].__self__ is bootstrapper
    assert runtime.bind.await_args.kwargs["session_turn_executor"].__self__ is bootstrapper


def test_agent_graph_module_is_an_explicit_profile_consumer() -> None:
    profile = load_profile_document_v2(_PROFILE_PATH)
    entry = next(
        entry for entry in profile.entries if entry.module_ref == AGENT_GRAPH_MANAGEMENT_MODULE_V2
    )

    assert entry.enabled is True
    assert entry.config == {"strategy": "operation-scoped-providers"}
    assert entry.inject == {
        "agent_orchestration": "service:agent.orchestration-runtime",
        "repositories": "service:persistence.agent-graph-repository-provider",
    }


def test_agent_graph_routes_have_no_static_container_lookup() -> None:
    for handler in (
        list_graphs,
        create_graph,
        get_graph,
        update_graph,
        delete_graph,
        start_graph_run,
        list_graph_runs,
        get_graph_run,
        cancel_graph_run,
    ):
        source = inspect.getsource(handler)
        assert "get_container_with_db" not in source
        assert "container." not in source
