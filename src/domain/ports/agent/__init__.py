"""
Agent Ports - Domain layer interfaces for agent subsystem.

These ports define contracts that infrastructure adapters implement.
Following hexagonal architecture, domain depends on ports (not implementations).
"""

from src.domain.ports.agent.llm_invoker_port import (
    LLMInvokerPort,
    LLMInvocationRequest,
    LLMInvocationResult,
    StreamChunk,
)
from src.domain.ports.agent.tool_executor_port import (
    ToolExecutorPort,
    ToolExecutionRequest,
    ToolExecutionResult,
)
from src.domain.ports.agent.skill_orchestrator_port import (
    SkillOrchestratorPort,
    SkillMatchRequest,
    SkillMatchResult,
    SkillExecutionRequest,
)
from src.domain.ports.agent.subagent_orchestrator_port import (
    SubAgentOrchestratorPort,
    SubAgentMatchRequest,
    SubAgentMatchResult,
)
from src.domain.ports.agent.react_loop_port import (
    ReActLoopPort,
    ReActLoopConfig,
    ReActLoopContext,
)
from src.domain.ports.agent.context_manager_port import (
    ContextManagerPort,
    MessageBuilderPort,
    AttachmentInjectorPort,
    ContextBuildRequest,
    ContextBuildResult,
    AttachmentMetadata,
    AttachmentContent,
    MessageInput,
    CompressionStrategy,
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
