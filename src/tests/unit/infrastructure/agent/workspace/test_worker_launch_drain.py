"""Unit tests for :mod:`worker_launch_drain`.

Regression anchors: the drain helper is the single path that converts
``WorkspaceTaskCommandService._pending_worker_launches`` into real worker
session launches. Skipping or crashing it leaves assigned execution tasks
stranded with no conversation (the ``2c11849d-…`` stuck-workspace bug).
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

from src.application.services.workspace_task_command_service import (
    WorkspaceTaskCommandService,
)
from src.infrastructure.agent.workspace import worker_launch_drain


@dataclass
class _FakeTask:
    id: str
    workspace_id: str
    assignee_agent_id: str | None = None


@pytest.mark.unit
class TestDrainPendingWorkerLaunches:
    def test_empty_queue_is_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[dict] = []
        monkeypatch.setattr(
            worker_launch_drain.worker_launch_mod,
            "schedule_worker_session",
            lambda **kw: calls.append(kw),
        )
        command_service = WorkspaceTaskCommandService(AsyncMock())

        fired = worker_launch_drain.drain_pending_worker_launches(command_service)

        assert fired == 0
        assert calls == []

    def test_fires_all_queued_entries_and_clears_queue(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[dict] = []
        monkeypatch.setattr(
            worker_launch_drain.worker_launch_mod,
            "schedule_worker_session",
            lambda **kw: calls.append(kw),
        )
        command_service = WorkspaceTaskCommandService(AsyncMock())
        t1 = _FakeTask(id="wt-1", workspace_id="ws-1", assignee_agent_id="agent-1")
        t2 = _FakeTask(id="wt-2", workspace_id="ws-1", assignee_agent_id="agent-2")
        command_service._pending_worker_launches.extend(
            [(t1, "user-1", "leader-1"), (t2, "user-1", "leader-1")]
        )

        fired = worker_launch_drain.drain_pending_worker_launches(command_service)

        assert fired == 2
        assert [c["worker_agent_id"] for c in calls] == ["agent-1", "agent-2"]
        assert command_service._pending_worker_launches == []

    def test_skips_entries_missing_assignee(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[dict] = []
        monkeypatch.setattr(
            worker_launch_drain.worker_launch_mod,
            "schedule_worker_session",
            lambda **kw: calls.append(kw),
        )
        command_service = WorkspaceTaskCommandService(AsyncMock())
        t_bad = _FakeTask(id="wt-bad", workspace_id="ws-1", assignee_agent_id=None)
        t_good = _FakeTask(id="wt-good", workspace_id="ws-1", assignee_agent_id="agent-x")
        command_service._pending_worker_launches.extend(
            [(t_bad, "user-1", None), (t_good, "user-1", None)]
        )

        fired = worker_launch_drain.drain_pending_worker_launches(command_service)

        assert fired == 1
        assert calls[0]["worker_agent_id"] == "agent-x"

    def test_swallows_scheduler_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A single scheduler failure must not abort the rest of the drain."""
        attempts: list[str] = []

        def _boom(**kw: object) -> None:
            attempts.append(str(kw["worker_agent_id"]))
            if kw["worker_agent_id"] == "agent-1":
                raise RuntimeError("boom")

        monkeypatch.setattr(
            worker_launch_drain.worker_launch_mod,
            "schedule_worker_session",
            _boom,
        )
        command_service = WorkspaceTaskCommandService(AsyncMock())
        t1 = _FakeTask(id="wt-1", workspace_id="ws-1", assignee_agent_id="agent-1")
        t2 = _FakeTask(id="wt-2", workspace_id="ws-1", assignee_agent_id="agent-2")
        command_service._pending_worker_launches.extend(
            [(t1, "user-1", None), (t2, "user-1", None)]
        )

        fired = worker_launch_drain.drain_pending_worker_launches(command_service)

        assert attempts == ["agent-1", "agent-2"]
        assert fired == 1  # only agent-2 counted
