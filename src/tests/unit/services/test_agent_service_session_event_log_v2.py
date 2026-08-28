"""V2 session-log authority for AgentService turn admission and history."""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.application.services.agent_service import AgentService
from src.domain.model.agent import Conversation, ConversationStatus
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2 import session_event_log_store as store_module
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.session_event_log import (
    MODEL_MESSAGE_COMMITTED_EVENT_V2,
    SESSION_EVENT_LOG_SERVICE_V2,
    TURN_ADMITTED_EVENT_V2,
    SessionEventCursorV2,
    SessionEventRecordV2,
)

_ROOT = Path(__file__).resolve().parents[4]
_ROOT_SCOPE = ScopeV2(kind=ScopeKindV2.ROOT)


@dataclass
class _MemorySessionEventLogStore:
    records: list[SessionEventRecordV2] = field(default_factory=list)
    appended: list[dict[str, Any]] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)

    async def append_stream_events(
        self,
        *,
        conversation_id: str,
        message_id: str,
        events: list[dict[str, Any]],
        correlation_id: str | None,
    ) -> None:
        self.actions.append("append")
        self.appended.append(
            {
                "conversation_id": conversation_id,
                "message_id": message_id,
                "events": events,
                "correlation_id": correlation_id,
            }
        )

    async def read_events(
        self,
        *,
        conversation_id: str,
        after: SessionEventCursorV2 | None,
        limit: int,
    ) -> list[SessionEventRecordV2]:
        self.actions.append("read")
        records = [record for record in self.records if record.conversation_id == conversation_id]
        if after is not None:
            records = [record for record in records if record.cursor > after]
        return sorted(records, key=lambda record: record.cursor)[:limit]

    async def last_cursor(self, *, conversation_id: str) -> SessionEventCursorV2:
        self.actions.append("cursor")
        return max(
            (record.cursor for record in self.records if record.conversation_id == conversation_id),
            default=SessionEventCursorV2(),
        )


class _RecordingAgentService(AgentService):
    started_kwargs: dict[str, Any] | None = None
    connect_stream_closed = False

    async def get_available_tools(self) -> list[object]:
        return []

    async def _start_chat_actor(self, *_args: object, **kwargs: Any) -> str:
        self.started_kwargs = kwargs
        return "actor-v2"

    async def connect_chat_stream(
        self,
        conversation_id: str,
        message_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        try:
            yield {
                "type": "complete",
                "data": {"conversation_id": conversation_id, "message_id": message_id},
                "timestamp": datetime.now(UTC).isoformat(),
            }
        finally:
            self.connect_stream_closed = True


def _conversation() -> Conversation:
    return Conversation(
        id="conversation-a",
        project_id="project-a",
        tenant_id="tenant-a",
        user_id="user-a",
        title="V2 session log",
        status=ConversationStatus.ACTIVE,
    )


def _record(
    *,
    event_id: str,
    event_type: str,
    role: str,
    content: str,
    event_time_us: int,
) -> SessionEventRecordV2:
    return SessionEventRecordV2(
        event_id=event_id,
        conversation_id="conversation-a",
        message_id=f"message-{event_id}",
        event_type=event_type,
        event_data={"model_message": {"role": role, "content": content}},
        cursor=SessionEventCursorV2(event_time_us=event_time_us, event_counter=0),
    )


def _service(
    *,
    conversation_repo: AsyncMock,
    direct_event_repo: AsyncMock,
    context_loader: AsyncMock,
) -> _RecordingAgentService:
    return _RecordingAgentService(
        conversation_repository=conversation_repo,
        execution_repository=AsyncMock(),
        llm=AsyncMock(),
        agent_execution_event_repository=direct_event_repo,
        context_loader=context_loader,
    )


@pytest.fixture
async def runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[PlatformPluginRuntimeHostV2, _MemorySessionEventLogStore]]:
    store = _MemorySessionEventLogStore(
        records=[
            _record(
                event_id="previous-user",
                event_type=TURN_ADMITTED_EVENT_V2,
                role="user",
                content="previous question",
                event_time_us=100,
            ),
            _record(
                event_id="previous-assistant",
                event_type=MODEL_MESSAGE_COMMITTED_EVENT_V2,
                role="assistant",
                content="previous answer",
                event_time_us=101,
            ),
        ]
    )
    monkeypatch.setattr(store_module, "SqlSessionEventLogStoreV2", lambda: store)
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=7,
        version=7,
        nonce="agent-service-session-log-v2",
    )
    try:
        yield host, store
    finally:
        await host.close()


@pytest.mark.unit
async def test_stream_admits_turn_and_materializes_history_only_through_pinned_v2_service(
    runtime: tuple[PlatformPluginRuntimeHostV2, _MemorySessionEventLogStore],
) -> None:
    host, store = runtime
    conversation_repo = AsyncMock()
    conversation_repo.find_by_id.return_value = _conversation()
    direct_event_repo = AsyncMock()
    context_loader = AsyncMock()
    service = _service(
        conversation_repo=conversation_repo,
        direct_event_repo=direct_event_repo,
        context_loader=context_loader,
    )

    async with pin_operation_context_v2(
        host,
        operation_id="agent-service-turn-admission",
        scope=_ROOT_SCOPE,
    ) as operation:
        events = [
            event
            async for event in service.stream_chat_v2(
                conversation_id="conversation-a",
                user_message="current question",
                project_id="project-a",
                user_id="user-a",
                tenant_id="tenant-a",
                attachment_ids=["attachment-a"],
                file_metadata=[{"name": "brief.txt"}],
                forced_skill_name="planning",
                mentions=["agent-reviewer"],
                execution_message_id="execution-message-a",
            )
        ]

        assert store.actions == ["read", "cursor", "append"]
        assert len(store.appended) == 1
        append = store.appended[0]
        assert append["conversation_id"] == "conversation-a"
        assert append["message_id"] == "execution-message-a"
        admitted = append["events"][0]
        assert admitted["type"] == TURN_ADMITTED_EVENT_V2
        assert admitted["data"]["model_message"] == {
            "role": "user",
            "content": "current question",
        }
        assert admitted["data"]["plugin_generation"] == operation.descriptor.to_payload()
        assert admitted["data"]["attachment_ids"] == ["attachment-a"]
        assert admitted["data"]["file_metadata"] == [{"name": "brief.txt"}]
        assert admitted["data"]["forced_skill_name"] == "planning"
        assert admitted["data"]["mentions"] == ["agent-reviewer"]

    assert [event["type"] for event in events] == ["message", "complete"]
    assert events[0]["data"]["id"] == "execution-message-a"
    assert events[0]["data"]["role"] == "user"
    assert events[0]["data"]["content"] == "current question"
    assert events[1]["data"]["message_id"] == "execution-message-a"
    assert service.started_kwargs is not None
    assert service.started_kwargs["message_id"] == "execution-message-a"
    assert service.started_kwargs["conversation_context"] == [
        {"role": "user", "content": "previous question"},
        {"role": "assistant", "content": "previous answer"},
    ]
    assert service.started_kwargs["context_summary_data"] is None
    direct_event_repo.get_last_event_time.assert_not_awaited()
    direct_event_repo.save_and_commit.assert_not_awaited()
    direct_event_repo.get_message_events.assert_not_awaited()
    context_loader.load_context.assert_not_awaited()


@pytest.mark.unit
async def test_stream_close_propagates_to_connect_stream_before_boundary_exit(
    runtime: tuple[PlatformPluginRuntimeHostV2, _MemorySessionEventLogStore],
) -> None:
    host, _store = runtime
    conversation_repo = AsyncMock()
    conversation_repo.find_by_id.return_value = _conversation()
    service = _service(
        conversation_repo=conversation_repo,
        direct_event_repo=AsyncMock(),
        context_loader=AsyncMock(),
    )

    async with pin_operation_context_v2(
        host,
        operation_id="agent-service-stream-close",
        scope=_ROOT_SCOPE,
    ):
        stream = cast(
            AsyncGenerator[dict[str, Any], None],
            service.stream_chat_v2(
                conversation_id="conversation-a",
                user_message="close after terminal",
                project_id="project-a",
                user_id="user-a",
                tenant_id="tenant-a",
                execution_message_id="execution-message-close",
            ),
        )
        async with aclosing(stream) as events:
            assert (await anext(events))["type"] == "message"
            assert (await anext(events))["type"] == "complete"
            assert service.connect_stream_closed is False

        assert service.connect_stream_closed is True


@pytest.mark.unit
async def test_stream_without_pinned_operation_fails_closed_before_direct_authorities() -> None:
    conversation_repo = AsyncMock()
    conversation_repo.find_by_id.return_value = _conversation()
    direct_event_repo = AsyncMock()
    context_loader = AsyncMock()
    service = _service(
        conversation_repo=conversation_repo,
        direct_event_repo=direct_event_repo,
        context_loader=context_loader,
    )

    events = [
        event
        async for event in service.stream_chat_v2(
            conversation_id="conversation-a",
            user_message="must fail closed",
            project_id="project-a",
            user_id="user-a",
            tenant_id="tenant-a",
            execution_message_id="execution-message-a",
        )
    ]

    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert events[0]["data"]["code"] == "operation_context_not_pinned"
    assert service.started_kwargs is None
    direct_event_repo.get_last_event_time.assert_not_awaited()
    direct_event_repo.save_and_commit.assert_not_awaited()
    direct_event_repo.get_message_events.assert_not_awaited()
    context_loader.load_context.assert_not_awaited()


@pytest.mark.unit
async def test_stream_with_missing_session_log_service_fails_closed() -> None:
    conversation_repo = AsyncMock()
    conversation_repo.find_by_id.return_value = _conversation()
    direct_event_repo = AsyncMock()
    context_loader = AsyncMock()
    service = _service(
        conversation_repo=conversation_repo,
        direct_event_repo=direct_event_repo,
        context_loader=context_loader,
    )
    operation = MagicMock()
    operation.require.side_effect = RuntimeV2Error(
        "service_not_found",
        "session event-log service is not available",
    )

    with patch(
        "src.infrastructure.plugins.v2.boundary.current_operation_context_v2",
        return_value=operation,
    ):
        events = [
            event
            async for event in service.stream_chat_v2(
                conversation_id="conversation-a",
                user_message="must fail closed",
                project_id="project-a",
                user_id="user-a",
                tenant_id="tenant-a",
                execution_message_id="execution-message-a",
            )
        ]

    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert events[0]["data"]["code"] == "service_not_found"
    operation.require.assert_called_once_with(SESSION_EVENT_LOG_SERVICE_V2)
    assert service.started_kwargs is None
    direct_event_repo.get_last_event_time.assert_not_awaited()
    direct_event_repo.save_and_commit.assert_not_awaited()
    direct_event_repo.get_message_events.assert_not_awaited()
    context_loader.load_context.assert_not_awaited()
