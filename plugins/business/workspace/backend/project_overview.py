"""Project overview from the authenticated project and installed Knowledge authorities."""

import asyncio
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx
from fastapi import HTTPException

from src.host.operations.remote_application_commands import application_result
from src.infrastructure.i18n import gettext as _

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext, Progress


def _read(response: httpx.Response) -> dict[str, Any]:
    if not response.is_success:
        raise HTTPException(response.status_code, _("Project overview is unavailable"))
    return application_result(response.json())


def _recent(page: dict[str, Any], project: str) -> dict[str, Any]:
    if any(row["project_id"] != project for row in page["memories"]):
        raise HTTPException(502, _("Memory response scope mismatch"))
    fields = (
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
    return {
        "memories": [{key: row.get(key) for key in fields} for row in page["memories"]],
        "total": page["total"],
    }


async def read_overview(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    tenant, project = ctx.scope.tenant_id, ctx.scope.project_id
    if not tenant or not project:
        raise HTTPException(403, _("Project membership is required"))
    if payload:
        raise HTTPException(422, _("Project overview does not accept parameters"))
    path = "/api/v1/projects/" + quote(project, safe="")
    scope = {"tenant_id": tenant, "project_id": project}
    packages = "/api/v1/platform-plugins/v2/optional-business"
    from src.host.operations.admitted_loopback import admitted_client

    async with admitted_client(ctx) as client:
        meta, stats, available = await asyncio.gather(
            client.get(path, params={"tenant_id": tenant}),
            client.get(path + "/stats"),
            client.get(packages + "/", params=scope),
        )
        info = _read(meta)
        if (info["id"], info["tenant_id"]) != (project, tenant):
            raise HTTPException(403, _("Project scope mismatch"))
        counters = _read(stats)
        knowledge = next(
            (
                row
                for row in _read(available)["items"]
                if row["plugin_id"] == "memstack-knowledge" and row["status"] == "enabled"
            ),
            None,
        )
        recent = None
        if knowledge:
            response = await client.post(
                packages + "/memstack-knowledge/commands",
                json={
                    **scope,
                    "expected_digest": knowledge["actual_digest"],
                    "command_id": "list-memories",
                    "payload": {"page": 1, "page_size": 5},
                },
            )
            # A removed, changed or older Knowledge release may not provide this optional projection.
            if response.status_code not in {400, 403, 404, 409, 410, 422}:
                recent = _recent(_read(response), project)
    return {
        "project": {
            k: info.get(k)
            for k in ("id", "tenant_id", "name", "description", "created_at", "updated_at")
        },
        "stats": {
            k: counters[k]
            for k in (
                "memory_count",
                "storage_used",
                "storage_limit",
                "active_nodes",
                "collaborators",
            )
        },
        "recent": recent,
    }
