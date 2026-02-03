"""
Agent Ports - Domain layer interfaces for agent subsystem.

These ports define contracts that infrastructure adapters implement.
Following hexagonal architecture, domain depends on ports (not implementations).
"""

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
from src.domain.ports.agent.skill_orchestrator_port import (
    SkillExecutionRequest,
    SkillMatchRequest,
    SkillMatchResult,
    SkillOrchestratorPort,
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
    # Context Manager
    "ContextManagerPort",
    "MessageBuilderPort",
    "AttachmentInjectorPort",
    "ContextBuildRequest",
    "ContextBuildResult",
    "AttachmentMetadata",
    "AttachmentContent",
    "MessageInput",
    "CompressionStrategy",
]
