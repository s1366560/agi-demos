"""
Human-in-the-Loop (HITL) infrastructure.

This module provides the framework for HITL tools that require
human input during agent execution.

Architecture (Temporal-based):
- TemporalHITLHandler: Unified handler using Temporal Signals
- HITLType, HITLStatus: Unified type definitions from domain model
- HITLServicePort: Domain port for HITL operations
- HITLStateStore: Redis-based state persistence for pause/resume

Real-time Architecture (Redis Streams):
- HITLResponseListener: Consumes HITL responses from Redis Streams
- AgentSessionRegistry: Tracks sessions waiting for HITL responses
- Enables ~30ms response delivery (vs 500ms+ with Temporal Signal)

Features:
- Temporal Signals for reliable cross-process communication
- Redis Streams for low-latency direct delivery (dual-channel)
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
from src.infrastructure.agent.hitl.temporal_hitl_handler import (
    TemporalHITLHandler,
    create_hitl_handler,
)

__all__ = [
    # Temporal-based (reliable)
    "TemporalHITLHandler",
    "create_hitl_handler",
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
