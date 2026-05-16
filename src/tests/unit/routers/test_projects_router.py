from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.project import ProjectCreate
from src.infrastructure.adapters.primary.web.routers.projects import create_project
from src.infrastructure.adapters.secondary.persistence.models import Tenant, User


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
