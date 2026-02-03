"""
Backward compatibility redirect.

Compaction module has been moved to src.infrastructure.agent.context.compaction
This file provides backward compatibility for existing imports.
"""

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
    TokenCount,
    ToolPart,
    calculate_usable_context,
    estimate_tokens,
    is_overflow,
    prune_tool_outputs,
    should_compact,
)

__all__ = [
    "TokenCount",
    "ModelLimits",
    "ToolPart",
    "MessagePart",
    "MessageInfo",
    "Message",
    "CompactionResult",
    "is_overflow",
    "prune_tool_outputs",
    "should_compact",
    "calculate_usable_context",
    "estimate_tokens",
    "PRUNE_MINIMUM_TOKENS",
    "PRUNE_PROTECT_TOKENS",
    "PRUNE_PROTECTED_TOOLS",
    "OUTPUT_TOKEN_MAX",
]
