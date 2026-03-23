"""Agent API router module.

This module aggregates all agent-related endpoints from sub-modules.
All endpoints have been fully migrated from agent_legacy.py.
"""

from fastapi import APIRouter

from . import (
    agent_graph_router,
    binding_router,
    commands,
    config,
    conversations,
    definitions_router,
    events,
    hitl,
    marketplace_router,
    messages,
    patterns,
    plans,
    subagent_router,
    templates,
    tools,
    trace_router,
)
from .schemas import (
    ActiveRunCountResponse,
    CapabilityDomainSummary,
    CapabilitySummaryResponse,
    ChatRequest,
    ClarificationResponseRequest,
    CommandArgInfo,
    CommandInfo,
    CommandsListResponse,
    ConversationResponse,
    CreateConversationRequest,
    DecisionResponseRequest,
    DescendantTreeResponse,
    DoomLoopResponseRequest,
    EnvVarResponseRequest,
    EventReplayResponse,
    ExecutionStatsResponse,
    ExecutionStatusResponse,
    HITLRequestResponse,
    HumanInteractionResponse,
    PatternsListResponse,
    PatternStepResponse,
    PendingHITLResponse,
    PluginRuntimeCapabilitySummary,
    PolicyLayerSummary,
    RecoveryInfo,
    ResetPatternsResponse,
    SubAgentRunListResponse,
    SubAgentRunResponse,
    TenantAgentConfigResponse,
    ToolCompositionResponse,
    ToolCompositionsListResponse,
    ToolInfo,
    ToolPolicyDebugRequest,
    ToolPolicyDebugResponse,
    ToolPolicyReportItem,
    ToolsListResponse,
    TraceChainResponse,
    UpdateConversationTitleRequest,
    UpdateTenantAgentConfigRequest,
    WorkflowPatternResponse,
    WorkflowStatusResponse,
)
from .utils import get_container_with_db

# Create main router with prefix
router = APIRouter(prefix="/api/v1/agent", tags=["agent"])

# Include all sub-routers (fully modular structure)
router.include_router(commands.router)
router.include_router(conversations.router)
router.include_router(messages.router)
router.include_router(tools.router)
router.include_router(patterns.router)
router.include_router(config.router)
router.include_router(hitl.router, prefix="/hitl")
router.include_router(events.router)
router.include_router(templates.router)
router.include_router(plans.router)
router.include_router(subagent_router.router)
router.include_router(binding_router.router)
router.include_router(definitions_router.router)
router.include_router(trace_router.router, prefix="/trace")
router.include_router(agent_graph_router.router)
router.include_router(marketplace_router.router)

__all__ = [
    "ActiveRunCountResponse",
    "CapabilityDomainSummary",
    "CapabilitySummaryResponse",
    # Schemas
    "ChatRequest",
    "ClarificationResponseRequest",
    "CommandArgInfo",
    "CommandInfo",
    "CommandsListResponse",
    "ConversationResponse",
    "CreateConversationRequest",
    "DecisionResponseRequest",
    "DescendantTreeResponse",
    "DoomLoopResponseRequest",
    "EnvVarResponseRequest",
    "EventReplayResponse",
    "ExecutionStatsResponse",
    "ExecutionStatusResponse",
    "HITLRequestResponse",
    "HumanInteractionResponse",
    "PatternStepResponse",
    "PatternsListResponse",
    "PendingHITLResponse",
    "PluginRuntimeCapabilitySummary",
    "PolicyLayerSummary",
    "RecoveryInfo",
    "ResetPatternsResponse",
    "SubAgentRunListResponse",
    "SubAgentRunResponse",
    "TenantAgentConfigResponse",
    "ToolCompositionResponse",
    "ToolCompositionsListResponse",
    "ToolInfo",
    "ToolPolicyDebugRequest",
    "ToolPolicyDebugResponse",
    "ToolPolicyReportItem",
    "ToolsListResponse",
    "TraceChainResponse",
    "UpdateConversationTitleRequest",
    "UpdateTenantAgentConfigRequest",
    "WorkflowPatternResponse",
    "WorkflowStatusResponse",
    "get_container_with_db",
    "router",
]
