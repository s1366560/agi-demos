"""Structural, bounded model history projection with atomic tool exchanges."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any


def condense_model_messages(
    recent: Sequence[Mapping[str, Any]], max_chars: int
) -> list[dict[str, Any]]:
    """Keep complete exchanges and multimodal payloads atomic; clip plain text only.

    An in-flight parent tool call is history, never a pending call for the child.
    Window-trimmed or incomplete exchanges are omitted together rather than passing
    orphan tool responses to a new model request. No tool is executed here.
    """
    condensed: list[dict[str, Any]] = []
    remaining = max_chars
    index = 0
    while index < len(recent) and remaining > 0:
        message = deepcopy(dict(recent[index]))
        index += 1
        role = message.get("role", "user")
        if role == "assistant" and message.get("tool_calls"):
            group, index = _tool_exchange(message, recent, index)
        elif role == "assistant" and message.get("function_call"):
            group, index = _function_exchange(message, recent, index)
        elif role in {"tool", "function"}:
            continue
        else:
            normalized, cost = _content_message(message, remaining)
            if normalized is not None:
                condensed.append(normalized)
                remaining -= cost
            continue
        if group is not None:
            cost = _json_length(group)
            if cost <= remaining:
                condensed.extend(group)
                remaining -= cost
    return condensed


def _content_message(
    message: Mapping[str, Any], remaining: int
) -> tuple[dict[str, Any] | None, int]:
    role = message.get("role", "user")
    if role not in {"system", "developer", "user", "assistant"}:
        raise ValueError("Invalid model history role")
    content = message.get("content")
    if isinstance(content, list):
        if not all(
            isinstance(part, dict) and isinstance(part.get("type"), str) for part in content
        ):
            raise ValueError("Invalid multimodal history content")
        normalized = {"role": role, "content": content}
        cost = _json_length(normalized)
        return (normalized, cost) if cost <= remaining else (None, 0)
    if content is None:
        content = ""
    if not isinstance(content, str):
        raise ValueError("Invalid model history content")
    if len(content) > remaining:
        content = content[:remaining] + "... [truncated]"
    return {"role": role, "content": content}, len(content)


def _function_exchange(
    assistant: dict[str, Any], recent: Sequence[Mapping[str, Any]], index: int
) -> tuple[list[dict[str, Any]] | None, int]:
    call = assistant["function_call"]
    if index >= len(recent) or not isinstance(call, dict):
        return None, index
    result = recent[index]
    if result.get("role") != "function" or result.get("name") != call.get("name"):
        return None, index
    normalized_result = deepcopy(dict(result))
    if normalized_result.get("content") is None:
        normalized_result["content"] = ""
    return [assistant, normalized_result], index + 1


def _tool_exchange(
    assistant: dict[str, Any], recent: Sequence[Mapping[str, Any]], index: int
) -> tuple[list[dict[str, Any]] | None, int]:
    calls = assistant["tool_calls"]
    if not isinstance(calls, list) or not all(
        isinstance(call, dict)
        and isinstance(call.get("id"), str)
        and bool(call["id"])
        and call.get("type") == "function"
        and isinstance(call.get("function"), dict)
        and isinstance(call["function"].get("name"), str)
        and isinstance(call["function"].get("arguments"), str)
        for call in calls
    ):
        raise ValueError("Invalid model history tool calls")
    expected = {call["id"] for call in calls}
    group = [assistant]
    supplied = []
    while index < len(recent) and recent[index].get("role") == "tool":
        result = deepcopy(dict(recent[index]))
        if result.get("content") is None:
            result["content"] = ""
        supplied.append(result.get("tool_call_id"))
        group.append(result)
        index += 1
    if (
        len(expected) != len(calls)
        or len(supplied) != len(expected)
        or not all(isinstance(call_id, str) for call_id in supplied)
        or set(supplied) != expected
    ):
        return None, index
    return group, index


def _json_length(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
