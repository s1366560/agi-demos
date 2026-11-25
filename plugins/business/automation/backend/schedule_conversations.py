"""Project conversation choices available to the signed schedule editor."""

from typing import TYPE_CHECKING, Any

from fastapi import HTTPException
from sqlalchemy import select

from src.infrastructure.adapters.secondary.persistence.models import Conversation
from src.infrastructure.i18n import gettext as _

if TYPE_CHECKING:
    from sqlalchemy import Select

    from src.host.operations.application_commands import PackageOperationContext, Progress


def _choices(ctx: "PackageOperationContext") -> "Select[tuple[str, str, str | None]]":
    return select(Conversation.id, Conversation.title, Conversation.workspace_id).where(
        Conversation.tenant_id == ctx.scope.tenant_id,
        Conversation.project_id == ctx.scope.project_id,
        Conversation.user_id == ctx.user.id,
        Conversation.workspace_id.is_not(None),
    )


async def require_schedule_conversation(ctx: "PackageOperationContext", conversation: str) -> None:
    selected = await ctx.db.scalar(_choices(ctx).where(Conversation.id == conversation))
    if selected is None:
        raise HTTPException(403, _("Conversation is unavailable in this project"))


async def schedule_conversations(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    if payload:
        raise HTTPException(422, _("Unexpected schedule conversation filter"))
    rows = await ctx.db.execute(
        _choices(ctx).order_by(Conversation.updated_at.desc(), Conversation.id)
    )
    return {
        "items": [
            {"id": row.id, "title": row.title, "workspaceId": row.workspace_id} for row in rows
        ]
    }
