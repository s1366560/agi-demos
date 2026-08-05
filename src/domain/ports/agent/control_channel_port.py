"""Control Channel Port - Domain interface for SubAgent runtime control.

Enables parent Agents to send steer/kill/pause/resume messages to running
SubAgents via an infrastructure-agnostic control channel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from src.domain.model.agent.tool_policy import ControlMessageType


@dataclass(frozen=True)
class ControlMessage:
    """Immutable control message sent to a running SubAgent.

    Attributes:
        run_id: Target SubAgent run identifier.
        message_type: Control action (steer, kill, pause, resume).
        payload: Optional payload (e.g. steer instruction text).
        sender_id: Identifier of the sending agent/user.
        timestamp: When the message was created.
        cascade: For KILL, whether to also terminate child SubAgents.
        run_input_id: Canonical persisted run-input identifier for Cloud steering.
        delivery_mode: Structured delivery mode; never inferred from payload text.
        run_revision: Canonical parent run revision accepted by the authority.
        message_id: Timeline message identifier associated with the input.
        idempotency_key: Authority command idempotency key.
        target_agent_id: Roster agent identifier for audited SubAgent control.
        target_agent_name: Roster agent display name captured at acceptance.
    """

    run_id: str
    message_type: ControlMessageType
    payload: str = ""
    sender_id: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    cascade: bool = False
    run_input_id: str = ""
    delivery_mode: str = ""
    run_revision: int | None = None
    message_id: str = ""
    idempotency_key: str = ""
    target_agent_id: str = ""
    target_agent_name: str = ""


@runtime_checkable
class ControlChannelPort(Protocol):
    """Protocol for SubAgent control channel.

    Implementations provide send/check/consume semantics for control
    messages. The channel must support:
    - Immediate kill signals (non-blocking, idempotent)
    - Ordered steer/pause/resume messages (delivered in order)

    SessionProcessor checks the channel between Think-Act-Observe
    iterations to react to incoming control messages.
    """

    async def send_control(self, message: ControlMessage) -> bool:
        """Send a control message to a SubAgent.

        Args:
            message: Control message to deliver.

        Returns:
            True if the message was accepted for delivery.
        """
        ...

    async def check_control(self, run_id: str) -> ControlMessage | None:
        """Check for a pending control message without consuming it.

        Used for quick polling (e.g. kill check) without side effects.

        Args:
            run_id: SubAgent run to check.

        Returns:
            The highest-priority pending message, or None.
        """
        ...

    async def consume_control(self, run_id: str) -> list[ControlMessage]:
        """Consume all pending control messages for a run.

        Messages are removed from the channel after consumption.
        Returns messages ordered by timestamp (oldest first).

        Args:
            run_id: SubAgent run to consume messages for.

        Returns:
            List of pending control messages (may be empty).
        """
        ...

    async def cleanup(self, run_id: str) -> None:
        """Remove all channel state for a completed/cancelled run.

        Called when a SubAgent run reaches a terminal state to free
        resources.

        Args:
            run_id: SubAgent run to clean up.
        """
        ...
