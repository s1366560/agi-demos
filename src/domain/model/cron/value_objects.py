"""Value objects and enums for the Cron bounded context.

Ported from OpenClaw's discriminated-union schedule/payload/delivery types
into Python dataclasses following MemStack's DDD conventions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.domain.shared_kernel import ValueObject

# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------


class ScheduleType(str, Enum):
    """Discriminator for CronSchedule union."""

    AT = "at"  # One-shot at a specific ISO-8601 timestamp
    EVERY = "every"  # Recurring interval
    CRON = "cron"  # Cron expression


@dataclass(frozen=True, kw_only=True)
class CronSchedule(ValueObject):
    """Describes *when* a job fires.

    Stored as ``schedule_type`` + ``schedule_config`` JSON column.

    Attributes:
        kind: Discriminator — at | every | cron.
        config: Type-specific configuration dict.
            - at:    {"run_at": "<ISO-8601>"}
            - every: {"interval_seconds": int, "anchor_at": "<ISO-8601>"|None}
            - cron:  {"expr": "*/5 * * * *", "timezone": "UTC"|None,
                       "stagger_seconds": int|0}
    """

    kind: ScheduleType
    config: dict[str, Any] = field(default_factory=dict)

    # -- Factory helpers -----------------------------------------------------

    @classmethod
    def at(cls, run_at: str) -> CronSchedule:
        """One-shot schedule at an ISO-8601 timestamp."""
        return cls(kind=ScheduleType.AT, config={"run_at": run_at})

    @classmethod
    def every(
        cls,
        interval_seconds: int,
        anchor_at: str | None = None,
    ) -> CronSchedule:
        """Recurring interval schedule."""
        cfg: dict[str, Any] = {"interval_seconds": interval_seconds}
        if anchor_at is not None:
            cfg["anchor_at"] = anchor_at
        return cls(kind=ScheduleType.EVERY, config=cfg)

    @classmethod
    def cron(
        cls,
        expr: str,
        timezone: str | None = None,
        stagger_seconds: int = 0,
    ) -> CronSchedule:
        """Cron-expression schedule with optional timezone and stagger."""
        cfg: dict[str, Any] = {"expr": expr}
        if timezone is not None:
            cfg["timezone"] = timezone
        if stagger_seconds:
            cfg["stagger_seconds"] = stagger_seconds
        return cls(kind=ScheduleType.CRON, config=cfg)

    # -- Serialisation -------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind.value, **self.config}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CronSchedule:
        kind = ScheduleType(data["kind"])
        config = {k: v for k, v in data.items() if k != "kind"}
        return cls(kind=kind, config=config)


# ---------------------------------------------------------------------------
# Payload
# ---------------------------------------------------------------------------


class PayloadType(str, Enum):
    """What the cron job delivers to the agent."""

    SYSTEM_EVENT = "system_event"  # Inject text as a system event
    AGENT_TURN = "agent_turn"  # Run an agent turn with a message


@dataclass(frozen=True, kw_only=True)
class CronPayload(ValueObject):
    """Describes *what* a job sends when it fires.

    Attributes:
        kind: Discriminator — system_event | agent_turn.
        config: Type-specific configuration dict.
            - system_event: {"content": str}
            - agent_turn:   {"message": str, "model": str|None,
                             "timeout_seconds": int|300}
    """

    kind: PayloadType
    config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def system_event(cls, content: str) -> CronPayload:
        return cls(kind=PayloadType.SYSTEM_EVENT, config={"content": content})

    @classmethod
    def agent_turn(
        cls,
        message: str,
        model: str | None = None,
        timeout_seconds: int = 300,
    ) -> CronPayload:
        cfg: dict[str, Any] = {
            "message": message,
            "timeout_seconds": timeout_seconds,
        }
        if model is not None:
            cfg["model"] = model
        return cls(kind=PayloadType.AGENT_TURN, config=cfg)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind.value, **self.config}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CronPayload:
        kind = PayloadType(data["kind"])
        config = {k: v for k, v in data.items() if k != "kind"}
        return cls(kind=kind, config=config)


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


class DeliveryType(str, Enum):
    """How the result of a cron run is delivered."""

    NONE = "none"  # Fire-and-forget
    ANNOUNCE = "announce"  # Post result to conversation
    WEBHOOK = "webhook"  # POST result to external URL


@dataclass(frozen=True, kw_only=True)
class CronDelivery(ValueObject):
    """Describes *how* the result is delivered.

    Attributes:
        kind: Discriminator — none | announce | webhook.
        config: Type-specific configuration dict.
            - none:     {}
            - announce: {"conversation_id": str}
            - webhook:  {"url": str, "headers": dict|None, "secret": str|None}
    """

    kind: DeliveryType
    config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def none(cls) -> CronDelivery:
        return cls(kind=DeliveryType.NONE)

    @classmethod
    def announce(cls, conversation_id: str) -> CronDelivery:
        return cls(
            kind=DeliveryType.ANNOUNCE,
            config={"conversation_id": conversation_id},
        )

    @classmethod
    def webhook(
        cls,
        url: str,
        headers: dict[str, str] | None = None,
        secret: str | None = None,
    ) -> CronDelivery:
        cfg: dict[str, Any] = {"url": url}
        if headers is not None:
            cfg["headers"] = headers
        if secret is not None:
            cfg["secret"] = secret
        return cls(kind=DeliveryType.WEBHOOK, config=cfg)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind.value, **self.config}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CronDelivery:
        kind = DeliveryType(data["kind"])
        config = {k: v for k, v in data.items() if k != "kind"}
        return cls(kind=kind, config=config)


# ---------------------------------------------------------------------------
# Conversation mode
# ---------------------------------------------------------------------------


class ConversationMode(str, Enum):
    """How the scheduler manages conversations for a cron job."""

    REUSE = "reuse"  # Re-use existing conversation
    FRESH = "fresh"  # Create a new conversation each run


# ---------------------------------------------------------------------------
# Run status
# ---------------------------------------------------------------------------


class CronRunStatus(str, Enum):
    """Outcome of a single cron run."""

    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# Trigger type
# ---------------------------------------------------------------------------


class TriggerType(str, Enum):
    """What initiated the cron run."""

    SCHEDULED = "scheduled"
    MANUAL = "manual"
