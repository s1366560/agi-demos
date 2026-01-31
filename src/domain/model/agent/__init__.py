"""Agent domain models for React-mode agent functionality.

This module contains domain entities for:
- Conversations: Multi-turn chat sessions
- Messages: Individual messages in conversations
- AgentExecution: Agent execution cycles (Think-Act-Observe)
- WorkPlan: Work-level plans for multi-step queries
- PlanStep: Individual steps in a work plan
- PlanStatus: Status of a work plan
- ThoughtLevel: Level of thinking (work or task)
- WorkflowPattern: Learned workflow patterns (T074)
- ToolComposition: Composed tool chains (T108)
- TenantAgentConfig: Tenant-level configuration (T093)
- Skill: Declarative skills for task patterns (L2 layer)
- SubAgent: Specialized sub-agents (L3 layer)
- Plan: Plan Mode planning documents
- AgentMode: Agent operation modes (BUILD/PLAN/EXPLORE)
"""

from src.domain.events.agent_events import AgentEventType
from src.domain.model.agent.agent_execution import AgentExecution, ExecutionStatus

# AgentEventType is imported from domain.events.agent_events (unified event types)
from src.domain.model.agent.agent_execution_event import AgentExecutionEvent
from src.domain.model.agent.agent_mode import AgentMode
from src.domain.model.agent.conversation import Conversation, ConversationStatus
from src.domain.model.agent.execution_checkpoint import CheckpointType, ExecutionCheckpoint

# Plan Mode Execution Models (Enhanced execution tracking)
from src.domain.model.agent.execution_plan import (
    ExecutionPlan,
    ExecutionPlanStatus,
    ExecutionStep,
    ExecutionStepStatus,
)
from src.domain.model.agent.hitl_request import (
    HITLRequest,
    HITLRequestStatus,
    HITLRequestType,
)
from src.domain.model.agent.message import Message, MessageRole, MessageType, ToolCall, ToolResult
from src.domain.model.agent.plan import (
    AlreadyInPlanModeError,
    InvalidPlanStateError,
    NotInPlanModeError,
    Plan,
    PlanDocumentStatus,
    PlanNotFoundError,
)
from src.domain.model.agent.plan_execution import (
    ExecutionMode,
    PlanExecution,
    StepStatus,
)
from src.domain.model.agent.plan_execution import (
    ExecutionStatus as PlanExecutionStatus,
)
from src.domain.model.agent.plan_execution import (
    ExecutionStep as PlanExecutionStep,
)
from src.domain.model.agent.plan_snapshot import PlanSnapshot, StepState
from src.domain.model.agent.plan_status import PlanStatus
from src.domain.model.agent.plan_step import PlanStep
from src.domain.model.agent.reflection_result import (
    AdjustmentType,
    ReflectionAssessment,
    ReflectionResult,
    StepAdjustment,
)
from src.domain.model.agent.skill import Skill, SkillStatus, TriggerPattern, TriggerType
from src.domain.model.agent.step_result import StepOutcome, StepResult
from src.domain.model.agent.subagent import AgentModel, AgentTrigger, SubAgent
from src.domain.model.agent.tenant_agent_config import TenantAgentConfig
from src.domain.model.agent.thought_level import ThoughtLevel
from src.domain.model.agent.tool_composition import ToolComposition
from src.domain.model.agent.tool_environment_variable import (
    EnvVarScope,
    ToolEnvironmentVariable,
)
from src.domain.model.agent.tool_execution_record import ToolExecutionRecord
from src.domain.model.agent.work_plan import WorkPlan
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
    "WorkPlan",
    "PlanStep",
    "PlanStatus",
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
    # Plan Mode (Agent Mode System)
    "Plan",
    "PlanDocumentStatus",
    "AgentMode",
    "InvalidPlanStateError",
    "PlanNotFoundError",
    "AlreadyInPlanModeError",
    "NotInPlanModeError",
    # Unified Plan Execution (New - replaces WorkPlan + ExecutionPlan)
    "PlanExecution",
    "PlanExecutionStep",
    "PlanExecutionStatus",
    "ExecutionMode",
    "StepStatus",
    # Tool Environment Variables
    "ToolEnvironmentVariable",
    "EnvVarScope",
    # HITL Requests
    "HITLRequest",
    "HITLRequestStatus",
    "HITLRequestType",
]
