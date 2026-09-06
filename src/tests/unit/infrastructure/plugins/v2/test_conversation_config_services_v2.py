"""V2 application seam for conversation configuration mutations."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import Conversation
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.agent_definition import (
    AGENT_DEFINITION_MODULE_V2,
    AGENT_DEFINITION_RESOLVER_SERVICE_V2,
)
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.conversation_access_services import (
    CONVERSATION_ACCESS_MODULE_V2,
    CONVERSATION_ACCESS_SERVICE_V2,
    ConversationAccessResolverProtocolV2,
)
from src.infrastructure.plugins.v2.conversation_collection_services import (
    InvalidConversationAgentSelectionV2,
)
from src.infrastructure.plugins.v2.conversation_config_services import (
    CONVERSATION_CONFIG_AGENT_DEFINITIONS_INJECT_V2,
    CONVERSATION_CONFIG_CONVERSATION_ACCESS_INJECT_V2,
    CONVERSATION_CONFIG_MODULE_V2,
    CONVERSATION_CONFIG_SERVICE_V2,
    ConversationConfigPatchV2,
    ConversationConfigResolverProtocolV2,
    ConversationConfigResolverV2,
    ConversationConfigServiceV2,
)
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.tests.unit.infrastructure.plugins.v2.runtime_test_support import (
    disable_service_provider_closure_v2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


def _service(
    conversation: Conversation | None,
    *,
    resolved_agent: object | None = None,
) -> tuple[ConversationConfigServiceV2, Any, AsyncMock]:
    access = SimpleNamespace(
        get_conversation=AsyncMock(return_value=conversation),
        save_scoped_conversation=AsyncMock(return_value=conversation),
        cache=SimpleNamespace(invalidate=AsyncMock()),
    )
    resolve = AsyncMock(return_value=resolved_agent)
    service = ConversationConfigServiceV2(
        access=cast(Any, access),
        agent_definitions=cast(Any, SimpleNamespace(resolve=resolve)),
    )
    return service, access, resolve


async def test_resolver_builds_config_service_from_one_operation_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=953,
        version=953,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="conversation-config",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(CONVERSATION_CONFIG_SERVICE_V2)

            assert isinstance(resolver, ConversationConfigResolverV2)
            service = resolver.resolve(operation)
            assert isinstance(service, ConversationConfigServiceV2)
            assert cast(Any, service.access.repository)._session is db
    finally:
        await db.close()
        await host.close()


def test_config_consumer_uses_explicit_access_and_agent_definition_aliases() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    entries = {entry.module_ref: entry for entry in document.entries}
    ordered_modules = tuple(entry.module_ref for entry in document.entries)

    assert entries[CONVERSATION_CONFIG_MODULE_V2].inject == {
        CONVERSATION_CONFIG_CONVERSATION_ACCESS_INJECT_V2: CONVERSATION_ACCESS_SERVICE_V2,
        CONVERSATION_CONFIG_AGENT_DEFINITIONS_INJECT_V2: AGENT_DEFINITION_RESOLVER_SERVICE_V2,
    }
    assert ordered_modules.index(CONVERSATION_ACCESS_MODULE_V2) < ordered_modules.index(
        CONVERSATION_CONFIG_MODULE_V2
    )
    assert ordered_modules.index(AGENT_DEFINITION_MODULE_V2) < ordered_modules.index(
        CONVERSATION_CONFIG_MODULE_V2
    )


async def test_missing_agent_definition_provider_rejects_config_candidate() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    disabled = disable_service_provider_closure_v2(
        document,
        manifest,
        missing_service=AGENT_DEFINITION_RESOLVER_SERVICE_V2,
        kept_consumer_module_ref=CONVERSATION_CONFIG_MODULE_V2,
    )
    snapshot = compose_profile_v2(
        disabled,
        {manifest.plugin_id: manifest},
        generation=954,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-conversation-config" in str(error.value)


async def test_config_update_preserves_omitted_fields_and_normalizes_explicit_values() -> None:
    original_config = {
        "selected_agent_id": "agent-old",
        "llm_model_override": "model-old",
        "llm_overrides": {"temperature": 0.5},
        "capability_mode": "code",
    }
    conversation = Conversation(
        id="conversation-a",
        project_id="project-a",
        tenant_id="tenant-a",
        user_id="user-a",
        title="Config",
        agent_config=dict(original_config),
    )
    service, access, resolve = _service(
        conversation,
        resolved_agent=SimpleNamespace(id="agent-new"),
    )

    omitted = await service.update_conversation_config(
        conversation_id=conversation.id,
        project_id=conversation.project_id,
        tenant_id=conversation.tenant_id,
        user_id=conversation.user_id,
        patch=ConversationConfigPatchV2(),
    )
    assert omitted is conversation
    assert conversation.agent_config == original_config
    resolve.assert_not_awaited()

    updated = await service.update_conversation_config(
        conversation_id=conversation.id,
        project_id=conversation.project_id,
        tenant_id=conversation.tenant_id,
        user_id=conversation.user_id,
        patch=ConversationConfigPatchV2(
            selected_agent_id_present=True,
            selected_agent_id=" agent-new ",
            llm_model_override_present=True,
            llm_model_override=" model-new ",
            llm_overrides_present=True,
            llm_overrides={"temperature": 0.2, "max_tokens": None},
        ),
    )

    assert updated is conversation
    assert conversation.agent_config == {
        "selected_agent_id": "agent-new",
        "llm_model_override": "model-new",
        "llm_overrides": {"temperature": 0.2},
        "capability_mode": "code",
    }
    resolve.assert_awaited_once_with(
        agent_id="agent-new",
        tenant_id="tenant-a",
        project_id="project-a",
    )
    assert access.save_scoped_conversation.await_count == 2
    await service.after_update_committed(conversation.project_id)
    access.cache.invalidate.assert_awaited_once_with(conversation.project_id)


async def test_config_update_fails_closed_for_missing_agent_or_conversation() -> None:
    conversation = Conversation(
        id="conversation-a",
        project_id="project-a",
        tenant_id="tenant-a",
        user_id="user-a",
        title="Config",
    )
    service, access, _resolve = _service(conversation)

    with pytest.raises(InvalidConversationAgentSelectionV2):
        await service.update_conversation_config(
            conversation_id=conversation.id,
            project_id=conversation.project_id,
            tenant_id=conversation.tenant_id,
            user_id=conversation.user_id,
            patch=ConversationConfigPatchV2(
                selected_agent_id_present=True,
                selected_agent_id="missing-agent",
            ),
        )
    access.save_scoped_conversation.assert_not_awaited()

    missing_service, missing_access, missing_resolve = _service(None)
    assert (
        await missing_service.update_conversation_config(
            conversation_id="missing",
            project_id="project-a",
            tenant_id="tenant-a",
            user_id="user-a",
            patch=ConversationConfigPatchV2(
                selected_agent_id_present=True,
                selected_agent_id="agent-a",
            ),
        )
        is None
    )
    missing_resolve.assert_not_awaited()
    missing_access.save_scoped_conversation.assert_not_awaited()


def test_config_resolver_protocol_is_structural() -> None:
    resolver = SimpleNamespace(resolve=lambda _operation: object())

    assert isinstance(resolver, ConversationConfigResolverProtocolV2)
    assert isinstance(resolver, ConversationAccessResolverProtocolV2)
