"""Generation-owned Artifact lifecycle and typed event publication seams."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.application.services.artifact_service import ArtifactService

from .artifact_content_gc_runtime import ObjectStorageServiceV2
from .artifact_events import (
    ARTIFACT_EVENT_PUBLISHER_MODULE_V2,
    ARTIFACT_EVENT_PUBLISHER_SANDBOX_INJECT_V2,
    ARTIFACT_EVENT_PUBLISHER_SERVICE_V2,
    ArtifactEventPublisherProtocolV2,
    TypedArtifactEventPublisherV2,
    artifact_event_publisher_definition_v2,
)
from .artifact_lifecycle_persistence import (
    ArtifactLifecyclePersistenceFactoryProtocolV2,
    artifact_lifecycle_persistence_provider_definition_v2,
)
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

ARTIFACT_LIFECYCLE_APPLICATION_MODULE_V2 = (
    "builtin://memstack/application/artifact-lifecycle-services"
)
ARTIFACT_LIFECYCLE_APPLICATION_SERVICE_V2 = "service:application.artifact-lifecycle-services"
ARTIFACT_LIFECYCLE_PROVIDER_INJECT_V2 = "provider"
ARTIFACT_LIFECYCLE_STORAGE_INJECT_V2 = "storage"
ARTIFACT_LIFECYCLE_EVENTS_INJECT_V2 = "events"


@dataclass(frozen=True, kw_only=True)
class ArtifactLifecycleApplicationServiceV2:
    """Artifact lifecycle service owned by one exact generation."""

    artifact: ArtifactService


def _apply_artifact_lifecycle_application_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "generation-owned-provider":
        raise ValueError("Artifact lifecycle service requires strategy generation-owned-provider")
    bucket_prefix = config.get("bucket_prefix")
    if not isinstance(bucket_prefix, str) or not bucket_prefix.strip():
        raise ValueError("Artifact lifecycle service requires a non-empty bucket_prefix")
    url_expiration_seconds = config.get("url_expiration_seconds")
    if type(url_expiration_seconds) is not int or url_expiration_seconds <= 0:
        raise ValueError("Artifact lifecycle service requires positive url_expiration_seconds")

    provider = context.require(ARTIFACT_LIFECYCLE_PROVIDER_INJECT_V2)
    if not isinstance(provider, ArtifactLifecyclePersistenceFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_artifact_lifecycle_provider",
            "Artifact lifecycle provider inject has an invalid implementation",
        )
    storage = context.require(ARTIFACT_LIFECYCLE_STORAGE_INJECT_V2)
    if not isinstance(storage, ObjectStorageServiceV2):
        raise RuntimeV2Error(
            "invalid_artifact_lifecycle_storage",
            "Artifact lifecycle storage inject has an invalid implementation",
        )
    events = context.require(ARTIFACT_LIFECYCLE_EVENTS_INJECT_V2)
    if not isinstance(events, ArtifactEventPublisherProtocolV2):
        raise RuntimeV2Error(
            "invalid_artifact_lifecycle_events",
            "Artifact lifecycle events inject has an invalid implementation",
        )

    _ = context.provide(
        ARTIFACT_LIFECYCLE_APPLICATION_SERVICE_V2,
        ArtifactLifecycleApplicationServiceV2(
            artifact=ArtifactService(
                storage_service=storage.storage_service,
                event_publisher=events.publish,
                artifact_repository=provider.build(),
                bucket_prefix=bucket_prefix,
                url_expiration_seconds=url_expiration_seconds,
            )
        ),
        label="artifact-lifecycle-application",
    )


def artifact_lifecycle_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return both Providers before the Artifact lifecycle Consumer."""
    return (
        artifact_event_publisher_definition_v2(),
        artifact_lifecycle_persistence_provider_definition_v2(),
        PluginDefinitionV2(
            module_ref=ARTIFACT_LIFECYCLE_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(ARTIFACT_LIFECYCLE_APPLICATION_MODULE_V2),
            apply=_apply_artifact_lifecycle_application_v2,
        ),
    )


__all__ = [
    "ARTIFACT_EVENT_PUBLISHER_MODULE_V2",
    "ARTIFACT_EVENT_PUBLISHER_SANDBOX_INJECT_V2",
    "ARTIFACT_EVENT_PUBLISHER_SERVICE_V2",
    "ARTIFACT_LIFECYCLE_APPLICATION_MODULE_V2",
    "ARTIFACT_LIFECYCLE_APPLICATION_SERVICE_V2",
    "ARTIFACT_LIFECYCLE_EVENTS_INJECT_V2",
    "ARTIFACT_LIFECYCLE_PROVIDER_INJECT_V2",
    "ARTIFACT_LIFECYCLE_STORAGE_INJECT_V2",
    "ArtifactEventPublisherProtocolV2",
    "ArtifactLifecycleApplicationServiceV2",
    "TypedArtifactEventPublisherV2",
    "artifact_lifecycle_service_definitions_v2",
]
