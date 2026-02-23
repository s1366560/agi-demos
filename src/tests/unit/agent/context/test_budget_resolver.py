"""Tests for context budget resolver."""

import pytest

from src.infrastructure.agent.context.budget_resolver import ContextBudgetResolver


@pytest.mark.unit
class TestContextBudgetResolver:
    def test_resolve_uses_model_registry_limits(self) -> None:
        resolver = ContextBudgetResolver()
        profile = resolver.resolve(
            model="qwen-max",
            requested_output_tokens=20000,
        )

        # qwen-max output is clamped to 8192 from model registry.
        assert profile.context_window_tokens == 32768
        assert profile.output_tokens == 8192
        assert profile.input_budget_tokens == 24576
        assert profile.source == "model_registry"

    def test_resolve_applies_context_cap(self) -> None:
        resolver = ContextBudgetResolver()
        profile = resolver.resolve(
            model="qwen-plus",
            requested_output_tokens=4096,
            requested_context_tokens=64000,
        )

        assert profile.context_window_tokens == 64000
        assert profile.source == "configured_cap"

    def test_warn_and_block_thresholds(self) -> None:
        resolver = ContextBudgetResolver(warn_below_tokens=40000, hard_min_tokens=20000)
        profile = resolver.resolve(
            model="gpt-4",  # 8192
            requested_output_tokens=1024,
        )
        assert profile.should_warn is True
        assert profile.should_block is True

