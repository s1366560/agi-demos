"""Read cloud-owned conversation identity and placement for native P4/P5 clients."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.host.identity.project_package_scope import visible_projects
from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentRunAuthorityModel,
    Conversation,
    Project,
    User,
)
from src.infrastructure.i18n import gettext as _

router = APIRouter()
Db = Annotated[AsyncSession, Depends(get_db)]
Actor = Annotated[User, Depends(get_current_user)]
ProjectId = Annotated[str, Query(min_length=1, max_length=128)]
HistoryLimit = Annotated[int, Query(ge=1, le=500)]
HistoryOffset = Annotated[int, Query(ge=0)]


async def _items(
    db: AsyncSession,
    user: User,
    project_id: str,
    limit: int,
    offset: int,
    conversation_id: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    project = await db.scalar(visible_projects(user).where(Project.id == project_id))
    if project is None:
        raise HTTPException(403, _("Agent run access denied"))
    scoped = select(Conversation).where(
        Conversation.user_id == user.id,
        Conversation.project_id == project.id,
        Conversation.tenant_id == project.tenant_id,
    )
    if conversation_id is not None:
        scoped = scoped.where(Conversation.id == conversation_id)
    latest = (
        select(AgentRunAuthorityModel.id)
        .where(
            AgentRunAuthorityModel.conversation_id == Conversation.id,
            AgentRunAuthorityModel.tenant_id == project.tenant_id,
            AgentRunAuthorityModel.project_id == project.id,
        )
        .order_by(AgentRunAuthorityModel.created_at.desc(), AgentRunAuthorityModel.id.desc())
        .limit(1)
        .correlate(Conversation)
        .scalar_subquery()
    )
    query = scoped.add_columns(AgentRunAuthorityModel).outerjoin(
        AgentRunAuthorityModel, AgentRunAuthorityModel.id == latest
    )
    rows = await db.execute(
        query.order_by(Conversation.created_at.desc(), Conversation.id.desc())
        .offset(offset)
        .limit(limit)
    )
    items = [
        {
            "id": row.id,
            "project_id": row.project_id,
            "tenant_id": row.tenant_id,
            "user_id": row.user_id,
            "title": row.title,
            "status": row.status,
            "message_count": row.message_count,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "execution_target": run.execution_target
            if run
            else ("local" if row.meta and row.meta.get("execution_target") == "local" else "cloud"),
            "execution_machine_id": run.execution_machine_id if run else None,
            "execution_environment_id": run.execution_environment_id if run else None,
            "local_root_label": run.local_root_label if run else None,
            "workspace_id": row.workspace_id,
        }
        for row, run in rows
    ]
    total = (
        await db.scalar(select(func.count()).select_from(scoped.subquery()))
        if conversation_id is None
        else len(items)
    )
    return items, total or 0


@router.get("/conversations/{conversation_id}")
async def detail(
    conversation_id: str, project_id: ProjectId, db: Db, user: Actor
) -> dict[str, Any]:
    items, _total = await _items(db, user, project_id, 1, 0, conversation_id)
    if not items:
        raise HTTPException(404, _("Conversation not found"))
    return items[0]


@router.get("/conversations")
async def history(
    project_id: ProjectId, db: Db, user: Actor, limit: HistoryLimit = 50, offset: HistoryOffset = 0
) -> dict[str, Any]:
    items, total = await _items(db, user, project_id, limit, offset)
    end = offset + len(items)
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": end < total,
        "next_offset": end if end < total else None,
    }
