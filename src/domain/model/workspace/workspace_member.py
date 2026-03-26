from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.domain.model.workspace.workspace_role import WorkspaceRole
from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class WorkspaceMember(Entity):
    """Membership of a user in a workspace."""

    workspace_id: str
    user_id: str
    role: WorkspaceRole = WorkspaceRole.VIEWER
    invited_by: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.workspace_id:
            raise ValueError("workspace_id cannot be empty")
        if not self.user_id:
            raise ValueError("user_id cannot be empty")
