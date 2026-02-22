"""Tests for SubAgentRunRegistry."""

import json
import sqlite3

import pytest

from src.domain.model.agent.subagent_run import SubAgentRunStatus
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry
from src.infrastructure.agent.subagent.run_repository import (
    HybridSubAgentRunRepository,
    RedisRunSnapshotCache,
    SqliteSubAgentRunRepository,
)


@pytest.mark.unit
class TestSubAgentRunRegistry:
    """SubAgentRunRegistry tests."""

    def test_create_and_get_run(self):
        registry = SubAgentRunRegistry()

        created = registry.create_run(
            conversation_id="conv-1",
            subagent_name="researcher",
            task="Find references",
            metadata={"source": "delegate"},
        )
        loaded = registry.get_run("conv-1", created.run_id)

        assert loaded is not None
        assert loaded.run_id == created.run_id
        assert loaded.metadata["source"] == "delegate"

    def test_count_active_includes_pending_and_running(self):
        registry = SubAgentRunRegistry()
        pending = registry.create_run("conv-1", "researcher", "task-1")
        running = registry.create_run("conv-1", "coder", "task-2")
        registry.mark_running("conv-1", running.run_id)
        registry.mark_running("conv-1", pending.run_id)

        assert registry.count_active_runs("conv-1") == 2

        registry.mark_completed("conv-1", pending.run_id, summary="done")
        registry.mark_completed("conv-1", running.run_id, summary="done")
        assert registry.count_active_runs("conv-1") == 0

    def test_mark_methods_merge_metadata(self):
        registry = SubAgentRunRegistry()
        run = registry.create_run("conv-1", "researcher", "task-1", metadata={"a": 1})

        running = registry.mark_running("conv-1", run.run_id, metadata={"b": 2})
        assert running is not None
        assert running.metadata["a"] == 1
        assert running.metadata["b"] == 2
        assert running.metadata.get("lineage_root_run_id") == run.run_id

        completed = registry.mark_completed(
            "conv-1",
            run.run_id,
            summary="done",
            execution_time_ms=10,
            metadata={"c": 3},
        )
        assert completed is not None
        assert completed.metadata["a"] == 1
        assert completed.metadata["b"] == 2
        assert completed.metadata["c"] == 3
        assert completed.metadata.get("lineage_root_run_id") == run.run_id
        assert completed.execution_time_ms == 10

    def test_prunes_oldest_terminal_runs_when_capacity_exceeded(self):
        registry = SubAgentRunRegistry(max_runs_per_conversation=2)

        run1 = registry.create_run("conv-1", "a", "task-a")
        registry.mark_running("conv-1", run1.run_id)
        registry.mark_completed("conv-1", run1.run_id, summary="done")
        run2 = registry.create_run("conv-1", "b", "task-b")
        registry.mark_running("conv-1", run2.run_id)
        registry.mark_completed("conv-1", run2.run_id, summary="done")
        run3 = registry.create_run("conv-1", "c", "task-c")

        runs = registry.list_runs("conv-1")
        run_ids = {run.run_id for run in runs}
        assert len(runs) == 2
        assert run1.run_id not in run_ids
        assert run2.run_id in run_ids
        assert run3.run_id in run_ids

    def test_count_active_runs_for_requester(self):
        registry = SubAgentRunRegistry()
        run_a = registry.create_run(
            "conv-1",
            "researcher",
            "task-a",
            requester_session_key="req-a",
        )
        run_b = registry.create_run(
            "conv-1",
            "researcher",
            "task-b",
            requester_session_key="req-b",
        )
        registry.mark_running("conv-1", run_a.run_id)
        registry.mark_running("conv-1", run_b.run_id)

        assert registry.count_active_runs_for_requester("conv-1", "req-a") == 1
        assert registry.count_active_runs_for_requester("conv-1", "req-b") == 1
        assert registry.count_active_runs_for_requester("conv-1", "unknown") == 0

    def test_list_descendant_runs(self):
        registry = SubAgentRunRegistry()
        root = registry.create_run("conv-1", "root", "task-root")
        registry.mark_running("conv-1", root.run_id)
        child = registry.create_run(
            "conv-1",
            "child",
            "task-child",
            parent_run_id=root.run_id,
            lineage_root_run_id=root.run_id,
        )
        registry.mark_running("conv-1", child.run_id)
        grandchild = registry.create_run(
            "conv-1",
            "grandchild",
            "task-grandchild",
            parent_run_id=child.run_id,
            lineage_root_run_id=root.run_id,
        )
        registry.mark_running("conv-1", grandchild.run_id)

        descendants = registry.list_descendant_runs("conv-1", root.run_id, include_terminal=False)
        descendant_ids = [run.run_id for run in descendants]
        assert child.run_id in descendant_ids
        assert grandchild.run_id in descendant_ids

    def test_persist_and_recover_inflight_runs(self, tmp_path):
        persist_path = tmp_path / "subagent-runs.json"
        registry = SubAgentRunRegistry(persistence_path=str(persist_path))
        run = registry.create_run(
            "conv-1",
            "researcher",
            "task-a",
            requester_session_key="req-a",
        )
        registry.mark_running("conv-1", run.run_id)

        raw = json.loads(persist_path.read_text(encoding="utf-8"))
        assert raw["version"] == 1
        assert "conv-1" in raw["conversations"]

        recovered = SubAgentRunRegistry(persistence_path=str(persist_path))
        loaded = recovered.get_run("conv-1", run.run_id)
        assert loaded is not None
        assert loaded.status == SubAgentRunStatus.TIMED_OUT
        assert loaded.metadata.get("recovered_on_startup") is True

    def test_list_runs_for_requester_visibility_modes(self):
        registry = SubAgentRunRegistry()
        root = registry.create_run(
            "conv-1",
            "researcher",
            "root",
            requester_session_key="req-1",
        )
        registry.mark_running("conv-1", root.run_id)
        child = registry.create_run(
            "conv-1",
            "coder",
            "child",
            requester_session_key="req-2",
            parent_run_id=root.run_id,
            lineage_root_run_id=root.run_id,
        )
        registry.mark_running("conv-1", child.run_id)
        other = registry.create_run(
            "conv-1",
            "writer",
            "other",
            requester_session_key="req-3",
        )
        registry.mark_running("conv-1", other.run_id)

        self_only = registry.list_runs_for_requester("conv-1", "req-1", visibility="self")
        self_ids = {run.run_id for run in self_only}
        assert self_ids == {root.run_id}

        tree_runs = registry.list_runs_for_requester("conv-1", "req-1", visibility="tree")
        tree_ids = {run.run_id for run in tree_runs}
        assert tree_ids == {root.run_id, child.run_id}

        all_runs = registry.list_runs_for_requester("conv-1", "req-1", visibility="all")
        all_ids = {run.run_id for run in all_runs}
        assert all_ids == {root.run_id, child.run_id, other.run_id}

    def test_sync_across_processes_reads_latest_state(self, tmp_path):
        persist_path = tmp_path / "subagent-runs-shared.json"
        writer = SubAgentRunRegistry(
            persistence_path=str(persist_path),
            recover_inflight_on_boot=False,
            sync_across_processes=True,
        )
        reader = SubAgentRunRegistry(
            persistence_path=str(persist_path),
            recover_inflight_on_boot=False,
            sync_across_processes=True,
        )

        run = writer.create_run("conv-1", "researcher", "task-a")
        writer.mark_running("conv-1", run.run_id)
        writer.mark_completed("conv-1", run.run_id, summary="done")

        loaded = reader.get_run("conv-1", run.run_id)
        assert loaded is not None
        assert loaded.status == SubAgentRunStatus.COMPLETED
        assert loaded.summary == "done"

    def test_sync_across_processes_prevents_stale_transition(self, tmp_path):
        persist_path = tmp_path / "subagent-runs-shared.json"
        registry_a = SubAgentRunRegistry(
            persistence_path=str(persist_path),
            recover_inflight_on_boot=False,
            sync_across_processes=True,
        )
        registry_b = SubAgentRunRegistry(
            persistence_path=str(persist_path),
            recover_inflight_on_boot=False,
            sync_across_processes=True,
        )

        run = registry_a.create_run("conv-1", "researcher", "task-a")
        started = registry_b.mark_running(
            "conv-1",
            run.run_id,
            expected_statuses=[SubAgentRunStatus.PENDING],
        )
        assert started is not None

        stale_cancel = registry_a.mark_cancelled(
            "conv-1",
            run.run_id,
            reason="stale action",
            expected_statuses=[SubAgentRunStatus.PENDING],
        )
        assert stale_cancel is None
        current = registry_a.get_run("conv-1", run.run_id)
        assert current is not None
        assert current.status == SubAgentRunStatus.RUNNING

    def test_sqlite_repository_persists_latest_state(self, tmp_path):
        sqlite_path = tmp_path / "subagent-runs.sqlite3"
        writer_repo = SqliteSubAgentRunRepository(str(sqlite_path))
        reader_repo = SqliteSubAgentRunRepository(str(sqlite_path))
        writer = SubAgentRunRegistry(
            repository=writer_repo,
            recover_inflight_on_boot=False,
            sync_across_processes=True,
        )
        reader = SubAgentRunRegistry(
            repository=reader_repo,
            recover_inflight_on_boot=False,
            sync_across_processes=True,
        )

        run = writer.create_run("conv-1", "researcher", "task-a")
        writer.mark_running("conv-1", run.run_id)
        writer.mark_completed("conv-1", run.run_id, summary="done")

        loaded = reader.get_run("conv-1", run.run_id)
        assert loaded is not None
        assert loaded.status == SubAgentRunStatus.COMPLETED
        assert loaded.summary == "done"

    def test_postgres_repository_wiring_uses_shared_state(self, monkeypatch):
        shared_store = {}

        class _FakePostgresRepository:
            def __init__(self, postgres_dsn: str) -> None:
                self._postgres_dsn = postgres_dsn

            def load_runs(self):
                runs = shared_store.get(self._postgres_dsn, {})
                return {
                    conversation_id: dict(bucket)
                    for conversation_id, bucket in runs.items()
                }

            def save_runs(self, runs):
                shared_store[self._postgres_dsn] = {
                    conversation_id: dict(bucket)
                    for conversation_id, bucket in runs.items()
                }

            def close(self) -> None:
                return

        monkeypatch.setattr(
            "src.infrastructure.agent.subagent.run_registry.PostgresSubAgentRunRepository",
            _FakePostgresRepository,
        )

        writer = SubAgentRunRegistry(
            postgres_persistence_dsn="postgresql://memstack:test@localhost/memstack",
            recover_inflight_on_boot=False,
            sync_across_processes=True,
        )
        reader = SubAgentRunRegistry(
            postgres_persistence_dsn="postgresql://memstack:test@localhost/memstack",
            recover_inflight_on_boot=False,
            sync_across_processes=True,
        )

        run = writer.create_run("conv-1", "researcher", "task-a")
        writer.mark_running("conv-1", run.run_id)
        writer.mark_completed("conv-1", run.run_id, summary="done")

        loaded = reader.get_run("conv-1", run.run_id)
        assert loaded is not None
        assert loaded.status == SubAgentRunStatus.COMPLETED
        assert loaded.summary == "done"

    def test_hybrid_repository_uses_redis_cache_for_recovery(self, tmp_path):
        sqlite_path = tmp_path / "subagent-runs.sqlite3"

        class _FakeRedisClient:
            def __init__(self) -> None:
                self._store: dict[str, str] = {}

            def get(self, key: str):
                return self._store.get(key)

            def setex(self, key: str, _ttl: int, value: str) -> None:
                self._store[key] = value

        fake_redis = _FakeRedisClient()
        writer_repo = HybridSubAgentRunRepository(
            db_repository=SqliteSubAgentRunRepository(str(sqlite_path)),
            redis_cache=RedisRunSnapshotCache(client=fake_redis),
        )
        writer = SubAgentRunRegistry(
            repository=writer_repo,
            recover_inflight_on_boot=False,
            sync_across_processes=True,
        )
        run = writer.create_run("conv-1", "researcher", "task-a")
        writer.mark_running("conv-1", run.run_id)
        writer.mark_completed("conv-1", run.run_id, summary="done")

        with sqlite3.connect(sqlite_path) as conn:
            conn.execute("DELETE FROM subagent_run_snapshots")
            conn.commit()

        reader_repo = HybridSubAgentRunRepository(
            db_repository=SqliteSubAgentRunRepository(str(sqlite_path)),
            redis_cache=RedisRunSnapshotCache(client=fake_redis),
        )
        reader = SubAgentRunRegistry(
            repository=reader_repo,
            recover_inflight_on_boot=False,
            sync_across_processes=True,
        )
        loaded = reader.get_run("conv-1", run.run_id)
        assert loaded is not None
        assert loaded.status == SubAgentRunStatus.COMPLETED
