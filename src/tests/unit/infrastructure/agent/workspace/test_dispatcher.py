"""Unit tests for the dispatcher module (P2d M2)."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.model.workspace.workspace_agent import WorkspaceAgent
from src.domain.model.workspace.workspace_task import (
    WorkspaceTask,
    WorkspaceTaskStatus,
)
from src.infrastructure.agent.workspace.dispatcher import (
    DEFAULT_RETRY_POLICY,
    DispatchRetryPolicy,
    assign_execution_tasks_round_robin,
    filter_worker_bindings,
    pair_tasks_with_workers,
    sort_bindings,
)


def _agent(
    agent_id: str,
    *,
    binding_id: str | None = None,
    display: str | None = None,
    label: str | None = None,
) -> WorkspaceAgent:
    return WorkspaceAgent(
        id=binding_id or f"bind-{agent_id}",
        workspace_id="ws-1",
        agent_id=agent_id,
        display_name=display,
        label=label,
    )


def _task(task_id: str, *, status: WorkspaceTaskStatus = WorkspaceTaskStatus.TODO) -> WorkspaceTask:
    return WorkspaceTask(
        id=task_id,
        workspace_id="ws-1",
        created_by="user-1",
        title=f"task {task_id}",
        status=status,
    )


# ---------------------------------------------------------------------------
# filter_worker_bindings
# ---------------------------------------------------------------------------


class TestFilterWorkerBindings:
    def test_empty_input(self) -> None:
        assert filter_worker_bindings([], leader_agent_id="leader") == []

    def test_excludes_leader(self) -> None:
        bindings = [_agent("leader"), _agent("w1"), _agent("w2")]
        result = filter_worker_bindings(bindings, leader_agent_id="leader")
        assert [b.agent_id for b in result] == ["w1", "w2"]

    def test_falls_back_when_only_leader(self) -> None:
        # If the only active binding is the leader, dispatch to the leader itself.
        bindings = [_agent("leader")]
        result = filter_worker_bindings(bindings, leader_agent_id="leader")
        assert [b.agent_id for b in result] == ["leader"]

    def test_none_leader_keeps_all(self) -> None:
        bindings = [_agent("w1"), _agent("w2")]
        result = filter_worker_bindings(bindings, leader_agent_id=None)
        assert [b.agent_id for b in result] == ["w1", "w2"]


# ---------------------------------------------------------------------------
# sort_bindings
# ---------------------------------------------------------------------------


class TestSortBindings:
    def test_sort_stable_by_display_label_agent_id_id(self) -> None:
        bindings = [
            _agent("c", binding_id="bind-c", display="Zed"),
            _agent("a", binding_id="bind-a", display="Alice"),
            _agent("b", binding_id="bind-b", display=None, label="Bob"),
        ]
        result = sort_bindings(bindings)
        # "" (no display, label "Bob") sorts before "Alice" before "Zed"
        assert [b.agent_id for b in result] == ["b", "a", "c"]

    def test_deterministic_ties(self) -> None:
        bindings = [
            _agent("x", binding_id="bind-2"),
            _agent("x", binding_id="bind-1"),
        ]
        result = sort_bindings(bindings)
        # All other keys equal → fall back to id.
        assert [b.id for b in result] == ["bind-1", "bind-2"]


# ---------------------------------------------------------------------------
# pair_tasks_with_workers
# ---------------------------------------------------------------------------


class TestPairTasksWithWorkers:
    def test_empty_tasks(self) -> None:
        workers = [_agent("w1")]
        assert pair_tasks_with_workers([], workers) == []

    def test_empty_workers(self) -> None:
        tasks = [_task("t1")]
        assert pair_tasks_with_workers(tasks, []) == []

    def test_round_robin(self) -> None:
        tasks = [_task("t1"), _task("t2"), _task("t3"), _task("t4"), _task("t5")]
        workers = [_agent("w1"), _agent("w2")]
        pairs = pair_tasks_with_workers(tasks, workers)
        assert [(t.id, w.agent_id) for t, w in pairs] == [
            ("t1", "w1"),
            ("t2", "w2"),
            ("t3", "w1"),
            ("t4", "w2"),
            ("t5", "w1"),
        ]

    def test_more_workers_than_tasks(self) -> None:
        tasks = [_task("t1")]
        workers = [_agent("w1"), _agent("w2"), _agent("w3")]
        pairs = pair_tasks_with_workers(tasks, workers)
        assert [(t.id, w.agent_id) for t, w in pairs] == [("t1", "w1")]


# ---------------------------------------------------------------------------
# assign_execution_tasks_round_robin — orchestration + state-machine guard
# ---------------------------------------------------------------------------


def _fake_command_service() -> MagicMock:
    svc = MagicMock()
    svc.assign_task_to_agent = AsyncMock(return_value=None)
    return svc


class TestAssign:
    @pytest.mark.asyncio
    async def test_no_tasks_no_assignments(self) -> None:
        svc = _fake_command_service()
        result = await assign_execution_tasks_round_robin(
            workspace_id="ws-1",
            actor_user_id="u1",
            created_tasks=[],
            active_bindings=[_agent("w1")],
            command_service=svc,
            leader_agent_id="leader",
            reason="r",
        )
        assert result == 0
        svc.assign_task_to_agent.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_leader_no_assignments(self) -> None:
        svc = _fake_command_service()
        result = await assign_execution_tasks_round_robin(
            workspace_id="ws-1",
            actor_user_id="u1",
            created_tasks=[_task("t1")],
            active_bindings=[_agent("w1")],
            command_service=svc,
            leader_agent_id=None,
            reason="r",
        )
        assert result == 0
        svc.assign_task_to_agent.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_bindings_no_assignments(self) -> None:
        svc = _fake_command_service()
        result = await assign_execution_tasks_round_robin(
            workspace_id="ws-1",
            actor_user_id="u1",
            created_tasks=[_task("t1")],
            active_bindings=[],
            command_service=svc,
            leader_agent_id="leader",
            reason="r",
        )
        assert result == 0
        svc.assign_task_to_agent.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_assigns_each_task(self) -> None:
        svc = _fake_command_service()
        tasks = [_task("t1"), _task("t2"), _task("t3")]
        result = await assign_execution_tasks_round_robin(
            workspace_id="ws-1",
            actor_user_id="u1",
            created_tasks=tasks,
            active_bindings=[_agent("leader"), _agent("w1"), _agent("w2")],
            command_service=svc,
            leader_agent_id="leader",
            reason="r",
        )
        assert result == 3
        assert svc.assign_task_to_agent.await_count == 3
        # Verify round-robin: t1→w1, t2→w2, t3→w1 (sorted: bind-w1, bind-w2)
        calls = svc.assign_task_to_agent.await_args_list
        task_ids = [c.kwargs["task_id"] for c in calls]
        binding_ids = [c.kwargs["workspace_agent_id"] for c in calls]
        assert task_ids == ["t1", "t2", "t3"]
        assert binding_ids == ["bind-w1", "bind-w2", "bind-w1"]

    @pytest.mark.asyncio
    async def test_skips_non_todo_tasks(self) -> None:
        svc = _fake_command_service()
        tasks = [
            _task("t-todo", status=WorkspaceTaskStatus.TODO),
            _task("t-done", status=WorkspaceTaskStatus.DONE),
            _task("t-dispatched", status=WorkspaceTaskStatus.DISPATCHED),
            _task("t-also-todo", status=WorkspaceTaskStatus.TODO),
        ]
        result = await assign_execution_tasks_round_robin(
            workspace_id="ws-1",
            actor_user_id="u1",
            created_tasks=tasks,
            active_bindings=[_agent("w1")],
            command_service=svc,
            leader_agent_id="leader",
            reason="r",
        )
        # Only the 2 TODO tasks get dispatched.
        assert result == 2
        assigned_ids = [c.kwargs["task_id"] for c in svc.assign_task_to_agent.await_args_list]
        assert assigned_ids == ["t-todo", "t-also-todo"]

    @pytest.mark.asyncio
    async def test_assignment_failure_does_not_abort_batch(self) -> None:
        svc = MagicMock()
        err = RuntimeError("boom")
        svc.assign_task_to_agent = AsyncMock(side_effect=[err, None, None])
        tasks = [_task("t1"), _task("t2"), _task("t3")]
        result = await assign_execution_tasks_round_robin(
            workspace_id="ws-1",
            actor_user_id="u1",
            created_tasks=tasks,
            active_bindings=[_agent("w1")],
            command_service=svc,
            leader_agent_id="leader",
            reason="r",
        )
        # t1 failed; t2 and t3 succeeded.
        assert result == 2
        assert svc.assign_task_to_agent.await_count == 3

    @pytest.mark.asyncio
    async def test_leader_only_fallback_assigns_to_leader(self) -> None:
        svc = _fake_command_service()
        tasks = [_task("t1")]
        leader_binding = _agent("leader", binding_id="bind-leader")
        result = await assign_execution_tasks_round_robin(
            workspace_id="ws-1",
            actor_user_id="u1",
            created_tasks=tasks,
            active_bindings=[leader_binding],
            command_service=svc,
            leader_agent_id="leader",
            reason="r",
        )
        assert result == 1
        call = svc.assign_task_to_agent.await_args
        assert call.kwargs["workspace_agent_id"] == "bind-leader"

    @pytest.mark.asyncio
    async def test_uses_leader_as_actor_agent(self) -> None:
        svc = _fake_command_service()
        tasks = [_task("t1")]
        result = await assign_execution_tasks_round_robin(
            workspace_id="ws-1",
            actor_user_id="u1",
            created_tasks=tasks,
            active_bindings=[_agent("leader"), _agent("w1")],
            command_service=svc,
            leader_agent_id="leader",
            reason="my-reason",
        )
        assert result == 1
        call = svc.assign_task_to_agent.await_args
        assert call.kwargs["actor_type"] == "agent"
        assert call.kwargs["actor_agent_id"] == "leader"
        assert call.kwargs["reason"] == "my-reason"


# ---------------------------------------------------------------------------
# DispatchRetryPolicy
# ---------------------------------------------------------------------------


class TestDispatchRetryPolicy:
    def test_default_is_reasonable(self) -> None:
        p = DEFAULT_RETRY_POLICY
        assert p.max_attempts == 3
        assert p.initial_backoff_seconds == 5.0
        assert p.max_backoff_seconds == 120.0

    def test_backoff_curve(self) -> None:
        p = DispatchRetryPolicy(
            max_attempts=5, initial_backoff_seconds=2.0, max_backoff_seconds=16.0
        )
        assert p.backoff_for(1) == 0.0
        assert p.backoff_for(2) == 2.0
        assert p.backoff_for(3) == 4.0
        assert p.backoff_for(4) == 8.0
        # capped
        assert p.backoff_for(5) == 16.0
        assert p.backoff_for(6) == 16.0

    def test_invalid_max_attempts(self) -> None:
        with pytest.raises(ValueError, match="max_attempts"):
            DispatchRetryPolicy(max_attempts=0)

    def test_invalid_initial_backoff(self) -> None:
        with pytest.raises(ValueError, match="initial_backoff_seconds"):
            DispatchRetryPolicy(initial_backoff_seconds=-1)

    def test_invalid_max_backoff(self) -> None:
        with pytest.raises(ValueError, match="max_backoff_seconds"):
            DispatchRetryPolicy(initial_backoff_seconds=10.0, max_backoff_seconds=5.0)


# Silence unused import
_ = replace
