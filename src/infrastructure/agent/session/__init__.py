"""Session management package for Agent conversations.

DEPRECATED: This module has been moved to src.infrastructure.agent.context.
This file provides backward compatibility for existing imports.
"""

# Re-export from new location for backward compatibility
from src.infrastructure.agent.context.compaction import (
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
