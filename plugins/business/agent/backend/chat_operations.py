"""Project chat commands. Data access goes through the bound host port."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from plugins.business.agent.guest.binding import (
    CommandContext,
    CommandError,
    Progress,
    bound,
    current,
)

type Identifier = str


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ConversationInput(_Input):
    conversation_id: str = Field(pattern=r"^[A-Za-z0-9_:-]{1,128}$")


class History(ConversationInput):
    before_time_us: int | None = Field(default=None, ge=0)
    before_counter: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=500)


class Turn(ConversationInput):
    message_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    forced_skill_name: str | None = Field(default=None, min_length=1, max_length=255)
    message: str = Field(min_length=1, max_length=32000)


class Cancel(ConversationInput):
    run_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    expected_revision: int = Field(ge=1)


class WorkbenchList(_Input):
    workbench: bool = False
    limit: int | None = Field(default=None, ge=1, le=100)
    workspace_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,128}$")
    conversation_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_:-]{1,128}$")


def _project_of(ctx: CommandContext) -> str:
    project = getattr(getattr(ctx, "scope", None), "project_id", None) or (
        current().project_id if bound() else None
    )
    if not project:
        raise CommandError("forbidden", "project scope required")
    return project


async def _canonical_http(
    ctx: CommandContext,
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await current().http(method, path, body=body, query=query, absolute=True)


async def _canonical(
    _ctx: CommandContext,
    method: str,
    path: str,
    *,
    project_route: bool = False,
    body: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await current().http(method, path, project_route=project_route, body=body, query=query)


async def _own_conversation(_ctx: CommandContext, conversation_id: str) -> None:
    await current().own(conversation_id)


async def visible_skills(
    _ctx: CommandContext, *, limit: int, search: str | None = None
) -> list[dict[str, Any]]:
    project = _project_of(_ctx)
    tenant_id = getattr(getattr(_ctx, "scope", None), "tenant_id", None)
    if tenant_id is None and bound():
        tenant_id = current().tenant_id
    result = await _canonical_http(
        _ctx,
        "GET",
        "/api/v1/skills/",
        query={
            "tenant_id": tenant_id,
            "status": "active",
            "limit": limit,
            **({"search": search} if search else {}),
        },
    )
    return [
        {key: item[key] for key in ("id", "name", "description", "scope")}
        for item in result["skills"]
        if item.get("status") == "active"
        and item.get("project_id") in (None, project)
        and (item.get("scope") == "system" or item.get("tenant_id") == tenant_id)
    ]


def _conversation(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row[key] for key in ("id", "title", "execution_target")}


async def _conversation_page(_ctx: CommandContext, filters: WorkbenchList) -> list[dict[str, Any]]:
    query: dict[str, str | int] = {}
    if filters.limit is not None:
        query["limit"] = filters.limit
    if filters.workspace_id:
        query["workspace_id"] = filters.workspace_id
    if not filters.workbench or filters.workspace_id:
        result = await _canonical(_ctx, "GET", "conversations", query=query)
        items = result["items"]
        if not isinstance(items, list) or any(not isinstance(row, dict) for row in items):
            raise CommandError("runtime_unavailable", "Invalid conversation list")
        return items
    query["limit"] = filters.limit or 10
    unbound = await _canonical(
        _ctx, "GET", "conversations", query={**query, "unbound_only": "true"}
    )
    grouped = await _canonical(
        _ctx, "GET", "conversations", query={**query, "group_by_workspace": "true"}
    )
    items = list(unbound["items"])
    seen = {row["id"] for row in items}
    for row in grouped["items"]:
        if row["id"] not in seen:
            seen.add(row["id"])
            items.append(row)
    return items


async def list_conversations(
    ctx: CommandContext, payload: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    filters = WorkbenchList.model_validate(payload)
    page = await _conversation_page(ctx, filters)
    if filters.conversation_id and all(row["id"] != filters.conversation_id for row in page):
        await _own_conversation(ctx, filters.conversation_id)
        selected = await _canonical(ctx, "GET", f"conversations/{filters.conversation_id}")
        if filters.workspace_id and selected.get("workspace_id") != filters.workspace_id:
            raise CommandError("forbidden", "conversation unavailable for this workspace")
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
    local_ids = set(await current().local_ids([row["id"] for row in items])) if bound() else set()
    for row in items:
        if row["id"] in local_ids:
            row["execution_target"] = "local"
    return {"items": items}


async def create(_ctx: CommandContext, payload: dict[str, Any], _progress: Progress | None) -> dict[str, Any]:
    from plugins.business.agent.guest.models import DeviceConversationCreate

    data = DeviceConversationCreate.model_validate(payload)
    if data.execution_target == "local":
        return await current().device("create", payload)
    project_id = _project_of(_ctx)
    return _conversation(
        await _canonical(
            _ctx,
            "POST",
            "conversations",
            body={
                "title": data.title,
                "project_id": project_id,
                **(
                    {"workspace_id": data.workspace_id, "agent_config": {"capability_mode": "work"}}
                    if data.workspace_id
                    else {}
                ),
            },
        )
    )


async def rename(ctx: CommandContext, payload: dict[str, Any], _progress: Progress | None) -> dict[str, Any]:
    from plugins.business.agent.guest.models import ConversationRename

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

type Counter = int | float | dict[str, "Counter"]


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


async def history(ctx: CommandContext, payload: dict[str, Any], _progress: Progress | None) -> dict[str, Any]:
    data = History.model_validate(payload)
    await _own_conversation(ctx, data.conversation_id)
    preferred = await current().meta(data.conversation_id) if bound() else None
    placements = await current().placements([data.conversation_id]) if bound() else {}
    actual = placements.get(data.conversation_id)
    if actual == "local" or (preferred or {}).get("execution_target") == "local":
        replay = {key: value for key, value in payload.items() if key != "limit"}
        return await current().device("history", replay)

    query: dict[str, int] = {"limit": data.limit}
    if data.before_time_us is not None:
        query.update(before_time_us=data.before_time_us, before_counter=data.before_counter)
    result = await _canonical(
        ctx, "GET", f"conversations/{data.conversation_id}/messages", query=query
    )

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
    return {
        "before": {
            "before_time_us": result["first_time_us"],
            "before_counter": result["first_counter"],
        }
        if result["has_more"]
        else None,
        "messages": [
            {"id": identifier, "role": kind, "content": content, **position, **usage}
            for identifier, kind, content, position, usage in text
            if kind != "thought"
        ],
        "thoughts": [
            {"id": identifier, "content": content, **position}
            for identifier, kind, content, position, _usage in text
            if kind == "thought"
        ],
    }


async def turn(ctx: CommandContext, payload: dict[str, Any], progress: Progress | None) -> dict[str, Any]:
    return await _turn(ctx, Turn.model_validate(payload), progress)


async def _turn(
    ctx: CommandContext,
    data: Turn,
    progress: Progress | None,
    files: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    await _own_conversation(ctx, data.conversation_id)
    placements = await latest_execution_placements(ctx, data.conversation_id)
    previous = placements.get(data.conversation_id)
    preferred = await current().meta(data.conversation_id) if bound() else None
    if previous == "local" or (preferred or {}).get("execution_target") == "local":
        raise CommandError("forbidden", "Local conversations support read-only cloud replay")
    if data.forced_skill_name is not None:
        skills = await visible_skills(ctx, limit=500, search=data.forced_skill_name)
        if not any(skill["name"] == data.forced_skill_name for skill in skills):
            raise CommandError("forbidden", "Skill unavailable for this project")
    message = data.model_dump(exclude_none=True)
    if files:
        message["attachment_ids"] = [file["id"] for file in files]
        message["file_metadata"] = [
            {key: value for key, value in file.items() if key != "id"} for file in files
        ]
    return await stream_turn(ctx, message, progress)


async def latest_execution_placements(
    _ctx: CommandContext, conversation_id: str
) -> dict[str, str]:
    if not bound():
        return {}
    return await current().placements([conversation_id])


async def stream_turn(
    ctx: CommandContext, message: dict[str, Any], progress: Progress | None
) -> dict[str, Any]:
    del ctx
    return await current().stream(message, progress)


async def cancel(ctx: CommandContext, payload: dict[str, Any], _progress: Progress | None) -> dict[str, Any]:
    data = Cancel.model_validate(payload)
    await _own_conversation(ctx, data.conversation_id)
    if bound() and not await current().run_cloud(data.run_id, data.conversation_id):
        raise CommandError("forbidden", "cloud run unavailable for this conversation")
    result = await _canonical(
        ctx,
        "POST",
        f"runs/{data.run_id}/cancel",
        body={"expected_revision": data.expected_revision},
    )
    return {"status": result["status"]}


AGENT_OPERATIONS: dict[str, Any] = {}
