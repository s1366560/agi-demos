"""Knowledge command shaping. The child validates scope and projects public fields."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote
from uuid import UUID

from fastapi import HTTPException

from plugins.business.guest_runtime.binding import current
from plugins.business.guest_runtime.fetch import exchange, object_body
from src.infrastructure.i18n import gettext as _

_EXCERPT = 320


def _require_project(ctx: object) -> tuple[str, str]:
    tenant, project = ctx.scope.tenant_id, ctx.scope.project_id
    if not tenant or not project:
        raise HTTPException(403, _("Project membership is required"))
    return str(tenant), str(project)


async def search(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    from plugins.business.knowledge.backend.project_search import Search

    request = Search.model_validate(payload)
    tenant, project = _require_project(ctx)
    scope = {"tenant_id": tenant, "project_id": project}
    if any(request.parameters.get(key, value) != value for key, value in scope.items()):
        raise HTTPException(403, _("Search scope does not match the project"))
    status, body = await exchange(
        "POST",
        "/api/v1/search-enhanced/" + request.mode,
        body={**request.parameters, **scope},
    )
    return object_body(status, body, _("Failed to search the project"))


async def _graph(ctx: object, query: object, subgraph: bool) -> dict[str, Any]:
    tenant, project = _require_project(ctx)
    data = {**query.model_dump(), "tenant_id": tenant, "project_id": project}
    if subgraph:
        status, body = await exchange("POST", "/api/v1/graph/memory/graph/subgraph", body=data)
    else:
        status, body = await exchange("GET", "/api/v1/graph/memory/graph", query=data)
    return object_body(status, body, _("Failed to read the project graph"))


async def read_graph(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    from plugins.business.knowledge.backend.graph_queries import GraphRead

    return await _graph(ctx, GraphRead.model_validate(payload), False)


async def read_subgraph(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    from plugins.business.knowledge.backend.graph_queries import SubgraphRead

    return await _graph(ctx, SubgraphRead.model_validate(payload), True)


async def _entities(ctx: object, path: str, query: object) -> dict[str, Any]:
    tenant, project = _require_project(ctx)
    params = {
        **query.model_dump(exclude_none=True, exclude={"entity_id"}),
        "project_id": project,
        "tenant_id": tenant,
    }
    status, body = await exchange("GET", "/api/v1/graph/entities/" + path, query=params)
    return object_body(status, body, _("Failed to read the project graph"))


async def list_entities(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    from plugins.business.knowledge.backend.entity_queries import _Entities

    return await _entities(ctx, "", _Entities.model_validate(payload))


async def entity_types(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    from plugins.business.knowledge.backend.entity_queries import _Query

    return await _entities(ctx, "types", _Query.model_validate(payload))


async def entity_relationships(
    ctx: object, payload: dict[str, Any], _progress: object
) -> dict[str, Any]:
    from plugins.business.knowledge.backend.entity_queries import _Relationships

    query = _Relationships.model_validate(payload)
    return await _entities(ctx, f"{query.entity_id}/relationships", query)


def _excerpt(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "excerpt": str(row.get("content") or "")[:_EXCERPT],
        "content_type": row.get("content_type"),
    }


async def list_project_memories(
    ctx: object, payload: dict[str, Any], _progress: object
) -> dict[str, Any]:
    tenant, project = _require_project(ctx)
    if payload == {"draft": True}:
        raw = await current().data("knowledge.draft.read", {})
        return {"draft": raw.get("document")}
    if "page" in payload or "detail" in payload:
        return await _workbench(ctx, payload, tenant, project)
    if "id" in payload:
        from plugins.business.knowledge.backend.package_memory_editor import MemorySelection

        memory_id = MemorySelection.model_validate(payload).id
        raw = await current().data("knowledge.memory.record", {"id": memory_id})
        return {
            key: raw[key]
            for key in ("id", "title", "content", "version", "tags", "processing_status")
        }
    from plugins.business.knowledge.backend.project_memory_operation import _Search as Page

    query = Page.model_validate(payload)
    raw = await current().data("knowledge.memories.rows", query.model_dump())
    rows = list(raw["rows"])
    return {
        "items": [_excerpt(row) for row in rows[: query.limit]],
        "has_more": len(rows) > query.limit,
    }


async def _workbench(
    ctx: object, payload: dict[str, Any], tenant: str, project: str
) -> dict[str, Any]:
    del ctx
    params: dict[str, Any] = {"project_id": project}
    if "detail" in payload:
        from plugins.business.knowledge.backend.memory_workbench import MemoryDetailQuery

        detail = MemoryDetailQuery.model_validate(payload)
        path = f"/api/v1/memories/{detail.id}"
    else:
        from plugins.business.knowledge.backend.memory_workbench import MemoryPageQuery

        params.update(MemoryPageQuery.model_validate(payload).model_dump(exclude_none=True))
        path = "/api/v1/memories/"
    status, data = await exchange("GET", path, query=params, headers={"X-Tenant-ID": tenant})
    page = object_body(status, data, _("Memory operation failed"))
    rows = [page] if "detail" in payload else page["memories"]
    if any(item["project_id"] != project for item in rows):
        raise HTTPException(502, _("Memory response scope mismatch"))
    if "page" in payload:
        page["actor_id"] = current().user_id
        if page.get("command_capabilities") is None:
            commands = await current().data("knowledge.memory.commands", {"rows": rows})
            page["command_capabilities"] = commands["commands"]
    return page


async def save_memory(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    if set(payload) == {"draft"}:
        from plugins.business.knowledge.backend.memory_drafts import Draft

        document = Draft.model_validate(payload["draft"]).model_dump()
        await current().data("knowledge.draft.write", {"document": document})
        return {"saved": True}
    from plugins.business.knowledge.backend.package_memory_editor import _Edit

    edit = _Edit.model_validate(payload)
    tenant, project = _require_project(ctx)
    scope = {"tenant_id": tenant, "project_id": project}
    body: dict[str, Any] = {"title": edit.title, "content": edit.content}
    if edit.tags is not None:
        body["tags"] = edit.tags
    if edit.metadata is not None:
        body["metadata"] = edit.metadata
    if edit.id:
        await current().data("knowledge.memory.exists", {"id": edit.id})
        body["version"] = edit.version
        method, path = "PATCH", f"/api/v1/memories/{edit.id}"
    else:
        body["project_id"] = project
        method, path = "POST", "/api/v1/memories/"
    headers: dict[str, str] = {}
    status, result = await exchange(method, path, body=body, query=scope, headers=headers)
    if status == 428:
        headers = {
            "Idempotency-Key": edit.change_id,
            "X-Memory-Expected-Revision": str(edit.version),
        }
        status, result = await exchange(method, path, body=body, query=scope, headers=headers)
    if status == 409:
        raise HTTPException(409, _("Memory changed. Reload before editing again."))
    saved_body = object_body(status, result, _("Memory operation failed"))
    if saved_body["project_id"] != project:
        raise HTTPException(502, _("Memory response scope mismatch"))
    saved = {
        key: saved_body[key]
        for key in ("id", "title", "content", "version", "tags", "processing_status")
    }
    if saved_body.get("task_id"):
        saved["task_id"] = saved_body["task_id"]
    return saved


async def delete_memory(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    from plugins.business.knowledge.backend.memory_maintenance import DeleteMemory

    args = DeleteMemory.model_validate(payload)
    UUID(args.change_id)
    _require_project(ctx)
    path = f"/api/v1/memories/{quote(args.id, safe='')}"
    query: dict[str, Any] = {"project_id": ctx.scope.project_id, "version": args.version}
    headers: dict[str, str] = {}
    status, _body = await exchange("DELETE", path, query=query, headers=headers)
    if status == 428:
        headers = {
            "Idempotency-Key": args.change_id,
            "X-Memory-Expected-Revision": str(args.version),
        }
        status, _body = await exchange("DELETE", path, query=query, headers=headers)
    if status >= 400:
        raise HTTPException(status, _("Memory operation failed"))
    return {"memoryId": args.id, "deleted": True}


async def reindex_memory(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    from plugins.business.knowledge.backend.package_memory_editor import MemorySelection

    args = MemorySelection.model_validate(payload)
    _require_project(ctx)
    await current().data("knowledge.memory.exists", {"id": args.id})
    status, body = await exchange("POST", f"/api/v1/memories/{quote(args.id, safe='')}/reprocess")
    result = object_body(status, body, _("Memory operation failed"))
    if result["project_id"] != ctx.scope.project_id:
        raise HTTPException(502, _("Memory response scope mismatch"))
    return {key: value for key, value in result.items() if key != "author_id"}


async def read_index_task(
    ctx: object, payload: dict[str, Any], _progress: object
) -> dict[str, Any]:
    from plugins.business.knowledge.backend.package_memory_editor import MemorySelection

    task_id = MemorySelection.model_validate(payload).id
    _require_project(ctx)
    await current().data("knowledge.task.visible", {"id": task_id})
    status, body = await exchange("GET", f"/api/v1/tasks/{quote(task_id, safe='')}")
    data = object_body(status, body, _("Task read failed"))
    return {key: data.get(key) for key in ("id", "status", "message", "progress", "error")}


async def optimize_content(
    ctx: object, payload: dict[str, Any], _progress: object
) -> dict[str, Any]:
    from plugins.business.knowledge.backend.memory_maintenance import OptimizeContent

    body = OptimizeContent.model_validate(payload)
    tenant, _project = _require_project(ctx)
    status, response = await exchange(
        "POST",
        "/api/v1/ai/optimize",
        body=body.model_dump(),
        headers={"X-Tenant-ID": tenant},
    )
    document = object_body(status, response, _("Memory operation failed"))
    return {"content": document["content"]}


OPERATIONS = {
    "app.knowledge.memories.read": list_project_memories,
    "app.knowledge.memories.write": save_memory,
    "app.knowledge.entities.list": list_entities,
    "app.knowledge.entities.types": entity_types,
    "app.knowledge.entities.relationships": entity_relationships,
    "app.knowledge.memories.delete": delete_memory,
    "app.knowledge.memories.reindex": reindex_memory,
    "app.knowledge.memories.index_status": read_index_task,
    "app.knowledge.memories.optimize": optimize_content,
    "app.knowledge.graph.read": read_graph,
    "app.knowledge.graph.subgraph": read_subgraph,
    "app.knowledge.search": search,
}
