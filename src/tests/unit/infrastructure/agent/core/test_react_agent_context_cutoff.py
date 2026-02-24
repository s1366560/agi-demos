"""Unit tests for OverflowRecoveryCoordinator (context cutoff and overflow recovery)."""

import pytest

from src.infrastructure.agent.context.overflow_recovery import (
    OverflowRecoveryConfig,
    OverflowRecoveryCoordinator,
)
from src.infrastructure.agent.context.window_manager import ContextWindowConfig


@pytest.mark.unit
def test_truncate_messages_truncates_tool_output() -> None:
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "tool", "content": "a" * 1000},
        {"role": "assistant", "content": "short"},
    ]

    truncated, count = OverflowRecoveryCoordinator.truncate_messages(messages)

    assert count == 1
    assert "truncated for overflow recovery" in truncated[1]["content"]
    assert truncated[0]["content"] == "sys"
    assert truncated[2]["content"] == "short"


@pytest.mark.unit
def test_truncate_messages_truncates_assistant_output() -> None:
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "tool", "content": "ok"},
        {"role": "assistant", "content": "b" * 3000},
    ]

    truncated, count = OverflowRecoveryCoordinator.truncate_messages(messages)

    assert count == 1
    assert "truncated for overflow recovery" in truncated[2]["content"]
    assert truncated[1]["content"] == "ok"


@pytest.mark.unit
def test_truncate_messages_truncates_both_roles() -> None:
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "tool", "content": "a" * 1000},
        {"role": "assistant", "content": "b" * 3000},
    ]

    truncated, count = OverflowRecoveryCoordinator.truncate_messages(messages)

    assert count == 2
    assert "truncated for overflow recovery" in truncated[1]["content"]
    assert "truncated for overflow recovery" in truncated[2]["content"]


@pytest.mark.unit
def test_truncate_messages_empty_list() -> None:
    truncated, count = OverflowRecoveryCoordinator.truncate_messages([])

    assert truncated == []
    assert count == 0


@pytest.mark.unit
def test_truncate_messages_preserves_non_string_content() -> None:
    messages = [
        {"role": "assistant", "content": [{"type": "text", "text": "x" * 5000}]},
    ]

    truncated, count = OverflowRecoveryCoordinator.truncate_messages(messages)

    assert count == 0
    assert truncated[0] is messages[0]


@pytest.mark.unit
def test_tail_trim_keeps_system_prefix_and_recent_tail() -> None:
    config = OverflowRecoveryConfig(tail_keep_messages=3)
    coordinator = OverflowRecoveryCoordinator(config)

    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "u3"},
    ]

    trimmed, dropped = coordinator._tail_trim_messages(messages)

    assert dropped == 2
    assert len(trimmed) == 4
    assert trimmed[0]["role"] == "system"
    assert trimmed[1]["content"] == "u2"


@pytest.mark.unit
def test_tail_trim_no_drop_when_within_limit() -> None:
    config = OverflowRecoveryConfig(tail_keep_messages=10)
    coordinator = OverflowRecoveryCoordinator(config)

    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
    ]

    trimmed, dropped = coordinator._tail_trim_messages(messages)

    assert dropped == 0
    assert len(trimmed) == 3


@pytest.mark.unit
def test_build_aggressive_config_reduces_context_and_thresholds() -> None:
    coordinator = OverflowRecoveryCoordinator()
    base_config = ContextWindowConfig(
        max_context_tokens=100000,
        max_output_tokens=4096,
        l1_trigger_pct=0.60,
        l2_trigger_pct=0.80,
        l3_trigger_pct=0.90,
    )

    aggressive = coordinator.build_aggressive_config(base_config)

    assert aggressive.max_context_tokens == 75000
    assert aggressive.l1_trigger_pct <= 0.35
    assert aggressive.l2_trigger_pct <= 0.55
    assert aggressive.l3_trigger_pct <= 0.75
    assert aggressive.l1_trigger_pct < aggressive.l2_trigger_pct < aggressive.l3_trigger_pct
