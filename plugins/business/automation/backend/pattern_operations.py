"""Use the same membership and administrative checks as the workflow pattern API."""

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from src.infrastructure.adapters.primary.web.routers.agent import patterns
from src.infrastructure.adapters.primary.web.workflow_pattern_application_authority_v2 import (
    workflow_pattern_authority,
)

if TYPE_CHECKING:
    from src.host.operations.application_commands import Progress
    from src.host.operations.tenant_commands import TenantPackageContext


class ListPatterns(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=100)


class DeletePattern(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    pattern_id: str = Field(min_length=1, max_length=128)


async def raw_list_patterns(ctx: "TenantPackageContext", payload: dict[str, Any]) -> dict[str, Any]:
    query = ListPatterns.model_validate(payload)
    tenant = ctx.scope.tenant_id
    async with workflow_pattern_authority(ctx.request, ctx.user, ctx.db, tenant) as authority:
        result = await patterns.list_patterns(tenant, query.page, query.page_size, None, authority)
    return {"document": result.model_dump(mode="json"), "tenant_id": tenant}


async def raw_delete_pattern(ctx: "TenantPackageContext", pattern_id: str) -> dict[str, Any]:
    tenant = ctx.scope.tenant_id
    async with workflow_pattern_authority(ctx.request, ctx.user, ctx.db, tenant) as authority:
        deleted = await patterns.delete_pattern(pattern_id, tenant, authority)
    return {"document": deleted, "tenant_id": tenant}


async def list_patterns(
    ctx: "TenantPackageContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.automation.guest.commands import list_patterns as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)


async def delete_pattern(
    ctx: "TenantPackageContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.automation.guest.commands import delete_pattern as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)


PATTERN_OPERATIONS = {
    "app.automation.patterns.read": list_patterns,
    "app.automation.patterns.delete": delete_pattern,
}
