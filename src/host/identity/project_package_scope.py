"""Project picker for the independently deployed package management client."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Select, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    Tenant,
    User,
    UserProject,
    UserTenant,
)

router = APIRouter(prefix="/api/v1/project-packages", tags=["Project Packages"])


class ProjectPackageScope(BaseModel):
    project_id: str
    tenant_id: str
    project_name: str
    tenant_name: str
    can_manage: bool
    can_execute: bool


def visible_projects(user: User) -> Select[tuple[Project]]:
    # Project membership is required even for platform administrators. Read access
    # also requires tenant membership, with the same superuser exception as the API.
    query = (
        select(Project)
        .select_from(Project)
        .join(Tenant, Tenant.id == Project.tenant_id)
        .join(
            UserProject, and_(UserProject.project_id == Project.id, UserProject.user_id == user.id)
        )
        .outerjoin(
            UserTenant, and_(UserTenant.tenant_id == Tenant.id, UserTenant.user_id == user.id)
        )
    )
    if not user.is_superuser:
        query = query.where(UserTenant.id.is_not(None))
    return query


@router.get("/projects/", response_model=list[ProjectPackageScope])
async def projects_for_package_management(
    user: Annotated[User, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(get_db)]
) -> list[ProjectPackageScope]:
    query = (
        visible_projects(user)
        .with_only_columns(
            Project.id, Tenant.id, Project.name, Tenant.name, UserProject.role, UserTenant.id
        )
        .order_by(Tenant.name, Project.name, Project.id)
    )
    rows = await db.execute(query.execution_options(populate_existing=True))
    return [
        ProjectPackageScope(
            project_id=project,
            tenant_id=tenant,
            project_name=name,
            tenant_name=organization,
            can_manage=membership is not None and role in {"admin", "owner"},
            can_execute=user.is_active and role in {"owner", "admin", "member"},
        )
        for project, tenant, name, organization, role, membership in rows
    ]
