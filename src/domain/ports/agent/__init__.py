"""
Agent Ports - Domain layer interfaces for agent subsystem.

These ports define contracts that infrastructure adapters implement.
Following hexagonal architecture, domain depends on ports (not implementations).
"""

from src.domain.ports.agent.agent_credential_scope_port import AgentCredentialScopePort
from src.domain.ports.agent.agent_namespace_port import AgentNamespacePort
from src.domain.ports.agent.agent_registry import AgentRegistryPort
from src.domain.ports.agent.agent_tool_port import AgentToolBase
from src.domain.ports.agent.control_channel_port import (
    ControlChannelPort,
    ControlMessage,
)
from src.domain.ports.agent.binding_repository import (
    AgentBindingRepositoryPort,
)
from src.domain.ports.agent.context_engine_port import ContextEnginePort
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
from src.domain.ports.agent.message_binding_repository_port import (
    MessageBindingRepositoryPort,
)
from src.domain.ports.agent.message_router_port import MessageRouterPort
from src.domain.ports.agent.session_fork_merge_port import SessionForkMergePort
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
    "AgentBindingRepositoryPort",
    # Agent Credential Scope
    "AgentCredentialScopePort",
    # Agent Namespace
    "AgentNamespacePort",
    "AgentRegistryPort",
    "AgentToolBase",
    "AttachmentContent",
    "AttachmentInjectorPort",
    "AttachmentMetadata",
    "CompressionStrategy",
    "ContextBuildRequest",
    "ContextBuildResult",
    # Context Engine
    "ContextEnginePort",
    # Control Channel
    "ControlChannelPort",
    "ControlMessage",
    # Context Manager
    "ContextManagerPort",
    "LLMInvocationRequest",
    "LLMInvocationResult",
    # LLM Invoker
    "LLMInvokerPort",
    "MessageBindingRepositoryPort",
    "MessageBuilderPort",
    "MessageInput",
    # Message Router
    "MessageRouterPort",
    "ReActLoopConfig",
    # Session Fork/Merge
    "SessionForkMergePort",
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
