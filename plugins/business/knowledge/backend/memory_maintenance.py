"""Named memory maintenance operations with project and object authorization."""

from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.host.operations.remote_application_commands import application_result
from src.infrastructure.i18n import gettext as _

from .package_memory_editor import MemorySelection, _require_memory

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext, Progress


class DeleteMemory(MemorySelection):
    version: int = Field(ge=1, le=2147483647)
    change_id: str = Field(min_length=36, max_length=36)


async def delete_memory(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    args = DeleteMemory.model_validate(payload)
    UUID(args.change_id)
    path = f"/api/v1/memories/{args.id}"
    query: dict[str, str | int] = {"project_id": ctx.scope.project_id, "version": args.version}
    from src.host.operations.admitted_loopback import admitted_client

    headers: dict[str, str] = {}
    async with admitted_client(ctx) as api:
        response = await api.delete(path, params=query, headers=headers)
        if response.status_code == 428:
            headers.update(
                {"Idempotency-Key": args.change_id, "X-Memory-Expected-Revision": str(args.version)}
            )
            response = await api.delete(path, params=query, headers=headers)
    if not response.is_success:
        raise HTTPException(response.status_code, _("Memory operation failed"))
    return {"memoryId": args.id, "deleted": True}


async def reindex_memory(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    args = MemorySelection.model_validate(payload)
    await _require_memory(ctx, args.id)
    from src.host.operations.admitted_loopback import admitted_client

    async with admitted_client(ctx) as api:
        response = await api.post(f"/api/v1/memories/{args.id}/reprocess")
    if not response.is_success:
        raise HTTPException(response.status_code, _("Memory operation failed"))
    result = application_result(response.json())
    if result["project_id"] != ctx.scope.project_id:
        raise HTTPException(502, _("Memory response scope mismatch"))
    return result


async def read_index_task(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    from sqlalchemy import select

    from src.infrastructure.adapters.secondary.persistence.models import TaskLog

    task_id = MemorySelection.model_validate(payload).id
    found = await ctx.db.scalar(
        select(TaskLog.id).where(
            TaskLog.id == task_id,
            TaskLog.group_id == ctx.scope.project_id,
            TaskLog.task_type == "add_episode",
        )
    )
    if not found:
        raise HTTPException(404, _("Task not found"))
    from src.host.operations.admitted_loopback import admitted_client

    async with admitted_client(ctx) as api:
        response = await api.get(f"/api/v1/tasks/{task_id}")
    if not response.is_success:
        raise HTTPException(response.status_code, _("Task read failed"))
    data = response.json()
    return {key: data.get(key) for key in ("id", "status", "message", "progress", "error")}


class OptimizeContent(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    content: str = Field(min_length=1, max_length=32768)


async def optimize_content(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    body = OptimizeContent.model_validate(payload)
    from src.host.operations.admitted_loopback import admitted_client

    async with admitted_client(ctx) as api:
        response = await api.post(
            "/api/v1/ai/optimize",
            json=body.model_dump(),
            headers={"X-Tenant-ID": str(ctx.scope.tenant_id)},
        )
    if not response.is_success:
        raise HTTPException(response.status_code, _("Memory operation failed"))
    return {"content": response.json()["content"]}
