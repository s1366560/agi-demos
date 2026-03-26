from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from src.domain.shared_kernel import Entity


class CyberObjectiveType(str, Enum):
    OBJECTIVE = "objective"
    KEY_RESULT = "key_result"


@dataclass(kw_only=True)
class CyberObjective(Entity):
    workspace_id: str
    title: str
    description: str | None = None
    obj_type: CyberObjectiveType = CyberObjectiveType.OBJECTIVE
    parent_id: str | None = None
    progress: float = 0.0
    created_by: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.workspace_id:
            raise ValueError("workspace_id cannot be empty")
        if not self.title.strip():
            raise ValueError("title cannot be empty")
        if self.progress < 0.0 or self.progress > 1.0:
            raise ValueError("progress must be between 0.0 and 1.0")
        if self.obj_type == CyberObjectiveType.KEY_RESULT and not self.parent_id:
            raise ValueError("key_result must have a parent_id")
