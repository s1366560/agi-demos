"""Workspace command shaping. Core documents stay on the host; public fields do not."""

from __future__ import annotations

import asyncio
from typing import Any, Literal
from urllib.parse import quote, urlencode
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from plugins.business.guest_runtime.binding import current
from plugins.business.guest_runtime.fetch import exchange, object_body
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

_RECENT = (
    "id",
    "project_id",
    "title",
    "content",
    "content_type",
    "status",
    "metadata",
    "created_at",
    "updated_at",
)
_PROJECT = ("id", "tenant_id", "name", "description", "created_at", "updated_at")
_STATS = ("memory_count", "storage_used", "storage_limit", "active_nodes", "collaborators")
_OPTIONAL_MEMORY = {400, 403, 404, 409, 410, 422}
_HEADER_KEYS = {"etag", "x-workspace-revision", "x-workspace-cursor"}


class _Row(BaseModel):
    model_config = ConfigDict(strict=True)
    tenant_id: str
    project_id: str
    id: str = Field(max_length=128)
    name: str = Field(max_length=255)
    office_status: str = Field(max_length=128)
    is_archived: bool


class _Detail(_Row):
    description: str | None = Field(default=None, max_length=65536)


class _Authority(BaseModel):
    model_config = ConfigDict(strict=True)
    tenant_id: str
    project_id: str
    workspace_id: str
    revision: int = Field(ge=0)


def _scope(ctx: object) -> tuple[str, str]:
    tenant, project = ctx.scope.tenant_id, ctx.scope.project_id
    if not tenant or not project:
        raise HTTPException(403, _("Project membership is required"))
    return str(tenant), str(project)


async def _core(ctx: object, **params: object) -> dict[str, Any]:
    del ctx
    return await current().data("workspace.core", params)


def _public_detail(
    body: object, tenant: str, project: str, workspace: str | None
) -> dict[str, Any]:
    detail = _Detail.model_validate(body)
    if (detail.tenant_id, detail.project_id) != (tenant, project) or (
        workspace is not None and detail.id != workspace
    ):
        raise OptionalBusinessError("forbidden", "Workspace detail scope mismatch")
    return detail.model_dump(exclude={"tenant_id", "project_id"})


async def read_overview(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    tenant, project = _scope(ctx)
    if payload:
        raise HTTPException(422, _("Project overview does not accept parameters"))
    path = "/api/v1/projects/" + quote(project, safe="")
    scope = {"tenant_id": tenant, "project_id": project}
    packages = "/api/v1/platform-plugins/v2/optional-business"
    meta, stats, available = await asyncio.gather(
        exchange("GET", path, query={"tenant_id": tenant}),
        exchange("GET", path + "/stats"),
        exchange("GET", packages + "/", query=scope),
    )
    info = object_body(*meta, _("Project overview is unavailable"))
    if (info["id"], info["tenant_id"]) != (project, tenant):
        raise HTTPException(403, _("Project scope mismatch"))
    counters = object_body(*stats, _("Project overview is unavailable"))
    catalog = object_body(*available, _("Project overview is unavailable"))
    knowledge = next(
        (
            row
            for row in catalog["items"]
            if row["plugin_id"] == "memstack-knowledge" and row["status"] == "enabled"
        ),
        None,
    )
    recent = None
    if knowledge:
        status, body = await exchange(
            "POST",
            packages + "/memstack-knowledge/commands",
            body={
                **scope,
                "expected_digest": knowledge["actual_digest"],
                "command_id": "list-memories",
                "payload": {"page": 1, "page_size": 5},
            },
        )
        if status not in _OPTIONAL_MEMORY:
            page = object_body(status, body, _("Project overview is unavailable"))
            if any(row["project_id"] != project for row in page["memories"]):
                raise HTTPException(502, _("Memory response scope mismatch"))
            recent = {
                "memories": [{key: row.get(key) for key in _RECENT} for row in page["memories"]],
                "total": page["total"],
            }
    return {
        "project": {key: info.get(key) for key in _PROJECT},
        "stats": {key: counters[key] for key in _STATS},
        "recent": recent,
    }


class DirectoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=8, ge=1, le=100)
    cards: bool = False


async def read_directory(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    tenant, project = _scope(ctx)
    try:
        if "summary_for" in payload:
            from plugins.business.workspace.command_models import SummaryQuery

            return await _summary(ctx, SummaryQuery.model_validate(payload).summary_for)
        query = DirectoryQuery.model_validate(payload)
        if not query.cards and query.limit > 8:
            raise HTTPException(422, _("The export page size is limited to 8 workspaces"))
    except ValidationError as exc:
        raise HTTPException(422, _("Invalid workspace directory query")) from exc
    raw = await _core(ctx, query=urlencode(query.model_dump(exclude={"cards"})))
    if raw["status"] != 200:
        raise HTTPException(raw["status"], _("Workspace directory unavailable"))
    if query.cards:
        from plugins.business.workspace.command_models import Card, directory_card

        cards = TypeAdapter(list[Card]).validate_python(raw["body"])
        return {"rows": [directory_card(card, ctx.scope) for card in cards]}
    rows = TypeAdapter(list[_Row]).validate_python(raw["body"])
    if any((row.tenant_id, row.project_id) != (tenant, project) for row in rows):
        raise ValueError("workspace directory scope mismatch")
    return {"rows": [row.model_dump(exclude={"tenant_id", "project_id"}) for row in rows]}


async def _summary(ctx: object, workspace: str) -> dict[str, Any]:
    await read_workspace(ctx, {"workspace_id": workspace}, None)

    async def read(child: str) -> object:
        try:
            query = ""
            if child == "plan":
                query = (
                    "outbox_limit=0&event_limit=0&include_details=false"
                    "&recover_stale_attempts=false"
                )
            raw = await _core(
                ctx,
                workspace=workspace,
                child=[child],
                task_route=child != "objectives",
                query=query,
            )
            if raw["status"] == 200:
                return raw["body"]
        except (HTTPException, ValueError):
            return None
        return None

    def rows(value: object, key: str) -> list[dict[str, Any]] | None:
        items = value.get(key) if isinstance(value, dict) else value
        if not isinstance(items, list) or any(
            not isinstance(item, dict) or item.get("workspace_id", workspace) != workspace
            for item in items
        ):
            return None
        return items

    objectives, plan = await asyncio.gather(read("objectives"), read("plan"))
    items = rows(objectives, "items")
    nodes = plan.get("plan") if isinstance(plan, dict) else None
    node_items = rows(nodes, "nodes") if isinstance(nodes, dict) else None
    root = plan.get("root_goal") if isinstance(plan, dict) else None
    tasks = None if items or node_items else rows(await read("tasks"), "items")
    return {
        "objectives": None
        if items is None
        else [
            {"obj_type": item.get("obj_type"), "progress": item.get("progress")} for item in items
        ],
        "plan": None
        if not isinstance(plan, dict)
        else {
            "root_goal": {"status": root.get("status")} if isinstance(root, dict) else None,
            "plan": {
                "nodes": [
                    {"kind": node.get("kind"), "intent": node.get("intent")} for node in node_items
                ]
            }
            if node_items is not None
            else None,
        },
        "tasks": None if tasks is None else [{"status": task.get("status")} for task in tasks],
    }


async def read_workspace(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    from plugins.business.workspace.command_models import WorkspaceRead

    tenant, project = _scope(ctx)
    try:
        query = WorkspaceRead.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(422, _("Invalid workspace detail query")) from exc
    revision = None
    if query.include_revision:
        raw = await _core(ctx, workspace=query.workspace_id, read_authority=True)
        if raw["status"] != 200:
            raise HTTPException(raw["status"], _("Workspace settings unavailable"))
        value = _Authority.model_validate(raw["body"])
        if (value.tenant_id, value.project_id, value.workspace_id) != (
            tenant,
            project,
            query.workspace_id,
        ):
            raise OptionalBusinessError("forbidden", "Workspace settings scope mismatch")
        revision = value.revision
    raw = await _core(ctx, workspace=query.workspace_id)
    if raw["status"] == 409:
        raise HTTPException(409, _("Workspace changed. Reload its settings and try again."))
    if raw["status"] not in (200, 201):
        raise HTTPException(raw["status"], _("Workspace Core rejected this operation"))
    result = _public_detail(raw["body"], tenant, project, query.workspace_id)
    return {**result, "revision": revision} if revision is not None else result


async def create_workspace(
    ctx: object, payload: dict[str, Any], _progress: object
) -> dict[str, Any]:
    from plugins.business.workspace.command_models import CreateWorkspace

    tenant, project = _scope(ctx)
    try:
        data = CreateWorkspace.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(422, _("Invalid workspace creation request")) from exc
    raw = await _core(
        ctx,
        method="POST",
        request_id=str(data.request_id),
        data=data.model_dump(exclude_unset=True, exclude={"request_id"}, mode="json"),
    )
    return _finish_detail(raw, tenant, project, None)


async def update_workspace(
    ctx: object, payload: dict[str, Any], _progress: object
) -> dict[str, Any]:
    from plugins.business.workspace.command_models import UpdateWorkspace

    tenant, project = _scope(ctx)
    try:
        data = UpdateWorkspace.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(422, _("Invalid workspace settings request")) from exc
    changes = data.model_dump(
        exclude_unset=True, exclude={"workspace_id", "request_id", "expected_revision"}
    )
    if not changes:
        raise HTTPException(422, _("Provide workspace settings to change"))
    raw = await _core(
        ctx,
        workspace=data.workspace_id,
        method="PATCH",
        request_id=str(data.request_id),
        expected_revision=data.expected_revision,
        data=changes,
    )
    return _finish_detail(raw, tenant, project, data.workspace_id)


def _finish_detail(
    raw: dict[str, Any], tenant: str, project: str, workspace: str | None
) -> dict[str, Any]:
    if raw["status"] == 409:
        raise HTTPException(409, _("Workspace changed. Reload its settings and try again."))
    if raw["status"] not in (200, 201):
        raise HTTPException(raw["status"], _("Workspace Core rejected this operation"))
    return _public_detail(raw["body"], tenant, project, workspace)


def collaboration_handler(topic: str, *, write: bool) -> object:
    async def handler(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
        from plugins.business.workspace.backend.collaboration import (
            Change,
            CollectionRequest,
            _mutation,
        )

        paths = {"members": ("members",), "posts": ("blackboard", "posts"), "tasks": ("tasks",)}
        path = paths[topic]
        data = None
        method: Literal["GET", "POST", "PATCH", "DELETE"] = "GET"
        try:
            args = (
                Change.model_validate(payload)
                if write
                else CollectionRequest.model_validate(payload)
            )
            if isinstance(args, Change):
                method, data = _mutation(topic, args)
                if args.id:
                    path += (args.id,)
        except (ValidationError, ValueError) as exc:
            raise HTTPException(422, _("Invalid workspace collaboration request")) from exc
        await read_workspace(ctx, {"workspace_id": args.workspace_id}, None)
        raw = await _core(
            ctx,
            workspace=args.workspace_id,
            child=list(path),
            task_route=topic == "tasks",
            query=(
                f"offset={args.offset}&limit={args.limit}"
                if isinstance(args, CollectionRequest)
                else ""
            ),
            method=method,
            data=data,
            request_id=str(args.request_id) if isinstance(args, Change) else None,
            expected_revision=args.expected_revision if isinstance(args, Change) else None,
        )
        if not 200 <= raw["status"] < 300:
            error = raw["body"]
            reason = error.get("detail") if isinstance(error, dict) else None
            raise HTTPException(
                raw["status"],
                reason if isinstance(reason, str) else _("Workspace Core rejected this operation"),
            )
        if write:
            return {"saved": True}
        value = raw["body"] if raw["body"] is not None else {}
        rows = value if isinstance(value, list) else value.get("items", value.get(topic))
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) or row.get("workspace_id") != args.workspace_id
            for row in rows
        ):
            raise HTTPException(502, _("Invalid workspace collaboration response"))
        return {"items": rows}

    return handler


def _surface_headers(headers: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in headers.items() if key.lower() in _HEADER_KEYS}


async def _surface_call(ctx: object, args: object, change: object) -> dict[str, Any]:
    from plugins.business.workspace.command_models import _ROOT, _SCOPED, _WRITES

    permitted = _WRITES[change.method] if change else _SCOPED | _ROOT
    if args.resource not in permitted:
        raise HTTPException(422, _("Unknown workspace operation"))
    parts = args.resource.split("/") if args.resource else []
    if parts.count(":id") != len(args.ids):
        raise HTTPException(422, _("Invalid workspace item"))
    ids = iter(args.ids)
    path = tuple(next(ids) if part == ":id" else part for part in parts)
    allowed = {
        "offset",
        "limit",
        "page",
        "page_size",
        "status",
        "parent_path",
        "category",
        "is_active",
        "outbox_limit",
        "event_limit",
        "include_details",
        "plan_id",
        "recursive",
        "before",
        "after",
        "include_archived",
        "language",
        "locale",
        "sort",
    }
    if args.resource == "plan" and args.query.get("recover_stale_attempts") == "false":
        allowed.add("recover_stale_attempts")
    if args.query.keys() - allowed or any(len(item) > 512 for item in args.query.values()):
        raise HTTPException(422, _("Invalid workspace query"))
    root_route = bool(parts and parts[0] in {"tasks", "plan", "topology", "autonomy"})
    if root_route:
        await read_workspace(ctx, {"workspace_id": args.workspace_id}, None)
    raw = await _core(
        ctx,
        workspace=args.workspace_id,
        child=list(path),
        task_route=root_route,
        query=urlencode(args.query),
        method=change.method if change else "GET",
        data=change.fields if change else None,
        request_id=str(UUID(change.request_id)) if change else None,
        expected_revision=change.revision if change else None,
    )
    if not 200 <= raw["status"] < 300:
        raise HTTPException(raw["status"], _("Workspace Core rejected this operation"))
    return {
        "data": raw["body"],
        "status": raw["status"],
        "headers": _surface_headers(raw["headers"]),
    }


async def _download(ctx: object, workspace: str, file_id: str, progress: object) -> dict[str, Any]:
    if progress is None:
        raise HTTPException(422, _("File download requires a stream"))

    async def publish_chunk(frame: dict[str, Any]) -> None:
        await progress({"content": frame["raw"]})

    result = await current().data(
        "workspace.file.chunks",
        {"workspace": workspace, "file_id": file_id},
        publish_chunk,
    )
    return {"size": result["size"], "mime": result["mime"]}


class SurfaceQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    workspace_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    resource: str = Field(max_length=128)
    ids: list[str] = Field(default_factory=list, max_length=2)
    query: dict[str, str] = Field(default_factory=dict, max_length=12)


async def read_surface(ctx: object, payload: dict[str, Any], progress: object) -> dict[str, Any]:
    query = SurfaceQuery.model_validate(payload)
    if query.resource == "blackboard/files/:id/download" and len(query.ids) == 1:
        return await _download(ctx, query.workspace_id, query.ids[0], progress)
    if query.resource in {"published-genes", "board-conversations"} and not query.ids:
        return await _projection(ctx, query.workspace_id, query.resource, query.query)
    return await _surface_call(ctx, query, None)


class SurfaceChange(SurfaceQuery):
    method: Literal["POST", "PATCH", "DELETE"]
    fields: dict[str, Any] | None = None
    request_id: str = Field(min_length=36, max_length=36)
    revision: int = Field(ge=0)


async def change_surface(ctx: object, payload: dict[str, Any], progress: object) -> dict[str, Any]:
    del progress
    change = SurfaceChange.model_validate(payload)
    if change.method == "POST" and change.resource.startswith("file-transfer/") and not change.ids:
        return await current().data(
            "workspace.file.upload",
            {
                "workspace": change.workspace_id,
                "operation": change.resource.removeprefix("file-transfer/"),
                "request_id": change.request_id,
                "revision": change.revision,
                "fields": change.fields or {},
            },
        )
    return await _surface_call(ctx, change, change)


async def _projection(
    ctx: object, workspace: str, resource: str, query: dict[str, str]
) -> dict[str, Any]:
    await read_workspace(ctx, {"workspace_id": workspace}, None)
    tenant, project = _scope(ctx)
    if resource == "published-genes":
        from plugins.business.workspace.command_models import CatalogSearch

        params = {
            **CatalogSearch.model_validate(query).model_dump(),
            "is_published": True,
            "tenant_id": tenant,
        }
        path = "/api/v1/genes/"
    else:
        from plugins.business.workspace.command_models import RosterPage

        params = {
            **RosterPage.model_validate(query).model_dump(),
            "workspace_id": workspace,
            "project_id": project,
            "status": "active",
        }
        path = "/api/v1/agent/conversations"
    status, data = await exchange("GET", path, query=params, headers={"X-Tenant-ID": tenant})
    document = object_body(status, data, _("Workspace projection is unavailable"))
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
            for row in document["items"]
            if row.get("workspace_id") == workspace
        ]
        document = {
            "items": items,
            "has_more": document["has_more"],
            "next_offset": document.get("next_offset"),
        }
    return {"data": document, "status": 200, "headers": {}}


async def read_chat(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    from plugins.business.workspace.backend.group_chat import Read

    args = Read.model_validate(payload)

    async def rows(resource: str) -> list[dict[str, Any]]:
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
        return {"messages": await rows("messages"), "principal_id": current().user_id}
    members, agents = await asyncio.gather(rows("members"), rows("agents"))
    return {"members": members, "agents": agents}


async def send_chat(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    from plugins.business.workspace.backend.group_chat import Send

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


OPERATIONS = {
    "app.workspace.directory.read": read_directory,
    "app.workspace.detail.read": read_workspace,
    "app.workspace.create": create_workspace,
    "app.workspace.settings.update": update_workspace,
    "app.workspace.members.read": collaboration_handler("members", write=False),
    "app.workspace.members.write": collaboration_handler("members", write=True),
    "app.workspace.posts.read": collaboration_handler("posts", write=False),
    "app.workspace.posts.write": collaboration_handler("posts", write=True),
    "app.workspace.tasks.read": collaboration_handler("tasks", write=False),
    "app.workspace.tasks.write": collaboration_handler("tasks", write=True),
    "app.workspace.blackboard.read": read_surface,
    "app.workspace.blackboard.write": change_surface,
    "app.workspace.overview.read": read_overview,
    "app.workspace.chat.read": read_chat,
    "app.workspace.chat.send": send_chat,
}
