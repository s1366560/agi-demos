"""Export a page already filtered by Workspace Core for this caller."""

import csv
import io
from typing import Annotated, Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
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
from src.infrastructure.workspace_core.client import WorkspaceCoreProxyResponse


class _WorkspaceRow(BaseModel):
    model_config = ConfigDict(strict=True)
    tenant_id: str
    project_id: str
    id: str = Field(max_length=128)
    name: str = Field(max_length=255)
    office_status: str = Field(max_length=128)
    is_archived: bool


_PAGE = TypeAdapter[list[_WorkspaceRow]](Annotated[list[_WorkspaceRow], Field(max_length=500)])


async def _authorized_page(
    upstream: WorkspaceCoreProxyResponse, scope: ScopeBindingV2
) -> list[dict[str, Any]]:
    raw = bytearray()
    async for chunk in upstream.aiter_raw():
        if len(raw) + len(chunk) > 8 * 1024 * 1024:
            raise HTTPException(413, _("Reduce the workspace export page size"))
        raw.extend(chunk)
    rows = _PAGE.validate_json(raw)
    if any((r.tenant_id, r.project_id) != (scope.tenant_id, scope.project_id) for r in rows):
        raise ValueError("workspace directory scope mismatch")
    return [r.model_dump(exclude={"tenant_id", "project_id"}) for r in rows]


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
            if package.worker is not None or package.approved_permissions != frozenset(
                {"tools.execute"}
            ):
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
