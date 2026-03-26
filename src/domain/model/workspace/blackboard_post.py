from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from src.domain.shared_kernel import Entity


class BlackboardPostStatus(str, Enum):
    """Post status in workspace blackboard."""

    OPEN = "open"
    ARCHIVED = "archived"


@dataclass(kw_only=True)
class BlackboardPost(Entity):
    """Top-level discussion post in a workspace blackboard."""

    workspace_id: str
    author_id: str
    title: str
    content: str
    status: BlackboardPostStatus = BlackboardPostStatus.OPEN
    is_pinned: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.workspace_id:
            raise ValueError("workspace_id cannot be empty")
        if not self.author_id:
            raise ValueError("author_id cannot be empty")
        if not self.title.strip():
            raise ValueError("title cannot be empty")
