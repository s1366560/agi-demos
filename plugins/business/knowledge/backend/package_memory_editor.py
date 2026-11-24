"""Read project memory details and route writes through the canonical memory mutation path."""

from typing import TYPE_CHECKING, Annotated, Any, Self
from uuid import UUID

import httpx
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


async def read_memory(ctx: "PackageOperationContext", payload: dict[str, Any]) -> dict[str, Any]:
    memory = await _require_memory(ctx, MemorySelection.model_validate(payload).id)
    return {
        "id": memory.id,
        "title": memory.title,
        "content": memory.content,
        "version": memory.version,
        "tags": memory.tags,
        "processing_status": memory.processing_status,
    }


async def save_memory(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    edit = _Edit.model_validate(payload)
    scope = {"tenant_id": ctx.scope.tenant_id, "project_id": ctx.scope.project_id}
    body: dict[str, Any] = {"title": edit.title, "content": edit.content}
    if edit.id:
        await _require_memory(ctx, edit.id)
        body["version"] = edit.version
        method, path = "PATCH", f"/api/v1/memories/{edit.id}"
    else:
        body["project_id"] = ctx.scope.project_id
        method, path = "POST", "/api/v1/memories/"
    headers = {"Authorization": ctx.request.headers.get("Authorization", "")}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=ctx.request.app),
        base_url="http://localhost",
        trust_env=False,
        follow_redirects=False,
    ) as api:
        response = await api.request(method, path, params=scope, json=body, headers=headers)
        if response.status_code == 428:
            # The enrolled path rejects its first request before touching memory data.
            headers.update(
                {"Idempotency-Key": edit.change_id, "X-Memory-Expected-Revision": str(edit.version)}
            )
            response = await api.request(method, path, params=scope, json=body, headers=headers)
    if not response.is_success:
        if response.status_code == 409:
            raise HTTPException(409, _("Memory changed. Reload before editing again."))
        raise HTTPException(response.status_code, _("Memory operation failed"))
    result = response.json()
    if result["project_id"] != ctx.scope.project_id:
        raise HTTPException(502, _("Memory response scope mismatch"))
    return {
        key: result[key]
        for key in ("id", "title", "content", "version", "tags", "processing_status")
    }
