"""Generation-owned persistence and application seams for Agent graphs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.agent.runtime_bootstrapper import AgentRuntimeBootstrapper
from src.domain.events.agent_events import (
    GraphNodeStartedEvent,
    GraphRunCancelledEvent,
    GraphRunStartedEvent,
)
from src.domain.model.agent.graph.agent_graph import AgentGraph
from src.domain.model.agent.graph.graph_run import GraphRun
from src.domain.ports.repositories.graph_repository import (
    AgentGraphRepository,
    GraphRunRepository,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import Project, UserProject
from src.infrastructure.adapters.secondary.persistence.sql_graph_repository import (
    SqlAgentGraphRepository,
    SqlGraphRunRepository,
)
from src.infrastructure.agent.orchestration.graph_orchestrator import GraphOrchestrator

from .agent_orchestration_runtime import AgentOrchestrationRuntimeProtocolV2
from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

AGENT_GRAPH_REPOSITORY_PROVIDER_MODULE_V2 = (
    "builtin://memstack/persistence/agent-graph-repository-provider"
)
AGENT_GRAPH_REPOSITORY_PROVIDER_SERVICE_V2 = "service:persistence.agent-graph-repository-provider"
AGENT_GRAPH_MANAGEMENT_MODULE_V2 = "builtin://memstack/application/agent-graph-management"
AGENT_GRAPH_MANAGEMENT_SERVICE_V2 = "service:application.agent-graph-management"
AGENT_GRAPH_MANAGEMENT_REPOSITORIES_INJECT_V2 = "repositories"
AGENT_GRAPH_MANAGEMENT_ORCHESTRATION_INJECT_V2 = "agent_orchestration"
AGENT_GRAPH_WRITE_ROLES_V2 = ("owner", "admin", "member")

_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


class AgentGraphManagementErrorV2(RuntimeError):
    """Base failure for the Agent graph application seam."""


class AgentGraphNotFoundV2(AgentGraphManagementErrorV2):
    """The requested graph is absent from the exact authority scope."""


class AgentGraphRunNotFoundV2(AgentGraphManagementErrorV2):
    """The requested graph run is absent from the exact authority scope."""


class AgentGraphAccessDeniedV2(AgentGraphManagementErrorV2):
    """The current identity cannot access the requested graph scope."""


@dataclass(frozen=True, kw_only=True)
class AgentGraphProjectGrantV2:
    """Exact project membership used by one graph operation."""

    project_id: str
    tenant_id: str
    user_id: str
    role: str


@runtime_checkable
class AgentGraphProjectAccessProtocolV2(Protocol):
    async def require_access(
        self,
        *,
        project_id: str,
        user_id: str,
        tenant_id: str | None = None,
        required_roles: tuple[str, ...] | None = None,
    ) -> AgentGraphProjectGrantV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlAgentGraphProjectAccessV2:
    """Resolve one exact UserProject and Project tuple through the request session."""

    db: AsyncSession

    async def require_access(
        self,
        *,
        project_id: str,
        user_id: str,
        tenant_id: str | None = None,
        required_roles: tuple[str, ...] | None = None,
    ) -> AgentGraphProjectGrantV2:
        _require_identifier(project_id, field_name="project_id")
        _require_identifier(user_id, field_name="user_id")
        query = (
            select(Project.tenant_id, UserProject.role)
            .select_from(UserProject)
            .join(Project, UserProject.project_id == Project.id)
            .where(
                UserProject.user_id == user_id,
                UserProject.project_id == project_id,
            )
        )
        if tenant_id is not None:
            _require_identifier(tenant_id, field_name="tenant_id")
            query = query.where(Project.tenant_id == tenant_id)

        result = await self.db.execute(refresh_select_statement(query))
        row = result.one_or_none()
        if row is None:
            raise AgentGraphAccessDeniedV2(project_id)
        authorized_tenant_id = str(row[0])
        role = str(row[1])
        if required_roles is not None and role not in required_roles:
            raise AgentGraphAccessDeniedV2(project_id)
        return AgentGraphProjectGrantV2(
            project_id=project_id,
            tenant_id=authorized_tenant_id,
            user_id=user_id,
            role=role,
        )


@dataclass(frozen=True, kw_only=True)
class AgentGraphManagementRepositoriesV2:
    """Operation-owned persistence ports used by graph management."""

    db: AsyncSession
    graph: AgentGraphRepository
    run: GraphRunRepository
    project_access: AgentGraphProjectAccessProtocolV2


@runtime_checkable
class AgentGraphRepositoryFactoryProtocolV2(Protocol):
    def build(self, operation: OperationContextV2) -> AgentGraphManagementRepositoriesV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlAgentGraphRepositoryFactoryV2:
    """Create SQL graph adapters without exposing implementations to Consumers."""

    strategy: str

    def build(self, operation: OperationContextV2) -> AgentGraphManagementRepositoriesV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "Agent graph management requires an AsyncSession operation service",
            )
        return AgentGraphManagementRepositoriesV2(
            db=db,
            graph=SqlAgentGraphRepository(db),
            run=SqlGraphRunRepository(db),
            project_access=SqlAgentGraphProjectAccessV2(db=db),
        )


@runtime_checkable
class AgentGraphOrchestratorProtocolV2(Protocol):
    async def start_run(
        self,
        graph_id: str,
        conversation_id: str,
        tenant_id: str,
        project_id: str,
        *,
        initial_context: dict[str, Any] | None = None,
        parent_session_id: str = "",
        parent_agent_id: str = "__system__",
    ) -> tuple[GraphRun, list[GraphRunStartedEvent | GraphNodeStartedEvent]]: ...

    async def cancel_run(
        self,
        run_id: str,
        *,
        reason: str = "",
    ) -> tuple[GraphRun, list[GraphRunCancelledEvent]]: ...


@runtime_checkable
class AgentGraphOrchestratorFactoryProtocolV2(Protocol):
    async def build(
        self,
        repositories: AgentGraphManagementRepositoriesV2,
    ) -> AgentGraphOrchestratorProtocolV2: ...


@dataclass(frozen=True, kw_only=True)
class GenerationAgentGraphOrchestratorFactoryV2:
    """Bind graph execution to the exact generation's Agent orchestrator."""

    runtime: AgentOrchestrationRuntimeProtocolV2
    owner: object
    bootstrapper: AgentRuntimeBootstrapper

    async def build(
        self,
        repositories: AgentGraphManagementRepositoriesV2,
    ) -> AgentGraphOrchestratorProtocolV2:
        agent_orchestrator = await self.runtime.bind(
            owner=self.owner,
            spawn_executor=self.bootstrapper.launch_spawned_agent_session,
            session_turn_executor=self.bootstrapper.launch_agent_session_turn,
        )
        return GraphOrchestrator(
            agent_orchestrator=agent_orchestrator,
            graph_repo=repositories.graph,
            run_repo=repositories.run,
        )


@dataclass(frozen=True, kw_only=True)
class AgentGraphAccessV2:
    graph: AgentGraph
    grant: AgentGraphProjectGrantV2


@dataclass(frozen=True, kw_only=True)
class AgentGraphRunAccessV2:
    run: GraphRun
    grant: AgentGraphProjectGrantV2


@runtime_checkable
class AgentGraphManagementServiceProtocolV2(Protocol):
    async def require_project_access(
        self,
        *,
        project_id: str,
        user_id: str,
        require_write: bool = False,
    ) -> AgentGraphProjectGrantV2: ...

    async def list_graphs(self, grant: AgentGraphProjectGrantV2) -> list[AgentGraph]: ...

    async def create_graph(
        self,
        graph: AgentGraph,
        *,
        grant: AgentGraphProjectGrantV2,
    ) -> AgentGraph: ...

    async def get_graph(
        self,
        *,
        graph_id: str,
        user_id: str,
        require_write: bool = False,
    ) -> AgentGraphAccessV2: ...

    async def update_graph(self, access: AgentGraphAccessV2) -> AgentGraph: ...

    async def delete_graph(self, access: AgentGraphAccessV2) -> None: ...

    async def start_graph_run(
        self,
        *,
        graph_id: str,
        expected_project_id: str,
        conversation_id: str,
        user_id: str,
        initial_context: dict[str, Any],
        parent_session_id: str | None,
        parent_agent_id: str | None,
    ) -> GraphRun: ...

    async def list_graph_runs(
        self,
        *,
        graph_id: str,
        user_id: str,
    ) -> list[GraphRun]: ...

    async def get_graph_run(
        self,
        *,
        run_id: str,
        user_id: str,
        require_write: bool = False,
    ) -> AgentGraphRunAccessV2: ...

    async def cancel_graph_run(
        self,
        access: AgentGraphRunAccessV2,
        *,
        reason: str,
    ) -> GraphRun: ...


@dataclass(frozen=True, kw_only=True)
class AgentGraphManagementServiceV2:
    """Operation-owned authorization, persistence, and run orchestration surface."""

    repositories: AgentGraphManagementRepositoriesV2
    orchestrator_factory: AgentGraphOrchestratorFactoryProtocolV2

    async def require_project_access(
        self,
        *,
        project_id: str,
        user_id: str,
        require_write: bool = False,
    ) -> AgentGraphProjectGrantV2:
        return await self.repositories.project_access.require_access(
            project_id=project_id,
            user_id=user_id,
            required_roles=AGENT_GRAPH_WRITE_ROLES_V2 if require_write else None,
        )

    async def list_graphs(self, grant: AgentGraphProjectGrantV2) -> list[AgentGraph]:
        return await self.repositories.graph.list_by_project(
            tenant_id=grant.tenant_id,
            project_id=grant.project_id,
        )

    async def create_graph(
        self,
        graph: AgentGraph,
        *,
        grant: AgentGraphProjectGrantV2,
    ) -> AgentGraph:
        _ensure_graph_matches_grant(graph, grant)
        _ensure_valid_graph(graph)
        saved = await self.repositories.graph.save(graph)
        await self.repositories.db.commit()
        return saved

    async def get_graph(
        self,
        *,
        graph_id: str,
        user_id: str,
        require_write: bool = False,
    ) -> AgentGraphAccessV2:
        _require_identifier(graph_id, field_name="graph_id")
        graph = await self.repositories.graph.find_by_id(graph_id)
        if graph is None:
            raise AgentGraphNotFoundV2(graph_id)
        grant = await self.repositories.project_access.require_access(
            project_id=graph.project_id,
            tenant_id=graph.tenant_id,
            user_id=user_id,
            required_roles=AGENT_GRAPH_WRITE_ROLES_V2 if require_write else None,
        )
        _ensure_graph_matches_grant(graph, grant)
        return AgentGraphAccessV2(graph=graph, grant=grant)

    async def update_graph(self, access: AgentGraphAccessV2) -> AgentGraph:
        _ensure_graph_matches_grant(access.graph, access.grant)
        _ensure_valid_graph(access.graph)
        saved = await self.repositories.graph.save(access.graph)
        await self.repositories.db.commit()
        return saved

    async def delete_graph(self, access: AgentGraphAccessV2) -> None:
        _ensure_graph_matches_grant(access.graph, access.grant)
        _ = await self.repositories.graph.delete(access.graph.id)
        await self.repositories.db.commit()

    async def start_graph_run(
        self,
        *,
        graph_id: str,
        expected_project_id: str,
        conversation_id: str,
        user_id: str,
        initial_context: dict[str, Any],
        parent_session_id: str | None,
        parent_agent_id: str | None,
    ) -> GraphRun:
        access = await self.get_graph(
            graph_id=graph_id,
            user_id=user_id,
            require_write=True,
        )
        if access.graph.project_id != expected_project_id:
            raise AgentGraphNotFoundV2(graph_id)
        orchestrator = await self.orchestrator_factory.build(self.repositories)
        run, _events = await orchestrator.start_run(
            graph_id=graph_id,
            conversation_id=conversation_id,
            tenant_id=access.graph.tenant_id,
            project_id=expected_project_id,
            initial_context=initial_context,
            parent_session_id=parent_session_id or "",
            parent_agent_id=parent_agent_id or "__system__",
        )
        await self.repositories.db.commit()
        return run

    async def list_graph_runs(
        self,
        *,
        graph_id: str,
        user_id: str,
    ) -> list[GraphRun]:
        access = await self.get_graph(graph_id=graph_id, user_id=user_id)
        return await self.repositories.run.list_by_graph(access.graph.id)

    async def get_graph_run(
        self,
        *,
        run_id: str,
        user_id: str,
        require_write: bool = False,
    ) -> AgentGraphRunAccessV2:
        _require_identifier(run_id, field_name="run_id")
        run = await self.repositories.run.find_by_id(run_id)
        if run is None:
            raise AgentGraphRunNotFoundV2(run_id)
        grant = await self.repositories.project_access.require_access(
            project_id=run.project_id,
            tenant_id=run.tenant_id,
            user_id=user_id,
            required_roles=AGENT_GRAPH_WRITE_ROLES_V2 if require_write else None,
        )
        _ensure_run_matches_grant(run, grant)
        return AgentGraphRunAccessV2(run=run, grant=grant)

    async def cancel_graph_run(
        self,
        access: AgentGraphRunAccessV2,
        *,
        reason: str,
    ) -> GraphRun:
        _ensure_run_matches_grant(access.run, access.grant)
        orchestrator = await self.orchestrator_factory.build(self.repositories)
        run, _events = await orchestrator.cancel_run(access.run.id, reason=reason)
        _ensure_run_matches_grant(run, access.grant)
        await self.repositories.db.commit()
        return run


@runtime_checkable
class AgentGraphManagementResolverProtocolV2(Protocol):
    def resolve(self, operation: OperationContextV2) -> AgentGraphManagementServiceProtocolV2: ...


@dataclass(frozen=True, kw_only=True)
class AgentGraphManagementResolverV2:
    repositories: AgentGraphRepositoryFactoryProtocolV2
    agent_orchestration: AgentOrchestrationRuntimeProtocolV2
    bootstrapper: AgentRuntimeBootstrapper

    def resolve(self, operation: OperationContextV2) -> AgentGraphManagementServiceV2:
        repositories = self.repositories.build(operation)
        return AgentGraphManagementServiceV2(
            repositories=repositories,
            orchestrator_factory=GenerationAgentGraphOrchestratorFactoryV2(
                runtime=self.agent_orchestration,
                owner=self,
                bootstrapper=self.bootstrapper,
            ),
        )


def _apply_agent_graph_repository_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "request-async-session":
        raise ValueError("Agent graph repository Provider requires strategy request-async-session")
    _ = context.provide(
        AGENT_GRAPH_REPOSITORY_PROVIDER_SERVICE_V2,
        SqlAgentGraphRepositoryFactoryV2(strategy=strategy),
        label="agent-graph-repository-provider",
    )


def _apply_agent_graph_management_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-providers":
        raise ValueError("Agent graph management requires strategy operation-scoped-providers")
    repositories = context.require(AGENT_GRAPH_MANAGEMENT_REPOSITORIES_INJECT_V2)
    if not isinstance(repositories, AgentGraphRepositoryFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_agent_graph_repository_provider",
            "Agent graph management repository Provider has an invalid implementation",
        )
    agent_orchestration = context.require(AGENT_GRAPH_MANAGEMENT_ORCHESTRATION_INJECT_V2)
    if not isinstance(agent_orchestration, AgentOrchestrationRuntimeProtocolV2):
        raise RuntimeV2Error(
            "invalid_agent_graph_orchestration_runtime",
            "Agent graph management orchestration runtime has an invalid implementation",
        )
    _ = context.provide(
        AGENT_GRAPH_MANAGEMENT_SERVICE_V2,
        AgentGraphManagementResolverV2(
            repositories=repositories,
            agent_orchestration=agent_orchestration,
            bootstrapper=AgentRuntimeBootstrapper(),
        ),
        label="agent-graph-management",
    )


def agent_graph_management_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return the graph persistence Provider and application Consumer."""
    return (
        PluginDefinitionV2(
            module_ref=AGENT_GRAPH_REPOSITORY_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(AGENT_GRAPH_REPOSITORY_PROVIDER_MODULE_V2),
            apply=_apply_agent_graph_repository_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=AGENT_GRAPH_MANAGEMENT_MODULE_V2,
            contract_digest=generated_contract_digest_v2(AGENT_GRAPH_MANAGEMENT_MODULE_V2),
            apply=_apply_agent_graph_management_v2,
        ),
    )


def _require_identifier(value: str, *, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


def _ensure_graph_matches_grant(
    graph: AgentGraph,
    grant: AgentGraphProjectGrantV2,
) -> None:
    if graph.project_id != grant.project_id or graph.tenant_id != grant.tenant_id:
        raise AgentGraphAccessDeniedV2(graph.id)


def _ensure_run_matches_grant(
    run: GraphRun,
    grant: AgentGraphProjectGrantV2,
) -> None:
    if run.project_id != grant.project_id or run.tenant_id != grant.tenant_id:
        raise AgentGraphAccessDeniedV2(run.id)


def _ensure_valid_graph(graph: AgentGraph) -> None:
    if graph.validate_graph():
        raise ValueError("invalid agent graph definition")


__all__ = [
    "AGENT_GRAPH_MANAGEMENT_MODULE_V2",
    "AGENT_GRAPH_MANAGEMENT_ORCHESTRATION_INJECT_V2",
    "AGENT_GRAPH_MANAGEMENT_REPOSITORIES_INJECT_V2",
    "AGENT_GRAPH_MANAGEMENT_SERVICE_V2",
    "AGENT_GRAPH_REPOSITORY_PROVIDER_MODULE_V2",
    "AGENT_GRAPH_REPOSITORY_PROVIDER_SERVICE_V2",
    "AGENT_GRAPH_WRITE_ROLES_V2",
    "AgentGraphAccessDeniedV2",
    "AgentGraphAccessV2",
    "AgentGraphManagementErrorV2",
    "AgentGraphManagementRepositoriesV2",
    "AgentGraphManagementResolverProtocolV2",
    "AgentGraphManagementResolverV2",
    "AgentGraphManagementServiceProtocolV2",
    "AgentGraphManagementServiceV2",
    "AgentGraphNotFoundV2",
    "AgentGraphOrchestratorFactoryProtocolV2",
    "AgentGraphOrchestratorProtocolV2",
    "AgentGraphProjectAccessProtocolV2",
    "AgentGraphProjectGrantV2",
    "AgentGraphRepositoryFactoryProtocolV2",
    "AgentGraphRunAccessV2",
    "AgentGraphRunNotFoundV2",
    "GenerationAgentGraphOrchestratorFactoryV2",
    "SqlAgentGraphProjectAccessV2",
    "SqlAgentGraphRepositoryFactoryV2",
    "agent_graph_management_definitions_v2",
]
