"""Project context shown by the signed workbench."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from plugins.business.agent.backend.chat_operations import (
    ConversationInput,
    _canonical,
    _Input,
    _own_conversation,
    visible_skills,
)
from plugins.business.agent.backend.lifecycle_control import snapshot
from plugins.business.agent.guest.binding import CommandContext, Progress, current


class Context(_Input):
    view: Literal["stats", "trending", "recent-skills", "templates", "commands", "lifecycle"]
    limit: int | None = Field(default=None, ge=1, le=20)


class ConversationView(ConversationInput):
    view: Literal["tasks", "context-window"]


async def _conversation_view(ctx: CommandContext, item: ConversationView) -> dict[str, Any]:
    await _own_conversation(ctx, item.conversation_id)
    if item.view == "context-window":
        return await _canonical(ctx, "GET", f"conversations/{item.conversation_id}/context-status")
    result = await _canonical(ctx, "GET", f"plan/tasks/{item.conversation_id}")
    return {"tasks": result["tasks"], "total_count": result["total_count"]}


async def project_context(
    ctx: CommandContext, payload: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    if payload.get("view") in ("tasks", "context-window"):
        return await _conversation_view(ctx, ConversationView.model_validate(payload))
    query = Context.model_validate(payload)
    if query.view == "lifecycle":
        return await snapshot(ctx)
    if query.view == "commands":
        commands = await _canonical(ctx, "GET", "commands")
        skills = await visible_skills(ctx, limit=query.limit or 50)
        return {
            "commands": [
                {key: item[key] for key in ("name", "description", "category")}
                for item in commands["commands"]
            ],
            "skills": skills,
        }
    if query.view == "templates":
        return {"templates": await current().templates(query.limit or 50)}
    result = await _canonical(
        ctx,
        "GET",
        query.view,
        project_route=True,
        query={"limit": query.limit} if query.limit else None,
    )
    if query.view == "stats":
        return {
            key: result[key]
            for key in (
                "memory_count",
                "conversation_count",
                "node_count",
                "member_count",
                "active_nodes",
                "storage_used",
                "storage_limit",
            )
        }
    key = "entities" if query.view == "trending" else "skills"
    return {key: result[key]}
