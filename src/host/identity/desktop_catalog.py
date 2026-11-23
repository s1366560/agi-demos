"""Membership-scoped identity summaries consumed during native cloud session discovery."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.host.identity.project_package_scope import visible_projects
from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    Tenant,
    User,
    UserTenant,
)
from src.infrastructure.i18n import gettext as _

router = APIRouter(prefix="/api/v1", tags=["Identity"])
Database = Annotated[AsyncSession, Depends(get_db)]
Actor = Annotated[User, Depends(get_current_user)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


class TenantSummary(BaseModel):
    id: str
    name: str
    slug: str
    description: str | None


class ProjectSummary(BaseModel):
    id: str
    tenant_id: str
    name: str
    description: str | None
    is_public: bool


class TenantPage(BaseModel):
    tenants: list[TenantSummary]
    total: int
    page: int
    page_size: int


class ProjectPage(BaseModel):
    projects: list[ProjectSummary]
    owner_ids: list[str]
    total: int
    page: int
    page_size: int


@router.get("/tenants/")
async def tenants(
    user: Actor, db: Database, page: Page = 1, page_size: PageSize = 20, search: str | None = None
) -> TenantPage:
    # A historical user may have several links to the same tenant. Keep the
    # earliest membership, matching the cloud default-tenant order.
    memberships = (
        select(
            UserTenant.tenant_id,
            UserTenant.created_at,
            UserTenant.id,
            func.row_number()
            .over(
                partition_by=UserTenant.tenant_id, order_by=(UserTenant.created_at, UserTenant.id)
            )
            .label("position"),
        )
        .where(UserTenant.user_id == user.id)
        .subquery()
    )
    query = (
        select(Tenant)
        .join(memberships, memberships.c.tenant_id == Tenant.id)
        .where(memberships.c.position == 1)
    )
    if search:
        query = query.where(
            or_(Tenant.name.ilike(f"%{search}%"), Tenant.description.ilike(f"%{search}%"))
        )
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = await db.scalars(
        query.order_by(memberships.c.created_at, memberships.c.id, Tenant.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return TenantPage(
        tenants=[TenantSummary.model_validate(row, from_attributes=True) for row in rows],
        total=total or 0,
        page=page,
        page_size=page_size,
    )


@router.get("/projects/")
async def projects(
    user: Actor,
    db: Database,
    tenant_id: str | None = None,
    page: Page = 1,
    page_size: PageSize = 20,
    search: str | None = None,
    visibility: Literal["all", "public", "private"] = "all",
    owner_id: str | None = None,
) -> ProjectPage:
    query = select(Project).where(
        Project.id.in_(visible_projects(user).with_only_columns(Project.id))
    )
    if tenant_id is not None:
        query = query.where(Project.tenant_id == tenant_id)
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        query = query.where(
            or_(
                Project.id.ilike(pattern),
                Project.name.ilike(pattern),
                Project.description.ilike(pattern),
                Project.owner_id.ilike(pattern),
            )
        )
    if visibility != "all":
        query = query.where(Project.is_public.is_(visibility == "public"))
    owners = await db.scalars(
        query.with_only_columns(Project.owner_id).distinct().order_by(Project.owner_id)
    )
    if owner_id:
        query = query.where(Project.owner_id == owner_id)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = await db.scalars(
        query.order_by(
            case((Project.name.in_(("Default project", "默认项目")), 0), else_=1),
            Project.created_at.desc(),
            Project.id,
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return ProjectPage(
        projects=[ProjectSummary.model_validate(row, from_attributes=True) for row in rows],
        owner_ids=[owner for owner in owners if owner],
        total=total or 0,
        page=page,
        page_size=page_size,
    )


@router.get("/projects/{project_id}")
async def project(
    project_id: str, user: Actor, db: Database, tenant_id: str | None = None
) -> ProjectSummary:
    query = visible_projects(user).where(Project.id == project_id)
    if tenant_id is not None:
        query = query.where(Project.tenant_id == tenant_id)
    row = await db.scalar(query)
    if row is None:
        raise HTTPException(404, _("Project not found"))
    return ProjectSummary.model_validate(row, from_attributes=True)
