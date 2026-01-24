"""Session management package for Agent conversations."""

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

__all__ = [
    # Compaction types
    "TokenCount",
    "ModelLimits",
    "ToolPart",
    "MessagePart",
    "MessageInfo",
    "Message",
    "CompactionResult",
    # Compaction functions
    "is_overflow",
    "prune_tool_outputs",
    "should_compact",
    "calculate_usable_context",
    "estimate_tokens",
    # Constants
    "PRUNE_MINIMUM_TOKENS",
    "PRUNE_PROTECT_TOKENS",
    "PRUNE_PROTECTED_TOOLS",
]
