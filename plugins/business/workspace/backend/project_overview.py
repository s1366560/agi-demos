"""Project overview from the authenticated project and installed Knowledge authorities."""

from typing import TYPE_CHECKING, Any

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
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.workspace.guest.commands import read_overview as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)
