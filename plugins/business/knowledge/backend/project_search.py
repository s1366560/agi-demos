"""Run the original search modes under the signed operation's project scope."""

from typing import TYPE_CHECKING, Any, Literal

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict

from src.host.operations.remote_application_commands import application_result
from src.infrastructure.i18n import gettext as _

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext, Progress


class Search(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mode: Literal["advanced", "graph-traversal", "community", "temporal", "faceted"]
    parameters: dict[str, Any]


async def search(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    request = Search.model_validate(payload)
    if not ctx.scope.tenant_id or not ctx.scope.project_id:
        raise HTTPException(403, _("Project membership is required"))
    scope = {"tenant_id": ctx.scope.tenant_id, "project_id": ctx.scope.project_id}
    if any(request.parameters.get(key, value) != value for key, value in scope.items()):
        raise HTTPException(403, _("Search scope does not match the project"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=ctx.request.app),
        base_url="http://localhost",
        trust_env=False,
    ) as client:
        response = await client.post(
            "/api/v1/search-enhanced/" + request.mode,
            json={**request.parameters, **scope},
            headers={"authorization": ctx.request.headers.get("authorization", "")},
        )
    if not response.is_success:
        raise HTTPException(response.status_code, _("Failed to search the project"))
    return application_result(response.json())
