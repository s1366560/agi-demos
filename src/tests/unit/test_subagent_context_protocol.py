"""SubAgent history retains valid model protocol after bounded context transfer."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from src.infrastructure.agent.subagent.context_bridge import ContextBridge

pytestmark = pytest.mark.unit


def actual_assistant():
    return json.loads(
        (
            Path(__file__).parent / "fixtures/subagent_context/assistant_tool_call_null.json"
        ).read_text()
    )


def transfer(history, **kwargs):
    bridge = ContextBridge(**kwargs)
    context = bridge.build_subagent_context("new child task", "child system", history)
    return bridge.build_messages(context)[1:-1]


def test_actual_null_assistant_and_tool_result_survive_transfer_without_mutation():
    assistant = actual_assistant()
    result = {
        "role": "tool",
        "tool_call_id": assistant["tool_calls"][0]["id"],
        "content": "QA child created",
    }
    history = [assistant, result]
    original = deepcopy(history)
    assert transfer(history) == original
    assert history == original


def test_inflight_parent_tool_call_is_not_an_unanswered_child_call():
    assert transfer([{"role": "user", "content": "original task"}, actual_assistant()]) == [
        {"role": "user", "content": "original task"}
    ]


def test_window_and_character_budget_never_emit_orphan_results():
    assistant = actual_assistant()
    result = {"role": "tool", "tool_call_id": assistant["tool_calls"][0]["id"], "content": "done"}
    latest = {"role": "user", "content": "latest"}
    assert transfer([assistant, result, latest], max_context_messages=2) == [latest]
    assert transfer([assistant, result, latest], max_context_chars=30) == [latest]


def test_parallel_tool_calls_require_exact_complete_results():
    assistant = actual_assistant()
    second = deepcopy(assistant["tool_calls"][0])
    second["id"] = "second-call"
    assistant["tool_calls"].append(second)
    first = {"role": "tool", "tool_call_id": assistant["tool_calls"][0]["id"], "content": "first"}
    second_result = {"role": "tool", "tool_call_id": "second-call", "content": "second"}
    assert transfer([assistant, second_result, first]) == [assistant, second_result, first]
    assert transfer([assistant, first]) == []
    assert transfer([assistant, first, first]) == []


def test_multimodal_content_retains_structure_and_opaque_payloads_are_not_sliced():
    parts = [
        {"type": "text", "text": "inspect"},
        {"type": "image_url", "image_url": {"url": "https://example.invalid/qa.png"}},
    ]
    message = {"role": "user", "content": parts}
    transferred = transfer([message])
    assert transferred == [message]
    transferred[0]["content"][1]["image_url"]["url"] = "changed"
    assert message["content"][1]["image_url"]["url"] == "https://example.invalid/qa.png"
    assert transfer([message], max_context_chars=20) == []


def test_plain_nullable_content_and_existing_text_clipping():
    assert transfer([{"role": "assistant", "content": None}]) == [
        {"role": "assistant", "content": ""}
    ]
    assert transfer([{"role": "user", "content": "abcdef"}], max_context_chars=3) == [
        {"role": "user", "content": "abc... [truncated]"}
    ]


def test_legacy_function_exchange_is_kept_whole():
    assistant = {
        "role": "assistant",
        "content": None,
        "function_call": {"name": "qa", "arguments": "{}"},
    }
    result = {"role": "function", "name": "qa", "content": "done"}
    assert transfer([assistant, result]) == [assistant, result]
    assert transfer([result]) == []
    assert transfer([assistant, result], max_context_chars=1) == []


def test_audio_multimodal_and_nullable_tool_results_remain_valid():
    message = {
        "role": "user",
        "content": [{"type": "input_audio", "input_audio": {"data": "UUE=", "format": "wav"}}],
    }
    assert transfer([message]) == [message]
    assistant = actual_assistant()
    result = {"role": "tool", "tool_call_id": assistant["tool_calls"][0]["id"], "content": None}
    assert transfer([assistant, result])[1]["content"] == ""


@pytest.mark.parametrize("content", [123, {"unexpected": "object"}, ["invalid block"]])
def test_malformed_content_is_rejected_without_stringifying_it(content):
    with pytest.raises(ValueError, match="history content"):
        transfer([{"role": "user", "content": content}])
