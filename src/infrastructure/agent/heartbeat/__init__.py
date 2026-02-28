"""Heartbeat system for periodic agent self-check during long-running sessions.

Ported from OpenClaw's heartbeat-runner.ts / heartbeat.ts / tokens.ts.

The heartbeat system periodically checks HEARTBEAT.md for instructions,
allowing users to nudge the agent mid-session without interrupting its flow.
If no actionable content is found, the agent emits HEARTBEAT_OK and continues.
"""

from src.infrastructure.agent.heartbeat.config import HeartbeatConfig
from src.infrastructure.agent.heartbeat.runner import HeartbeatRunner
from src.infrastructure.agent.heartbeat.tokens import (
    HEARTBEAT_TOKEN,
    is_heartbeat_content_effectively_empty,
    strip_heartbeat_token,
)

__all__ = [
    "HEARTBEAT_TOKEN",
    "HeartbeatConfig",
    "HeartbeatRunner",
    "is_heartbeat_content_effectively_empty",
    "strip_heartbeat_token",
]
