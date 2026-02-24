"""
Session Processor - Core ReAct agent processing loop.

This module re-exports from the refactored processor package for backward compatibility.
New code should import from src.infrastructure.agent.processor directly.
"""

# Re-export from refactored module for backward compatibility
from src.infrastructure.agent.processor import (
    ProcessorConfig,
    ProcessorResult,
    ProcessorState,
    SessionProcessor,
    ToolDefinition,
)

__all__ = [
    "ProcessorConfig",
    "ProcessorResult",
    "ProcessorState",
    "SessionProcessor",
    "ToolDefinition",
]
