"""Access the workspace-owned collaboration resources through the scoped Core authority."""

import json
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlencode
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from plugins.business.workspace.command_models import _ROOT, _SCOPED, _WRITES
from src.infrastructure.i18n import gettext as _

from .collaboration import Identifier
from .workspace_directory_export import _body, _request_core, read_workspace_operation

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext, Progress

class SurfaceQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    workspace_id: Identifier
    resource: str = Field(max_length=128)
    ids: list[Identifier] = Field(default_factory=list, max_length=2)
    query: dict[str, str] = Field(default_factory=dict, max_length=12)


class SurfaceChange(SurfaceQuery):
    method: Literal["POST", "PATCH", "DELETE"]
    fields: dict[str, Any] | None = None
    request_id: str = Field(min_length=36, max_length=36)
    revision: int = Field(ge=0)


async def _call(ctx: "PackageOperationContext", args: SurfaceQuery) -> dict[str, Any]:
    change = args if isinstance(args, SurfaceChange) else None
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
    if args.query.keys() - allowed or any(len(s) > 512 for s in args.query.values()):
        raise HTTPException(422, _("Invalid workspace query"))
    root_route = bool(parts and parts[0] in {"tasks", "plan", "topology", "autonomy"})
    if root_route:
        await read_workspace_operation(ctx, {"workspace_id": args.workspace_id}, None)
    response = await _request_core(
        ctx,
        workspace=args.workspace_id,
        child=path,
        task_route=root_route,
        query=urlencode(args.query).encode(),
        method=change.method if change else "GET",
        data=change.fields if change else None,
        request_id=UUID(change.request_id) if change else None,
        expected_revision=change.revision if change else None,
    )
    try:
        raw = await _body(response)
        if not 200 <= response.status_code < 300:
            raise HTTPException(response.status_code, _("Workspace Core rejected this operation"))
        return {
            "data": json.loads(raw) if raw else None,
            "status": response.status_code,
            "headers": {
                key: val
                for key, val in response.headers.items()
                if key.lower() in {"etag", "x-workspace-revision", "x-workspace-cursor"}
            },
        }
    finally:
        await response.aclose()


async def read_surface(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.workspace.guest.commands import read_surface as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)


async def change_surface(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.workspace.guest.commands import change_surface as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)
