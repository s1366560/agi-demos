"""Export a page already filtered by Workspace Core for this caller."""

import csv
import io
import json
from collections.abc import AsyncIterable
from typing import TYPE_CHECKING, Annotated, Any, Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.host.packages.project_plugin_installation import ProjectPluginInstallationService
from src.infrastructure.adapters.primary.web.dependencies.plugin_scope_auth_v2 import (
    project_package_actor_can_execute,
)
from src.infrastructure.adapters.primary.web.routers.workspaces import (
    WorkspaceCreateRequest,
    WorkspaceUpdateRequest,
)
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.project_package_execution import invoke_project_tool
from src.infrastructure.plugins.v2.runtime_context import RuntimeV2Error
from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
    OptionalBusinessError,
    ScopeBindingV2,
    SignedPackageBytesV2,
)
from src.infrastructure.workspace_core.client import (
    WorkspaceCoreClientError,
    WorkspaceCoreProxyResponse,
)
from src.infrastructure.workspace_core.project_membership import project_membership_header

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext
    from src.infrastructure.plugins.v2.project_package_execution import Progress


class _WorkspaceRow(BaseModel):
    model_config = ConfigDict(strict=True)
    tenant_id: str
    project_id: str
    id: str = Field(max_length=128)
    name: str = Field(max_length=255)
    office_status: str = Field(max_length=128)
    is_archived: bool


_PAGE = TypeAdapter[list[_WorkspaceRow]](Annotated[list[_WorkspaceRow], Field(max_length=500)])


async def _body(upstream: WorkspaceCoreProxyResponse) -> bytes:
    raw = bytearray()
    async for chunk in upstream.aiter_raw():
        if len(raw) + len(chunk) > 8 * 1024 * 1024:
            raise HTTPException(413, _("Reduce the workspace export page size"))
        raw.extend(chunk)
    return bytes(raw)


async def _authorized_page(
    upstream: WorkspaceCoreProxyResponse, scope: ScopeBindingV2
) -> list[dict[str, Any]]:
    rows = _PAGE.validate_json(await _body(upstream))
    if any((r.tenant_id, r.project_id) != (scope.tenant_id, scope.project_id) for r in rows):
        raise ValueError("workspace directory scope mismatch")
    return [r.model_dump(exclude={"tenant_id", "project_id"}) for r in rows]


class DirectoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=8, ge=1, le=100)
    cards: bool = False


async def core_document(ctx: "PackageOperationContext", params: dict[str, Any]) -> dict[str, Any]:
    """Return the Workspace Core document before the guest projects public fields."""
    request_id = params.get("request_id")
    response = await _request_core(
        ctx,
        method=params.get("method") or "GET",
        workspace=params.get("workspace"),
        child=tuple(params.get("child") or ()),
        task_route=bool(params.get("task_route")),
        query=str(params.get("query") or "").encode(),
        data=params.get("data"),
        request_id=UUID(request_id) if request_id else None,
        expected_revision=params.get("expected_revision"),
        read_authority=bool(params.get("read_authority")),
    )
    try:
        raw = await _body(response)
        return {
            "status": response.status_code,
            "body": json.loads(raw) if raw else None,
            "headers": {key: value for key, value in response.headers.items()},
        }
    finally:
        await response.aclose()


async def read_directory_operation(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.workspace.guest.commands import read_directory
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, read_directory, payload, progress)


class _WorkspaceQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    workspace_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")


class _WorkspaceRead(_WorkspaceQuery):
    include_revision: bool = False


class _WorkspaceAuthority(BaseModel):
    model_config = ConfigDict(strict=True)
    tenant_id: str
    project_id: str
    workspace_id: str
    revision: int = Field(ge=0)


class _WorkspaceDetail(_WorkspaceRow):
    description: str | None = Field(default=None, max_length=65536)


async def _request_core(
    ctx: "PackageOperationContext",
    *,
    workspace: str | None = None,
    query: bytes = b"",
    method: Literal["GET", "PATCH", "POST", "DELETE"] = "GET",
    read_authority: bool = False,
    child: tuple[str, ...] = (),
    task_route: bool = False,
    data: dict[str, Any] | None = None,
    upload: AsyncIterable[bytes] | None = None,
    content_type: str = "application/json",
    request_id: UUID | None = None,
    expected_revision: int | None = None,
) -> WorkspaceCoreProxyResponse:
    from src.infrastructure.adapters.primary.web.workspace_core_runtime_resolver import (
        workspace_core_client_v2_from_request,
    )

    tenant, project = ctx.scope.tenant_id, ctx.scope.project_id
    if not tenant or not project:
        raise HTTPException(403, _("A project is required to read its workspace directory"))
    path = f"/api/v1/tenants/{quote(tenant, safe='')}/projects/{quote(project, safe='')}/workspaces"
    if workspace:
        path += "/" + quote(workspace, safe="")
    if task_route:
        path = "/api/v1/workspaces/" + quote(workspace or "", safe="")
    if child:
        path += "/" + "/".join(quote(segment, safe="") for segment in child)
    if read_authority:
        path += "/collaboration/authority"
    headers = [
        ("X-MemStack-Tenant-ID", tenant),
        ("X-MemStack-Project-ID", project),
        ("X-MemStack-User-ID", ctx.user.id),
        ("X-MemStack-User-Is-Superuser", "true" if ctx.user.is_superuser else "false"),
    ]
    if request_id is not None:
        headers.extend([("Idempotency-Key", str(request_id)), ("Content-Type", content_type)])
    if expected_revision is not None:
        headers.extend(
            [("If-Match", str(expected_revision)), ("X-Expected-Revision", str(expected_revision))]
        )
    if method == "POST":
        headers.append(("X-MemStack-User-Email", ctx.user.email))
        if membership := await project_membership_header(ctx.db, ctx.user.id, project):
            headers.append(membership)
    try:
        core = workspace_core_client_v2_from_request(ctx.request)
        return await core.proxy_request(
            method=method,
            path=path,
            query=query,
            body=upload
            if upload is not None
            else json.dumps(data).encode()
            if data is not None
            else b"",
            headers=headers,
        )
    except (RuntimeError, TypeError, WorkspaceCoreClientError) as exc:
        raise HTTPException(503, _("Workspace Core is unavailable")) from exc


async def read_workspace_operation(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.workspace.guest.commands import read_workspace
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, read_workspace, payload, progress)


async def _workspace_result(
    ctx: "PackageOperationContext", upstream: WorkspaceCoreProxyResponse, workspace: str | None
) -> dict[str, Any]:
    try:
        if upstream.status_code == 409:
            raise HTTPException(409, _("Workspace changed. Reload its settings and try again."))
        if upstream.status_code not in (200, 201):
            raise HTTPException(upstream.status_code, _("Workspace Core rejected this operation"))
        detail = _WorkspaceDetail.model_validate_json(await _body(upstream))
        if (detail.tenant_id, detail.project_id) != (ctx.scope.tenant_id, ctx.scope.project_id) or (
            workspace is not None and detail.id != workspace
        ):
            raise OptionalBusinessError("forbidden", "Workspace detail scope mismatch")
        return detail.model_dump(exclude={"tenant_id", "project_id"})
    finally:
        await upstream.aclose()


class _CreateRequest(WorkspaceCreateRequest):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID


class _UpdateRequest(_WorkspaceQuery, WorkspaceUpdateRequest):
    request_id: UUID
    expected_revision: int = Field(ge=0)
    model_config = ConfigDict(extra="forbid", strict=False)


async def create_workspace_operation(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.workspace.guest.commands import create_workspace
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, create_workspace, payload, progress)


async def update_workspace_operation(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.workspace.guest.commands import update_workspace
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, update_workspace, payload, progress)


def _check_csv(document: object, expected_rows: int, columns: int | None) -> tuple[str, int]:
    if (
        not isinstance(document, str)
        or len(document.encode()) > 65536
        or not document.endswith("\n")
    ):
        raise ValueError("invalid workspace CSV")
    parsed = list(csv.reader(io.StringIO(document, newline=""), strict=True))
    if len(parsed) != expected_rows or not parsed:
        raise ValueError("invalid workspace CSV row count")
    width = columns if columns is not None else len(parsed[0])
    if not 1 <= width <= 32 or any(len(row) != width for row in parsed):
        raise ValueError("invalid workspace CSV column count")
    if any(
        cell.lstrip().startswith(("=", "+", "-", "@")) or cell.startswith(("\t", "\r", "\n"))
        for row in parsed
        for cell in row
    ):
        raise ValueError("unsafe spreadsheet cell")
    return document, width


async def export_workspace_directory(
    upstream: WorkspaceCoreProxyResponse,
    *,
    db: AsyncSession,
    actor: User,
    tenant: str,
    project: str,
    plugin: str,
    keys: tuple[str, ...],
) -> Response:
    scope = ScopeBindingV2(tenant_id=tenant, project_id=project)
    try:
        allowed = await project_package_actor_can_execute(
            db,
            current_user=actor,
            requested_scope=ScopeV2(kind=ScopeKindV2.PROJECT, tenant_id=tenant, project_id=project),
        )
        if not allowed:
            raise HTTPException(
                403, _("Workspace export requires project package execution access")
            )
        rows = await _authorized_page(upstream, scope)
        service = ProjectPluginInstallationService(db, scope, keys, actor_id=actor.id)

        async def render(package: SignedPackageBytesV2) -> str:
            if package.worker is not None or not package.approved_permissions <= {
                "tools.execute",
                "ui.slot",
                "app.workspace.directory.read",
                "app.workspace.blackboard.read",
                "app.workspace.blackboard.write",
                "app.workspace.chat.read",
                "app.workspace.chat.send",
                "app.workspace.overview.read",
                "app.workspace.detail.read",
                "app.workspace.create",
                "app.workspace.settings.update",
                "app.workspace.members.read",
                "app.workspace.members.write",
                "app.workspace.posts.read",
                "app.workspace.posts.write",
                "app.workspace.tasks.read",
                "app.workspace.tasks.write",
            }:
                raise ValueError("workspace exporters only accept isolated computation")
            parts: list[str] = []
            columns = None
            for i in range(0, max(1, len(rows)), 8):
                batch = rows[i : i + 8]
                data = await invoke_project_tool(
                    package, scope, "export_csv", {"header": i == 0, "rows": batch}
                )
                fragment, columns = _check_csv(data.get("csv"), len(batch) + int(i == 0), columns)
                parts.append(fragment)
            return "".join(parts)

        result = await service.call_active(plugin, render)
    except RuntimeV2Error as exc:
        raise HTTPException(403, _("Workspace export is unavailable in this project")) from exc
    except (ValueError, KeyError, csv.Error, OptionalBusinessError) as exc:
        raise HTTPException(
            409, _("Workspace export package could not produce this report")
        ) from exc
    finally:
        await upstream.aclose()
    return Response(
        result,
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="workspaces.csv"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
