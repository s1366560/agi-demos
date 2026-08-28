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
