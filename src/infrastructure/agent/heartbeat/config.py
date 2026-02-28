"""Heartbeat configuration dataclass.

Holds resolved heartbeat settings for a single agent session,
including interval, prompt text, and acknowledgement thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass

# Default heartbeat prompt (ported from OpenClaw heartbeat.ts)
DEFAULT_HEARTBEAT_PROMPT: str = (
    "Read HEARTBEAT.md if it exists (workspace context). "
    "Follow it strictly. Do not infer or repeat old tasks from prior chats. "
    "If nothing needs attention, reply HEARTBEAT_OK."
)

# Default interval between heartbeat checks (minutes)
DEFAULT_HEARTBEAT_INTERVAL_MINUTES: int = 30

# Maximum character count for an "acknowledgement-only" reply.
# Replies at or below this length (after HEARTBEAT_OK stripping) are treated
# as empty acknowledgements and suppressed.
DEFAULT_HEARTBEAT_ACK_MAX_CHARS: int = 300


@dataclass(frozen=True)
class HeartbeatConfig:
    """Resolved heartbeat configuration for a single agent session.

    Attributes:
        enabled: Whether heartbeat checks are active.
        interval_minutes: Minutes between heartbeat checks.
        prompt: The prompt text sent to the agent for heartbeat checks.
        ack_max_chars: Maximum chars for an ack-only reply (stripped replies
            at or below this length are treated as HEARTBEAT_OK).
    """

    enabled: bool = True
    interval_minutes: int = DEFAULT_HEARTBEAT_INTERVAL_MINUTES
    prompt: str = DEFAULT_HEARTBEAT_PROMPT
    ack_max_chars: int = DEFAULT_HEARTBEAT_ACK_MAX_CHARS

    @property
    def interval_seconds(self) -> float:
        """Return the interval in seconds."""
        return self.interval_minutes * 60.0
