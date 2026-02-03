"""
Session Processor Module - Refactored from monolithic processor.py

Components:
- processor.py: Main SessionProcessor class (orchestration)
- llm_caller.py: LLM stream handling and response processing
- tool_runner.py: Tool execution with permission and retry
- message_utils.py: Message building utilities
"""

from .processor import (
    ProcessorConfig,
    ProcessorResult,
    ProcessorState,
    SessionProcessor,
    ToolDefinition,
)

__all__ = [
    "SessionProcessor",
    "ProcessorConfig",
    "ProcessorState",
    "ProcessorResult",
    "ToolDefinition",
]
