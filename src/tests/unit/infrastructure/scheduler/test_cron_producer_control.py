"""Local producer inspection labels shared storage and never starts a scheduler."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.scheduler import scheduler_service

pytestmark = pytest.mark.unit


async def test_inspection_without_scheduler_is_read_only_and_unavailable(monkeypatch):
    from src.infrastructure.plugins.v2.cron_producer_control import BuiltinCronProducerControlV2

    monkeypatch.setattr(scheduler_service, "_scheduler", None)
    start = AsyncMock(side_effect=AssertionError("inspection must not start scheduler"))
    monkeypatch.setattr(scheduler_service, "start_scheduler", start)
    result = await BuiltinCronProducerControlV2().inspect_local()
    assert result["responding_producer_id"] is None
    assert result["datastore_view"]["status"] == "unavailable"
    assert result["verified"] is False
    start.assert_not_awaited()


async def test_inspection_labels_shared_schedule_view_and_local_seal(monkeypatch):
    from src.infrastructure.adapters.secondary.persistence import database
    from src.infrastructure.adapters.secondary.persistence.sql_cron_cutover_repository import (
        SqlCronCutoverRepository,
    )
    from src.infrastructure.plugins.v2.cron_producer_control import BuiltinCronProducerControlV2

    reference = "src.infrastructure.scheduler.job_executor:execute_cron_job"
    scheduler = SimpleNamespace(
        identity="actual-worker",
        get_tasks=AsyncMock(return_value=[SimpleNamespace(id=reference, func=reference)]),
        get_schedules=AsyncMock(
            return_value=[
                SimpleNamespace(
                    id="shared-job", task_id=reference, args=(), kwargs={"job_id": "shared-job"}
                )
            ]
        ),
    )
    monkeypatch.setattr(scheduler_service, "_scheduler", scheduler)
    monkeypatch.setattr(scheduler_service, "_scheduler_lock", asyncio.Lock())
    monkeypatch.setattr(scheduler_service, "_cron_registration_seal", ("deployment", 1))

    @asynccontextmanager
    async def sessions():
        yield object()

    monkeypatch.setattr(database, "async_session_factory", sessions)
    monkeypatch.setattr(
        SqlCronCutoverRepository,
        "read",
        AsyncMock(
            return_value=SimpleNamespace(to_wire=lambda: {"phase": "prepared", "revision": 1})
        ),
    )
    result = await BuiltinCronProducerControlV2().inspect_local()
    assert result["responding_producer_id"] == "actual-worker"
    assert result["local_registration_sealed"] is True
    assert result["datastore_view"]["scope"] == "shared_scheduler_datastore"
    assert result["datastore_view"]["canonical_cron_schedule_ids"] == ["shared-job"]
    assert result["discovery_complete"] is False
    assert "owned_schedule_ids" not in result["datastore_view"]


async def test_wrong_process_close_does_not_access_barrier(monkeypatch):
    from src.infrastructure.adapters.secondary.persistence.sql_cron_cutover_repository import (
        SqlCronCutoverRepository,
    )
    from src.infrastructure.plugins.v2.cron_producer_control import BuiltinCronProducerControlV2
    from src.infrastructure.scheduler.cron_deployment_drain import CronProducerCloseRequest

    monkeypatch.setattr(scheduler_service, "_scheduler", SimpleNamespace(identity="actual-worker"))
    monkeypatch.setattr(scheduler_service, "_scheduler_lock", asyncio.Lock())
    read = AsyncMock(side_effect=AssertionError("wrong worker must not read prepared state"))
    monkeypatch.setattr(SqlCronCutoverRepository, "require_prepared_deployment", read)
    result = await BuiltinCronProducerControlV2().close_prepared(
        CronProducerCloseRequest(
            deployment_id="deployment",
            source_generation="old",
            producer_id="different-worker",
            expected_revision=1,
            schedule_ids=("job",),
        )
    )
    assert result.reason_code == "local_producer_identity_mismatch"
    read.assert_not_awaited()
