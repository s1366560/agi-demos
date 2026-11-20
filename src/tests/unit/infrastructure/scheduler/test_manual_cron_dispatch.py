"""Durable manual runs must not use the legacy admission claim."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from src.domain.model.cron.cron_job import CronJob
from src.infrastructure.scheduler import job_executor


class _Run:
    def __init__(self, *, runtime_execution_id: str | None) -> None:
        self.id = "run-1"
        self.job_id = "job-1"
        self.status = "queued"
        self.runtime_execution_id = runtime_execution_id
        self.conversation_id = "conv-1"
        self.started_at = datetime.now(UTC)
        self.finished_at = None
        self.error_message = None
        self.duration_ms = None


class _Operation:
    def __init__(self) -> None:
        self.status = "pending"
        self.started_at = None
        self.updated_at = None
        self.last_error_code = None
        self.last_error_redacted = None
        self.completed_at = None
        self.next_attempt_at = None


class _Session:
    def __init__(self, run: _Run, operation: _Operation) -> None:
        self.run = run
        self.operation = operation
        self.commits = 0

    async def get(self, _model: object, _identity: str) -> _Run:
        return self.run

    async def scalar(self, _statement: object) -> _Operation:
        return self.operation

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


def _job() -> CronJob:
    return CronJob(id="job-1", project_id="project-1", tenant_id="tenant-1", name="probe")


def _install_store(
    monkeypatch: pytest.MonkeyPatch,
    run: _Run,
    operation: _Operation,
) -> _Session:
    session = _Session(run, operation)

    class _Repo:
        def __init__(self, _session: object) -> None:
            return None

        async def find_by_id(self, _job_id: str) -> CronJob:
            return _job()

    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
        lambda: session,
    )
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.sql_cron_job_repository.SqlCronJobRepository",
        _Repo,
    )
    monkeypatch.setattr(job_executor, "_wait_for_process_host", _ready)
    return session


async def _ready() -> bool:
    return True


@pytest.mark.unit
async def test_durable_manual_run_skips_legacy_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _Run(runtime_execution_id="run-1")
    operation = _Operation()
    _install_store(monkeypatch, run, operation)
    seen: dict[str, Any] = {}

    async def _durable(
        job: CronJob,
        conversation_id: str,
        _session: object,
        runtime_execution_id: str,
    ) -> None:
        seen["job_id"] = job.id
        seen["conversation_id"] = conversation_id
        seen["runtime_execution_id"] = runtime_execution_id
        seen["operation_status"] = operation.status

    async def _legacy(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("durable runs must not open a legacy admission")

    monkeypatch.setattr(job_executor, "_execute_durable_payload", _durable)
    monkeypatch.setattr(job_executor, "_admit_legacy_execution", _legacy)

    result = await job_executor.dispatch_queued_manual_run("job-1", "run-1")

    assert result["dispatched"] is True
    assert seen == {
        "job_id": "job-1",
        "conversation_id": "conv-1",
        "runtime_execution_id": "run-1",
        "operation_status": "waiting_runtime",
    }
    assert run.status == "queued"


@pytest.mark.unit
async def test_failed_durable_dispatch_closes_waiting_runtime_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _Run(runtime_execution_id="run-1")
    operation = _Operation()
    _install_store(monkeypatch, run, operation)

    async def _durable(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("actor refused the run")

    monkeypatch.setattr(job_executor, "_execute_durable_payload", _durable)

    result = await job_executor.dispatch_queued_manual_run("job-1", "run-1")

    assert result["dispatched"] is False
    assert result["status"] == "failed"
    assert run.status == "failed"
    assert run.finished_at is not None
    assert operation.status == "failed"
    assert operation.completed_at is not None


@pytest.mark.unit
async def test_legacy_dispatch_failure_closes_the_committed_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _Run(runtime_execution_id=None)
    operation = _Operation()
    _install_store(monkeypatch, run, operation)
    identity = SimpleNamespace(run_id="run-1", message_id="run-1")
    closed: dict[str, object] = {}

    async def _admit(*_args: object, **_kwargs: object) -> SimpleNamespace:
        operation.status = "waiting_runtime"
        return identity

    async def _payload(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("delivery failed before start")

    async def _close(admission: object, exc: BaseException) -> None:
        closed["admission"] = admission
        closed["error"] = str(exc)
        run.status = "failed"

    monkeypatch.setattr(job_executor, "_admit_legacy_execution", _admit)
    monkeypatch.setattr(job_executor, "_execute_payload", _payload)
    monkeypatch.setattr(job_executor, "_fail_unstarted_delivery", _close)

    result = await job_executor.dispatch_queued_manual_run("job-1", "run-1")

    assert result["dispatched"] is False
    assert closed["admission"] is identity
    assert run.status == "failed"
    assert operation.status == "failed"
