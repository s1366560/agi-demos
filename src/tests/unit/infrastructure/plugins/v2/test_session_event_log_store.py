"""Ordered SQL store tests for the protocol-v2 session event log."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.plugins.v2 import session_event_log_store as store_module
from src.infrastructure.plugins.v2.session_event_log import SessionEventCursorV2
from src.infrastructure.plugins.v2.session_event_log_store import SqlSessionEventLogStoreV2


def _session_context(session: MagicMock) -> AsyncMock:
    context = AsyncMock()
    context.__aenter__.return_value = session
    context.__aexit__.return_value = None
    return context


def _append_session(*execute_results: object) -> tuple[MagicMock, AsyncMock]:
    session = MagicMock()
    session.execute = AsyncMock(side_effect=list(execute_results))
    transaction = AsyncMock()
    transaction.__aenter__.return_value = None
    transaction.__aexit__.return_value = None
    session.begin.return_value = transaction
    return session, _session_context(session)


def _existing_assistant_result(*sources: str) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = [{"source": source} for source in sources]
    return result


def _insert_result(row: tuple[str, int] | None) -> MagicMock:
    result = MagicMock()
    result.one_or_none.return_value = row
    return result


def _jwt_like_token() -> str:
    return (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJ1c2VySWQiOiJ1c2VyLTEiLCJlbWFpbCI6InVzZXJAZXhhbXBsZS5jb20ifQ."
        "abc123abc123abc123abc123abc123abc123"
    )


@pytest.mark.unit
async def test_append_treats_duplicate_cursor_as_idempotent() -> None:
    session, session_context = _append_session(
        _existing_assistant_result(),
        _insert_result(None),
    )
    projection = AsyncMock()

    with (
        patch.object(store_module, "async_session_factory", return_value=session_context),
        patch.object(
            store_module,
            "apply_conversation_event_projection_delta",
            new=projection,
        ),
    ):
        await SqlSessionEventLogStoreV2().append_stream_events(
            conversation_id="conversation-a",
            message_id="message-a",
            events=[
                {
                    "type": "observe",
                    "data": {"result": "already stored"},
                    "event_time_us": 100,
                    "event_counter": 4,
                }
            ],
            correlation_id="correlation-a",
        )

    insert_statement = session.execute.await_args_list[1].args[0]
    assert "ON CONFLICT (conversation_id, event_time_us, event_counter) DO NOTHING" in str(
        insert_statement
    )
    projection.assert_awaited_once_with(
        session,
        "conversation-a",
        inserted_message_count=0,
        latest_event_time_us=None,
    )


@pytest.mark.unit
async def test_append_keeps_complete_metadata_without_duplicate_assistant_message() -> None:
    session, session_context = _append_session(
        _existing_assistant_result(),
        _insert_result(("assistant_message", 200)),
        _insert_result(("complete", 201)),
    )
    projection = AsyncMock()

    with (
        patch.object(store_module, "async_session_factory", return_value=session_context),
        patch.object(
            store_module,
            "apply_conversation_event_projection_delta",
            new=projection,
        ),
    ):
        await SqlSessionEventLogStoreV2().append_stream_events(
            conversation_id="conversation-a",
            message_id="message-a",
            events=[
                {
                    "type": "text_end",
                    "data": {"full_text": "final answer"},
                    "event_time_us": 200,
                    "event_counter": 0,
                },
                {
                    "type": "complete",
                    "data": {
                        "content": "final answer",
                        "execution_summary": {"step_count": 2},
                    },
                    "event_time_us": 201,
                    "event_counter": 0,
                },
            ],
            correlation_id=None,
        )

    persisted_types = [
        call.args[0].compile().params["event_type"] for call in session.execute.await_args_list[1:]
    ]
    assert persisted_types == ["assistant_message", "complete"]
    projection.assert_awaited_once_with(
        session,
        "conversation-a",
        inserted_message_count=1,
        latest_event_time_us=201,
    )


@pytest.mark.unit
async def test_append_keeps_complete_metadata_after_persisted_text_end() -> None:
    session, session_context = _append_session(
        _existing_assistant_result("text_end"),
        _insert_result(("complete", 210)),
    )
    projection = AsyncMock()

    with (
        patch.object(store_module, "async_session_factory", return_value=session_context),
        patch.object(
            store_module,
            "apply_conversation_event_projection_delta",
            new=projection,
        ),
    ):
        await SqlSessionEventLogStoreV2().append_stream_events(
            conversation_id="conversation-a",
            message_id="message-a",
            events=[
                {
                    "type": "complete",
                    "data": {
                        "content": "final answer",
                        "execution_summary": {"step_count": 2},
                    },
                    "event_time_us": 210,
                    "event_counter": 0,
                }
            ],
            correlation_id=None,
        )

    statement = session.execute.await_args_list[1].args[0]
    assert statement.compile().params["event_type"] == "complete"
    assert statement.compile().params["event_data"]["execution_summary"] == {
        "step_count": 2
    }
    projection.assert_awaited_once_with(
        session,
        "conversation-a",
        inserted_message_count=0,
        latest_event_time_us=210,
    )


@pytest.mark.unit
async def test_append_skips_complete_when_complete_assistant_already_exists() -> None:
    session, session_context = _append_session(_existing_assistant_result("complete"))
    projection = AsyncMock()

    with (
        patch.object(store_module, "async_session_factory", return_value=session_context),
        patch.object(
            store_module,
            "apply_conversation_event_projection_delta",
            new=projection,
        ),
    ):
        await SqlSessionEventLogStoreV2().append_stream_events(
            conversation_id="conversation-a",
            message_id="message-a",
            events=[{"type": "complete", "data": {"content": "final answer"}}],
            correlation_id=None,
        )

    assert session.execute.await_count == 1
    projection.assert_awaited_once_with(
        session,
        "conversation-a",
        inserted_message_count=0,
        latest_event_time_us=None,
    )


@pytest.mark.unit
async def test_append_preserves_metadata_only_completion() -> None:
    session, session_context = _append_session(
        _existing_assistant_result(),
        _insert_result(("assistant_message", 220)),
    )
    projection = AsyncMock()

    with (
        patch.object(store_module, "async_session_factory", return_value=session_context),
        patch.object(
            store_module,
            "apply_conversation_event_projection_delta",
            new=projection,
        ),
    ):
        await SqlSessionEventLogStoreV2().append_stream_events(
            conversation_id="conversation-a",
            message_id="message-a",
            events=[
                {
                    "type": "complete",
                    "data": {
                        "content": "",
                        "trace_url": "https://trace.example/empty",
                        "execution_summary": {"step_count": 2},
                    },
                    "event_time_us": 220,
                    "event_counter": 0,
                }
            ],
            correlation_id=None,
        )

    event_data = session.execute.await_args_list[1].args[0].compile().params["event_data"]
    assert event_data["content"] == ""
    assert event_data["source"] == "complete"
    assert event_data["trace_url"] == "https://trace.example/empty"
    assert event_data["execution_summary"] == {"step_count": 2}


@pytest.mark.unit
async def test_append_projects_terminal_workspace_status_as_assistant_message() -> None:
    session, session_context = _append_session(
        _existing_assistant_result(),
        _insert_result(("assistant_message", 230)),
    )
    projection = AsyncMock()

    with (
        patch.object(store_module, "async_session_factory", return_value=session_context),
        patch.object(
            store_module,
            "apply_conversation_event_projection_delta",
            new=projection,
        ),
    ):
        await SqlSessionEventLogStoreV2().append_stream_events(
            conversation_id="conversation-a",
            message_id="message-a",
            events=[
                {
                    "type": "status",
                    "data": {"status": "goal_achieved:workspace_contract_submitted"},
                    "event_time_us": 230,
                    "event_counter": 0,
                }
            ],
            correlation_id=None,
        )

    statement = session.execute.await_args_list[1].args[0]
    assert statement.compile().params["event_type"] == "assistant_message"
    event_data = statement.compile().params["event_data"]
    assert event_data["content"] == "Workspace contract submitted."
    assert event_data["source"] == "terminal_workspace_status"


@pytest.mark.unit
async def test_append_updates_projection_only_for_inserted_rows() -> None:
    session, session_context = _append_session(
        _existing_assistant_result(),
        _insert_result(("user_message", 300)),
        _insert_result(None),
        _insert_result(("observe", 302)),
    )
    projection = AsyncMock()

    with (
        patch.object(store_module, "async_session_factory", return_value=session_context),
        patch.object(
            store_module,
            "apply_conversation_event_projection_delta",
            new=projection,
        ),
    ):
        await SqlSessionEventLogStoreV2().append_stream_events(
            conversation_id="conversation-a",
            message_id="message-a",
            events=[
                {
                    "type": "user_message",
                    "data": {"role": "user", "content": "hello"},
                    "event_time_us": 300,
                    "event_counter": 0,
                },
                {
                    "type": "assistant_message",
                    "data": {"role": "assistant", "content": "duplicate"},
                    "event_time_us": 301,
                    "event_counter": 0,
                },
                {
                    "type": "observe",
                    "data": {"result": "ok"},
                    "event_time_us": 302,
                    "event_counter": 0,
                },
            ],
            correlation_id=None,
        )

    projection.assert_awaited_once_with(
        session,
        "conversation-a",
        inserted_message_count=1,
        latest_event_time_us=302,
    )


@pytest.mark.unit
async def test_append_redacts_legacy_payload_and_preserves_correlation_id() -> None:
    jwt = _jwt_like_token()
    session, session_context = _append_session(
        _existing_assistant_result(),
        _insert_result(("assistant_message", 310)),
    )
    projection = AsyncMock()
    correlation_id = "cron:0e464e94-b2e8-4dbe-8a13-08b203ba6667"

    with (
        patch.object(store_module, "async_session_factory", return_value=session_context),
        patch.object(
            store_module,
            "apply_conversation_event_projection_delta",
            new=projection,
        ),
    ):
        await SqlSessionEventLogStoreV2().append_stream_events(
            conversation_id="conversation-a",
            message_id="message-a",
            events=[
                {
                    "type": "assistant_message",
                    "content": f"legacy reply {jwt}",
                    "role": "assistant",
                    "source": "legacy",
                    "nested": [{"authorization": f"Bearer {jwt}"}],
                    "event_time_us": 310,
                    "event_counter": 0,
                }
            ],
            correlation_id=correlation_id,
        )

    params = session.execute.await_args_list[1].args[0].compile().params
    event_data = params["event_data"]
    assert event_data["role"] == "assistant"
    assert event_data["source"] == "legacy"
    assert jwt not in event_data["content"]
    assert event_data["nested"][0]["authorization"] == "Bearer [REDACTED_JWT]"
    assert params["correlation_id"] == correlation_id


@pytest.mark.unit
async def test_append_projects_run_input_application_after_insert() -> None:
    session, session_context = _append_session(
        _existing_assistant_result(),
        _insert_result(("run_input_applied", 320)),
    )
    conversation_projection = AsyncMock()
    run_input_projection = AsyncMock()
    event_data = {
        "run_input_id": "input-1",
        "run_id": "run-1",
        "run_revision": 4,
        "message_id": "message-1",
        "idempotency_key": "input-key-1",
        "delivery_mode": "steer_now",
        "applied_round": 3,
        "applied_at": "2026-08-04T01:00:00+00:00",
        "injected_via": "control_channel_observe_boundary",
    }

    with (
        patch.object(store_module, "async_session_factory", return_value=session_context),
        patch.object(
            store_module,
            "apply_conversation_event_projection_delta",
            new=conversation_projection,
        ),
        patch.object(
            store_module,
            "apply_run_input_applied_projection",
            new=run_input_projection,
        ),
    ):
        await SqlSessionEventLogStoreV2().append_stream_events(
            conversation_id="conversation-a",
            message_id="message-a",
            events=[
                {
                    "type": "run_input_applied",
                    "data": event_data,
                    "event_time_us": 320,
                    "event_counter": 0,
                }
            ],
            correlation_id=None,
        )

    run_input_projection.assert_awaited_once_with(session, event_data=event_data)


@pytest.mark.unit
async def test_append_executes_atomic_conversation_projection_update() -> None:
    session, session_context = _append_session(
        _existing_assistant_result(),
        _insert_result(("assistant_message", 330)),
        MagicMock(),
    )

    with patch.object(store_module, "async_session_factory", return_value=session_context):
        await SqlSessionEventLogStoreV2().append_stream_events(
            conversation_id="conversation-a",
            message_id="message-a",
            events=[{"type": "complete", "data": {"content": "final answer"}}],
            correlation_id=None,
        )

    executed_sql = [str(call.args[0]) for call in session.execute.await_args_list]
    inserted = session.execute.await_args_list[1].args[0].compile().params
    assert inserted["event_type"] == "assistant_message"
    assert inserted["event_data"]["content"] == "final answer"
    assert any("UPDATE conversations" in sql for sql in executed_sql)
    assert any("message_count" in sql for sql in executed_sql)
    assert any("updated_at" in sql for sql in executed_sql)


@pytest.mark.unit
async def test_append_propagates_database_failure() -> None:
    database_error = OSError("database unavailable")
    _session, session_context = _append_session(database_error)
    projection = AsyncMock()

    with (
        patch.object(store_module, "async_session_factory", return_value=session_context),
        patch.object(
            store_module,
            "apply_conversation_event_projection_delta",
            new=projection,
        ),
        pytest.raises(OSError, match="database unavailable"),
    ):
        await SqlSessionEventLogStoreV2().append_stream_events(
            conversation_id="conversation-a",
            message_id="message-a",
            events=[{"type": "observe", "data": {"result": "ok"}}],
            correlation_id=None,
        )

    projection.assert_not_awaited()


@pytest.mark.unit
async def test_read_events_uses_full_cursor_order_within_same_microsecond() -> None:
    rows = [
        SimpleNamespace(
            id="event-2",
            conversation_id="conversation-a",
            message_id="message-a",
            event_type="assistant_message",
            event_data={"role": "assistant", "content": "second"},
            event_time_us=400,
            event_counter=2,
        ),
        SimpleNamespace(
            id="event-3",
            conversation_id="conversation-a",
            message_id="message-a",
            event_type="user_message",
            event_data={"role": "user", "content": "third"},
            event_time_us=401,
            event_counter=0,
        ),
    ]
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session_context = _session_context(session)

    with patch.object(store_module, "async_session_factory", return_value=session_context):
        records = await SqlSessionEventLogStoreV2().read_events(
            conversation_id="conversation-a",
            after=SessionEventCursorV2(event_time_us=400, event_counter=1),
            limit=2,
        )

    statement = session.execute.await_args.args[0]
    sql = str(statement)
    assert "agent_execution_events.event_counter >" in sql
    assert (
        "ORDER BY agent_execution_events.event_time_us ASC, "
        "agent_execution_events.event_counter ASC"
    ) in sql
    assert [record.event_id for record in records] == ["event-2", "event-3"]
    assert [record.cursor for record in records] == [
        SessionEventCursorV2(event_time_us=400, event_counter=2),
        SessionEventCursorV2(event_time_us=401, event_counter=0),
    ]


@pytest.mark.unit
async def test_last_cursor_returns_origin_for_empty_stream() -> None:
    result = MagicMock()
    result.one_or_none.return_value = None
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session_context = _session_context(session)

    with patch.object(store_module, "async_session_factory", return_value=session_context):
        cursor = await SqlSessionEventLogStoreV2().last_cursor(conversation_id="conversation-a")

    assert cursor == SessionEventCursorV2()
