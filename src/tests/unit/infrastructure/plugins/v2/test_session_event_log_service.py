"""Authoritative session event-log service contract tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.session_event_log import (
    HITL_TOOL_RESULT_APPLIED_EVENT_V2,
    MODEL_MESSAGE_COMMITTED_EVENT_V2,
    SessionEventCursorV2,
    SessionEventLogServiceV2,
    SessionEventRecordV2,
)


@dataclass
class _MemorySessionEventLogStore:
    records: list[SessionEventRecordV2] = field(default_factory=list)
    appended: list[dict[str, Any]] = field(default_factory=list)
    append_error: BaseException | None = None

    async def append_stream_events(
        self,
        *,
        conversation_id: str,
        message_id: str,
        events: list[dict[str, Any]],
        correlation_id: str | None,
    ) -> None:
        _ = (conversation_id, message_id, correlation_id)
        if self.append_error is not None:
            raise self.append_error
        self.appended.extend(events)

    async def read_events(
        self,
        *,
        conversation_id: str,
        after: SessionEventCursorV2 | None,
        limit: int,
    ) -> list[SessionEventRecordV2]:
        records = [record for record in self.records if record.conversation_id == conversation_id]
        if after is not None:
            records = [record for record in records if record.cursor > after]
        return sorted(records, key=lambda record: record.cursor)[:limit]

    async def read_message_events(
        self,
        *,
        conversation_id: str,
        message_id: str,
    ) -> list[SessionEventRecordV2]:
        return sorted(
            [
                record
                for record in self.records
                if record.conversation_id == conversation_id and record.message_id == message_id
            ],
            key=lambda record: record.cursor,
        )

    async def last_cursor(self, *, conversation_id: str) -> SessionEventCursorV2:
        cursors = [
            record.cursor for record in self.records if record.conversation_id == conversation_id
        ]
        return max(cursors, default=SessionEventCursorV2())


def _descriptor() -> PluginGenerationDescriptorV2:
    return PluginGenerationDescriptorV2(
        profile_id="memstack-default-v2",
        generation=7,
        digest="a" * 64,
    )


def _service(store: _MemorySessionEventLogStore) -> SessionEventLogServiceV2:
    return SessionEventLogServiceV2(
        strategy="ordered-sql-event-log",
        store=store,
        generation_resolver=_descriptor,
    )


def _record(
    *,
    event_id: str,
    event_type: str,
    event_data: dict[str, Any],
    time_us: int,
    counter: int,
    conversation_id: str = "conversation-a",
    message_id: str = "message-a",
) -> SessionEventRecordV2:
    return SessionEventRecordV2(
        event_id=event_id,
        conversation_id=conversation_id,
        message_id=message_id,
        event_type=event_type,
        event_data=event_data,
        cursor=SessionEventCursorV2(event_time_us=time_us, event_counter=counter),
    )


@pytest.mark.unit
async def test_append_stamps_exact_pinned_generation_without_caller_callback() -> None:
    store = _MemorySessionEventLogStore()
    service = _service(store)

    await service.append(
        conversation_id="conversation-a",
        message_id="message-a",
        events=[
            {
                "type": "observe",
                "data": {"call_id": "call-1", "result": "ok"},
                "event_time_us": 100,
                "event_counter": 2,
            }
        ],
        correlation_id="correlation-a",
    )

    assert store.appended == [
        {
            "type": "observe",
            "data": {
                "call_id": "call-1",
                "result": "ok",
                "plugin_generation": _descriptor().to_payload(),
            },
            "event_time_us": 100,
            "event_counter": 2,
        }
    ]


@pytest.mark.unit
async def test_append_rejects_conflicting_generation_before_storage() -> None:
    store = _MemorySessionEventLogStore()
    service = _service(store)

    with pytest.raises(RuntimeV2Error) as error:
        await service.append(
            conversation_id="conversation-a",
            message_id="message-a",
            events=[
                {
                    "type": "observe",
                    "data": {
                        "plugin_generation": {
                            "profile_id": "memstack-default-v2",
                            "generation": 6,
                            "digest": "b" * 64,
                        }
                    },
                }
            ],
        )

    assert error.value.code == "generation_descriptor_mismatch"
    assert store.appended == []


@pytest.mark.unit
async def test_append_propagates_storage_failure() -> None:
    store = _MemorySessionEventLogStore(append_error=OSError("database unavailable"))
    service = _service(store)

    with pytest.raises(OSError, match="database unavailable"):
        await service.append(
            conversation_id="conversation-a",
            message_id="message-a",
            events=[{"type": "status", "data": {"status": "running"}}],
        )


@pytest.mark.unit
async def test_materialize_model_messages_preserves_order_and_tool_shape() -> None:
    store = _MemorySessionEventLogStore(
        records=[
            _record(
                event_id="tool-result",
                event_type=HITL_TOOL_RESULT_APPLIED_EVENT_V2,
                event_data={
                    "model_message": {
                        "role": "tool",
                        "tool_call_id": "call-1",
                        "content": "approved",
                    }
                },
                time_us=100,
                counter=2,
            ),
            _record(
                event_id="legacy-user",
                event_type="user_message",
                event_data={"role": "user", "content": "run it"},
                time_us=100,
                counter=0,
            ),
            _record(
                event_id="assistant-tool-call",
                event_type=MODEL_MESSAGE_COMMITTED_EVENT_V2,
                event_data={
                    "model_message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "request_permission",
                                    "arguments": '{"path":"/tmp/result"}',
                                },
                            }
                        ],
                    }
                },
                time_us=100,
                counter=1,
            ),
            _record(
                event_id="legacy-assistant",
                event_type="assistant_message",
                event_data={"role": "assistant", "content": "done"},
                time_us=101,
                counter=0,
            ),
        ]
    )

    messages = await _service(store).materialize_model_messages(conversation_id="conversation-a")

    assert messages == [
        {"role": "user", "content": "run it"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "request_permission",
                        "arguments": '{"path":"/tmp/result"}',
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": "approved"},
        {"role": "assistant", "content": "done"},
    ]


@pytest.mark.unit
async def test_materialize_uses_full_cursor_and_can_exclude_event() -> None:
    store = _MemorySessionEventLogStore(
        records=[
            _record(
                event_id="covered",
                event_type="user_message",
                event_data={"role": "user", "content": "covered"},
                time_us=200,
                counter=1,
            ),
            _record(
                event_id="excluded",
                event_type="assistant_message",
                event_data={"role": "assistant", "content": "exclude me"},
                time_us=200,
                counter=2,
            ),
            _record(
                event_id="included",
                event_type="user_message",
                event_data={"role": "user", "content": "include me"},
                time_us=200,
                counter=3,
            ),
        ]
    )

    messages = await _service(store).materialize_model_messages(
        conversation_id="conversation-a",
        after=SessionEventCursorV2(event_time_us=200, event_counter=1),
        exclude_event_id="excluded",
    )

    assert messages == [{"role": "user", "content": "include me"}]


@pytest.mark.unit
async def test_materialize_reads_every_page_with_same_microsecond_cursors() -> None:
    store = _MemorySessionEventLogStore(
        records=[
            _record(
                event_id=f"event-{counter}",
                event_type="user_message",
                event_data={"role": "user", "content": f"message-{counter}"},
                time_us=250,
                counter=counter,
            )
            for counter in range(5)
        ]
    )

    messages = await _service(store).materialize_model_messages(
        conversation_id="conversation-a",
        page_size=2,
    )

    assert messages == [{"role": "user", "content": f"message-{counter}"} for counter in range(5)]


@pytest.mark.unit
async def test_materialize_rejects_malformed_typed_model_event() -> None:
    store = _MemorySessionEventLogStore(
        records=[
            _record(
                event_id="malformed",
                event_type=MODEL_MESSAGE_COMMITTED_EVENT_V2,
                event_data={"model_message": {"content": "missing role"}},
                time_us=300,
                counter=0,
            )
        ]
    )

    with pytest.raises(RuntimeV2Error) as error:
        await _service(store).materialize_model_messages(conversation_id="conversation-a")

    assert error.value.code == "invalid_model_message_event"


@pytest.mark.unit
async def test_last_cursor_returns_precise_time_and_counter() -> None:
    store = _MemorySessionEventLogStore(
        records=[
            _record(
                event_id="first",
                event_type="user_message",
                event_data={"role": "user", "content": "first"},
                time_us=400,
                counter=1,
            ),
            _record(
                event_id="last",
                event_type="assistant_message",
                event_data={"role": "assistant", "content": "last"},
                time_us=400,
                counter=7,
            ),
        ]
    )

    cursor = await _service(store).last_cursor(conversation_id="conversation-a")

    assert cursor == SessionEventCursorV2(event_time_us=400, event_counter=7)


@pytest.mark.unit
async def test_message_recovery_state_is_message_scoped_and_detects_terminal_event() -> None:
    store = _MemorySessionEventLogStore(
        records=[
            _record(
                event_id="running-message-event",
                event_type="text_delta",
                event_data={"delta": "working"},
                time_us=500,
                counter=2,
            ),
            _record(
                event_id="other-message-terminal",
                event_type="complete",
                event_data={},
                time_us=999,
                counter=0,
                message_id="message-other",
            ),
            _record(
                event_id="running-message-terminal",
                event_type="error",
                event_data={"code": "failed"},
                time_us=501,
                counter=0,
            ),
        ]
    )

    state = await _service(store).message_recovery_state(
        conversation_id="conversation-a",
        message_id="message-a",
    )

    assert state.has_events is True
    assert state.is_terminal is True
    assert state.cursor == SessionEventCursorV2(event_time_us=501, event_counter=0)


@pytest.mark.unit
async def test_message_recovery_state_is_empty_for_unknown_message() -> None:
    state = await _service(_MemorySessionEventLogStore()).message_recovery_state(
        conversation_id="conversation-a",
        message_id="message-missing",
    )

    assert state.has_events is False
    assert state.is_terminal is False
    assert state.cursor == SessionEventCursorV2()
