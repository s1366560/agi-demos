"""Generation-owned typed Artifact event dispatch and transport handlers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, TypeGuard, runtime_checkable

from pydantic import ValidationError

from src.domain.events.agent_events import (
    AgentArtifactCreatedEvent,
    AgentArtifactErrorEvent,
    AgentArtifactReadyEvent,
    AgentArtifactsBatchEvent,
    AgentDomainEvent,
)
from src.domain.events.types import AgentEventType

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

ARTIFACT_CREATED_EVENT_V2 = "artifact.created"
ARTIFACT_READY_EVENT_V2 = "artifact.ready"
ARTIFACT_ERROR_EVENT_V2 = "artifact.error"
ARTIFACTS_BATCH_EVENT_V2 = "artifacts.batch"
ARTIFACT_LIFECYCLE_EVENTS_V2 = (
    ARTIFACT_CREATED_EVENT_V2,
    ARTIFACT_READY_EVENT_V2,
    ARTIFACT_ERROR_EVENT_V2,
    ARTIFACTS_BATCH_EVENT_V2,
)

type _ArtifactEventDispatchV2 = Callable[
    [str, AgentDomainEvent, str | None],
    Awaitable[None],
]


@runtime_checkable
class ArtifactEventPublisherProtocolV2(Protocol):
    """Publish Artifact domain events through the active generation contract."""

    async def publish(
        self,
        project_id: str,
        event: AgentDomainEvent,
        *,
        conversation_id: str | None = None,
    ) -> None: ...


@dataclass(frozen=True, kw_only=True)
class TypedArtifactEventPublisherV2:
    """Adapt the Artifact service callback to fixed protocol-v2 event modes."""

    dispatch_event: _ArtifactEventDispatchV2

    async def publish(
        self,
        project_id: str,
        event: AgentDomainEvent,
        *,
        conversation_id: str | None = None,
    ) -> None:
        await self.dispatch_event(project_id, event, conversation_id)


def _event_payload_v2(
    project_id: str,
    event: AgentDomainEvent,
    conversation_id: str | None,
) -> dict[str, object]:
    return {
        "project_id": project_id,
        "conversation_id": conversation_id,
        "event": event.model_dump(mode="json"),
    }


async def _publish_event_payload_v2(
    sandbox: SandboxApplicationResolverProtocolV2,
    payload: object,
    *,
    event_model: type[AgentDomainEvent],
    expected_event_type: AgentEventType,
) -> None:
    if not _is_string_keyed_mapping_v2(payload):
        raise RuntimeV2Error(
            "invalid_artifact_event_payload",
            "Artifact event payload must be an object",
        )
    project_id = payload.get("project_id")
    conversation_id = payload.get("conversation_id")
    event_payload = payload.get("event")
    if (
        not isinstance(project_id, str)
        or not project_id
        or (conversation_id is not None and not isinstance(conversation_id, str))
        or not isinstance(event_payload, Mapping)
    ):
        raise RuntimeV2Error(
            "invalid_artifact_event_payload",
            "Artifact event payload has invalid routing metadata",
        )
    try:
        event = event_model.model_validate(event_payload)
    except ValidationError as exc:
        raise RuntimeV2Error(
            "invalid_artifact_event_payload",
            "Artifact event payload does not match its declared domain event",
        ) from exc
    if event.event_type is not expected_event_type:
        raise RuntimeV2Error(
            "invalid_artifact_event_payload",
            "Artifact event type does not match its declared contract",
        )

    services = sandbox.resolve()
    _ = await services.event_publisher.publish_domain_event(
        project_id,
        event,
        conversation_id=conversation_id,
    )


def _is_string_keyed_mapping_v2(value: object) -> TypeGuard[Mapping[str, object]]:
    return isinstance(value, Mapping)


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

    async def dispatch_event(
        project_id: str,
        event: AgentDomainEvent,
        conversation_id: str | None,
    ) -> None:
        payload = _event_payload_v2(project_id, event, conversation_id)
        if isinstance(event, AgentArtifactCreatedEvent):
            _ = await context.dispatch(ARTIFACT_CREATED_EVENT_V2, payload)
        elif isinstance(event, AgentArtifactReadyEvent):
            _ = await context.dispatch(ARTIFACT_READY_EVENT_V2, payload)
        elif isinstance(event, AgentArtifactErrorEvent):
            _ = await context.dispatch(ARTIFACT_ERROR_EVENT_V2, payload)
        elif isinstance(event, AgentArtifactsBatchEvent):
            _ = await context.dispatch(ARTIFACTS_BATCH_EVENT_V2, payload)
        else:
            raise RuntimeV2Error(
                "unsupported_artifact_event",
                f"Unsupported Artifact event {type(event).__name__}",
            )

    async def publish_created(payload: object) -> None:
        await _publish_event_payload_v2(
            sandbox,
            payload,
            event_model=AgentArtifactCreatedEvent,
            expected_event_type=AgentEventType.ARTIFACT_CREATED,
        )

    async def publish_ready(payload: object) -> None:
        await _publish_event_payload_v2(
            sandbox,
            payload,
            event_model=AgentArtifactReadyEvent,
            expected_event_type=AgentEventType.ARTIFACT_READY,
        )

    async def publish_error(payload: object) -> None:
        await _publish_event_payload_v2(
            sandbox,
            payload,
            event_model=AgentArtifactErrorEvent,
            expected_event_type=AgentEventType.ARTIFACT_ERROR,
        )

    async def publish_batch(payload: object) -> None:
        await _publish_event_payload_v2(
            sandbox,
            payload,
            event_model=AgentArtifactsBatchEvent,
            expected_event_type=AgentEventType.ARTIFACTS_BATCH,
        )

    _ = context.on(ARTIFACT_CREATED_EVENT_V2, publish_created)
    _ = context.on(ARTIFACT_READY_EVENT_V2, publish_ready)
    _ = context.on(ARTIFACT_ERROR_EVENT_V2, publish_error)
    _ = context.on(ARTIFACTS_BATCH_EVENT_V2, publish_batch)
    _ = context.provide(
        ARTIFACT_EVENT_PUBLISHER_SERVICE_V2,
        TypedArtifactEventPublisherV2(dispatch_event=dispatch_event),
        label="artifact-event-publisher",
    )


def artifact_event_publisher_definition_v2() -> PluginDefinitionV2:
    """Return the typed Artifact event Provider and transport handler module."""
    return PluginDefinitionV2(
        module_ref=ARTIFACT_EVENT_PUBLISHER_MODULE_V2,
        contract_digest=generated_contract_digest_v2(ARTIFACT_EVENT_PUBLISHER_MODULE_V2),
        apply=_apply_artifact_event_publisher_v2,
    )


__all__ = [
    "ARTIFACTS_BATCH_EVENT_V2",
    "ARTIFACT_CREATED_EVENT_V2",
    "ARTIFACT_ERROR_EVENT_V2",
    "ARTIFACT_EVENT_PUBLISHER_MODULE_V2",
    "ARTIFACT_EVENT_PUBLISHER_SANDBOX_INJECT_V2",
    "ARTIFACT_EVENT_PUBLISHER_SERVICE_V2",
    "ARTIFACT_LIFECYCLE_EVENTS_V2",
    "ARTIFACT_READY_EVENT_V2",
    "ArtifactEventPublisherProtocolV2",
    "TypedArtifactEventPublisherV2",
    "artifact_event_publisher_definition_v2",
]
