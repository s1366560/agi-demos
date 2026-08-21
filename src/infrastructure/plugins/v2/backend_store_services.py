"""Generation-owned graph/retrieval store Provider and shadow Consumer seams."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.graph_store_service import GraphStoreService
from src.application.services.retrieval_store_service import RetrievalStoreService
from src.domain.model.plugins.generated_v2 import ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
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
BACKEND_STORE_SHADOW_MODULE_V2 = "builtin://memstack/application/backend-store-shadow"
BACKEND_STORE_SHADOW_SERVICE_V2 = "service:application.backend-store-shadow"
BACKEND_STORE_PROVIDER_INJECT_V2 = "provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


@dataclass(frozen=True, kw_only=True)
class BackendStoreServicesV2:
    """One request-session-owned graph/retrieval management service set."""

    graph_service: GraphStoreService
    retrieval_service: RetrievalStoreService


@dataclass(frozen=True, kw_only=True)
class BackendStoreShadowEvidenceV2:
    """Objective parity evidence from the non-authoritative shadow Consumer."""

    operation_id: str
    scope: ScopeV2
    descriptor: PluginGenerationDescriptorV2 | None
    matches: bool
    differences: tuple[str, ...]
    error_code: str | None = None

    @classmethod
    def failed(
        cls,
        *,
        operation_id: str,
        scope: ScopeV2,
        descriptor: PluginGenerationDescriptorV2 | None,
        error_code: str,
        difference: str,
    ) -> BackendStoreShadowEvidenceV2:
        return cls(
            operation_id=operation_id,
            scope=scope,
            descriptor=descriptor,
            matches=False,
            differences=(difference,),
            error_code=error_code,
        )


@runtime_checkable
class BackendStoreServiceFactoryProtocolV2(Protocol):
    """Consumer-visible factory contract that hides SQL and backend implementations."""

    def build(self, operation: OperationContextV2) -> BackendStoreServicesV2: ...


@runtime_checkable
class BackendStoreApplicationResolverProtocolV2(Protocol):
    """Application-facing resolver injected through a declared service alias."""

    def resolve(self, operation: OperationContextV2) -> BackendStoreServicesV2: ...


@runtime_checkable
class BackendStoreShadowProtocolV2(Protocol):
    """Boundary-visible structural comparator contract."""

    def compare(
        self,
        *,
        operation: OperationContextV2,
        legacy: BackendStoreServicesV2,
        expected_scope: ScopeV2,
    ) -> BackendStoreShadowEvidenceV2: ...


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


@dataclass(frozen=True, kw_only=True)
class BackendStoreShadowComparatorV2:
    """Compare V2 and legacy service construction without selecting either."""

    provider: BackendStoreServiceFactoryProtocolV2

    def compare(
        self,
        *,
        operation: OperationContextV2,
        legacy: BackendStoreServicesV2,
        expected_scope: ScopeV2,
    ) -> BackendStoreShadowEvidenceV2:
        candidate = self.provider.build(operation)
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        differences: list[str] = []

        if operation.context.scope != expected_scope:
            differences.append("operation.scope")
        _compare_service_v2(
            "graph_service",
            candidate.graph_service,
            legacy.graph_service,
            db=db,
            differences=differences,
        )
        _compare_service_v2(
            "retrieval_service",
            candidate.retrieval_service,
            legacy.retrieval_service,
            db=db,
            differences=differences,
        )
        return BackendStoreShadowEvidenceV2(
            operation_id=operation.operation_id,
            scope=operation.context.scope,
            descriptor=operation.descriptor,
            matches=not differences,
            differences=tuple(differences),
        )


def _compare_service_v2(
    label: str,
    candidate: GraphStoreService | RetrievalStoreService,
    legacy: GraphStoreService | RetrievalStoreService,
    *,
    db: object,
    differences: list[str],
) -> None:
    if type(candidate) is not type(legacy):
        differences.append(f"{label}.type")
    candidate_repo = getattr(candidate, "_repo", None)
    legacy_repo = getattr(legacy, "_repo", None)
    if type(candidate_repo) is not type(legacy_repo):
        differences.append(f"{label}.repository.type")
    if getattr(candidate_repo, "_session", None) is not db:
        differences.append(f"{label}.repository.candidate_session")
    if getattr(legacy_repo, "_session", None) is not db:
        differences.append(f"{label}.repository.legacy_session")
    if getattr(candidate, "_registry", None) is not getattr(legacy, "_registry", None):
        differences.append(f"{label}.registry")
    candidate_factory = getattr(candidate, "_factory", None)
    legacy_factory = getattr(legacy, "_factory", None)
    if type(candidate_factory) is not type(legacy_factory):
        differences.append(f"{label}.factory.type")
    if _builder_ids_v2(candidate_factory) != _builder_ids_v2(legacy_factory):
        differences.append(f"{label}.factory.builders")


def _builder_ids_v2(factory: object) -> tuple[str, ...]:
    builders = getattr(factory, "_builders", None)
    if not isinstance(builders, dict):
        return ()
    object_map = cast("dict[object, object]", builders)
    return tuple(sorted(str(key) for key in object_map))


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


def _apply_backend_store_shadow_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    strategy = config.get("strategy")
    if strategy != "structural-parity":
        raise ValueError("backend store shadow requires strategy structural-parity")
    provider = context.require(BACKEND_STORE_PROVIDER_INJECT_V2)
    if not isinstance(provider, BackendStoreServiceFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_backend_store_provider",
            "backend store provider inject does not implement the factory contract",
        )
    _ = context.provide(
        BACKEND_STORE_SHADOW_SERVICE_V2,
        BackendStoreShadowComparatorV2(provider=provider),
        label="backend-store-shadow",
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
        PluginDefinitionV2(
            module_ref=BACKEND_STORE_SHADOW_MODULE_V2,
            contract_digest=generated_contract_digest_v2(BACKEND_STORE_SHADOW_MODULE_V2),
            apply=_apply_backend_store_shadow_v2,
        ),
    )


__all__ = [
    "BACKEND_STORE_APPLICATION_MODULE_V2",
    "BACKEND_STORE_APPLICATION_SERVICE_V2",
    "BACKEND_STORE_PROVIDER_INJECT_V2",
    "BACKEND_STORE_PROVIDER_MODULE_V2",
    "BACKEND_STORE_PROVIDER_SERVICE_V2",
    "BACKEND_STORE_SHADOW_MODULE_V2",
    "BACKEND_STORE_SHADOW_SERVICE_V2",
    "BackendStoreApplicationResolverProtocolV2",
    "BackendStoreApplicationResolverV2",
    "BackendStoreServiceFactoryProtocolV2",
    "BackendStoreServicesV2",
    "BackendStoreShadowComparatorV2",
    "BackendStoreShadowEvidenceV2",
    "BackendStoreShadowProtocolV2",
    "SqlBackendStoreServiceFactoryV2",
    "backend_store_service_definitions_v2",
]
