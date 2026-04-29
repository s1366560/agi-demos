"""Unit tests for P0 autonomy helpers in workspace_leader_bootstrap."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

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
