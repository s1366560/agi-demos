from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from src.infrastructure.adapters.primary.web.routers.cron import _require_project_access

pytestmark = pytest.mark.unit


async def test_require_project_access_accepts_explicit_membership() -> None:
    db = AsyncMock()
    db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value="membership-1"))

    await _require_project_access(
        "project-1",
        SimpleNamespace(id="user-1"),
        db,
    )

    db.execute.assert_awaited_once()


async def test_require_project_access_rejects_non_members() -> None:
    db = AsyncMock()
    db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=None))

    with pytest.raises(HTTPException) as exc_info:
        await _require_project_access(
            "project-1",
            SimpleNamespace(id="user-1"),
            db,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Access denied to project"
