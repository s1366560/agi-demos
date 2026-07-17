"""Durable identity for client-submitted agent turns."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from src.domain.shared_kernel import DomainException, ValueObject


class AgentClientTurnStatus(str, Enum):
    """Protocol state for a durably accepted client turn."""

    ACCEPTED = "accepted"
    STARTED = "started"


@dataclass(frozen=True)
class AgentClientTurn(ValueObject):
    """Persisted binding between a client message ID and one agent execution."""

    id: str
    conversation_id: str
    client_message_id: str
    payload_hash: str
    execution_message_id: str
    status: AgentClientTurnStatus
    created_at: datetime
    started_at: datetime | None = None


@dataclass(frozen=True)
class AgentClientTurnClaim(ValueObject):
    """Result of atomically accepting or replaying a client turn."""

    turn: AgentClientTurn
    created: bool


class AgentClientTurnPayloadConflictError(DomainException):
    """Raised when one client message ID is reused with a different payload."""


class AgentClientTurnNotFoundError(DomainException):
    """Raised when execution is attempted without an accepted client turn."""
