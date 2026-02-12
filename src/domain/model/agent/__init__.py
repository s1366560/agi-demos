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
from src.domain.model.agent.agent_mode import AgentMode

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

# Core concepts (kept at agent/ level)
from src.domain.model.agent.subagent import AgentModel, AgentTrigger, SubAgent
from src.domain.model.agent.workflow_pattern import WorkflowPattern

__all__ = [
    "Conversation",
    "ConversationStatus",
    "Message",
    "MessageRole",
    "MessageType",
    "ToolCall",
    "ToolResult",
    "AgentExecution",
    "ExecutionStatus",
    "AgentExecutionEvent",
    "AgentEventType",
    "ExecutionCheckpoint",
    "CheckpointType",
    "ThoughtLevel",
    "WorkflowPattern",
    "ToolComposition",
    "TenantAgentConfig",
    "ToolExecutionRecord",
    # Skill System (L2 layer)
    "Skill",
    "SkillStatus",
    "TriggerType",
    "TriggerPattern",
    # SubAgent System (L3 layer)
    "SubAgent",
    "AgentModel",
    "AgentTrigger",
    # Agent Mode
    "AgentMode",
    # Tool Environment Variables
    "ToolEnvironmentVariable",
    "EnvVarScope",
    # HITL Requests
    "HITLRequest",
    "HITLRequestStatus",
    "HITLRequestType",
    # Execution Plan (Enhanced)
    "ExecutionPlan",
    "ExecutionPlanStatus",
    "ExecutionStep",
    "ExecutionStepStatus",
    # Reflection Result
    "AdjustmentType",
    "ReflectionAssessment",
    "ReflectionResult",
    "StepAdjustment",
    # Step Result
    "StepOutcome",
    "StepResult",
]
