"""Typed Artifact event contracts and generation lifecycle coverage."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, call

import pytest

from src.domain.events.agent_events import (
    AgentArtifactCreatedEvent,
    AgentArtifactErrorEvent,
    AgentArtifactReadyEvent,
    AgentArtifactsBatchEvent,
    AgentDomainEvent,
    ArtifactInfo,
)
from src.domain.model.plugins.generated_v2 import EventModeV2, ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.artifact_events import (
    ARTIFACT_CREATED_EVENT_V2,
    ARTIFACT_ERROR_EVENT_V2,
    ARTIFACT_EVENT_PUBLISHER_MODULE_V2,
    ARTIFACT_EVENT_PUBLISHER_SERVICE_V2,
    ARTIFACT_LIFECYCLE_EVENTS_V2,
    ARTIFACT_READY_EVENT_V2,
    ARTIFACTS_BATCH_EVENT_V2,
    TypedArtifactEventPublisherV2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import (
    ContextV2,
    FiberPhaseV2,
    LoaderV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeGenerationV2,
    RuntimeV2Error,
)
from src.infrastructure.plugins.v2.sandbox_runtime import (
    SANDBOX_APPLICATION_MODULE_V2,
    SANDBOX_APPLICATION_SERVICE_V2,
    SandboxApplicationServicesV2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


class _FakeSandboxResolver:
    def __init__(self, public_publisher: object) -> None:
        self._services = cast(
            SandboxApplicationServicesV2,
            SimpleNamespace(event_publisher=public_publisher),
        )

    def resolve(self, operation: OperationContextV2 | None = None) -> SandboxApplicationServicesV2:
        del operation
        return self._services


async def _stage(public_publisher: object, *, generation: int) -> RuntimeGenerationV2:
    document = load_profile_document_v2(_PROFILE_PATH)
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(document, {manifest.plugin_id: manifest}, generation=generation)
    definitions = builtin_runtime_definitions_v2()
    sandbox_definition = next(
        definition
        for definition in definitions
        if definition.module_ref == SANDBOX_APPLICATION_MODULE_V2
    )
    resolver = _FakeSandboxResolver(public_publisher)

    def apply_fake_sandbox(context: ContextV2, _config: Mapping[str, Any]) -> None:
        _ = context.provide(
            SANDBOX_APPLICATION_SERVICE_V2,
            resolver,
            label="fake-sandbox-application",
        )

    fake_sandbox_definition = PluginDefinitionV2(
        module_ref=sandbox_definition.module_ref,
        contract_digest=sandbox_definition.contract_digest,
        apply=apply_fake_sandbox,
    )
    return await LoaderV2(
        tuple(
            fake_sandbox_definition
            if definition.module_ref == SANDBOX_APPLICATION_MODULE_V2
            else definition
            for definition in definitions
        )
    ).stage(snapshot)


def _events() -> tuple[AgentDomainEvent, ...]:
    return (
        AgentArtifactCreatedEvent(
            artifact_id="artifact-created",
            sandbox_id="sandbox-a",
            tool_execution_id="tool-a",
            filename="created.txt",
            mime_type="text/plain",
            category="document",
            size_bytes=7,
            source_tool="write",
            source_path="/workspace/created.txt",
        ),
        AgentArtifactReadyEvent(
            artifact_id="artifact-ready",
            sandbox_id="sandbox-a",
            tool_execution_id="tool-a",
            filename="ready.txt",
            mime_type="text/plain",
            category="document",
            size_bytes=5,
            url="https://storage.invalid/ready",
            preview_url=None,
            source_tool="write",
            metadata={"revision": 1},
        ),
        AgentArtifactErrorEvent(
            artifact_id="artifact-error",
            sandbox_id="sandbox-a",
            tool_execution_id="tool-a",
            filename="error.txt",
            error="upload failed",
        ),
        AgentArtifactsBatchEvent(
            sandbox_id="sandbox-a",
            tool_execution_id="tool-a",
            artifacts=[
                ArtifactInfo(
                    id="artifact-batch",
                    filename="batch.txt",
                    mime_type="text/plain",
                    category="document",
                    size_bytes=5,
                    url="https://storage.invalid/batch",
                    source_tool="write",
                    metadata={"revision": 1},
                )
            ],
            source_tool="write",
        ),
    )


async def test_four_artifact_events_round_trip_through_declared_dispatch() -> None:
    public_publisher = SimpleNamespace(publish_domain_event=AsyncMock(return_value="message-a"))
    generation = await _stage(public_publisher, generation=163)
    try:
        publisher = generation.resolve(
            ARTIFACT_EVENT_PUBLISHER_SERVICE_V2,
            ScopeV2(kind=ScopeKindV2.ROOT),
        )
        assert isinstance(publisher, TypedArtifactEventPublisherV2)
        events = _events()

        for event in events:
            await publisher.publish(
                "project-a",
                event,
                conversation_id="conversation-a",
            )

        assert public_publisher.publish_domain_event.await_args_list == [
            call(
                "project-a",
                event,
                conversation_id="conversation-a",
            )
            for event in events
        ]
    finally:
        await generation.dispose()


async def test_artifact_event_schema_rejects_cross_event_payload() -> None:
    public_publisher = SimpleNamespace(publish_domain_event=AsyncMock(return_value="message-a"))
    generation = await _stage(public_publisher, generation=164)
    event = cast(AgentArtifactCreatedEvent, _events()[0])
    payload = {
        "project_id": "project-a",
        "conversation_id": None,
        "event": {
            **event.model_dump(mode="json"),
            "event_type": "artifact_ready",
        },
    }
    operation = OperationContextV2(
        generation=generation,
        operation_id="artifact-schema",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    )
    try:
        async with operation:
            with pytest.raises(RuntimeV2Error) as error:
                await operation.dispatch(ARTIFACT_CREATED_EVENT_V2, payload)

        assert error.value.code == "invalid_event_payload"
        public_publisher.publish_domain_event.assert_not_awaited()
    finally:
        await generation.dispose()


async def test_generation_disposal_removes_all_artifact_event_handlers() -> None:
    public_publisher = SimpleNamespace(publish_domain_event=AsyncMock(return_value="message-a"))
    generation = await _stage(public_publisher, generation=165)
    publisher = generation.resolve(
        ARTIFACT_EVENT_PUBLISHER_SERVICE_V2,
        ScopeV2(kind=ScopeKindV2.ROOT),
    )
    assert isinstance(publisher, TypedArtifactEventPublisherV2)
    event = _events()[0]

    await publisher.publish("project-a", event, conversation_id=None)
    event_fiber = next(
        fiber
        for fiber in generation.fibers
        if fiber.entry.module_ref == ARTIFACT_EVENT_PUBLISHER_MODULE_V2
    )
    await generation.dispose()

    assert event_fiber.phase is FiberPhaseV2.DISPOSED
    assert {
        diagnostic.label
        for diagnostic in event_fiber.diagnostics().effects
        if diagnostic.label.startswith("event:")
    } == {f"event:{event_name}" for event_name in ARTIFACT_LIFECYCLE_EVENTS_V2}

    await publisher.publish("project-a", event, conversation_id=None)
    assert public_publisher.publish_domain_event.await_count == 1


def test_manifest_declares_exact_serial_artifact_event_contracts() -> None:
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    module = next(
        module
        for module in manifest.modules
        if module.module_ref == ARTIFACT_EVENT_PUBLISHER_MODULE_V2
    )
    emitted = {event.event: event for event in module.contract.events.emits}
    handled = {event.event: event for event in module.contract.events.handles}
    expected_event_types = {
        ARTIFACT_CREATED_EVENT_V2: "artifact_created",
        ARTIFACT_READY_EVENT_V2: "artifact_ready",
        ARTIFACT_ERROR_EVENT_V2: "artifact_error",
        ARTIFACTS_BATCH_EVENT_V2: "artifacts_batch",
    }

    assert tuple(emitted) == ARTIFACT_LIFECYCLE_EVENTS_V2
    assert tuple(handled) == ARTIFACT_LIFECYCLE_EVENTS_V2
    for event_name, event_type in expected_event_types.items():
        emit = emitted[event_name]
        handle = handled[event_name]
        assert emit == handle
        assert emit.mode is EventModeV2.SERIAL
        assert emit.result_schema["type"] == "null"
        assert emit.payload_schema["additionalProperties"] is False
        assert set(emit.payload_schema["required"]) == {
            "conversation_id",
            "event",
            "project_id",
        }
        event_schema = cast(Mapping[str, Any], emit.payload_schema["properties"])["event"]
        assert event_schema["additionalProperties"] is False
        properties = cast(Mapping[str, Any], event_schema["properties"])
        assert cast(Mapping[str, Any], properties["event_type"])["const"] == event_type
