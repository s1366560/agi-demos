"""Scoped workbench queries reuse the original memory API and its object authorization."""

from typing import TYPE_CHECKING, Any, Literal

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

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
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=ctx.request.app),
        base_url="http://localhost",
        trust_env=False,
    ) as api:
        result = await api.get(
            path,
            params=params,
            headers={
                "Authorization": ctx.request.headers.get("Authorization", ""),
            },
        )
    if not result.is_success:
        raise HTTPException(result.status_code, _("Memory operation failed"))
    data = result.json()
    rows = [data] if "detail" in payload else data["memories"]
    if any(item["project_id"] != project for item in rows):
        raise HTTPException(502, _("Memory response scope mismatch"))
    if "page" in payload:
        data["actor_id"] = ctx.user.id
    return data
