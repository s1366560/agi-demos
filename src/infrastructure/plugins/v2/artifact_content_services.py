"""Generation-owned application seam for Artifact content operations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.artifact_content_authority_service import (
    ArtifactContentAuthorityService,
)
from src.infrastructure.adapters.secondary.persistence.artifact_content_commit_reconciler import (
    ArtifactContentCommitReconciler,
)
from src.infrastructure.adapters.secondary.persistence.sql_artifact_content_authority import (
    SqlArtifactContentAuthorityRepository,
)

from .artifact_content_gc_runtime import (
    AsyncSessionFactoryServiceV2,
    ObjectStorageServiceV2,
)
from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

ARTIFACT_CONTENT_APPLICATION_MODULE_V2 = "builtin://memstack/application/artifact-content-services"
ARTIFACT_CONTENT_APPLICATION_SERVICE_V2 = "service:application.artifact-content-services"
ARTIFACT_CONTENT_SESSIONS_INJECT_V2 = "sessions"
ARTIFACT_CONTENT_STORAGE_INJECT_V2 = "storage"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


@dataclass(frozen=True, kw_only=True)
class ArtifactContentApplicationServicesV2:
    """Operation-owned content authority plus fresh-session reconciler."""

    content: ArtifactContentAuthorityService
    reconciler: ArtifactContentCommitReconciler


@runtime_checkable
class ArtifactContentApplicationResolverProtocolV2(Protocol):
    """Resolve Artifact content services for one operation."""

    def resolve(self, operation: OperationContextV2) -> ArtifactContentApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class ArtifactContentApplicationResolverV2:
    """Bind declared session/storage Providers to the operation session."""

    sessions: AsyncSessionFactoryServiceV2
    storage: ObjectStorageServiceV2

    def resolve(self, operation: OperationContextV2) -> ArtifactContentApplicationServicesV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "Artifact content services require an AsyncSession operation service",
            )
        reconciler = ArtifactContentCommitReconciler(
            session_factory=self.sessions.factory,
            storage_service=self.storage.storage_service,
        )
        return ArtifactContentApplicationServicesV2(
            content=ArtifactContentAuthorityService(
                repository=SqlArtifactContentAuthorityRepository(db),
                storage_service=self.storage.storage_service,
                orphan_recorder=reconciler.record_pending,
            ),
            reconciler=reconciler,
        )


def artifact_content_application_definition_v2() -> PluginDefinitionV2:
    """Publish the explicit Artifact content application Consumer."""

    def apply(context: ContextV2, config: Mapping[str, Any]) -> None:
        if config.get("strategy") != "operation-scoped-provider":
            raise ValueError(
                "Artifact content application resolver requires strategy operation-scoped-provider"
            )
        sessions = context.require(ARTIFACT_CONTENT_SESSIONS_INJECT_V2)
        if not isinstance(sessions, AsyncSessionFactoryServiceV2):
            raise RuntimeV2Error(
                "invalid_artifact_content_sessions",
                "Artifact content sessions inject has an invalid implementation",
            )
        storage = context.require(ARTIFACT_CONTENT_STORAGE_INJECT_V2)
        if not isinstance(storage, ObjectStorageServiceV2):
            raise RuntimeV2Error(
                "invalid_artifact_content_storage",
                "Artifact content storage inject has an invalid implementation",
            )
        _ = context.provide(
            ARTIFACT_CONTENT_APPLICATION_SERVICE_V2,
            ArtifactContentApplicationResolverV2(sessions=sessions, storage=storage),
            label="artifact-content-application",
        )

    return PluginDefinitionV2(
        module_ref=ARTIFACT_CONTENT_APPLICATION_MODULE_V2,
        contract_digest=generated_contract_digest_v2(ARTIFACT_CONTENT_APPLICATION_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "ARTIFACT_CONTENT_APPLICATION_MODULE_V2",
    "ARTIFACT_CONTENT_APPLICATION_SERVICE_V2",
    "ARTIFACT_CONTENT_SESSIONS_INJECT_V2",
    "ARTIFACT_CONTENT_STORAGE_INJECT_V2",
    "ArtifactContentApplicationResolverProtocolV2",
    "ArtifactContentApplicationResolverV2",
    "ArtifactContentApplicationServicesV2",
    "artifact_content_application_definition_v2",
]
