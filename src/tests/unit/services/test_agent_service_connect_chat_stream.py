"""Unit tests for AgentService.connect_chat_stream cursor/replay behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.application.services.agent_service import AgentService
from src.domain.model.agent import ToolExecutionRecord
from src.domain.ports.agent.tool_executor_port import ToolExecutionStatus


class _TestAgentService(AgentService):
    async def get_available_tools(self):
        return []

    async def get_conversation_context(self, conversation_id: str):
        return []


class _InMemoryToolExecutionRecordRepo:
    def __init__(self) -> None:
        self.records: dict[str, ToolExecutionRecord] = {}

    async def find_by_id(self, record_id: str) -> ToolExecutionRecord | None:
        return self.records.get(record_id)

    async def save_and_commit(self, record: ToolExecutionRecord) -> None:
        self.records[record.id] = record


def _build_service(
    tool_execution_record_repo: _InMemoryToolExecutionRecordRepo | None = None,
) -> _TestAgentService:
    conversation_repo = AsyncMock()
    execution_repo = AsyncMock()
    graph_service = AsyncMock()
    llm = AsyncMock()
    neo4j_client = AsyncMock()
    agent_event_repo = AsyncMock()
    service = _TestAgentService(
        conversation_repository=conversation_repo,
        execution_repository=execution_repo,
        graph_service=graph_service,
        llm=llm,
        neo4j_client=neo4j_client,
        agent_execution_event_repository=agent_event_repo,
        tool_execution_record_repository=tool_execution_record_repo,
        redis_client=None,
    )
    service._event_bus = SimpleNamespace(stream_read=AsyncMock())
    return service


@pytest.mark.unit
@pytest.mark.asyncio
async def test_connect_chat_stream_skips_db_replay_when_disabled() -> None:
    service = _build_service()
    service._replay_db_events = AsyncMock(
        return_value=(
            [],
            0,
            0,
            False,
        )
    )

    async def _stream_read(*_args, **_kwargs):
        yield {
            "id": "1-0",
            "data": {
                "type": "text_delta",
                "event_time_us": 10,
                "event_counter": 1,
                "data": {"message_id": "m1", "delta": "hello"},
            },
        }
        yield {
            "id": "2-0",
            "data": {
                "type": "complete",
                "event_time_us": 11,
                "event_counter": 2,
                "data": {"message_id": "m1", "content": "done"},
            },
        }

    service._event_bus.stream_read = _stream_read
    service._read_delayed_events = AsyncMock(return_value=[])
    service._handle_title_generation = AsyncMock()

    events = []
    async for event in service.connect_chat_stream(
        conversation_id="conv-1",
        message_id="m1",
        replay_from_db=False,
    ):
        events.append(event)

    service._replay_db_events.assert_not_awaited()
    assert [event["type"] for event in events] == ["text_delta", "complete"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_connect_chat_stream_honors_cursor_without_db_replay() -> None:
    service = _build_service()
    service._replay_db_events = AsyncMock(
        return_value=(
            [],
            0,
            0,
            False,
        )
    )

    async def _stream_read(*_args, **_kwargs):
        # Already seen by cursor -> should be skipped
        yield {
            "id": "1-0",
            "data": {
                "type": "text_delta",
                "event_time_us": 20,
                "event_counter": 3,
                "data": {"message_id": "m1", "delta": "old"},
            },
        }
        # New event -> should pass
        yield {
            "id": "2-0",
            "data": {
                "type": "text_delta",
                "event_time_us": 20,
                "event_counter": 4,
                "data": {"message_id": "m1", "delta": "new"},
            },
        }
        yield {
            "id": "3-0",
            "data": {
                "type": "complete",
                "event_time_us": 21,
                "event_counter": 1,
                "data": {"message_id": "m1", "content": "done"},
            },
        }

    service._event_bus.stream_read = _stream_read
    service._read_delayed_events = AsyncMock(return_value=[])
    service._handle_title_generation = AsyncMock()

    events = []
    async for event in service.connect_chat_stream(
        conversation_id="conv-1",
        message_id="m1",
        replay_from_db=False,
        from_time_us=20,
        from_counter=3,
    ):
        events.append(event)

    assert [event["type"] for event in events] == ["text_delta", "complete"]
    assert events[0]["data"]["delta"] == "new"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_connect_chat_stream_keeps_higher_cursor_than_replay() -> None:
    service = _build_service()

    async def _stream_read(*_args, **_kwargs):
        # lower/equal than caller cursor(40,2) -> skip
        yield {
            "id": "1-0",
            "data": {
                "type": "text_delta",
                "event_time_us": 40,
                "event_counter": 2,
                "data": {"message_id": "m1", "delta": "skip"},
            },
        }
        # greater than caller cursor -> yield
        yield {
            "id": "2-0",
            "data": {
                "type": "text_delta",
                "event_time_us": 40,
                "event_counter": 3,
                "data": {"message_id": "m1", "delta": "keep"},
            },
        }
        yield {
            "id": "3-0",
            "data": {
                "type": "complete",
                "event_time_us": 41,
                "event_counter": 1,
                "data": {"message_id": "m1", "content": "done"},
            },
        }

    # replay still enabled, but caller cursor should remain authoritative if greater
    service._replay_db_events = AsyncMock(return_value=([], 31, 1, False))
    service._event_bus.stream_read = _stream_read
    service._read_delayed_events = AsyncMock(return_value=[])
    service._handle_title_generation = AsyncMock()

    events = []
    async for event in service.connect_chat_stream(
        conversation_id="conv-1",
        message_id="m1",
        replay_from_db=True,
        from_time_us=40,
        from_counter=2,
    ):
        events.append(event)

    assert [event["type"] for event in events] == ["text_delta", "complete"]
    assert events[0]["data"]["delta"] == "keep"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_connect_chat_stream_persists_live_tool_execution_records() -> None:
    tool_record_repo = _InMemoryToolExecutionRecordRepo()
    service = _build_service(tool_record_repo)

    async def _stream_read(*_args: Any, **_kwargs: Any):
        yield {
            "id": "1-0",
            "data": {
                "type": "act",
                "event_time_us": 1_000_000,
                "event_counter": 1,
                "data": {
                    "message_id": "m1",
                    "tool_execution_id": "ter-1",
                    "call_id": "call-1",
                    "tool_name": "bash",
                    "tool_input": {"command": "git status"},
                },
            },
        }
        yield {
            "id": "2-0",
            "data": {
                "type": "observe",
                "event_time_us": 1_200_000,
                "event_counter": 2,
                "data": {
                    "message_id": "m1",
                    "tool_execution_id": "ter-1",
                    "call_id": "call-1",
                    "tool_name": "bash",
                    "result": {"exit_code": 0, "output": "clean"},
                    "duration_ms": 25.8,
                    "status": "success",
                },
            },
        }
        yield {
            "id": "3-0",
            "data": {
                "type": "complete",
                "event_time_us": 1_300_000,
                "event_counter": 3,
                "data": {"message_id": "m1", "content": "done"},
            },
        }

    service._replay_db_events = AsyncMock(return_value=([], 0, 0, False))
    service._event_bus.stream_read = _stream_read
    service._read_delayed_events = AsyncMock(return_value=[])
    service._handle_title_generation = AsyncMock()

    events = []
    async for event in service.connect_chat_stream(
        conversation_id="conv-1",
        message_id="m1",
        replay_from_db=False,
    ):
        events.append(event)

    assert [event["type"] for event in events] == ["act", "observe", "complete"]
    record = tool_record_repo.records["ter-1"]
    assert record.conversation_id == "conv-1"
    assert record.message_id == "m1"
    assert record.call_id == "call-1"
    assert record.tool_name == "bash"
    assert record.tool_input == {"command": "git status"}
    assert record.status == ToolExecutionStatus.SUCCESS
    assert record.tool_output == '{"exit_code": 0, "output": "clean"}'
    assert record.started_at == datetime.fromtimestamp(1, UTC)
    assert record.completed_at == datetime.fromtimestamp(1.2, UTC)
    assert record.duration_ms == 25


@pytest.mark.unit
@pytest.mark.asyncio
async def test_persist_tool_execution_event_marks_failed_observations() -> None:
    tool_record_repo = _InMemoryToolExecutionRecordRepo()
    service = _build_service(tool_record_repo)

    await service._persist_tool_execution_event(
        conversation_id="conv-1",
        message_id="m1",
        event_type="observe",
        event_data={
            "tool_execution_id": "ter-failed",
            "call_id": "call-failed",
            "tool_name": "bash",
            "error": "command failed",
            "duration_ms": "12",
            "status": "failed",
        },
        event_time_us=2_000_000,
        event_counter=5,
    )

    record = tool_record_repo.records["ter-failed"]
    assert record.status == ToolExecutionStatus.FAILED
    assert record.error == "command failed"
    assert record.completed_at == datetime.fromtimestamp(2, UTC)
    assert record.duration_ms == 12


@pytest.mark.unit
@pytest.mark.asyncio
async def test_persist_tool_execution_event_strips_nul_bytes() -> None:
    tool_record_repo = _InMemoryToolExecutionRecordRepo()
    service = _build_service(tool_record_repo)

    await service._persist_tool_execution_event(
        conversation_id="conv-1",
        message_id="m1",
        event_type="act",
        event_data={
            "tool_execution_id": "ter-binary",
            "call_id": "call-binary",
            "tool_name": "bash",
            "tool_input": {"command": "printf '\\0'", "nested": ["a\x00b"]},
        },
        event_time_us=2_000_000,
        event_counter=5,
    )
    await service._persist_tool_execution_event(
        conversation_id="conv-1",
        message_id="m1",
        event_type="observe",
        event_data={
            "tool_execution_id": "ter-binary",
            "call_id": "call-binary",
            "tool_name": "bash",
            "result": "binary\x00payload",
            "status": "success",
        },
        event_time_us=2_100_000,
        event_counter=6,
    )

    record = tool_record_repo.records["ter-binary"]
    assert record.tool_input == {"command": "printf '\\0'", "nested": ["ab"]}
    assert record.tool_output == "binarypayload"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_replay_db_events_repairs_malformed_task_list_updated_payload() -> None:
    service = _build_service()
    created_at = datetime.now(UTC)
    task_snapshot = [
        {
            "id": "task-1",
            "conversation_id": "conv-1",
            "content": "Repair replay payload",
            "status": "pending",
            "priority": "medium",
            "order_index": 0,
            "created_at": created_at.isoformat(),
            "updated_at": created_at.isoformat(),
        }
    ]
    service._agent_execution_event_repo.get_events_by_message.return_value = [
        SimpleNamespace(
            event_type="task_list_updated",
            event_data={},
            created_at=created_at,
            event_time_us=55,
            event_counter=2,
        )
    ]
    service._load_task_snapshot = AsyncMock(return_value=task_snapshot)

    events, last_event_time_us, last_event_counter, saw_complete = await service._replay_db_events(
        "conv-1",
        "msg-1",
    )

    assert events == [
        {
            "type": "task_list_updated",
            "data": {"conversation_id": "conv-1", "tasks": task_snapshot},
            "timestamp": created_at.isoformat(),
            "event_time_us": 55,
            "event_counter": 2,
        }
    ]
    assert last_event_time_us == 55
    assert last_event_counter == 2
    assert saw_complete is False
    service._agent_execution_event_repo.get_events_by_message.assert_awaited_once_with(
        conversation_id="conv-1",
        message_id="msg-1",
    )
    service._load_task_snapshot.assert_awaited_once_with("conv-1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_replay_db_events_replaces_malformed_task_updated_with_snapshot() -> None:
    service = _build_service()
    created_at = datetime.now(UTC)
    task_snapshot = [
        {
            "id": "task-1",
            "conversation_id": "conv-1",
            "content": "Recovered task state",
            "status": "in_progress",
            "priority": "medium",
            "order_index": 0,
            "created_at": created_at.isoformat(),
            "updated_at": created_at.isoformat(),
        }
    ]
    service._agent_execution_event_repo.get_events_by_message.return_value = [
        SimpleNamespace(
            event_type="task_updated",
            event_data={"conversation_id": "conv-1"},
            created_at=created_at,
            event_time_us=89,
            event_counter=4,
        )
    ]
    service._load_task_snapshot = AsyncMock(return_value=task_snapshot)

    events, last_event_time_us, last_event_counter, saw_complete = await service._replay_db_events(
        "conv-1",
        "msg-1",
    )

    assert events == [
        {
            "type": "task_list_updated",
            "data": {"conversation_id": "conv-1", "tasks": task_snapshot},
            "timestamp": created_at.isoformat(),
            "event_time_us": 89,
            "event_counter": 4,
        }
    ]
    assert last_event_time_us == 89
    assert last_event_counter == 4
    assert saw_complete is False
    service._agent_execution_event_repo.get_events_by_message.assert_awaited_once_with(
        conversation_id="conv-1",
        message_id="msg-1",
    )
    service._load_task_snapshot.assert_awaited_once_with("conv-1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_replay_db_events_repairs_task_update_for_wrong_conversation() -> None:
    service = _build_service()
    created_at = datetime.now(UTC)
    task_snapshot = [
        {
            "id": "task-2",
            "conversation_id": "conv-1",
            "content": "Correct conversation snapshot",
            "status": "completed",
            "priority": "medium",
            "order_index": 1,
            "created_at": created_at.isoformat(),
            "updated_at": created_at.isoformat(),
        }
    ]
    service._agent_execution_event_repo.get_events_by_message.return_value = [
        SimpleNamespace(
            event_type="task_updated",
            event_data={
                "conversation_id": "conv-other",
                "task_id": "task-2",
                "status": "completed",
            },
            created_at=created_at,
            event_time_us=144,
            event_counter=5,
        )
    ]
    service._load_task_snapshot = AsyncMock(return_value=task_snapshot)

    events, last_event_time_us, last_event_counter, saw_complete = await service._replay_db_events(
        "conv-1",
        "msg-1",
    )

    assert events == [
        {
            "type": "task_list_updated",
            "data": {"conversation_id": "conv-1", "tasks": task_snapshot},
            "timestamp": created_at.isoformat(),
            "event_time_us": 144,
            "event_counter": 5,
        }
    ]
    assert last_event_time_us == 144
    assert last_event_counter == 5
    assert saw_complete is False
    service._agent_execution_event_repo.get_events_by_message.assert_awaited_once_with(
        conversation_id="conv-1",
        message_id="msg-1",
    )
    service._load_task_snapshot.assert_awaited_once_with("conv-1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_extract_first_user_message_scopes_event_lookup_to_conversation() -> None:
    service = _build_service()
    service._agent_execution_event_repo.get_events_by_message.return_value = [
        SimpleNamespace(
            event_type="user_message",
            event_data={"content": "hello"},
        )
    ]

    content = await service._extract_first_user_message("conv-1", "msg-1")

    assert content == "hello"
    service._agent_execution_event_repo.get_events_by_message.assert_awaited_once_with(
        conversation_id="conv-1",
        message_id="msg-1",
    )
