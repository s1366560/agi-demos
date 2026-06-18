"""Tenant management API endpoints."""

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from src.application.schemas.tenant import (
    TenantCreate,
    TenantListResponse,
    TenantResponse,
    TenantUpdate,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    Memory,
    OrgGenePolicyModel,
    Project,
    RegistryConfigModel,
    Tenant,
    User,
    UserTenant,
)
from src.infrastructure.i18n import gettext as _

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])
TENANT_ANALYTICS_PROJECT_STORAGE_LIMIT = 10


def _order_tenant_list_query(query: Select[Any]) -> Select[Any]:
    """Return tenants newest-first with a stable ID tie-breaker."""
    return query.order_by(Tenant.created_at.desc(), Tenant.id.asc())


def _coerce_history_day(value: object) -> date:
    """Normalize SQL date extraction results across PostgreSQL and SQLite."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


async def _build_memory_usage_history(
    db: AsyncSession,
    tenant_id: str,
    *,
    storage_limit: int,
    days: int = 30,
) -> list[dict[str, Any]]:
    """Return cumulative tenant memory usage for the trailing window."""
    today = datetime.now(UTC).date()
    start_date = today - timedelta(days=days - 1)
    start_at = datetime.combine(start_date, time.min, tzinfo=UTC)

    initial_usage_result = await db.execute(
        refresh_select_statement(
            select(func.coalesce(func.sum(func.length(Memory.content)), 0))
            .join(Project, Memory.project_id == Project.id)
            .where(and_(Project.tenant_id == tenant_id, Memory.created_at < start_at))
        )
    )
    running_total = int(initial_usage_result.scalar() or 0)

    history_day = func.date(Memory.created_at).label("history_day")
    daily_usage_result = await db.execute(
        refresh_select_statement(
            select(
                history_day,
                func.coalesce(func.sum(func.length(Memory.content)), 0).label("daily_added"),
                func.count(Memory.id).label("memory_count"),
            )
            .join(Project, Memory.project_id == Project.id)
            .where(and_(Project.tenant_id == tenant_id, Memory.created_at >= start_at))
            .group_by(history_day)
            .order_by(history_day)
        )
    )

    daily_usage = {
        _coerce_history_day(row.history_day): {
            "daily_added": int(row.daily_added or 0),
            "memory_count": int(row.memory_count or 0),
        }
        for row in daily_usage_result
    }

    history: list[dict[str, Any]] = []
    safe_limit = max(storage_limit, 1)
    for offset in range(days):
        day = start_date + timedelta(days=offset)
        day_usage = daily_usage.get(day, {"daily_added": 0, "memory_count": 0})
        running_total += day_usage["daily_added"]
        history.append(
            {
                "date": day.isoformat(),
                "used": running_total,
                "daily_added": day_usage["daily_added"],
                "memory_count": day_usage["memory_count"],
                "percentage": round((running_total / safe_limit) * 100, 1),
            }
        )

    return history


class AddMemberRequest(BaseModel):
    user_id: str
    role: str | None = "member"


class UpdateMemberRoleRequest(BaseModel):
    role: str


@router.post("/", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    tenant_data: TenantCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantResponse:
    """Create a new tenant."""
    # Create tenant
    tenant_id = str(uuid4())
    tenant = Tenant(
        id=tenant_id,
        name=tenant_data.name,
        slug=tenant_data.name.lower().replace(" ", "-"),  # Generate slug from name
        description=tenant_data.description,
        owner_id=current_user.id,
        # plan=tenant_data.plan,
        # max_projects=tenant_data.max_projects,
        # max_users=tenant_data.max_users,
        # max_storage=tenant_data.max_storage,
    )
    db.add(tenant)
    await db.flush()

    # Create user-tenant relationship
    user_tenant = UserTenant(
        id=str(uuid4()),
        user_id=current_user.id,
        tenant_id=tenant.id,
        role="owner",
        permissions={"admin": True, "create_projects": True, "manage_users": True},
    )
    db.add(user_tenant)

    await db.commit()
    await db.refresh(tenant)

    return TenantResponse.from_orm(tenant)


@router.get("/", response_model=TenantListResponse)
async def list_tenants(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    search: str | None = Query(None, description="Search query"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantListResponse:
    """List tenants for the current user."""
    # Get tenant IDs user has access to
    user_tenants_result = await db.execute(
        refresh_select_statement(
            select(UserTenant.tenant_id).where(UserTenant.user_id == current_user.id)
        )
    )
    tenant_ids = [row[0] for row in user_tenants_result.fetchall()]

    if not tenant_ids:
        return TenantListResponse(tenants=[], total=0, page=page, page_size=page_size)

    # Build query
    query = select(Tenant).where(Tenant.id.in_(tenant_ids))

    if search:
        query = query.where(
            or_(
                Tenant.name.ilike(f"%{search}%"),
                Tenant.description.ilike(f"%{search}%"),
            )
        )

    # Get total count
    count_query = select(func.count(Tenant.id)).where(Tenant.id.in_(tenant_ids))
    if search:
        count_query = count_query.where(
            or_(
                Tenant.name.ilike(f"%{search}%"),
                Tenant.description.ilike(f"%{search}%"),
            )
        )
    total_result = await db.execute(refresh_select_statement(count_query))
    total = total_result.scalar()

    # Get paginated results
    query = _order_tenant_list_query(query).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(refresh_select_statement(query))
    tenants = result.scalars().all()

    return TenantListResponse(
        tenants=[TenantResponse.from_orm(tenant) for tenant in tenants],
        total=total or 0,
        page=page,
        page_size=page_size,
    )


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantResponse:
    """Get tenant by ID or slug."""
    result = await db.execute(
        refresh_select_statement(
            select(Tenant).where(or_(Tenant.id == tenant_id, Tenant.slug == tenant_id))
        )
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_("Tenant not found"))

    user_tenant_result = await db.execute(
        refresh_select_statement(
            select(UserTenant).where(
                and_(UserTenant.user_id == current_user.id, UserTenant.tenant_id == tenant.id)
            )
        )
    )
    if not user_tenant_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_("Access denied to tenant")
        )

    return TenantResponse.from_orm(tenant)


@router.put("/{tenant_id}", response_model=TenantResponse)
async def update_tenant(
    tenant_id: str,
    tenant_data: TenantUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantResponse:
    """Update tenant."""
    # Check if user is owner
    result = await db.execute(
        refresh_select_statement(
            select(Tenant).where(and_(Tenant.id == tenant_id, Tenant.owner_id == current_user.id))
        )
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_("Only tenant owner can update tenant")
        )

    # Update fields
    update_data = tenant_data.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(tenant, field, value)

    await db.commit()
    await db.refresh(tenant)

    return TenantResponse.from_orm(tenant)


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete tenant."""
    # Check if user is owner
    result = await db.execute(
        refresh_select_statement(
            select(Tenant).where(and_(Tenant.id == tenant_id, Tenant.owner_id == current_user.id))
        )
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_("Only tenant owner can delete tenant")
        )

    await db.delete(tenant)
    await db.commit()


@router.post("/{tenant_id}/members/{user_id}", status_code=status.HTTP_201_CREATED)
async def add_tenant_member(
    tenant_id: str,
    user_id: str,
    role: str = Query("member", description="Member role"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Add member to tenant."""
    # Validate role set
    if role not in ["owner", "admin", "member", "viewer", "editor"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_("Invalid role"))
    # Existence-first with invalid id 422
    result = await db.execute(
        refresh_select_statement(select(Tenant).where(Tenant.id == tenant_id))
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_("Tenant not found"))
    # Permission check
    owner_check = await db.execute(
        refresh_select_statement(
            select(Tenant).where(and_(Tenant.id == tenant_id, Tenant.owner_id == current_user.id))
        )
    )
    if not owner_check.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_("Only tenant owner can add members")
        )

    # Check if user exists
    user_result = await db.execute(refresh_select_statement(select(User).where(User.id == user_id)))
    if not user_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_("User not found"))

    # Check if user is already member
    existing_result = await db.execute(
        refresh_select_statement(
            select(UserTenant).where(
                and_(UserTenant.user_id == user_id, UserTenant.tenant_id == tenant_id)
            )
        )
    )
    if existing_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("User is already a member of this tenant"),
        )

    # Create user-tenant relationship
    user_tenant = UserTenant(
        id=str(uuid4()),
        user_id=user_id,
        tenant_id=tenant_id,
        role=role,
        permissions={"read": True, "write": role in ["admin", "member", "editor"]},
    )
    db.add(user_tenant)
    await db.commit()

    return {"message": "Member added successfully", "user_id": user_id, "role": role}


@router.post("/{tenant_id}/members", status_code=status.HTTP_201_CREATED)
async def add_tenant_member_json(
    tenant_id: str,
    body: AddMemberRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Add member to tenant (JSON body version to match frontend)."""
    role = body.role or "member"
    if role not in ["owner", "admin", "member", "viewer", "editor"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_("Invalid role"))
    # Existence-first with invalid id 422
    result = await db.execute(
        refresh_select_statement(select(Tenant).where(Tenant.id == tenant_id))
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_("Tenant not found"))
    # Permission check
    owner_check = await db.execute(
        refresh_select_statement(
            select(Tenant).where(and_(Tenant.id == tenant_id, Tenant.owner_id == current_user.id))
        )
    )
    if not owner_check.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_("Only tenant owner can add members")
        )

    # Check if user exists
    user_result = await db.execute(
        refresh_select_statement(select(User).where(User.id == body.user_id))
    )
    if not user_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_("User not found"))

    # Check if user is already member
    existing_result = await db.execute(
        refresh_select_statement(
            select(UserTenant).where(
                and_(UserTenant.user_id == body.user_id, UserTenant.tenant_id == tenant_id)
            )
        )
    )
    if existing_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("User is already a member of this tenant"),
        )

    user_tenant = UserTenant(
        id=str(uuid4()),
        user_id=body.user_id,
        tenant_id=tenant_id,
        role=role,
        permissions={"read": True, "write": role in ["admin", "member", "editor"]},
    )
    db.add(user_tenant)
    await db.commit()

    return {"message": "Member added successfully", "user_id": body.user_id, "role": role}


@router.patch("/{tenant_id}/members/{user_id}", response_model=dict[str, Any])
async def update_tenant_member_role(
    tenant_id: str,
    user_id: str,
    body: UpdateMemberRoleRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Update an existing tenant member role."""
    role = body.role
    if role not in ["owner", "admin", "member", "viewer", "editor"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_("Invalid role"))

    result = await db.execute(
        refresh_select_statement(select(Tenant).where(Tenant.id == tenant_id))
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_("Tenant not found"))

    if tenant.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Only tenant owner can update member roles"),
        )

    if user_id == tenant.owner_id and role != "owner":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Cannot change tenant owner role"),
        )

    membership_result = await db.execute(
        refresh_select_statement(
            select(UserTenant).where(
                and_(UserTenant.user_id == user_id, UserTenant.tenant_id == tenant_id)
            )
        )
    )
    membership = membership_result.scalar_one_or_none()
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_("Tenant member not found")
        )

    membership.role = role
    membership.permissions = {"read": True, "write": role in ["owner", "admin", "member", "editor"]}
    await db.commit()

    return {"message": "Member role updated successfully", "user_id": user_id, "role": role}


@router.delete("/{tenant_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_tenant_member(
    tenant_id: str,
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove member from tenant."""
    # Existence-first with invalid id 422
    result = await db.execute(
        refresh_select_statement(select(Tenant).where(Tenant.id == tenant_id))
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_("Tenant not found"))
    # Permission check
    owner_check = await db.execute(
        refresh_select_statement(
            select(Tenant).where(and_(Tenant.id == tenant_id, Tenant.owner_id == current_user.id))
        )
    )
    if not owner_check.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_("Only tenant owner can remove members")
        )

    # Cannot remove owner
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=_("Cannot remove tenant owner")
        )

    # Remove user-tenant relationship
    result = await db.execute(
        refresh_select_statement(
            select(UserTenant).where(
                and_(UserTenant.user_id == user_id, UserTenant.tenant_id == tenant_id)
            )
        )
    )
    user_tenant = result.scalar_one_or_none()
    if not user_tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_("User is not a member of this tenant")
        )

    await db.delete(user_tenant)
    await db.commit()


@router.get("/{tenant_id}/members")
async def list_tenant_members(
    tenant_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List tenant members."""
    # Check if user has access to tenant
    user_tenant_result = await db.execute(
        refresh_select_statement(
            select(UserTenant).where(
                and_(UserTenant.user_id == current_user.id, UserTenant.tenant_id == tenant_id)
            )
        )
    )
    if not user_tenant_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_("Access denied to tenant")
        )
    # Existence check
    result = await db.execute(
        refresh_select_statement(select(Tenant).where(Tenant.id == tenant_id))
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_("Tenant not found"))

    # Get all members
    result = await db.execute(
        refresh_select_statement(
            select(UserTenant, User)
            .join(User, UserTenant.user_id == User.id)
            .where(UserTenant.tenant_id == tenant_id)
        )
    )
    members = []
    for user_tenant, user in result.fetchall():
        members.append(
            {
                "user_id": user.id,
                "email": user.email,
                "name": user.full_name,  # Fixed: use full_name instead of name
                "role": user_tenant.role,
                "permissions": user_tenant.permissions,
                "created_at": user_tenant.created_at,
            }
        )

    return {"members": members, "total": len(members)}


@router.get("/{tenant_id}/stats")
async def get_tenant_stats(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get tenant statistics for the overview dashboard."""
    # Check access
    user_tenant_result = await db.execute(
        refresh_select_statement(
            select(UserTenant).where(
                and_(UserTenant.user_id == current_user.id, UserTenant.tenant_id == tenant_id)
            )
        )
    )
    if not user_tenant_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_("Access denied to tenant")
        )

    # Get tenant details
    tenant_result = await db.execute(
        refresh_select_statement(select(Tenant).where(Tenant.id == tenant_id))
    )
    tenant = tenant_result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail=_("Tenant not found"))

    # Projects do not have a lifecycle status column today; every existing
    # project is counted as active for overview compatibility.
    active_projects_result = await db.execute(
        refresh_select_statement(
            select(func.count(Project.id)).where(Project.tenant_id == tenant_id)
        )
    )
    active_projects_count = active_projects_result.scalar() or 0

    # Get team members count
    members_result = await db.execute(
        refresh_select_statement(
            select(func.count(UserTenant.id)).where(UserTenant.tenant_id == tenant_id)
        )
    )
    team_members_count = members_result.scalar()

    # Calculate storage used (sum of memory content length)
    storage_result = await db.execute(
        refresh_select_statement(
            select(func.sum(func.length(Memory.content)))
            .join(Project, Memory.project_id == Project.id)
            .where(Project.tenant_id == tenant_id)
        )
    )
    storage_used = storage_result.scalar() or 0

    # New projects this week
    one_week_ago = datetime.now(UTC) - timedelta(days=7)
    new_projects_result = await db.execute(
        refresh_select_statement(
            select(func.count(Project.id)).where(
                and_(Project.tenant_id == tenant_id, Project.created_at >= one_week_ago)
            )
        )
    )
    new_projects_this_week = new_projects_result.scalar() or 0

    # New members this week
    new_members_result = await db.execute(
        refresh_select_statement(
            select(func.count(UserTenant.id)).where(
                and_(UserTenant.tenant_id == tenant_id, UserTenant.created_at >= one_week_ago)
            )
        )
    )
    new_members_this_week = new_members_result.scalar() or 0

    # Project details with memory usage. Use an aggregate subquery so large
    # tenants do not load every Project entity just to render the top-five list.
    project_usage_subquery = (
        select(
            Memory.project_id.label("project_id"),
            func.coalesce(func.sum(func.length(Memory.content)), 0).label("storage_bytes"),
            func.count(Memory.id).label("memory_count"),
        )
        .join(Project, Memory.project_id == Project.id)
        .where(Project.tenant_id == tenant_id)
        .group_by(Memory.project_id)
        .subquery()
    )
    project_storage_bytes = func.coalesce(project_usage_subquery.c.storage_bytes, 0).label(
        "storage_bytes"
    )
    project_memory_count = func.coalesce(project_usage_subquery.c.memory_count, 0).label(
        "memory_count"
    )
    top_projects_result = await db.execute(
        refresh_select_statement(
            select(Project, project_storage_bytes, project_memory_count)
            .outerjoin(project_usage_subquery, project_usage_subquery.c.project_id == Project.id)
            .where(Project.tenant_id == tenant_id)
            .order_by(
                project_storage_bytes.desc(),
                project_memory_count.desc(),
                Project.created_at.desc(),
                Project.id.asc(),
            )
            .limit(5)
        )
    )
    top_project_rows = top_projects_result.all()
    owner_ids = {
        project.owner_id
        for project, _storage_bytes, _memory_count in top_project_rows
        if project.owner_id
    }
    owners_by_id: dict[str, User] = {}
    if owner_ids:
        owners_result = await db.execute(
            refresh_select_statement(select(User).where(User.id.in_(owner_ids)))
        )
        owners_by_id = {owner.id: owner for owner in owners_result.scalars().all()}

    active_projects_list: list[dict[str, Any]] = []
    for project, storage_bytes, _memory_count in top_project_rows:
        owner = owners_by_id.get(project.owner_id)
        owner_name = owner.full_name if owner else "Unknown"

        proj_storage = int(storage_bytes or 0)

        # Format storage
        if proj_storage > 1024 * 1024 * 1024:
            storage_str = f"{proj_storage / (1024 * 1024 * 1024):.1f} GB"
        elif proj_storage > 1024 * 1024:
            storage_str = f"{proj_storage / (1024 * 1024):.1f} MB"
        else:
            storage_str = f"{proj_storage / 1024:.1f} KB"

        active_projects_list.append(
            {
                "id": project.id,
                "name": project.name,
                "owner": owner_name,
                "memory_consumed": storage_str,
                "status": "active",
            }
        )

    storage_limit = tenant.max_storage or 1024 * 1024 * 1024
    memory_usage_history = await _build_memory_usage_history(
        db,
        tenant_id,
        storage_limit=storage_limit,
    )

    return {
        "storage": {
            "total": storage_limit,
            "used": storage_used,
            "percentage": round((storage_used / max(storage_limit, 1)) * 100, 1),
        },
        "projects": {
            "active": active_projects_count,
            "new_this_week": new_projects_this_week,
            "list": active_projects_list,
        },
        "members": {
            "total": team_members_count,
            "new_added": new_members_this_week,
        },
        "memory_history": memory_usage_history,
        "tenant_info": {
            "organization_id": f"#TEN-{tenant.id[:5].upper()}",
            "plan": tenant.plan or "Free",
            "region": None,
            "next_billing_date": None,
        },
    }


@router.get("/{tenant_id}/analytics")
async def get_tenant_analytics(
    tenant_id: str,
    period: str = Query("30d", description="Time period: 7d, 30d, 90d"),
    project_storage_limit: int = Query(
        TENANT_ANALYTICS_PROJECT_STORAGE_LIMIT,
        ge=1,
        le=50,
        description="Maximum number of projects returned for the storage distribution chart",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Get analytics data for tenant dashboard charts.

    Returns:
        - memoryGrowth: Time-series data for memory creation
        - projectStorage: Per-project storage distribution
        - summary: Quick stats
    """
    # Verify user belongs to tenant
    user_tenant_result = await db.execute(
        refresh_select_statement(
            select(UserTenant).where(
                UserTenant.user_id == current_user.id,
                UserTenant.tenant_id == tenant_id,
            )
        )
    )
    if not user_tenant_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail=_("Access denied to this tenant"))

    # Determine time range
    days_map = {"7d": 7, "30d": 30, "90d": 90}
    period_value = period if isinstance(period, str) else "30d"
    days = days_map.get(period_value, 30)
    storage_limit = (
        project_storage_limit
        if isinstance(project_storage_limit, int)
        else TENANT_ANALYTICS_PROJECT_STORAGE_LIMIT
    )

    project_storage = await _get_tenant_project_storage(
        db,
        tenant_id,
        limit=storage_limit,
    )
    memory_growth = await _get_memory_growth_by_day(db, tenant_id, days)
    summary = await _get_tenant_memory_summary(db, tenant_id)

    return {
        "memoryGrowth": memory_growth,
        "projectStorage": project_storage,
        "summary": {
            "total_memories": summary["total_memories"],
            "total_storage_bytes": summary["total_storage_bytes"],
            "total_projects": summary["total_projects"],
            "period_days": days,
        },
    }


async def _get_tenant_memory_summary(db: AsyncSession, tenant_id: str) -> dict[str, int]:
    """Get tenant-wide project and memory totals without loading project rows."""
    project_count_result = await db.execute(
        refresh_select_statement(
            select(func.count(Project.id)).where(Project.tenant_id == tenant_id)
        )
    )
    project_count = int(project_count_result.scalar() or 0)

    memory_summary_result = await db.execute(
        refresh_select_statement(
            select(
                func.coalesce(func.sum(func.length(Memory.content)), 0).label("storage_bytes"),
                func.count(Memory.id).label("memory_count"),
            )
            .select_from(Memory)
            .join(Project, Memory.project_id == Project.id)
            .where(Project.tenant_id == tenant_id)
        )
    )
    storage_bytes, memory_count = memory_summary_result.one()

    return {
        "total_projects": project_count,
        "total_memories": int(memory_count or 0),
        "total_storage_bytes": int(storage_bytes or 0),
    }


async def _get_tenant_project_storage(
    db: AsyncSession,
    tenant_id: str,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Return the top project storage rows needed by the dashboard chart."""
    storage_expr = func.coalesce(func.sum(func.length(Memory.content)), 0)
    memory_count_expr = func.count(Memory.id)

    result = await db.execute(
        refresh_select_statement(
            select(
                Project.name,
                storage_expr.label("storage_bytes"),
                memory_count_expr.label("memory_count"),
            )
            .select_from(Project)
            .outerjoin(Memory, Memory.project_id == Project.id)
            .where(Project.tenant_id == tenant_id)
            .group_by(Project.id, Project.name)
            .order_by(storage_expr.desc(), Project.name.asc())
            .limit(limit)
        )
    )

    return [
        {
            "name": name,
            "storage_bytes": int(storage_bytes or 0),
            "memory_count": int(memory_count or 0),
        }
        for name, storage_bytes, memory_count in result.all()
    ]


async def _get_memory_growth_by_day(db: AsyncSession, tenant_id: str, days: int) -> list[Any]:
    """Get memory creation counts by day for the last N days."""
    _start_date = datetime.now(UTC) - timedelta(days=days)

    # Query memory counts grouped by date
    result = await db.execute(
        refresh_select_statement(
            select(
                func.date(Memory.created_at).label("date"),
                func.count().label("count"),
            )
            .select_from(Memory)
            .join(Project, Memory.project_id == Project.id)
            .where(Project.tenant_id == tenant_id)
            .where(Memory.created_at >= _start_date)
            .group_by(func.date(Memory.created_at))
            .order_by(func.date(Memory.created_at))
        )
    )

    # Format for chart
    growth_data: list[dict[str, Any]] = []
    for row in result:
        memory_day = _coerce_history_day(row.date) if row.date else None
        date_str = memory_day.strftime("%b %d") if memory_day else ""
        growth_data.append({"date": date_str, "count": row.count})

    return growth_data


# ---------------------------------------------------------------------------
# Gene Policy endpoints
# ---------------------------------------------------------------------------


class GenePolicyRequest(BaseModel):
    policy_key: str
    policy_value: dict[str, Any] = {}
    description: str | None = None


class GenePolicyResponse(BaseModel):
    id: str
    tenant_id: str
    policy_key: str
    policy_value: dict[str, Any]
    description: str | None
    created_at: datetime
    updated_at: datetime | None


@router.get("/{tenant_id}/gene-policies", response_model=list[GenePolicyResponse])
async def list_gene_policies(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[GenePolicyResponse]:
    result = await db.execute(
        refresh_select_statement(
            select(OrgGenePolicyModel)
            .where(
                and_(
                    OrgGenePolicyModel.tenant_id == tenant_id,
                    OrgGenePolicyModel.deleted_at.is_(None),
                )
            )
            .order_by(OrgGenePolicyModel.policy_key)
        )
    )
    rows = result.scalars().all()
    return [
        GenePolicyResponse(
            id=r.id,
            tenant_id=r.tenant_id,
            policy_key=r.policy_key,
            policy_value=r.policy_value,
            description=r.description,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


@router.put("/{tenant_id}/gene-policies/{policy_key}", response_model=GenePolicyResponse)
async def upsert_gene_policy(
    tenant_id: str,
    policy_key: str,
    body: GenePolicyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GenePolicyResponse:
    result = await db.execute(
        refresh_select_statement(
            select(OrgGenePolicyModel).where(
                and_(
                    OrgGenePolicyModel.tenant_id == tenant_id,
                    OrgGenePolicyModel.policy_key == policy_key,
                    OrgGenePolicyModel.deleted_at.is_(None),
                )
            )
        )
    )
    existing = result.scalar_one_or_none()
    now = datetime.now(UTC)

    if existing:
        existing.policy_value = body.policy_value
        existing.description = body.description
        existing.updated_at = now
        await db.flush()
        row = existing
    else:
        row = OrgGenePolicyModel(
            id=str(uuid4()),
            tenant_id=tenant_id,
            policy_key=body.policy_key,
            policy_value=body.policy_value,
            description=body.description,
        )
        db.add(row)
        await db.flush()

    await db.commit()
    return GenePolicyResponse(
        id=row.id,
        tenant_id=row.tenant_id,
        policy_key=row.policy_key,
        policy_value=row.policy_value,
        description=row.description,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.delete("/{tenant_id}/gene-policies/{policy_key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_gene_policy(
    tenant_id: str,
    policy_key: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        refresh_select_statement(
            select(OrgGenePolicyModel).where(
                and_(
                    OrgGenePolicyModel.tenant_id == tenant_id,
                    OrgGenePolicyModel.policy_key == policy_key,
                    OrgGenePolicyModel.deleted_at.is_(None),
                )
            )
        )
    )
    existing = result.scalar_one_or_none()
    if not existing:
        raise HTTPException(status_code=404, detail=_("Gene policy not found"))
    existing.deleted_at = datetime.now(UTC)
    await db.flush()
    await db.commit()


# ---------------------------------------------------------------------------
# Registry Config CRUD
# ---------------------------------------------------------------------------


class RegistryRequest(BaseModel):
    name: str
    registry_type: str
    url: str
    username: str | None = None
    password: str | None = None
    is_default: bool = False


class RegistryResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    type: str
    url: str
    username: str | None = None
    is_default: bool
    status: str
    last_checked: str | None = None
    created_at: str
    updated_at: str | None = None


def _registry_to_response(row: RegistryConfigModel) -> RegistryResponse:
    return RegistryResponse(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        type=row.registry_type,
        url=row.url,
        username=row.username,
        is_default=row.is_default,
        status="disconnected",
        last_checked=None,
        created_at=row.created_at.isoformat() if row.created_at else "",
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


@router.get("/{tenant_id}/registries")
async def list_registries(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[RegistryResponse]:
    result = await db.execute(
        refresh_select_statement(
            select(RegistryConfigModel).where(
                and_(
                    RegistryConfigModel.tenant_id == tenant_id,
                    RegistryConfigModel.deleted_at.is_(None),
                )
            )
        )
    )
    rows = result.scalars().all()
    return [_registry_to_response(r) for r in rows]


@router.post("/{tenant_id}/registries", status_code=status.HTTP_201_CREATED)
async def create_registry(
    tenant_id: str,
    body: RegistryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RegistryResponse:
    row = RegistryConfigModel(
        id=str(uuid4()),
        tenant_id=tenant_id,
        name=body.name,
        registry_type=body.registry_type,
        url=body.url,
        username=body.username,
        password_encrypted=body.password,
        is_default=body.is_default,
    )
    db.add(row)
    await db.flush()
    await db.commit()
    return _registry_to_response(row)


@router.put("/{tenant_id}/registries/{registry_id}")
async def update_registry(
    tenant_id: str,
    registry_id: str,
    body: RegistryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RegistryResponse:
    result = await db.execute(
        refresh_select_statement(
            select(RegistryConfigModel).where(
                and_(
                    RegistryConfigModel.id == registry_id,
                    RegistryConfigModel.tenant_id == tenant_id,
                    RegistryConfigModel.deleted_at.is_(None),
                )
            )
        )
    )
    existing = result.scalar_one_or_none()
    if not existing:
        raise HTTPException(status_code=404, detail=_("Registry not found"))

    existing.name = body.name
    existing.registry_type = body.registry_type
    existing.url = body.url
    existing.username = body.username
    if body.password is not None:
        existing.password_encrypted = body.password
    existing.is_default = body.is_default
    existing.updated_at = datetime.now(UTC)
    await db.flush()
    await db.commit()
    return _registry_to_response(existing)


@router.delete("/{tenant_id}/registries/{registry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_registry(
    tenant_id: str,
    registry_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        refresh_select_statement(
            select(RegistryConfigModel).where(
                and_(
                    RegistryConfigModel.id == registry_id,
                    RegistryConfigModel.tenant_id == tenant_id,
                    RegistryConfigModel.deleted_at.is_(None),
                )
            )
        )
    )
    existing = result.scalar_one_or_none()
    if not existing:
        raise HTTPException(status_code=404, detail=_("Registry not found"))
    existing.deleted_at = datetime.now(UTC)
    await db.flush()
    await db.commit()


class TestConnectionResponse(BaseModel):
    success: bool
    message: str


@router.post("/{tenant_id}/registries/{registry_id}/test")
async def test_registry_connection(
    tenant_id: str,
    registry_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TestConnectionResponse:
    result = await db.execute(
        refresh_select_statement(
            select(RegistryConfigModel).where(
                and_(
                    RegistryConfigModel.id == registry_id,
                    RegistryConfigModel.tenant_id == tenant_id,
                    RegistryConfigModel.deleted_at.is_(None),
                )
            )
        )
    )
    existing = result.scalar_one_or_none()
    if not existing:
        raise HTTPException(status_code=404, detail=_("Registry not found"))

    return TestConnectionResponse(
        success=True,
        message=f"Successfully connected to {existing.name}",
    )
