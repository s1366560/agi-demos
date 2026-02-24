"""Tests for overflow recovery coordinator."""

from types import SimpleNamespace

import pytest

from src.infrastructure.agent.context.overflow_recovery import OverflowRecoveryCoordinator
from src.infrastructure.agent.context.window_manager import (
    ContextWindowConfig,
    ContextWindowManager,
)


def _estimate_messages_tokens(messages: list[dict]) -> int:
    total = 0
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str):
            total += len(content) // 4 + 4
    return total


@pytest.mark.unit
def test_truncate_messages_for_overflow_recovery() -> None:
    messages = [
        {"role": "tool", "content": "x" * 800},
        {"role": "assistant", "content": "y" * 2200},
        {"role": "user", "content": "ok"},
    ]

    truncated, count = OverflowRecoveryCoordinator.truncate_messages(messages)
    assert count == 2
    assert "overflow recovery" in truncated[0]["content"]
    assert "overflow recovery" in truncated[1]["content"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_recover_runs_staged_pipeline() -> None:
    coordinator = OverflowRecoveryCoordinator()
    base_manager = ContextWindowManager(
        ContextWindowConfig(max_context_tokens=10000, max_output_tokens=512)
    )
    current_messages = [
        {"role": "system", "content": "system"},
        {"role": "tool", "content": "x" * 3000},
        {"role": "assistant", "content": "y" * 4000},
        {"role": "user", "content": "latest"},
    ]

    async def _build_context(request, manager):
        # Simulate force-compaction stage producing a compressed context.
        return SimpleNamespace(
            messages=[
                {"role": "system", "content": "system"},
                {"role": "assistant", "content": "short"},
            ],
            was_compressed=True,
            metadata={"compression_level": "l2_summarize"},
        )

    result = await coordinator.recover(
        context_request=SimpleNamespace(),
        current_messages=current_messages,
        base_manager=base_manager,
        build_context=_build_context,
        estimate_messages_tokens=_estimate_messages_tokens,
    )

    assert result.metadata["forced_compaction"] is True
    assert "stages" in result.metadata
    assert result.metadata["stages"][0]["stage"] == "force_compaction"
    assert result.metadata["tokens_after"] <= result.metadata["tokens_before"]
