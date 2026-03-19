"""Orchestration layer for multi-agent coordination."""

from __future__ import annotations

from src.infrastructure.agent.orchestration.orchestrator import (
    AgentOrchestrator,
    SendResult,
    SpawnResult,
)
from src.infrastructure.agent.orchestration.session_registry import (
    AgentSession,
    AgentSessionRegistry,
)
from src.infrastructure.agent.orchestration.spawn_manager import (
    SpawnDepthExceededError,
    SpawnManager,
)

__all__ = [
    "AgentOrchestrator",
    "AgentSession",
    "AgentSessionRegistry",
    "SendResult",
    "SpawnDepthExceededError",
    "SpawnManager",
    "SpawnResult",
]
