"""V2 application seam for conversation title and summary generation."""

from __future__ import annotations

import inspect
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import Conversation
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.conversation_access_services import (
    CONVERSATION_ACCESS_MODULE_V2,
    CONVERSATION_ACCESS_SERVICE_V2,
)
from src.infrastructure.plugins.v2.conversation_enrichment_judge import (
    CONVERSATION_ENRICHMENT_JUDGE_MODULE_V2,
    CONVERSATION_ENRICHMENT_JUDGE_SERVICE_V2,
    CONVERSATION_ENRICHMENT_LLM_CLIENTS_INJECT_V2,
    ConversationEnrichmentAuditV2,
    ConversationEnrichmentMessageV2,
    ConversationEnrichmentResultV2,
)
from src.infrastructure.plugins.v2.conversation_generation_services import (
    CONVERSATION_GENERATION_ACCESS_INJECT_V2,
    CONVERSATION_GENERATION_ENRICHMENT_JUDGE_INJECT_V2,
    CONVERSATION_GENERATION_MODULE_V2,
    CONVERSATION_GENERATION_SERVICE_V2,
    CONVERSATION_GENERATION_SESSION_LOG_INJECT_V2,
    ConversationGenerationResolverV2,
    ConversationGenerationServiceV2,
    ConversationGenerationSourceMissingV2,
)
from src.infrastructure.plugins.v2.llm_client_service import (
    TENANT_LLM_CLIENT_FACTORY_MODULE_V2,
    TENANT_LLM_CLIENT_FACTORY_SERVICE_V2,
)
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.session_event_log import (
    SESSION_EVENT_LOG_MODULE_V2,
    SESSION_EVENT_LOG_SERVICE_V2,
    SessionEventLogServiceV2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_SAVE_CONVERSATION = object()


def _conversation() -> Conversation:
    return Conversation(
        id="conversation-a",
        project_id="project-a",
        tenant_id="tenant-a",
        user_id="user-a",
        title="Before",
    )


def _service(
    *,
    conversation: Conversation | None,
    messages: list[dict[str, object]],
    judgment_value: str,
    save_result: object = _SAVE_CONVERSATION,
) -> tuple[ConversationGenerationServiceV2, Any, AsyncMock, AsyncMock]:
    session_log = AsyncMock()
    session_log.materialize_model_messages.return_value = messages

    async def save_scoped_conversation(**kwargs: Any) -> Conversation | None:
        if save_result is _SAVE_CONVERSATION:
            return cast(Conversation, kwargs["conversation"])
        return cast(Conversation | None, save_result)

    access = SimpleNamespace(
        get_conversation=AsyncMock(return_value=conversation),
        save_scoped_conversation=AsyncMock(side_effect=save_scoped_conversation),
        cache=SimpleNamespace(invalidate=AsyncMock()),
    )
    audit = ConversationEnrichmentAuditV2(
        agent_id="tenant-llm:model-a",
        tool_name="submit_conversation_enrichment_v2",
        input_json={},
        output_json={},
        rationale="Structured judgment",
        latency_ms=1,
    )
    judge = AsyncMock()
    judge.judge.return_value = ConversationEnrichmentResultV2(
        value=judgment_value,
        rationale="Structured judgment",
        audit=audit,
    )
    service = ConversationGenerationServiceV2(
        access=cast(Any, access),
        session_log=cast(Any, session_log),
        enrichment_judge=cast(Any, judge),
        tenant_id="tenant-a",
        project_id="project-a",
        user_id="user-a",
    )
    return service, access, session_log, judge


async def test_resolver_builds_generation_service_from_one_operation_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=956,
        version=956,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="conversation-generation",
                scope=ScopeV2(
                    kind=ScopeKindV2.PROJECT,
                    tenant_id="tenant-a",
                    project_id="project-a",
                ),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            _ = operation.provide(
                OPERATION_IDENTITY_SERVICE_V2,
                {
                    "tenant_id": "tenant-a",
                    "project_id": "project-a",
                    "user_id": "user-a",
                },
            )
            resolver = operation.require(CONVERSATION_GENERATION_SERVICE_V2)

            assert isinstance(resolver, ConversationGenerationResolverV2)
            service = resolver.resolve(operation)
            assert isinstance(service, ConversationGenerationServiceV2)
            assert service.tenant_id == "tenant-a"
            assert service.project_id == "project-a"
            assert service.user_id == "user-a"
            assert cast(Any, service.access.repository)._session is db
            assert isinstance(service.session_log, SessionEventLogServiceV2)
            assert service.enrichment_judge.db is db
            assert service.enrichment_judge.operation_id == "conversation-generation"
            assert service.enrichment_judge.generation == generation.descriptor
    finally:
        await db.close()
        await host.close()


def test_generation_consumer_uses_explicit_access_log_and_judge_aliases() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    entries = {entry.module_ref: entry for entry in document.entries}
    ordered_modules = tuple(entry.module_ref for entry in document.entries)

    assert entries[CONVERSATION_GENERATION_MODULE_V2].inject == {
        CONVERSATION_GENERATION_ACCESS_INJECT_V2: CONVERSATION_ACCESS_SERVICE_V2,
        CONVERSATION_GENERATION_SESSION_LOG_INJECT_V2: SESSION_EVENT_LOG_SERVICE_V2,
        CONVERSATION_GENERATION_ENRICHMENT_JUDGE_INJECT_V2: (
            CONVERSATION_ENRICHMENT_JUDGE_SERVICE_V2
        ),
    }
    assert entries[CONVERSATION_ENRICHMENT_JUDGE_MODULE_V2].inject == {
        CONVERSATION_ENRICHMENT_LLM_CLIENTS_INJECT_V2: TENANT_LLM_CLIENT_FACTORY_SERVICE_V2,
    }
    assert ordered_modules.index(CONVERSATION_ACCESS_MODULE_V2) < ordered_modules.index(
        CONVERSATION_GENERATION_MODULE_V2
    )
    assert ordered_modules.index(TENANT_LLM_CLIENT_FACTORY_MODULE_V2) < ordered_modules.index(
        CONVERSATION_ENRICHMENT_JUDGE_MODULE_V2
    )
    assert SESSION_EVENT_LOG_MODULE_V2 in ordered_modules


async def test_missing_declared_judge_provider_rejects_generation_candidate() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    broken = replace(
        document,
        entries=tuple(
            replace(
                entry,
                inject={
                    **entry.inject,
                    CONVERSATION_GENERATION_ENRICHMENT_JUDGE_INJECT_V2: "service:missing.judge",
                },
            )
            if entry.module_ref == CONVERSATION_GENERATION_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        broken,
        {manifest.plugin_id: manifest},
        generation=957,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "inject_service_mismatch"
    assert "builtin-conversation-generation" in str(error.value)


async def test_generate_title_uses_ordered_session_log_and_structured_judge() -> None:
    conversation = _conversation()
    messages = [
        {"role": "user", "content": "Plan the typed generation migration"},
        {"role": "assistant", "content": "The migration plan is ready."},
    ]
    service, access, session_log, judge = _service(
        conversation=conversation,
        messages=messages,
        judgment_value="Structured title",
    )

    updated = await service.generate_title(
        conversation_id=conversation.id,
    )

    assert updated is conversation
    assert conversation.title == "Structured title"
    session_log.materialize_model_messages.assert_awaited_once_with(
        conversation_id=conversation.id,
    )
    judge.judge.assert_awaited_once_with(
        purpose="title",
        conversation_id=conversation.id,
        messages=(
            ConversationEnrichmentMessageV2(
                role="user",
                content="Plan the typed generation migration",
            ),
        ),
    )
    access.save_scoped_conversation.assert_awaited_once()


async def test_generate_summary_filters_ordered_session_log_for_structured_judge() -> None:
    conversation = _conversation()
    messages = [
        {"role": "user", "content": "Summarize typed history"},
        {"role": "assistant", "content": "Typed history is ready."},
        {"role": "system", "content": "not conversation content"},
        {"role": "user", "content": {"text": "invalid"}},
    ]
    service, access, session_log, judge = _service(
        conversation=conversation,
        messages=messages,
        judgment_value="Typed admission summary",
    )

    updated = await service.generate_summary(
        conversation_id=conversation.id,
    )

    assert updated is conversation
    assert conversation.summary == "Typed admission summary"
    session_log.materialize_model_messages.assert_awaited_once_with(
        conversation_id=conversation.id,
    )
    judge.judge.assert_awaited_once_with(
        purpose="summary",
        conversation_id=conversation.id,
        messages=(
            ConversationEnrichmentMessageV2(role="user", content="Summarize typed history"),
            ConversationEnrichmentMessageV2(
                role="assistant",
                content="Typed history is ready.",
            ),
        ),
    )
    access.save_scoped_conversation.assert_awaited_once()


@pytest.mark.parametrize("purpose", ["title", "summary"])
async def test_generation_propagates_invalid_structured_judgment_without_persisting(
    purpose: str,
) -> None:
    conversation = _conversation()
    service, access, _session_log, judge = _service(
        conversation=conversation,
        messages=[{"role": "user", "content": "Generate output"}],
        judgment_value="Structured title" if purpose == "title" else "Structured summary",
    )
    judge.judge.side_effect = RuntimeV2Error(
        "conversation_enrichment_tool_call_required",
        "test",
    )

    with pytest.raises(RuntimeV2Error) as error:
        if purpose == "title":
            await service.generate_title(conversation_id=conversation.id)
        else:
            await service.generate_summary(conversation_id=conversation.id)

    assert error.value.code == "conversation_enrichment_tool_call_required"
    access.save_scoped_conversation.assert_not_awaited()


async def test_generation_fails_closed_for_missing_scope_or_source_messages() -> None:
    conversation = _conversation()
    missing_service, _missing_access, missing_log, missing_judge = _service(
        conversation=None,
        messages=[],
        judgment_value="unused",
    )
    assert (
        await missing_service.generate_title(
            conversation_id="missing",
        )
        is None
    )
    missing_log.materialize_model_messages.assert_not_awaited()
    missing_judge.judge.assert_not_awaited()

    wrong_tenant_service, _wrong_access, wrong_log, wrong_judge = _service(
        conversation=conversation,
        messages=[],
        judgment_value="unused",
    )
    wrong_tenant_service = replace(wrong_tenant_service, tenant_id="tenant-b")
    assert (
        await wrong_tenant_service.generate_summary(
            conversation_id=conversation.id,
        )
        is None
    )
    wrong_log.materialize_model_messages.assert_not_awaited()
    wrong_judge.judge.assert_not_awaited()

    no_source_service, no_source_access, no_source_log, no_source_judge = _service(
        conversation=conversation,
        messages=[],
        judgment_value="unused",
    )
    with pytest.raises(ConversationGenerationSourceMissingV2) as error:
        await no_source_service.generate_title(
            conversation_id=conversation.id,
        )
    assert error.value.purpose == "title"
    no_source_log.materialize_model_messages.assert_awaited_once_with(
        conversation_id=conversation.id,
    )
    no_source_judge.judge.assert_not_awaited()
    no_source_access.save_scoped_conversation.assert_not_awaited()

    await no_source_service.after_update_committed()
    no_source_access.cache.invalidate.assert_awaited_once_with(conversation.project_id)


async def test_generation_treats_post_fetch_save_none_as_persistence_failure() -> None:
    conversation = _conversation()
    service, _access, _session_log, _judge = _service(
        conversation=conversation,
        messages=[{"role": "user", "content": "Generate output"}],
        judgment_value="Structured title",
        save_result=None,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await service.generate_title(conversation_id=conversation.id)

    assert error.value.code == "conversation_generation_persistence_failed"


async def test_generation_rejects_wrong_judge_result_type_before_mutation() -> None:
    conversation = _conversation()
    service, access, _session_log, judge = _service(
        conversation=conversation,
        messages=[{"role": "user", "content": "Generate output"}],
        judgment_value="Structured title",
    )
    judge.judge.return_value = {"value": "untyped fallback"}

    with pytest.raises(RuntimeV2Error) as error:
        await service.generate_title(conversation_id=conversation.id)

    assert error.value.code == "invalid_conversation_enrichment_result"
    assert conversation.title == "Before"
    access.save_scoped_conversation.assert_not_awaited()


def test_generation_service_has_no_private_event_repository_or_free_text_llm_fallback() -> None:
    source = inspect.getsource(ConversationGenerationServiceV2)

    for forbidden in (
        ".ainvoke(",
        ".repositories.execution_event",
        "_conversation_repo",
        "save_and_commit",
        "create_llm_client",
    ):
        assert forbidden not in source
