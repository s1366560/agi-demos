"""
Domain Ports - Hexagonal architecture interfaces.

Ports define contracts that infrastructure adapters implement.
Domain layer depends on these interfaces, not concrete implementations.
"""

# Agent ports (L1-L4 architecture)
from src.domain.ports.agent import (
    # LLM Invoker
    LLMInvokerPort,
    LLMInvocationRequest,
    LLMInvocationResult,
    StreamChunk,
    # Tool Executor
    ToolExecutorPort,
    ToolExecutionRequest,
    ToolExecutionResult,
    # Skill Orchestrator
    SkillOrchestratorPort,
    SkillMatchRequest,
    SkillMatchResult,
    SkillExecutionRequest,
    # SubAgent Orchestrator
    SubAgentOrchestratorPort,
    SubAgentMatchRequest,
    SubAgentMatchResult,
    # ReAct Loop
    ReActLoopPort,
    ReActLoopConfig,
    ReActLoopContext,
)

__all__ = [
    # LLM Invoker
    "LLMInvokerPort",
    "LLMInvocationRequest",
    "LLMInvocationResult",
    "StreamChunk",
    # Tool Executor
    "ToolExecutorPort",
    "ToolExecutionRequest",
    "ToolExecutionResult",
    # Skill Orchestrator
    "SkillOrchestratorPort",
    "SkillMatchRequest",
    "SkillMatchResult",
    "SkillExecutionRequest",
    # SubAgent Orchestrator
    "SubAgentOrchestratorPort",
    "SubAgentMatchRequest",
    "SubAgentMatchResult",
    # ReAct Loop
    "ReActLoopPort",
    "ReActLoopConfig",
    "ReActLoopContext",
]
