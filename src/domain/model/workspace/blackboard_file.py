from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class BlackboardFile(Entity):
    """Shared file in a workspace blackboard."""

    workspace_id: str
    parent_path: str = "/"
    name: str
    is_directory: bool = False
    file_size: int = 0
    content_type: str = ""
    storage_key: str = ""
    uploader_type: str  # "user" or "agent"
    uploader_id: str
    uploader_name: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.workspace_id:
            raise ValueError("workspace_id cannot be empty")
        if not self.name.strip():
            raise ValueError("name cannot be empty")
        if not self.uploader_id:
            raise ValueError("uploader_id cannot be empty")
