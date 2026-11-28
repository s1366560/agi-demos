"""Named memory maintenance operations with project and object authorization."""

from typing import TYPE_CHECKING, Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.infrastructure.i18n import gettext as _

from .package_memory_editor import MemorySelection

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext, Progress


class DeleteMemory(MemorySelection):
    version: int = Field(ge=1, le=2147483647)
    change_id: str = Field(min_length=36, max_length=36)


async def task_is_visible(ctx: "PackageOperationContext", task_id: str) -> None:
    from sqlalchemy import select

    from src.infrastructure.adapters.secondary.persistence.models import TaskLog

    found = await ctx.db.scalar(
        select(TaskLog.id).where(
            TaskLog.id == task_id,
            TaskLog.group_id == ctx.scope.project_id,
            TaskLog.task_type == "add_episode",
        )
    )
    if not found:
        raise HTTPException(404, _("Task not found"))


async def delete_memory(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.knowledge.guest.commands import delete_memory as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)


async def reindex_memory(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.knowledge.guest.commands import reindex_memory as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)


async def read_index_task(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.knowledge.guest.commands import read_index_task as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)


class OptimizeContent(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    content: str = Field(min_length=1, max_length=32768)


async def optimize_content(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.knowledge.guest.commands import optimize_content as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)
