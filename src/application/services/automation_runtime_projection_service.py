"""Typed projection of Agent runtime lifecycle into durable automation records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol


class AutomationRuntimeProjectionConflictError(RuntimeError):
    """Raised when a terminal runtime result conflicts with persisted state."""


class AutomationRuntimeOutcome(str, Enum):
    """Closed terminal outcomes emitted by the Agent runtime."""

    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"

    @property
    def error_code(self) -> str | None:
        return {
            self.SUCCESS: None,
            self.FAILED: "agent_execution_failed",
            self.CANCELLED: "agent_execution_cancelled",
            self.TIMEOUT: "agent_execution_timed_out",
        }[self]


@dataclass(frozen=True, slots=True)
class AutomationRuntimeIdentity:
    """Server-owned correlation and tenant/project scope for one Agent turn."""

    tenant_id: str
    project_id: str
    runtime_execution_id: str
    conversation_id: str


@dataclass(frozen=True, slots=True)
class AutomationRuntimeTerminal:
    """Structured terminal facts; arbitrary Agent output is intentionally excluded."""

    outcome: AutomationRuntimeOutcome
    observed_at: datetime
    execution_time_ms: float
    event_count: int


@dataclass(frozen=True, slots=True)
class AutomationRuntimeProjection:
    """Result of an idempotent runtime projection attempt."""

    matched: bool
    run_status: str | None = None
    operation_status: str | None = None
    duplicate: bool = False
    delivery_ack_pending: bool = False


class AutomationRuntimeProjectionRepository(Protocol):
    async def mark_running(
        self,
        *,
        identity: AutomationRuntimeIdentity,
        observed_at: datetime,
    ) -> AutomationRuntimeProjection: ...

    async def mark_waiting_human(
        self,
        *,
        identity: AutomationRuntimeIdentity,
        observed_at: datetime,
    ) -> AutomationRuntimeProjection: ...

    async def project_terminal(
        self,
        *,
        identity: AutomationRuntimeIdentity,
        terminal: AutomationRuntimeTerminal,
    ) -> AutomationRuntimeProjection: ...


class AutomationRuntimeProjectionService:
    """Validate structural facts and delegate the transactional CAS projection."""

    def __init__(self, repository: AutomationRuntimeProjectionRepository) -> None:
        super().__init__()
        self._repository = repository

    async def mark_running(
        self,
        *,
        identity: AutomationRuntimeIdentity,
        observed_at: datetime,
    ) -> AutomationRuntimeProjection:
        _validate_identity(identity)
        _validate_timestamp(observed_at)
        return await self._repository.mark_running(identity=identity, observed_at=observed_at)

    async def project_terminal(
        self,
        *,
        identity: AutomationRuntimeIdentity,
        terminal: AutomationRuntimeTerminal,
    ) -> AutomationRuntimeProjection:
        _validate_identity(identity)
        _validate_timestamp(terminal.observed_at)
        if terminal.execution_time_ms < 0:
            raise ValueError("execution_time_ms must be non-negative")
        if terminal.event_count < 0:
            raise ValueError("event_count must be non-negative")
        return await self._repository.project_terminal(identity=identity, terminal=terminal)

    async def mark_waiting_human(
        self,
        *,
        identity: AutomationRuntimeIdentity,
        observed_at: datetime,
    ) -> AutomationRuntimeProjection:
        _validate_identity(identity)
        _validate_timestamp(observed_at)
        return await self._repository.mark_waiting_human(
            identity=identity,
            observed_at=observed_at,
        )


def _validate_identity(identity: AutomationRuntimeIdentity) -> None:
    for field_name in ("tenant_id", "project_id", "runtime_execution_id", "conversation_id"):
        value = getattr(identity, field_name)
        if not value or not value.strip():
            raise ValueError(f"{field_name} must be non-empty")


def _validate_timestamp(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
