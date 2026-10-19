"""Cancellation settles exact run tool records without affecting adjacent work."""

from datetime import UTC, datetime, timedelta

import pytest

from src.infrastructure.adapters.secondary.persistence.agent_run_settlement import settle_agent_run
from src.infrastructure.adapters.secondary.persistence.agent_run_tool_settlement import (
    settle_cancelled_run_tools,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    ToolExecutionRecord,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_run_authority import (
    ensure_chat_run_authority,
)

pytestmark = pytest.mark.unit


@pytest.fixture
async def tool_settlement_fixture(test_db, test_project_db, test_user):
    conversation = Conversation(
        id="tool-settlement-conversation",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        user_id=test_user.id,
        title="Tool cancellation",
    )
    other = Conversation(
        id="other-tool-settlement-conversation",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        user_id=test_user.id,
        title="Other work",
    )
    test_db.add_all([conversation, other])
    await test_db.commit()
    run = await ensure_chat_run_authority(
        test_db,
        conversation=conversation,
        run_id="tool-settlement-run",
        request_message="Observe",
        client_message_id=None,
        app_model_context=None,
    )
    now = datetime.now(UTC)
    records = []
    for name, conversation_id, message_id, status, completed in (
        ("interrupted", conversation.id, run.message_id, "running", None),
        ("success", conversation.id, run.message_id, "success", now),
        ("failed", conversation.id, run.message_id, "failed", now),
        ("next-run", conversation.id, "next-message", "running", None),
        ("other-conversation", other.id, run.message_id, "running", None),
    ):
        row = ToolExecutionRecord(
            id=name,
            conversation_id=conversation_id,
            message_id=message_id,
            call_id=f"call-{name}",
            tool_name="computer_get_app_state",
            tool_input={},
            tool_output="retained result" if completed else None,
            status=status,
            sequence_number=len(records),
            started_at=now - timedelta(seconds=2),
            completed_at=completed,
            duration_ms=7 if completed else None,
        )
        records.append(row)
    test_db.add_all(records)
    await test_db.commit()
    return test_db, run, records, now


async def test_terminal_transaction_settles_only_its_unfinished_tool(tool_settlement_fixture):
    db, run, records, now = tool_settlement_fixture
    run.status = "cancelled"
    run.completed_at = now
    await settle_agent_run(
        db, run=run, started_at=now - timedelta(seconds=2), succeeded=False, completed_at=now
    )
    await db.commit()

    for record in records:
        await db.refresh(record)
    interrupted, success, failed, next_run, other_conversation = records
    assert interrupted.status == "cancelled"
    assert interrupted.completed_at is not None
    assert interrupted.duration_ms == 2000
    assert interrupted.error == "Run cancelled before tool completion"
    assert interrupted.tool_output is None
    assert [(row.status, row.tool_output, row.duration_ms) for row in (success, failed)] == [
        ("success", "retained result", 7),
        ("failed", "retained result", 7),
    ]
    assert next_run.status == other_conversation.status == "running"
    assert await settle_cancelled_run_tools(db, run=run) == 0


@pytest.mark.parametrize("status", ["queued", "running", "completed", "failed"])
async def test_non_cancelled_run_does_not_settle_tools(tool_settlement_fixture, status):
    db, run, records, now = tool_settlement_fixture
    run.status = status
    run.completed_at = now
    assert await settle_cancelled_run_tools(db, run=run) == 0
    assert records[0].status == "running"


async def test_cancelled_run_without_terminal_time_does_not_settle_tools(tool_settlement_fixture):
    db, run, records, _ = tool_settlement_fixture
    run.status = "cancelled"
    assert await settle_cancelled_run_tools(db, run=run) == 0
    assert records[0].status == "running"


@pytest.mark.parametrize("field", ["tenant_id", "project_id"])
async def test_foreign_scope_cannot_settle_tool(tool_settlement_fixture, field):
    db, run, records, now = tool_settlement_fixture
    run.status = "cancelled"
    run.completed_at = now
    # Keep the unrelated identity out of the database while validating query scope.
    with db.no_autoflush:
        setattr(run, field, "foreign")
        assert await settle_cancelled_run_tools(db, run=run) == 0
    await db.rollback()
    await db.refresh(records[0])
    assert records[0].status == "running"
