from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from pydantic import TypeAdapter, ValidationError

from src.application.schemas.cron import AutomationRunCommandV2, ManualRunRequest
from src.application.services.automation_command_service import (
    AutomationRunReceipt,
)
from src.domain.model.cron.cron_job import CronJob
from src.infrastructure.adapters.primary.web.routers import cron as cron_router
from src.infrastructure.adapters.primary.web.routers.cron import (
    _require_project_access,
    get_cron_job_capabilities,
)

pytestmark = pytest.mark.unit


def test_manual_run_contract_selects_v2_only_with_an_explicit_valid_version() -> None:
    adapter = TypeAdapter(AutomationRunCommandV2 | ManualRunRequest)
    v2 = adapter.validate_python(
        {
            "contract_version": 2,
            "expected_revision": 7,
            "idempotency_key": "run-now-1",
        }
    )
    assert isinstance(v2, AutomationRunCommandV2)
    assert isinstance(
        adapter.validate_python({"conversation_id": "conversation-1"}),
        ManualRunRequest,
    )

    for invalid in (
        {"expected_revision": 7, "idempotency_key": "run-now-1"},
        {
            "contract_version": 3,
            "expected_revision": 7,
            "idempotency_key": "run-now-1",
        },
        {
            "contract_version": 2,
            "expected_revision": 7,
            "idempotency_key": "contains whitespace",
        },
    ):
        with pytest.raises(ValidationError):
            adapter.validate_python(invalid)


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


async def test_manual_run_v2_returns_one_durable_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    db = AsyncMock()
    db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value="membership-1"))
    job = CronJob(
        project_id="project-1",
        tenant_id="tenant-1",
        name="Durable job",
        revision=7,
    )
    cron_service = SimpleNamespace(get_job=AsyncMock(return_value=job))
    command_service = SimpleNamespace(
        queue_manual_run=AsyncMock(
            return_value=AutomationRunReceipt(
                receipt_id="receipt-1",
                operation_id="operation-1",
                run_id="run-1",
                runtime_execution_id="execution-1",
                job_id=job.id,
                job_revision=7,
                status="queued",
                duplicate=False,
            )
        )
    )
    monkeypatch.setattr(
        cron_router,
        "_container",
        lambda _db: SimpleNamespace(cron_job_service=Mock(return_value=cron_service)),
    )
    monkeypatch.setattr(
        cron_router,
        "_automation_command_service",
        lambda _db: command_service,
    )

    response = await cron_router.trigger_manual_run(
        project_id="project-1",
        job_id=job.id,
        body=AutomationRunCommandV2(
            contract_version=2,
            expected_revision=7,
            idempotency_key="run-now-1",
            conversation_id="conversation-1",
        ),
        current_user=SimpleNamespace(id="user-1"),
        db=db,
    )

    assert response.model_dump() == {
        "contract_version": 2,
        "receipt_id": "receipt-1",
        "operation_id": "operation-1",
        "run_id": "run-1",
        "runtime_execution_id": "execution-1",
        "job_id": job.id,
        "job_revision": 7,
        "status": "queued",
        "duplicate": False,
    }
    queued = command_service.queue_manual_run.await_args.kwargs
    assert queued["actor"].tenant_id == "tenant-1"
    assert queued["actor"].project_id == "project-1"
    assert queued["actor"].user_id == "user-1"
    assert queued["command"].expected_revision == 7
    assert queued["command"].idempotency_key == "run-now-1"
    assert queued["command"].conversation_id == "conversation-1"
    db.commit.assert_awaited_once()


async def test_manual_run_without_contract_version_keeps_legacy_unavailable_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = AsyncMock()
    db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value="membership-1"))
    job = CronJob(
        project_id="project-1",
        tenant_id="tenant-1",
        name="Legacy job",
    )
    cron_service = SimpleNamespace(
        get_job=AsyncMock(return_value=job),
        trigger_manual_run=AsyncMock(
            side_effect=cron_router.CronExecutionUnavailableError("unavailable")
        ),
    )
    command_service = SimpleNamespace(queue_manual_run=AsyncMock())
    monkeypatch.setattr(
        cron_router,
        "_container",
        lambda _db: SimpleNamespace(cron_job_service=Mock(return_value=cron_service)),
    )
    monkeypatch.setattr(
        cron_router,
        "_automation_command_service",
        lambda _db: command_service,
    )

    with pytest.raises(HTTPException) as exc_info:
        await cron_router.trigger_manual_run(
            project_id="project-1",
            job_id=job.id,
            body=ManualRunRequest(conversation_id="conversation-1"),
            current_user=SimpleNamespace(id="user-1"),
            db=db,
        )

    assert exc_info.value.status_code == 503
    command_service.queue_manual_run.assert_not_awaited()
