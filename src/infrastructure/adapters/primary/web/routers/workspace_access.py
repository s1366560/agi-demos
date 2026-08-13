"""Fail-closed compatibility guard for Core-proxied Workspace routers."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.workspace_authority import (
    workspace_core_unavailable_error,
)
from src.infrastructure.adapters.secondary.persistence.models import User as DBUser


async def require_workspace_access(
    db: AsyncSession,
    current_user: DBUser,
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    *,
    require_editor: bool = False,
) -> None:
    """Reject direct execution because public callers must use the Core proxy."""
    del db, current_user, tenant_id, project_id, workspace_id, require_editor
    raise workspace_core_unavailable_error()
