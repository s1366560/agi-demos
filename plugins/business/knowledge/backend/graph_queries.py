"""Read the original graph visualization and its provenance within the installed project."""

from typing import TYPE_CHECKING, Annotated, Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.host.operations.remote_application_commands import application_result
from src.infrastructure.i18n import gettext as _

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext, Progress


class GraphRead(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    limit: int = Field(default=100, ge=1, le=1000)


class SubgraphRead(GraphRead):
    node_uuids: list[Annotated[str, Field(min_length=1, max_length=256)]] = Field(
        min_length=1, max_length=500
    )
    include_neighbors: bool = False


async def read_graph(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    return await _project_graph(ctx, GraphRead.model_validate(payload))


async def read_subgraph(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    return await _project_graph(ctx, SubgraphRead.model_validate(payload))


async def _project_graph(ctx: "PackageOperationContext", query: GraphRead) -> dict[str, Any]:
    if not ctx.scope.project_id or not ctx.scope.tenant_id:
        raise HTTPException(403, _("Project membership is required"))
    data = {
        **query.model_dump(),
        "tenant_id": ctx.scope.tenant_id,
        "project_id": ctx.scope.project_id,
    }
    from src.host.operations.admitted_loopback import admitted_client

    async with admitted_client(ctx) as client:
        if isinstance(query, SubgraphRead):
            response = await client.post("/api/v1/graph/memory/graph/subgraph", json=data)
        else:
            response = await client.get("/api/v1/graph/memory/graph", params=data)
    if not response.is_success:
        raise HTTPException(response.status_code, _("Failed to read the project graph"))
    return application_result(response.json())
