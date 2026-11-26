"""Scoped application capabilities backed by the canonical Agent HTTP and WS authorities."""

from collections.abc import Mapping
from typing import TYPE_CHECKING, Annotated, Any

import httpx
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from src.host.operations.device_conversations import (
    ConversationId,
    ConversationList,
    ConversationRename,
    DeviceConversationCreate,
    create_owned,
    local_history,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentRunAuthorityModel,
    Conversation,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_run_authority import (
    latest_execution_placements,
)
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

from .chat_stream import stream_turn

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext, Progress

type Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ConversationInput(_Input):
    conversation_id: ConversationId


class History(ConversationInput):
    before_time_us: int | None = Field(default=None, ge=0)
    before_counter: int = Field(default=0, ge=0)
    # A transcript page carries the reasoning and tool steps around its messages,
    # so the workbench reads wider pages than a single-message caller.
    limit: int = Field(default=50, ge=1, le=500)


class Turn(ConversationInput):
    message_id: Identifier
    forced_skill_name: str | None = Field(default=None, min_length=1, max_length=255)
    message: str = Field(min_length=1, max_length=32000)


class Cancel(ConversationInput):
    run_id: Identifier
    expected_revision: int = Field(ge=1)


async def _own_conversation(ctx: "PackageOperationContext", conversation_id: str) -> None:
    match = await ctx.db.scalar(
        select(Conversation.id).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == ctx.scope.tenant_id,
            Conversation.project_id == ctx.scope.project_id,
            Conversation.user_id == ctx.user.id,
        )
    )
    if match is None:
        raise OptionalBusinessError("forbidden", "conversation unavailable for this project")


async def _canonical(
    ctx: "PackageOperationContext",
    method: str,
    path: str,
    *,
    project_route: bool = False,
    body: dict[str, Any] | None = None,
    query: Mapping[str, int | str] | None = None,
) -> dict[str, Any]:
    base = f"/api/v1/projects/{ctx.scope.project_id}/" if project_route else "/api/v1/agent/"
    return await _canonical_http(ctx, method, base + path, body=body, query=query)


async def _canonical_http(
    ctx: "PackageOperationContext",
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    query: Mapping[str, int | str] | None = None,
) -> dict[str, Any]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=ctx.request.app),
        base_url="http://localhost",
        headers={"authorization": ctx.request.headers.get("authorization", "")},
    ) as client:
        reply = await client.request(
            method,
            path,
            params={"project_id": ctx.scope.project_id, **(query or {})},
            json=body,
        )
    if reply.status_code >= 400:
        code = {403: "forbidden", 401: "forbidden", 404: "page_not_found", 409: "conflict"}.get(
            reply.status_code, "runtime_unavailable"
        )
        raise OptionalBusinessError(code, f"Agent authority returned HTTP {reply.status_code}")
    result = reply.json()
    if not isinstance(result, dict):
        raise OptionalBusinessError("runtime_unavailable", "Invalid Agent authority response")
    return result


async def visible_skills(
    ctx: "PackageOperationContext", *, limit: int, search: str | None = None
) -> list[dict[str, Any]]:
    result = await _canonical_http(
        ctx,
        "GET",
        "/api/v1/skills/",
        query={
            "tenant_id": ctx.scope.tenant_id,
            "status": "active",
            "limit": limit,
            **({"search": search} if search else {}),
        },
    )
    return [
        {key: item[key] for key in ("id", "name", "description", "scope")}
        for item in result["skills"]
        if item.get("status") == "active"
        and item.get("project_id") in (None, ctx.scope.project_id)
        and (item.get("scope") == "system" or item.get("tenant_id") == ctx.scope.tenant_id)
    ]


def _conversation(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row[key] for key in ("id", "title", "execution_target")}


class WorkbenchList(ConversationList):
    workbench: bool = False
    limit: int | None = Field(default=None, ge=1, le=100)


async def _conversation_page(
    ctx: "PackageOperationContext", filters: WorkbenchList
) -> list[dict[str, Any]]:
    query: dict[str, str | int] = {}
    if filters.limit is not None:
        query["limit"] = filters.limit
    if filters.workspace_id:
        query["workspace_id"] = filters.workspace_id
    if not filters.workbench or filters.workspace_id:
        result = await _canonical(ctx, "GET", "conversations", query=query)
        items = result["items"]
        if not isinstance(items, list) or any(not isinstance(row, dict) for row in items):
            raise OptionalBusinessError("runtime_unavailable", "Invalid conversation list")
        return items

    # The Web workbench initially loads two pages. The unbound list owns its
    # ordering and duplicates, then grouped rows contribute previously unseen IDs.
    query["limit"] = filters.limit or 10
    unbound = await _canonical(ctx, "GET", "conversations", query={**query, "unbound_only": "true"})
    grouped = await _canonical(
        ctx, "GET", "conversations", query={**query, "group_by_workspace": "true"}
    )
    items = list(unbound["items"])
    seen = {row["id"] for row in items}
    for row in grouped["items"]:
        if row["id"] not in seen:
            seen.add(row["id"])
            items.append(row)
    return items


async def list_conversations(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    filters = WorkbenchList.model_validate(payload)
    page = await _conversation_page(ctx, filters)
    if filters.conversation_id and all(row["id"] != filters.conversation_id for row in page):
        await _own_conversation(ctx, filters.conversation_id)
        selected = await _canonical(ctx, "GET", f"conversations/{filters.conversation_id}")
        if filters.workspace_id and selected.get("workspace_id") != filters.workspace_id:
            raise OptionalBusinessError("forbidden", "conversation unavailable for this workspace")
        page.insert(0, selected)
    items: list[dict[str, Any]] = []
    for row in page:
        metadata = row.get("metadata") or {}
        items.append(
            {
                **_conversation(row),
                **{
                    key: row[key]
                    for key in (
                        "workspace_id",
                        "workspace_name",
                        "linked_workspace_task_id",
                        "created_at",
                        "updated_at",
                    )
                    if row.get(key)
                },
                "sidebar_active": row.get("status") == "active",
                "sidebar_hidden": bool(
                    row.get("parent_conversation_id")
                    or metadata.get("spawned_by_agent_id")
                    or metadata.get("spawned_agent_id")
                ),
                **(
                    {"sidebar_role": metadata["workspace_role"]}
                    if isinstance(metadata.get("workspace_role"), str)
                    else {}
                ),
            }
        )
    local_ids = set(
        await ctx.db.scalars(
            select(Conversation.id).where(
                Conversation.id.in_([row["id"] for row in items]),
                Conversation.tenant_id == ctx.scope.tenant_id,
                Conversation.project_id == ctx.scope.project_id,
                Conversation.user_id == ctx.user.id,
                Conversation.meta["execution_target"].as_string() == "local",
            )
        )
    )
    for row in items:
        if row["id"] in local_ids:
            row["execution_target"] = "local"
    return {"items": items}


async def create(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    data = DeviceConversationCreate.model_validate(payload)
    if data.execution_target == "local":
        return await create_owned(ctx, payload, progress)
    return _conversation(
        await _canonical(
            ctx,
            "POST",
            "conversations",
            body={
                "title": data.title,
                "project_id": ctx.scope.project_id,
                **(
                    {"workspace_id": data.workspace_id, "agent_config": {"capability_mode": "work"}}
                    if data.workspace_id
                    else {}
                ),
            },
        )
    )


async def rename(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    data = ConversationRename.model_validate(payload)
    await _own_conversation(ctx, data.conversation_id)
    row = await _canonical(
        ctx, "PATCH", f"conversations/{data.conversation_id}/title", body={"title": data.title}
    )
    return {"id": row["id"], "title": row["title"]}


USAGE_KEYS = (
    ("stepCount", "step_count"),
    ("artifactCount", "artifact_count"),
    ("callCount", "call_count"),
    ("totalCost", "total_cost"),
    ("totalCostFormatted", "total_cost_formatted"),
    ("totalTokens", "total_tokens"),
    ("tasks", "tasks"),
)

type Counter = int | float | dict[str, Counter]


def _counters(value: object) -> Counter | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, dict):
        return {
            key: counter
            for key, child in value.items()
            if isinstance(key, str) and (counter := _counters(child)) is not None
        }
    return None


def usage_summary(row: dict[str, Any]) -> dict[str, Any]:
    """Counters of a finished answer. Nothing else of the message metadata leaves."""
    summary = (row.get("metadata") or {}).get("executionSummary")
    if row.get("type") != "assistant_message" or not isinstance(summary, dict):
        return {}
    usage: dict[str, Counter | str] = {}
    for camel, snake in USAGE_KEYS:
        value = summary.get(camel, summary.get(snake))
        if camel == "totalCostFormatted":
            if isinstance(value, str) and len(value) <= 32:
                usage[camel] = value
        elif (counter := _counters(value)) is not None:
            usage[camel] = counter
    return {"summary": usage} if usage else {}


async def history(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    data = History.model_validate(payload)
    await _own_conversation(ctx, data.conversation_id)
    preferred = await ctx.db.scalar(
        select(Conversation.meta).where(Conversation.id == data.conversation_id)
    )
    placements = await latest_execution_placements(
        ctx.db,
        tenant_id=ctx.scope.tenant_id,
        project_id=ctx.scope.project_id,
        conversation_ids=[data.conversation_id],
    )
    actual = placements.get(data.conversation_id)
    if (actual and actual.execution_target == "local") or (preferred or {}).get(
        "execution_target"
    ) == "local":
        replay = {key: value for key, value in payload.items() if key != "limit"}
        return await local_history(ctx, replay, progress)
    query = {"limit": data.limit}
    if data.before_time_us is not None:
        query.update(before_time_us=data.before_time_us, before_counter=data.before_counter)
    result = await _canonical(
        ctx, "GET", f"conversations/{data.conversation_id}/messages", query=query
    )

    # Every row carries its position, because a transcript interleaves messages
    # with the reasoning and the tool steps of the same turn.
    def positioned(row: dict[str, Any]) -> dict[str, Any]:
        return {
            key: row[key]
            for key in ("timestamp", "eventTimeUs", "eventCounter")
            if isinstance(row.get(key), int)
        }

    text = [
        (row["id"], row["type"], row["content"], positioned(row), usage_summary(row))
        for row in result["timeline"]
        if row.get("type") in {"user_message", "assistant_message", "thought"}
        and isinstance(row.get("content"), str)
    ]
    # P5 contains tool arguments and execution authorizations as well as messages.
    # Only return the text presentation that this capability promises: reasoning
    # is part of what a reader sees, while tool arguments belong to interactions.
    return {
        "before": {
            "before_time_us": result["first_time_us"],
            "before_counter": result["first_counter"],
        }
        if result["has_more"]
        else None,
        "messages": [
            {
                "id": identifier,
                "role": kind,
                "content": content,
                **position,
                **usage,
            }
            for identifier, kind, content, position, usage in text
            if kind != "thought"
        ],
        "thoughts": [
            {"id": identifier, "content": content, **position}
            for identifier, kind, content, position, _usage in text
            if kind == "thought"
        ],
    }


async def turn(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    return await _turn(ctx, Turn.model_validate(payload), progress)


async def _turn(
    ctx: "PackageOperationContext",
    data: Turn,
    progress: "Progress | None",
    files: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    await _own_conversation(ctx, data.conversation_id)
    placements = await latest_execution_placements(
        ctx.db,
        tenant_id=ctx.scope.tenant_id,
        project_id=ctx.scope.project_id,
        conversation_ids=[data.conversation_id],
    )
    previous = placements.get(data.conversation_id)
    preferred = await ctx.db.scalar(
        select(Conversation.meta).where(Conversation.id == data.conversation_id)
    )
    if (previous is not None and previous.execution_target == "local") or (preferred or {}).get(
        "execution_target"
    ) == "local":
        raise OptionalBusinessError(
            "forbidden", "Local conversations support read-only cloud replay"
        )
    if data.forced_skill_name is not None:
        skills = await visible_skills(ctx, limit=500, search=data.forced_skill_name)
        if not any(skill["name"] == data.forced_skill_name for skill in skills):
            raise OptionalBusinessError("forbidden", "Skill unavailable for this project")
    message = data.model_dump(exclude_none=True)
    if files:
        message["attachment_ids"] = [file["id"] for file in files]
        message["file_metadata"] = [
            {key: value for key, value in file.items() if key != "id"} for file in files
        ]
    return await stream_turn(ctx, message, progress)


async def cancel(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    data = Cancel.model_validate(payload)
    await _own_conversation(ctx, data.conversation_id)
    run = await ctx.db.scalar(
        select(AgentRunAuthorityModel.id).where(
            AgentRunAuthorityModel.id == data.run_id,
            AgentRunAuthorityModel.conversation_id == data.conversation_id,
            AgentRunAuthorityModel.tenant_id == ctx.scope.tenant_id,
            AgentRunAuthorityModel.project_id == ctx.scope.project_id,
            AgentRunAuthorityModel.execution_target == "cloud",
        )
    )
    if run is None:
        raise OptionalBusinessError("forbidden", "cloud run unavailable for this conversation")
    result = await _canonical(
        ctx,
        "POST",
        f"runs/{data.run_id}/cancel",
        body={"expected_revision": data.expected_revision},
    )
    return {"status": result["status"]}


AGENT_OPERATIONS = {
    "app.agent.list": list_conversations,
    "app.agent.create": create,
    "app.agent.rename": rename,
    "app.agent.history": history,
    "app.agent.turn": turn,
    "app.agent.cancel": cancel,
}
