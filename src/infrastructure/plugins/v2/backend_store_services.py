"""Generation-owned graph/retrieval store Provider and application Consumer seams."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.graph_store_service import GraphStoreService
from src.application.services.retrieval_store_service import RetrievalStoreService
from src.infrastructure.adapters.secondary.persistence.sql_graph_store_repository import (
    SqlGraphStoreRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_retrieval_store_repository import (
    SqlRetrievalStoreRepository,
)
from src.infrastructure.graph.backend_factory import build_default_factory
from src.infrastructure.graph.registry import get_graph_backend_registry
from src.infrastructure.retrieval.backend_factory import build_default_retrieval_factory
from src.infrastructure.retrieval.registry import get_retrieval_backend_registry

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

BACKEND_STORE_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/backend-store-provider"
BACKEND_STORE_PROVIDER_SERVICE_V2 = "service:persistence.backend-store-provider"
BACKEND_STORE_APPLICATION_MODULE_V2 = "builtin://memstack/application/backend-store-services"
BACKEND_STORE_APPLICATION_SERVICE_V2 = "service:application.backend-store-services"
BACKEND_STORE_PROVIDER_INJECT_V2 = "provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


@dataclass(frozen=True, kw_only=True)
class BackendStoreServicesV2:
    """One request-session-owned graph/retrieval management service set."""

    graph_service: GraphStoreService
    retrieval_service: RetrievalStoreService


@runtime_checkable
class BackendStoreServiceFactoryProtocolV2(Protocol):
    """Consumer-visible factory contract that hides SQL and backend implementations."""

    def build(self, operation: OperationContextV2) -> BackendStoreServicesV2: ...


@runtime_checkable
class BackendStoreApplicationResolverProtocolV2(Protocol):
    """Application-facing resolver injected through a declared service alias."""

    def resolve(self, operation: OperationContextV2) -> BackendStoreServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlBackendStoreServiceFactoryV2:
    """Build graph/retrieval services from the operation's exact AsyncSession."""

    strategy: str

    def build(self, operation: OperationContextV2) -> BackendStoreServicesV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "backend store services require an AsyncSession operation service",
            )
        return BackendStoreServicesV2(
            graph_service=GraphStoreService(
                repo=SqlGraphStoreRepository(db),
                registry=get_graph_backend_registry(),
                factory=build_default_factory(),
            ),
            retrieval_service=RetrievalStoreService(
                repo=SqlRetrievalStoreRepository(db),
                registry=get_retrieval_backend_registry(),
                factory=build_default_retrieval_factory(),
            ),
        )


@dataclass(frozen=True, kw_only=True)
class BackendStoreApplicationResolverV2:
    """Resolve request-owned services without exposing a Provider implementation."""

    provider: BackendStoreServiceFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> BackendStoreServicesV2:
        return self.provider.build(operation)


def _apply_backend_store_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "request-async-session":
        raise ValueError("backend store provider requires strategy request-async-session")
    _ = context.provide(
        BACKEND_STORE_PROVIDER_SERVICE_V2,
        SqlBackendStoreServiceFactoryV2(strategy=strategy),
        label="backend-store-provider",
    )


def _apply_backend_store_application_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "operation-scoped-provider":
        raise ValueError(
            "backend store application resolver requires strategy operation-scoped-provider"
        )
    provider = context.require(BACKEND_STORE_PROVIDER_INJECT_V2)
    if not isinstance(provider, BackendStoreServiceFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_backend_store_provider",
            "backend store provider inject does not implement the factory contract",
        )
    _ = context.provide(
        BACKEND_STORE_APPLICATION_SERVICE_V2,
        BackendStoreApplicationResolverV2(provider=provider),
        label="backend-store-application",
    )


def backend_store_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    return (
        PluginDefinitionV2(
            module_ref=BACKEND_STORE_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(BACKEND_STORE_PROVIDER_MODULE_V2),
            apply=_apply_backend_store_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=BACKEND_STORE_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(BACKEND_STORE_APPLICATION_MODULE_V2),
            apply=_apply_backend_store_application_v2,
        ),
    )


__all__ = [
    "BACKEND_STORE_APPLICATION_MODULE_V2",
    "BACKEND_STORE_APPLICATION_SERVICE_V2",
    "BACKEND_STORE_PROVIDER_INJECT_V2",
    "BACKEND_STORE_PROVIDER_MODULE_V2",
    "BACKEND_STORE_PROVIDER_SERVICE_V2",
    "BackendStoreApplicationResolverProtocolV2",
    "BackendStoreApplicationResolverV2",
    "BackendStoreServiceFactoryProtocolV2",
    "BackendStoreServicesV2",
    "SqlBackendStoreServiceFactoryV2",
    "backend_store_service_definitions_v2",
]
