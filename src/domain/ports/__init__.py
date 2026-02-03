"""
Domain Ports - Hexagonal architecture interfaces.

Ports define contracts that infrastructure adapters implement.
Domain layer depends on these interfaces, not concrete implementations.
"""

# Agent ports (L1-L4 architecture)
from src.domain.ports.agent import (
    LLMInvocationRequest,
    LLMInvocationResult,
    # LLM Invoker
    LLMInvokerPort,
    ReActLoopConfig,
    ReActLoopContext,
    # ReAct Loop
    ReActLoopPort,
    SkillExecutionRequest,
    SkillMatchRequest,
    SkillMatchResult,
    # Skill Orchestrator
    SkillOrchestratorPort,
    StreamChunk,
    SubAgentMatchRequest,
    SubAgentMatchResult,
    # SubAgent Orchestrator
    SubAgentOrchestratorPort,
    ToolExecutionRequest,
    ToolExecutionResult,
    # Tool Executor
    ToolExecutorPort,
)

# MCP ports (Model Context Protocol)
from src.domain.ports.mcp import (
    MCPClientPort,
    MCPRegistryPort,
    MCPToolExecutorPort,
    MCPTransportPort,
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
    # MCP
    "MCPClientPort",
    "MCPRegistryPort",
    "MCPToolExecutorPort",
    "MCPTransportPort",
]
