"""Billing and invoice management router."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    Invoice,
    Memory,
    Project,
    Tenant,
    User,
    UserProject,
)

router = APIRouter(prefix="/tenants", tags=["billing"])


@router.get("/{tenant_id}/billing")
async def get_billing_info(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get billing information for a tenant."""

    # Verify user has access to tenant (permission-first)
    from src.infrastructure.adapters.secondary.persistence.models import UserTenant

    user_tenant_result = await db.execute(
        select(UserTenant).where(
            UserTenant.user_id == current_user.id, UserTenant.tenant_id == tenant_id
        )
    )
    user_tenant = user_tenant_result.scalar_one_or_none()

    if not user_tenant or user_tenant.role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Access denied")

    # Optional tenant info; fall back to defaults if not present
    tenant_result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = tenant_result.scalar_one_or_none()
    # Get invoices
    invoices_result = await db.execute(
        select(Invoice)
        .where(Invoice.tenant_id == tenant_id)
        .order_by(Invoice.created_at.desc())
        .limit(12)
    )
    invoices = invoices_result.scalars().all()

    # Calculate usage statistics
    projects_result = await db.execute(select(Project).where(Project.tenant_id == tenant_id))
    projects = projects_result.scalars().all()

    project_ids = [p.id for p in projects]

    # Count memories
    memories_result = await db.execute(
        select(func.count(Memory.id)).where(Memory.project_id.in_(project_ids))
    )
    memory_count = memories_result.scalar() or 0

    # Count users with access
    users_result = await db.execute(
        select(func.count(func.distinct(UserProject.user_id))).where(
            UserProject.project_id.in_(project_ids)
        )
    )
    user_count = users_result.scalar() or 0

    # If no tenant record and no associated data, return defaults unless system has zero tenants
    if not tenant and not projects and not invoices:
        any_tenant = await db.execute(select(func.count(Tenant.id)))
        if (any_tenant.scalar() or 0) == 0:
            raise HTTPException(status_code=404, detail="Tenant not found")

    return {
        "tenant": {
            "id": tenant_id if not tenant else tenant.id,
            "name": None if not tenant else tenant.name,
            "plan": ("free" if not tenant else getattr(tenant, "plan", "free")),
            "storage_limit": (
                10737418240 if not tenant else getattr(tenant, "storage_limit", 10737418240)
            ),
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

    # Verify user has access to tenant (permission-first)
    from src.infrastructure.adapters.secondary.persistence.models import UserTenant

    user_tenant_result = await db.execute(
        select(UserTenant).where(
            UserTenant.user_id == current_user.id, UserTenant.tenant_id == tenant_id
        )
    )
    user_tenant = user_tenant_result.scalar_one_or_none()

    if not user_tenant or user_tenant.role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Access denied")

    # Optional existence; invoices can be listed by tenant_id regardless
    # Get invoices
    result = await db.execute(
        select(Invoice).where(Invoice.tenant_id == tenant_id).order_by(Invoice.created_at.desc())
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

    # Verify user is owner (permission-first)
    from src.infrastructure.adapters.secondary.persistence.models import UserTenant

    user_tenant_result = await db.execute(
        select(UserTenant).where(
            UserTenant.user_id == current_user.id, UserTenant.tenant_id == tenant_id
        )
    )
    user_tenant = user_tenant_result.scalar_one_or_none()

    if not user_tenant or user_tenant.role != "owner":
        raise HTTPException(status_code=403, detail="Only owner can upgrade plan")

    # Existence after permission; allow auto-create only if system has tenants
    tenant_result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = tenant_result.scalar_one_or_none()
    if not tenant:
        # Check whether any tenant exists; if none, treat as not found
        any_tenant = await db.execute(select(func.count(Tenant.id)))
        if (any_tenant.scalar() or 0) == 0:
            raise HTTPException(status_code=404, detail="Tenant not found")
        # Auto-create minimal tenant record
        tenant = Tenant(
            id=tenant_id,
            name=f"Tenant {tenant_id}",
            slug=str(tenant_id).lower().replace(" ", "-"),
            description=None,
            owner_id=current_user.id,
        )
        db.add(tenant)
        await db.flush()

    # Update plan (in a real implementation, this would integrate with payment processor)
    new_plan = plan_data.get("plan", "pro")
    tenant.plan = new_plan  # type: ignore

    # Set limits based on plan
    if new_plan == "free":
        tenant.storage_limit = 10 * 1024 * 1024 * 1024  # 10GB
    elif new_plan == "pro":
        tenant.storage_limit = 100 * 1024 * 1024 * 1024  # 100GB
    elif new_plan == "enterprise":
        tenant.storage_limit = 1024 * 1024 * 1024 * 1024  # 1TB

    await db.commit()
    await db.refresh(tenant)

    return {
        "message": "Plan upgraded successfully",
        "tenant": {
            "id": tenant.id,
            "name": tenant.name,
            "plan": getattr(tenant, "plan", "free"),
            "storage_limit": getattr(tenant, "storage_limit", 10737418240),
        },
    }
