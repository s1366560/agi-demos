"""Tenant-bound commands for the original runtime pool dashboard."""

from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import quote

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.host.operations.remote_application_commands import application_result
from src.infrastructure.i18n import gettext as _

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext, Progress


class PoolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Read(PoolInput):
    resource: Literal["status", "instances", "metrics"]
    tier: Literal["hot", "warm", "cold"] | None = None
    status: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class Control(PoolInput):
    action: Literal["pause", "resume", "terminate"]
    instance_key: str = Field(min_length=1, max_length=512, pattern=r"^[^/\\?#%]+$")
    graceful: bool = True


class Tier(PoolInput):
    project_id: str = Field(min_length=1, max_length=128, pattern=r"^[\w-]+$")
    tier: Literal["hot", "warm", "cold"]


async def _request(
    ctx: "PackageOperationContext",
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    body: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not ctx.scope.tenant_id:
        raise HTTPException(403, _("Tenant membership is required"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=ctx.request.app),
        base_url="http://localhost",
        trust_env=False,
    ) as client:
        response = await client.request(
            method,
            f"/api/v1/admin/pool/{path}",
            params={**(params or {}), "scope": "tenant", "tenant_id": ctx.scope.tenant_id},
            json=body,
            headers={"authorization": ctx.request.headers.get("authorization", "")},
        )
    if response.status_code == 403:
        # Preserve the original dashboard's permission state across the signed command channel.
        return {"forbidden": True}
    if not response.is_success:
        raise HTTPException(response.status_code, _("Runtime pool operation failed"))
    return application_result(response.json())


async def read(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    query = Read.model_validate(payload)
    params = query.model_dump(exclude={"resource"}, exclude_none=True)
    return await _request(
        ctx, "GET", query.resource, params=params if query.resource == "instances" else None
    )


async def control(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    command = Control.model_validate(payload)
    key = command.instance_key
    if key in {".", ".."}:
        raise HTTPException(422, _("Invalid instance key"))
    path = f"instances/{quote(key, safe='')}"
    if command.action == "terminate":
        return await _request(ctx, "DELETE", path, params={"graceful": command.graceful})
    return await _request(ctx, "POST", f"{path}/{command.action}")


async def set_tier(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    command = Tier.model_validate(payload)
    return await _request(
        ctx, "POST", f"projects/{command.project_id}/tier", body={"tier": command.tier}
    )
