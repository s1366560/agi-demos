"""Tests for SpawnManager orchestration."""

import pytest

from src.domain.model.agent.spawn_mode import SpawnMode
from src.infrastructure.agent.orchestration.session_registry import (
    AgentSessionRegistry,
)
from src.infrastructure.agent.orchestration.spawn_manager import (
    SpawnDepthExceededError,
    SpawnManager,
)
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry


@pytest.fixture
def manager() -> SpawnManager:
    return SpawnManager(
        session_registry=AgentSessionRegistry(),
        run_registry=None,
        max_spawn_depth=3,
    )


@pytest.mark.unit
class TestSpawnDepthExceededError:
    def test_error_message(self) -> None:
        err = SpawnDepthExceededError(current_depth=4, max_depth=3)
        assert str(err) == "Spawn depth 4 would exceed max 3"

    def test_error_attributes(self) -> None:
        err = SpawnDepthExceededError(current_depth=5, max_depth=3)
        assert err.current_depth == 5
        assert err.max_depth == 3


@pytest.mark.unit
class TestSpawnManager:
    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    async def test_register_spawn_creates_record(self, manager: SpawnManager) -> None:
        record = await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
            parent_session_id="session-a",
            task_summary="do stuff",
        )
        assert record.parent_agent_id == "agent-a"
        assert record.child_agent_id == "agent-b"
        assert record.child_session_id == "session-b"
        assert record.project_id == "proj-1"
        assert record.task_summary == "do stuff"
        assert record.status == "running"

    async def test_register_spawn_stores_in_index(self, manager: SpawnManager) -> None:
        record = await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
            parent_session_id="session-a",
        )
        fetched = await manager.get_record("session-b")
        assert fetched is not None
        assert fetched.id == record.id

    async def test_register_spawn_default_mode_is_run(self, manager: SpawnManager) -> None:
        record = await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
        )
        assert record.mode is SpawnMode.RUN

    async def test_register_spawn_custom_mode(self, manager: SpawnManager) -> None:
        record = await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
            mode=SpawnMode.SESSION,
        )
        assert record.mode is SpawnMode.SESSION

    async def test_register_spawn_syncs_trace_context_and_requester_identity(self) -> None:
        run_registry = SubAgentRunRegistry(sync_across_processes=False)
        manager = SpawnManager(
            session_registry=AgentSessionRegistry(),
            run_registry=run_registry,
            max_spawn_depth=3,
        )

        record = await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
            parent_session_id="session-a",
            conversation_id="conv-1",
            task_summary="Investigate issue",
            trace_id="trace-1",
            span_id="span-1",
        )

        run = run_registry.get_run("conv-1", record.id)
        assert run is not None
        assert run.trace_id == "trace-1"
        assert run.parent_span_id == "span-1"
        assert run.metadata["requester_session_key"] == "session-a"
        assert "parent_run_id" not in run.metadata

    async def test_register_spawn_depth_exceeded_raises(self, manager: SpawnManager) -> None:
        await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
            parent_session_id="session-a",
        )
        await manager.register_spawn(
            parent_agent_id="agent-b",
            child_agent_id="agent-c",
            child_session_id="session-c",
            project_id="proj-1",
            parent_session_id="session-b",
        )
        await manager.register_spawn(
            parent_agent_id="agent-c",
            child_agent_id="agent-d",
            child_session_id="session-d",
            project_id="proj-1",
            parent_session_id="session-c",
        )
        with pytest.raises(SpawnDepthExceededError) as exc_info:
            await manager.register_spawn(
                parent_agent_id="agent-d",
                child_agent_id="agent-e",
                child_session_id="session-e",
                project_id="proj-1",
                parent_session_id="session-d",
            )
        assert exc_info.value.current_depth == 3
        assert exc_info.value.max_depth == 3

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def test_find_children_returns_direct_children(self, manager: SpawnManager) -> None:
        await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
            parent_session_id="session-a",
        )
        await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-c",
            child_session_id="session-c",
            project_id="proj-1",
            parent_session_id="session-a",
        )
        children = await manager.find_children("session-a")
        assert len(children) == 2

    async def test_find_children_empty_for_unknown_parent(self, manager: SpawnManager) -> None:
        children = await manager.find_children("nonexistent")
        assert children == []

    async def test_find_children_filters_by_status(self, manager: SpawnManager) -> None:
        await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
            parent_session_id="session-a",
        )
        await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-c",
            child_session_id="session-c",
            project_id="proj-1",
            parent_session_id="session-a",
        )
        await manager.update_status("session-b", "completed")
        running = await manager.find_children("session-a", status="running")
        assert len(running) == 1
        assert running[0].child_session_id == "session-c"

    async def test_find_descendants_returns_all_nested(self, manager: SpawnManager) -> None:
        await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
            parent_session_id="session-a",
        )
        await manager.register_spawn(
            parent_agent_id="agent-b",
            child_agent_id="agent-c",
            child_session_id="session-c",
            project_id="proj-1",
            parent_session_id="session-b",
        )
        descendants = await manager.find_descendants("session-a")
        session_ids = [r.child_session_id for r in descendants]
        assert "session-b" in session_ids
        assert "session-c" in session_ids
        assert len(descendants) == 2

    async def test_find_descendants_include_self(self, manager: SpawnManager) -> None:
        await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
            parent_session_id="session-a",
        )
        descendants = await manager.find_descendants("session-b", include_self=True)
        session_ids = [r.child_session_id for r in descendants]
        assert "session-b" in session_ids

    async def test_get_spawn_depth_root_is_zero(self, manager: SpawnManager) -> None:
        depth = await manager.get_spawn_depth("unknown-session")
        assert depth == 0

    async def test_get_spawn_depth_none_is_zero(self, manager: SpawnManager) -> None:
        depth = await manager.get_spawn_depth(None)
        assert depth == 0

    async def test_get_spawn_depth_child_is_one(self, manager: SpawnManager) -> None:
        await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
            parent_session_id="session-a",
        )
        depth = await manager.get_spawn_depth("session-b")
        assert depth == 1

    async def test_get_spawn_depth_grandchild_is_two(self, manager: SpawnManager) -> None:
        await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
            parent_session_id="session-a",
        )
        await manager.register_spawn(
            parent_agent_id="agent-b",
            child_agent_id="agent-c",
            child_session_id="session-c",
            project_id="proj-1",
            parent_session_id="session-b",
        )
        depth = await manager.get_spawn_depth("session-c")
        assert depth == 2

    async def test_has_active_children_true(self, manager: SpawnManager) -> None:
        await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
            parent_session_id="session-a",
        )
        assert await manager.has_active_children("session-a") is True

    async def test_has_active_children_false_when_completed(self, manager: SpawnManager) -> None:
        await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
            parent_session_id="session-a",
        )
        await manager.update_status("session-b", "completed")
        assert await manager.has_active_children("session-a") is False

    async def test_count_children_total(self, manager: SpawnManager) -> None:
        for i in range(3):
            await manager.register_spawn(
                parent_agent_id="agent-a",
                child_agent_id=f"agent-child-{i}",
                child_session_id=f"session-child-{i}",
                project_id="proj-1",
                parent_session_id="session-a",
            )
        count = await manager.count_children("session-a")
        assert count == 3

    async def test_count_children_by_status(self, manager: SpawnManager) -> None:
        for i in range(3):
            await manager.register_spawn(
                parent_agent_id="agent-a",
                child_agent_id=f"agent-child-{i}",
                child_session_id=f"session-child-{i}",
                project_id="proj-1",
                parent_session_id="session-a",
            )
        await manager.update_status("session-child-0", "completed")
        running = await manager.count_children("session-a", status="running")
        assert running == 2

    # ------------------------------------------------------------------
    # Status Updates
    # ------------------------------------------------------------------

    async def test_update_status_returns_new_record(self, manager: SpawnManager) -> None:
        original = await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
        )
        updated = await manager.update_status("session-b", "completed")
        assert updated is not None
        assert updated.status == "completed"
        assert updated is not original

    async def test_update_status_unknown_session_returns_none(self, manager: SpawnManager) -> None:
        result = await manager.update_status("nonexistent", "completed")
        assert result is None

    async def test_update_status_persisted(self, manager: SpawnManager) -> None:
        await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
        )
        await manager.update_status("session-b", "failed")
        fetched = await manager.get_record("session-b")
        assert fetched is not None
        assert fetched.status == "failed"

    # ------------------------------------------------------------------
    # Cascade Stop
    # ------------------------------------------------------------------

    async def test_cascade_stop_stops_descendants(self, manager: SpawnManager) -> None:
        await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
            parent_session_id="session-a",
        )
        await manager.register_spawn(
            parent_agent_id="agent-b",
            child_agent_id="agent-c",
            child_session_id="session-c",
            project_id="proj-1",
            parent_session_id="session-b",
        )
        await manager.cascade_stop("session-a", "proj-1")
        rec_b = await manager.get_record("session-b")
        rec_c = await manager.get_record("session-c")
        assert rec_b is not None and rec_b.status == "stopped"
        assert rec_c is not None and rec_c.status == "stopped"

    async def test_cascade_stop_returns_stopped_session_ids(self, manager: SpawnManager) -> None:
        await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
            parent_session_id="session-a",
        )
        await manager.register_spawn(
            parent_agent_id="agent-b",
            child_agent_id="agent-c",
            child_session_id="session-c",
            project_id="proj-1",
            parent_session_id="session-b",
        )
        stopped = await manager.cascade_stop("session-a", "proj-1")
        assert "session-b" in stopped
        assert "session-c" in stopped

    async def test_cascade_stop_skips_already_completed(self, manager: SpawnManager) -> None:
        await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
            parent_session_id="session-a",
        )
        await manager.update_status("session-b", "completed")
        stopped = await manager.cascade_stop("session-a", "proj-1")
        assert stopped == []

    async def test_cascade_stop_calls_on_stop_callback(self, manager: SpawnManager) -> None:
        await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
            parent_session_id="session-a",
        )
        await manager.register_spawn(
            parent_agent_id="agent-b",
            child_agent_id="agent-c",
            child_session_id="session-c",
            project_id="proj-1",
            parent_session_id="session-b",
        )
        callback_calls: list[tuple[str, str]] = []

        async def on_stop(session_id: str, agent_id: str) -> None:
            callback_calls.append((session_id, agent_id))

        await manager.cascade_stop("session-a", "proj-1", on_stop=on_stop)
        stopped_sessions = {s for s, _ in callback_calls}
        assert "session-b" in stopped_sessions
        assert "session-c" in stopped_sessions

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def test_cleanup_session_removes_record(self, manager: SpawnManager) -> None:
        await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
        )
        await manager.cleanup_session("session-b")
        assert await manager.get_record("session-b") is None

    async def test_cleanup_session_removes_from_parent_index(self, manager: SpawnManager) -> None:
        await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
            parent_session_id="session-a",
        )
        await manager.cleanup_session("session-b")
        children = await manager.find_children("session-a")
        assert children == []

    async def test_cleanup_session_removes_orphaned_children(self, manager: SpawnManager) -> None:
        await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
            parent_session_id="session-a",
        )
        await manager.register_spawn(
            parent_agent_id="agent-b",
            child_agent_id="agent-c",
            child_session_id="session-c",
            project_id="proj-1",
            parent_session_id="session-b",
        )
        await manager.cleanup_session("session-b")
        assert await manager.get_record("session-c") is None

    async def test_cleanup_session_noop_for_unknown(self, manager: SpawnManager) -> None:
        await manager.cleanup_session("nonexistent")

    async def test_cleanup_project_removes_all_project_records(self, manager: SpawnManager) -> None:
        await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="p1",
            parent_session_id="session-a",
        )
        await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-c",
            child_session_id="session-c",
            project_id="p1",
            parent_session_id="session-a",
        )
        await manager.register_spawn(
            parent_agent_id="agent-x",
            child_agent_id="agent-y",
            child_session_id="session-y",
            project_id="p2",
        )
        removed = await manager.cleanup_project("p1")
        assert removed == 2
        assert await manager.get_record("session-b") is None
        assert await manager.get_record("session-c") is None
        assert await manager.get_record("session-y") is not None

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    async def test_get_stats_empty(self, manager: SpawnManager) -> None:
        stats = await manager.get_stats()
        assert stats["total_records"] == 0

    async def test_get_stats_with_records(self, manager: SpawnManager) -> None:
        await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
            mode=SpawnMode.RUN,
        )
        await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-c",
            child_session_id="session-c",
            project_id="proj-1",
            mode=SpawnMode.SESSION,
        )
        stats = await manager.get_stats()
        assert stats["total_records"] == 2
        assert stats["by_status"]["running"] == 2
        assert stats["by_mode"]["run"] == 1
        assert stats["by_mode"]["session"] == 1
