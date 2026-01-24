"""
Unit tests for ContextWindowManager.

Tests context window management capabilities:
- Token estimation
- Message splitting by budget
- Context compression with summarization
- Configuration validation
- Overflow detection and compaction integration
"""

import pytest

from src.infrastructure.agent.context.window_manager import (
    CompressionStrategy,
    ContextWindowConfig,
    ContextWindowManager,
    ContextWindowResult,
)
from src.infrastructure.agent.session.compaction import (
    ModelLimits,
    TokenCount,
)


class TestContextWindowConfig:
    """Tests for ContextWindowConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = ContextWindowConfig()
        assert config.max_context_tokens == 128000
        assert config.max_output_tokens == 4096
        assert config.compression_trigger_pct == 0.80
        assert config.summary_max_tokens == 500

    def test_custom_config(self):
        """Test custom configuration values."""
        config = ContextWindowConfig(
            max_context_tokens=32000,
            max_output_tokens=2048,
            compression_trigger_pct=0.70,
        )
        assert config.max_context_tokens == 32000
        assert config.max_output_tokens == 2048
        assert config.compression_trigger_pct == 0.70

    def test_budget_validation(self):
        """Test that budget percentages must sum to 1.0."""
        with pytest.raises(ValueError, match="Budget percentages must sum to 1.0"):
            ContextWindowConfig(
                system_budget_pct=0.50,
                history_budget_pct=0.50,
                recent_budget_pct=0.50,
                output_reserve_pct=0.50,
            )


class TestTokenEstimation:
    """Tests for token estimation."""

    def test_estimate_empty_text(self):
        """Test estimation of empty text."""
        manager = ContextWindowManager()
        assert manager.estimate_tokens("") == 0

    def test_estimate_english_text(self):
        """Test estimation of English text."""
        manager = ContextWindowManager()
        text = "Hello, this is a test message with some content."
        tokens = manager.estimate_tokens(text)
        # Rough estimate: ~4 chars per token for English
        assert 10 <= tokens <= 20

    def test_estimate_chinese_text(self):
        """Test estimation of Chinese text."""
        manager = ContextWindowManager()
        text = "这是一段中文测试文本，用于测试中文字符的令牌估算。"
        tokens = manager.estimate_tokens(text)
        # Chinese: ~2 chars per token
        assert tokens > 0

    def test_estimate_message_tokens(self):
        """Test estimation of message tokens."""
        manager = ContextWindowManager()
        message = {
            "role": "user",
            "content": "Hello, how are you?",
        }
        tokens = manager.estimate_message_tokens(message)
        # Should include content + overhead
        assert tokens > 0

    def test_estimate_message_with_tool_calls(self):
        """Test estimation of message with tool calls."""
        manager = ContextWindowManager()
        message = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_123",
                    "function": {
                        "name": "search_memory",
                        "arguments": '{"query": "test"}',
                    },
                }
            ],
        }
        tokens = manager.estimate_message_tokens(message)
        assert tokens > 0

    def test_token_caching(self):
        """Test that token estimates are cached."""
        manager = ContextWindowManager()
        text = "Test text for caching"

        # First call
        tokens1 = manager.estimate_tokens(text)
        # Second call (should use cache)
        tokens2 = manager.estimate_tokens(text)

        assert tokens1 == tokens2

        # Clear cache and verify still works
        manager.clear_cache()
        tokens3 = manager.estimate_tokens(text)
        assert tokens3 == tokens1


class TestBudgetCalculation:
    """Tests for budget calculation."""

    def test_calculate_budgets_default(self):
        """Test default budget calculation."""
        manager = ContextWindowManager()
        budgets = manager.calculate_budgets()

        assert "system" in budgets
        assert "history" in budgets
        assert "recent" in budgets
        assert "output_reserve" in budgets
        assert "total_available" in budgets

        # Verify budgets are reasonable
        available = 128000 - 4096  # max_context - max_output
        assert budgets["total_available"] == available

    def test_calculate_budgets_custom(self):
        """Test budget calculation with custom config."""
        config = ContextWindowConfig(
            max_context_tokens=50000,
            max_output_tokens=2000,
        )
        manager = ContextWindowManager(config)
        budgets = manager.calculate_budgets()

        available = 50000 - 2000
        assert budgets["total_available"] == available


class TestContextWindowBuilding:
    """Tests for context window building."""

    @pytest.mark.asyncio
    async def test_build_no_compression_needed(self):
        """Test building context when no compression is needed."""
        manager = ContextWindowManager()

        system_prompt = "You are a helpful assistant."
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]

        result = await manager.build_context_window(
            system_prompt=system_prompt,
            messages=messages,
        )

        assert not result.was_compressed
        assert result.compression_strategy == CompressionStrategy.NONE
        assert result.original_message_count == 2
        assert len(result.messages) >= 2  # System + messages

    @pytest.mark.asyncio
    async def test_build_with_compression_truncation(self):
        """Test building context with truncation compression."""
        # Use small context limit to trigger compression
        config = ContextWindowConfig(
            max_context_tokens=500,
            max_output_tokens=100,
            compression_trigger_pct=0.5,
        )
        manager = ContextWindowManager(config)

        system_prompt = "You are a helpful assistant."
        messages = [{"role": "user", "content": f"Message {i} " * 50} for i in range(20)]

        result = await manager.build_context_window(
            system_prompt=system_prompt,
            messages=messages,
            llm_client=None,  # No LLM for summary
        )

        assert result.was_compressed
        # Without LLM client, should fallback to truncation
        assert result.compression_strategy == CompressionStrategy.TRUNCATE
        assert result.original_message_count == 20
        assert result.final_message_count < 20

    @pytest.mark.asyncio
    async def test_context_result_to_event_data(self):
        """Test converting result to event data."""
        result = ContextWindowResult(
            messages=[{"role": "system", "content": "test"}],
            was_compressed=True,
            compression_strategy=CompressionStrategy.SUMMARIZE,
            original_message_count=10,
            final_message_count=5,
            estimated_tokens=1000,
            token_budget=5000,
            budget_utilization_pct=20.0,
            summarized_message_count=5,
        )

        event_data = result.to_event_data()

        assert event_data["was_compressed"] is True
        assert event_data["compression_strategy"] == "summarize"
        assert event_data["original_message_count"] == 10
        assert event_data["final_message_count"] == 5


class TestMessageSplitting:
    """Tests for message splitting logic."""

    def test_split_empty_messages(self):
        """Test splitting empty message list."""
        manager = ContextWindowManager()
        history, recent = manager._split_messages_by_budget(
            messages=[],
            history_budget=1000,
            recent_budget=1000,
        )
        assert history == []
        assert recent == []

    def test_split_few_messages(self):
        """Test splitting when all messages fit in recent budget."""
        manager = ContextWindowManager()
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]

        history, recent = manager._split_messages_by_budget(
            messages=messages,
            history_budget=1000,
            recent_budget=1000,
        )

        # All messages should be in recent
        assert len(history) == 0
        assert len(recent) == 2

    def test_split_many_messages(self):
        """Test splitting when messages exceed recent budget."""
        config = ContextWindowConfig(max_context_tokens=500, max_output_tokens=100)
        manager = ContextWindowManager(config)

        messages = [{"role": "user", "content": f"Message {i} " * 20} for i in range(10)]

        history, recent = manager._split_messages_by_budget(
            messages=messages,
            history_budget=100,
            recent_budget=100,  # Very small budget
        )

        # Should have some in history and some in recent
        assert len(history) + len(recent) == len(messages)


class TestConfigUpdate:
    """Tests for configuration updates."""

    def test_update_context_tokens(self):
        """Test updating max context tokens."""
        manager = ContextWindowManager()
        assert manager.config.max_context_tokens == 128000

        manager.update_config(max_context_tokens=64000)
        assert manager.config.max_context_tokens == 64000

    def test_update_output_tokens(self):
        """Test updating max output tokens."""
        manager = ContextWindowManager()
        assert manager.config.max_output_tokens == 4096

        manager.update_config(max_output_tokens=8192)
        assert manager.config.max_output_tokens == 8192

    def test_update_both(self):
        """Test updating both limits."""
        manager = ContextWindowManager()

        manager.update_config(max_context_tokens=200000, max_output_tokens=16384)

        assert manager.config.max_context_tokens == 200000
        assert manager.config.max_output_tokens == 16384


class TestCompactionIntegration:
    """Tests for compaction module integration."""

    def test_get_token_count(self):
        """Test getting detailed token count."""
        manager = ContextWindowManager()
        messages = [
            {"role": "user", "content": "Hello world " * 100},
            {"role": "assistant", "content": "Hi there! " * 100},
        ]

        count = manager.get_token_count(messages)

        assert isinstance(count, TokenCount)
        assert count.input > 0
        assert count.total() > 0

    def test_get_token_count_with_cache(self):
        """Test token count with cached content."""
        manager = ContextWindowManager()
        messages = [
            {
                "role": "system",
                "content": "System prompt",
                "cache_control": {"type": "ephemeral"},
            },
            {"role": "user", "content": "Hello"},
        ]

        count = manager.get_token_count(messages)

        # Cached messages should be counted in cache_read
        assert count.cache_read > 0
        assert count.input > 0

    def test_is_overflow_true(self):
        """Test overflow detection when over limit."""
        config = ContextWindowConfig(
            max_context_tokens=1000,
            max_output_tokens=100,
        )
        manager = ContextWindowManager(config)

        # Create messages that exceed the limit
        messages = [
            {"role": "user", "content": "x" * 5000},  # Way over limit
        ]

        assert manager.is_overflow(messages) is True

    def test_is_overflow_false(self):
        """Test overflow detection when under limit."""
        config = ContextWindowConfig(
            max_context_tokens=100000,
            max_output_tokens=4096,
        )
        manager = ContextWindowManager(config)

        messages = [
            {"role": "user", "content": "Hello world"},
        ]

        assert manager.is_overflow(messages) is False

    def test_is_overflow_auto_disabled(self):
        """Test overflow detection with auto-compaction disabled."""
        manager = ContextWindowManager()

        messages = [
            {"role": "user", "content": "x" * 50000},
        ]

        # With auto disabled, should never report overflow
        assert manager.is_overflow(messages, auto_compaction_enabled=False) is False

    def test_is_overflow_custom_limits(self):
        """Test overflow with custom model limits."""
        manager = ContextWindowManager()

        limits = ModelLimits(
            context=10000,
            input=2000,  # Lower limit to trigger overflow
            output=1000,
        )

        messages = [
            {"role": "user", "content": "x" * 10000},  # ~2500 tokens, over 2000 input limit
        ]

        assert manager.is_overflow(messages, model_limits=limits) is True

    def test_should_compact_true(self):
        """Test compaction trigger when above threshold."""
        config = ContextWindowConfig(
            max_context_tokens=10000,
            max_output_tokens=1000,
        )
        manager = ContextWindowManager(config)

        # Create messages that use > 80% of context
        # Usable = 9000 (10000 - 1000)
        # 80% threshold = 7200
        messages = [
            {"role": "user", "content": "x" * 30000},  # ~7500 tokens
        ]

        assert manager.should_compact(messages, threshold=0.8) is True

    def test_should_compact_false(self):
        """Test compaction not triggered when below threshold."""
        manager = ContextWindowManager()

        messages = [
            {"role": "user", "content": "Hello"},
        ]

        assert manager.should_compact(messages, threshold=0.8) is False

    def test_should_compact_custom_threshold(self):
        """Test compaction with custom threshold."""
        # Use small context to make thresholds easier to hit
        config = ContextWindowConfig(
            max_context_tokens=10000,
            max_output_tokens=1000,
        )
        manager = ContextWindowManager(config)

        messages = [
            {"role": "user", "content": "x" * 10000},  # ~2500 tokens
        ]

        # usable = 9000, 50% = 4500, so 2500 < 4500 = no compact
        # Wait, let me recalculate...
        # Actually with input=0, usable = 10000 - min(1000, 8192) = 10000 - 1000 = 9000
        # 50% of 9000 = 4500, 2500 < 4500, so should NOT compact
        # But the test expects True at 50%... let me use more content
        messages = [
            {"role": "user", "content": "x" * 20000},  # ~5000 tokens
        ]

        # usable = 9000, 50% = 4500, 5000 > 4500 = should compact
        assert manager.should_compact(messages, threshold=0.5) is True

        # 90% = 8100, 5000 < 8100 = should not compact
        assert manager.should_compact(messages, threshold=0.9) is False

    def test_get_usable_context_default(self):
        """Test getting usable context with default config."""
        manager = ContextWindowManager()

        usable = manager.get_usable_context()

        # Default: 128000 - min(4096, 8192) = 128000 - 4096 = 123904
        assert usable > 0

    def test_get_usable_context_custom(self):
        """Test getting usable context with custom limits."""
        manager = ContextWindowManager()

        limits = ModelLimits(
            context=50000,
            input=45000,
            output=5000,
        )

        usable = manager.get_usable_context(limits)

        assert usable == 45000

    def test_get_usable_context_derived(self):
        """Test usable context when derived from context - output."""
        manager = ContextWindowManager()

        limits = ModelLimits(
            context=50000,
            input=0,  # Derive from context - output
            output=5000,
        )

        usable = manager.get_usable_context(limits)

        # 50000 - min(5000, 8192) = 50000 - 5000 = 45000
        assert usable == 45000
