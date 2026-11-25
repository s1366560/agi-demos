"""Workspace Core access for the signed group chat pane."""

import asyncio
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.infrastructure.i18n import gettext as _

from .blackboard_surface import change_surface, read_surface
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
    ctx: "PackageOperationContext", payload: dict[str, "Any"], _progress: "Progress | None"
) -> dict[str, "Any"]:
    args = Read.model_validate(payload)

    async def rows(resource: str) -> list[dict[str, "Any"]]:
        result = await read_surface(
            ctx, {"workspace_id": args.workspace_id, "resource": resource}, None
        )
        data = result["data"]
        items = (
            data
            if isinstance(data, list)
            else data.get("items", data.get(resource))
            if isinstance(data, dict)
            else None
        )
        if not isinstance(items, list) or any(
            not isinstance(row, dict) or row.get("workspace_id") != args.workspace_id
            for row in items
        ):
            raise HTTPException(502, _("Invalid workspace collaboration response"))
        return items

    if args.view == "messages":
        return {"messages": await rows("messages"), "principal_id": ctx.user.id}
    members, agents = await asyncio.gather(rows("members"), rows("agents"))
    return {"members": members, "agents": agents}


async def send_chat(
    ctx: "PackageOperationContext", payload: dict[str, "Any"], _progress: "Progress | None"
) -> dict[str, "Any"]:
    args = Send.model_validate(payload)
    authority = await read_surface(
        ctx, {"workspace_id": args.workspace_id, "resource": "collaboration/authority"}, None
    )
    result = await change_surface(
        ctx,
        {
            "workspace_id": args.workspace_id,
            "resource": "messages",
            "method": "POST",
            "revision": authority["data"]["revision"],
            "request_id": str(args.request_id),
            "fields": {"content": args.content, "mentions": args.mentions, "sender_type": "human"},
        },
        None,
    )
    return {"message": result["data"]}
