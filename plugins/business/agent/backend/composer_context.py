"""Project and conversation context shown in the signed Agent workbench."""

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from src.infrastructure.adapters.primary.web.routers.agent.templates import list_templates

from .chat_operations import (
    ConversationInput,
    _canonical,
    _Input,
    _own_conversation,
    visible_skills,
)
from .lifecycle_control import snapshot

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext, Progress


class Context(_Input):
    view: Literal["stats", "trending", "recent-skills", "templates", "commands", "lifecycle"]
    limit: int | None = Field(default=None, ge=1, le=20)


class ConversationView(ConversationInput):
    view: Literal["tasks", "context-window"]


async def _conversation_view(
    ctx: "PackageOperationContext", item: ConversationView
) -> dict[str, Any]:
    await _own_conversation(ctx, item.conversation_id)
    if item.view == "context-window":
        return await _canonical(ctx, "GET", f"conversations/{item.conversation_id}/context-status")
    result = await _canonical(ctx, "GET", f"plan/tasks/{item.conversation_id}")
    return {"tasks": result["tasks"], "total_count": result["total_count"]}


async def project_context(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
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
        templates = await list_templates(
            tenant_id=ctx.scope.tenant_id,
            project_id=ctx.scope.project_id,
            limit=query.limit or 50,
            offset=0,
            category=None,
            current_user=ctx.user,
            db=ctx.db,
        )
        return {
            "templates": [
                t.model_dump(mode="json")
                for t in templates
                if t.tenant_id == ctx.scope.tenant_id and t.project_id == ctx.scope.project_id
            ]
        }
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


class TemplateSave(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=200_000)
    category: Literal["general", "analysis", "code", "writing"] = "general"


async def save_template(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    """Keep an answer as a prompt template of the project, as the original workbench does."""
    data = TemplateSave.model_validate(payload)
    template = await _canonical(
        ctx,
        "POST",
        "templates",
        query={"tenant_id": ctx.scope.tenant_id},
        body={**data.model_dump(), "project_id": ctx.scope.project_id},
    )
    return {key: template[key] for key in ("id", "title", "category")}
