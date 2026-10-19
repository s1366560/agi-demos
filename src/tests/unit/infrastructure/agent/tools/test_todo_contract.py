"""Task update arguments stay explicit, correctable, and permission confined."""

import json

import pytest
from jsonschema import Draft202012Validator

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.permission_metadata_v2 import resolve_tool_permission_v2
from src.infrastructure.agent.tools.todo_tools import make_todo_tools, todowrite_tool

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "arguments",
    [
        {"action": "update", "todos": [{"status": "cancelled"}, {"id": "task-a"}]},
        {"action": "update", "todos": [{"status": "cancelled"}, {"$text": "task-a"}]},
        {
            "action": "update",
            "todo_id": "task-a",
            "todos": [{"status": "cancelled"}, {"id": "task-a"}],
        },
        {"action": "update", "todo_id": "task-a", "todos": [{"$text": "cancelled"}]},
        {
            "action": "update",
            "todo_id": "task-a",
            "todos": [{"status": "cancelled", "conversation_id": "other"}],
        },
        {
            "action": "update",
            "todo_id": "task-a",
            "todos": [{"status": "cancelled"}],
            "session_id": "other",
        },
        {"action": "update", "todo_id": "task-a", "todos": []},
        {"action": "update", "todo_id": "task-a", "todos": [{}]},
        {"action": "update", "todo_id": "task-a", "todos": [{"id": "task-a"}]},
        {"action": "update", "todo_id": "task-a"},
        {"action": "update", "todo_id": " ", "todos": [{"status": "cancelled"}]},
        {"action": "update", "todo_id": "task-a", "todos": [{"status": "stopped"}]},
        {"action": "update", "todo_id": "task-a", "todos": [{"evidence_refs": "evidence"}]},
    ],
)
async def test_invalid_update_is_rejected_by_schema_and_direct_tool_before_storage(arguments):
    assert not Draft202012Validator(todowrite_tool.parameters).is_valid(arguments)
    assert resolve_tool_permission_v2(todowrite_tool, arguments) == "workspace_task_write"

    def unexpected_storage():
        raise AssertionError("Invalid arguments must not reach task storage")

    tool = make_todo_tools(session_factory=unexpected_storage)["todowrite"]
    result = await tool.execute(
        ToolContext(
            session_id="current",
            conversation_id="current",
            message_id="message",
            call_id="call",
            agent_name="test",
        ),
        **arguments,
    )
    assert result.is_error
    payload = json.loads(result.output)
    assert payload["code"] == "invalid_tool_arguments"
    assert "todo_id" in payload["retry_instruction"]
    assert "exactly one" in payload["retry_instruction"]
    assert "cancelled" in payload["retry_instruction"]
    assert not payload["success"]


@pytest.mark.parametrize("status", ["pending", "in_progress", "completed", "failed", "cancelled"])
def test_valid_single_progress_patch_preserves_conversation_progress_permission(status):
    arguments = {"action": "update", "todo_id": "task-a", "todos": [{"status": status}]}
    Draft202012Validator(todowrite_tool.parameters).validate(arguments)
    assert resolve_tool_permission_v2(todowrite_tool, arguments) == "conversation_progress"


@pytest.mark.parametrize(
    "arguments",
    [
        {"action": "add", "todos": [{"content": "New task"}]},
        {"action": "replace", "todos": []},
        {"action": "replace"},
        {"action": "update", "todo_id": "task-a", "todos": [{"content": "Revised task"}]},
        {
            "action": "update",
            "todo_id": "task-a",
            "todos": [{"id": "task-a", "status": "completed"}],
        },
    ],
)
def test_existing_structural_shapes_remain_valid_without_permission_promotion(arguments):
    Draft202012Validator(todowrite_tool.parameters).validate(arguments)
    assert resolve_tool_permission_v2(todowrite_tool, arguments) == "workspace_task_write"


async def test_conflicting_nested_id_cannot_silently_update_a_different_task():
    def unexpected_storage():
        raise AssertionError("Conflicting identities must fail before storage")

    tool = make_todo_tools(session_factory=unexpected_storage)["todowrite"]
    result = await tool.execute(
        ToolContext(
            session_id="current",
            conversation_id="current",
            message_id="message",
            call_id="call",
            agent_name="test",
        ),
        action="update",
        todo_id="task-a",
        todos=[{"id": "task-b", "status": "cancelled"}],
    )
    assert result.is_error
    assert json.loads(result.output)["code"] == "invalid_tool_arguments"
