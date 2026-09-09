"""Generation-owned cloud sync repository and application composition."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.knowledge_graph_sync_service import (
    KnowledgeGraphSyncApplication,
    KnowledgeGraphSyncService,
)
from src.application.services.knowledge_sync_service import (
    KnowledgeSyncApplication,
    KnowledgeSyncService,
)
from src.domain.model.knowledge_sync.contracts import KnowledgeSyncScope
from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.domain.ports.repositories.knowledge_graph_sync_repository import (
    KnowledgeGraphSyncRepository,
)
from src.domain.ports.repositories.knowledge_sync_enrollment_repository import (
    KnowledgeSyncEnrollmentRepository,
)
from src.domain.ports.repositories.knowledge_sync_repository import KnowledgeSyncRepository
from src.infrastructure.adapters.secondary.persistence.sql_cloud_knowledge_sync_repository import (
    SqlCloudKnowledgeSyncRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_knowledge_sync_repository import (
    SqlKnowledgeSyncRepository,
)

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

CLOUD_KNOWLEDGE_SYNC_REPOSITORY_MODULE_V2 = "builtin://memstack/persistence/cloud-knowledge-sync"
CLOUD_KNOWLEDGE_SYNC_REPOSITORY_SERVICE_V2 = "service:persistence.cloud-knowledge-sync"
CLOUD_KNOWLEDGE_SYNC_APPLICATION_MODULE_V2 = "builtin://memstack/application/cloud-knowledge-sync"
CLOUD_KNOWLEDGE_SYNC_APPLICATION_SERVICE_V2 = "service:application.cloud-knowledge-sync"
_DB_SERVICE = "service:operation.db-session"
_IDENTITY_SERVICE = "service:operation.identity"


class CloudKnowledgeSyncStoreProtocolV2(
    KnowledgeSyncRepository, KnowledgeGraphSyncRepository, Protocol
): ...


@dataclass(frozen=True, kw_only=True)
class CloudKnowledgeSyncRepositoriesV2:
    sync: CloudKnowledgeSyncStoreProtocolV2
    enrollment: KnowledgeSyncEnrollmentRepository
    commit: Callable[[], Awaitable[None]]


@dataclass(frozen=True, kw_only=True)
class CloudKnowledgeSyncServicesV2:
    sync: KnowledgeSyncApplication
    graph_sync: KnowledgeGraphSyncApplication
    enrollment: KnowledgeSyncEnrollmentRepository


@runtime_checkable
class CloudKnowledgeSyncRepositoryProviderProtocolV2(Protocol):
    async def discover_scope(
        self, operation: OperationContextV2, project_id: str
    ) -> KnowledgeSyncScope: ...

    def build(self, operation: OperationContextV2) -> CloudKnowledgeSyncRepositoriesV2: ...


@runtime_checkable
class CloudKnowledgeSyncResolverProtocolV2(Protocol):
    async def discover_scope(
        self, operation: OperationContextV2, project_id: str
    ) -> KnowledgeSyncScope: ...

    def resolve(self, operation: OperationContextV2) -> CloudKnowledgeSyncServicesV2: ...


def _db(operation: OperationContextV2) -> AsyncSession:
    value = operation.require(_DB_SERVICE)
    if not isinstance(value, AsyncSession):
        raise RuntimeV2Error("invalid_operation_db_session", "cloud sync requires an AsyncSession")
    return value


def _actor(operation: OperationContextV2) -> str:
    identity = operation.require(_IDENTITY_SERVICE)
    if not isinstance(identity, dict):
        raise RuntimeV2Error(
            "invalid_operation_identity", "cloud sync requires an authenticated actor"
        )
    actor = cast("dict[str, object]", identity).get("user_id")
    if not isinstance(actor, str) or not actor or actor.strip() != actor:
        raise RuntimeV2Error("invalid_operation_identity", "cloud sync requires a canonical actor")
    return actor


@dataclass(frozen=True, kw_only=True)
class SqlCloudKnowledgeSyncProviderV2:
    async def discover_scope(
        self, operation: OperationContextV2, project_id: str
    ) -> KnowledgeSyncScope:
        db, actor = _db(operation), _actor(operation)
        scope = await SqlKnowledgeSyncRepository(db).resolve_scope(actor, project_id)
        if _db(operation) is not db or _actor(operation) != actor:
            raise RuntimeV2Error("invalid_operation_identity", "cloud sync identity changed")
        return scope

    def build(self, operation: OperationContextV2) -> CloudKnowledgeSyncRepositoriesV2:
        db, actor = _db(operation), _actor(operation)
        declared = operation.context.scope
        if (
            declared.kind is not ScopeKindV2.PROJECT
            or declared.tenant_id is None
            or declared.project_id is None
        ):
            raise RuntimeV2Error(
                "invalid_operation_scope", "cloud sync requires a project operation"
            )
        scope = KnowledgeSyncScope(
            tenant_id=declared.tenant_id, project_id=declared.project_id, actor_id=actor
        )

        def current() -> None:
            identity = operation.require(_IDENTITY_SERVICE)
            if (
                _db(operation) is not db
                or _actor(operation) != actor
                or not isinstance(identity, dict)
                or cast("dict[str, object]", identity).get("tenant_id") != scope.tenant_id
                or operation.context.scope != declared
            ):
                raise RuntimeV2Error("invalid_operation_identity", "cloud sync operation changed")

        current()
        repository = SqlCloudKnowledgeSyncRepository(db, scope, current)

        async def commit() -> None:
            current()
            await db.commit()
            current()

        return CloudKnowledgeSyncRepositoriesV2(
            sync=repository, enrollment=repository, commit=commit
        )


@dataclass(frozen=True, kw_only=True)
class CloudKnowledgeSyncResolverV2:
    repository_provider: CloudKnowledgeSyncRepositoryProviderProtocolV2

    async def discover_scope(
        self, operation: OperationContextV2, project_id: str
    ) -> KnowledgeSyncScope:
        return await self.repository_provider.discover_scope(operation, project_id)

    def resolve(self, operation: OperationContextV2) -> CloudKnowledgeSyncServicesV2:
        repositories = self.repository_provider.build(operation)
        return CloudKnowledgeSyncServicesV2(
            sync=KnowledgeSyncApplication(
                service=KnowledgeSyncService(repository=repositories.sync),
                commit=repositories.commit,
            ),
            graph_sync=KnowledgeGraphSyncApplication(
                service=KnowledgeGraphSyncService(repository=repositories.sync),
                commit=repositories.commit,
            ),
            enrollment=repositories.enrollment,
        )


def _apply_cloud_knowledge_sync_repository_v2(
    context: ContextV2, config: Mapping[str, Any]
) -> None:
    if config.get("strategy") != "request-async-session":
        raise ValueError("cloud sync repository requires request-async-session")
    _ = context.provide(
        CLOUD_KNOWLEDGE_SYNC_REPOSITORY_SERVICE_V2,
        SqlCloudKnowledgeSyncProviderV2(),
        label="cloud-knowledge-sync-repository",
    )


def _apply_cloud_knowledge_sync_application_v2(
    context: ContextV2, config: Mapping[str, Any]
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError("cloud sync application requires operation-scoped-provider")
    provider = context.require("repositories")
    if not isinstance(provider, CloudKnowledgeSyncRepositoryProviderProtocolV2):
        raise RuntimeV2Error(
            "invalid_cloud_sync_provider", "cloud sync repository inject is invalid"
        )
    _ = context.provide(
        CLOUD_KNOWLEDGE_SYNC_APPLICATION_SERVICE_V2,
        CloudKnowledgeSyncResolverV2(repository_provider=provider),
        label="cloud-knowledge-sync-application",
    )


def cloud_knowledge_sync_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    return (
        PluginDefinitionV2(
            module_ref=CLOUD_KNOWLEDGE_SYNC_REPOSITORY_MODULE_V2,
            contract_digest=generated_contract_digest_v2(CLOUD_KNOWLEDGE_SYNC_REPOSITORY_MODULE_V2),
            apply=_apply_cloud_knowledge_sync_repository_v2,
        ),
        PluginDefinitionV2(
            module_ref=CLOUD_KNOWLEDGE_SYNC_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(
                CLOUD_KNOWLEDGE_SYNC_APPLICATION_MODULE_V2
            ),
            apply=_apply_cloud_knowledge_sync_application_v2,
        ),
    )
