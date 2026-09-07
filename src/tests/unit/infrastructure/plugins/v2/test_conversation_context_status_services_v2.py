"""V2 application seam for conversation context-status queries."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import Conversation
from src.domain.model.agent.conversation.context_summary import ContextSummary
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.conversation_access_services import (
    CONVERSATION_ACCESS_MODULE_V2,
    CONVERSATION_ACCESS_SERVICE_V2,
)
from src.infrastructure.plugins.v2.conversation_context_status_services import (
    CONTEXT_SUMMARY_PROVIDER_MODULE_V2,
    CONTEXT_SUMMARY_PROVIDER_SERVICE_V2,
    CONVERSATION_CONTEXT_STATUS_ACCESS_INJECT_V2,
    CONVERSATION_CONTEXT_STATUS_MODULE_V2,
    CONVERSATION_CONTEXT_STATUS_SERVICE_V2,
    CONVERSATION_CONTEXT_STATUS_SUMMARIES_INJECT_V2,
    ConversationContextStatusResolverV2,
    ConversationContextStatusServiceV2,
)
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import (
    ContextV2,
    LoaderV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
)
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


def _conversation() -> Conversation:
    return Conversation(
        id="conversation-a",
        project_id="project-a",
        tenant_id="tenant-a",
        user_id="user-a",
        title="Context status",
        message_count=17,
    )


def _summary() -> ContextSummary:
    return ContextSummary(
        summary_text="Earlier work was compressed.",
        summary_tokens=321,
        messages_covered_up_to=42,
        messages_covered_count=11,
        compression_level="l2_summarize",
    )


def _service(
    conversation: Conversation | None,
    summary: ContextSummary | None,
) -> tuple[ConversationContextStatusServiceV2, AsyncMock, AsyncMock]:
    get_conversation = AsyncMock(return_value=conversation)
    get_summary = AsyncMock(return_value=summary)
    service = ConversationContextStatusServiceV2(
        access=cast(Any, SimpleNamespace(get_conversation=get_conversation)),
        summaries=cast(Any, SimpleNamespace(get_summary=get_summary)),
    )
    return service, get_conversation, get_summary


async def test_resolver_builds_status_service_from_one_operation_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=959,
        version=959,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="conversation-context-status",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(CONVERSATION_CONTEXT_STATUS_SERVICE_V2)

            assert isinstance(resolver, ConversationContextStatusResolverV2)
            service = resolver.resolve(operation)
            assert isinstance(service, ConversationContextStatusServiceV2)
            assert cast(Any, service.access.repository)._session is db
            assert cast(Any, service.summaries)._session is db
    finally:
        await db.close()
        await host.close()


def test_status_consumer_uses_explicit_access_and_summary_aliases() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    entries = {entry.module_ref: entry for entry in document.entries}
    ordered_modules = tuple(entry.module_ref for entry in document.entries)

    assert entries[CONVERSATION_CONTEXT_STATUS_MODULE_V2].inject == {
        CONVERSATION_CONTEXT_STATUS_ACCESS_INJECT_V2: CONVERSATION_ACCESS_SERVICE_V2,
        CONVERSATION_CONTEXT_STATUS_SUMMARIES_INJECT_V2: CONTEXT_SUMMARY_PROVIDER_SERVICE_V2,
    }
    assert ordered_modules.index(CONVERSATION_ACCESS_MODULE_V2) < ordered_modules.index(
        CONVERSATION_CONTEXT_STATUS_MODULE_V2
    )
    assert ordered_modules.index(CONTEXT_SUMMARY_PROVIDER_MODULE_V2) < ordered_modules.index(
        CONVERSATION_CONTEXT_STATUS_MODULE_V2
    )


async def test_missing_summary_provider_rejects_status_candidate() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == CONTEXT_SUMMARY_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        disabled,
        {manifest.plugin_id: manifest},
        generation=960,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-conversation-context-status" in str(error.value)


async def test_invalid_profile_selected_summary_provider_fails_closed() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        document,
        {manifest.plugin_id: manifest},
        generation=961,
    )
    definitions = builtin_runtime_definitions_v2()
    provider_definition = next(
        definition
        for definition in definitions
        if definition.module_ref == CONTEXT_SUMMARY_PROVIDER_MODULE_V2
    )

    def apply_invalid_provider(context: ContextV2, _config: Mapping[str, Any]) -> None:
        _ = context.provide(
            CONTEXT_SUMMARY_PROVIDER_SERVICE_V2,
            object(),
            label="invalid-context-summary-provider",
        )

    invalid_provider = PluginDefinitionV2(
        module_ref=provider_definition.module_ref,
        contract_digest=provider_definition.contract_digest,
        apply=apply_invalid_provider,
    )
    definitions_with_invalid_provider = tuple(
        invalid_provider
        if definition.module_ref == CONTEXT_SUMMARY_PROVIDER_MODULE_V2
        else definition
        for definition in definitions
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(definitions_with_invalid_provider).stage(snapshot)

    assert error.value.code == "invalid_context_summary_provider"
    assert "invalid implementation" in str(error.value)


@pytest.mark.parametrize(
    ("summary", "expected"),
    [
        (
            None,
            {
                "conversation_id": "conversation-a",
                "message_count": 17,
                "has_summary": False,
                "summary_tokens": 0,
                "messages_in_summary": 0,
                "compression_level": "none",
                "from_cache": False,
            },
        ),
        (
            _summary(),
            {
                "conversation_id": "conversation-a",
                "message_count": 17,
                "has_summary": True,
                "summary_tokens": 321,
                "messages_in_summary": 11,
                "compression_level": "l2_summarize",
                "from_cache": True,
            },
        ),
    ],
)
async def test_status_response_preserves_public_shape(
    summary: ContextSummary | None,
    expected: dict[str, object],
) -> None:
    conversation = _conversation()
    service, get_conversation, get_summary = _service(conversation, summary)

    status = await service.get_context_status(
        conversation_id=conversation.id,
        project_id=conversation.project_id,
        tenant_id=conversation.tenant_id,
        user_id=conversation.user_id,
    )

    assert status is not None
    assert status.to_dict() == expected
    get_conversation.assert_awaited_once_with(
        conversation_id=conversation.id,
        project_id=conversation.project_id,
        user_id=conversation.user_id,
    )
    get_summary.assert_awaited_once_with(conversation.id)


@pytest.mark.parametrize("conversation", [None, _conversation()])
async def test_missing_or_cross_tenant_conversation_fails_closed(
    conversation: Conversation | None,
) -> None:
    service, _get_conversation, get_summary = _service(conversation, _summary())
    tenant_id = "tenant-a" if conversation is None else "tenant-other"

    status = await service.get_context_status(
        conversation_id="conversation-a",
        project_id="project-a",
        tenant_id=tenant_id,
        user_id="user-a",
    )

    assert status is None
    get_summary.assert_not_awaited()


def test_manifest_declares_summary_provider_before_status_consumer() -> None:
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    modules = {module.module_ref: module for module in manifest.modules}
    provider = modules[CONTEXT_SUMMARY_PROVIDER_MODULE_V2]
    consumer = modules[CONVERSATION_CONTEXT_STATUS_MODULE_V2]

    assert [provided.service for provided in provider.contract.services.provides] == [
        CONTEXT_SUMMARY_PROVIDER_SERVICE_V2
    ]
    assert {
        required.alias: required.service for required in consumer.contract.services.requires
    } == {
        CONVERSATION_CONTEXT_STATUS_ACCESS_INJECT_V2: CONVERSATION_ACCESS_SERVICE_V2,
        CONVERSATION_CONTEXT_STATUS_SUMMARIES_INJECT_V2: CONTEXT_SUMMARY_PROVIDER_SERVICE_V2,
    }
