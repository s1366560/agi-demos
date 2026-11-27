"""Scoped workbench queries reuse the original memory API and its object authorization."""

from typing import TYPE_CHECKING, Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.host.operations.remote_application_commands import application_result
from src.infrastructure.i18n import gettext as _

from .package_memory_editor import MemoryId

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext


class MemoryPageQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    page: int = Field(ge=1, le=2147483647)
    page_size: int = Field(default=20, ge=1, le=100)
    search: str = Field(default="", max_length=200)
    content_type: Literal["text", "document", "image", "video"] | None = None


class MemoryDetailQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: MemoryId
    detail: Literal[True]


async def query_memory_workbench(
    ctx: "PackageOperationContext", payload: dict[str, Any]
) -> dict[str, Any]:
    project = ctx.scope.project_id
    if not project or not ctx.scope.tenant_id:
        raise HTTPException(403, _("Project membership is required"))
    params: dict[str, Any] = {"project_id": project}
    if "detail" in payload:
        detail = MemoryDetailQuery.model_validate(payload)
        path = f"/api/v1/memories/{detail.id}"
    else:
        params.update(MemoryPageQuery.model_validate(payload).model_dump(exclude_none=True))
        path = "/api/v1/memories/"
    from src.host.operations.admitted_loopback import admitted_client

    async with admitted_client(ctx) as api:
        result = await api.get(path, params=params)
    if not result.is_success:
        raise HTTPException(result.status_code, _("Memory operation failed"))
    data = application_result(result.json())
    rows = [data] if "detail" in payload else data["memories"]
    if any(item["project_id"] != project for item in rows):
        raise HTTPException(502, _("Memory response scope mismatch"))
    if "page" in payload:
        data["actor_id"] = ctx.user.id
        if data.get("command_capabilities") is None:
            data["command_capabilities"] = await _legacy_commands(ctx, rows)
    return data


async def _legacy_commands(
    ctx: "PackageOperationContext", rows: list[dict[str, Any]]
) -> dict[str, Any] | None:
    from sqlalchemy import select

    from src.infrastructure.adapters.primary.web.routers.memories import (
        _check_memory_edit_permission,
        _get_memory_write_project,
        _has_project_admin_access,
    )
    from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
        KnowledgeSyncEnrollmentModel,
    )
    from src.infrastructure.adapters.secondary.persistence.models import Memory

    project_id = ctx.scope.project_id
    enrollment = await ctx.db.scalar(
        select(KnowledgeSyncEnrollmentModel).where(
            KnowledgeSyncEnrollmentModel.project_id == project_id,
            KnowledgeSyncEnrollmentModel.tenant_id == ctx.scope.tenant_id,
        )
    )
    if enrollment is None or enrollment.enabled:
        return None
    try:
        await _get_memory_write_project(project_id, ctx.user, ctx.db)
    except HTTPException as err:
        if err.status_code not in (403, 404):
            raise
        return None
    objects = []
    revisions = {row["id"]: row["version"] for row in rows}
    records = await ctx.db.scalars(
        select(Memory).where(
            Memory.project_id == project_id,
            Memory.id.in_(revisions),
        )
    )
    for record in records:
        if revisions.get(record.id) != record.version:
            continue
        actions = []
        try:
            await _check_memory_edit_permission(record, ctx.user, ctx.db)
            actions.append("update")
        except HTTPException as err:
            if err.status_code != 403:
                raise
        if record.author_id == ctx.user.id or await _has_project_admin_access(
            record, ctx.user, ctx.db
        ):
            actions.append("delete")
        objects.append(
            {"memory_id": record.id, "revision": record.version, "allowed_actions": actions}
        )
    return {
        "protocol_version": 1,
        "actor_id": ctx.user.id,
        "tenant_id": ctx.scope.tenant_id,
        "project_id": project_id,
        "allowed_actions": ["create"],
        "objects": objects,
    }
