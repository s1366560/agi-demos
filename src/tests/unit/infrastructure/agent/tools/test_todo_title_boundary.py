"""Task titles obey storage limits while exact task content remains intact."""

from unittest.mock import AsyncMock

import pytest
from jsonschema import Draft202012Validator

from src.domain.model.agent.task import AgentTask
from src.infrastructure.agent.core.message import ToolPart, ToolState
from src.infrastructure.agent.core.tool_converter import convert_tools
from src.infrastructure.agent.processor.processor import ProcessorConfig, SessionProcessor
from src.infrastructure.agent.tools.todo_tools import make_todo_tools, todowrite_tool

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("content", ["x" * 501, "中" * 501, "𠀀" * 501, "exact cell\n" * 100])
def test_implicit_title_is_only_a_bounded_display_projection(content):
    for task in (
        AgentTask(conversation_id="current", content=content),
        AgentTask.from_dict({"conversation_id": "current", "content": content}),
    ):
        assert task.title == content[:500]
        assert len(task.title) == 500
        assert task.content == content
        assert task.to_dict()["content"] == content


def test_explicit_title_is_preserved_at_limit_and_rejected_over_limit():
    content = "full content\n" * 100
    title = "𠀀" * 500
    assert AgentTask(conversation_id="current", content=content, title=title).title == title
    with pytest.raises(ValueError, match="title"):
        AgentTask(conversation_id="current", content=content, title=title + "中")


@pytest.mark.parametrize("action", ["add", "replace", "update"])
async def test_explicit_oversized_title_is_rejected_before_approval_or_storage(action):
    arguments = {"action": action, "todos": [{"content": "exact content", "title": "中" * 501}]}
    if action == "update":
        arguments["todo_id"] = "current-task"
    assert not Draft202012Validator(todowrite_tool.parameters).is_valid(arguments)
    storage = AsyncMock(side_effect=AssertionError("must not access storage"))
    tools = make_todo_tools(session_factory=storage)
    processor = SessionProcessor(
        config=ProcessorConfig(model="never-called"), tools=convert_tools(tools)
    )
    coordinator = AsyncMock()
    processor._get_hitl_coordinator = lambda: coordinator
    processor._pending_tool_calls["call"] = ToolPart(
        call_id="call",
        tool="todowrite",
        input=arguments,
        status=ToolState.RUNNING,
    )
    events = [
        event async for event in processor._execute_tool("current", "call", "todowrite", arguments)
    ]
    assert events
    assert processor._pending_tool_calls["call"].status == ToolState.ERROR
    coordinator.prepare_request.assert_not_called()
    storage.assert_not_called()
    assert "too long" in (processor._pending_tool_calls["call"].error or "")
