from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.project import ProjectCreate
from src.infrastructure.adapters.primary.web.routers.projects import create_project, get_project
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    Tenant,
    User,
    UserProject,
)


@pytest.mark.unit
async def test_create_project_internal_error_is_sanitized(
    test_db: AsyncSession,
    test_tenant_db: Tenant,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        test_db,
        "commit",
        AsyncMock(side_effect=RuntimeError("postgres://secret-host/internal failure")),
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_project(
            ProjectCreate(name="Broken Project", tenant_id=test_tenant_db.id),
            current_user=test_user,
            db=test_db,
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to create project"
    assert "secret-host" not in str(exc_info.value.detail)


@pytest.mark.unit
async def test_get_project_rejects_requested_tenant_mismatch(
    test_db: AsyncSession,
    test_tenant_db: Tenant,
    test_user: User,
) -> None:
    other_tenant = Tenant(
        id="tenant-other",
        name="Other Tenant",
        slug="other-tenant",
        description="Tenant outside the requested route scope",
        owner_id=test_user.id,
        plan="free",
        max_projects=10,
        max_users=5,
        max_storage=1073741824,
    )
    project = Project(
        id="project-other-tenant",
        tenant_id=other_tenant.id,
        name="Other Tenant Project",
        description="Should not be returned through another tenant scope",
        owner_id=test_user.id,
        memory_rules={},
        graph_config={},
    )
    user_project = UserProject(
        id=str(uuid4()),
        user_id=test_user.id,
        project_id=project.id,
        role="owner",
        permissions={"read": True, "write": True, "admin": True},
    )
    test_db.add_all([other_tenant, project, user_project])
    await test_db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await get_project(
            project.id,
            tenant_id=test_tenant_db.id,
            current_user=test_user,
            db=test_db,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Project not found in requested tenant"
