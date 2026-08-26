"""Persistence Provider seam for Artifact content operations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.artifact_content_authority_service import (
    ArtifactContentSaveOutcome,
)
from src.domain.ports.repositories.artifact_content_authority_repository import (
    ArtifactContentAuthorityRepositoryPort,
)
from src.domain.ports.services.storage_service_port import StorageServicePort
from src.infrastructure.adapters.secondary.persistence.artifact_content_commit_reconciler import (
    ArtifactContentCommitReconciler,
)
from src.infrastructure.adapters.secondary.persistence.sql_artifact_content_authority import (
    SqlArtifactContentAuthorityRepository,
)

from .artifact_content_gc_runtime import AsyncSessionFactoryServiceV2
from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

ARTIFACT_CONTENT_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/artifact-content-provider"
ARTIFACT_CONTENT_PROVIDER_SERVICE_V2 = "service:persistence.artifact-content-provider"
ARTIFACT_CONTENT_PROVIDER_SESSIONS_INJECT_V2 = "sessions"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


@runtime_checkable
class ArtifactContentCommitReconcilerProtocolV2(Protocol):
    """Reconcile provisional storage writes using fresh persistence sessions."""

    async def reconcile(self, outcome: ArtifactContentSaveOutcome) -> None: ...

    async def record_pending(
        self,
        outcome: ArtifactContentSaveOutcome,
        *,
        reason_code: str,
        last_error_code: str,
        next_attempt_at: datetime | None = None,
    ) -> None: ...


@dataclass(frozen=True, kw_only=True)
class ArtifactContentPersistenceServicesV2:
    """Persistence resources selected by one exact Provider module."""

    repository: ArtifactContentAuthorityRepositoryPort
    reconciler: ArtifactContentCommitReconcilerProtocolV2


@runtime_checkable
class ArtifactContentPersistenceFactoryProtocolV2(Protocol):
    """Build operation and fresh-session persistence without host fallbacks."""

    def build(
        self,
        operation: OperationContextV2,
        *,
        storage: StorageServicePort,
    ) -> ArtifactContentPersistenceServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlArtifactContentPersistenceFactoryV2:
    """SQL persistence implementation selected only by the active Profile."""

    sessions: AsyncSessionFactoryServiceV2

    def build(
        self,
        operation: OperationContextV2,
        *,
        storage: StorageServicePort,
    ) -> ArtifactContentPersistenceServicesV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "Artifact content persistence requires an AsyncSession operation service",
            )
        return ArtifactContentPersistenceServicesV2(
            repository=SqlArtifactContentAuthorityRepository(db),
            reconciler=ArtifactContentCommitReconciler(
                session_factory=self.sessions.factory,
                storage_service=storage,
            ),
        )


def artifact_content_persistence_provider_definition_v2() -> PluginDefinitionV2:
    """Publish the SQL Provider behind one exact persistence service key."""

    def apply(context: ContextV2, config: Mapping[str, Any]) -> None:
        if config.get("strategy") != "operation-and-fresh-session":
            raise ValueError(
                "Artifact content provider requires strategy operation-and-fresh-session"
            )
        sessions = context.require(ARTIFACT_CONTENT_PROVIDER_SESSIONS_INJECT_V2)
        if not isinstance(sessions, AsyncSessionFactoryServiceV2):
            raise RuntimeV2Error(
                "invalid_artifact_content_provider_sessions",
                "Artifact content provider sessions inject has an invalid implementation",
            )
        _ = context.provide(
            ARTIFACT_CONTENT_PROVIDER_SERVICE_V2,
            SqlArtifactContentPersistenceFactoryV2(sessions=sessions),
            label="artifact-content-provider",
        )

    return PluginDefinitionV2(
        module_ref=ARTIFACT_CONTENT_PROVIDER_MODULE_V2,
        contract_digest=generated_contract_digest_v2(ARTIFACT_CONTENT_PROVIDER_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "ARTIFACT_CONTENT_PROVIDER_MODULE_V2",
    "ARTIFACT_CONTENT_PROVIDER_SERVICE_V2",
    "ARTIFACT_CONTENT_PROVIDER_SESSIONS_INJECT_V2",
    "ArtifactContentCommitReconcilerProtocolV2",
    "ArtifactContentPersistenceFactoryProtocolV2",
    "ArtifactContentPersistenceServicesV2",
    "SqlArtifactContentPersistenceFactoryV2",
    "artifact_content_persistence_provider_definition_v2",
]
