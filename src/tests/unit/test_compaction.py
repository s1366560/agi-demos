"""
Unit tests for Context Compaction module.

Tests the token overflow detection and tool output pruning features
aligned with vendor/opencode implementation.
"""

import pytest

from src.infrastructure.agent.session.compaction import (
    PRUNE_MINIMUM_TOKENS,
    PRUNE_PROTECT_TOKENS,
    PRUNE_PROTECTED_TOOLS,
    CompactionResult,
    Message,
    MessageInfo,
    MessagePart,
    ModelLimits,
    TokenCount,
    ToolPart,
    calculate_usable_context,
    estimate_tokens,
    is_overflow,
    prune_tool_outputs,
    should_compact,
)


@pytest.mark.unit
class TestTokenCount:
    """Test TokenCount dataclass."""

    def test_initialization(self):
        """Test token count initialization."""
        count = TokenCount(
            input=1000,
            output=500,
            cache_read=200,
            cache_write=100,
            reasoning=50,
        )
        assert count.input == 1000
        assert count.output == 500
        assert count.cache_read == 200
        assert count.cache_write == 100
        assert count.reasoning == 50

    def test_total(self):
        """Test total token calculation."""
        count = TokenCount(
            input=1000,
            output=500,
            cache_read=200,
            cache_write=100,
            reasoning=50,
        )
        assert count.total() == 1850

    def test_total_empty(self):
        """Test total with zero values."""
        count = TokenCount()
        assert count.total() == 0


@pytest.mark.unit
class TestModelLimits:
    """Test ModelLimits dataclass."""

    def test_default_limits(self):
        """Test default model limits."""
        limits = ModelLimits()
        assert limits.context == 128_000
        assert limits.input == 124_000
        assert limits.output == 4_096

    def test_custom_limits(self):
        """Test custom model limits."""
        limits = ModelLimits(
            context=200_000,
            input=195_000,
            output=5_000,
        )
        assert limits.context == 200_000
        assert limits.input == 195_000
        assert limits.output == 5_000

    def test_unlimited_context(self):
        """Test unlimited context (context=0)."""
        limits = ModelLimits(context=0)
        assert limits.context == 0


@pytest.mark.unit
class TestEstimateTokens:
    """Test token estimation."""

    def test_empty_string(self):
        """Test empty string returns 0."""
        assert estimate_tokens("") == 0

    def test_none_input(self):
        """Test None input returns 0."""
        assert estimate_tokens(None) == 0

    def test_english_text(self):
        """Test English text estimation."""
        text = "Hello world, this is a test."
        # 28 chars / 4 = 7 tokens
        assert estimate_tokens(text) == 7

    def test_custom_chars_per_token(self):
        """Test custom chars_per_token."""
        text = "Hello world"
        assert estimate_tokens(text, chars_per_token=2.0) == 5

    def test_long_text(self):
        """Test longer text."""
        text = "a" * 1000  # 1000 chars
        assert estimate_tokens(text) == 250


@pytest.mark.unit
class TestCalculateUsableContext:
    """Test usable context calculation."""

    def test_explicit_input_limit(self):
        """Test when input limit is explicitly set."""
        limits = ModelLimits(
            context=100_000,
            input=90_000,
            output=10_000,
        )
        assert calculate_usable_context(limits) == 90_000

    def test_derived_input_limit(self):
        """Test when input is derived from context - output."""
        limits = ModelLimits(
            context=100_000,
            input=0,  # Not set, derive from context
            output=10_000,
        )
        # 100_000 - min(10_000, 8_192) = 100_000 - 8_192 = 91_808
        expected = 100_000 - 8_192
        assert calculate_usable_context(limits) == expected

    def test_unlimited_context(self):
        """Test unlimited context returns 0."""
        limits = ModelLimits(context=0)
        assert calculate_usable_context(limits) == 0


@pytest.mark.unit
class TestIsOverflow:
    """Test overflow detection."""

    def test_no_overflow(self):
        """Test when tokens are within limit."""
        tokens = TokenCount(input=50_000)
        limits = ModelLimits(context=100_000, input=90_000, output=10_000)
        assert not is_overflow(tokens, limits)

    def test_overflow(self):
        """Test when tokens exceed limit."""
        tokens = TokenCount(input=100_000)
        limits = ModelLimits(context=100_000, input=90_000, output=10_000)
        assert is_overflow(tokens, limits)

    def test_auto_compaction_disabled(self):
        """Test when auto-compaction is disabled."""
        tokens = TokenCount(input=100_000)
        limits = ModelLimits(context=100_000, input=90_000, output=10_000)
        assert not is_overflow(tokens, limits, auto_compaction_enabled=False)

    def test_unlimited_context(self):
        """Test with unlimited context never overflows."""
        tokens = TokenCount(input=1_000_000)
        limits = ModelLimits(context=0)
        assert not is_overflow(tokens, limits)

    def test_with_cache_tokens(self):
        """Test that cached tokens count toward total."""
        tokens = TokenCount(
            input=50_000,
            cache_read=30_000,
            cache_write=20_000,
        )
        limits = ModelLimits(context=100_000, input=90_000, output=10_000)
        # Total = 100_000, which exceeds 90_000 usable
        assert is_overflow(tokens, limits)


@pytest.mark.unit
class TestShouldCompact:
    """Test compaction threshold check."""

    def test_below_threshold(self):
        """Test when usage is below threshold."""
        tokens = TokenCount(input=50_000)
        limits = ModelLimits(context=100_000, input=90_000, output=10_000)
        assert not should_compact(tokens, limits, threshold=0.8)

    def test_above_threshold(self):
        """Test when usage exceeds threshold."""
        tokens = TokenCount(input=80_000)
        limits = ModelLimits(context=100_000, input=90_000, output=10_000)
        # 80_000 > 90_000 * 0.8 = 72_000
        assert should_compact(tokens, limits, threshold=0.8)

    def test_at_threshold(self):
        """Test when usage equals threshold."""
        tokens = TokenCount(input=72_000)
        limits = ModelLimits(context=100_000, input=90_000, output=10_000)
        # 72_000 == 90_000 * 0.8 = 72_000
        assert should_compact(tokens, limits, threshold=0.8)

    def test_unlimited_context(self):
        """Test unlimited context never compacts."""
        tokens = TokenCount(input=1_000_000)
        limits = ModelLimits(context=0)
        assert not should_compact(tokens, limits)

    def test_custom_threshold(self):
        """Test custom threshold."""
        tokens = TokenCount(input=60_000)
        limits = ModelLimits(context=100_000, input=90_000, output=10_000)
        # At 0.5 threshold: 60_000 > 45_000 = True
        assert should_compact(tokens, limits, threshold=0.5)
        # At 0.8 threshold: 60_000 < 72_000 = False
        assert not should_compact(tokens, limits, threshold=0.8)


@pytest.mark.unit
class TestPruneToolOutputs:
    """Test tool output pruning."""

    def _create_message(
        self,
        role: str,
        tool_parts: list[ToolPart] | None = None,
        is_summary: bool = False,
    ) -> Message:
        """Helper to create a test message."""
        return Message(
            info=MessageInfo(
                id=f"msg_{role}",
                role=role,
                summary=is_summary,
            ),
            parts=[
                MessagePart(
                    id="part_1",
                    type="tool",
                    tool_part=tool_part,
                )
                for tool_part in (tool_parts or [])
            ],
        )

    def _create_tool_part(
        self,
        tool: str,
        output: str,
        status: str = "completed",
        tokens: int | None = None,
        compacted: bool = False,
    ) -> ToolPart:
        """Helper to create a tool part."""
        return ToolPart(
            id=f"tool_{tool}",
            tool=tool,
            status=status,
            output=output,
            tokens=tokens,
            compacted=compacted,
        )

    def test_empty_messages(self):
        """Test with no messages."""
        result = prune_tool_outputs([])
        assert result.pruned_count == 0
        assert not result.was_pruned

    def test_pruning_disabled(self):
        """Test when pruning is disabled."""
        tool_part = self._create_tool_part("file_edit", "x" * 100_000)
        msg = self._create_message("assistant", [tool_part])
        result = prune_tool_outputs([msg], enabled=False)
        assert result.pruned_count == 0
        assert not result.was_pruned

    def test_protected_tool_not_pruned(self):
        """Test that protected tools are not pruned."""
        # "skill" is in PRUNE_PROTECTED_TOOLS
        # Need at least 2 user turns after this tool for it to be analyzed
        # Use 200K chars = 50K tokens > 40K threshold
        msgs = [
            self._create_message("user"),
            self._create_message("assistant", [self._create_tool_part("skill", "x" * 200_000)]),
            self._create_message("user"),
            self._create_message("assistant"),
            self._create_message("user"),
            self._create_message("assistant"),
        ]
        result = prune_tool_outputs(msgs)
        assert result.pruned_count == 0
        assert result.protected_count == 1
        assert not result.was_pruned
        # The skill tool should not be compacted
        assert not msgs[1].parts[0].tool_part.compacted

    def test_stops_at_summary(self):
        """Test that pruning stops at summary messages."""
        # Create messages: old, summary, recent
        old_tool = self._create_tool_part("file_edit", "x" * 100_000)
        old_msg = self._create_message("assistant", [old_tool])

        summary_msg = self._create_message("assistant", is_summary=True)

        recent_tool = self._create_tool_part("grep", "y" * 100_000)
        recent_msg = self._create_message("assistant", [recent_tool])

        result = prune_tool_outputs([old_msg, summary_msg, recent_msg])
        # Old tool should NOT be pruned because summary blocks it
        assert result.pruned_count == 0

    def test_stops_at_compacted(self):
        """Test that pruning stops at already compacted parts."""
        # Create messages with compacted tool in the middle
        old_tool = self._create_tool_part("file_edit", "x" * 100_000)
        old_msg = self._create_message("assistant", [old_tool])

        compacted_tool = self._create_tool_part(
            "grep",
            "y" * 100_000,
            compacted=True,
        )
        compacted_msg = self._create_message("assistant", [compacted_tool])

        very_old_tool = self._create_tool_part("find", "z" * 100_000)
        very_old_msg = self._create_message("assistant", [very_old_tool])

        result = prune_tool_outputs([very_old_msg, compacted_msg, old_msg])
        # very_old_tool should NOT be pruned because compacted_tool blocks it
        assert result.pruned_count == 0

    def test_skips_last_two_turns(self):
        """Test that last 2 user turns are protected."""
        # Create: user1, tool1, user2, tool2, user3, tool3, user4, tool4
        # Should skip tool3 and tool4 (in last 2 turns)
        # Each tool needs 200K chars = 50K tokens to exceed thresholds
        msgs = []

        # Turn 1
        msgs.append(self._create_message("user"))
        tool1 = self._create_tool_part("file_edit", "x" * 200_000)
        msgs.append(self._create_message("assistant", [tool1]))

        # Turn 2
        msgs.append(self._create_message("user"))
        tool2 = self._create_tool_part("grep", "y" * 200_000)
        msgs.append(self._create_message("assistant", [tool2]))

        # Turn 3
        msgs.append(self._create_message("user"))
        tool3 = self._create_tool_part("find", "z" * 200_000)
        msgs.append(self._create_message("assistant", [tool3]))

        # Turn 4
        msgs.append(self._create_message("user"))
        tool4 = self._create_tool_part("glob", "w" * 200_000)
        msgs.append(self._create_message("assistant", [tool4]))

        result = prune_tool_outputs(msgs)
        # Both tool1 and tool2 should be pruned (they're outside the last 2 turns)
        # Going backwards: user4 (turns=1, skip), tool4, user3 (turns=2, skip), tool3,
        # user2 (turns=3, analyze), tool2 (analyze), user1 (turns=4, analyze), tool1 (analyze)
        # PRUNE_PROTECT_TOKENS = 40_000, each tool ~50K tokens
        # total_tokens: tool2 (50K), tool1 (50K) = 100K > 40K, so both marked for prune
        # pruned_tokens > 20K, so both get pruned
        assert result.pruned_count == 2
        assert tool2.compacted
        assert tool1.compacted
        assert not tool3.compacted
        assert not tool4.compacted

    def test_only_completed_tools_pruned(self):
        """Test that only completed tools are pruned."""
        failed_tool = self._create_tool_part("file_edit", "x" * 200_000, status="failed")
        running_tool = self._create_tool_part("grep", "y" * 200_000, status="running")
        completed_tool = self._create_tool_part("find", "z" * 200_000, status="completed")

        # Need at least 2 user turns after completed_tool for it to be analyzed
        msgs = [
            self._create_message("user"),
            self._create_message("assistant", [failed_tool]),
            self._create_message("user"),
            self._create_message("assistant", [running_tool]),
            self._create_message("user"),
            self._create_message("assistant", [completed_tool]),
            self._create_message("user"),
            self._create_message("assistant"),
            self._create_message("user"),
            self._create_message("assistant"),
        ]

        result = prune_tool_outputs(msgs)
        # Only completed_tool should be pruned
        assert result.pruned_count == 1
        assert completed_tool.compacted
        assert not failed_tool.compacted
        assert not running_tool.compacted

    def test_minimum_threshold(self):
        """Test that pruning requires minimum tokens."""
        # Create a small tool output (< PRUNE_MINIMUM_TOKENS)
        # PRUNE_MINIMUM = 20_000 tokens = 80_000 chars
        small_tool = self._create_tool_part("file_edit", "x" * 10_000)
        msgs = [
            self._create_message("user"),
            self._create_message("assistant", [small_tool]),
            self._create_message("user"),
            self._create_message("assistant"),
            self._create_message("user"),
            self._create_message("assistant"),
        ]

        result = prune_tool_outputs(msgs)
        # Should not prune because below minimum threshold (20K)
        assert result.pruned_count == 0
        assert not result.was_pruned

    def test_prune_above_minimum(self):
        """Test that pruning works above minimum threshold."""
        # Create a large tool output (> PRUNE_MINIMUM_TOKENS)
        # PRUNE_MINIMUM = 20_000 tokens = 80_000 chars
        # PRUNE_PROTECT = 40_000 tokens = 160_000 chars
        large_tool = self._create_tool_part("file_edit", "x" * 200_000)
        msgs = [
            self._create_message("user"),
            self._create_message("assistant", [large_tool]),
            self._create_message("user"),
            self._create_message("assistant"),
            self._create_message("user"),
            self._create_message("assistant"),
        ]

        result = prune_tool_outputs(msgs)
        # Should prune because above minimum threshold (50K tokens > 20K)
        assert result.pruned_count == 1
        assert result.was_pruned
        assert large_tool.compacted
        assert large_tool.output == "[Output compacted to save tokens]"
        assert large_tool.compacted_at is not None

    def test_prune_multiple_tools(self):
        """Test pruning multiple tool outputs."""
        # Create multiple large tools
        # Each ~50K tokens, so they all exceed thresholds
        tool1 = self._create_tool_part("file_edit", "x" * 200_000)
        tool2 = self._create_tool_part("grep", "y" * 200_000)
        tool3 = self._create_tool_part("find", "z" * 200_000)

        msgs = [
            self._create_message("user"),
            self._create_message("assistant", [tool1]),
            self._create_message("user"),
            self._create_message("assistant", [tool2]),
            self._create_message("user"),
            self._create_message("assistant", [tool3]),
            self._create_message("user"),
            self._create_message("assistant"),
            self._create_message("user"),
            self._create_message("assistant"),
        ]

        result = prune_tool_outputs(msgs)
        # All three should be pruned (total tokens > 40K protect threshold)
        assert result.pruned_count == 3
        assert tool1.compacted
        assert tool2.compacted
        assert tool3.compacted

    def test_mixed_protected_and_regular(self):
        """Test mix of protected and regular tools."""
        # skill is protected
        skill_tool = self._create_tool_part("skill", "x" * 200_000)
        file_tool = self._create_tool_part("file_edit", "y" * 200_000)
        grep_tool = self._create_tool_part("grep", "z" * 200_000)

        msgs = [
            self._create_message("user"),
            self._create_message("assistant", [skill_tool]),
            self._create_message("user"),
            self._create_message("assistant", [file_tool]),
            self._create_message("user"),
            self._create_message("assistant", [grep_tool]),
            self._create_message("user"),
            self._create_message("assistant"),
            self._create_message("user"),
            self._create_message("assistant"),
        ]

        result = prune_tool_outputs(msgs)
        # Only file_edit and grep should be pruned, skill protected
        assert result.pruned_count == 2
        assert result.protected_count == 1
        assert not skill_tool.compacted
        assert file_tool.compacted
        assert grep_tool.compacted


@pytest.mark.unit
class TestCompactionResult:
    """Test CompactionResult class."""

    def test_initialization(self):
        """Test result initialization."""
        result = CompactionResult(
            was_compacted=True,
            original_token_count=100_000,
            final_token_count=50_000,
            pruned_tool_outputs=5,
            summary="Conversation summary",
        )
        assert result.was_compacted is True
        assert result.original_token_count == 100_000
        assert result.final_token_count == 50_000
        assert result.tokens_saved == 50_000
        assert result.pruned_tool_outputs == 5
        assert result.summary == "Conversation summary"

    def test_to_dict(self):
        """Test serialization to dict."""
        result = CompactionResult(
            was_compacted=True,
            original_token_count=100_000,
            final_token_count=50_000,
            pruned_tool_outputs=5,
            summary="Summary",
        )
        data = result.to_dict()
        assert data["was_compacted"] is True
        assert data["original_token_count"] == 100_000
        assert data["final_token_count"] == 50_000
        assert data["tokens_saved"] == 50_000
        assert data["pruned_tool_outputs"] == 5
        assert data["summary"] == "Summary"

    def test_default_values(self):
        """Test default values."""
        result = CompactionResult()
        assert result.was_compacted is False
        assert result.original_token_count == 0
        assert result.final_token_count == 0
        assert result.tokens_saved == 0
        assert result.pruned_tool_outputs == 0
        assert result.summary is None


@pytest.mark.unit
class TestConstants:
    """Test compaction constants."""

    def test_prune_minimum(self):
        """Test PRUNE_MINIMUM_TOKENS constant."""
        assert PRUNE_MINIMUM_TOKENS == 20_000

    def test_prune_protect(self):
        """Test PRUNE_PROTECT_TOKENS constant."""
        assert PRUNE_PROTECT_TOKENS == 40_000

    def test_protected_tools(self):
        """Test PRUNE_PROTECTED_TOOLS constant."""
        assert "skill" in PRUNE_PROTECTED_TOOLS
