"""Read the projections used by the board from each owning application's scoped API."""

from typing import TYPE_CHECKING, Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.infrastructure.i18n import gettext as _

from .workspace_directory_export import read_workspace_operation

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext


class CatalogSearch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=50)
    search: str = Field(default="", max_length=250)


class RosterPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)


async def read_projection(
    ctx: "PackageOperationContext", workspace: str, resource: str, query: dict[str, str]
) -> dict[str, Any]:
    await read_workspace_operation(ctx, {"workspace_id": workspace}, None)
    if resource == "published-genes":
        path = "/api/v1/genes/"
        params = {
            **CatalogSearch.model_validate(query).model_dump(),
            "is_published": True,
            "tenant_id": ctx.scope.tenant_id,
        }
    else:
        path = "/api/v1/agent/conversations"
        params = {
            **RosterPage.model_validate(query).model_dump(),
            "workspace_id": workspace,
            "project_id": ctx.scope.project_id,
            "status": "active",
        }
    from src.host.operations.admitted_loopback import admitted_client

    async with admitted_client(ctx) as api:
        result = await api.get(
            path,
            params=params,
            headers={"X-Tenant-ID": str(ctx.scope.tenant_id)},
        )
    if not result.is_success:
        raise HTTPException(result.status_code, _("Workspace projection is unavailable"))
    data = result.json()
    if resource == "board-conversations":
        items = [
            {
                key: row.get(key)
                for key in (
                    "id",
                    "title",
                    "created_at",
                    "updated_at",
                    "workspace_id",
                    "conversation_mode",
                )
            }
            for row in data["items"]
            if row.get("workspace_id") == workspace
        ]
        data = {
            "items": items,
            "has_more": data["has_more"],
            "next_offset": data.get("next_offset"),
        }
    return {"data": data, "status": 200, "headers": {}}
