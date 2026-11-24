"""Vouch a current project membership to Workspace Core when creating a workspace."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import UserProject


async def project_membership_header(
    db: AsyncSession, user_id: str, project_id: str
) -> tuple[str, str] | None:
    result = await db.execute(
        refresh_select_statement(
            select(UserProject.role).where(
                UserProject.user_id == user_id, UserProject.project_id == project_id
            )
        )
    )
    role = result.scalar_one_or_none()
    if role is None:
        return None
    known = {"owner", "admin", "editor", "member", "viewer"}
    return "x-memstack-project-membership-role", role if role in known else "member"
