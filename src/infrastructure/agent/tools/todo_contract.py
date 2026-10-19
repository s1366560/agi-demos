"""Structural task-write schema and correction guidance shared by all entry points."""

from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft202012Validator

from src.infrastructure.agent.tools.result import ToolResult

TODO_UPDATE_INSTRUCTION = (
    "For action=update, call todoread and copy the exact todos[].id into the top-level "
    "todo_id. Send exactly one object in todos, with all patch fields together. "
    "Never split status and id into separate items or use $text. "
    'Example: {"action":"update","todo_id":"<copied task id>",'
    '"todos":[{"status":"cancelled","result_summary":"Stopped by the user"}]}. '
    "Choose the status from the actual task outcome; cancelled is for deliberately "
    "stopped work, failed for genuine failures, and completed for finished work. "
    "For progress-only updates omit content, title, priority, and nested id."
)

TODOWRITE_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "description": "replace (replace entire list), add (append), update (modify one)",
            "enum": ["replace", "add", "update"],
        },
        "todos": {
            "type": "array",
            "description": (
                "For update: exactly one object containing only the patch fields; todo_id "
                "belongs at the top level. For add/replace: task objects with content; "
                "backend generates IDs."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": (
                            "Task description; required for add/replace, omit for status-only updates"
                        ),
                    },
                    "title": {"type": "string", "description": "Short step title"},
                    "description": {
                        "type": "string",
                        "description": "Optional detailed step description",
                    },
                    "estimated_duration_seconds": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "Optional estimated duration in seconds",
                    },
                    "started_at": {"type": "string", "description": "ISO-8601 start time"},
                    "completed_at": {"type": "string", "description": "ISO-8601 completion time"},
                    "result_summary": {
                        "type": "string",
                        "description": "Agent-authored semantic result summary",
                    },
                    "evidence_refs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Structured artifact or evidence references",
                    },
                    "id": {
                        "type": "string",
                        "description": (
                            "Optional stable task id copied from todoread; not a numeric list position."
                        ),
                        "pattern": "^(?!\\d+$).+",
                    },
                    "status": {
                        "type": "string",
                        "description": "pending, in_progress, completed, failed, cancelled",
                        "enum": ["pending", "in_progress", "completed", "failed", "cancelled"],
                    },
                    "priority": {
                        "type": "string",
                        "description": "high, medium, low",
                        "enum": ["high", "medium", "low"],
                    },
                },
                "additionalProperties": False,
            },
        },
        "todo_id": {
            "type": "string",
            "description": (
                "For action=update only: exact id copied from todoread todos[].id or "
                "workspace_task_id. Do not use order_index or list positions like '1' or '2'."
            ),
            "pattern": "^(?!\\d+$).+",
            "allOf": [{"pattern": "\\S"}],
        },
    },
    "required": ["action"],
    "additionalProperties": False,
    "description": (
        'Update one task: {"action":"update","todo_id":"<exact todos[].id from todoread>",'
        '"todos":[{"status":"cancelled"}]}. Put todo_id at the top level and all patch '
        "fields together in exactly one todos item; never split fields across items or use $text."
    ),
    "allOf": [
        {
            "if": {"properties": {"action": {"const": "update"}}, "required": ["action"]},
            "then": {
                "required": ["todo_id", "todos"],
                "properties": {
                    "todos": {
                        "minItems": 1,
                        "maxItems": 1,
                        "items": {
                            "minProperties": 1,
                            "not": {"required": ["id"], "maxProperties": 1},
                        },
                    }
                },
            },
        },
        {
            "if": {"properties": {"action": {"enum": ["add", "replace"]}}, "required": ["action"]},
            "then": {
                "properties": {
                    "todos": {
                        "items": {
                            "required": ["content"],
                            "properties": {"content": {"minLength": 1, "pattern": "\\S"}},
                        }
                    }
                }
            },
        },
    ],
}

_VALIDATOR = Draft202012Validator(TODOWRITE_PARAMETERS)


def validate_todowrite_arguments(arguments: dict[str, Any]) -> ToolResult | None:
    """Reject malformed writes without inferring a task identity or executing a patch."""
    # Optional Python arguments historically accept None as omission. The model
    # schema remains strict JSON; an update still requires both non-null fields.
    normalized = {
        key: value
        for key, value in arguments.items()
        if not (key in {"todos", "todo_id"} and value is None)
    }
    error = next(_VALIDATOR.iter_errors(normalized), None)
    todo_id = normalized.get("todo_id")
    todos = normalized.get("todos")
    conflict = (
        normalized.get("action") == "update"
        and isinstance(todos, list)
        and len(todos) == 1
        and isinstance(todos[0], dict)
        and "id" in todos[0]
        and todos[0]["id"] != todo_id
    )
    if error is None and not conflict:
        return None
    payload: dict[str, Any] = {
        "success": False,
        "code": "invalid_tool_arguments",
        "error": "Invalid todowrite arguments.",
        "retry_instruction": TODO_UPDATE_INSTRUCTION,
    }
    if error is not None:
        payload["argument_path"] = list(error.absolute_path)
        payload["constraint"] = error.validator
        payload["error"] = f"Invalid todowrite arguments: {error.message}"
    if conflict:
        payload["error"] = (
            "Nested todos[0].id must match top-level todo_id; omit it for progress updates."
        )
        payload["argument_path"] = ["todos", 0, "id"]
    if isinstance(todo_id, str) and todo_id.strip().isdigit():
        payload["error_code"] = "TODO_ID_IS_LIST_POSITION"
        payload["retry_instruction"] = (
            "Call todoread and retry with the copied id, not a numeric list position. "
            + TODO_UPDATE_INSTRUCTION
        )
    if normalized.get("action") in {"add", "replace"} and isinstance(todos, list):
        if any(
            isinstance(item, dict)
            and (not isinstance(item.get("content"), str) or not item["content"].strip())
            for item in todos
        ):
            payload["code"] = "TODO_CONTENT_REQUIRED"
            payload["error"] = "Content is required when adding or replacing tasks."
    return ToolResult(output=json.dumps(payload), is_error=True)
