from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from src.domain.shared_kernel import Entity


class TaskLogStatus(str, Enum):
    """Status of a background task."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


@dataclass(kw_only=True)
class TaskLog(Entity):
    """Task Log domain entity for tracking background tasks"""

    group_id: str
    task_type: str
    status: TaskLogStatus
    payload: dict[str, Any] = field(default_factory=dict)
    entity_id: str | None = None
    entity_type: str | None = None
    parent_task_id: str | None = None
    worker_id: str | None = None
    retry_count: int = 0
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    stopped_at: datetime | None = None
