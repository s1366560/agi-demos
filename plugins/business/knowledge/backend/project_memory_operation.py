"""Project-scoped directory over the existing persistent memory application."""

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from src.application.use_cases.memory.list_memories import ListMemoriesQuery, ListMemoriesUseCase
from src.infrastructure.adapters.secondary.persistence.sql_memory_repository import (
    SqlMemoryRepository,
)

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext, Progress


class _Search(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    search: str = Field(default="", max_length=200)
    offset: int = Field(default=0, ge=0, le=2_147_483_647)
    limit: int = Field(default=20, ge=1, le=50)


async def raw_memory_rows(ctx: "PackageOperationContext", params: dict[str, Any]) -> dict[str, Any]:
    """Return full memory rows. The guest projects excerpts and drops scope fields."""
    query = _Search.model_validate(params)
    rows = await ListMemoriesUseCase(SqlMemoryRepository(ctx.db)).execute(
        ListMemoriesQuery(
            project_id=ctx.scope.project_id,
            search=query.search,
            offset=query.offset,
            limit=query.limit + 1,
        )
    )
    return {
        "rows": [
            {
                "id": row.id,
                "title": row.title,
                "content": row.content,
                "content_type": row.content_type,
                "project_id": ctx.scope.project_id,
            }
            for row in rows
        ]
    }


async def list_project_memories(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    """Use the authenticated package invocation's project as the only data scope."""
    from plugins.business.knowledge.guest.commands import list_project_memories as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)
