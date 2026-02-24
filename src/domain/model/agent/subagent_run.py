"""Domain model for SubAgent run lifecycle."""

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class SubAgentRunStatus(str, Enum):
    """Execution status for a SubAgent run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True, kw_only=True)
class SubAgentRun:
    """Represents one delegated SubAgent execution run."""

    conversation_id: str
    subagent_name: str
    task: str
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: SubAgentRunStatus = SubAgentRunStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    ended_at: datetime | None = None
    summary: str | None = None
    error: str | None = None
    execution_time_ms: int | None = None
    tokens_used: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.run_id or not self.run_id.strip():
            raise ValueError("run_id cannot be empty")
        if not self.conversation_id or not self.conversation_id.strip():
            raise ValueError("conversation_id cannot be empty")
        if not self.subagent_name or not self.subagent_name.strip():
            raise ValueError("subagent_name cannot be empty")
        if not self.task or not self.task.strip():
            raise ValueError("task cannot be empty")

    def start(self, now: datetime | None = None) -> "SubAgentRun":
        """Mark run as running."""
        if self.status is not SubAgentRunStatus.PENDING:
            raise ValueError(
                f"Invalid status transition: {self.status.value} -> {SubAgentRunStatus.RUNNING.value}"
            )
        timestamp = now or datetime.now(UTC)
        return replace(
            self,
            status=SubAgentRunStatus.RUNNING,
            started_at=timestamp,
            ended_at=None,
            error=None,
        )

    def complete(
        self,
        summary: str | None = None,
        tokens_used: int | None = None,
        execution_time_ms: int | None = None,
        now: datetime | None = None,
    ) -> "SubAgentRun":
        """Mark run as completed."""
        if self.status is not SubAgentRunStatus.RUNNING:
            raise ValueError(
                f"Invalid status transition: {self.status.value} -> {SubAgentRunStatus.COMPLETED.value}"
            )
        timestamp = now or datetime.now(UTC)
        return replace(
            self,
            status=SubAgentRunStatus.COMPLETED,
            ended_at=timestamp,
            summary=summary if summary is not None else self.summary,
            tokens_used=tokens_used if tokens_used is not None else self.tokens_used,
            execution_time_ms=(
                execution_time_ms if execution_time_ms is not None else self.execution_time_ms
            ),
            error=None,
        )

    def fail(
        self,
        error: str,
        execution_time_ms: int | None = None,
        now: datetime | None = None,
    ) -> "SubAgentRun":
        """Mark run as failed."""
        if self.status is not SubAgentRunStatus.RUNNING:
            raise ValueError(
                f"Invalid status transition: {self.status.value} -> {SubAgentRunStatus.FAILED.value}"
            )
        timestamp = now or datetime.now(UTC)
        return replace(
            self,
            status=SubAgentRunStatus.FAILED,
            ended_at=timestamp,
            error=error,
            execution_time_ms=(
                execution_time_ms if execution_time_ms is not None else self.execution_time_ms
            ),
        )

    def cancel(self, reason: str | None = None, now: datetime | None = None) -> "SubAgentRun":
        """Mark run as cancelled."""
        if self.status not in {SubAgentRunStatus.PENDING, SubAgentRunStatus.RUNNING}:
            raise ValueError(
                f"Invalid status transition: {self.status.value} -> {SubAgentRunStatus.CANCELLED.value}"
            )
        timestamp = now or datetime.now(UTC)
        return replace(
            self,
            status=SubAgentRunStatus.CANCELLED,
            ended_at=timestamp,
            error=reason if reason else self.error,
        )

    def time_out(
        self, reason: str = "SubAgent execution timed out", now: datetime | None = None
    ) -> "SubAgentRun":
        """Mark run as timed out."""
        if self.status not in {SubAgentRunStatus.PENDING, SubAgentRunStatus.RUNNING}:
            raise ValueError(
                f"Invalid status transition: {self.status.value} -> {SubAgentRunStatus.TIMED_OUT.value}"
            )
        timestamp = now or datetime.now(UTC)
        return replace(
            self,
            status=SubAgentRunStatus.TIMED_OUT,
            ended_at=timestamp,
            error=reason,
        )

    def to_event_data(self) -> dict[str, Any]:
        """Serialize to stream-friendly event payload."""
        return {
            "run_id": self.run_id,
            "conversation_id": self.conversation_id,
            "subagent_name": self.subagent_name,
            "task": self.task,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "summary": self.summary,
            "error": self.error,
            "execution_time_ms": self.execution_time_ms,
            "tokens_used": self.tokens_used,
            "metadata": dict(self.metadata),
        }
