"""Unit tests for the cron agent tool."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.application.services.cron_service import CronMutationUnavailableError
from src.infrastructure.agent.tools import cron_tool as cron_tool_module
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.cron_tool import cron_tool

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
    monkeypatch.setattr(cron_tool_module, "_cron_session_factory", session_factory)
    monkeypatch.setattr(cron_tool_module, "_build_service", lambda _session: service)

    kwargs = (
        {"action": "update", "job_id": "job-1", "patch": {"name": "Updated"}}
        if action == "update"
        else {"action": "remove", "job_id": "job-1"}
    )
    result = await cron_tool.execute(_make_ctx(), **kwargs)
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
    monkeypatch.setattr(cron_tool_module, "_cron_session_factory", session_factory)
    monkeypatch.setattr(cron_tool_module, "_build_service", lambda _session: service)

    result = await cron_tool.execute(_make_ctx(), action=action, job_id="job-1")
    payload = json.loads(result.output)

    assert result.is_error is True
    assert payload == {"error": "CronJob job-1 not found"}
    service.trigger_manual_run.assert_not_awaited()
    service.list_runs.assert_not_awaited()
    session.commit.assert_not_awaited()
