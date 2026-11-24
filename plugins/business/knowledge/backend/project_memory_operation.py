"""Project-scoped directory over the existing persistent memory application."""

from typing import TYPE_CHECKING, Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.application.use_cases.memory.list_memories import ListMemoriesQuery, ListMemoriesUseCase
from src.infrastructure.adapters.secondary.persistence.sql_memory_repository import (
    SqlMemoryRepository,
)
from src.infrastructure.i18n import gettext as _

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext, Progress


class _Search(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    search: str = Field(default="", max_length=200)
    offset: int = Field(default=0, ge=0, le=2_147_483_647)
    limit: int = Field(default=20, ge=1, le=50)


async def list_project_memories(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    """Use the authenticated package invocation's project as the only data scope."""
    if not ctx.scope.project_id or not ctx.scope.tenant_id:
        raise HTTPException(403, _("Project membership is required"))
    if "id" in payload:
        from plugins.business.knowledge.backend.package_memory_editor import read_memory

        return await read_memory(ctx, payload)
    query = _Search.model_validate(payload)
    rows = await ListMemoriesUseCase(SqlMemoryRepository(ctx.db)).execute(
        ListMemoriesQuery(
            project_id=ctx.scope.project_id,
            search=query.search,
            offset=query.offset,
            limit=query.limit + 1,
        )
    )
    return {
        "items": [
            {
                "id": row.id,
                "title": row.title,
                "excerpt": row.content[:320],
                "content_type": row.content_type,
            }
            for row in rows[: query.limit]
        ],
        "has_more": len(rows) > query.limit,
    }
