"""Read-only entity graph capabilities bound to the invoking project's approved scope."""

from typing import TYPE_CHECKING, Any

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.host.operations.remote_application_commands import application_result
from src.infrastructure.i18n import gettext as _

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext, Progress


class _Query(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _Entities(_Query):
    entity_type: str | None = Field(default=None, max_length=256)
    limit: int = Field(default=20, ge=1, le=200)
    offset: int = Field(default=0, ge=0, le=2147483647)


class _Relationships(_Query):
    entity_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    limit: int = Field(default=50, ge=1, le=200)


async def _read(ctx: "PackageOperationContext", path: str, query: _Query) -> dict[str, Any]:
    if not ctx.scope.project_id or not ctx.scope.tenant_id:
        raise HTTPException(403, _("Project membership is required"))
    params = {
        **query.model_dump(exclude_none=True, exclude={"entity_id"}),
        "project_id": ctx.scope.project_id,
        "tenant_id": ctx.scope.tenant_id,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=ctx.request.app),
        base_url="http://localhost",
        follow_redirects=False,
        trust_env=False,
    ) as client:
        response = await client.get(
            "/api/v1/graph/entities/" + path,
            params=params,
            headers={"authorization": ctx.request.headers.get("authorization", "")},
        )
    if not response.is_success:
        raise HTTPException(response.status_code, _("Failed to read the project graph"))
    return application_result(response.json())


async def list_entities(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    return await _read(ctx, "", _Entities.model_validate(payload))


async def entity_types(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    return await _read(ctx, "types", _Query.model_validate(payload))


async def entity_relationships(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    query = _Relationships.model_validate(payload)
    return await _read(ctx, f"{query.entity_id}/relationships", query)


ENTITY_OPERATIONS = {
    "app.knowledge.entities.list": list_entities,
    "app.knowledge.entities.types": entity_types,
    "app.knowledge.entities.relationships": entity_relationships,
}
