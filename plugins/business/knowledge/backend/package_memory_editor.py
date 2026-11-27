"""Read project memory details and route writes through the canonical memory mutation path."""

from typing import TYPE_CHECKING, Annotated, Any, Self
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from src.infrastructure.adapters.secondary.persistence.models import Memory
from src.infrastructure.i18n import gettext as _

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext, Progress

MemoryId = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,128}$")]


class MemorySelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: MemoryId


class _Edit(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    id: MemoryId | None = None
    version: int = Field(ge=0, le=2147483647)
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=32768)
    tags: list[str] | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] | None = None
    change_id: str = Field(min_length=36, max_length=36)

    @model_validator(mode="after")
    def validate_revision(self) -> Self:
        UUID(self.change_id)
        if (self.id is None) != (self.version == 0):
            raise ValueError(
                "New memories require revision zero and existing memories require their current revision"
            )
        return self


async def _require_memory(ctx: "PackageOperationContext", memory_id: str) -> Memory:
    row = await ctx.db.scalar(
        select(Memory).where(Memory.project_id == ctx.scope.project_id, Memory.id == memory_id)
    )
    if row is None:
        raise HTTPException(404, _("Memory not found"))
    return row


async def raw_memory_record(ctx: "PackageOperationContext", memory_id: str) -> dict[str, Any]:
    memory = await _require_memory(ctx, memory_id)
    return {
        "id": memory.id,
        "title": memory.title,
        "content": memory.content,
        "version": memory.version,
        "tags": memory.tags,
        "processing_status": memory.processing_status,
        "author_id": memory.author_id,
        "project_id": memory.project_id,
    }


async def save_memory(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.knowledge.guest.commands import save_memory as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)
