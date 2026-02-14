"""Processor module for memstack-agent.

This module provides:
- SessionProcessor: Core execution loop
- Event handling and streaming
- Tool execution orchestration
"""

from memstack_agent.processor.session import SessionProcessor

__all__ = [
    "SessionProcessor",
]
