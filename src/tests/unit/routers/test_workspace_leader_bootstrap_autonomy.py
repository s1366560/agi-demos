"""Unit tests for P0 autonomy helpers in workspace_leader_bootstrap."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from src.domain.model.workspace.workspace_agent import WorkspaceAgent
from src.infrastructure.adapters.primary.web.routers import (
    workspace_leader_bootstrap as bootstrap,
)


@dataclass
class _FakeRootTask:
    id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class _FakeChildTask:
    id: str = "child-1"
    status: str = "in_progress"
    metadata: dict[str, Any] = field(default_factory=dict)


class _FakeTaskRepo:
    def __init__(self, children_map: dict[str, list[Any]]) -> None:
        self._children_map = children_map

    async def find_by_root_goal_task_id(self, workspace_id: str, root_task_id: str) -> list[Any]:
        return self._children_map.get(root_task_id, [])


class _FakeWorkspaceAgentRepo:
    def __init__(self, bindings: list[WorkspaceAgent]) -> None:
        self.bindings = list(bindings)
        self.saved: list[WorkspaceAgent] = []

    async def find_by_workspace_and_agent_id(
        self, workspace_id: str, agent_id: str
    ) -> WorkspaceAgent | None:
        return next(
            (
                binding
                for binding in self.bindings
                if binding.workspace_id == workspace_id and binding.agent_id == agent_id
            ),
            None,
        )

    async def save(self, binding: WorkspaceAgent) -> WorkspaceAgent:
        self.saved.append(binding)
        for index, existing in enumerate(self.bindings):
            if existing.id == binding.id:
                self.bindings[index] = binding
                return binding
        self.bindings.append(binding)
        return binding


class _FakeContainer:
    def __init__(self, workspace_agent_repo: _FakeWorkspaceAgentRepo) -> None:
        self._workspace_agent_repo = workspace_agent_repo

    def workspace_agent_repository(self) -> _FakeWorkspaceAgentRepo:
        return self._workspace_agent_repo


class _FakeNestedTransaction:
    async def __aenter__(self) -> _FakeNestedTransaction:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        return False


class _FakeDb:
    def __init__(self, builtin_exists: bool = True) -> None:
        self.builtin_exists = builtin_exists
        self.added: list[Any] = []
        self.flush_count = 0

    async def get(self, model: Any, key: str) -> object | None:
        return object() if self.builtin_exists else None

    def add(self, row: Any) -> None:
        self.added.append(row)

    def begin_nested(self) -> _FakeNestedTransaction:
        return _FakeNestedTransaction()

    async def flush(self) -> None:
        self.flush_count += 1


@pytest.mark.unit
class TestEnsureWorkspaceLeaderBinding:
    async def test_prefers_existing_builtin_leader_over_worker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        worker = WorkspaceAgent(
            id="worker-binding",
            workspace_id="ws-1",
            agent_id="worker-agent",
            display_name="Worker",
        )
        builtin = WorkspaceAgent(
            id="leader-binding",
            workspace_id="ws-1",
            agent_id=bootstrap.BUILTIN_SISYPHUS_ID,
            display_name=bootstrap.BUILTIN_SISYPHUS_DISPLAY_NAME,
        )
        repo = _FakeWorkspaceAgentRepo([worker, builtin])
        container = _FakeContainer(repo)
        monkeypatch.setattr(bootstrap, "_resolve_container", lambda request, db: container)

        binding, created = await bootstrap.ensure_workspace_leader_binding(
            db=_FakeDb(), workspace_id="ws-1"
        )

        assert binding is builtin
        assert created is False
        assert repo.saved == []

    async def test_creates_builtin_leader_when_only_worker_is_bound(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _FakeWorkspaceAgentRepo(
            [
                WorkspaceAgent(
                    id="worker-binding",
                    workspace_id="ws-1",
                    agent_id="worker-agent",
                    display_name="Worker",
                )
            ]
        )
        container = _FakeContainer(repo)
        monkeypatch.setattr(bootstrap, "_resolve_container", lambda request, db: container)

        binding, created = await bootstrap.ensure_workspace_leader_binding(
            db=_FakeDb(), workspace_id="ws-1"
        )

        assert binding.agent_id == bootstrap.BUILTIN_SISYPHUS_ID
        assert binding.display_name == bootstrap.BUILTIN_SISYPHUS_DISPLAY_NAME
        assert binding.config["workspace_role"] == "leader"
        assert created is True
        assert repo.saved == [binding]

    async def test_reactivates_existing_builtin_leader_binding(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        inactive = WorkspaceAgent(
            id="leader-binding",
            workspace_id="ws-1",
            agent_id=bootstrap.BUILTIN_SISYPHUS_ID,
            display_name=None,
            config={"custom": "kept"},
            is_active=False,
        )
        repo = _FakeWorkspaceAgentRepo([inactive])
        container = _FakeContainer(repo)
        monkeypatch.setattr(bootstrap, "_resolve_container", lambda request, db: container)

        binding, created = await bootstrap.ensure_workspace_leader_binding(
            db=_FakeDb(), workspace_id="ws-1"
        )

        assert binding.id == inactive.id
        assert binding.is_active is True
        assert binding.display_name == bootstrap.BUILTIN_SISYPHUS_DISPLAY_NAME
        assert binding.config["custom"] == "kept"
        assert binding.config["workspace_role"] == "leader"
        assert binding.config["auto_bound_builtin"] is True
        assert created is False
        assert repo.saved == [binding]


@pytest.mark.unit
class TestRootTaskSortKey:
    def test_ready_for_completion_has_highest_priority(self) -> None:
        ready = _FakeRootTask(id="r1", metadata={"remediation_status": "ready_for_completion"})
        replan = _FakeRootTask(id="r2", metadata={"remediation_status": "replan_required"})
        none = _FakeRootTask(id="r3", metadata={"remediation_status": "none"})
        sorted_tasks = sorted([none, replan, ready], key=bootstrap._root_task_sort_key)
        assert [t.id for t in sorted_tasks] == ["r1", "r2", "r3"]

    def test_missing_metadata_defaults_to_lowest_priority(self) -> None:
        a = _FakeRootTask(id="r1", metadata={})
        b = _FakeRootTask(id="r2", metadata={"remediation_status": "replan_required"})
        sorted_tasks = sorted([a, b], key=bootstrap._root_task_sort_key)
        assert [t.id for t in sorted_tasks] == ["r2", "r1"]


@pytest.mark.unit
class TestSelectRootTaskNeedingProgress:
    async def test_prefers_root_without_children(self) -> None:
        with_kids = _FakeRootTask(id="r-kids", metadata={"remediation_status": "none"})
        no_kids = _FakeRootTask(id="r-empty", metadata={"remediation_status": "none"})
        repo = _FakeTaskRepo(
            {
                "r-kids": [_FakeChildTask(status="in_progress")],
                "r-empty": [],
            }
        )

        task, has_children = await bootstrap._select_root_task_needing_progress(
            task_repo=repo,
            workspace_id="ws-1",
            root_tasks=[with_kids, no_kids],
        )
        assert task is not None and task.id == "r-empty"
        assert has_children is False

    async def test_ready_for_completion_beats_empty_root(self) -> None:
        ready = _FakeRootTask(id="r-ready", metadata={"remediation_status": "ready_for_completion"})
        empty = _FakeRootTask(id="r-empty", metadata={"remediation_status": "none"})
        repo = _FakeTaskRepo(
            {
                "r-ready": [_FakeChildTask(status="done")],
                "r-empty": [],
            }
        )

        task, has_children = await bootstrap._select_root_task_needing_progress(
            task_repo=repo, workspace_id="ws-1", root_tasks=[empty, ready]
        )
        assert task is not None and task.id == "r-ready"
        assert has_children is True

    async def test_returns_none_when_all_stable(self) -> None:
        stable_a = _FakeRootTask(id="a", metadata={"remediation_status": "none"})
        stable_b = _FakeRootTask(id="b", metadata={"remediation_status": "none"})
        repo = _FakeTaskRepo(
            {
                "a": [_FakeChildTask(status="in_progress")],
                "b": [_FakeChildTask(status="done")],
            }
        )

        task, has_children = await bootstrap._select_root_task_needing_progress(
            task_repo=repo, workspace_id="ws-1", root_tasks=[stable_a, stable_b]
        )
        assert task is None
        assert has_children is False

    async def test_returns_root_when_children_in_todo(self) -> None:
        """Root with TODO children needs progress (worker sessions must launch)."""
        root = _FakeRootTask(id="r-todo", metadata={"remediation_status": "none"})
        repo = _FakeTaskRepo(
            {
                "r-todo": [
                    _FakeChildTask(id="c1", status="todo"),
                    _FakeChildTask(id="c2", status="in_progress"),
                ],
            }
        )
        task, has_children = await bootstrap._select_root_task_needing_progress(
            task_repo=repo, workspace_id="ws-1", root_tasks=[root]
        )
        assert task is not None and task.id == "r-todo"
        assert has_children is True

    async def test_force_returns_root_even_when_stable(self) -> None:
        """force=True overrides the 'all children active' check."""
        root = _FakeRootTask(id="r-stable", metadata={"remediation_status": "none"})
        repo = _FakeTaskRepo(
            {
                "r-stable": [_FakeChildTask(status="in_progress")],
            }
        )
        task, has_children = await bootstrap._select_root_task_needing_progress(
            task_repo=repo,
            workspace_id="ws-1",
            root_tasks=[root],
            force=True,
        )
        assert task is not None and task.id == "r-stable"
        assert has_children is True

    async def test_returns_root_when_children_pending_adjudication(self) -> None:
        """Children with pending_leader_adjudication=True trigger the tick."""
        root = _FakeRootTask(id="r-adj", metadata={"remediation_status": "none"})
        repo = _FakeTaskRepo(
            {
                "r-adj": [
                    _FakeChildTask(
                        id="c1",
                        status="in_progress",
                        metadata={"pending_leader_adjudication": True},
                    ),
                    _FakeChildTask(
                        id="c2",
                        status="in_progress",
                        metadata={"pending_leader_adjudication": True},
                    ),
                ],
            }
        )
        task, has_children = await bootstrap._select_root_task_needing_progress(
            task_repo=repo, workspace_id="ws-1", root_tasks=[root]
        )
        assert task is not None and task.id == "r-adj"
        assert has_children is True


@pytest.mark.unit
class TestCooldownHelpers:
    async def test_cooldown_read_and_write_roundtrip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store: dict[str, str] = {}
        expirations: dict[str, int | None] = {}

        class _FakeRedis:
            async def exists(self, key: str) -> int:
                return 1 if key in store else 0

            async def set(self, key: str, value: str, ex: int | None = None) -> None:
                store[key] = value
                expirations[key] = ex

        async def _fake_get_redis_client() -> _FakeRedis:
            return _FakeRedis()

        monkeypatch.setattr(bootstrap, "get_redis_client", _fake_get_redis_client)

        assert await bootstrap._is_on_cooldown("ws-1", "root-1") is False
        await bootstrap._mark_cooldown("ws-1", "root-1")
        assert await bootstrap._is_on_cooldown("ws-1", "root-1") is True
        assert await bootstrap._is_on_cooldown("ws-1", "root-2") is False
        key = bootstrap._AUTO_TRIGGER_COOLDOWN_KEY.format(
            workspace_id="ws-1",
            root_task_id="root-1",
        )
        assert expirations[key] == bootstrap.AUTO_TRIGGER_COOLDOWN_SECONDS

    async def test_replan_trigger_uses_longer_cooldown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        expirations: dict[str, int | None] = {}

        class _FakeRedis:
            async def set(self, key: str, value: str, ex: int | None = None) -> None:
                expirations[key] = ex

        async def _fake_get_redis_client() -> _FakeRedis:
            return _FakeRedis()

        monkeypatch.setattr(bootstrap, "get_redis_client", _fake_get_redis_client)

        await bootstrap._mark_autonomy_trigger_cooldown(
            "ws-1",
            "root-1",
            remediation_status="replan_required",
        )

        key = bootstrap._AUTO_TRIGGER_COOLDOWN_KEY.format(
            workspace_id="ws-1",
            root_task_id="root-1",
        )
        assert expirations[key] == bootstrap.REPLAN_TRIGGER_COOLDOWN_SECONDS

    async def test_cooldown_fails_open_when_redis_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _boom() -> Any:
            raise RuntimeError("redis unavailable")

        monkeypatch.setattr(bootstrap, "get_redis_client", _boom)

        # Should not raise, and must report not-on-cooldown so autonomy can proceed
        assert await bootstrap._is_on_cooldown("ws-1", "root-1") is False
        await bootstrap._mark_cooldown("ws-1", "root-1")  # must not raise


@pytest.mark.unit
class TestSweepOrphanExecutionTasks:
    """P5b safety net — orphan execution tasks get self-healed by autonomy tick."""

    async def _run(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        children: list[Any],
        leader_agent_id: str | None = "leader-1",
    ) -> tuple[int, list[dict[str, Any]]]:
        class _Repo:
            async def find_by_root_goal_task_id(
                self, workspace_id: str, root_task_id: str
            ) -> list[Any]:
                return list(children)

        captured: list[dict[str, Any]] = []

        async def _fake_assign(**kwargs: Any) -> None:
            captured.append(kwargs)

        import src.infrastructure.agent.workspace.workspace_goal_runtime as wgr

        monkeypatch.setattr(wgr, "_assign_execution_tasks_to_workers", _fake_assign)

        dispatched = await bootstrap._sweep_orphan_execution_tasks(
            task_repo=_Repo(),
            workspace_agent_repo=object(),
            command_service=object(),
            workspace_id="ws-1",
            root_task_id="root-1",
            leader_agent_id=leader_agent_id,
            actor_user_id="user-1",
        )
        return dispatched, captured

    async def test_dispatches_only_unassigned_todo_execution_tasks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.domain.model.workspace.workspace_task import (
            WorkspaceTask,
            WorkspaceTaskPriority,
            WorkspaceTaskStatus,
        )

        def _task(
            *,
            tid: str,
            role: str | None,
            assignee: str | None,
            status: WorkspaceTaskStatus,
            archived: bool = False,
        ) -> WorkspaceTask:
            from datetime import UTC, datetime

            return WorkspaceTask(
                id=tid,
                workspace_id="ws-1",
                title=f"t-{tid}",
                created_by="user-1",
                assignee_agent_id=assignee,
                status=status,
                priority=WorkspaceTaskPriority.NONE,
                metadata={"task_role": role} if role else {},
                archived_at=(datetime.now(UTC) if archived else None),
            )

        orphan1 = _task(
            tid="orph-1",
            role="execution_task",
            assignee=None,
            status=WorkspaceTaskStatus.TODO,
        )
        orphan2 = _task(
            tid="orph-2",
            role="execution",
            assignee=None,
            status=WorkspaceTaskStatus.TODO,
        )
        already_assigned = _task(
            tid="assigned",
            role="execution_task",
            assignee="agent-a",
            status=WorkspaceTaskStatus.TODO,
        )
        done = _task(
            tid="done-1",
            role="execution_task",
            assignee=None,
            status=WorkspaceTaskStatus.DONE,
        )
        archived = _task(
            tid="arch",
            role="execution_task",
            assignee=None,
            status=WorkspaceTaskStatus.TODO,
            archived=True,
        )
        goal_root = _task(
            tid="root-child",
            role="goal_root",
            assignee=None,
            status=WorkspaceTaskStatus.TODO,
        )
        no_role = _task(
            tid="no-role",
            role=None,
            assignee=None,
            status=WorkspaceTaskStatus.TODO,
        )

        dispatched, captured = await self._run(
            monkeypatch,
            children=[orphan1, orphan2, already_assigned, done, archived, goal_root, no_role],
        )

        assert dispatched == 1
        assert len(captured) == 1
        call = captured[0]
        assert call["leader_agent_id"] == "leader-1"
        assert call["workspace_id"] == "ws-1"
        assert call["reason"] == "autonomy_tick.orphan_sweep"
        assert [t.id for t in call["created_tasks"]] == ["orph-1"]

    async def test_noop_when_no_orphans(self, monkeypatch: pytest.MonkeyPatch) -> None:
        dispatched, captured = await self._run(monkeypatch, children=[])
        assert dispatched == 0
        assert captured == []

    async def test_skips_when_leader_agent_id_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from datetime import UTC, datetime  # noqa: F401

        from src.domain.model.workspace.workspace_task import (
            WorkspaceTask,
            WorkspaceTaskPriority,
            WorkspaceTaskStatus,
        )

        orphan = WorkspaceTask(
            id="orph",
            workspace_id="ws-1",
            title="t",
            created_by="user-1",
            assignee_agent_id=None,
            status=WorkspaceTaskStatus.TODO,
            priority=WorkspaceTaskPriority.NONE,
            metadata={"task_role": "execution_task"},
        )

        dispatched, captured = await self._run(monkeypatch, children=[orphan], leader_agent_id=None)
        assert dispatched == 0
        assert captured == []

    async def test_dispatch_failure_does_not_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.domain.model.workspace.workspace_task import (
            WorkspaceTask,
            WorkspaceTaskPriority,
            WorkspaceTaskStatus,
        )

        orphan = WorkspaceTask(
            id="orph",
            workspace_id="ws-1",
            title="t",
            created_by="user-1",
            assignee_agent_id=None,
            status=WorkspaceTaskStatus.TODO,
            priority=WorkspaceTaskPriority.NONE,
            metadata={"task_role": "execution_task"},
        )

        class _Repo:
            async def find_by_root_goal_task_id(
                self, workspace_id: str, root_task_id: str
            ) -> list[Any]:
                return [orphan]

        async def _boom(**kwargs: Any) -> None:
            raise RuntimeError("dispatch broken")

        import src.infrastructure.agent.workspace.workspace_goal_runtime as wgr

        monkeypatch.setattr(wgr, "_assign_execution_tasks_to_workers", _boom)

        dispatched = await bootstrap._sweep_orphan_execution_tasks(
            task_repo=_Repo(),
            workspace_agent_repo=object(),
            command_service=object(),
            workspace_id="ws-1",
            root_task_id="root-1",
            leader_agent_id="leader-1",
            actor_user_id="user-1",
        )
        assert dispatched == 0


@pytest.mark.unit
class TestAutoAdjudicatePendingReports:
    """Tests for _auto_adjudicate_pending_reports tick-based auto-accept."""

    async def test_adjudicates_completed_report_as_done(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        adjudicated_calls: list[dict[str, Any]] = []

        async def _fake_adjudicate(**kwargs: Any) -> str:
            adjudicated_calls.append(kwargs)
            return "adjudicated"

        import src.infrastructure.agent.workspace.workspace_goal_runtime as wgr

        monkeypatch.setattr(wgr, "adjudicate_workspace_worker_report", _fake_adjudicate)

        repo = _FakeTaskRepo(
            {
                "root-1": [
                    _FakeChildTask(
                        id="c1",
                        status="in_progress",
                        metadata={
                            "pending_leader_adjudication": True,
                            "last_worker_report_type": "completed",
                            "current_attempt_id": "att-1",
                        },
                    ),
                ],
            }
        )

        count = await bootstrap._auto_adjudicate_pending_reports(
            task_repo=repo,
            workspace_id="ws-1",
            root_task_id="root-1",
            leader_agent_id="leader-1",
            actor_user_id="user-1",
        )
        assert count == 1
        assert adjudicated_calls[0]["task_id"] == "c1"
        assert adjudicated_calls[0]["attempt_id"] == "att-1"
        assert adjudicated_calls[0]["status"].value == "done"

    async def test_adjudicates_blocked_report_as_blocked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        adjudicated_calls: list[dict[str, Any]] = []

        async def _fake_adjudicate(**kwargs: Any) -> str:
            adjudicated_calls.append(kwargs)
            return "adjudicated"

        import src.infrastructure.agent.workspace.workspace_goal_runtime as wgr

        monkeypatch.setattr(wgr, "adjudicate_workspace_worker_report", _fake_adjudicate)

        repo = _FakeTaskRepo(
            {
                "root-1": [
                    _FakeChildTask(
                        id="c1",
                        status="in_progress",
                        metadata={
                            "pending_leader_adjudication": True,
                            "last_worker_report_type": "blocked",
                            "current_attempt_id": "att-2",
                        },
                    ),
                    _FakeChildTask(
                        id="c2",
                        status="in_progress",
                        metadata={
                            "pending_leader_adjudication": True,
                            "last_worker_report_type": "failed",
                        },
                    ),
                ],
            }
        )

        count = await bootstrap._auto_adjudicate_pending_reports(
            task_repo=repo,
            workspace_id="ws-1",
            root_task_id="root-1",
            leader_agent_id="leader-1",
            actor_user_id="user-1",
        )
        assert count == 2
        assert adjudicated_calls[0]["status"].value == "blocked"
        assert adjudicated_calls[1]["status"].value == "blocked"
        assert adjudicated_calls[1]["attempt_id"] is None  # no attempt_id

    async def test_skips_children_without_pending_adjudication(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        adjudicated_calls: list[dict[str, Any]] = []

        async def _fake_adjudicate(**kwargs: Any) -> str:
            adjudicated_calls.append(kwargs)
            return "adjudicated"

        import src.infrastructure.agent.workspace.workspace_goal_runtime as wgr

        monkeypatch.setattr(wgr, "adjudicate_workspace_worker_report", _fake_adjudicate)

        repo = _FakeTaskRepo(
            {
                "root-1": [
                    _FakeChildTask(id="c1", status="done", metadata={}),
                    _FakeChildTask(
                        id="c2",
                        status="in_progress",
                        metadata={"pending_leader_adjudication": False},
                    ),
                ],
            }
        )

        count = await bootstrap._auto_adjudicate_pending_reports(
            task_repo=repo,
            workspace_id="ws-1",
            root_task_id="root-1",
            leader_agent_id="leader-1",
            actor_user_id="user-1",
        )
        assert count == 0
        assert adjudicated_calls == []

    async def test_skips_unknown_report_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        adjudicated_calls: list[dict[str, Any]] = []

        async def _fake_adjudicate(**kwargs: Any) -> str:
            adjudicated_calls.append(kwargs)
            return "adjudicated"

        import src.infrastructure.agent.workspace.workspace_goal_runtime as wgr

        monkeypatch.setattr(wgr, "adjudicate_workspace_worker_report", _fake_adjudicate)

        repo = _FakeTaskRepo(
            {
                "root-1": [
                    _FakeChildTask(
                        id="c1",
                        status="in_progress",
                        metadata={
                            "pending_leader_adjudication": True,
                            "last_worker_report_type": "progress_update",
                        },
                    ),
                ],
            }
        )

        count = await bootstrap._auto_adjudicate_pending_reports(
            task_repo=repo,
            workspace_id="ws-1",
            root_task_id="root-1",
            leader_agent_id="leader-1",
            actor_user_id="user-1",
        )
        assert count == 0

    async def test_continues_on_individual_adjudication_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        call_count = 0

        async def _flaky_adjudicate(**kwargs: Any) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("DB connection lost")
            return "adjudicated"

        import src.infrastructure.agent.workspace.workspace_goal_runtime as wgr

        monkeypatch.setattr(wgr, "adjudicate_workspace_worker_report", _flaky_adjudicate)

        repo = _FakeTaskRepo(
            {
                "root-1": [
                    _FakeChildTask(
                        id="c1",
                        status="in_progress",
                        metadata={
                            "pending_leader_adjudication": True,
                            "last_worker_report_type": "completed",
                        },
                    ),
                    _FakeChildTask(
                        id="c2",
                        status="in_progress",
                        metadata={
                            "pending_leader_adjudication": True,
                            "last_worker_report_type": "completed",
                        },
                    ),
                ],
            }
        )

        count = await bootstrap._auto_adjudicate_pending_reports(
            task_repo=repo,
            workspace_id="ws-1",
            root_task_id="root-1",
            leader_agent_id="leader-1",
            actor_user_id="user-1",
        )
        # First call fails, second succeeds
        assert count == 1
