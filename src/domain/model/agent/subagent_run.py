"""Domain model for SubAgent run lifecycle."""

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from src.domain.model.agent.announce_config import AnnounceState


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
    frozen_result_text: str | None = None
    frozen_at: datetime | None = None
    trace_id: str | None = None
    parent_span_id: str | None = None
    announce_state: AnnounceState | None = None

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

    def freeze_result(self, result_text: str, now: datetime | None = None) -> "SubAgentRun":
        """Freeze the final result text for durable capture.

        Can only be called on COMPLETED or FAILED runs.
        Once frozen, the result is immutable (calling again raises ValueError).
        """
        if self.status not in {SubAgentRunStatus.COMPLETED, SubAgentRunStatus.FAILED}:
            raise ValueError(
                f"Cannot freeze result in status {self.status.value}; must be completed or failed"
            )
        if self.frozen_result_text is not None:
            raise ValueError("Result is already frozen")
        timestamp = now or datetime.now(UTC)
        return replace(
            self,
            frozen_result_text=result_text,
            frozen_at=timestamp,
        )

    def with_trace_context(
        self,
        trace_id: str,
        parent_span_id: str | None = None,
    ) -> "SubAgentRun":
        """Attach distributed tracing context to this run.

        Can only be called on PENDING runs (before execution starts).
        """
        if self.status is not SubAgentRunStatus.PENDING:
            raise ValueError(
                f"Cannot set trace context in status {self.status.value}; must be pending"
            )
        normalized_trace_id = trace_id.strip()
        if not normalized_trace_id:
            raise ValueError("trace_id cannot be empty")
        normalized_parent_span_id = parent_span_id.strip() if parent_span_id else None
        if normalized_parent_span_id == "":
            normalized_parent_span_id = None
        return replace(
            self,
            trace_id=normalized_trace_id,
            parent_span_id=normalized_parent_span_id,
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
            "frozen_result_text": self.frozen_result_text,
            "frozen_at": self.frozen_at.isoformat() if self.frozen_at else None,
            "trace_id": self.trace_id,
            "parent_span_id": self.parent_span_id,
            "announce_state": self.announce_state.value if self.announce_state else None,
        }
