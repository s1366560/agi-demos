"""Export a page already filtered by Workspace Core for this caller."""

import csv
import io
from typing import TYPE_CHECKING, Annotated, Any
from urllib.parse import quote, urlencode

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.host.packages.project_plugin_installation import ProjectPluginInstallationService
from src.infrastructure.adapters.primary.web.dependencies.plugin_scope_auth_v2 import (
    project_package_actor_can_execute,
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
    limit: int = Field(default=8, ge=1, le=8)


async def read_directory_operation(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    try:
        query = DirectoryQuery.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(422, _("Invalid workspace directory query")) from exc
    upstream = await _read_core(ctx, query=urlencode(query.model_dump()).encode())
    try:
        if upstream.status_code != 200:
            raise HTTPException(upstream.status_code, _("Workspace directory unavailable"))
        return {"rows": await _authorized_page(upstream, ctx.scope)}
    finally:
        await upstream.aclose()


class _WorkspaceQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    workspace_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")


class _WorkspaceDetail(_WorkspaceRow):
    description: str | None = Field(default=None, max_length=65536)


async def _read_core(
    ctx: "PackageOperationContext", *, workspace: str | None = None, query: bytes = b""
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
    try:
        core = workspace_core_client_v2_from_request(ctx.request)
        return await core.proxy_request(
            method="GET",
            path=path,
            query=query,
            body=b"",
            headers=[
                ("X-MemStack-Tenant-ID", tenant),
                ("X-MemStack-Project-ID", project),
                ("X-MemStack-User-ID", ctx.user.id),
                ("X-MemStack-User-Is-Superuser", "true" if ctx.user.is_superuser else "false"),
            ],
        )
    except (RuntimeError, TypeError, WorkspaceCoreClientError) as exc:
        raise HTTPException(503, _("Workspace Core is unavailable")) from exc


async def read_workspace_operation(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    try:
        query = _WorkspaceQuery.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(422, _("Invalid workspace detail query")) from exc
    upstream = await _read_core(ctx, workspace=query.workspace_id)
    try:
        if upstream.status_code != 200:
            raise HTTPException(upstream.status_code, _("Workspace unavailable"))
        detail = _WorkspaceDetail.model_validate_json(await _body(upstream))
        if (detail.tenant_id, detail.project_id, detail.id) != (
            ctx.scope.tenant_id,
            ctx.scope.project_id,
            query.workspace_id,
        ):
            raise OptionalBusinessError("forbidden", "Workspace detail scope mismatch")
        return detail.model_dump(exclude={"tenant_id", "project_id"})
    finally:
        await upstream.aclose()


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
                "app.workspace.detail.read",
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
