"""Unit tests for src.infrastructure.agent.workspace.worker_launch (P3 M-bug)."""

from __future__ import annotations

import asyncio

import pytest

from src.domain.model.workspace.workspace_task import (
    WorkspaceTask,
    WorkspaceTaskStatus,
)
from src.infrastructure.agent.workspace import worker_launch as wl


def _make_task(
    *,
    task_id: str = "task-1",
    workspace_id: str = "ws-1",
    title: str = "Build report",
    description: str | None = "Render quarterly stats",
    metadata: dict | None = None,
) -> WorkspaceTask:
    return WorkspaceTask(
        id=task_id,
        workspace_id=workspace_id,
        title=title,
        description=description,
        created_by="user-1",
        status=WorkspaceTaskStatus.TODO,
        metadata=metadata or {"task_role": "execution", "root_goal_task_id": "root-1"},
    )


class TestConversationScope:
    def test_without_attempt(self) -> None:
        assert wl._conversation_scope_for_task("t1") == "task:t1"

    def test_with_attempt(self) -> None:
        assert wl._conversation_scope_for_task("t1", "att-9") == "task:t1:attempt:att-9"


class TestConversationId:
    def test_deterministic_and_distinct_per_scope(self) -> None:
        a = wl._conversation_id_for_worker(
            workspace_id="w", worker_agent_id="agent-X", task_id="t1"
        )
        b = wl._conversation_id_for_worker(
            workspace_id="w", worker_agent_id="agent-X", task_id="t1"
        )
        c = wl._conversation_id_for_worker(
            workspace_id="w",
            worker_agent_id="agent-X",
            task_id="t1",
            attempt_id="att-9",
        )
        assert a == b
        assert a != c
        # UUIDv5 length
        assert len(a) == 36

    def test_distinct_per_agent(self) -> None:
        a = wl._conversation_id_for_worker(
            workspace_id="w", worker_agent_id="agent-A", task_id="t1"
        )
        b = wl._conversation_id_for_worker(
            workspace_id="w", worker_agent_id="agent-B", task_id="t1"
        )
        assert a != b


class TestBuildBrief:
    def test_includes_binding_block_and_title(self) -> None:
        task = _make_task()
        brief = wl._build_worker_brief(
            workspace_id="ws-1",
            task=task,
            attempt_id=None,
            leader_agent_id="leader-1",
        )
        assert "[workspace-task-binding]" in brief
        assert "workspace_id=ws-1" in brief
        assert "workspace_task_id=task-1" in brief
        assert "root_goal_task_id=root-1" in brief
        assert "leader_agent_id=leader-1" in brief
        assert "## Task title" in brief
        assert "Build report" in brief
        assert "Render quarterly stats" in brief

    def test_omits_attempt_when_none(self) -> None:
        task = _make_task()
        brief = wl._build_worker_brief(
            workspace_id="w",
            task=task,
            attempt_id=None,
            leader_agent_id=None,
        )
        assert "attempt_id" not in brief

    def test_includes_attempt_and_extra(self) -> None:
        task = _make_task()
        brief = wl._build_worker_brief(
            workspace_id="w",
            task=task,
            attempt_id="att-2",
            leader_agent_id="L",
            extra_instructions="Be brief.",
        )
        assert "attempt_id=att-2" in brief
        assert "Additional instructions" in brief
        assert "Be brief." in brief

    def test_handles_missing_description(self) -> None:
        task = _make_task(description=None)
        brief = wl._build_worker_brief(
            workspace_id="w", task=task, attempt_id=None, leader_agent_id=None
        )
        assert "Task description" not in brief


class TestLaunchWorkerSession:
    @pytest.mark.asyncio
    async def test_missing_worker_agent_id(self) -> None:
        task = _make_task()
        out = await wl.launch_worker_session(
            workspace_id="w",
            task=task,
            worker_agent_id="",
            actor_user_id="u1",
        )
        assert out == {
            "launched": False,
            "conversation_id": None,
            "attempt_id": None,
            "reason": "worker_agent_id_missing",
        }

    @pytest.mark.asyncio
    async def test_workspace_not_found_short_circuits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the workspace does not exist we must not attempt to stream."""
        task = _make_task()

        class _Repo:
            def __init__(self, db: object) -> None:
                pass

            async def find_by_id(self, _wid: str) -> None:
                return None

        class _Session:
            async def __aenter__(self) -> object:
                return object()

            async def __aexit__(self, *_: object) -> None:
                return None

        def _fake_session_factory() -> _Session:
            return _Session()

        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence."
            "sql_workspace_repository.SqlWorkspaceRepository",
            _Repo,
        )
        monkeypatch.setattr(
            "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
            _fake_session_factory,
        )

        async def _fake_redis() -> None:
            return None

        monkeypatch.setattr(
            "src.infrastructure.agent.state.agent_worker_state.get_redis_client",
            _fake_redis,
        )
        out = await wl.launch_worker_session(
            workspace_id="w",
            task=task,
            worker_agent_id="agent-X",
            actor_user_id="u1",
        )
        assert out["launched"] is False
        assert out["reason"] == "workspace_not_found"
        assert out["conversation_id"] is None


class TestScheduleWorkerSession:
    @pytest.mark.asyncio
    async def test_schedules_background_task(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: dict[str, object] = {}

        async def _fake_launch(**kwargs: object) -> dict[str, object]:
            called.update(kwargs)
            return {"launched": True, "conversation_id": "cid", "reason": "launched"}

        monkeypatch.setattr(wl, "launch_worker_session", _fake_launch)
        task = _make_task()
        wl.schedule_worker_session(
            workspace_id="w",
            task=task,
            worker_agent_id="agent-X",
            actor_user_id="u1",
            leader_agent_id="leader-1",
            attempt_id="att-1",
        )
        # let the scheduled task run
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert called["worker_agent_id"] == "agent-X"
        assert called["task"] is task
        assert called["leader_agent_id"] == "leader-1"
        assert called["attempt_id"] == "att-1"
