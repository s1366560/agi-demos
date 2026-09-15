"""Creation results must provide durable identifiers usable by the next tool call."""

import copy
import json
import uuid
from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.infrastructure.adapters.secondary.persistence.models import (
    AgentPlanVersionModel,
    AgentTaskModel,
    Conversation,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.todo_tools import make_todo_tools


@pytest.mark.unit
@pytest.mark.parametrize(
    "patch,new_draft",
    [
        ({"status": "completed"}, False),
        ({"result_summary": "Verified", "evidence_refs": ["evidence-1"]}, False),
        ({"started_at": "2026-09-14T10:00:00Z", "completed_at": "2026-09-14T10:01:00Z"}, False),
        ({"content": "Revised task"}, True),
        ({"priority": "high"}, True),
        ({"status": "completed", "content": "Revised task"}, True),
    ],
)
async def test_progress_keeps_approved_snapshot_and_structural_changes_create_draft(
    test_db, test_engine, test_user, test_project_db, patch, new_draft
):
    conversation = Conversation(
        id=str(uuid.uuid4()),
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        user_id=test_user.id,
        title="Task identifier round trip",
    )
    test_db.add(conversation)
    await test_db.commit()
    tools = make_todo_tools(session_factory=async_sessionmaker(test_engine, expire_on_commit=False))
    ctx = ToolContext(
        session_id=conversation.id,
        conversation_id=conversation.id,
        tenant_id=conversation.tenant_id,
        project_id=conversation.project_id,
        user_id=test_user.id,
        message_id="task-id-round-trip",
        call_id="create",
        agent_name="test-agent",
    )
    created = await tools["todowrite"].execute(
        ctx,
        action="replace",
        todos=[{"content": "Verify the read result", "status": "pending"}],
    )
    assert not created.is_error
    payload = json.loads(created.output)
    task = payload["todos"][0]
    assert payload["total_count"] == 1
    assert "todo_id" in payload["update_instruction"]
    assert task["content"] == "Verify the read result"
    assert task["status"] == "pending"
    assert str(uuid.UUID(task["id"])) == task["id"]
    stored = await test_db.get(AgentTaskModel, task["id"])
    assert stored.conversation_id == conversation.id
    approved = await test_db.scalar(select(AgentPlanVersionModel))
    approved.status = "approved"
    await test_db.commit()
    snapshot = copy.deepcopy(approved.tasks_json)
    updated = await tools["todowrite"].execute(
        ctx, action="update", todo_id=task["id"], todos=[patch]
    )
    assert not updated.is_error
    await test_db.refresh(stored)
    await test_db.refresh(approved)
    for key, value in patch.items():
        actual = getattr(stored, key)
        if key in {"started_at", "completed_at"}:
            assert actual.replace(tzinfo=None) == datetime.fromisoformat(value).replace(tzinfo=None)
        else:
            assert actual == value
    assert approved.tasks_json == snapshot
    assert approved.status == "approved"
    plans = list(
        (
            await test_db.execute(
                select(AgentPlanVersionModel).order_by(AgentPlanVersionModel.version)
            )
        ).scalars()
    )
    assert len(plans) == (2 if new_draft else 1)
    if new_draft:
        assert plans[-1].status == "draft"
    from src.infrastructure.adapters.secondary.persistence.sql_conversation_session_projection_reader import (
        SqlConversationSessionProjectionReader,
    )

    reader = SqlConversationSessionProjectionReader(test_db, None)
    projected = await reader._load_conversation_tasks(conversation.id)
    assert projected[0].status == patch.get("status", "pending")
    assert projected[0].content == patch.get("content", "Verify the read result")
