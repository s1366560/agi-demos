"""One running conversation preserves its task ledger across native user controls."""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.domain.events.agent_events import AgentObserveEvent
from src.infrastructure.adapters.secondary.persistence.models import AgentTaskModel, Conversation
from src.infrastructure.agent.core.message import Message, MessageRole, ToolPart, ToolState
from src.infrastructure.agent.core.tool_converter import convert_tools
from src.infrastructure.agent.processor.processor import (
    ProcessorConfig,
    SessionProcessor,
    ToolDefinition,
)
from src.infrastructure.agent.processor.run_context import RunContext, bind_run_context
from src.infrastructure.agent.tools.hooks import ToolHookRegistry
from src.infrastructure.agent.tools.pipeline import ToolPipeline
from src.infrastructure.agent.tools.result import ToolControlOutcome, ToolResult
from src.infrastructure.agent.tools.todo_tools import make_todo_tools
from src.infrastructure.agent.tools.truncation import OutputTruncator
from src.tests.unit.infrastructure.agent.processor.test_native_control_results import (
    control_result,
)
from src.tests.unit.infrastructure.agent.processor.test_todo_argument_feedback import (
    read_only_guard,
)

pytestmark = pytest.mark.unit


@pytest.fixture
async def task_scope(test_db, test_user, test_project_db):
    conversation = Conversation(
        id=str(uuid.uuid4()),
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        user_id=test_user.id,
        title="Native control and task lifecycle",
    )
    test_db.add(conversation)
    await test_db.flush()
    task_ids = [str(uuid.uuid4()) for _ in range(3)]
    test_db.add_all(
        AgentTaskModel(
            id=task_id,
            conversation_id=conversation.id,
            content=content,
            title=content,
            status=status,
        )
        for task_id, content, status in zip(
            task_ids,
            ["Observe the native target", "Independent authorized work", "Earlier real failure"],
            ["pending", "pending", "failed"],
            strict=True,
        )
    )
    await test_db.commit()
    return conversation, task_ids


@pytest.mark.parametrize("pipeline", [False, True])
async def test_pause_resume_stop_requires_explicit_task_update_and_never_replays(  # noqa: PLR0915
    monkeypatch, test_engine, task_scope, pipeline
):
    conversation, task_ids = task_scope
    sessions = async_sessionmaker(test_engine, expire_on_commit=False)

    async def statuses():
        async with sessions() as db:
            rows = await db.execute(
                select(AgentTaskModel.id, AgentTaskModel.status).where(
                    AgentTaskModel.conversation_id == conversation.id
                )
            )
            return dict(rows.all())

    resumed, waiting = asyncio.Event(), asyncio.Event()

    async def wait_for_resume():
        waiting.set()
        await resumed.wait()
        return None

    paused = control_result(ToolControlOutcome.USER_PAUSED)
    paused.control_wait = wait_for_resume
    native = AsyncMock(
        side_effect=[
            ToolResult(output='{"snapshot_id":"before-pause"}'),
            paused,
            ToolResult(output='{"snapshot_id":"after-resume"}'),
            control_result(ToolControlOutcome.USER_STOPPED),
        ]
    )
    manager, detector = MagicMock(), MagicMock()
    manager.evaluate.return_value.action = "allow"
    detector.should_intervene.return_value = False
    processor = SessionProcessor(
        config=ProcessorConfig(model="never-called", run_id="one-run", approved_run_required=True),
        tools=[
            *convert_tools(make_todo_tools(session_factory=sessions)),
            ToolDefinition(
                name="computer_get_app_state",
                description="Observe the authorized native window",
                parameters={},
                permission="computer_observe",
                execute=native,
                repeatable_observation=True,
            ),
        ],
        tool_pipeline=ToolPipeline(manager, detector, OutputTruncator(), ToolHookRegistry())
        if pipeline
        else None,
    )
    processor._abort_event = asyncio.Event()
    processor._current_message = Message(role=MessageRole.ASSISTANT, parts=[])
    permissions = read_only_guard(monkeypatch)

    async def dispatch(call_id, name, arguments):
        part = ToolPart(call_id=call_id, tool=name, input=arguments, status=ToolState.RUNNING)
        processor._pending_tool_calls[call_id] = part
        processor._current_message.parts.append(part)
        events = [
            event
            async for event in processor._execute_tool(conversation.id, call_id, name, arguments)
        ]
        assert not any(isinstance(event, AgentObserveEvent) and event.error for event in events)
        return part

    progress = {"action": "update", "todo_id": task_ids[0], "todos": [{"status": "in_progress"}]}
    with bind_run_context(RunContext(conversation_id=conversation.id)):
        assert (await dispatch("start-task", "todowrite", progress)).status == ToolState.COMPLETED
        await dispatch("observe-before", "computer_get_app_state", {})
        pending = asyncio.create_task(dispatch("paused-call", "computer_get_app_state", {}))
        try:
            await asyncio.wait_for(waiting.wait(), 1)
            assert not pending.done()
            assert native.await_count == 2
            assert await statuses() == dict(
                zip(task_ids, ["in_progress", "pending", "failed"], strict=True)
            )
            assert not processor._native_control_stopped
            resumed.set()
            assert (await asyncio.wait_for(pending, 1)).status == ToolState.CANCELLED
        finally:
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)

        assert native.await_count == 2
        fresh = await dispatch("fresh-after-resume", "computer_get_app_state", {})
        assert fresh.status == ToolState.COMPLETED
        assert json.loads(fresh.output)["snapshot_id"] == "after-resume"
        assert native.await_count == 3
        assert (await statuses())[task_ids[0]] == "in_progress"
        assert not processor._native_control_stopped
        stopped = await dispatch("stopped-call", "computer_get_app_state", {})
        assert stopped.status == ToolState.CANCELLED
        assert native.await_count == 4
        assert processor._native_control_stopped
        assert not processor._abort_event.is_set()
        # The control signal never guesses which task should be cancelled.
        assert await statuses() == dict(
            zip(task_ids, ["in_progress", "pending", "failed"], strict=True)
        )
        cancelled = await dispatch(
            "cancel-native-task",
            "todowrite",
            {"action": "update", "todo_id": task_ids[0], "todos": [{"status": "cancelled"}]},
        )
        assert cancelled.status == ToolState.COMPLETED
        assert await statuses() == dict(
            zip(task_ids, ["cancelled", "pending", "failed"], strict=True)
        )
        assert native.await_count == 4
        assert processor.config.run_id == "one-run"
        assert set(permissions) == {"conversation_progress", "computer_observe"}
