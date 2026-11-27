"""Signed account commands, authorized by the existing tenant billing authority."""

from typing import TYPE_CHECKING, Any

from plugins.business.billing.backend.authority import billing_application_authority_context_v2
from plugins.business.billing.backend.http import get_billing_info, list_invoices, upgrade_plan
from src.domain.ports.services.tenant_entitlement_port import TenantQuotaAccessDenied

if TYPE_CHECKING:
    from src.host.operations.application_commands import (
        Operation,
        PackageOperationContext,
        Progress,
    )


async def raw_account_parts(ctx: "PackageOperationContext", full_history: bool) -> dict[str, Any]:
    async with billing_application_authority_context_v2(
        request=ctx.request, current_user=ctx.user, db=ctx.db, tenant_id=ctx.scope.tenant_id
    ) as authority:
        account = await get_billing_info(ctx.scope.tenant_id, authority)
        if not full_history:
            return {"account": account, "invoices": None, "role": None}
        invoices = await list_invoices(ctx.scope.tenant_id, authority)
        try:
            await authority.services.billing.entitlements.authorize_quota_change()
        except TenantQuotaAccessDenied:
            role = "admin"
        else:
            role = "owner"
        return {"account": account, "invoices": invoices, "role": role}


async def raw_change_plan(ctx: "PackageOperationContext", plan: dict[str, Any]) -> dict[str, Any]:
    async with billing_application_authority_context_v2(
        request=ctx.request, current_user=ctx.user, db=ctx.db, tenant_id=ctx.scope.tenant_id
    ) as authority:
        return await upgrade_plan(ctx.scope.tenant_id, plan, authority)


async def read_account(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.billing.guest.commands import read_account as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)


async def change_plan(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from plugins.business.billing.guest.commands import change_plan as shaped
    from src.host.operations.business_guest.loopback import call_in_guest

    return await call_in_guest(ctx, shaped, payload, progress)


BILLING_OPERATIONS: dict[str, "Operation"] = {
    "app.billing.account.read": read_account,
    "app.billing.plan.write": change_plan,
}
