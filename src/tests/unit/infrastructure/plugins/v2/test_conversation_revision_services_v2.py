"""V2 conversation fork, message revision, and tool-undo authority tests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent,
    Conversation,
    Message,
    ToolExecutionRecord,
    UserProject,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.conversation_revision_services import (
    CONVERSATION_REVISION_MODULE_V2,
    CONVERSATION_REVISION_PROVIDER_INJECT_V2,
    CONVERSATION_REVISION_PROVIDER_MODULE_V2,
    CONVERSATION_REVISION_PROVIDER_SERVICE_V2,
    CONVERSATION_REVISION_REDIS_INJECT_V2,
    CONVERSATION_REVISION_SERVICE_V2,
    ConversationRevisionAccessDeniedV2,
    ConversationRevisionConversationNotFoundV2,
    ConversationRevisionMessageNotFoundV2,
    ConversationRevisionServiceV2,
    ConversationRevisionToolExecutionNotFoundV2,
    SqlConversationRevisionTransactionV2,
)
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.redis_runtime import REDIS_RUNTIME_SERVICE_V2
from src.infrastructure.plugins.v2.runtime import (
    ContextV2,
    LoaderV2,
    PluginDefinitionV2,
    RuntimeV2Error,
)
from src.infrastructure.plugins.v2.session_event_log import (
    SessionEventCursorV2,
    SessionEventLogServiceV2,
    SessionEventRecordV2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


def _descriptor() -> PluginGenerationDescriptorV2:
    return PluginGenerationDescriptorV2(
        profile_id="memstack-default-v2",
        generation=971,
        digest="a" * 64,
    )


def _conversation(
    *,
    conversation_id: str,
    project_id: str,
    tenant_id: str,
    user_id: str,
    message_count: int = 0,
) -> Conversation:
    return Conversation(
        id=conversation_id,
        project_id=project_id,
        tenant_id=tenant_id,
        user_id=user_id,
        title="Revision source",
        status="active",
        agent_config={},
        meta={},
        message_count=message_count,
        current_mode="build",
        participant_agents=[],
    )


def _event(
    *,
    event_id: str,
    conversation_id: str,
    message_id: str,
    event_type: str,
    event_data: dict[str, Any],
    event_time_us: int,
    event_counter: int = 0,
) -> AgentExecutionEvent:
    return AgentExecutionEvent(
        id=event_id,
        conversation_id=conversation_id,
        message_id=message_id,
        event_type=event_type,
        event_data=event_data,
        event_time_us=event_time_us,
        event_counter=event_counter,
    )


def _service(db: AsyncSession) -> tuple[ConversationRevisionServiceV2, AsyncMock]:
    invalidate = AsyncMock()
    service = ConversationRevisionServiceV2(
        transaction=SqlConversationRevisionTransactionV2(
            db=db,
            descriptor=_descriptor(),
        ),
        cache=type("Cache", (), {"invalidate": invalidate})(),
    )
    return service, invalidate


class _DbReadSessionEventStore:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def read_events(
        self,
        *,
        conversation_id: str,
        after: SessionEventCursorV2 | None,
        limit: int,
    ) -> list[SessionEventRecordV2]:
        rows = list(
            (
                await self._db.execute(
                    select(AgentExecutionEvent)
                    .where(AgentExecutionEvent.conversation_id == conversation_id)
                    .order_by(
                        AgentExecutionEvent.event_time_us,
                        AgentExecutionEvent.event_counter,
                    )
                )
            )
            .scalars()
            .all()
        )
        records = [
            SessionEventRecordV2(
                event_id=row.id,
                conversation_id=row.conversation_id,
                message_id=row.message_id or "",
                event_type=row.event_type,
                event_data=row.event_data or {},
                cursor=SessionEventCursorV2(
                    event_time_us=row.event_time_us,
                    event_counter=row.event_counter,
                ),
            )
            for row in rows
        ]
        if after is not None:
            records = [record for record in records if record.cursor > after]
        return records[:limit]

    async def append_stream_events(self, **_kwargs: Any) -> None:
        raise AssertionError("read-only test store")

    async def read_message_events(self, **_kwargs: Any) -> list[SessionEventRecordV2]:
        raise AssertionError("not used")

    async def last_cursor(self, **_kwargs: Any) -> SessionEventCursorV2:
        raise AssertionError("not used")


async def _materialize(db: AsyncSession, conversation_id: str) -> list[dict[str, Any]]:
    service = SessionEventLogServiceV2(
        strategy="ordered-sql-event-log",
        store=_DbReadSessionEventStore(db),
        generation_resolver=_descriptor,
    )
    return await service.materialize_model_messages(conversation_id=conversation_id)


async def _add_source(
    db: AsyncSession,
    *,
    project_id: str,
    tenant_id: str,
    user_id: str,
    conversation_id: str = "conversation-source",
    message_count: int = 0,
) -> Conversation:
    conversation = _conversation(
        conversation_id=conversation_id,
        project_id=project_id,
        tenant_id=tenant_id,
        user_id=user_id,
        message_count=message_count,
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def test_fork_copies_authoritative_history_through_exact_branch(
    db_session: AsyncSession,
    test_project_db: Any,
    test_user: Any,
) -> None:
    source = await _add_source(
        db_session,
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
        message_count=3,
    )
    db_session.add_all(
        [
            _event(
                event_id="event-user-1",
                conversation_id=source.id,
                message_id="turn-1",
                event_type="turn_admitted",
                event_data={"model_message": {"role": "user", "content": "first"}},
                event_time_us=100,
            ),
            _event(
                event_id="event-assistant-1",
                conversation_id=source.id,
                message_id="turn-1",
                event_type="assistant_message",
                event_data={
                    "message_id": "assistant-1",
                    "role": "assistant",
                    "content": "first answer",
                },
                event_time_us=110,
            ),
            _event(
                event_id="event-user-2",
                conversation_id=source.id,
                message_id="turn-2",
                event_type="turn_admitted",
                event_data={"model_message": {"role": "user", "content": "second"}},
                event_time_us=200,
            ),
        ]
    )
    await db_session.flush()

    service, invalidate = _service(db_session)
    result = await service.fork_conversation(
        conversation_id=source.id,
        branch_message_id="assistant-1",
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
    )

    fork = await db_session.get(Conversation, result.conversation_id)
    assert fork is not None
    assert fork.parent_conversation_id == source.id
    assert fork.fork_source_id == source.id
    assert fork.branch_point_message_id == "assistant-1"
    assert fork.project_id == source.project_id
    assert fork.tenant_id == source.tenant_id
    assert fork.user_id == source.user_id
    assert fork.message_count == 2

    fork_events = list(
        (
            await db_session.execute(
                select(AgentExecutionEvent)
                .where(AgentExecutionEvent.conversation_id == fork.id)
                .order_by(
                    AgentExecutionEvent.event_time_us,
                    AgentExecutionEvent.event_counter,
                )
            )
        )
        .scalars()
        .all()
    )
    assert [event.event_type for event in fork_events] == [
        "turn_admitted",
        "assistant_message",
    ]
    assert fork_events[0].message_id != "turn-1"
    assert fork_events[1].message_id == fork_events[0].message_id
    assert fork_events[1].event_data["message_id"] != "assistant-1"
    assert fork_events[0].event_data["model_message"]["content"] == "first"
    assert fork_events[1].event_data["content"] == "first answer"
    for event in fork_events:
        assert event.event_data["plugin_generation"] == _descriptor().to_payload()
        assert event.event_data["fork_source_conversation_id"] == source.id
        assert event.event_data["fork_source_event_id"]
    assert await _materialize(db_session, fork.id) == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "first answer"},
    ]

    await service.after_mutation_committed(result.project_id)
    invalidate.assert_awaited_once_with(source.project_id)


async def test_fork_rejects_unknown_branch_without_creating_child(
    db_session: AsyncSession,
    test_project_db: Any,
    test_user: Any,
) -> None:
    source = await _add_source(
        db_session,
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
    )
    db_session.add(
        _event(
            event_id="event-only",
            conversation_id=source.id,
            message_id="turn-only",
            event_type="turn_admitted",
            event_data={"model_message": {"role": "user", "content": "only"}},
            event_time_us=100,
        )
    )
    await db_session.flush()

    service, _invalidate = _service(db_session)
    with pytest.raises(ConversationRevisionMessageNotFoundV2):
        await service.fork_conversation(
            conversation_id=source.id,
            branch_message_id="missing",
            tenant_id=test_project_db.tenant_id,
            user_id=test_user.id,
        )

    children = list(
        (
            await db_session.execute(
                select(Conversation).where(Conversation.parent_conversation_id == source.id)
            )
        )
        .scalars()
        .all()
    )
    assert children == []


async def test_edit_updates_model_event_legacy_projection_and_audit_metadata(
    db_session: AsyncSession,
    test_project_db: Any,
    test_user: Any,
) -> None:
    source = await _add_source(
        db_session,
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
        message_count=1,
    )
    event = _event(
        event_id="event-edit",
        conversation_id=source.id,
        message_id="message-edit",
        event_type="turn_admitted",
        event_data={"model_message": {"role": "user", "content": "before"}},
        event_time_us=100,
    )
    legacy = Message(
        id="message-edit",
        conversation_id=source.id,
        role="user",
        content="before",
        message_type="text",
        version=1,
    )
    db_session.add_all([event, legacy])
    await db_session.flush()

    service, _invalidate = _service(db_session)
    first = await service.edit_message(
        conversation_id=source.id,
        message_id="message-edit",
        content="after one",
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
    )
    second = await service.edit_message(
        conversation_id=source.id,
        message_id="message-edit",
        content="after two",
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
    )

    await db_session.refresh(event)
    await db_session.refresh(legacy)
    assert first.version == 2
    assert second.version == 3
    assert second.content == "after two"
    assert second.original_content == "before"
    assert event.event_data["model_message"]["content"] == "after two"
    assert event.event_data["original_content"] == "before"
    assert event.event_data["version"] == 3
    assert event.event_data["edited_at"] == second.edited_at.isoformat()
    assert legacy.content == "after two"
    assert legacy.original_content == "before"
    assert legacy.version == 3
    assert legacy.edited_at is not None
    assert legacy.edited_at.replace(tzinfo=UTC) == second.edited_at

    audits = list(
        (
            await db_session.execute(
                select(AgentExecutionEvent)
                .where(
                    AgentExecutionEvent.conversation_id == source.id,
                    AgentExecutionEvent.event_type == "model_message_revised",
                )
                .order_by(
                    AgentExecutionEvent.event_time_us,
                    AgentExecutionEvent.event_counter,
                )
            )
        )
        .scalars()
        .all()
    )
    assert [audit.event_data["version"] for audit in audits] == [2, 3]
    assert all(
        audit.event_data["plugin_generation"] == _descriptor().to_payload() for audit in audits
    )
    assert await _materialize(db_session, source.id) == [{"role": "user", "content": "after two"}]


async def test_message_and_execution_must_belong_to_scoped_conversation(
    db_session: AsyncSession,
    test_project_db: Any,
    test_user: Any,
) -> None:
    source = await _add_source(
        db_session,
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
    )
    other = await _add_source(
        db_session,
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
        conversation_id="conversation-other",
    )
    db_session.add_all(
        [
            _event(
                event_id="event-other",
                conversation_id=other.id,
                message_id="message-other",
                event_type="turn_admitted",
                event_data={"model_message": {"role": "user", "content": "private"}},
                event_time_us=100,
            ),
            ToolExecutionRecord(
                id="execution-other",
                conversation_id=other.id,
                message_id="message-other",
                call_id="call-other",
                tool_name="write_file",
                tool_input={},
                status="success",
                sequence_number=1,
            ),
        ]
    )
    await db_session.flush()
    service, _invalidate = _service(db_session)

    with pytest.raises(ConversationRevisionMessageNotFoundV2):
        await service.edit_message(
            conversation_id=source.id,
            message_id="message-other",
            content="leak",
            tenant_id=test_project_db.tenant_id,
            user_id=test_user.id,
        )
    with pytest.raises(ConversationRevisionToolExecutionNotFoundV2):
        await service.request_tool_undo(
            conversation_id=source.id,
            execution_id="execution-other",
            tenant_id=test_project_db.tenant_id,
            user_id=test_user.id,
        )


async def test_tool_undo_appends_typed_user_turn_and_updates_projection_atomically(
    db_session: AsyncSession,
    test_project_db: Any,
    test_user: Any,
) -> None:
    source = await _add_source(
        db_session,
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
        message_count=4,
    )
    db_session.add(
        ToolExecutionRecord(
            id="execution-undo",
            conversation_id=source.id,
            message_id="message-tool",
            call_id="call-undo",
            tool_name="write_file",
            tool_input={"path": "/tmp/result"},
            status="success",
            sequence_number=1,
        )
    )
    await db_session.flush()
    service, _invalidate = _service(db_session)

    result = await service.request_tool_undo(
        conversation_id=source.id,
        execution_id="execution-undo",
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
    )

    await db_session.refresh(source)
    event = (
        await db_session.execute(
            select(AgentExecutionEvent).where(
                AgentExecutionEvent.conversation_id == source.id,
                AgentExecutionEvent.message_id == result.message_id,
            )
        )
    ).scalar_one()
    assert result.tool_name == "write_file"
    assert source.message_count == 5
    assert event.event_type == "turn_admitted"
    assert event.event_data["source"] == "tool_undo"
    assert event.event_data["tool_execution_id"] == "execution-undo"
    assert event.event_data["model_message"] == {
        "role": "user",
        "content": (
            "Please undo the previous tool execution: write_file. Revert any changes made."
        ),
    }
    assert event.event_data["plugin_generation"] == _descriptor().to_payload()
    assert await _materialize(db_session, source.id) == [event.event_data["model_message"]]


async def test_revision_rollback_removes_event_and_projection_changes(
    db_session: AsyncSession,
    test_project_db: Any,
    test_user: Any,
) -> None:
    source = await _add_source(
        db_session,
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
        message_count=2,
    )
    db_session.add(
        ToolExecutionRecord(
            id="execution-rollback",
            conversation_id=source.id,
            message_id="message-tool",
            call_id="call-rollback",
            tool_name="write_file",
            tool_input={},
            status="success",
            sequence_number=1,
        )
    )
    await db_session.commit()
    source_id = source.id
    service, _invalidate = _service(db_session)

    result = await service.request_tool_undo(
        conversation_id=source.id,
        execution_id="execution-rollback",
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
    )
    await db_session.rollback()

    persisted = (
        await db_session.execute(
            select(AgentExecutionEvent).where(AgentExecutionEvent.message_id == result.message_id)
        )
    ).scalar_one_or_none()
    refreshed_source = await db_session.get(Conversation, source_id)
    assert persisted is None
    assert refreshed_source is not None
    assert refreshed_source.message_count == 2


async def test_revision_scope_enforces_tenant_owner_and_project_membership(
    db_session: AsyncSession,
    test_project_db: Any,
    test_user: Any,
) -> None:
    source = await _add_source(
        db_session,
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
    )
    db_session.add(
        _event(
            event_id="event-scope",
            conversation_id=source.id,
            message_id="message-scope",
            event_type="turn_admitted",
            event_data={"model_message": {"role": "user", "content": "scope"}},
            event_time_us=100,
        )
    )
    await db_session.flush()
    service, _invalidate = _service(db_session)

    with pytest.raises(ConversationRevisionConversationNotFoundV2):
        await service.edit_message(
            conversation_id=source.id,
            message_id="message-scope",
            content="wrong tenant",
            tenant_id="tenant-other",
            user_id=test_user.id,
        )
    with pytest.raises(ConversationRevisionAccessDeniedV2):
        await service.edit_message(
            conversation_id=source.id,
            message_id="message-scope",
            content="wrong owner",
            tenant_id=test_project_db.tenant_id,
            user_id="user-other",
        )

    membership = (
        await db_session.execute(
            select(UserProject).where(
                UserProject.user_id == test_user.id,
                UserProject.project_id == test_project_db.id,
            )
        )
    ).scalar_one()
    await db_session.delete(membership)
    await db_session.flush()
    with pytest.raises(ConversationRevisionAccessDeniedV2):
        await service.edit_message(
            conversation_id=source.id,
            message_id="message-scope",
            content="no project membership",
            tenant_id=test_project_db.tenant_id,
            user_id=test_user.id,
        )


def test_profile_declares_revision_provider_before_application_consumer() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    entries = {entry.module_ref: entry for entry in document.entries}
    ordered_modules = tuple(entry.module_ref for entry in document.entries)

    assert entries[CONVERSATION_REVISION_MODULE_V2].inject == {
        CONVERSATION_REVISION_PROVIDER_INJECT_V2: CONVERSATION_REVISION_PROVIDER_SERVICE_V2,
        CONVERSATION_REVISION_REDIS_INJECT_V2: REDIS_RUNTIME_SERVICE_V2,
    }
    assert ordered_modules.index(CONVERSATION_REVISION_PROVIDER_MODULE_V2) < ordered_modules.index(
        CONVERSATION_REVISION_MODULE_V2
    )


def test_manifest_declares_revision_provider_and_application_contracts() -> None:
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    modules = {module.module_ref: module for module in manifest.modules}
    provider = modules[CONVERSATION_REVISION_PROVIDER_MODULE_V2]
    consumer = modules[CONVERSATION_REVISION_MODULE_V2]

    assert [provided.service for provided in provider.contract.services.provides] == [
        CONVERSATION_REVISION_PROVIDER_SERVICE_V2
    ]
    assert [provided.service for provided in consumer.contract.services.provides] == [
        CONVERSATION_REVISION_SERVICE_V2
    ]
    assert {
        required.alias: required.service for required in consumer.contract.services.requires
    } == {
        CONVERSATION_REVISION_PROVIDER_INJECT_V2: CONVERSATION_REVISION_PROVIDER_SERVICE_V2,
        CONVERSATION_REVISION_REDIS_INJECT_V2: REDIS_RUNTIME_SERVICE_V2,
    }


async def test_missing_revision_provider_rejects_candidate_before_activation() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == CONVERSATION_REVISION_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=973)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-conversation-revision" in str(error.value)


async def test_invalid_revision_provider_fails_closed_during_candidate_activation() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(document, {manifest.plugin_id: manifest}, generation=974)
    definitions = builtin_runtime_definitions_v2()
    provider_definition = next(
        definition
        for definition in definitions
        if definition.module_ref == CONVERSATION_REVISION_PROVIDER_MODULE_V2
    )

    def apply_invalid_provider(context: ContextV2, _config: Mapping[str, Any]) -> None:
        _ = context.provide(
            CONVERSATION_REVISION_PROVIDER_SERVICE_V2,
            object(),
            label="invalid-conversation-revision-provider",
        )

    invalid_provider = PluginDefinitionV2(
        module_ref=provider_definition.module_ref,
        contract_digest=provider_definition.contract_digest,
        apply=apply_invalid_provider,
    )
    definitions_with_invalid_provider = tuple(
        invalid_provider
        if definition.module_ref == CONVERSATION_REVISION_PROVIDER_MODULE_V2
        else definition
        for definition in definitions
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(definitions_with_invalid_provider).stage(snapshot)

    assert error.value.code == "invalid_conversation_revision_provider"
    assert "invalid implementation" in str(error.value)
