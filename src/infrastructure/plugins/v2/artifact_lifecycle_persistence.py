"""Persistence Provider seam for Artifact lifecycle services."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from src.domain.ports.repositories.artifact_repository import ArtifactRepositoryPort
from src.infrastructure.adapters.secondary.persistence.sql_artifact_repository import (
    SqlArtifactRepository,
)

from .artifact_content_gc_runtime import AsyncSessionFactoryServiceV2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

ARTIFACT_LIFECYCLE_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/artifact-lifecycle-provider"
ARTIFACT_LIFECYCLE_PROVIDER_SERVICE_V2 = "service:persistence.artifact-lifecycle-provider"
ARTIFACT_LIFECYCLE_PROVIDER_SESSIONS_INJECT_V2 = "sessions"


@runtime_checkable
class ArtifactLifecyclePersistenceFactoryProtocolV2(Protocol):
    """Build the exact Artifact repository selected by the active Profile."""

    def build(self) -> ArtifactRepositoryPort: ...


@dataclass(frozen=True, kw_only=True)
class SqlArtifactLifecyclePersistenceFactoryV2:
    """Trusted SQL repository factory backed by the declared session Provider."""

    sessions: AsyncSessionFactoryServiceV2

    def build(self) -> ArtifactRepositoryPort:
        return SqlArtifactRepository(self.sessions.factory)


def artifact_lifecycle_persistence_provider_definition_v2() -> PluginDefinitionV2:
    """Publish the SQL repository factory behind one exact service key."""

    def apply(context: ContextV2, config: Mapping[str, Any]) -> None:
        if config.get("strategy") != "sqlalchemy-async-sessionmaker":
            raise ValueError(
                "Artifact lifecycle provider requires strategy sqlalchemy-async-sessionmaker"
            )
        sessions = context.require(ARTIFACT_LIFECYCLE_PROVIDER_SESSIONS_INJECT_V2)
        if not isinstance(sessions, AsyncSessionFactoryServiceV2):
            raise RuntimeV2Error(
                "invalid_artifact_lifecycle_provider_sessions",
                "Artifact lifecycle provider sessions inject has an invalid implementation",
            )
        _ = context.provide(
            ARTIFACT_LIFECYCLE_PROVIDER_SERVICE_V2,
            SqlArtifactLifecyclePersistenceFactoryV2(sessions=sessions),
            label="artifact-lifecycle-provider",
        )

    return PluginDefinitionV2(
        module_ref=ARTIFACT_LIFECYCLE_PROVIDER_MODULE_V2,
        contract_digest=generated_contract_digest_v2(ARTIFACT_LIFECYCLE_PROVIDER_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "ARTIFACT_LIFECYCLE_PROVIDER_MODULE_V2",
    "ARTIFACT_LIFECYCLE_PROVIDER_SERVICE_V2",
    "ARTIFACT_LIFECYCLE_PROVIDER_SESSIONS_INJECT_V2",
    "ArtifactLifecyclePersistenceFactoryProtocolV2",
    "SqlArtifactLifecyclePersistenceFactoryV2",
    "artifact_lifecycle_persistence_provider_definition_v2",
]
