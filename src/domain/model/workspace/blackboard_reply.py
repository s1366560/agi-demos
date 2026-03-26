from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class BlackboardReply(Entity):
    """Reply item for a workspace blackboard post."""

    post_id: str
    workspace_id: str
    author_id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.post_id:
            raise ValueError("post_id cannot be empty")
        if not self.workspace_id:
            raise ValueError("workspace_id cannot be empty")
        if not self.author_id:
            raise ValueError("author_id cannot be empty")
        if not self.content.strip():
            raise ValueError("content cannot be empty")
