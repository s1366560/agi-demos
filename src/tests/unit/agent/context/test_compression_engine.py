"""Tests for ContextCompressionEngine and AdaptiveStrategySelector."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.infrastructure.agent.context.compaction import ModelLimits
from src.infrastructure.agent.context.compression_engine import (
    AdaptiveStrategySelector,
    AdaptiveThresholds,
    ContextCompressionEngine,
)
from src.infrastructure.agent.context.compression_history import (
    CompressionHistory,
    CompressionRecord,
)
from src.infrastructure.agent.context.compression_state import (
    CompressionLevel,
    CompressionState,
    SummaryChunk,
)


def make_messages(count: int, content_len: int = 100) -> list:
    """Create test messages with predictable token counts."""
    messages = []
    for i in range(count):
        role = "user" if i % 2 == 0 else "assistant"
        content = f"Message {i}: " + "x" * content_len
        messages.append({"role": role, "content": content})
    return messages


def simple_token_estimator(text: str) -> int:
    """Simple 4-chars-per-token estimator for tests."""
    return len(text) // 4 if text else 0


def simple_message_token_estimator(msg: dict) -> int:
    """Simple message token estimator for tests."""
    content = msg.get("content", "")
    return simple_token_estimator(content) + 4  # +4 overhead


# =============================================================================
# AdaptiveStrategySelector Tests
# =============================================================================


@pytest.mark.unit
class TestAdaptiveStrategySelector:
    def test_select_none_below_l1_threshold(self):
        selector = AdaptiveStrategySelector()
        limits = ModelLimits(context=100000, input=0, output=4096)
        # 50% occupancy -> NONE
        level = selector.select(48000, limits)
        assert level == CompressionLevel.NONE

    def test_select_l1_between_thresholds(self):
        selector = AdaptiveStrategySelector()
        limits = ModelLimits(context=100000, input=0, output=4096)
        # 70% occupancy -> L1_PRUNE
        level = selector.select(67000, limits)
        assert level == CompressionLevel.L1_PRUNE

    def test_select_l2_between_thresholds(self):
        selector = AdaptiveStrategySelector()
        limits = ModelLimits(context=100000, input=0, output=4096)
        # 85% occupancy -> L2_SUMMARIZE
        level = selector.select(81500, limits)
        assert level == CompressionLevel.L2_SUMMARIZE

    def test_select_l3_above_threshold(self):
        selector = AdaptiveStrategySelector()
        limits = ModelLimits(context=100000, input=0, output=4096)
        # 95% occupancy -> L3_DEEP_COMPRESS
        level = selector.select(91000, limits)
        assert level == CompressionLevel.L3_DEEP_COMPRESS

    def test_select_none_for_unlimited_context(self):
        selector = AdaptiveStrategySelector()
        limits = ModelLimits(context=0, input=0, output=4096)
        level = selector.select(999999, limits)
        assert level == CompressionLevel.NONE

    def test_custom_thresholds(self):
        thresholds = AdaptiveThresholds(
            l1_trigger_pct=0.50,
            l2_trigger_pct=0.70,
            l3_trigger_pct=0.85,
        )
        selector = AdaptiveStrategySelector(thresholds)
        limits = ModelLimits(context=100000, input=0, output=4096)

        # 55% -> L1 with custom thresholds
        level = selector.select(52700, limits)
        assert level == CompressionLevel.L1_PRUNE

    def test_invalid_thresholds_raise_error(self):
        with pytest.raises(ValueError):
            AdaptiveThresholds(
                l1_trigger_pct=0.90,
                l2_trigger_pct=0.80,  # Out of order
                l3_trigger_pct=0.70,
            ).validate()

    def test_get_occupancy(self):
        selector = AdaptiveStrategySelector()
        limits = ModelLimits(context=100000, input=0, output=4096)
        occupancy = selector.get_occupancy(48000, limits)
        assert 0.49 < occupancy < 0.51

    def test_exact_threshold_boundary(self):
        selector = AdaptiveStrategySelector()
        limits = ModelLimits(context=100000, input=0, output=4096)
        usable = 100000 - 4096  # 95904
        # Just above L1 threshold (60%) to account for integer truncation
        level = selector.select(int(usable * 0.60) + 1, limits)
        assert level == CompressionLevel.L1_PRUNE


# =============================================================================
# CompressionHistory Tests
# =============================================================================


@pytest.mark.unit
class TestCompressionHistory:
    def test_empty_history(self):
        history = CompressionHistory()
        assert history.total_compressions == 0
        assert history.total_tokens_saved == 0
        assert history.last_compression is None
        assert history.average_compression_ratio() == 0.0

    def test_record_compression(self):
        history = CompressionHistory()
        from datetime import datetime, timezone

        record = CompressionRecord(
            timestamp=datetime.now(timezone.utc),
            level="l1_prune",
            tokens_before=10000,
            tokens_after=7000,
            messages_before=20,
            messages_after=20,
            pruned_tool_outputs=5,
            duration_ms=150.0,
        )
        history.record(record)

        assert history.total_compressions == 1
        assert history.total_tokens_saved == 3000
        assert history.last_compression == record
        assert record.tokens_saved == 3000
        assert record.compression_ratio == 0.7
        assert record.savings_pct == 30.0

    def test_max_records_eviction(self):
        history = CompressionHistory(max_records=3)
        from datetime import datetime, timezone

        for i in range(5):
            record = CompressionRecord(
                timestamp=datetime.now(timezone.utc),
                level="l1_prune",
                tokens_before=1000,
                tokens_after=800,
                messages_before=10,
                messages_after=10,
            )
            history.record(record)

        assert len(history.records) == 3
        assert history.total_compressions == 5  # Total count preserved

    def test_summary_output(self):
        history = CompressionHistory()
        from datetime import datetime, timezone

        record = CompressionRecord(
            timestamp=datetime.now(timezone.utc),
            level="l2_summarize",
            tokens_before=10000,
            tokens_after=5000,
            messages_before=30,
            messages_after=10,
            summary_generated=True,
        )
        history.record(record)

        summary = history.to_summary()
        assert summary["total_compressions"] == 1
        assert summary["total_tokens_saved"] == 5000
        assert len(summary["recent_records"]) == 1

    def test_reset(self):
        history = CompressionHistory()
        from datetime import datetime, timezone

        history.record(
            CompressionRecord(
                timestamp=datetime.now(timezone.utc),
                level="l1_prune",
                tokens_before=1000,
                tokens_after=800,
                messages_before=10,
                messages_after=10,
            )
        )
        history.reset()
        assert history.total_compressions == 0


# =============================================================================
# CompressionState Tests
# =============================================================================


@pytest.mark.unit
class TestCompressionState:
    def test_initial_state(self):
        state = CompressionState()
        assert state.current_level == CompressionLevel.NONE
        assert not state.has_cached_summary()
        assert state.get_combined_summary() is None
        assert state.messages_summarized_up_to == 0

    def test_add_summary_chunk(self):
        state = CompressionState()
        chunk = SummaryChunk(
            summary_text="User asked about feature X.",
            message_start_index=0,
            message_end_index=10,
            original_token_count=5000,
            summary_token_count=200,
        )
        state.add_summary_chunk(chunk)

        assert state.has_cached_summary()
        assert state.messages_summarized_up_to == 10
        assert state.get_summary_token_count() == 200
        assert "feature X" in state.get_combined_summary()

    def test_multiple_summary_chunks(self):
        state = CompressionState()
        state.add_summary_chunk(
            SummaryChunk(
                summary_text="Part 1",
                message_start_index=0,
                message_end_index=10,
                original_token_count=5000,
                summary_token_count=100,
            )
        )
        state.add_summary_chunk(
            SummaryChunk(
                summary_text="Part 2",
                message_start_index=10,
                message_end_index=20,
                original_token_count=5000,
                summary_token_count=100,
            )
        )

        combined = state.get_combined_summary()
        assert "Part 1" in combined
        assert "Part 2" in combined
        assert state.get_summary_token_count() == 200

    def test_global_summary_overrides_chunks(self):
        state = CompressionState()
        state.add_summary_chunk(
            SummaryChunk(
                summary_text="Chunk summary",
                message_start_index=0,
                message_end_index=10,
                original_token_count=5000,
                summary_token_count=100,
            )
        )
        state.set_global_summary("Global distilled summary", 50)

        assert state.get_combined_summary() == "Global distilled summary"
        assert state.get_summary_token_count() == 50

    def test_pending_state(self):
        state = CompressionState()
        state.mark_pending(CompressionLevel.L2_SUMMARIZE)
        assert state.pending_compression is True
        assert state.pending_level == CompressionLevel.L2_SUMMARIZE

        state.clear_pending()
        assert state.pending_compression is False
        assert state.pending_level is None

    def test_reset(self):
        state = CompressionState()
        state.current_level = CompressionLevel.L2_SUMMARIZE
        state.set_global_summary("test", 100)
        state.mark_pending(CompressionLevel.L3_DEEP_COMPRESS)

        state.reset()
        assert state.current_level == CompressionLevel.NONE
        assert not state.has_cached_summary()
        assert not state.pending_compression

    def test_to_dict(self):
        state = CompressionState()
        d = state.to_dict()
        assert d["current_level"] == "none"
        assert d["pending_compression"] is False


# =============================================================================
# ContextCompressionEngine Tests
# =============================================================================


@pytest.mark.unit
class TestContextCompressionEngine:
    def _make_engine(self, **kwargs):
        return ContextCompressionEngine(
            estimate_tokens=simple_token_estimator,
            estimate_message_tokens=simple_message_token_estimator,
            **kwargs,
        )

    def test_select_level_none(self):
        engine = self._make_engine()
        messages = make_messages(5, content_len=100)
        limits = ModelLimits(context=128000, input=0, output=4096)
        level = engine.select_level(messages, limits)
        assert level == CompressionLevel.NONE

    async def test_compress_no_action_needed(self):
        engine = self._make_engine()
        messages = make_messages(5, content_len=100)
        limits = ModelLimits(context=128000, input=0, output=4096)

        result = await engine.compress(
            system_prompt="You are helpful.",
            messages=messages,
            model_limits=limits,
        )
        assert result.level == CompressionLevel.NONE
        assert result.tokens_saved == 0
        assert len(result.messages) == len(messages) + 1  # +1 for system

    async def test_compress_l1_prune(self):
        engine = self._make_engine()
        # Create messages with large tool outputs to trigger L1
        messages = []
        for i in range(20):
            messages.append({"role": "user", "content": f"Question {i}"})
            messages.append(
                {"role": "assistant", "content": f"Let me check.", "tool_calls": []}
            )
            messages.append(
                {"role": "tool", "name": "search", "content": "x" * 20000}
            )
            messages.append({"role": "assistant", "content": f"Answer {i}."})

        limits = ModelLimits(context=200000, input=0, output=4096)

        result = await engine.compress(
            system_prompt="You are helpful.",
            messages=messages,
            model_limits=limits,
            level=CompressionLevel.L1_PRUNE,
        )
        assert result.level == CompressionLevel.L1_PRUNE
        assert result.pruned_tool_outputs > 0
        # History should be updated
        assert engine.history.total_compressions == 1

    async def test_compress_l2_with_mock_llm(self):
        engine = self._make_engine(chunk_size=5, summary_max_tokens=200)
        messages = make_messages(30, content_len=200)
        limits = ModelLimits(context=128000, input=0, output=4096)

        # Mock LLM client
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content="Summary of conversation."))
        ]
        mock_llm.chat_completion.return_value = mock_response

        result = await engine.compress(
            system_prompt="You are helpful.",
            messages=messages,
            model_limits=limits,
            llm_client=mock_llm,
            level=CompressionLevel.L2_SUMMARIZE,
        )
        assert result.level == CompressionLevel.L2_SUMMARIZE
        assert result.summary is not None
        assert engine.state.has_cached_summary()
        assert engine.history.total_compressions == 1

    async def test_compress_l3_with_mock_llm(self):
        engine = self._make_engine(summary_max_tokens=200)
        messages = make_messages(20, content_len=200)
        limits = ModelLimits(context=128000, input=0, output=4096)

        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content="Ultra-compact global summary."))
        ]
        mock_llm.chat_completion.return_value = mock_response

        result = await engine.compress(
            system_prompt="You are helpful.",
            messages=messages,
            model_limits=limits,
            llm_client=mock_llm,
            level=CompressionLevel.L3_DEEP_COMPRESS,
        )
        assert result.level == CompressionLevel.L3_DEEP_COMPRESS
        assert result.summary is not None
        assert engine.state.global_summary is not None

    def test_get_token_distribution(self):
        engine = self._make_engine()
        messages = [
            {"role": "user", "content": "Hello there"},
            {"role": "assistant", "content": "How can I help?"},
            {"role": "tool", "name": "search", "content": "Search results"},
        ]
        dist = engine.get_token_distribution(messages, system_prompt="System prompt")
        assert dist["system"] > 0
        assert dist["user"] > 0
        assert dist["assistant"] > 0
        assert dist["tool"] > 0

    def test_reset(self):
        engine = self._make_engine()
        engine.state.current_level = CompressionLevel.L2_SUMMARIZE
        engine.reset()
        assert engine.state.current_level == CompressionLevel.NONE
        assert engine.history.total_compressions == 0

    def test_get_occupancy(self):
        engine = self._make_engine()
        messages = make_messages(5, content_len=100)
        limits = ModelLimits(context=128000, input=0, output=4096)
        occupancy = engine.get_occupancy(messages, limits)
        assert 0.0 <= occupancy < 1.0
