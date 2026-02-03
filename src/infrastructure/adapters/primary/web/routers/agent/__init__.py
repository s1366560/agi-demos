"""Agent API router module.

This module aggregates all agent-related endpoints from sub-modules.
Phase 1 migration: conversations, messages, tools extracted to dedicated modules.
Remaining endpoints are imported from agent_legacy.py until fully migrated.
"""

from fastapi import APIRouter

from src.infrastructure.adapters.primary.web.routers import agent_legacy

from . import conversations, messages, tools
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

# Include sub-routers (new modular structure)
router.include_router(conversations.router)
router.include_router(messages.router)
router.include_router(tools.router)

# Endpoints already migrated (to be excluded from legacy import)
_MIGRATED_PATHS = {
    "/conversations",
    "/conversations/{conversation_id}",
    "/conversations/{conversation_id}/title",
    "/conversations/{conversation_id}/generate-title",
    "/conversations/{conversation_id}/messages",
    "/conversations/{conversation_id}/execution",
    "/conversations/{conversation_id}/tool-executions",
    "/conversations/{conversation_id}/status",
    "/conversations/{conversation_id}/execution/stats",
    "/tools",
    "/tools/compositions",
    "/tools/compositions/{composition_id}",
}

# Add remaining legacy routes (those not yet migrated)
for _route in agent_legacy.router.routes:
    if hasattr(_route, "path"):
        _path = _route.path.replace("/api/v1/agent", "")
        if _path not in _MIGRATED_PATHS:
            router.routes.append(_route)

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
