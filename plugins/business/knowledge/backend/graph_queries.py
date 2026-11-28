"""Read the original graph visualization and its provenance within the installed project."""

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

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
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.knowledge.guest.commands import read_graph as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)


async def read_subgraph(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.knowledge.guest.commands import read_subgraph as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)
