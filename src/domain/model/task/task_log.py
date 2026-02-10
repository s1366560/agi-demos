from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class TaskLog(Entity):
    """Task Log domain entity for tracking background tasks"""

    group_id: str
    task_type: str
    status: str  # PENDING, PROCESSING, COMPLETED, FAILED
    payload: Dict[str, Any] = field(default_factory=dict)
    entity_id: Optional[str] = None
    entity_type: Optional[str] = None
    parent_task_id: Optional[str] = None
    worker_id: Optional[str] = None
    retry_count: int = 0
    error_message: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
