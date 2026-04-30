"""Tests for processor message normalization helpers."""

import pytest

from src.infrastructure.agent.processor.message_utils import sanitize_tool_call_messages


@pytest.mark.unit
def test_sanitize_tool_call_messages_drops_orphan_tool_result() -> None:
    messages = [
        {"role": "user", "content": "start"},
        {"role": "tool", "tool_call_id": "missing", "content": "orphaned"},
        {"role": "assistant", "content": "continue"},
    ]

    sanitized = sanitize_tool_call_messages(messages)

    assert [message["role"] for message in sanitized] == ["user", "assistant"]
    assert all(message.get("tool_call_id") != "missing" for message in sanitized)


@pytest.mark.unit
def test_sanitize_tool_call_messages_keeps_adjacent_tool_pair() -> None:
    messages = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "read", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": "ok"},
        {"role": "system", "content": "runtime guidance"},
    ]

    sanitized = sanitize_tool_call_messages(messages)

    assert sanitized == messages


@pytest.mark.unit
def test_sanitize_tool_call_messages_drops_non_adjacent_tool_result() -> None:
    messages = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "read", "arguments": "{}"},
                }
            ],
        },
        {"role": "system", "content": "runtime guidance"},
        {"role": "tool", "tool_call_id": "call-1", "content": "late result"},
    ]

    sanitized = sanitize_tool_call_messages(messages)

    assert sanitized == [
        {"role": "assistant", "content": ""},
        {"role": "system", "content": "runtime guidance"},
    ]
