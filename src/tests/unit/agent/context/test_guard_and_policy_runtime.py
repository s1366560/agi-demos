"""Tests for guard chain and context runtime policy registry."""

import pytest

from src.infrastructure.agent.context.guard_chain import ContextGuardChain
from src.infrastructure.agent.context.guards import HistoryTurnGuard, ToolResultGuard
from src.infrastructure.agent.context.runtime_registry import ContextRuntimeRegistry


def _estimate_message_tokens(message: dict) -> int:
    content = message.get("content", "")
    if isinstance(content, str):
        return len(content) // 4 + 4
    return 4


@pytest.mark.unit
def test_guard_chain_applies_history_and_tool_guards() -> None:
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "tool", "name": "search", "content": "x" * 400},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
        {"role": "tool", "name": "search", "content": "y" * 500},
        {"role": "user", "content": "u3"},
    ]
    chain = ContextGuardChain(
        guards=[
            HistoryTurnGuard(max_messages=4),
            ToolResultGuard(max_tool_chars=80, max_tool_output_ratio=0.2),
        ]
    )

    result = chain.apply(messages, estimate_message_tokens=_estimate_message_tokens)

    assert len(result.messages) <= 5  # system + 4 history
    assert "history_turn_guard" in result.metadata["applied_guards"]
    assert "tool_result_guard" in result.metadata["applied_guards"]
    tool_contents = [m.get("content", "") for m in result.messages if m.get("role") == "tool"]
    assert all(len(content) <= 120 for content in tool_contents)


@pytest.mark.unit
def test_runtime_registry_enriches_summary_with_failures_and_file_activity() -> None:
    registry = ContextRuntimeRegistry.with_defaults()
    source_messages = [
        {
            "role": "system",
            "content": "[Previous conversation summary]\nold",
        },
        {
            "role": "system",
            "content": "[Previous conversation summary]\nnew",
        },
        {
            "role": "tool",
            "name": "read",
            "content": "Exception: failed to read /workspace/src/main.py due to timeout",
        },
    ]

    pre_messages, pre_meta = registry.apply_pre_compression(source_messages)
    assert len(pre_messages) == 2
    assert "dedupe_cached_summary_messages" in pre_meta["applied"]

    summary, summary_meta = registry.apply_summary_enrichment("Base summary", source_messages)
    assert "Tool failure highlights" in summary
    assert "File activity" in summary
    assert "enrich_summary_with_tool_failures" in summary_meta["applied"]
    assert "enrich_summary_with_file_activity" in summary_meta["applied"]
