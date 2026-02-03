"""Context management module for agent conversations.

This module provides context window management capabilities:
- Dynamic context window sizing based on model limits
- Token estimation for messages
- Message compression via summarization
- Real-time context compaction during active conversations
- Tool output pruning to prevent context overflow
- Message building and attachment injection
"""

from .compaction import (
    Message,
    ModelLimits,
    PRUNE_MINIMUM_TOKENS,
    PRUNE_PROTECT_TOKENS,
    PRUNE_PROTECTED_TOOLS,
    OUTPUT_TOKEN_MAX,
    TokenCount,
    ToolPart,
    is_overflow,
    prune_tool_outputs,
)
from .window_manager import ContextWindowConfig, ContextWindowManager, ContextWindowResult
from .context_facade import ContextFacade, ContextFacadeConfig
from .builder import MessageBuilder, AttachmentInjector

__all__ = [
    # Facade (recommended entry point)
    "ContextFacade",
    "ContextFacadeConfig",
    # Builders
    "MessageBuilder",
    "AttachmentInjector",
    # Window Manager
    "ContextWindowManager",
    "ContextWindowConfig",
    "ContextWindowResult",
    # Compaction
    "Message",
    "ModelLimits",
    "TokenCount",
    "ToolPart",
    "is_overflow",
    "prune_tool_outputs",
    "PRUNE_MINIMUM_TOKENS",
    "PRUNE_PROTECT_TOKENS",
    "PRUNE_PROTECTED_TOOLS",
    "OUTPUT_TOKEN_MAX",
]
