"""Signed account commands, authorized by the existing tenant billing authority."""

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict

from plugins.business.billing.backend.authority import billing_application_authority_context_v2
from plugins.business.billing.backend.http import get_billing_info, list_invoices, upgrade_plan
from src.domain.ports.services.tenant_entitlement_port import TenantQuotaAccessDenied

if TYPE_CHECKING:
    from src.host.operations.application_commands import (
        Operation,
        PackageOperationContext,
        Progress,
    )


class _AccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _AccountView(_AccountRequest):
    full_history: bool = False


class _Plan(_AccountRequest):
    plan: Literal["free", "pro", "enterprise"]


async def read_account(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    view = _AccountView.model_validate(payload)
    async with billing_application_authority_context_v2(
        request=ctx.request, current_user=ctx.user, db=ctx.db, tenant_id=ctx.scope.tenant_id
    ) as authority:
        account = await get_billing_info(ctx.scope.tenant_id, authority)
        if not view.full_history:
            return account
        invoices = await list_invoices(ctx.scope.tenant_id, authority)
        try:
            await authority.services.billing.entitlements.authorize_quota_change()
        except TenantQuotaAccessDenied:
            role = "admin"
        else:
            role = "owner"
        return {**account, **invoices, "membership_role": role}


async def change_plan(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    plan = _Plan.model_validate(payload)
    async with billing_application_authority_context_v2(
        request=ctx.request, current_user=ctx.user, db=ctx.db, tenant_id=ctx.scope.tenant_id
    ) as authority:
        return await upgrade_plan(ctx.scope.tenant_id, plan.model_dump(), authority)


BILLING_OPERATIONS: dict[str, "Operation"] = {
    "app.billing.account.read": read_account,
    "app.billing.plan.write": change_plan,
}
