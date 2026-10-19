"""Actual producer SQL persistence does not require a stream subscriber."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    ToolExecutionRecord,
)
from src.infrastructure.plugins.v2 import session_event_log_store as store_module
from src.infrastructure.plugins.v2.session_event_log_store import SqlSessionEventLogStoreV2


@pytest.fixture
async def producer(test_db, test_engine, test_project_db, test_user, monkeypatch):
    cid = "unsubscribed-producer"
    test_db.add(
        Conversation(
            id=cid,
            tenant_id=test_project_db.tenant_id,
            project_id=test_project_db.id,
            user_id=test_user.id,
            title="Producer",
        )
    )
    await test_db.commit()
    monkeypatch.setattr(
        store_module,
        "async_session_factory",
        async_sessionmaker(test_engine, expire_on_commit=False),
    )
    return SqlSessionEventLogStoreV2(), cid


def event(kind, counter, **data):
    return {
        "type": kind,
        "event_time_us": 1_000_000 + counter,
        "event_counter": counter,
        "data": {
            "tool_execution_id": "exact-execution",
            "call_id": "exact-call",
            "tool_name": "opaque_tool",
            **data,
        },
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    "outcome,expected",
    [
        ({"result": {"score": 42}, "status": "success"}, "success"),
        ({"error": "Rejected", "status": "permission_denied"}, "permission_denied"),
        ({"error": "Exception", "status": "failed"}, "failed"),
        ({"error": "Cancelled", "status": "cancelled"}, "cancelled"),
    ],
)
async def test_unsubscribed_producer_settles_and_replay_does_not_regress(
    producer, test_db, outcome, expected
):
    store, cid = producer
    act = event("act", 1, tool_input={"text": "safe"})
    observation = event("observe", 2, **outcome)

    async def append(events):
        await store.append_stream_events(
            conversation_id=cid, message_id="turn", events=events, correlation_id=None
        )

    await append([act])
    await append([observation])
    await append([act, observation])
    await append([event("act", 3, tool_input={"text": "late"})])
    test_db.expire_all()
    rows = list((await test_db.execute(select(ToolExecutionRecord))).scalars())
    assert len(rows) == 1
    row = rows[0]
    assert (row.conversation_id, row.message_id, row.call_id) == (cid, "turn", "exact-call")
    assert row.status == expected
    assert row.tool_input == {"text": "safe"}
    assert row.completed_at.replace(tzinfo=UTC) == datetime.fromtimestamp(1.000002, UTC)
    assert row.error == outcome.get("error")
    if expected == "success":
        assert row.tool_output == '{"score": 42}'


@pytest.mark.unit
@pytest.mark.parametrize("control", ["user_paused", "user_stopped"])
async def test_native_control_persists_cancelled_output_without_error(producer, test_db, control):
    import json

    store, cid = producer
    output = json.dumps({"type": "computer_use_control", "status": control, "retry_allowed": False})
    await store.append_stream_events(
        conversation_id=cid,
        message_id="turn",
        events=[
            event("act", 1),
            event(
                "observe", 2, status="cancelled", control_outcome=control, result={"output": output}
            ),
        ],
        correlation_id=None,
    )
    row = await test_db.get(ToolExecutionRecord, "exact-execution")
    assert row.status == "cancelled" and row.error is None
    assert row.tool_output == output


@pytest.mark.unit
async def test_control_marker_cannot_hide_real_error(producer, test_db):
    store, cid = producer
    await store.append_stream_events(
        conversation_id=cid,
        message_id="turn",
        events=[
            event(
                "observe",
                1,
                status="cancelled",
                control_outcome="user_stopped",
                error="permission_denied",
            )
        ],
        correlation_id=None,
    )
    row = await test_db.get(ToolExecutionRecord, "exact-execution")
    assert row.status == "failed" and row.error == "permission_denied"


@pytest.mark.unit
@pytest.mark.parametrize("control", ["user_paused", "user_stopped", None])
async def test_only_pending_paused_control_can_upgrade_to_real_wait_failure(
    producer, test_db, control
):
    import json

    store, cid = producer
    output = json.dumps({"type": "computer_use_control", "status": control, "retry_allowed": False})
    paused = event(
        "observe", 2, status="cancelled", control_outcome=control, result={"output": output}
    )
    failure = event(
        "observe",
        3,
        status="error",
        control_outcome="user_paused",
        error="native_control_wait_failed",
    )
    for events in (
        [event("act", 1), paused],
        [failure],
        [paused],
        [event("observe", 4, status="success", result="late")],
    ):
        await store.append_stream_events(
            conversation_id=cid, message_id="turn", events=events, correlation_id=None
        )
    test_db.expire_all()
    row = await test_db.get(ToolExecutionRecord, "exact-execution")
    assert row.status == ("failed" if control == "user_paused" else "cancelled")
    if control == "user_paused":
        assert row.error == "native_control_wait_failed"
        assert row.completed_at.replace(tzinfo=UTC) == datetime.fromtimestamp(1.000003, UTC)


@pytest.mark.unit
@pytest.mark.parametrize(
    "output,typed,counter",
    [
        ("invalid json", True, 3),
        ("[]", True, 3),
        ('{"type":"computer_use_control","status":"user_paused","retry_allowed":0}', True, 3),
        ('{"type":"computer_use_control","status":"user_paused","retry_allowed":false}', False, 3),
        ('{"type":"computer_use_control","status":"user_paused","retry_allowed":false}', True, 1),
    ],
)
async def test_untrusted_or_stale_failure_cannot_upgrade_cancelled_record(
    producer, test_db, output, typed, counter
):
    store, cid = producer
    await store.append_stream_events(
        conversation_id=cid,
        message_id="turn",
        events=[
            event(
                "observe",
                2,
                status="cancelled",
                control_outcome="user_paused" if typed else None,
                result={"output": output},
            ),
            event("observe", counter, status="error", control_outcome="user_paused", error="lost"),
        ],
        correlation_id=None,
    )
    row = await test_db.get(ToolExecutionRecord, "exact-execution")
    assert row.status == "cancelled"


@pytest.mark.unit
@pytest.mark.parametrize("field", ["message_id", "call_id", "tool_name"])
async def test_pause_failure_cannot_reassign_call_identity(producer, test_db, field):
    store, cid = producer
    output = '{"type":"computer_use_control","status":"user_paused","retry_allowed":false}'
    await store.append_stream_events(
        conversation_id=cid,
        message_id="turn",
        events=[
            event("observe", 2, status="cancelled", control_outcome="user_paused", result=output)
        ],
        correlation_id=None,
    )
    changes = {} if field == "message_id" else {field: "foreign"}
    with pytest.raises(ValueError, match="identity"):
        await store.append_stream_events(
            conversation_id=cid,
            message_id="foreign" if field == "message_id" else "turn",
            events=[
                event(
                    "observe",
                    3,
                    status="error",
                    control_outcome="user_paused",
                    error="lost",
                    **changes,
                )
            ],
            correlation_id=None,
        )
    row = await test_db.get(ToolExecutionRecord, "exact-execution")
    assert row.status == "cancelled" and row.error is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "field,value",
    [("message_id", "other-turn"), ("call_id", "other-call"), ("tool_name", "other-tool")],
)
async def test_collision_cannot_reassign_existing_execution(producer, test_db, field, value):
    store, cid = producer
    await store.append_stream_events(
        conversation_id=cid, message_id="turn", events=[event("act", 1)], correlation_id=None
    )
    kwargs = {field: value} if field != "message_id" else {}
    with pytest.raises(ValueError, match="identity"):
        await store.append_stream_events(
            conversation_id=cid,
            message_id=value if field == "message_id" else "turn",
            events=[event("observe", 2, status="success", result="wrong", **kwargs)],
            correlation_id=None,
        )
    test_db.expire_all()
    row = await test_db.get(ToolExecutionRecord, "exact-execution")
    assert row.status == "running"
    assert row.tool_output is None


@pytest.mark.unit
async def test_observe_before_act_preserves_original_input_without_reopening(producer, test_db):
    store, cid = producer
    for value in [
        event("observe", 3, status="completed", result="done"),
        event("act", 1, tool_input={"original": True}),
        event("act", 2, tool_input={"later": True}),
    ]:
        await store.append_stream_events(
            conversation_id=cid, message_id="turn", events=[value], correlation_id=None
        )
    row = await test_db.get(ToolExecutionRecord, "exact-execution")
    assert row.status == "success"
    assert row.tool_output == "done"
    assert row.tool_input == {"original": True}
    assert row.sequence_number == 1
    assert row.started_at.replace(tzinfo=UTC) == datetime.fromtimestamp(1.000001, UTC)


@pytest.mark.unit
async def test_unknown_observation_does_not_claim_success(producer, test_db):
    store, cid = producer
    with pytest.raises(ValueError, match="unknown terminal"):
        await store.append_stream_events(
            conversation_id=cid,
            message_id="turn",
            events=[event("observe", 1, status="running", result="not done")],
            correlation_id=None,
        )
    assert await test_db.get(ToolExecutionRecord, "exact-execution") is None


@pytest.mark.unit
async def test_same_execution_id_cannot_move_conversations(
    producer, test_db, test_user, test_project_db
):
    store, cid = producer
    other = Conversation(
        id="sibling",
        user_id=test_user.id,
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        title="Other",
    )
    test_db.add(other)
    await test_db.commit()
    await store.append_stream_events(
        conversation_id=cid, message_id="turn", events=[event("act", 1)], correlation_id=None
    )
    with pytest.raises(ValueError, match="identity"):
        await store.append_stream_events(
            conversation_id="sibling",
            message_id="turn",
            events=[event("observe", 2, status="completed", result="wrong")],
            correlation_id=None,
        )
    row = await test_db.get(ToolExecutionRecord, "exact-execution")
    assert row.conversation_id == cid
    assert row.status == "running"


@pytest.mark.unit
async def test_projector_uses_existing_log_redaction(producer, test_db):
    store, cid = producer
    await store.append_stream_events(
        conversation_id=cid,
        message_id="turn",
        events=[
            event("act", 1, tool_input={"nested": ["a\x00b"]}),
            event("observe", 2, status="completed", result="value\x00end"),
        ],
        correlation_id=None,
    )
    row = await test_db.get(ToolExecutionRecord, "exact-execution")
    assert row.tool_input == {"nested": ["a[NUL]b"]}
    assert row.tool_output == "value[NUL]end"


@pytest.mark.unit
@pytest.mark.parametrize(
    "kind",
    [
        "act",
        "observe",
        "permission_asked",
        "decision_asked",
        "clarification_asked",
        "env_var_requested",
    ],
)
async def test_producer_flushes_tool_and_pause_boundary_before_waiting(kind):
    from src.infrastructure.agent.actor.execution import _extract_event_side_effects

    assert _extract_event_side_effects({"type": kind, "data": {}}).should_flush_events
