"""Agent domain models for React-mode agent functionality.

This module contains domain entities organized into bounded context subpackages:
- conversation/: Conversations, messages, and attachments
- execution/: Agent execution cycles, checkpoints, and results
- skill/: Skills, permissions, tools, and compositions
- hitl/: Human-in-the-Loop requests and types
- config/: Tenant agent and skill configurations

Core concepts kept at this level:
- SubAgent: Specialized sub-agents (L3 layer)
- AgentMode: Agent operation modes (BUILD/PLAN/EXPLORE)
- WorkflowPattern: Learned workflow patterns

All symbols are re-exported here for backward compatibility.
"""

from src.domain.events.agent_events import AgentEventType

# Multi-Agent System (L4 layer)
from src.domain.model.agent.agent_binding import AgentBinding
from src.domain.model.agent.agent_definition import Agent
from src.domain.model.agent.agent_mode import AgentMode
from src.domain.model.agent.agent_source import AgentSource
from src.domain.model.agent.announce_payload import AnnouncePayload

# Config bounded context
from src.domain.model.agent.config import TenantAgentConfig

# Conversation bounded context
from src.domain.model.agent.conversation import (
    Conversation,
    ConversationStatus,
    Message,
    MessageRole,
    MessageType,
    ToolCall,
    ToolResult,
)

# Execution bounded context
from src.domain.model.agent.execution import (
    AdjustmentType,
    AgentExecution,
    AgentExecutionEvent,
    CheckpointType,
    ExecutionCheckpoint,
    ExecutionPlan,
    ExecutionPlanStatus,
    ExecutionStatus,
    ExecutionStep,
    ExecutionStepStatus,
    ReflectionAssessment,
    ReflectionResult,
    StepAdjustment,
    StepOutcome,
    StepResult,
    ThoughtLevel,
)

# HITL bounded context
from src.domain.model.agent.hitl import (
    HITLRequest,
    HITLRequestStatus,
    HITLRequestType,
)

# Skill bounded context
from src.domain.model.agent.skill import (
    EnvVarScope,
    Skill,
    SkillStatus,
    ToolComposition,
    ToolEnvironmentVariable,
    ToolExecutionRecord,
    TriggerPattern,
    TriggerType,
)
from src.domain.model.agent.spawn_mode import SpawnMode
from src.domain.model.agent.spawn_record import SpawnRecord

# Core concepts (kept at agent/ level)
from src.domain.model.agent.subagent import AgentModel, AgentTrigger, SubAgent
from src.domain.model.agent.subagent_run import SubAgentRun, SubAgentRunStatus
from src.domain.model.agent.workflow_pattern import WorkflowPattern
from src.domain.model.agent.workspace_config import WorkspaceConfig

__all__ = [
    # Reflection Result
    "AdjustmentType",
    # Multi-Agent System (L4 layer)
    "Agent",
    "AgentBinding",
    "AgentEventType",
    "AgentExecution",
    "AgentExecutionEvent",
    # Agent Mode
    "AgentMode",
    "AgentModel",
    "AgentSource",
    "AgentTrigger",
    "AnnouncePayload",
    "CheckpointType",
    "Conversation",
    "ConversationStatus",
    "EnvVarScope",
    "ExecutionCheckpoint",
    # Execution Plan (Enhanced)
    "ExecutionPlan",
    "ExecutionPlanStatus",
    "ExecutionStatus",
    "ExecutionStep",
    "ExecutionStepStatus",
    # HITL Requests
    "HITLRequest",
    "HITLRequestStatus",
    "HITLRequestType",
    "Message",
    "MessageRole",
    "MessageType",
    "ReflectionAssessment",
    "ReflectionResult",
    # Skill System (L2 layer)
    "Skill",
    "SkillStatus",
    "SpawnMode",
    "SpawnRecord",
    "StepAdjustment",
    # Step Result
    "StepOutcome",
    "StepResult",
    # SubAgent System (L3 layer)
    "SubAgent",
    "SubAgentRun",
    "SubAgentRunStatus",
    "TenantAgentConfig",
    "ThoughtLevel",
    "ToolCall",
    "ToolComposition",
    # Tool Environment Variables
    "ToolEnvironmentVariable",
    "ToolExecutionRecord",
    "ToolResult",
    "TriggerPattern",
    "TriggerType",
    "WorkflowPattern",
    "WorkspaceConfig",
]
