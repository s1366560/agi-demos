"""Persistent input queued for, or steered into, an agent run."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any


class AgentRunInputDelivery(StrEnum):
    """When an accepted input is eligible for delivery."""

    STEER_NOW = "steer_now"
    QUEUE_NEXT = "queue_next"


class AgentRunInputStatus(StrEnum):
    """Authoritative lifecycle of an accepted run input."""

    PENDING_BOUNDARY = "pending_boundary"
    QUEUED = "queued"
    APPLIED = "applied"
    READY = "ready"
    BLOCKED = "blocked"
    PROMOTED_TO_PLAN = "promoted_to_plan"


class InvalidAgentRunInputTransition(ValueError):
    """Raised when a caller attempts an invalid lifecycle transition."""


@dataclass(frozen=True, kw_only=True)
class AgentRunInput:
    """Immutable run-input aggregate."""

    id: str
    tenant_id: str
    project_id: str
    conversation_id: str
    run_id: str
    actor_user_id: str
    expected_run_revision: int
    message: str
    message_id: str
    idempotency_key: str
    payload_hash: str
    delivery: AgentRunInputDelivery
    references: tuple[dict[str, Any], ...] = ()
    context_items: tuple[dict[str, Any], ...] = ()
    status: AgentRunInputStatus | None = None
    injected_via: str | None = None
    promoted_run_id: str | None = None
    promotion_key: str | None = None

    def __post_init__(self) -> None:
        if self.status is None:
            initial = (
                AgentRunInputStatus.PENDING_BOUNDARY
                if self.delivery == AgentRunInputDelivery.STEER_NOW
                else AgentRunInputStatus.QUEUED
            )
            object.__setattr__(self, "status", initial)

    def mark_applied(self, *, injected_via: str) -> AgentRunInput:
        """Record actual boundary injection."""

        if self.status == AgentRunInputStatus.APPLIED and self.injected_via == injected_via:
            return self
        if self.status != AgentRunInputStatus.PENDING_BOUNDARY:
            raise InvalidAgentRunInputTransition(
                f"Cannot apply run input from status {self.status}"
            )
        return replace(
            self,
            status=AgentRunInputStatus.APPLIED,
            injected_via=injected_via,
        )

    def settle_run_terminal(self, *, succeeded: bool) -> AgentRunInput:
        """Settle a queued input when its target run terminates."""

        if self.status != AgentRunInputStatus.QUEUED:
            raise InvalidAgentRunInputTransition(
                f"Cannot settle run input from status {self.status}"
            )
        return replace(
            self,
            status=(AgentRunInputStatus.READY if succeeded else AgentRunInputStatus.BLOCKED),
        )

    def promote(self, *, promoted_run_id: str, promotion_key: str) -> AgentRunInput:
        """Promote one ready input into the next explicit planning turn."""

        if self.status == AgentRunInputStatus.PROMOTED_TO_PLAN:
            if self.promoted_run_id == promoted_run_id and self.promotion_key == promotion_key:
                return self
            raise InvalidAgentRunInputTransition("Promotion replay payload conflicts")
        if self.status != AgentRunInputStatus.READY:
            raise InvalidAgentRunInputTransition(
                f"Cannot promote run input from status {self.status}"
            )
        return replace(
            self,
            status=AgentRunInputStatus.PROMOTED_TO_PLAN,
            promoted_run_id=promoted_run_id,
            promotion_key=promotion_key,
        )


__all__ = [
    "AgentRunInput",
    "AgentRunInputDelivery",
    "AgentRunInputStatus",
    "InvalidAgentRunInputTransition",
]
