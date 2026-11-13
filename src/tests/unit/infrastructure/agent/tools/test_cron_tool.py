"""Unit tests for the cron agent tool."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.application.services.cron_service import CronMutationUnavailableError
from src.infrastructure.agent.tools import cron_tool as cron_tool_module
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.cron_tool import cron_tool, make_cron_tool

pytestmark = pytest.mark.unit


def _make_ctx(**overrides: Any) -> ToolContext:
    defaults: dict[str, Any] = {
        "session_id": "session-1",
        "message_id": "msg-1",
        "call_id": "call-1",
        "agent_name": "test-agent",
        "conversation_id": "conv-1",
        "project_id": "project-1",
    }
    defaults.update(overrides)
    return ToolContext(**defaults)


async def test_update_returns_invalid_schedule_error_before_session_access() -> None:
    result = await cron_tool.execute(
        _make_ctx(),
        action="update",
        job_id="job-1",
        patch={
            "schedule": {
                "kind": "every",
                "config": {"hours": 0, "minutes": 0, "seconds": 0},
            }
        },
    )

    payload = json.loads(result.output)

    assert result.is_error is True
    assert payload["error"].startswith("Invalid schedule:")
    assert "every schedule requires interval_seconds" in payload["error"]


@pytest.mark.parametrize("action", ["update", "remove"])
async def test_mutation_actions_surface_fail_closed_error_without_commit(
    action: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SimpleNamespace(commit=AsyncMock())

    @asynccontextmanager
    async def session_factory():
        yield session

    service = SimpleNamespace(
        update_job=AsyncMock(
            side_effect=CronMutationUnavailableError(
                "Update requires durable automation command processing"
            )
        ),
        delete_job=AsyncMock(
            side_effect=CronMutationUnavailableError(
                "Delete requires durable automation command processing"
            )
        ),
    )
    monkeypatch.setattr(cron_tool_module, "_build_service", lambda _session: service)
    bound_tool = make_cron_tool(session_factory=session_factory)

    kwargs = (
        {"action": "update", "job_id": "job-1", "patch": {"name": "Updated"}}
        if action == "update"
        else {"action": "remove", "job_id": "job-1"}
    )
    result = await bound_tool.execute(_make_ctx(), **kwargs)
    payload = json.loads(result.output)

    assert result.is_error is True
    assert "durable automation command processing" in payload["error"]
    session.commit.assert_not_awaited()


@pytest.mark.parametrize("action", ["run", "runs"])
async def test_job_actions_reject_cross_project_job_ids(
    action: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SimpleNamespace(commit=AsyncMock())

    @asynccontextmanager
    async def session_factory():
        yield session

    service = SimpleNamespace(
        get_job=AsyncMock(return_value=SimpleNamespace(id="job-1", project_id="project-2")),
        trigger_manual_run=AsyncMock(),
        list_runs=AsyncMock(),
        count_runs=AsyncMock(),
    )
    monkeypatch.setattr(cron_tool_module, "_build_service", lambda _session: service)
    bound_tool = make_cron_tool(session_factory=session_factory)

    result = await bound_tool.execute(_make_ctx(), action=action, job_id="job-1")
    payload = json.loads(result.output)

    assert result.is_error is True
    assert payload == {"error": "CronJob job-1 not found"}
    service.trigger_manual_run.assert_not_awaited()
    service.list_runs.assert_not_awaited()
    session.commit.assert_not_awaited()


async def test_bound_cron_factories_are_isolated_during_interleaved_awaits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    exits: dict[str, int] = {"a": 0, "b": 0}

    @asynccontextmanager
    async def _session(label: str):
        try:
            yield SimpleNamespace(label=label)
        finally:
            exits[label] += 1

    class _Service:
        def __init__(self, label: str) -> None:
            self.label = label
            self.count_calls = 0

        async def count_jobs(self, _project_id: str, *, include_disabled: bool) -> int:
            self.count_calls += 1
            if self.count_calls == 1:
                if self.label == "a":
                    first_entered.set()
                    await release_first.wait()
                elif self.label == "b":
                    await first_entered.wait()
                    release_first.set()
                    await asyncio.sleep(0)
            totals = {"a": (2, 1), "b": (5, 3)}
            total, enabled = totals[self.label]
            return total if include_disabled else enabled

        async def list_jobs(
            self,
            _project_id: str,
            *,
            include_disabled: bool,
            limit: int,
        ) -> list[object]:
            _ = include_disabled, limit
            return []

    monkeypatch.setattr(
        cron_tool_module,
        "_build_service",
        lambda session: _Service(session.label),
    )
    tool_a = make_cron_tool(session_factory=lambda: _session("a"))
    tool_b = make_cron_tool(session_factory=lambda: _session("b"))

    result_a, result_b = await asyncio.gather(
        tool_a.execute(_make_ctx(project_id="project-a"), action="status"),
        tool_b.execute(_make_ctx(project_id="project-b"), action="status"),
    )

    assert result_a.metadata == {"total": 2, "enabled": 1}
    assert result_b.metadata == {"total": 5, "enabled": 3}
    assert exits == {"a": 1, "b": 1}


async def test_unbound_cron_template_rejects_legacy_runtime_fallback() -> None:
    result = await cron_tool.execute(_make_ctx(), action="status")

    assert result.is_error is True
    assert json.loads(result.output) == {
        "error": "Cron tool error: cron requires a generation-bound runtime"
    }


def test_cron_module_has_no_legacy_configure_seam() -> None:
    assert not hasattr(cron_tool_module, "configure_cron_tool")


async def test_status_and_list_share_job_keys_and_add_stays_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = SimpleNamespace(
        id="job-1",
        name="nightly",
        enabled=True,
        schedule=SimpleNamespace(to_dict=lambda: {"kind": "every"}),
        payload=SimpleNamespace(kind=SimpleNamespace(value="agent")),
        timezone="UTC",
        conversation_mode=SimpleNamespace(value="reuse"),
        conversation_id=None,
        state="idle",
    )

    class _Service:
        async def count_jobs(self, _project_id: str, *, include_disabled: bool) -> int:
            _ = include_disabled
            return 1

        async def list_jobs(self, *_args: object, **_kwargs: object) -> list[object]:
            return [job]

        async def create_job(self, **_kwargs: object) -> None:
            raise CronMutationUnavailableError(
                "Create requires durable automation command processing; no job was created"
            )

    @asynccontextmanager
    async def session_factory():
        yield SimpleNamespace()

    class _ProjectRepo:
        def __init__(self, _session: object) -> None:
            return None

        async def find_by_id(self, _project_id: str) -> SimpleNamespace:
            return SimpleNamespace(tenant_id="tenant-1")

    monkeypatch.setattr(cron_tool_module, "_build_service", lambda _session: _Service())
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.sql_project_repository.SqlProjectRepository",
        _ProjectRepo,
    )
    tool = make_cron_tool(session_factory=session_factory)
    status = json.loads((await tool.execute(_make_ctx(), action="status")).output)
    listed = json.loads((await tool.execute(_make_ctx(), action="list")).output)
    assert status["jobs"] == status["items"]
    assert listed["jobs"] == listed["items"]
    assert status["jobs"][0]["id"] == "job-1"
    added = await tool.execute(
        _make_ctx(),
        action="add",
        job={
            "name": "nightly",
            "schedule": {"kind": "every", "config": {"interval_seconds": 60}},
            "payload": {"kind": "agent_turn", "config": {"message": "check"}},
        },
    )
    assert added.is_error is True
    assert "no job was created" in json.loads(added.output)["error"]


async def test_update_remove_and_run_forward_revision_and_idempotency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.domain.model.cron.cron_job import CronJob
    from src.domain.model.cron.cron_job_run import CronJobRun
    from src.domain.model.cron.value_objects import CronRunStatus, TriggerType

    job = CronJob(id="job-1", project_id="project-1", tenant_id="tenant-1", name="kept")
    calls: list[tuple[str, dict[str, object]]] = []

    class _Service:
        async def update_job(self, job_id: str, **kwargs: object) -> CronJob:
            calls.append((job_id, kwargs))
            return job

        async def delete_job(self, job_id: str, **kwargs: object) -> bool:
            calls.append((job_id, kwargs))
            return True

        async def get_job(self, job_id: str) -> CronJob:
            assert job_id == "job-1"
            return job

        async def trigger_manual_run(self, job_id: str, **kwargs: object) -> CronJobRun:
            calls.append((job_id, kwargs))
            return CronJobRun(
                id="run-1",
                job_id=job_id,
                project_id="project-1",
                status=CronRunStatus.QUEUED,
                trigger_type=TriggerType.MANUAL,
            )

    @asynccontextmanager
    async def session_factory():
        yield SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(cron_tool_module, "_build_service", lambda _session: _Service())
    monkeypatch.setattr(
        cron_tool_module,
        "_try_register_job",
        AsyncMock(
            return_value={
                "scheduler_registration": "registered",
                "executable": False,
                "run_state": "not_started",
            }
        ),
    )
    monkeypatch.setattr(cron_tool_module, "_try_unregister_job", AsyncMock())
    tool = make_cron_tool(session_factory=session_factory)
    ctx = _make_ctx(user_id="user-1")
    updated = await tool.execute(
        ctx,
        action="update",
        job_id="job-1",
        patch={"name": "kept"},
        expected_revision=2,
        idempotency_key="revise-1",
    )
    removed = await tool.execute(
        ctx,
        action="remove",
        job_id="job-1",
        expected_revision=3,
        idempotency_key="delete-1",
    )
    ran = await tool.execute(
        ctx,
        action="run",
        job_id="job-1",
        expected_revision=3,
        idempotency_key="run-1",
    )
    assert updated.is_error is False
    assert removed.is_error is False
    assert ran.is_error is False
    assert calls[0][1]["expected_revision"] == 2
    assert calls[0][1]["idempotency_key"] == "revise-1"
    assert calls[0][1]["project_id"] == "project-1"
    assert calls[0][1]["actor_user_id"] == "user-1"
    assert calls[1][1]["idempotency_key"] == "delete-1"
    assert calls[2][1]["expected_revision"] == 3
    assert calls[2][1]["idempotency_key"] == "run-1"
    updated_payload = json.loads(updated.output)
    assert updated_payload["scheduler_registration"] == "registered"
    assert updated_payload["executable"] is False
    assert updated_payload["run_state"] == "not_started"


async def test_scheduler_rejection_stays_durable_and_not_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = SimpleNamespace(
        id="job-pending",
        enabled=True,
        timezone="UTC",
        schedule=SimpleNamespace(
            kind=SimpleNamespace(value="every"),
            config={"interval_seconds": 60},
        ),
    )

    async def _reject(**_kwargs: object) -> None:
        raise RuntimeError("Scheduler not initialised -- call start_scheduler() first")

    monkeypatch.setattr(
        "src.infrastructure.scheduler.scheduler_service.register_job",
        _reject,
    )
    report = await cron_tool_module._try_register_job(job)  # type: ignore[arg-type]

    assert report["scheduler_registration"] == "registration_pending"
    assert report["executable"] is False
    assert report["run_state"] == "not_started"
    assert report["failure_class"] == "backend"
    assert report["code"] == "scheduler_registration_unavailable"
    assert "no run was queued" in report["message"]
