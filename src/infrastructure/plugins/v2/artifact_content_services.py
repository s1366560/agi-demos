"""Generation-owned application seam for Artifact content operations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from src.application.services.artifact_content_authority_service import (
    ArtifactContentAuthorityService,
)

from .artifact_content_gc_runtime import ObjectStorageServiceV2
from .artifact_content_persistence import (
    ArtifactContentCommitReconcilerProtocolV2,
    ArtifactContentPersistenceFactoryProtocolV2,
    artifact_content_persistence_provider_definition_v2,
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
ARTIFACT_CONTENT_PROVIDER_INJECT_V2 = "provider"
ARTIFACT_CONTENT_STORAGE_INJECT_V2 = "storage"


@dataclass(frozen=True, kw_only=True)
class ArtifactContentApplicationServicesV2:
    """Operation-owned content authority plus fresh-session reconciler."""

    content: ArtifactContentAuthorityService
    reconciler: ArtifactContentCommitReconcilerProtocolV2


@runtime_checkable
class ArtifactContentApplicationResolverProtocolV2(Protocol):
    """Resolve Artifact content services for one operation."""

    def resolve(self, operation: OperationContextV2) -> ArtifactContentApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class ArtifactContentApplicationResolverV2:
    """Bind the Profile-selected persistence and storage Providers."""

    provider: ArtifactContentPersistenceFactoryProtocolV2
    storage: ObjectStorageServiceV2

    def resolve(self, operation: OperationContextV2) -> ArtifactContentApplicationServicesV2:
        persistence = self.provider.build(
            operation,
            storage=self.storage.storage_service,
        )
        return ArtifactContentApplicationServicesV2(
            content=ArtifactContentAuthorityService(
                repository=persistence.repository,
                storage_service=self.storage.storage_service,
                orphan_recorder=persistence.reconciler.record_pending,
            ),
            reconciler=persistence.reconciler,
        )


def artifact_content_application_definition_v2() -> PluginDefinitionV2:
    """Publish the explicit Artifact content application Consumer."""

    def apply(context: ContextV2, config: Mapping[str, Any]) -> None:
        if config.get("strategy") != "operation-scoped-provider":
            raise ValueError(
                "Artifact content application resolver requires strategy operation-scoped-provider"
            )
        provider = context.require(ARTIFACT_CONTENT_PROVIDER_INJECT_V2)
        if not isinstance(provider, ArtifactContentPersistenceFactoryProtocolV2):
            raise RuntimeV2Error(
                "invalid_artifact_content_provider",
                "Artifact content provider inject has an invalid implementation",
            )
        storage = context.require(ARTIFACT_CONTENT_STORAGE_INJECT_V2)
        if not isinstance(storage, ObjectStorageServiceV2):
            raise RuntimeV2Error(
                "invalid_artifact_content_storage",
                "Artifact content storage inject has an invalid implementation",
            )
        _ = context.provide(
            ARTIFACT_CONTENT_APPLICATION_SERVICE_V2,
            ArtifactContentApplicationResolverV2(provider=provider, storage=storage),
            label="artifact-content-application",
        )

    return PluginDefinitionV2(
        module_ref=ARTIFACT_CONTENT_APPLICATION_MODULE_V2,
        contract_digest=generated_contract_digest_v2(ARTIFACT_CONTENT_APPLICATION_MODULE_V2),
        apply=apply,
    )


def artifact_content_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return the persistence Provider before its application Consumer."""
    return (
        artifact_content_persistence_provider_definition_v2(),
        artifact_content_application_definition_v2(),
    )


__all__ = [
    "ARTIFACT_CONTENT_APPLICATION_MODULE_V2",
    "ARTIFACT_CONTENT_APPLICATION_SERVICE_V2",
    "ARTIFACT_CONTENT_PROVIDER_INJECT_V2",
    "ARTIFACT_CONTENT_STORAGE_INJECT_V2",
    "ArtifactContentApplicationResolverProtocolV2",
    "ArtifactContentApplicationResolverV2",
    "ArtifactContentApplicationServicesV2",
    "artifact_content_application_definition_v2",
    "artifact_content_service_definitions_v2",
]
