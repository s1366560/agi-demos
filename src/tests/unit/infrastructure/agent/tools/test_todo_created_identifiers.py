"""Creation results must provide durable identifiers usable by the next tool call."""

import json
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.infrastructure.adapters.secondary.persistence.models import AgentTaskModel, Conversation
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.todo_tools import make_todo_tools


@pytest.mark.unit
@pytest.mark.parametrize("action", ["replace", "add"])
async def test_created_task_result_identifies_persisted_task_for_progress_update(
    test_db, test_engine, test_user, test_project_db, action
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
        action=action,
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
    updated = await tools["todowrite"].execute(
        ctx,
        action="update",
        todo_id=task["id"],
        todos=[{"status": "completed"}],
    )
    assert not updated.is_error
    assert json.loads(updated.output)["todo_id"] == task["id"]
    await test_db.refresh(stored)
    assert stored.status == "completed"
