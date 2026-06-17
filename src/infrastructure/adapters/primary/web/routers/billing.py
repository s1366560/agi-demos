"""Billing and invoice management router."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    Invoice,
    Memory,
    Project,
    Tenant,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.i18n import gettext as _

router = APIRouter(prefix="/api/v1/tenants", tags=["billing"])

BILLING_ADMIN_ROLES = frozenset({"admin", "owner"})
BILLING_OWNER_ROLES = frozenset({"owner"})
PLAN_STORAGE_LIMITS = {
    "free": 10 * 1024 * 1024 * 1024,
    "pro": 100 * 1024 * 1024 * 1024,
    "enterprise": 1024 * 1024 * 1024 * 1024,
}


async def _require_billing_role(
    db: AsyncSession,
    current_user: User,
    tenant_id: str,
    *,
    allowed_roles: frozenset[str],
    denial_detail: str,
) -> None:
    user_tenant_result = await db.execute(
        refresh_select_statement(
            select(UserTenant).where(
                UserTenant.user_id == current_user.id,
                UserTenant.tenant_id == tenant_id,
            )
        )
    )
    user_tenant = user_tenant_result.scalar_one_or_none()

    if not user_tenant or user_tenant.role not in allowed_roles:
        raise HTTPException(status_code=403, detail=_(denial_detail))


async def _get_billing_tenant_or_404(db: AsyncSession, tenant_id: str) -> Tenant:
    tenant_result = await db.execute(
        refresh_select_statement(select(Tenant).where(Tenant.id == tenant_id))
    )
    tenant = tenant_result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail=_("Tenant not found"))
    return tenant


@router.get("/{tenant_id}/billing")
async def get_billing_info(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get billing information for a tenant."""

    await _require_billing_role(
        db,
        current_user,
        tenant_id,
        allowed_roles=BILLING_ADMIN_ROLES,
        denial_detail="Access denied",
    )
    tenant = await _get_billing_tenant_or_404(db, tenant_id)
    # Get invoices
    invoices_result = await db.execute(
        refresh_select_statement(
            select(Invoice)
            .where(Invoice.tenant_id == tenant_id)
            .order_by(Invoice.created_at.desc())
            .limit(12)
        )
    )
    invoices = invoices_result.scalars().all()

    # Calculate usage statistics
    projects_result = await db.execute(
        refresh_select_statement(select(Project).where(Project.tenant_id == tenant_id))
    )
    projects = projects_result.scalars().all()

    project_ids = [p.id for p in projects]

    # Count memories
    memories_result = await db.execute(
        refresh_select_statement(
            select(func.count(Memory.id)).where(Memory.project_id.in_(project_ids))
        )
    )
    memory_count = memories_result.scalar() or 0

    # Count users with access
    users_result = await db.execute(
        refresh_select_statement(
            select(func.count(func.distinct(UserProject.user_id))).where(
                UserProject.project_id.in_(project_ids)
            )
        )
    )
    user_count = users_result.scalar() or 0

    return {
        "tenant": {
            "id": tenant.id,
            "name": tenant.name,
            "plan": getattr(tenant, "plan", "free"),
            "storage_limit": getattr(tenant, "max_storage", 10737418240),
        },
        "usage": {
            "projects": len(projects),
            "memories": memory_count,
            "users": user_count,
            "storage": sum(getattr(p, "storage_used", 0) or 0 for p in projects),
        },
        "invoices": [
            {
                "id": inv.id,
                "amount": inv.amount,
                "currency": inv.currency,
                "status": inv.status,
                "period_start": inv.period_start.isoformat(),
                "period_end": inv.period_end.isoformat(),
                "created_at": inv.created_at.isoformat(),
                "paid_at": inv.paid_at.isoformat() if inv.paid_at else None,
                "invoice_url": inv.invoice_url,
            }
            for inv in invoices
        ],
    }


@router.get("/{tenant_id}/invoices")
async def list_invoices(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List all invoices for a tenant."""

    await _require_billing_role(
        db,
        current_user,
        tenant_id,
        allowed_roles=BILLING_ADMIN_ROLES,
        denial_detail="Access denied",
    )
    _ = await _get_billing_tenant_or_404(db, tenant_id)

    result = await db.execute(
        refresh_select_statement(
            select(Invoice)
            .where(Invoice.tenant_id == tenant_id)
            .order_by(Invoice.created_at.desc())
        )
    )
    invoices = result.scalars().all()

    return {
        "invoices": [
            {
                "id": inv.id,
                "amount": inv.amount,
                "currency": inv.currency,
                "status": inv.status,
                "period_start": inv.period_start.isoformat(),
                "period_end": inv.period_end.isoformat(),
                "created_at": inv.created_at.isoformat(),
                "paid_at": inv.paid_at.isoformat() if inv.paid_at else None,
                "invoice_url": inv.invoice_url,
            }
            for inv in invoices
        ]
    }


@router.post("/{tenant_id}/upgrade")
async def upgrade_plan(
    tenant_id: str,
    plan_data: dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Upgrade tenant plan."""

    await _require_billing_role(
        db,
        current_user,
        tenant_id,
        allowed_roles=BILLING_OWNER_ROLES,
        denial_detail="Only owner can upgrade plan",
    )

    tenant = await _get_billing_tenant_or_404(db, tenant_id)

    new_plan = plan_data.get("plan") or "pro"
    if not isinstance(new_plan, str) or new_plan not in PLAN_STORAGE_LIMITS:
        raise HTTPException(status_code=400, detail=_("Invalid billing plan"))

    tenant.plan = new_plan
    tenant.max_storage = PLAN_STORAGE_LIMITS[new_plan]

    await db.commit()
    await db.refresh(tenant)

    return {
        "message": "Plan upgraded successfully",
        "tenant": {
            "id": tenant.id,
            "name": tenant.name,
            "plan": getattr(tenant, "plan", "free"),
            "storage_limit": getattr(tenant, "max_storage", 10737418240),
        },
    }
