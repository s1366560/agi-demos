"""
Human-in-the-Loop (HITL) infrastructure.

This module provides the framework for HITL tools that require
human input during agent execution.

Architecture:
- HITLCoordinator: Future-based cooperative HITL management (primary)
- RayHITLHandler: Legacy handler kept for backward compatibility
- HITLType, HITLStatus: Unified type definitions from domain model
- HITLStateStore: Redis-based state persistence for crash recovery

Features:
- asyncio.Future-based cooperative pausing (no exception unwinding)
- Global coordinator registry for response routing
- Redis Streams for low-latency response delivery
- Database persistence for recovery after page refresh
- SSE events for real-time frontend updates
- Automatic cleanup and timeout handling
"""

from src.infrastructure.agent.hitl.coordinator import (
    HITLCoordinator,
    resolve_by_request_id,
)
from src.infrastructure.agent.hitl.ray_hitl_handler import RayHITLHandler
from src.infrastructure.agent.hitl.response_listener import (
    HITLResponseListener,
    get_hitl_response_listener,
    shutdown_hitl_response_listener,
)
from src.infrastructure.agent.hitl.session_registry import (
    AgentSessionRegistry,
    HITLWaiter,
    get_session_registry,
    reset_session_registry,
)
from src.infrastructure.agent.hitl.state_store import (
    HITLAgentState,
    HITLStateStore,
    get_hitl_state_store,
)

__all__ = [
    # Coordinator (primary)
    "HITLCoordinator",
    "resolve_by_request_id",
    # Legacy
    "RayHITLHandler",
    "HITLAgentState",
    "HITLStateStore",
    "get_hitl_state_store",
    # Real-time (low-latency)
    "HITLResponseListener",
    "get_hitl_response_listener",
    "shutdown_hitl_response_listener",
    "AgentSessionRegistry",
    "HITLWaiter",
    "get_session_registry",
    "reset_session_registry",
]
