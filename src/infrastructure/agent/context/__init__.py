"""Context management module for agent conversations.

This module provides context window management capabilities:
- Dynamic context window sizing based on model limits
- Token estimation for messages
- Message compression via summarization
- Real-time context compaction during active conversations
- Tool output pruning to prevent context overflow
- Message building and attachment injection
"""

from .builder import AttachmentInjector, MessageBuilder
from .compaction import (
    OUTPUT_TOKEN_MAX,
    PRUNE_MINIMUM_TOKENS,
    PRUNE_PROTECT_TOKENS,
    PRUNE_PROTECTED_TOOLS,
    Message,
    ModelLimits,
    TokenCount,
    ToolPart,
    is_overflow,
    prune_tool_outputs,
)
from .compression_engine import (
    AdaptiveStrategySelector,
    AdaptiveThresholds,
    CompressionResult,
    ContextCompressionEngine,
)
from .compression_history import CompressionHistory, CompressionRecord
from .compression_state import CompressionLevel, CompressionState, SummaryChunk
from .context_facade import ContextFacade, ContextFacadeConfig
from .window_manager import ContextWindowConfig, ContextWindowManager, ContextWindowResult

__all__ = [
    "OUTPUT_TOKEN_MAX",
    "PRUNE_MINIMUM_TOKENS",
    "PRUNE_PROTECTED_TOOLS",
    "PRUNE_PROTECT_TOKENS",
    "AdaptiveStrategySelector",
    "AdaptiveThresholds",
    "AttachmentInjector",
    "CompressionHistory",
    # Compression State & History
    "CompressionLevel",
    "CompressionRecord",
    "CompressionResult",
    "CompressionState",
    # Compression Engine
    "ContextCompressionEngine",
    # Facade (recommended entry point)
    "ContextFacade",
    "ContextFacadeConfig",
    "ContextWindowConfig",
    # Window Manager
    "ContextWindowManager",
    "ContextWindowResult",
    # Compaction
    "Message",
    # Builders
    "MessageBuilder",
    "ModelLimits",
    "SummaryChunk",
    "TokenCount",
    "ToolPart",
    "is_overflow",
    "prune_tool_outputs",
]
