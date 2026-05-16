"""Shared workspace access checks for path-scoped workspace routers."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    User as DBUser,
    WorkspaceMemberModel,
    WorkspaceModel,
)
from src.infrastructure.i18n import gettext as _

_EDITOR_ROLES = {"owner", "editor", "admin"}


async def require_workspace_access(
    db: AsyncSession,
    current_user: DBUser,
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    *,
    require_editor: bool = False,
) -> None:
    """Require the requested workspace to match the path scope and caller membership."""
    workspace = (
        await db.execute(
            refresh_select_statement(
                select(WorkspaceModel.id).where(
                    WorkspaceModel.id == workspace_id,
                    WorkspaceModel.tenant_id == tenant_id,
                    WorkspaceModel.project_id == project_id,
                )
            )
        )
    ).scalar_one_or_none()
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Workspace not found"),
        )

    if getattr(current_user, "is_superuser", False):
        return

    role = (
        await db.execute(
            refresh_select_statement(
                select(WorkspaceMemberModel.role).where(
                    WorkspaceMemberModel.workspace_id == workspace_id,
                    WorkspaceMemberModel.user_id == current_user.id,
                )
            )
        )
    ).scalar_one_or_none()
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Workspace access required"),
        )
    if require_editor and str(role) not in _EDITOR_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Workspace editor access required"),
        )
