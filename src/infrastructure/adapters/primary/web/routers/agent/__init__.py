"""Agent API router module.

This module aggregates all agent-related endpoints from sub-modules.
All endpoints have been fully migrated from agent_legacy.py.
"""

from fastapi import APIRouter

from . import config, conversations, events, hitl, messages, patterns, plans, tools
from .schemas import (
    ChatRequest,
    ClarificationResponseRequest,
    ConversationResponse,
    CreateConversationRequest,
    DecisionResponseRequest,
    DoomLoopResponseRequest,
    EnterPlanModeRequest,
    EnvVarResponseRequest,
    EventReplayResponse,
    ExecutionStatsResponse,
    ExecutionStatusResponse,
    ExitPlanModeRequest,
    HITLRequestResponse,
    HumanInteractionResponse,
    PatternsListResponse,
    PatternStepResponse,
    PendingHITLResponse,
    PlanModeStatusResponse,
    PlanResponse,
    RecoveryInfo,
    ResetPatternsResponse,
    TenantAgentConfigResponse,
    ToolCompositionResponse,
    ToolCompositionsListResponse,
    ToolInfo,
    ToolsListResponse,
    UpdateConversationTitleRequest,
    UpdatePlanRequest,
    UpdateTenantAgentConfigRequest,
    WorkflowPatternResponse,
    WorkflowStatusResponse,
)
from .utils import get_container_with_db

# Create main router with prefix
router = APIRouter(prefix="/api/v1/agent", tags=["agent"])

# Include all sub-routers (fully modular structure)
router.include_router(conversations.router)
router.include_router(messages.router)
router.include_router(tools.router)
router.include_router(patterns.router)
router.include_router(config.router)
router.include_router(hitl.router, prefix="/hitl")
router.include_router(plans.router)
router.include_router(events.router)

__all__ = [
    "router",
    "get_container_with_db",
    # Schemas
    "ChatRequest",
    "ClarificationResponseRequest",
    "ConversationResponse",
    "CreateConversationRequest",
    "DecisionResponseRequest",
    "DoomLoopResponseRequest",
    "EnterPlanModeRequest",
    "EnvVarResponseRequest",
    "EventReplayResponse",
    "ExecutionStatsResponse",
    "ExecutionStatusResponse",
    "ExitPlanModeRequest",
    "HITLRequestResponse",
    "HumanInteractionResponse",
    "PatternStepResponse",
    "PatternsListResponse",
    "PendingHITLResponse",
    "PlanModeStatusResponse",
    "PlanResponse",
    "RecoveryInfo",
    "ResetPatternsResponse",
    "TenantAgentConfigResponse",
    "ToolCompositionResponse",
    "ToolCompositionsListResponse",
    "ToolInfo",
    "ToolsListResponse",
    "UpdateConversationTitleRequest",
    "UpdatePlanRequest",
    "UpdateTenantAgentConfigRequest",
    "WorkflowPatternResponse",
    "WorkflowStatusResponse",
]
