"""Unit tests for project sandbox access helpers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException, status

from src.infrastructure.adapters.primary.web.routers.project_sandbox import verify_project_access


@pytest.mark.unit
async def test_verify_project_access_returns_project_tenant_id() -> None:
    result = Mock()
    result.scalar_one_or_none.return_value = "tenant-project"
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)

    tenant_id = await verify_project_access(
        "project-1",
        SimpleNamespace(id="user-1"),
        db,
        ["owner", "admin", "member"],
    )

    assert tenant_id == "tenant-project"
    db.execute.assert_awaited_once()


@pytest.mark.unit
async def test_verify_project_access_denies_missing_membership() -> None:
    result = Mock()
    result.scalar_one_or_none.return_value = None
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)

    with pytest.raises(HTTPException) as exc_info:
        await verify_project_access(
            "project-1",
            SimpleNamespace(id="user-1"),
            db,
            ["owner", "admin", "member"],
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert exc_info.value.detail == "Access denied to project"
