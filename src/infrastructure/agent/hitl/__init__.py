"""
Human-in-the-Loop (HITL) infrastructure.

This module provides the framework for HITL tools that require
human input during agent execution.

Architecture (Ray-based):
- RayHITLHandler: Unified handler for HITL requests in Actor runtime
- HITLType, HITLStatus: Unified type definitions from domain model
- HITLStateStore: Redis-based state persistence for pause/resume

Features:
- Redis Streams for low-latency response delivery
- Database persistence for recovery after page refresh
- SSE events for real-time frontend updates
- Automatic cleanup and timeout handling
- Agent state serialization for proper pause/resume
"""

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
from src.infrastructure.agent.hitl.ray_hitl_handler import RayHITLHandler

__all__ = [
    # Ray-based
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
