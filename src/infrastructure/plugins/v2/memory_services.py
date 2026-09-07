"""Generation-owned memory repository Provider and application Consumer seams."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.memory_service import MemoryService
from src.application.services.online_memory_commands import OnlineMemoryCommands
from src.application.services.search_service import SearchService
from src.application.use_cases.memory.create_memory import CreateMemoryUseCase
from src.application.use_cases.memory.delete_memory import DeleteMemoryUseCase
from src.application.use_cases.memory.get_memory import GetMemoryUseCase
from src.application.use_cases.memory.list_memories import ListMemoriesUseCase
from src.application.use_cases.memory.search_memory import SearchMemoryUseCase
from src.domain.ports.repositories.memory_repository import MemoryRepository
from src.domain.ports.repositories.online_memory_repository import OnlineMemoryRepository
from src.domain.ports.services.graph_store_port import GraphStorePort
from src.infrastructure.adapters.secondary.persistence.sql_memory_repository import (
    SqlMemoryRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_online_memory_repository import (
    SqlOnlineMemoryRepository,
)

from .graph_runtime import GraphRuntimeServiceV2
from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

MEMORY_REPOSITORY_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/memory-repository-provider"
MEMORY_REPOSITORY_PROVIDER_SERVICE_V2 = "service:persistence.memory-repository-provider"
MEMORY_APPLICATION_MODULE_V2 = "builtin://memstack/application/memory-services"
MEMORY_APPLICATION_SERVICE_V2 = "service:application.memory-services"
MEMORY_REPOSITORY_PROVIDER_INJECT_V2 = "repository_provider"
MEMORY_GRAPH_RUNTIME_INJECT_V2 = "graph_runtime"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


@dataclass(frozen=True, kw_only=True)
class MemoryApplicationServicesV2:
    """Complete request-session-owned memory application service set."""

    graph_service: GraphStorePort
    memory_repository: MemoryRepository
    online_commands: OnlineMemoryCommands
    memory_service: MemoryService
    search_service: SearchService
    create_memory_use_case: CreateMemoryUseCase
    get_memory_use_case: GetMemoryUseCase
    list_memories_use_case: ListMemoriesUseCase
    delete_memory_use_case: DeleteMemoryUseCase
    search_memory_use_case: SearchMemoryUseCase


@runtime_checkable
class MemoryRepositoryProviderProtocolV2(Protocol):
    """Consumer-visible repository factory hiding the SQL implementation."""

    def build(self, operation: OperationContextV2) -> MemoryRepository: ...

    def build_online(self, operation: OperationContextV2) -> OnlineMemoryRepository: ...


@runtime_checkable
class MemoryApplicationResolverProtocolV2(Protocol):
    """Application-facing resolver injected through the public service key."""

    def resolve(self, operation: OperationContextV2) -> MemoryApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlMemoryRepositoryProviderV2:
    """Build a memory repository from the exact operation AsyncSession."""

    strategy: str

    def build(self, operation: OperationContextV2) -> MemoryRepository:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "memory repository provider requires an AsyncSession operation service",
            )
        return SqlMemoryRepository(db)

    def build_online(self, operation: OperationContextV2) -> OnlineMemoryRepository:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "online memory provider requires an AsyncSession operation service",
            )
        return SqlOnlineMemoryRepository(db)


@dataclass(frozen=True, kw_only=True)
class MemoryApplicationResolverV2:
    """Compose memory services without exposing Provider implementations."""

    repository_provider: MemoryRepositoryProviderProtocolV2
    graph_runtime: GraphRuntimeServiceV2

    def resolve(self, operation: OperationContextV2) -> MemoryApplicationServicesV2:
        graph_service = self.graph_runtime.require()
        memory_repository = self.repository_provider.build(operation)
        return MemoryApplicationServicesV2(
            graph_service=graph_service,
            memory_repository=memory_repository,
            online_commands=OnlineMemoryCommands(self.repository_provider.build_online(operation)),
            memory_service=MemoryService(
                memory_repo=memory_repository,
                graph_service=graph_service,
            ),
            search_service=SearchService(
                graph_service=graph_service,
                memory_repo=memory_repository,
            ),
            create_memory_use_case=CreateMemoryUseCase(memory_repository, graph_service),
            get_memory_use_case=GetMemoryUseCase(memory_repository),
            list_memories_use_case=ListMemoriesUseCase(memory_repository),
            delete_memory_use_case=DeleteMemoryUseCase(memory_repository, graph_service),
            search_memory_use_case=SearchMemoryUseCase(graph_service),
        )


def _apply_memory_repository_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "request-async-session":
        raise ValueError("memory repository provider requires strategy request-async-session")
    _ = context.provide(
        MEMORY_REPOSITORY_PROVIDER_SERVICE_V2,
        SqlMemoryRepositoryProviderV2(strategy=strategy),
        label="memory-repository-provider",
    )


def _apply_memory_application_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "operation-scoped-provider":
        raise ValueError("memory application resolver requires strategy operation-scoped-provider")
    repository_provider = context.require(MEMORY_REPOSITORY_PROVIDER_INJECT_V2)
    if not isinstance(repository_provider, MemoryRepositoryProviderProtocolV2):
        raise RuntimeV2Error(
            "invalid_memory_repository_provider",
            "memory repository provider inject does not implement the factory contract",
        )
    graph_runtime = context.require(MEMORY_GRAPH_RUNTIME_INJECT_V2)
    if not isinstance(graph_runtime, GraphRuntimeServiceV2):
        raise RuntimeV2Error(
            "invalid_memory_graph_runtime",
            "memory graph runtime inject has an invalid implementation",
        )
    _ = context.provide(
        MEMORY_APPLICATION_SERVICE_V2,
        MemoryApplicationResolverV2(
            repository_provider=repository_provider,
            graph_runtime=graph_runtime,
        ),
        label="memory-application",
    )


def memory_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    return (
        PluginDefinitionV2(
            module_ref=MEMORY_REPOSITORY_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(MEMORY_REPOSITORY_PROVIDER_MODULE_V2),
            apply=_apply_memory_repository_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=MEMORY_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(MEMORY_APPLICATION_MODULE_V2),
            apply=_apply_memory_application_v2,
        ),
    )


__all__ = [
    "MEMORY_APPLICATION_MODULE_V2",
    "MEMORY_APPLICATION_SERVICE_V2",
    "MEMORY_GRAPH_RUNTIME_INJECT_V2",
    "MEMORY_REPOSITORY_PROVIDER_INJECT_V2",
    "MEMORY_REPOSITORY_PROVIDER_MODULE_V2",
    "MEMORY_REPOSITORY_PROVIDER_SERVICE_V2",
    "MemoryApplicationResolverProtocolV2",
    "MemoryApplicationResolverV2",
    "MemoryApplicationServicesV2",
    "MemoryRepositoryProviderProtocolV2",
    "SqlMemoryRepositoryProviderV2",
    "memory_service_definitions_v2",
]
