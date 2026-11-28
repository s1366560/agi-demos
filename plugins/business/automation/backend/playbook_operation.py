"""Read the active project's playbooks through its existing membership authority."""

from typing import TYPE_CHECKING, Any

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.reflection_application_authority_v2 import (
    reflection_authority,
)
from src.infrastructure.adapters.primary.web.routers.reflection import (
    list_playbooks,
    list_reflection_verdicts,
)

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext, Progress


async def raw_playbooks(ctx: "PackageOperationContext") -> dict[str, Any]:
    scope = ScopeV2(
        kind=ScopeKindV2.PROJECT, tenant_id=ctx.scope.tenant_id, project_id=ctx.scope.project_id
    )
    async with reflection_authority(ctx.request, ctx.user, ctx.db, scope) as authority:
        result = await list_playbooks(ctx.scope.project_id, 200, ctx.user, authority)
    return result.model_dump()


async def raw_verdicts(ctx: "PackageOperationContext") -> dict[str, Any]:
    scope = ScopeV2(
        kind=ScopeKindV2.PROJECT, tenant_id=ctx.scope.tenant_id, project_id=ctx.scope.project_id
    )
    async with reflection_authority(ctx.request, ctx.user, ctx.db, scope) as authority:
        result = await list_reflection_verdicts(ctx.scope.project_id, 200, ctx.user, authority)
    return {"items": [item.model_dump() for item in result.items]}


async def read_playbooks(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.automation.guest.commands import read_playbooks as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)


async def read_verdicts(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.automation.guest.commands import read_verdicts as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)
