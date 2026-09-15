"""Independent review of real SQL producer reorder and collision behavior."""

import asyncio

import pytest
from sqlalchemy import select

from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent,
    ToolExecutionRecord,
)
from src.tests.unit.infrastructure.plugins.v2.test_tool_execution_producer_projection import (
    event,
)

pytest_plugins = [
    "src.tests.unit.infrastructure.plugins.v2.test_tool_execution_producer_projection"
]


@pytest.mark.unit
async def test_duplicate_running_act_keeps_original_start_and_input(producer, test_db):
    store, cid = producer
    for counter, text in [(1, "original"), (2, "changed-replay")]:
        await store.append_stream_events(
            conversation_id=cid,
            message_id="turn",
            events=[event("act", counter, tool_input={"text": text})],
            correlation_id=None,
        )
    test_db.expire_all()
    row = await test_db.get(ToolExecutionRecord, "exact-execution")
    assert row.tool_input == {"text": "original"}
    assert row.sequence_number == 1


@pytest.mark.unit
async def test_unknown_observe_does_not_invent_success(producer, test_db):
    store, cid = producer
    with pytest.raises(ValueError, match="unknown terminal"):
        await store.append_stream_events(
            conversation_id=cid,
            message_id="turn",
            events=[event("observe", 1, status="unknown")],
            correlation_id=None,
        )
    test_db.expire_all()
    row = await test_db.get(ToolExecutionRecord, "exact-execution")
    assert row is None or row.status != "success"


@pytest.mark.unit
async def test_concurrent_replay_creates_single_terminal_record(producer, test_db):
    store, cid = producer

    async def append():
        await store.append_stream_events(
            conversation_id=cid,
            message_id="turn",
            events=[event("act", 1), event("observe", 2, status="success", result="ok")],
            correlation_id=None,
        )

    await asyncio.gather(append(), append())
    test_db.expire_all()
    rows = list((await test_db.execute(select(ToolExecutionRecord))).scalars())
    assert len(rows) == 1
    assert rows[0].status == "success"
    events = list((await test_db.execute(select(AgentExecutionEvent))).scalars())
    assert len(events) == 2


@pytest.mark.unit
async def test_cancelled_projection_rolls_back_event_and_tool(producer, test_db, monkeypatch):
    from src.infrastructure.plugins.v2 import session_event_log_store as store_module

    original = store_module.apply_tool_execution_event_projection

    async def cancel_after_projection(*args, **kwargs):
        await original(*args, **kwargs)
        raise asyncio.CancelledError

    monkeypatch.setattr(
        store_module, "apply_tool_execution_event_projection", cancel_after_projection
    )
    store, cid = producer
    with pytest.raises(asyncio.CancelledError):
        await store.append_stream_events(
            conversation_id=cid, message_id="turn", events=[event("act", 1)], correlation_id=None
        )
    assert list((await test_db.execute(select(ToolExecutionRecord))).scalars()) == []
    assert list((await test_db.execute(select(AgentExecutionEvent))).scalars()) == []


@pytest.mark.unit
async def test_other_conversation_collision_rolls_back(
    producer, test_db, test_project_db, test_user
):
    from src.infrastructure.adapters.secondary.persistence.models import Conversation

    store, cid = producer
    other = Conversation(
        id="other-projection-conversation",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        user_id=test_user.id,
        title="Other",
    )
    test_db.add(other)
    await test_db.commit()
    await store.append_stream_events(
        conversation_id=cid, message_id="turn", events=[event("act", 1)], correlation_id=None
    )
    with pytest.raises(ValueError, match="identity"):
        await store.append_stream_events(
            conversation_id=other.id,
            message_id="turn",
            events=[event("observe", 2, status="success", result="foreign")],
            correlation_id=None,
        )
    test_db.expire_all()
    row = await test_db.get(ToolExecutionRecord, "exact-execution")
    assert row.conversation_id == cid
    assert row.status == "running"
    events = list((await test_db.execute(select(AgentExecutionEvent))).scalars())
    assert len(events) == 1
    assert events[0].conversation_id == cid
