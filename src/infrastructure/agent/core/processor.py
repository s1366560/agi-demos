"""
Session Processor - Core ReAct agent processing loop.

This module re-exports from the refactored processor package for backward compatibility.
New code should import from plugins.business.agent.engine.processor directly.
"""

# Re-export from refactored module for backward compatibility
from plugins.business.agent.engine.processor import (
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
