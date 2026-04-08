"""Tests for SubAgentRunRegistry."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.domain.model.agent.announce_config import AnnounceState
from src.domain.model.agent.subagent_run import SubAgentRun, SubAgentRunStatus
from src.infrastructure.agent.subagent.run_registry import (
    SubAgentRunRegistry,
    clear_shared_subagent_run_registry_cache,
    get_shared_subagent_run_registry,
)
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

    def test_create_run_protected_metadata_uses_explicit_identity(self):
        registry = SubAgentRunRegistry()

        run = registry.create_run(
            "conv-1",
            "researcher",
            "task-1",
            metadata={
                "requester_session_key": "spoofed",
                "parent_run_id": "spoofed-parent",
                "lineage_root_run_id": "spoofed-root",
            },
            requester_session_key="req-1",
            parent_run_id="parent-1",
            lineage_root_run_id="root-1",
        )

        assert run.metadata["requester_session_key"] == "req-1"
        assert run.metadata["parent_run_id"] == "parent-1"
        assert run.metadata["lineage_root_run_id"] == "root-1"

    def test_attach_metadata_rejects_protected_identity_keys(self):
        registry = SubAgentRunRegistry()
        run = registry.create_run("conv-1", "researcher", "task-1")

        with pytest.raises(ValueError, match="requester_session_key"):
            registry.attach_metadata("conv-1", run.run_id, {"requester_session_key": "other"})

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

    def test_bulk_helpers_deduplicate_conversation_ids(self):
        registry = SubAgentRunRegistry()
        run = registry.create_run("conv-1", "researcher", "task-a")
        registry.mark_running("conv-1", run.run_id)

        assert registry.count_active_runs_for_conversations(["conv-1", "conv-1"]) == 1
        runs = registry.list_runs_for_conversations(["conv-1", "conv-1"])
        assert [item.run_id for item in runs] == [run.run_id]

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

    def test_list_descendant_runs_limit_keeps_oldest_descendants(self):
        registry = SubAgentRunRegistry()
        registry._runs_by_conversation["conv-1"] = {
            "root": SubAgentRun(
                conversation_id="conv-1",
                subagent_name="root",
                task="root",
                run_id="root",
                status=SubAgentRunStatus.RUNNING,
                created_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
            ),
            "late": SubAgentRun(
                conversation_id="conv-1",
                subagent_name="child",
                task="late",
                run_id="late",
                status=SubAgentRunStatus.RUNNING,
                created_at=datetime(2026, 1, 1, 2, 0, 0, tzinfo=UTC),
                metadata={"parent_run_id": "root"},
            ),
            "early": SubAgentRun(
                conversation_id="conv-1",
                subagent_name="child",
                task="early",
                run_id="early",
                status=SubAgentRunStatus.RUNNING,
                created_at=datetime(2026, 1, 1, 1, 0, 0, tzinfo=UTC),
                metadata={"parent_run_id": "root"},
            ),
        }

        descendants = registry.list_descendant_runs("conv-1", "root", limit=1)

        assert [run.run_id for run in descendants] == ["early"]

    def test_list_descendant_runs_zero_limit_returns_empty(self):
        registry = SubAgentRunRegistry()
        registry._runs_by_conversation["conv-1"] = {
            "root": SubAgentRun(
                conversation_id="conv-1",
                subagent_name="root",
                task="root",
                run_id="root",
                status=SubAgentRunStatus.RUNNING,
                created_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
            ),
            "child": SubAgentRun(
                conversation_id="conv-1",
                subagent_name="child",
                task="child",
                run_id="child",
                status=SubAgentRunStatus.RUNNING,
                created_at=datetime(2026, 1, 1, 1, 0, 0, tzinfo=UTC),
                metadata={"parent_run_id": "root"},
            ),
        }

        descendants = registry.list_descendant_runs("conv-1", "root", limit=0)

        assert descendants == []

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

    def test_boot_recovery_uses_exclusive_lock(self, monkeypatch, tmp_path):
        persist_path = tmp_path / "subagent-runs-shared.json"
        lock_modes: list[bool] = []

        @contextmanager
        def _fake_lock(_self, *, exclusive: bool):
            lock_modes.append(exclusive)
            yield

        monkeypatch.setattr(SubAgentRunRegistry, "_with_registry_lock", _fake_lock)
        monkeypatch.setattr(
            SubAgentRunRegistry,
            "_load_from_disk_unlocked",
            lambda self, *, recover_inflight: None,
        )

        SubAgentRunRegistry(
            persistence_path=str(persist_path),
            recover_inflight_on_boot=True,
            sync_across_processes=True,
        )

        assert lock_modes == [True]

    def test_count_all_active_runs_syncs_new_conversations(self, tmp_path):
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

        run = writer.create_run("conv-2", "researcher", "task-a")
        writer.mark_running("conv-2", run.run_id)

        assert reader.count_all_active_runs() == 1

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

    def test_sqlite_repository_round_trips_trace_context(self, tmp_path):
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
        traced_run = run.with_trace_context(" trace-123 ", " span-456 ")
        writer._runs_by_conversation["conv-1"][run.run_id] = traced_run
        writer._persist_locked()

        loaded = reader.get_run("conv-1", run.run_id)
        assert loaded is not None
        assert loaded.trace_id == "trace-123"
        assert loaded.parent_span_id == "span-456"
        assert [item.run_id for item in reader.list_trace_runs("conv-1", "trace-123")] == [
            run.run_id
        ]

    def test_json_persistence_round_trips_announce_state(self, tmp_path):
        persist_path = tmp_path / "subagent-runs.json"
        writer = SubAgentRunRegistry(
            persistence_path=str(persist_path),
            recover_inflight_on_boot=False,
            sync_across_processes=True,
        )
        run = writer.create_run("conv-1", "researcher", "task-a")
        writer._runs_by_conversation["conv-1"][run.run_id] = SubAgentRun(
            conversation_id="conv-1",
            subagent_name="researcher",
            task="task-a",
            run_id=run.run_id,
            status=SubAgentRunStatus.RUNNING,
            created_at=run.created_at,
            metadata=dict(run.metadata),
            announce_state=AnnounceState.ANNOUNCING,
        )
        writer._persist_locked()

        reader = SubAgentRunRegistry(
            persistence_path=str(persist_path),
            recover_inflight_on_boot=False,
            sync_across_processes=True,
        )

        loaded = reader.get_run("conv-1", run.run_id)
        assert loaded is not None
        assert loaded.announce_state == AnnounceState.ANNOUNCING

    def test_sqlite_repository_sync_configures_lock_path(self, tmp_path):
        sqlite_path = tmp_path / "subagent-runs.sqlite3"
        registry = SubAgentRunRegistry(
            repository=SqliteSubAgentRunRepository(str(sqlite_path)),
            recover_inflight_on_boot=False,
            sync_across_processes=True,
        )

        assert registry._lock_path == sqlite_path.with_suffix(".sqlite3.lock")

    def test_postgres_repository_wiring_uses_shared_state(self, monkeypatch):
        shared_store = {}

        class _FakePostgresRepository:
            def __init__(self, postgres_dsn: str) -> None:
                self._postgres_dsn = postgres_dsn

            def load_runs(self):
                runs = shared_store.get(self._postgres_dsn, {})
                return {conversation_id: dict(bucket) for conversation_id, bucket in runs.items()}

            def save_runs(self, runs):
                shared_store[self._postgres_dsn] = {
                    conversation_id: dict(bucket) for conversation_id, bucket in runs.items()
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

    def test_postgres_repository_sync_configures_lock_path(self, monkeypatch):
        class _FakePostgresRepository:
            def __init__(self, postgres_dsn: str) -> None:
                self._postgres_dsn = postgres_dsn

            def load_runs(self):
                return {}

            def save_runs(self, runs):
                return None

            def close(self) -> None:
                return

        monkeypatch.setattr(
            "src.infrastructure.agent.subagent.run_registry.PostgresSubAgentRunRepository",
            _FakePostgresRepository,
        )

        registry = SubAgentRunRegistry(
            postgres_persistence_dsn="postgresql://memstack:test@localhost/memstack",
            recover_inflight_on_boot=False,
            sync_across_processes=True,
        )

        assert registry._lock_path is not None
        assert (
            registry._lock_path.parent == Path.home() / ".cache" / "memstack" / "subagent-run-locks"
        )
        assert registry._lock_path.name.startswith("postgres-")

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

    def test_redis_cache_rejects_insecure_remote_url(self):
        cache = RedisRunSnapshotCache(redis_url="redis://cache.example.com:6379/0")

        assert cache._client is None

    def test_shared_registry_reuses_same_in_memory_instance(self):
        clear_shared_subagent_run_registry_cache()
        try:
            writer = get_shared_subagent_run_registry()
            reader = get_shared_subagent_run_registry()

            run = writer.create_run("conv-1", "researcher", "task-a")

            assert writer is reader
            assert reader.get_run("conv-1", run.run_id) is not None
        finally:
            clear_shared_subagent_run_registry_cache()

    def test_shared_registry_isolated_by_sqlite_path(self, tmp_path):
        clear_shared_subagent_run_registry_cache()
        try:
            registry_a = get_shared_subagent_run_registry(
                sqlite_persistence_path=str(tmp_path / "runs-a.sqlite")
            )
            registry_b = get_shared_subagent_run_registry(
                sqlite_persistence_path=str(tmp_path / "runs-b.sqlite")
            )

            assert registry_a is not registry_b
        finally:
            clear_shared_subagent_run_registry_cache()
