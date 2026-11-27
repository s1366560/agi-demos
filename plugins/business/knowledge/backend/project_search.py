"""Run the original search modes under the signed operation's project scope."""

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext, Progress


class Search(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mode: Literal["advanced", "graph-traversal", "community", "temporal", "faceted"]
    parameters: dict[str, Any]


async def search(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.knowledge.guest.commands import search as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)
