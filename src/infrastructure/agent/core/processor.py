"""
Session Processor - Core ReAct agent processing loop.

This module re-exports from the refactored processor package for backward compatibility.
New code should import from src.infrastructure.agent.processor directly.
"""

# Re-export from refactored module for backward compatibility
from src.infrastructure.agent.processor import (
    ProcessorConfig,
    ProcessorFactory,
    ProcessorResult,
    ProcessorState,
    RunContext,
    SessionProcessor,
    ToolDefinition,
)

__all__ = [
    "ProcessorConfig",
    "ProcessorFactory",
    "ProcessorResult",
    "ProcessorState",
    "RunContext",
    "SessionProcessor",
    "ToolDefinition",
]
