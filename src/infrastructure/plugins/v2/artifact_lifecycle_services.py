"""Generation-owned Artifact lifecycle and typed event publication seams."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from src.application.services.artifact_service import ArtifactService
from src.domain.events.agent_events import AgentDomainEvent
from src.infrastructure.adapters.secondary.persistence.sql_artifact_repository import (
    SqlArtifactRepository,
)

from .artifact_content_gc_runtime import (
    AsyncSessionFactoryServiceV2,
    ObjectStorageServiceV2,
)
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)
from .sandbox_runtime import SandboxApplicationResolverProtocolV2

ARTIFACT_EVENT_PUBLISHER_MODULE_V2 = "builtin://memstack/events/artifact-publisher"
ARTIFACT_EVENT_PUBLISHER_SERVICE_V2 = "service:events.artifact-publisher"
ARTIFACT_EVENT_PUBLISHER_SANDBOX_INJECT_V2 = "sandbox"
ARTIFACT_LIFECYCLE_APPLICATION_MODULE_V2 = (
    "builtin://memstack/application/artifact-lifecycle-services"
)
ARTIFACT_LIFECYCLE_APPLICATION_SERVICE_V2 = "service:application.artifact-lifecycle-services"
ARTIFACT_LIFECYCLE_SESSIONS_INJECT_V2 = "sessions"
ARTIFACT_LIFECYCLE_STORAGE_INJECT_V2 = "storage"
ARTIFACT_LIFECYCLE_EVENTS_INJECT_V2 = "events"


@runtime_checkable
class ArtifactEventPublisherProtocolV2(Protocol):
    """Publish typed Artifact events through generation-selected transports."""

    async def publish(
        self,
        project_id: str,
        event: AgentDomainEvent,
        *,
        conversation_id: str | None = None,
    ) -> None: ...


@dataclass(frozen=True, kw_only=True)
class SandboxArtifactEventPublisherV2:
    """Adapt the declared sandbox service to both sandbox and Agent streams."""

    sandbox: SandboxApplicationResolverProtocolV2

    async def publish(
        self,
        project_id: str,
        event: AgentDomainEvent,
        *,
        conversation_id: str | None = None,
    ) -> None:
        services = self.sandbox.resolve()
        _ = await services.event_publisher.publish_domain_event(
            project_id,
            event,
            conversation_id=conversation_id,
        )


@dataclass(frozen=True, kw_only=True)
class ArtifactLifecycleApplicationServiceV2:
    """Artifact lifecycle service owned by one exact generation."""

    artifact: ArtifactService


def _apply_artifact_event_publisher_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "sandbox-and-agent-streams":
        raise ValueError("Artifact event publisher requires strategy sandbox-and-agent-streams")
    sandbox = context.require(ARTIFACT_EVENT_PUBLISHER_SANDBOX_INJECT_V2)
    if not isinstance(sandbox, SandboxApplicationResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_artifact_event_sandbox",
            "Artifact event publisher sandbox inject has an invalid implementation",
        )
    _ = context.provide(
        ARTIFACT_EVENT_PUBLISHER_SERVICE_V2,
        SandboxArtifactEventPublisherV2(sandbox=sandbox),
        label="artifact-event-publisher",
    )


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

    sessions = context.require(ARTIFACT_LIFECYCLE_SESSIONS_INJECT_V2)
    if not isinstance(sessions, AsyncSessionFactoryServiceV2):
        raise RuntimeV2Error(
            "invalid_artifact_lifecycle_sessions",
            "Artifact lifecycle sessions inject has an invalid implementation",
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
                artifact_repository=SqlArtifactRepository(sessions.factory),
                bucket_prefix=bucket_prefix,
                url_expiration_seconds=url_expiration_seconds,
            )
        ),
        label="artifact-lifecycle-application",
    )


def artifact_lifecycle_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return the event Provider and Artifact lifecycle Consumer definitions."""
    return (
        PluginDefinitionV2(
            module_ref=ARTIFACT_EVENT_PUBLISHER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(ARTIFACT_EVENT_PUBLISHER_MODULE_V2),
            apply=_apply_artifact_event_publisher_v2,
        ),
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
    "ARTIFACT_LIFECYCLE_SESSIONS_INJECT_V2",
    "ARTIFACT_LIFECYCLE_STORAGE_INJECT_V2",
    "ArtifactEventPublisherProtocolV2",
    "ArtifactLifecycleApplicationServiceV2",
    "SandboxArtifactEventPublisherV2",
    "artifact_lifecycle_service_definitions_v2",
]
