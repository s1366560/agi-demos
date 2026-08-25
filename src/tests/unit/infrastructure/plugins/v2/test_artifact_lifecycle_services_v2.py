"""V2 service seams for Artifact lifecycle storage and event publication."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest

from src.domain.events.agent_events import AgentArtifactCreatedEvent
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.artifact_content_gc_runtime import (
    ASYNC_SESSION_FACTORY_MODULE_V2,
    ASYNC_SESSION_FACTORY_SERVICE_V2,
    OBJECT_STORAGE_PROVIDER_MODULE_V2,
    OBJECT_STORAGE_SERVICE_V2,
    AsyncSessionFactoryServiceV2,
    ObjectStorageServiceV2,
)
from src.infrastructure.plugins.v2.artifact_lifecycle_services import (
    ARTIFACT_EVENT_PUBLISHER_MODULE_V2,
    ARTIFACT_EVENT_PUBLISHER_SANDBOX_INJECT_V2,
    ARTIFACT_EVENT_PUBLISHER_SERVICE_V2,
    ARTIFACT_LIFECYCLE_APPLICATION_MODULE_V2,
    ARTIFACT_LIFECYCLE_APPLICATION_SERVICE_V2,
    ARTIFACT_LIFECYCLE_EVENTS_INJECT_V2,
    ARTIFACT_LIFECYCLE_SESSIONS_INJECT_V2,
    ARTIFACT_LIFECYCLE_STORAGE_INJECT_V2,
    ArtifactLifecycleApplicationServiceV2,
    SandboxArtifactEventPublisherV2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.sandbox_runtime import (
    SANDBOX_APPLICATION_MODULE_V2,
    SANDBOX_APPLICATION_SERVICE_V2,
    SandboxApplicationResolverProtocolV2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def test_generation_owns_one_durable_artifact_service() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=160,
        version=160,
    )
    assert publication.accepted is True
    try:
        async with await host.acquire() as generation:
            scope = ScopeV2(kind=ScopeKindV2.ROOT)
            lifecycle = generation.resolve(ARTIFACT_LIFECYCLE_APPLICATION_SERVICE_V2, scope)
            sessions = generation.resolve(ASYNC_SESSION_FACTORY_SERVICE_V2, scope)
            storage = generation.resolve(OBJECT_STORAGE_SERVICE_V2, scope)
            events = generation.resolve(ARTIFACT_EVENT_PUBLISHER_SERVICE_V2, scope)

            assert isinstance(lifecycle, ArtifactLifecycleApplicationServiceV2)
            assert isinstance(sessions, AsyncSessionFactoryServiceV2)
            assert isinstance(storage, ObjectStorageServiceV2)
            assert isinstance(events, SandboxArtifactEventPublisherV2)
            assert lifecycle.artifact._storage is storage.storage_service
            assert lifecycle.artifact._repository._session_factory is sessions.factory
            assert lifecycle.artifact._event_publisher.__self__ is events
            assert lifecycle.artifact._bucket_prefix == "artifacts"
            assert lifecycle.artifact._url_expiration == 604_800
    finally:
        await host.close()


async def test_event_provider_uses_only_the_public_sandbox_publisher_seam() -> None:
    public_publisher = SimpleNamespace(publish_domain_event=AsyncMock(return_value="msg-1"))
    sandbox_resolver = SimpleNamespace(
        resolve=Mock(return_value=SimpleNamespace(event_publisher=public_publisher))
    )
    publisher = SandboxArtifactEventPublisherV2(
        sandbox=cast(SandboxApplicationResolverProtocolV2, sandbox_resolver)
    )
    event = AgentArtifactCreatedEvent(
        artifact_id="artifact-1",
        sandbox_id="sandbox-1",
        filename="report.txt",
        mime_type="text/plain",
        category="document",
        size_bytes=12,
    )

    await publisher.publish(
        "project-1",
        event,
        conversation_id="conversation-1",
    )

    public_publisher.publish_domain_event.assert_awaited_once_with(
        "project-1",
        event,
        conversation_id="conversation-1",
    )
    assert not hasattr(publisher, "_event_bus")


def test_profile_declares_event_and_lifecycle_provider_aliases() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    entries = {entry.module_ref: entry for entry in document.entries}
    ordered_modules = tuple(entry.module_ref for entry in document.entries)

    assert entries[ARTIFACT_EVENT_PUBLISHER_MODULE_V2].inject == {
        ARTIFACT_EVENT_PUBLISHER_SANDBOX_INJECT_V2: SANDBOX_APPLICATION_SERVICE_V2,
    }
    assert entries[ARTIFACT_LIFECYCLE_APPLICATION_MODULE_V2].inject == {
        ARTIFACT_LIFECYCLE_SESSIONS_INJECT_V2: ASYNC_SESSION_FACTORY_SERVICE_V2,
        ARTIFACT_LIFECYCLE_STORAGE_INJECT_V2: OBJECT_STORAGE_SERVICE_V2,
        ARTIFACT_LIFECYCLE_EVENTS_INJECT_V2: ARTIFACT_EVENT_PUBLISHER_SERVICE_V2,
    }
    event_index = ordered_modules.index(ARTIFACT_EVENT_PUBLISHER_MODULE_V2)
    lifecycle_index = ordered_modules.index(ARTIFACT_LIFECYCLE_APPLICATION_MODULE_V2)
    assert ordered_modules.index(SANDBOX_APPLICATION_MODULE_V2) < event_index
    assert ordered_modules.index(ASYNC_SESSION_FACTORY_MODULE_V2) < lifecycle_index
    assert ordered_modules.index(OBJECT_STORAGE_PROVIDER_MODULE_V2) < lifecycle_index
    assert event_index < lifecycle_index


@pytest.mark.parametrize(
    ("disabled_module", "consumer_module", "consumer_entry_id", "provider_modules"),
    (
        (
            SANDBOX_APPLICATION_MODULE_V2,
            ARTIFACT_EVENT_PUBLISHER_MODULE_V2,
            "builtin-artifact-event-publisher",
            frozenset({SANDBOX_APPLICATION_MODULE_V2}),
        ),
        (
            ASYNC_SESSION_FACTORY_MODULE_V2,
            ARTIFACT_LIFECYCLE_APPLICATION_MODULE_V2,
            "builtin-artifact-lifecycle-services",
            frozenset(
                {
                    ASYNC_SESSION_FACTORY_MODULE_V2,
                    OBJECT_STORAGE_PROVIDER_MODULE_V2,
                    ARTIFACT_EVENT_PUBLISHER_MODULE_V2,
                }
            ),
        ),
        (
            OBJECT_STORAGE_PROVIDER_MODULE_V2,
            ARTIFACT_LIFECYCLE_APPLICATION_MODULE_V2,
            "builtin-artifact-lifecycle-services",
            frozenset(
                {
                    ASYNC_SESSION_FACTORY_MODULE_V2,
                    OBJECT_STORAGE_PROVIDER_MODULE_V2,
                    ARTIFACT_EVENT_PUBLISHER_MODULE_V2,
                }
            ),
        ),
        (
            ARTIFACT_EVENT_PUBLISHER_MODULE_V2,
            ARTIFACT_LIFECYCLE_APPLICATION_MODULE_V2,
            "builtin-artifact-lifecycle-services",
            frozenset(
                {
                    ASYNC_SESSION_FACTORY_MODULE_V2,
                    OBJECT_STORAGE_PROVIDER_MODULE_V2,
                    ARTIFACT_EVENT_PUBLISHER_MODULE_V2,
                }
            ),
        ),
    ),
)
async def test_missing_provider_is_rejected_before_lifecycle_code_loads(
    disabled_module: str,
    consumer_module: str,
    consumer_entry_id: str,
    provider_modules: frozenset[str],
) -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    target_entry = next(entry for entry in document.entries if entry.module_ref == consumer_module)
    if consumer_module == ARTIFACT_LIFECYCLE_APPLICATION_MODULE_V2:
        moved_modules = {*provider_modules, consumer_module}
        moved_entries = tuple(
            entry for entry in document.entries if entry.module_ref in moved_modules
        )
        remaining_entries = tuple(
            entry for entry in document.entries if entry.module_ref not in moved_modules
        )
        anchor_index = next(
            index
            for index, entry in enumerate(remaining_entries)
            if entry.module_ref == SANDBOX_APPLICATION_MODULE_V2
        )
        isolated_entries = (
            *remaining_entries[: anchor_index + 1],
            *moved_entries,
            *remaining_entries[anchor_index + 1 :],
        )
    else:
        entries_without_target = tuple(
            entry for entry in document.entries if entry.module_ref != consumer_module
        )
        target_index = (
            max(
                index
                for index, entry in enumerate(entries_without_target)
                if entry.module_ref in provider_modules
            )
            + 1
        )
        isolated_entries = (
            *entries_without_target[:target_index],
            target_entry,
            *entries_without_target[target_index:],
        )
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False) if entry.module_ref == disabled_module else entry
            for entry in isolated_entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=161)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert consumer_entry_id in str(error.value)


def test_lifecycle_contract_has_no_implicit_container_or_implementation_alias() -> None:
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    modules = {module.module_ref: module for module in manifest.modules}

    lifecycle = modules[ARTIFACT_LIFECYCLE_APPLICATION_MODULE_V2]
    assert {requirement.alias for requirement in lifecycle.contract.services.requires} == {
        ARTIFACT_LIFECYCLE_SESSIONS_INJECT_V2,
        ARTIFACT_LIFECYCLE_STORAGE_INJECT_V2,
        ARTIFACT_LIFECYCLE_EVENTS_INJECT_V2,
    }
    assert all(
        "container" not in requirement.alias for requirement in lifecycle.contract.services.requires
    )
    assert all(
        "implementation" not in requirement.alias
        for requirement in lifecycle.contract.services.requires
    )


def test_legacy_container_delegates_event_fanout_to_the_public_publisher_seam() -> None:
    source = (_ROOT / "src/configuration/containers/agent_container.py").read_text(encoding="utf-8")

    assert "sandbox_event_pub._event_bus" not in source
    assert "sandbox_event_pub._publish" not in source
    assert "_publish_to_agent_stream" not in source
    assert "event_publisher=sandbox_event_pub.publish_domain_event" in source
