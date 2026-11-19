"""Startup publish can lag scheduler sync. Do not admit until the host exists."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from src.domain.model.cron.cron_job import CronJob
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.scheduler import job_executor


class _Session:
    async def rollback(self) -> None:
        return None

    async def commit(self) -> None:
        return None


class _SessionScope:
    async def __aenter__(self) -> _Session:
        return _Session()

    async def __aexit__(self, *_exc: object) -> bool:
        return False


def _job() -> CronJob:
    return CronJob(
        id="job-1",
        project_id="project-1",
        tenant_id="tenant-1",
        name="probe",
    )


@pytest.mark.unit
async def test_missing_host_does_not_open_a_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job_executor, "_HOST_READY_TIMEOUT_S", 0.0)

    def _missing() -> object:
        raise RuntimeV2Error("process_generation_host_not_configured", "host missing")

    monkeypatch.setattr(
        "src.infrastructure.plugins.v2.boundary.current_process_generation_host_v2",
        _missing,
    )
    opened = {"count": 0}

    def _factory() -> _SessionScope:
        opened["count"] += 1
        return _SessionScope()

    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
        _factory,
    )

    await job_executor.execute_cron_job("job-1")

    assert opened["count"] == 0


@pytest.mark.unit
async def test_publish_during_wait_pins_the_job_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(job_executor, "_HOST_READY_TIMEOUT_S", 1.0)
    monkeypatch.setattr(job_executor, "_HOST_READY_POLL_S", 0.01)
    published = {"ready": False}
    pinned: dict[str, Any] = {}

    def _current() -> object:
        if not published["ready"]:
            raise RuntimeV2Error("process_generation_host_not_configured", "host missing")
        return object()

    async def _publish_later() -> None:
        await asyncio.sleep(0.03)
        published["ready"] = True

    monkeypatch.setattr(
        "src.infrastructure.plugins.v2.boundary.current_process_generation_host_v2",
        _current,
    )

    @asynccontextmanager
    async def _pin(**kwargs: Any) -> Any:
        pinned.update(kwargs)
        yield object()

    monkeypatch.setattr("src.infrastructure.plugins.v2.boundary.pin_agent_turn_operation_v2", _pin)

    class _Repo:
        def __init__(self, _session: object) -> None:
            return None

        async def find_by_id(self, _job_id: str) -> CronJob:
            return _job()

    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
        lambda: _SessionScope(),
    )
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.sql_cron_job_repository.SqlCronJobRepository",
        _Repo,
    )

    async def _no_open_run(_session: object, _job_id: str) -> None:
        return None

    async def _conversation(_job: CronJob, _session: object) -> str:
        return "conversation-1"

    async def _admit(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(message_id="message-1", run_id="run-1")

    dispatched = {"count": 0}

    async def _dispatch(*_args: object, **_kwargs: object) -> None:
        dispatched["count"] += 1
        assert pinned["tenant_id"] == "tenant-1"
        assert pinned["project_id"] == "project-1"
        assert pinned["session_id"] == "conversation-1"
        assert pinned["force_process_host_lease"] is True

    monkeypatch.setattr(job_executor, "_open_scheduled_run_id", _no_open_run)
    monkeypatch.setattr(job_executor, "_resolve_conversation", _conversation)
    monkeypatch.setattr(job_executor, "_admit_legacy_execution", _admit)
    monkeypatch.setattr(job_executor, "_dispatch_payload", _dispatch)

    publisher = asyncio.create_task(_publish_later())
    await job_executor.execute_cron_job("job-1")
    await publisher

    assert dispatched["count"] == 1
    assert pinned["tenant_id"] == "tenant-1"


@pytest.mark.unit
async def test_pin_failure_after_admission_is_closed_without_a_second_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(job_executor, "_HOST_READY_TIMEOUT_S", 0.2)

    monkeypatch.setattr(
        "src.infrastructure.plugins.v2.boundary.current_process_generation_host_v2",
        lambda: object(),
    )

    class _Repo:
        def __init__(self, _session: object) -> None:
            return None

        async def find_by_id(self, _job_id: str) -> CronJob:
            return _job()

    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
        lambda: _SessionScope(),
    )
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.sql_cron_job_repository.SqlCronJobRepository",
        _Repo,
    )
    monkeypatch.setattr(job_executor, "_open_scheduled_run_id", lambda *_a, **_k: _async_none())
    monkeypatch.setattr(
        job_executor, "_resolve_conversation", lambda *_a, **_k: _async_value("conversation-1")
    )
    identity = SimpleNamespace(message_id="message-1", run_id="run-1")
    monkeypatch.setattr(
        job_executor,
        "_admit_legacy_execution",
        lambda *_a, **_k: _async_value(identity),
    )

    async def _dispatch(*_args: object, **_kwargs: object) -> None:
        raise RuntimeV2Error(
            "operation_context_not_pinned", "plugin operation context is not pinned"
        )

    closed: dict[str, Any] = {}

    async def _close(admission: object, exc: BaseException) -> None:
        closed["admission"] = admission
        closed["code"] = getattr(exc, "code", None)

    monkeypatch.setattr(job_executor, "_dispatch_payload", _dispatch)
    monkeypatch.setattr(job_executor, "_fail_unstarted_delivery", _close)

    @asynccontextmanager
    async def _pin(**_kwargs: Any) -> Any:
        yield object()

    monkeypatch.setattr("src.infrastructure.plugins.v2.boundary.pin_agent_turn_operation_v2", _pin)

    await job_executor.execute_cron_job("job-1")

    assert closed["admission"] is identity
    assert closed["code"] == "operation_context_not_pinned"


async def _async_none() -> None:
    return None


async def _async_value(value: object) -> object:
    return value
