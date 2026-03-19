"""Unit tests for RedisSpawnManager with mocked Redis."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.model.agent.spawn_mode import SpawnMode
from src.domain.model.agent.spawn_record import SpawnRecord
from src.infrastructure.agent.orchestration.redis_spawn_manager import RedisSpawnManager
from src.infrastructure.agent.orchestration.spawn_manager import SpawnDepthExceededError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_record(
    parent_agent_id: str = "agent-parent",
    child_agent_id: str = "agent-child",
    child_session_id: str = "session-child",
    project_id: str = "proj-1",
    mode: SpawnMode = SpawnMode.RUN,
    status: str = "running",
    task_summary: str = "do task",
) -> SpawnRecord:
    """Build a SpawnRecord with predictable defaults."""
    return SpawnRecord(
        parent_agent_id=parent_agent_id,
        child_agent_id=child_agent_id,
        child_session_id=child_session_id,
        project_id=project_id,
        mode=mode,
        status=status,
        task_summary=task_summary,
    )


def record_json(record: SpawnRecord) -> bytes:
    """Serialize a SpawnRecord to bytes as Redis would return."""
    return json.dumps(record.to_dict()).encode("utf-8")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Mocked async Redis client with safe defaults."""
    redis = AsyncMock()

    # pipeline() is synchronous in redis-py -- use MagicMock so calling it
    # returns the pipe object directly (not a coroutine).
    pipe = MagicMock()
    pipe.execute = AsyncMock(return_value=[True, True, True])
    pipe.setex = MagicMock()
    pipe.sadd = MagicMock()
    pipe.srem = MagicMock()
    pipe.delete = MagicMock()
    redis.pipeline = MagicMock(return_value=pipe)

    redis.smembers = AsyncMock(return_value=set())
    redis.get = AsyncMock(return_value=None)
    redis.sismember = AsyncMock(return_value=False)
    redis.scan = AsyncMock(return_value=(0, []))
    redis.ttl = AsyncMock(return_value=-1)
    redis.setex = AsyncMock()
    redis.srem = AsyncMock()
    return redis


@pytest.fixture
def manager(mock_redis: AsyncMock) -> RedisSpawnManager:
    """RedisSpawnManager wired to a mocked Redis client."""
    return RedisSpawnManager(
        redis_client=mock_redis,
        max_spawn_depth=3,
    )


# ---------------------------------------------------------------------------
# TestMaxSpawnDepthProperty
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMaxSpawnDepthProperty:
    """Tests for the max_spawn_depth property."""

    def test_default_max_spawn_depth_is_three(self, manager: RedisSpawnManager) -> None:
        assert manager.max_spawn_depth == 3

    def test_custom_max_spawn_depth(self, mock_redis: AsyncMock) -> None:
        mgr = RedisSpawnManager(redis_client=mock_redis, max_spawn_depth=7)
        assert mgr.max_spawn_depth == 7

    def test_max_spawn_depth_minimum_enforced(self, mock_redis: AsyncMock) -> None:
        mgr = RedisSpawnManager(redis_client=mock_redis, max_spawn_depth=0)
        assert mgr.max_spawn_depth == 1

    def test_max_spawn_depth_negative_enforced(self, mock_redis: AsyncMock) -> None:
        mgr = RedisSpawnManager(redis_client=mock_redis, max_spawn_depth=-5)
        assert mgr.max_spawn_depth == 1


# ---------------------------------------------------------------------------
# TestRegisterSpawn
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRegisterSpawn:
    """Tests for register_spawn()."""

    async def test_register_spawn_returns_record(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        mock_redis.get.return_value = None  # no existing record → depth 0
        mock_redis.scan.return_value = (0, [])  # no children sets

        record = await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
            parent_session_id="session-a",
            task_summary="my task",
        )

        assert record.parent_agent_id == "agent-a"
        assert record.child_agent_id == "agent-b"
        assert record.child_session_id == "session-b"
        assert record.project_id == "proj-1"
        assert record.task_summary == "my task"
        assert record.status == "running"

    async def test_register_spawn_default_mode_is_run(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        mock_redis.get.return_value = None
        mock_redis.scan.return_value = (0, [])

        record = await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
        )
        assert record.mode is SpawnMode.RUN

    async def test_register_spawn_custom_mode_session(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        mock_redis.get.return_value = None
        mock_redis.scan.return_value = (0, [])

        record = await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
            mode=SpawnMode.SESSION,
        )
        assert record.mode is SpawnMode.SESSION

    async def test_register_spawn_calls_pipeline(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        mock_redis.get.return_value = None
        mock_redis.scan.return_value = (0, [])

        await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
        )

        mock_redis.pipeline.assert_called_once()

    async def test_register_spawn_depth_exceeded_raises(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        # manager has max_spawn_depth=3; simulate depth-3 parent chain
        # get_spawn_depth counts records for session-d → 3 hops
        session_d_record = make_record(
            parent_agent_id="agent-c",
            child_agent_id="agent-d",
            child_session_id="session-d",
            project_id="proj-1",
        )
        session_c_record = make_record(
            parent_agent_id="agent-b",
            child_agent_id="agent-c",
            child_session_id="session-c",
            project_id="proj-1",
        )
        session_b_record = make_record(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
        )

        # get() returns different records based on key
        def get_side_effect(key: str) -> bytes | None:
            if "session-d" in key:
                return record_json(session_d_record)
            if "session-c" in key:
                return record_json(session_c_record)
            if "session-b" in key:
                return record_json(session_b_record)
            return None

        mock_redis.get.side_effect = get_side_effect

        # scan finds children sets for parent lookup
        children_key_d = "agent:spawn:children:session-c"
        children_key_c = "agent:spawn:children:session-b"
        children_key_b = "agent:spawn:children:session-a"

        def scan_side_effect(**kwargs: object) -> tuple[int, list[str]]:
            return (0, [children_key_b, children_key_c, children_key_d])

        mock_redis.scan.side_effect = scan_side_effect

        def sismember_side_effect(key: str, member: str) -> bool:
            if key == children_key_b and member == "session-b":
                return True
            if key == children_key_c and member == "session-c":
                return True
            return key == children_key_d and member == "session-d"

        mock_redis.sismember.side_effect = sismember_side_effect

        with pytest.raises(SpawnDepthExceededError) as exc_info:
            await manager.register_spawn(
                parent_agent_id="agent-d",
                child_agent_id="agent-e",
                child_session_id="session-e",
                project_id="proj-1",
                parent_session_id="session-d",
            )
        assert exc_info.value.max_depth == 3

    async def test_register_spawn_with_run_registry(self, mock_redis: AsyncMock) -> None:
        run_registry = MagicMock()
        run_registry.create_run = MagicMock()
        mgr = RedisSpawnManager(
            redis_client=mock_redis,
            run_registry=run_registry,
            max_spawn_depth=5,
        )
        mock_redis.get.return_value = None
        mock_redis.scan.return_value = (0, [])

        await mgr.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
            conversation_id="conv-1",
        )

        run_registry.create_run.assert_called_once()

    async def test_register_spawn_redis_failure_does_not_raise(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        mock_redis.get.return_value = None
        mock_redis.scan.return_value = (0, [])
        pipe = mock_redis.pipeline.return_value
        pipe.execute.side_effect = ConnectionError("Redis down")

        # Should NOT raise — failures are logged and swallowed
        record = await manager.register_spawn(
            parent_agent_id="agent-a",
            child_agent_id="agent-b",
            child_session_id="session-b",
            project_id="proj-1",
        )
        assert record is not None


# ---------------------------------------------------------------------------
# TestFindChildren
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFindChildren:
    """Tests for find_children()."""

    async def test_find_children_empty_when_no_members(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        mock_redis.smembers.return_value = set()
        result = await manager.find_children("session-a")
        assert result == []

    async def test_find_children_returns_matching_records(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        child_b = make_record(child_session_id="session-b")
        mock_redis.smembers.return_value = {b"session-b"}
        mock_redis.get.return_value = record_json(child_b)

        result = await manager.find_children("session-a")
        assert len(result) == 1
        assert result[0].child_session_id == "session-b"

    async def test_find_children_filters_by_status(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        running_child = make_record(child_session_id="session-b", status="running")
        completed_child = make_record(child_session_id="session-c", status="completed")

        mock_redis.smembers.return_value = {b"session-b", b"session-c"}

        def get_side_effect(key: str) -> bytes | None:
            if "session-b" in key:
                return record_json(running_child)
            if "session-c" in key:
                return record_json(completed_child)
            return None

        mock_redis.get.side_effect = get_side_effect

        running = await manager.find_children("session-a", status="running")
        assert len(running) == 1
        assert running[0].child_session_id == "session-b"

        completed = await manager.find_children("session-a", status="completed")
        assert len(completed) == 1
        assert completed[0].child_session_id == "session-c"

    async def test_find_children_skips_missing_records(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        mock_redis.smembers.return_value = {b"session-b"}
        mock_redis.get.return_value = None  # record disappeared

        result = await manager.find_children("session-a")
        assert result == []

    async def test_find_children_redis_failure_returns_empty(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        mock_redis.smembers.side_effect = ConnectionError("Redis down")
        result = await manager.find_children("session-a")
        assert result == []

    async def test_find_children_handles_string_member(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        child = make_record(child_session_id="session-b")
        # String member instead of bytes
        mock_redis.smembers.return_value = {"session-b"}
        mock_redis.get.return_value = record_json(child)

        result = await manager.find_children("session-a")
        assert len(result) == 1


# ---------------------------------------------------------------------------
# TestFindDescendants
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFindDescendants:
    """Tests for find_descendants()."""

    async def test_find_descendants_empty_tree(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        mock_redis.smembers.return_value = set()
        result = await manager.find_descendants("session-root")
        assert result == []

    async def test_find_descendants_single_level(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        child_b = make_record(child_session_id="session-b")
        # First smembers call returns session-b; second (for session-b children) returns empty
        mock_redis.smembers.side_effect = [
            {b"session-b"},
            set(),
        ]
        mock_redis.get.return_value = record_json(child_b)

        result = await manager.find_descendants("session-root")
        assert len(result) == 1
        assert result[0].child_session_id == "session-b"

    async def test_find_descendants_multi_level(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        child_b = make_record(child_session_id="session-b")
        child_c = make_record(child_session_id="session-c")

        mock_redis.smembers.side_effect = [
            {b"session-b"},  # children of root
            {b"session-c"},  # children of session-b
            set(),  # children of session-c
        ]

        def get_side_effect(key: str) -> bytes | None:
            if "session-b" in key:
                return record_json(child_b)
            if "session-c" in key:
                return record_json(child_c)
            return None

        mock_redis.get.side_effect = get_side_effect

        result = await manager.find_descendants("session-root")
        session_ids = [r.child_session_id for r in result]
        assert "session-b" in session_ids
        assert "session-c" in session_ids
        assert len(result) == 2

    async def test_find_descendants_include_self(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        self_record = make_record(child_session_id="session-root")
        mock_redis.smembers.return_value = set()

        def get_side_effect(key: str) -> bytes | None:
            if "session-root" in key:
                return record_json(self_record)
            return None

        mock_redis.get.side_effect = get_side_effect

        result = await manager.find_descendants("session-root", include_self=True)
        assert any(r.child_session_id == "session-root" for r in result)

    async def test_find_descendants_include_self_false_by_default(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        mock_redis.smembers.return_value = set()
        mock_redis.get.return_value = None

        result = await manager.find_descendants("session-root")
        assert result == []


# ---------------------------------------------------------------------------
# TestGetRecord
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetRecord:
    """Tests for get_record()."""

    async def test_get_record_found(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        record = make_record(child_session_id="session-b")
        mock_redis.get.return_value = record_json(record)

        result = await manager.get_record("session-b")

        assert result is not None
        assert result.child_session_id == "session-b"

    async def test_get_record_not_found_returns_none(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        mock_redis.get.return_value = None
        result = await manager.get_record("nonexistent")
        assert result is None

    async def test_get_record_redis_failure_returns_none(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        mock_redis.get.side_effect = ConnectionError("Redis down")
        result = await manager.get_record("session-b")
        assert result is None

    async def test_get_record_uses_correct_key(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        mock_redis.get.return_value = None
        await manager.get_record("session-xyz")
        mock_redis.get.assert_called_once_with("agent:spawn:session-xyz")


# ---------------------------------------------------------------------------
# TestGetSpawnDepth
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetSpawnDepth:
    """Tests for get_spawn_depth()."""

    async def test_get_spawn_depth_none_returns_zero(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        depth = await manager.get_spawn_depth(None)
        assert depth == 0

    async def test_get_spawn_depth_unknown_session_returns_zero(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        mock_redis.get.return_value = None
        depth = await manager.get_spawn_depth("unknown")
        assert depth == 0

    async def test_get_spawn_depth_child_is_one(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        child = make_record(child_session_id="session-b")
        mock_redis.get.return_value = record_json(child)
        mock_redis.scan.return_value = (0, [])  # no parent found

        depth = await manager.get_spawn_depth("session-b")
        assert depth == 1

    async def test_get_spawn_depth_grandchild_is_two(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        session_c = make_record(child_session_id="session-c")
        session_b = make_record(child_session_id="session-b")

        children_key_a = "agent:spawn:children:session-a"
        children_key_b = "agent:spawn:children:session-b"

        def get_side_effect(key: str) -> bytes | None:
            if "session-c" in key:
                return record_json(session_c)
            if "session-b" in key:
                return record_json(session_b)
            return None

        mock_redis.get.side_effect = get_side_effect
        mock_redis.scan.return_value = (0, [children_key_a, children_key_b])

        def sismember_side_effect(key: str, member: str) -> bool:
            if key == children_key_a and member == "session-b":
                return True
            return key == children_key_b and member == "session-c"

        mock_redis.sismember.side_effect = sismember_side_effect

        depth = await manager.get_spawn_depth("session-c")
        assert depth == 2

    async def test_get_spawn_depth_cycle_protection(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        # Artificial cycle: session-a references itself as a record
        session_a = make_record(child_session_id="session-a")
        mock_redis.get.return_value = record_json(session_a)
        mock_redis.scan.return_value = (0, [])  # scan finds no parent set

        # Should not loop forever — visited set breaks the cycle
        depth = await manager.get_spawn_depth("session-a")
        assert isinstance(depth, int)
        assert depth >= 0


# ---------------------------------------------------------------------------
# TestHasActiveChildren
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHasActiveChildren:
    """Tests for has_active_children()."""

    async def test_has_active_children_true(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        running_child = make_record(child_session_id="session-b", status="running")
        mock_redis.smembers.return_value = {b"session-b"}
        mock_redis.get.return_value = record_json(running_child)

        result = await manager.has_active_children("session-a")
        assert result is True

    async def test_has_active_children_false_no_children(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        mock_redis.smembers.return_value = set()
        result = await manager.has_active_children("session-a")
        assert result is False

    async def test_has_active_children_false_when_all_completed(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        completed_child = make_record(child_session_id="session-b", status="completed")
        mock_redis.smembers.return_value = {b"session-b"}
        mock_redis.get.return_value = record_json(completed_child)

        result = await manager.has_active_children("session-a")
        assert result is False


# ---------------------------------------------------------------------------
# TestCountChildren
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCountChildren:
    """Tests for count_children()."""

    async def test_count_children_zero_when_empty(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        mock_redis.smembers.return_value = set()
        count = await manager.count_children("session-a")
        assert count == 0

    async def test_count_children_total_without_filter(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        child_b = make_record(child_session_id="session-b")
        child_c = make_record(child_session_id="session-c", status="completed")
        mock_redis.smembers.return_value = {b"session-b", b"session-c"}

        def get_side_effect(key: str) -> bytes | None:
            if "session-b" in key:
                return record_json(child_b)
            if "session-c" in key:
                return record_json(child_c)
            return None

        mock_redis.get.side_effect = get_side_effect

        count = await manager.count_children("session-a")
        assert count == 2

    async def test_count_children_with_status_filter(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        child_b = make_record(child_session_id="session-b", status="running")
        child_c = make_record(child_session_id="session-c", status="completed")
        mock_redis.smembers.return_value = {b"session-b", b"session-c"}

        def get_side_effect(key: str) -> bytes | None:
            if "session-b" in key:
                return record_json(child_b)
            if "session-c" in key:
                return record_json(child_c)
            return None

        mock_redis.get.side_effect = get_side_effect

        running = await manager.count_children("session-a", status="running")
        assert running == 1

        completed = await manager.count_children("session-a", status="completed")
        assert completed == 1


# ---------------------------------------------------------------------------
# TestUpdateStatus
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateStatus:
    """Tests for update_status()."""

    async def test_update_status_returns_updated_record(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        original = make_record(child_session_id="session-b", status="running")
        mock_redis.get.return_value = record_json(original)
        mock_redis.ttl.return_value = 3600

        updated = await manager.update_status("session-b", "completed")

        assert updated is not None
        assert updated.status == "completed"
        assert updated.child_session_id == "session-b"

    async def test_update_status_unknown_session_returns_none(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        mock_redis.get.return_value = None
        result = await manager.update_status("nonexistent", "completed")
        assert result is None

    async def test_update_status_preserves_existing_ttl(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        original = make_record(child_session_id="session-b")
        mock_redis.get.return_value = record_json(original)
        mock_redis.ttl.return_value = 1800  # 30 minutes remaining

        await manager.update_status("session-b", "completed")

        mock_redis.setex.assert_called_once()
        _, args, _ = mock_redis.setex.mock_calls[0]
        # Second positional arg is TTL
        assert args[1] == 1800

    async def test_update_status_uses_default_ttl_when_ttl_negative(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        original = make_record(child_session_id="session-b")
        mock_redis.get.return_value = record_json(original)
        mock_redis.ttl.return_value = -1  # key has no TTL

        await manager.update_status("session-b", "failed")

        mock_redis.setex.assert_called_once()
        _, args, _ = mock_redis.setex.mock_calls[0]
        assert args[1] == 86400  # default TTL

    async def test_update_status_redis_failure_returns_none(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        original = make_record(child_session_id="session-b")
        mock_redis.get.return_value = record_json(original)
        mock_redis.ttl.return_value = 3600
        mock_redis.setex.side_effect = ConnectionError("Redis down")

        result = await manager.update_status("session-b", "completed")
        assert result is None

    async def test_update_status_with_run_registry_completed(self, mock_redis: AsyncMock) -> None:
        run_registry = MagicMock()
        mgr = RedisSpawnManager(
            redis_client=mock_redis, run_registry=run_registry, max_spawn_depth=5
        )
        original = make_record(child_session_id="session-b")
        mock_redis.get.return_value = record_json(original)
        mock_redis.ttl.return_value = 3600

        await mgr.update_status("session-b", "completed", conversation_id="conv-1")

        run_registry.mark_completed.assert_called_once()

    async def test_update_status_with_run_registry_failed(self, mock_redis: AsyncMock) -> None:
        run_registry = MagicMock()
        mgr = RedisSpawnManager(
            redis_client=mock_redis, run_registry=run_registry, max_spawn_depth=5
        )
        original = make_record(child_session_id="session-b")
        mock_redis.get.return_value = record_json(original)
        mock_redis.ttl.return_value = 3600

        await mgr.update_status("session-b", "failed", conversation_id="conv-1")

        run_registry.mark_failed.assert_called_once()


# ---------------------------------------------------------------------------
# TestCascadeStop
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCascadeStop:
    """Tests for cascade_stop()."""

    async def test_cascade_stop_no_children_no_root_record(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        # No descendants, no root record
        mock_redis.smembers.return_value = set()
        mock_redis.get.return_value = None

        stopped = await manager.cascade_stop("session-a", "proj-1")
        assert stopped == []

    async def test_cascade_stop_stops_running_root(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        root_record = make_record(child_session_id="session-a", status="running")
        mock_redis.smembers.return_value = set()

        call_count = 0

        def get_side_effect(key: str) -> bytes | None:
            nonlocal call_count
            call_count += 1
            if "session-a" in key:
                # First call from get_record inside find_descendants's include_self=False
                # Then from get_record called for root in cascade_stop itself
                return record_json(root_record)
            return None

        mock_redis.get.side_effect = get_side_effect
        mock_redis.ttl.return_value = 3600

        stopped = await manager.cascade_stop("session-a", "proj-1")
        assert "session-a" in stopped

    async def test_cascade_stop_skips_non_running_root(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        completed_root = make_record(child_session_id="session-a", status="completed")
        mock_redis.smembers.return_value = set()
        mock_redis.get.return_value = record_json(completed_root)

        stopped = await manager.cascade_stop("session-a", "proj-1")
        assert stopped == []

    async def test_cascade_stop_calls_on_stop_callback(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        root_record = make_record(child_session_id="session-a", status="running")
        mock_redis.smembers.return_value = set()
        mock_redis.get.return_value = record_json(root_record)
        mock_redis.ttl.return_value = 3600

        callback_calls: list[tuple[str, str]] = []

        async def on_stop(session_id: str, agent_id: str) -> None:
            callback_calls.append((session_id, agent_id))

        await manager.cascade_stop("session-a", "proj-1", on_stop=on_stop)
        assert any(s == "session-a" for s, _ in callback_calls)

    async def test_cascade_stop_with_session_registry(self, mock_redis: AsyncMock) -> None:
        session_registry = AsyncMock()
        session_registry.unregister = AsyncMock()
        mgr = RedisSpawnManager(
            redis_client=mock_redis,
            session_registry=session_registry,
            max_spawn_depth=5,
        )
        root_record = make_record(child_session_id="session-a", status="running")
        mock_redis.smembers.return_value = set()
        mock_redis.get.return_value = record_json(root_record)
        mock_redis.ttl.return_value = 3600

        await mgr.cascade_stop("session-a", "proj-1")

        session_registry.unregister.assert_called()


# ---------------------------------------------------------------------------
# TestCleanupSession
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCleanupSession:
    """Tests for cleanup_session()."""

    async def test_cleanup_session_noop_for_unknown(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        mock_redis.get.return_value = None
        # Should not raise
        await manager.cleanup_session("nonexistent")

    async def test_cleanup_session_calls_pipeline_delete(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        record = make_record(child_session_id="session-b", project_id="proj-1")
        mock_redis.get.return_value = record_json(record)
        mock_redis.scan.return_value = (0, [])  # no parent found
        mock_redis.smembers.return_value = set()  # no orphaned children

        await manager.cleanup_session("session-b")

        mock_redis.pipeline.assert_called()
        pipe = mock_redis.pipeline.return_value
        pipe.execute.assert_called()

    async def test_cleanup_session_removes_from_parent_set(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        record = make_record(child_session_id="session-b", project_id="proj-1")
        mock_redis.get.return_value = record_json(record)

        children_key = "agent:spawn:children:session-a"
        mock_redis.scan.return_value = (0, [children_key])
        mock_redis.sismember.return_value = True  # session-b is member of session-a's children
        mock_redis.smembers.return_value = set()  # no orphaned children of session-b

        await manager.cleanup_session("session-b")

        mock_redis.srem.assert_called_once_with(children_key, "session-b")

    async def test_cleanup_session_removes_orphaned_children(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        record = make_record(child_session_id="session-b", project_id="proj-1")
        mock_redis.get.return_value = record_json(record)
        mock_redis.scan.return_value = (0, [])  # no parent found

        # session-b has one orphan child: session-c
        mock_redis.smembers.return_value = {b"session-c"}

        await manager.cleanup_session("session-b")

        # orphan_pipe.delete should be called for session-c record + children key
        pipe = mock_redis.pipeline.return_value
        assert pipe.delete.called


# ---------------------------------------------------------------------------
# TestCleanupProject
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCleanupProject:
    """Tests for cleanup_project()."""

    async def test_cleanup_project_empty_returns_zero(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        mock_redis.smembers.return_value = set()
        count = await manager.cleanup_project("proj-empty")
        assert count == 0

    async def test_cleanup_project_returns_count(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        mock_redis.smembers.return_value = {b"session-b", b"session-c"}
        count = await manager.cleanup_project("proj-1")
        assert count == 2

    async def test_cleanup_project_calls_pipeline(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        mock_redis.smembers.return_value = {b"session-b"}
        await manager.cleanup_project("proj-1")

        mock_redis.pipeline.assert_called()
        pipe = mock_redis.pipeline.return_value
        pipe.execute.assert_called()

    async def test_cleanup_project_redis_failure_returns_zero_on_smembers(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        mock_redis.smembers.side_effect = ConnectionError("Redis down")
        count = await manager.cleanup_project("proj-1")
        assert count == 0

    async def test_cleanup_project_redis_failure_returns_zero_on_execute(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        mock_redis.smembers.return_value = {b"session-b"}
        pipe = mock_redis.pipeline.return_value
        pipe.execute.side_effect = ConnectionError("Redis down")

        count = await manager.cleanup_project("proj-1")
        assert count == 0


# ---------------------------------------------------------------------------
# TestGetStats
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetStats:
    """Tests for get_stats()."""

    async def test_get_stats_empty_returns_zeros(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        mock_redis.scan.return_value = (0, [])
        stats = await manager.get_stats()

        assert stats["total_records"] == 0
        assert stats["parent_count"] == 0
        assert stats["by_status"] == {}
        assert stats["by_mode"] == {}
        assert stats["max_spawn_depth"] == 3

    async def test_get_stats_counts_record_keys(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        record = make_record(child_session_id="session-b", status="running")
        record_key = "agent:spawn:session-b"
        mock_redis.scan.return_value = (0, [record_key])
        mock_redis.get.return_value = record_json(record)

        stats = await manager.get_stats()
        assert stats["total_records"] == 1
        assert stats["by_status"]["running"] == 1
        assert stats["by_mode"]["run"] == 1

    async def test_get_stats_skips_children_keys(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        children_key = "agent:spawn:children:session-a"
        mock_redis.scan.return_value = (0, [children_key])

        stats = await manager.get_stats()
        assert stats["total_records"] == 0
        assert stats["parent_count"] == 1  # the children key counts as a parent session

    async def test_get_stats_skips_project_keys(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        project_key = "agent:spawn:project:proj-1"
        mock_redis.scan.return_value = (0, [project_key])

        stats = await manager.get_stats()
        assert stats["total_records"] == 0

    async def test_get_stats_multiple_modes_and_statuses(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        run_record = make_record(
            child_session_id="session-b",
            mode=SpawnMode.RUN,
            status="running",
        )
        session_record = make_record(
            child_session_id="session-c",
            mode=SpawnMode.SESSION,
            status="completed",
        )

        run_key = "agent:spawn:session-b"
        session_key = "agent:spawn:session-c"

        mock_redis.scan.return_value = (0, [run_key, session_key])

        def get_side_effect(key: str) -> bytes | None:
            if "session-b" in key:
                return record_json(run_record)
            if "session-c" in key:
                return record_json(session_record)
            return None

        mock_redis.get.side_effect = get_side_effect

        stats = await manager.get_stats()
        assert stats["total_records"] == 2
        assert stats["by_status"]["running"] == 1
        assert stats["by_status"]["completed"] == 1
        assert stats["by_mode"]["run"] == 1
        assert stats["by_mode"]["session"] == 1

    async def test_get_stats_handles_redis_failure(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        mock_redis.scan.side_effect = ConnectionError("Redis down")
        # Should return a partial stats dict without raising
        stats = await manager.get_stats()
        assert "total_records" in stats

    async def test_get_stats_includes_max_spawn_depth(
        self, manager: RedisSpawnManager, mock_redis: AsyncMock
    ) -> None:
        mock_redis.scan.return_value = (0, [])
        stats = await manager.get_stats()
        assert stats["max_spawn_depth"] == 3
