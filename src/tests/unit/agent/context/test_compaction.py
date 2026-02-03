"""
Unit tests for compaction module.

Tests cover:
- TokenCount operations
- ModelLimits defaults
- is_overflow() detection
- prune_tool_outputs() pruning logic
- estimate_tokens() estimation
- calculate_usable_context() calculation
- should_compact() threshold detection
- CompactionResult operations
"""

from datetime import datetime

from src.infrastructure.agent.context.compaction import (
    OUTPUT_TOKEN_MAX,
    PRUNE_MINIMUM_TOKENS,
    PRUNE_PROTECT_TOKENS,
    PRUNE_PROTECTED_TOOLS,
    CompactionResult,
    Message,
    MessageInfo,
    MessagePart,
    ModelLimits,
    PruneResult,
    TokenCount,
    ToolPart,
    calculate_usable_context,
    estimate_tokens,
    is_overflow,
    prune_tool_outputs,
    should_compact,
)


class TestTokenCount:
    """Tests for TokenCount dataclass."""

    def test_default_values(self):
        """Test default values are all zero."""
        tc = TokenCount()
        assert tc.input == 0
        assert tc.output == 0
        assert tc.cache_read == 0
        assert tc.cache_write == 0
        assert tc.reasoning == 0

    def test_custom_values(self):
        """Test custom values."""
        tc = TokenCount(input=100, output=50, reasoning=20)
        assert tc.input == 100
        assert tc.output == 50
        assert tc.reasoning == 20

    def test_total_empty(self):
        """Test total for empty token count."""
        tc = TokenCount()
        assert tc.total() == 0

    def test_total_with_values(self):
        """Test total calculation."""
        tc = TokenCount(input=100, output=50, cache_read=25, cache_write=10, reasoning=15)
        assert tc.total() == 200

    def test_total_partial_values(self):
        """Test total with only some values set."""
        tc = TokenCount(input=100, output=50)
        assert tc.total() == 150


class TestModelLimits:
    """Tests for ModelLimits dataclass."""

    def test_default_values(self):
        """Test default values."""
        ml = ModelLimits()
        assert ml.context == 128_000
        assert ml.input == 124_000
        assert ml.output == 4_096

    def test_custom_values(self):
        """Test custom values."""
        ml = ModelLimits(context=200_000, input=196_000, output=8_192)
        assert ml.context == 200_000
        assert ml.input == 196_000
        assert ml.output == 8_192

    def test_zero_context_unlimited(self):
        """Test zero context represents unlimited."""
        ml = ModelLimits(context=0, input=0, output=0)
        assert ml.context == 0


class TestToolPart:
    """Tests for ToolPart dataclass."""

    def test_default_values(self):
        """Test default values."""
        tp = ToolPart(id="1", tool="grep", status="completed", output="result")
        assert tp.id == "1"
        assert tp.tool == "grep"
        assert tp.status == "completed"
        assert tp.output == "result"
        assert tp.tokens is None
        assert tp.compacted is False
        assert tp.compacted_at is None

    def test_with_tokens(self):
        """Test with token count."""
        tp = ToolPart(id="1", tool="grep", status="completed", output="x", tokens=100)
        assert tp.tokens == 100

    def test_compacted_state(self):
        """Test compacted state."""
        now = datetime.now()
        tp = ToolPart(
            id="1", tool="grep", status="completed", output="compacted",
            compacted=True, compacted_at=now
        )
        assert tp.compacted is True
        assert tp.compacted_at == now


class TestMessage:
    """Tests for Message dataclass."""

    def test_get_tool_parts_empty(self):
        """Test get_tool_parts with no tool parts."""
        msg = Message(info=MessageInfo(id="1", role="user"))
        assert msg.get_tool_parts() == []

    def test_get_tool_parts_with_tools(self):
        """Test get_tool_parts with tool parts."""
        tool1 = ToolPart(id="t1", tool="grep", status="completed", output="out1")
        tool2 = ToolPart(id="t2", tool="view", status="completed", output="out2")
        parts = [
            MessagePart(id="p1", type="tool", tool_part=tool1),
            MessagePart(id="p2", type="text", content="hello"),
            MessagePart(id="p3", type="tool", tool_part=tool2),
        ]
        msg = Message(info=MessageInfo(id="1", role="assistant"), parts=parts)
        
        tool_parts = msg.get_tool_parts()
        assert len(tool_parts) == 2
        assert tool_parts[0].id == "t1"
        assert tool_parts[1].id == "t2"

    def test_get_tool_parts_skips_none(self):
        """Test get_tool_parts skips None tool_parts."""
        parts = [
            MessagePart(id="p1", type="tool", tool_part=None),
        ]
        msg = Message(info=MessageInfo(id="1", role="assistant"), parts=parts)
        assert msg.get_tool_parts() == []


class TestIsOverflow:
    """Tests for is_overflow function."""

    def test_no_overflow(self):
        """Test when tokens are below limit."""
        tokens = TokenCount(input=50_000)
        limits = ModelLimits(context=128_000, input=124_000, output=4_096)
        assert is_overflow(tokens, limits) is False

    def test_overflow_at_threshold(self):
        """Test overflow when at threshold."""
        tokens = TokenCount(input=124_000)
        limits = ModelLimits(context=128_000, input=124_000, output=4_096)
        assert is_overflow(tokens, limits) is True

    def test_overflow_above_threshold(self):
        """Test overflow when above threshold."""
        tokens = TokenCount(input=130_000)
        limits = ModelLimits(context=128_000, input=124_000, output=4_096)
        assert is_overflow(tokens, limits) is True

    def test_auto_compaction_disabled(self):
        """Test no overflow when auto_compaction is disabled."""
        tokens = TokenCount(input=200_000)  # Way over limit
        limits = ModelLimits(context=128_000, input=124_000, output=4_096)
        assert is_overflow(tokens, limits, auto_compaction_enabled=False) is False

    def test_unlimited_context(self):
        """Test no overflow with unlimited context."""
        tokens = TokenCount(input=1_000_000)
        limits = ModelLimits(context=0)  # Unlimited
        assert is_overflow(tokens, limits) is False

    def test_uses_input_limit_if_specified(self):
        """Test uses explicit input limit."""
        tokens = TokenCount(input=100_000)
        limits = ModelLimits(context=128_000, input=100_000, output=4_096)
        assert is_overflow(tokens, limits) is True

    def test_calculates_from_context_minus_output(self):
        """Test calculates usable from context - output when no input limit."""
        tokens = TokenCount(input=120_000)
        limits = ModelLimits(context=128_000, input=0, output=4_096)
        # usable = 128_000 - min(4_096, 8_192) = 123_904
        # 120_000 < 123_904, so no overflow
        assert is_overflow(tokens, limits) is False

        tokens2 = TokenCount(input=124_000)
        assert is_overflow(tokens2, limits) is True


class TestPruneToolOutputs:
    """Tests for prune_tool_outputs function."""

    def test_empty_messages(self):
        """Test pruning empty message list."""
        result = prune_tool_outputs([])
        assert result.pruned_count == 0
        assert result.was_pruned is False

    def test_disabled_pruning(self):
        """Test pruning when disabled."""
        messages = [_create_message_with_tool("msg1", "user", "grep", 50_000)]
        result = prune_tool_outputs(messages, enabled=False)
        assert result.pruned_count == 0
        assert result.was_pruned is False

    def test_below_minimum_threshold(self):
        """Test no pruning when below minimum threshold."""
        # Create messages with tools that have less than PRUNE_MINIMUM_TOKENS
        messages = [
            _create_message_with_tool("m1", "user", "grep", 5_000),
            _create_message_with_tool("m2", "assistant", "grep", 5_000),
            _create_message_with_tool("m3", "user", "grep", 5_000),
            _create_message_with_tool("m4", "assistant", "grep", 5_000),
        ]
        result = prune_tool_outputs(messages)
        assert result.was_pruned is False

    def test_protects_recent_turns(self):
        """Test that recent 2 turns are protected."""
        messages = [
            _create_message_with_tool("m1", "user", "grep", 50_000),
            _create_message_with_tool("m2", "assistant", "grep", 50_000),
            _create_message_with_tool("m3", "user", "grep", 50_000),  # Turn 1 (recent)
            _create_message_with_tool("m4", "assistant", "grep", 50_000),
        ]
        result = prune_tool_outputs(messages)
        # The last 2 turns should be protected
        assert messages[3].get_tool_parts()[0].compacted is False  # Most recent
        assert messages[2].get_tool_parts()[0].compacted is False  # Turn 1

    def test_protects_protected_tools(self):
        """Test protected tools are not pruned."""
        # Create a message with a protected tool
        messages = [
            _create_message_with_tool("m1", "user", "grep", 30_000),
            _create_message_with_tool("m2", "assistant", "skill", 30_000),  # Protected
            _create_message_with_tool("m3", "user", "grep", 30_000),
            _create_message_with_tool("m4", "assistant", "view", 30_000),
            _create_message_with_tool("m5", "user", "grep", 30_000),
            _create_message_with_tool("m6", "assistant", "grep", 30_000),
        ]
        result = prune_tool_outputs(messages)
        # skill tool should be protected
        assert result.protected_count >= 1

    def test_prune_result_counts(self):
        """Test PruneResult fields are populated."""
        # Create enough messages with large token counts to trigger pruning
        messages = []
        for i in range(10):
            role = "user" if i % 2 == 0 else "assistant"
            messages.append(_create_message_with_tool(f"m{i}", role, "grep", 15_000))
        
        result = prune_tool_outputs(messages)
        # Should have some pruning statistics
        assert isinstance(result.pruned_count, int)
        assert isinstance(result.pruned_tokens, int)
        assert isinstance(result.protected_count, int)


class TestEstimateTokens:
    """Tests for estimate_tokens function."""

    def test_empty_string(self):
        """Test empty string returns 0."""
        assert estimate_tokens("") == 0

    def test_simple_text(self):
        """Test simple text estimation."""
        text = "Hello world"  # 11 chars
        tokens = estimate_tokens(text)
        assert tokens == 2  # 11 / 4.0 = 2.75 -> 2

    def test_longer_text(self):
        """Test longer text estimation."""
        text = "a" * 100
        tokens = estimate_tokens(text)
        assert tokens == 25  # 100 / 4.0

    def test_custom_chars_per_token(self):
        """Test custom chars_per_token."""
        text = "a" * 100
        tokens = estimate_tokens(text, chars_per_token=2.0)
        assert tokens == 50  # 100 / 2.0


class TestCalculateUsableContext:
    """Tests for calculate_usable_context function."""

    def test_uses_explicit_input(self):
        """Test uses explicit input limit."""
        limits = ModelLimits(context=128_000, input=100_000, output=4_096)
        usable = calculate_usable_context(limits)
        assert usable == 100_000

    def test_calculates_from_context(self):
        """Test calculates from context - output."""
        limits = ModelLimits(context=128_000, input=0, output=4_096)
        usable = calculate_usable_context(limits)
        # output_budget = min(4_096, 8_192) = 4_096
        # usable = 128_000 - 4_096 = 123_904
        assert usable == 123_904

    def test_unlimited_context(self):
        """Test unlimited context returns 0."""
        limits = ModelLimits(context=0)
        usable = calculate_usable_context(limits)
        assert usable == 0

    def test_output_capped_at_max(self):
        """Test output is capped at OUTPUT_TOKEN_MAX."""
        limits = ModelLimits(context=200_000, input=0, output=20_000)
        usable = calculate_usable_context(limits)
        # output_budget = min(20_000, 8_192) = 8_192
        # usable = 200_000 - 8_192 = 191_808
        assert usable == 191_808


class TestShouldCompact:
    """Tests for should_compact function."""

    def test_below_threshold(self):
        """Test no compaction below threshold."""
        tokens = TokenCount(input=50_000)
        limits = ModelLimits(context=128_000, input=124_000)
        assert should_compact(tokens, limits) is False

    def test_at_default_threshold(self):
        """Test compaction at 80% threshold."""
        limits = ModelLimits(context=128_000, input=124_000)
        # 80% of 124_000 = 99_200
        tokens = TokenCount(input=99_200)
        assert should_compact(tokens, limits) is True

    def test_above_threshold(self):
        """Test compaction above threshold."""
        tokens = TokenCount(input=100_000)
        limits = ModelLimits(context=128_000, input=124_000)
        assert should_compact(tokens, limits) is True

    def test_custom_threshold(self):
        """Test custom threshold."""
        tokens = TokenCount(input=60_000)
        limits = ModelLimits(context=128_000, input=124_000)
        # 50% of 124_000 = 62_000
        assert should_compact(tokens, limits, threshold=0.5) is False
        
        tokens2 = TokenCount(input=65_000)
        assert should_compact(tokens2, limits, threshold=0.5) is True

    def test_unlimited_context(self):
        """Test no compaction with unlimited context."""
        tokens = TokenCount(input=1_000_000)
        limits = ModelLimits(context=0)
        assert should_compact(tokens, limits) is False


class TestCompactionResult:
    """Tests for CompactionResult class."""

    def test_default_values(self):
        """Test default values."""
        result = CompactionResult()
        assert result.was_compacted is False
        assert result.original_token_count == 0
        assert result.final_token_count == 0
        assert result.pruned_tool_outputs == 0
        assert result.summary is None
        assert result.tokens_saved == 0

    def test_custom_values(self):
        """Test custom values."""
        result = CompactionResult(
            was_compacted=True,
            original_token_count=100_000,
            final_token_count=50_000,
            pruned_tool_outputs=5,
            summary="Conversation summary...",
        )
        assert result.was_compacted is True
        assert result.original_token_count == 100_000
        assert result.final_token_count == 50_000
        assert result.pruned_tool_outputs == 5
        assert result.summary == "Conversation summary..."
        assert result.tokens_saved == 50_000

    def test_to_dict(self):
        """Test to_dict serialization."""
        result = CompactionResult(
            was_compacted=True,
            original_token_count=100_000,
            final_token_count=60_000,
            pruned_tool_outputs=3,
            summary="Summary",
        )
        d = result.to_dict()
        assert d["was_compacted"] is True
        assert d["original_token_count"] == 100_000
        assert d["final_token_count"] == 60_000
        assert d["tokens_saved"] == 40_000
        assert d["pruned_tool_outputs"] == 3
        assert d["summary"] == "Summary"


class TestPruneResult:
    """Tests for PruneResult dataclass."""

    def test_default_values(self):
        """Test default values."""
        result = PruneResult()
        assert result.pruned_count == 0
        assert result.pruned_tokens == 0
        assert result.protected_count == 0
        assert result.was_pruned is False


class TestConstants:
    """Tests for module constants."""

    def test_prune_minimum_tokens(self):
        """Test PRUNE_MINIMUM_TOKENS constant."""
        assert PRUNE_MINIMUM_TOKENS == 20_000

    def test_prune_protect_tokens(self):
        """Test PRUNE_PROTECT_TOKENS constant."""
        assert PRUNE_PROTECT_TOKENS == 40_000

    def test_output_token_max(self):
        """Test OUTPUT_TOKEN_MAX constant."""
        assert OUTPUT_TOKEN_MAX == 8_192

    def test_protected_tools(self):
        """Test PRUNE_PROTECTED_TOOLS contains skill."""
        assert "skill" in PRUNE_PROTECTED_TOOLS


# Helper functions for test data creation

def _create_message_with_tool(
    msg_id: str,
    role: str,
    tool_name: str,
    token_count: int,
) -> Message:
    """Create a message with a tool part for testing."""
    tool_part = ToolPart(
        id=f"tool_{msg_id}",
        tool=tool_name,
        status="completed",
        output="x" * (token_count * 4),  # Approx tokens * chars_per_token
        tokens=token_count,
    )
    part = MessagePart(id=f"part_{msg_id}", type="tool", tool_part=tool_part)
    return Message(
        info=MessageInfo(id=msg_id, role=role),
        parts=[part],
    )
