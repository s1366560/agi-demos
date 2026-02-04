"""
Human-in-the-Loop (HITL) infrastructure.

This module provides the framework for HITL tools that require
human input during agent execution.

Architecture (Temporal-based):
- TemporalHITLHandler: Unified handler using Temporal Signals
- HITLType, HITLStatus: Unified type definitions from domain model
- HITLServicePort: Domain port for HITL operations
- HITLStateStore: Redis-based state persistence for pause/resume

Features:
- Temporal Signals for reliable cross-process communication
- Database persistence for recovery after page refresh
- SSE events for real-time frontend updates
- Automatic cleanup and timeout handling
- Agent state serialization for proper pause/resume
"""

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
    "TemporalHITLHandler",
    "create_hitl_handler",
    "HITLAgentState",
    "HITLStateStore",
    "get_hitl_state_store",
]
