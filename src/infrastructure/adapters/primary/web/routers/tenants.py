"""Tenant management API endpoints."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.tenant import (
    TenantCreate,
    TenantListResponse,
    TenantResponse,
    TenantUpdate,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    Memory,
    Project,
    Tenant,
    User,
    UserTenant,
)

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])


class AddMemberRequest(BaseModel):
    user_id: str
    role: str | None = "member"


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
        select(UserTenant.tenant_id).where(UserTenant.user_id == current_user.id)
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
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # Get paginated results
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    tenants = result.scalars().all()

    return TenantListResponse(
        tenants=[TenantResponse.from_orm(tenant) for tenant in tenants],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantResponse:
    """Get tenant by ID."""
    # Check if user has access to tenant
    user_tenant_result = await db.execute(
        select(UserTenant).where(
            and_(UserTenant.user_id == current_user.id, UserTenant.tenant_id == tenant_id)
        )
    )
    if not user_tenant_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to tenant")

    # Get tenant
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

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
        select(Tenant).where(and_(Tenant.id == tenant_id, Tenant.owner_id == current_user.id))
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only tenant owner can update tenant"
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
        select(Tenant).where(and_(Tenant.id == tenant_id, Tenant.owner_id == current_user.id))
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only tenant owner can delete tenant"
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
) -> dict:
    """Add member to tenant."""
    # Validate role set
    if role not in ["owner", "admin", "member", "viewer", "editor"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role")
    # Existence-first with invalid id 422
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    # Permission check
    owner_check = await db.execute(
        select(Tenant).where(and_(Tenant.id == tenant_id, Tenant.owner_id == current_user.id))
    )
    if not owner_check.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only tenant owner can add members"
        )

    # Check if user exists
    user_result = await db.execute(select(User).where(User.id == user_id))
    if not user_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Check if user is already member
    existing_result = await db.execute(
        select(UserTenant).where(
            and_(UserTenant.user_id == user_id, UserTenant.tenant_id == tenant_id)
        )
    )
    if existing_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already a member of this tenant",
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
) -> dict:
    """Add member to tenant (JSON body version to match frontend)."""
    role = body.role or "member"
    if role not in ["owner", "admin", "member", "viewer", "editor"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role")
    # Existence-first with invalid id 422
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    # Permission check
    owner_check = await db.execute(
        select(Tenant).where(and_(Tenant.id == tenant_id, Tenant.owner_id == current_user.id))
    )
    if not owner_check.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only tenant owner can add members"
        )

    # Check if user exists
    user_result = await db.execute(select(User).where(User.id == body.user_id))
    if not user_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Check if user is already member
    existing_result = await db.execute(
        select(UserTenant).where(
            and_(UserTenant.user_id == body.user_id, UserTenant.tenant_id == tenant_id)
        )
    )
    if existing_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already a member of this tenant",
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


@router.delete("/{tenant_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_tenant_member(
    tenant_id: str,
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove member from tenant."""
    # Existence-first with invalid id 422
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    # Permission check
    owner_check = await db.execute(
        select(Tenant).where(and_(Tenant.id == tenant_id, Tenant.owner_id == current_user.id))
    )
    if not owner_check.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only tenant owner can remove members"
        )

    # Cannot remove owner
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot remove tenant owner"
        )

    # Remove user-tenant relationship
    result = await db.execute(
        select(UserTenant).where(
            and_(UserTenant.user_id == user_id, UserTenant.tenant_id == tenant_id)
        )
    )
    user_tenant = result.scalar_one_or_none()
    if not user_tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User is not a member of this tenant"
        )

    await db.delete(user_tenant)
    await db.commit()


@router.get("/{tenant_id}/members")
async def list_tenant_members(
    tenant_id: str,
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List tenant members."""
    # Check if user has access to tenant
    user_tenant_result = await db.execute(
        select(UserTenant).where(
            and_(UserTenant.user_id == current_user.id, UserTenant.tenant_id == tenant_id)
        )
    )
    if not user_tenant_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to tenant")
    # Existence check
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    # Get all members
    result = await db.execute(
        select(UserTenant, User)
        .join(User, UserTenant.user_id == User.id)
        .where(UserTenant.tenant_id == tenant_id)
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
) -> dict:
    """Get tenant statistics for the overview dashboard."""
    # Check access
    user_tenant_result = await db.execute(
        select(UserTenant).where(
            and_(UserTenant.user_id == current_user.id, UserTenant.tenant_id == tenant_id)
        )
    )
    if not user_tenant_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to tenant")

    # Get tenant details
    tenant_result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = tenant_result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Get active projects count
    projects_result = await db.execute(select(Project).where(Project.tenant_id == tenant_id))
    projects = projects_result.scalars().all()
    active_projects_count = len(projects)

    # Get team members count
    members_result = await db.execute(
        select(func.count(UserTenant.id)).where(UserTenant.tenant_id == tenant_id)
    )
    team_members_count = members_result.scalar()

    # Calculate storage used (sum of memory content length)
    storage_result = await db.execute(
        select(func.sum(func.length(Memory.content)))
        .join(Project, Memory.project_id == Project.id)
        .where(Project.tenant_id == tenant_id)
    )
    storage_used = storage_result.scalar() or 0

    # New projects this week
    one_week_ago = datetime.now(UTC) - timedelta(days=7)
    new_projects_result = await db.execute(
        select(func.count(Project.id)).where(
            and_(Project.tenant_id == tenant_id, Project.created_at >= one_week_ago)
        )
    )
    new_projects_this_week = new_projects_result.scalar() or 0

    # New members this week
    new_members_result = await db.execute(
        select(func.count(UserTenant.id)).where(
            and_(UserTenant.tenant_id == tenant_id, UserTenant.created_at >= one_week_ago)
        )
    )
    new_members_this_week = new_members_result.scalar() or 0

    # Project details with memory usage
    active_projects_list = []
    for project in projects[:5]:  # Top 5 projects
        # Get owner name
        owner_result = await db.execute(select(User).where(User.id == project.owner_id))
        owner = owner_result.scalar_one_or_none()
        owner_name = owner.full_name if owner else "Unknown"

        # Get memory consumption for this project
        proj_storage_result = await db.execute(
            select(func.sum(func.length(Memory.content))).where(Memory.project_id == project.id)
        )
        proj_storage = proj_storage_result.scalar() or 0

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
                "status": "Active",  # Could rely on project.updated_at
            }
        )

    # Memory usage history (simplified: daily creation count/size for last 30 days)
    # This is a bit complex for SQL, so we might skip or approximate.
    # For now, let's just return a placeholder or calculate real data if efficient.
    # We'll use a placeholder for history as it requires time-series aggregation.
    memory_usage_history = []
    # Placeholder: mock trend based on real total?
    # Or just empty list if no data.

    return {
        "storage": {
            "total": tenant.max_storage or 1024 * 1024 * 1024,  # Default 1GB
            "used": storage_used,
            "percentage": round(
                (storage_used / (tenant.max_storage or 1024 * 1024 * 1024)) * 100, 1
            ),
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
        "memory_history": memory_usage_history,  # Empty for now, or could implement daily aggregation
        "tenant_info": {
            "organization_id": f"#TEN-{tenant.id[:5].upper()}",
            "plan": tenant.plan or "Free",
            "region": "US-East",  # Hardcoded or from config
            "next_billing_date": (datetime.now() + timedelta(days=30)).strftime("%b %d, %Y"),
        },
    }


@router.get("/{tenant_id}/analytics")
async def get_tenant_analytics(
    tenant_id: str,
    period: str = Query("30d", description="Time period: 7d, 30d, 90d"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get analytics data for tenant dashboard charts.

    Returns:
        - memoryGrowth: Time-series data for memory creation
        - projectStorage: Per-project storage distribution
        - summary: Quick stats
    """
    # Verify user belongs to tenant
    user_tenant_result = await db.execute(
        select(UserTenant).where(
            UserTenant.user_id == current_user.id,
            UserTenant.tenant_id == tenant_id,
        )
    )
    if not user_tenant_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Access denied to this tenant")

    # Determine time range
    days_map = {"7d": 7, "30d": 30, "90d": 90}
    days = days_map.get(period, 30)
    _start_date = datetime.now(UTC) - timedelta(days=days)

    # Get projects for this tenant
    projects_result = await db.execute(
        select(Project).where(Project.tenant_id == tenant_id)
    )
    projects = projects_result.scalars().all()

    # Calculate per-project storage
    project_storage = []
    for project in projects:
        # Sum memory content lengths as proxy for storage
        storage_result = await db.execute(
            select(func.sum(func.length(Memory.content))).where(
                Memory.project_id == project.id
            )
        )
        storage_bytes = storage_result.scalar() or 0
        project_storage.append(
            {
                "name": project.name,
                "storage_bytes": storage_bytes,
                "memory_count": await _get_memory_count(db, project.id),
            }
        )

    # Get memory growth by day
    memory_growth = await _get_memory_growth_by_day(db, [p.id for p in projects], days)

    # Summary stats
    total_memories = sum(p.get("memory_count", 0) for p in project_storage)
    total_storage = sum(p.get("storage_bytes", 0) for p in project_storage)

    return {
        "memoryGrowth": memory_growth,
        "projectStorage": project_storage,
        "summary": {
            "total_memories": total_memories,
            "total_storage_bytes": total_storage,
            "total_projects": len(projects),
            "period_days": days,
        },
    }


async def _get_memory_count(db: AsyncSession, project_id: str) -> int:
    """Get memory count for a project."""
    result = await db.execute(
        select(func.count()).select_from(Memory).where(Memory.project_id == project_id)
    )
    return result.scalar() or 0


async def _get_memory_growth_by_day(
    db: AsyncSession, project_ids: list, days: int
) -> list:
    """Get memory creation counts by day for the last N days."""
    if not project_ids:
        return []

    _start_date = datetime.now(UTC) - timedelta(days=days)

    # Query memory counts grouped by date
    result = await db.execute(
        select(
            func.date(Memory.created_at).label("date"),
            func.count().label("count"),
        )
        .where(Memory.project_id.in_(project_ids))
        .where(Memory.created_at >= _start_date)
        .group_by(func.date(Memory.created_at))
        .order_by(func.date(Memory.created_at))
    )

    # Format for chart
    growth_data = []
    for row in result:
        date_str = row.date.strftime("%b %d") if row.date else ""
        growth_data.append({"date": date_str, "count": row.count})

    return growth_data
