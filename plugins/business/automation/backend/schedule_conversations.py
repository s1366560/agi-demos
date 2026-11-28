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


async def raw_schedule_conversations(ctx: "PackageOperationContext") -> dict[str, Any]:
    rows = await ctx.db.execute(
        _choices(ctx).order_by(Conversation.updated_at.desc(), Conversation.id)
    )
    return {
        "rows": [
            {
                "id": row.id,
                "title": row.title,
                "workspace_id": row.workspace_id,
                "updated_at": None,
            }
            for row in rows
        ]
    }


async def schedule_conversations(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.automation.guest.commands import schedule_conversations as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)
