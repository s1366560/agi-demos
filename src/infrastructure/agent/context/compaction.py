"""
Context Compaction Module - Token overflow detection and tool output pruning.

Implements compaction strategies to prevent context window overflow:
1. is_overflow() - Detects when token count exceeds context window
2. prune_tool_outputs() - Removes old tool outputs while protecting important tools
3. Constants aligned with vendor/opencode implementation

Reference: vendor/opencode/packages/opencode/src/session/compaction.ts
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Compaction thresholds (aligned with vendor/opencode)
PRUNE_MINIMUM_TOKENS = 20_000  # Minimum tokens before pruning is worthwhile
PRUNE_PROTECT_TOKENS = 40_000  # Protect recent 40K tokens worth of tool calls

# Tools whose output should never be pruned (aligned with vendor/opencode)
PRUNE_PROTECTED_TOOLS: set[str] = {"skill"}

# Default output token max (aligned with vendor/opencode)
OUTPUT_TOKEN_MAX = 8_192


@dataclass
class TokenCount:
    """Token count for a message or session."""

    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    reasoning: int = 0

    def total(self) -> int:
        """Get total token count."""
        return self.input + self.output + self.cache_read + self.cache_write + self.reasoning


@dataclass
class ModelLimits:
    """Model token limits."""

    context: int = 128_000  # Total context window
    input: int = 124_000  # Input tokens (if specified, else context - output)
    output: int = 4_096  # Max output tokens


@dataclass
class ToolPart:
    """Tool execution part in a message."""

    id: str
    tool: str  # Tool name (e.g., "file_edit", "grep", "skill")
    status: str  # "completed", "failed", "running"
    output: str  # Tool output content
    tokens: int | None = None  # Token count of output (if known)
    compacted: bool = False  # Whether output has been compacted
    compacted_at: datetime | None = None  # When compaction occurred


@dataclass
class MessagePart:
    """A part of a message (text, tool, etc.)."""

    id: str
    type: str  # "text", "tool", "compaction", etc.
    content: str | None = None
    tool_part: ToolPart | None = None
    synthetic: bool = False  # If True, this part was auto-generated


@dataclass
class MessageInfo:
    """Message metadata."""

    id: str
    role: str  # "user", "assistant", "system"
    parent_id: str | None = None
    summary: bool = False  # If True, this is a summary message
    created_at: datetime | None = None
    model_provider: str | None = None
    model_id: str | None = None


@dataclass
class Message:
    """A message in the conversation."""

    info: MessageInfo
    parts: list[MessagePart] = field(default_factory=list)
    tokens: TokenCount | None = None

    def get_tool_parts(self) -> list[ToolPart]:
        """Get all tool parts in this message."""
        return [
            part.tool_part
            for part in self.parts
            if part.type == "tool" and part.tool_part is not None
        ]


@dataclass
class PruneResult:
    """Result of tool output pruning."""

    pruned_count: int = 0  # Number of tool outputs pruned
    pruned_tokens: int = 0  # Total tokens pruned
    protected_count: int = 0  # Number of tools protected from pruning
    was_pruned: bool = False  # Whether any pruning occurred


def is_overflow(
    tokens: TokenCount,
    model_limits: ModelLimits,
    auto_compaction_enabled: bool = True,
) -> bool:
    """
    Detect if context has overflowed the available token budget.

    Aligned with vendor/opencode's isOverflow function.

    Args:
        tokens: Current token count
        model_limits: Model token limits
        auto_compaction_enabled: If False, never report overflow

    Returns:
        True if tokens exceed usable context window
    """
    # Auto-compaction can be disabled
    if not auto_compaction_enabled:
        return False

    # Models with unlimited context (context = 0)
    if model_limits.context == 0:
        return False

    # Calculate total tokens
    total = tokens.total()

    # Determine usable tokens
    # Vendor logic: output is min(model.limit.output, OUTPUT_TOKEN_MAX)
    # usable = model.limit.input or (context - output)
    output_budget = (
        min(model_limits.output, OUTPUT_TOKEN_MAX) if model_limits.output > 0 else OUTPUT_TOKEN_MAX
    )
    usable = (
        model_limits.input if model_limits.input > 0 else (model_limits.context - output_budget)
    )

    # Check for overflow (>= for at threshold detection)
    return total >= usable


def prune_tool_outputs(
    messages: list[Message],
    enabled: bool = True,
) -> PruneResult:
    """
    Prune old tool outputs to reduce context window usage.

    Aligned with vendor/opencode's prune function:
    - Goes backwards through parts until 40K tokens of tool calls accumulated
    - Erases output of previous tool calls (older than 40K tokens)
    - Protects PRUNE_PROTECTED_TOOLS from pruning
    - Only prunes if at least 20K tokens can be recovered

    Args:
        messages: List of messages in the conversation (in order)
        enabled: If False, pruning is disabled

    Returns:
        PruneResult with pruning statistics
    """
    result = PruneResult()

    # Pruning can be disabled
    if not enabled:
        logger.debug("Tool output pruning is disabled")
        return result

    if not messages:
        return result

    logger.info("Starting tool output pruning")

    # Find tool outputs to prune
    total_tokens = 0
    pruned_tokens = 0
    parts_to_prune: list[tuple[Message, ToolPart]] = []
    turns = 0  # Number of user messages seen (turns)

    # Iterate backwards through messages
    for msg_index in range(len(messages) - 1, -1, -1):
        msg = messages[msg_index]

        # Count user turns
        if msg.info.role == "user":
            turns += 1

        # Skip the last 2 turns (most recent context)
        if turns < 2:
            continue

        # Stop at summary messages (they're already compressed)
        if msg.info.role == "assistant" and msg.info.summary:
            break

        # Check tool parts in this message (iterate backwards)
        tool_parts = msg.get_tool_parts()
        for part_index in range(len(tool_parts) - 1, -1, -1):
            tool_part = tool_parts[part_index]

            # Only prune completed tool outputs
            if tool_part.status != "completed":
                continue

            # Skip protected tools
            if tool_part.tool in PRUNE_PROTECTED_TOOLS:
                result.protected_count += 1
                continue

            # Skip already compacted parts
            if tool_part.compacted:
                break

            # Estimate tokens if not provided
            if tool_part.tokens is None:
                tool_part.tokens = estimate_tokens(tool_part.output)

            # Add to total
            total_tokens += tool_part.tokens

            # If we're past the protection threshold, mark for pruning
            if total_tokens > PRUNE_PROTECT_TOKENS:
                pruned_tokens += tool_part.tokens
                parts_to_prune.append((msg, tool_part))

    logger.info(
        f"Pruning analysis: {len(parts_to_prune)} parts, "
        f"{pruned_tokens} tokens to prune, {total_tokens} total"
    )

    # Only prune if we can recover at least PRUNE_MINIMUM_TOKENS
    if pruned_tokens > PRUNE_MINIMUM_TOKENS:
        for msg, tool_part in parts_to_prune:
            # Mark as compacted
            tool_part.compacted = True
            tool_part.compacted_at = datetime.now()
            # Clear the output to save tokens
            tool_part.output = "[Output compacted to save tokens]"
            result.pruned_count += 1

        result.pruned_tokens = pruned_tokens
        result.was_pruned = True

        logger.info(
            f"Pruned {result.pruned_count} tool outputs, recovered ~{result.pruned_tokens} tokens"
        )
    else:
        logger.info(
            f"Skipping pruning: only {pruned_tokens} tokens available "
            f"(minimum threshold: {PRUNE_MINIMUM_TOKENS})"
        )

    return result


def estimate_tokens(text: str, chars_per_token: float = 4.0) -> int:
    """
    Estimate token count for text with CJK awareness.

    Args:
        text: Text to estimate
        chars_per_token: Characters per token (default 4.0 for English)

    Returns:
        Estimated token count
    """
    if not text:
        return 0

    import re

    cjk_pattern = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uac00-\ud7af]")
    cjk_chars = len(cjk_pattern.findall(text))
    total_chars = len(text)
    cjk_ratio = cjk_chars / total_chars if total_chars > 0 else 0

    if cjk_ratio > 0.3:
        effective_ratio = 2.0
    elif cjk_ratio > 0.1:
        effective_ratio = 3.0
    else:
        effective_ratio = chars_per_token

    return int(total_chars / effective_ratio)


def calculate_usable_context(
    model_limits: ModelLimits,
) -> int:
    """
    Calculate usable context tokens for input.

    Aligned with vendor/opencode's logic.

    Args:
        model_limits: Model token limits

    Returns:
        Usable input tokens
    """
    if model_limits.context == 0:
        return 0  # Unlimited

    # Output budget is min(model limit, OUTPUT_TOKEN_MAX)
    output_budget = (
        min(model_limits.output, OUTPUT_TOKEN_MAX) if model_limits.output > 0 else OUTPUT_TOKEN_MAX
    )

    # Usable is explicit input limit or (context - output)
    if model_limits.input > 0:
        return model_limits.input
    return model_limits.context - output_budget


def should_compact(
    tokens: TokenCount,
    model_limits: ModelLimits,
    threshold: float = 0.8,
) -> bool:
    """
    Check if context should be compacted based on threshold.

    Args:
        tokens: Current token count
        model_limits: Model token limits
        threshold: Usage threshold (0.0-1.0) to trigger compaction

    Returns:
        True if compaction should be triggered
    """
    usable = calculate_usable_context(model_limits)
    if usable == 0:
        return False  # Unlimited context

    total = tokens.total()
    return total >= (usable * threshold)


class CompactionResult:
    """Result of context compaction operation."""

    def __init__(
        self,
        was_compacted: bool = False,
        original_token_count: int = 0,
        final_token_count: int = 0,
        pruned_tool_outputs: int = 0,
        summary: str | None = None,
    ) -> None:
        self.was_compacted = was_compacted
        self.original_token_count = original_token_count
        self.final_token_count = final_token_count
        self.pruned_tool_outputs = pruned_tool_outputs
        self.summary = summary
        self.tokens_saved = original_token_count - final_token_count

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "was_compacted": self.was_compacted,
            "original_token_count": self.original_token_count,
            "final_token_count": self.final_token_count,
            "tokens_saved": self.tokens_saved,
            "pruned_tool_outputs": self.pruned_tool_outputs,
            "summary": self.summary,
        }
