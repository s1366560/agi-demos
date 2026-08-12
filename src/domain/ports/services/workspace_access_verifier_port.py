"""Port for checking Workspace membership at event-delivery boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, kw_only=True)
class WorkspaceAccessRequest:
    """Tenant-bound identity correlation for one Workspace access check."""

    tenant_id: str
    user_id: str
    workspace_id: str


class WorkspaceAccessVerifier(Protocol):
    """Verify current access against the selected Workspace authority."""

    async def has_access(self, request: WorkspaceAccessRequest) -> bool:
        """Return whether the correlated user is still a Workspace member."""
        ...
