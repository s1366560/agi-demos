"""Workspace Core access for the signed group chat pane."""

from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .collaboration import Identifier

if TYPE_CHECKING:
    from typing import Any

    from src.host.operations.application_commands import PackageOperationContext, Progress


class Read(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: Identifier
    view: Literal["messages", "roster"]


class Send(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: Identifier
    content: str = Field(min_length=1, max_length=16000)
    mentions: list[Identifier] = Field(default_factory=list, max_length=100)
    request_id: UUID


async def read_chat(
    ctx: "PackageOperationContext", payload: dict[str, "Any"], progress: "Progress | None"
) -> dict[str, "Any"]:
    from plugins.business.workspace.guest.commands import read_chat as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)


async def send_chat(
    ctx: "PackageOperationContext", payload: dict[str, "Any"], progress: "Progress | None"
) -> dict[str, "Any"]:
    from plugins.business.workspace.guest.commands import send_chat as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)
