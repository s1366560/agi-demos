"""Context management module for agent conversations.

This module provides context window management capabilities:
- Dynamic context window sizing based on model limits
- Token estimation for messages
- Message compression via summarization
- Real-time context compaction during active conversations
"""

from .window_manager import ContextWindowConfig, ContextWindowManager, ContextWindowResult

__all__ = [
    "ContextWindowManager",
    "ContextWindowConfig",
    "ContextWindowResult",
]
