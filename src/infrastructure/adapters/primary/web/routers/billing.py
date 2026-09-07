# pyright: reportImportCycles=false
"""Billing and invoice management router."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from src.infrastructure.adapters.primary.web.billing_application_authority_v2 import (
    BillingApplicationAuthorityV2,
    billing_application_authority_dependency_v2,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.billing_services import (
    BillingAdminAccessDeniedV2,
    BillingInvalidPlanV2,
    BillingOwnerAccessDeniedV2,
    BillingTenantNotFoundV2,
)

router = APIRouter(prefix="/api/v1/tenants", tags=["billing"])


@router.get("/{tenant_id}/billing")
async def get_billing_info(
    tenant_id: str,
    billing_application: BillingApplicationAuthorityV2 = Depends(
        billing_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    """Get billing information for a tenant."""
    try:
        return await billing_application.services.billing.get_billing_info(
            user_id=str(billing_application.current_user.id),
            tenant_id=tenant_id,
        )
    except BillingAdminAccessDeniedV2 as exc:
        raise HTTPException(status_code=403, detail=_("Access denied")) from exc
    except BillingTenantNotFoundV2 as exc:
        raise HTTPException(status_code=404, detail=_("Tenant not found")) from exc


@router.get("/{tenant_id}/invoices")
async def list_invoices(
    tenant_id: str,
    billing_application: BillingApplicationAuthorityV2 = Depends(
        billing_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    """List all invoices for a tenant."""
    try:
        return await billing_application.services.billing.list_invoices(
            user_id=str(billing_application.current_user.id),
            tenant_id=tenant_id,
        )
    except BillingAdminAccessDeniedV2 as exc:
        raise HTTPException(status_code=403, detail=_("Access denied")) from exc
    except BillingTenantNotFoundV2 as exc:
        raise HTTPException(status_code=404, detail=_("Tenant not found")) from exc


@router.post("/{tenant_id}/upgrade")
async def upgrade_plan(
    tenant_id: str,
    plan_data: dict[str, Any],
    billing_application: BillingApplicationAuthorityV2 = Depends(
        billing_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    """Upgrade tenant plan."""
    try:
        tenant = await billing_application.services.billing.upgrade_plan(
            user_id=str(billing_application.current_user.id),
            tenant_id=tenant_id,
            plan_data=plan_data,
        )
    except BillingOwnerAccessDeniedV2 as exc:
        raise HTTPException(
            status_code=403,
            detail=_("Only owner can upgrade plan"),
        ) from exc
    except BillingTenantNotFoundV2 as exc:
        raise HTTPException(status_code=404, detail=_("Tenant not found")) from exc
    except BillingInvalidPlanV2 as exc:
        raise HTTPException(status_code=400, detail=_("Invalid billing plan")) from exc

    await billing_application.db.commit()
    return {
        "message": _("Plan upgraded successfully"),
        "tenant": tenant,
    }
