"""
Agent Ports - Domain layer interfaces for agent subsystem.

These ports define contracts that infrastructure adapters implement.
Following hexagonal architecture, domain depends on ports (not implementations).
"""

from src.domain.ports.agent.agent_tool_port import AgentToolBase
from src.domain.ports.agent.context_manager_port import (
    AttachmentContent,
    AttachmentInjectorPort,
    AttachmentMetadata,
    CompressionStrategy,
    ContextBuildRequest,
    ContextBuildResult,
    ContextManagerPort,
    MessageBuilderPort,
    MessageInput,
)
from src.domain.ports.agent.llm_invoker_port import (
    LLMInvocationRequest,
    LLMInvocationResult,
    LLMInvokerPort,
    StreamChunk,
)
from src.domain.ports.agent.react_loop_port import (
    ReActLoopConfig,
    ReActLoopContext,
    ReActLoopPort,
)
from src.domain.ports.agent.subagent_orchestrator_port import (
    SubAgentMatchRequest,
    SubAgentMatchResult,
    SubAgentOrchestratorPort,
)
from src.domain.ports.agent.tool_executor_port import (
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolExecutorPort,
)

__all__ = [
    # Agent Tool Base
    "AgentToolBase",
    "AttachmentContent",
    "AttachmentInjectorPort",
    "AttachmentMetadata",
    "CompressionStrategy",
    "ContextBuildRequest",
    "ContextBuildResult",
    # Context Manager
    "ContextManagerPort",
    "LLMInvocationRequest",
    "LLMInvocationResult",
    # LLM Invoker
    "LLMInvokerPort",
    "MessageBuilderPort",
    "MessageInput",
    "ReActLoopConfig",
    "ReActLoopContext",
    # ReAct Loop
    "ReActLoopPort",
    "StreamChunk",
    "SubAgentMatchRequest",
    "SubAgentMatchResult",
    # SubAgent Orchestrator
    "SubAgentOrchestratorPort",
    "ToolExecutionRequest",
    "ToolExecutionResult",
    # Tool Executor
    "ToolExecutorPort",
]
