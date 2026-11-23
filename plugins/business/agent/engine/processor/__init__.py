"""
Session Processor Module - Refactored from monolithic processor.py

Components:
- processor.py: Main SessionProcessor class (orchestration)
- goal_evaluator.py: Goal completion evaluation and suggestion generation
- artifact_handler.py: Artifact processing, sanitization, and upload
- hitl_tool_handler.py: HITL tool dispatch (clarification, decision, env_var)
- message_utils.py: Message building utilities
"""

from .artifact_handler import ArtifactHandler
from .factory import ProcessorFactory
from .goal_evaluator import GoalCheckResult, GoalEvaluator
from .processor import (
    ProcessorConfig,
    ProcessorResult,
    ProcessorState,
    SessionProcessor,
    ToolDefinition,
)
from .run_context import RunContext

__all__ = [
    "ArtifactHandler",
    "GoalCheckResult",
    "GoalEvaluator",
    "ProcessorConfig",
    "ProcessorFactory",
    "ProcessorResult",
    "ProcessorState",
    "RunContext",
    "SessionProcessor",
    "ToolDefinition",
]
