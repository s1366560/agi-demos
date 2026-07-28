from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from src.infrastructure.adapters.primary.web.routers.cron import (
    _require_project_access,
    get_cron_job_capabilities,
)

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


async def test_capabilities_fail_closed_with_stable_reason_codes() -> None:
    db = AsyncMock()
    db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value="membership-1"))

    response = await get_cron_job_capabilities(
        "project-1",
        SimpleNamespace(id="user-1"),
        db,
    )

    assert response.service_version == "0.1.0"
    assert response.contract_version == "2.0.0"
    assert response.schema_version == 1
    assert response.read is True
    assert response.revision_guarded is False
    assert response.idempotency_guarded is False
    assert response.durable_execution is False
    assert response.create.allowed is False
    assert response.create.reason_code == "durable_automation_runtime_unavailable"
    assert response.run_now.allowed is False
    assert response.run_now.reason_code == "durable_automation_execution_unavailable"
