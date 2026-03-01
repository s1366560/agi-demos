"""Unit tests for DepsStateStore Redis-backed state store."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.plugins.sandbox_deps.models import (
    DepsStateRecord,
    PreparedState,
)
from src.infrastructure.agent.plugins.sandbox_deps.state_store import (
    DepsStateStore,
)


def _make_record(
    *,
    plugin_id: str = "test-plugin",
    project_id: str = "proj-1",
    sandbox_id: str = "sbx-1",
    state: PreparedState | None = None,
    install_attempts: int = 0,
    last_error: str | None = None,
) -> DepsStateRecord:
    """Helper to create a DepsStateRecord with sensible defaults."""
    return DepsStateRecord(
        plugin_id=plugin_id,
        project_id=project_id,
        sandbox_id=sandbox_id,
        state=state,
        last_check=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        install_attempts=install_attempts,
        last_error=last_error,
    )


def _make_prepared_state(
    *,
    plugin_id: str = "test-plugin",
    deps_hash: str = "abc123",
    sandbox_image_digest: str = "sha256:deadbeef",
    venv_path: str = "/opt/memstack/envs/test-plugin/abc123/",
) -> PreparedState:
    """Helper to create a PreparedState."""
    return PreparedState(
        plugin_id=plugin_id,
        deps_hash=deps_hash,
        sandbox_image_digest=sandbox_image_digest,
        prepared_at=datetime(2026, 1, 1, 11, 0, 0, tzinfo=UTC),
        venv_path=venv_path,
    )


def _mock_redis() -> AsyncMock:
    """Create a mock Redis client with common methods."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    redis.delete = AsyncMock(return_value=1)
    redis.sadd = AsyncMock(return_value=1)
    redis.srem = AsyncMock(return_value=1)
    redis.smembers = AsyncMock(return_value=set())
    redis.exists = AsyncMock(return_value=1)
    return redis


@pytest.mark.unit
class TestDepsStateStoreInit:
    """Test DepsStateStore initialization."""

    async def test_init_default_ttl(self) -> None:
        """Default TTL should be 7200 seconds (2 hours)."""
        store = DepsStateStore(redis_client=_mock_redis())
        assert store._ttl == 7200

    async def test_init_custom_ttl(self) -> None:
        """Custom TTL should override default."""
        store = DepsStateStore(redis_client=_mock_redis(), ttl=3600)
        assert store._ttl == 3600

    async def test_init_none_redis(self) -> None:
        """Store should accept None redis_client without error."""
        store = DepsStateStore(redis_client=None)
        assert store._redis is None


@pytest.mark.unit
class TestDepsStateStoreKeyHelpers:
    """Test static key-building methods."""

    async def test_record_key_format(self) -> None:
        """_record_key should produce 'deps:state:{plugin}:{sandbox}'."""
        key = DepsStateStore._record_key("my-plugin", "sbx-42")
        assert key == "deps:state:my-plugin:sbx-42"

    async def test_compound_id_format(self) -> None:
        """_compound_id should produce '{plugin}:{sandbox}'."""
        cid = DepsStateStore._compound_id("plug-a", "sbx-b")
        assert cid == "plug-a:sbx-b"

    async def test_project_key_format(self) -> None:
        """_project_key should produce 'deps:state:project:{project}'."""
        key = DepsStateStore._project_key("proj-99")
        assert key == "deps:state:project:proj-99"


@pytest.mark.unit
class TestDepsStateStoreSerialization:
    """Test round-trip serialization of DepsStateRecord."""

    async def test_serialize_record_without_state(self) -> None:
        """Record with state=None should serialize to valid JSON."""
        record = _make_record()
        raw = DepsStateStore._serialize_record(record)
        data = json.loads(raw)
        assert data["plugin_id"] == "test-plugin"
        assert data["state"] is None
        assert data["install_attempts"] == 0

    async def test_serialize_record_with_prepared_state(self) -> None:
        """Record with PreparedState should include all state fields."""
        ps = _make_prepared_state()
        record = _make_record(state=ps)
        raw = DepsStateStore._serialize_record(record)
        data = json.loads(raw)

        assert data["state"] is not None
        assert data["state"]["plugin_id"] == "test-plugin"
        assert data["state"]["deps_hash"] == "abc123"
        assert data["state"]["sandbox_image_digest"] == "sha256:deadbeef"
        assert data["state"]["venv_path"].endswith("/")
        # prepared_at should be ISO format string
        datetime.fromisoformat(data["state"]["prepared_at"])

    async def test_round_trip_without_state(self) -> None:
        """Serialize then deserialize should produce equivalent record."""
        record = _make_record(install_attempts=3, last_error="oops")
        raw = DepsStateStore._serialize_record(record)
        restored = DepsStateStore._deserialize_record(raw)

        assert restored.plugin_id == record.plugin_id
        assert restored.project_id == record.project_id
        assert restored.sandbox_id == record.sandbox_id
        assert restored.state is None
        assert restored.install_attempts == 3
        assert restored.last_error == "oops"

    async def test_round_trip_with_prepared_state(self) -> None:
        """Round-trip with PreparedState should preserve all fields."""
        ps = _make_prepared_state()
        record = _make_record(state=ps)
        raw = DepsStateStore._serialize_record(record)
        restored = DepsStateStore._deserialize_record(raw)

        assert restored.state is not None
        assert restored.state.plugin_id == ps.plugin_id
        assert restored.state.deps_hash == ps.deps_hash
        assert restored.state.sandbox_image_digest == ps.sandbox_image_digest
        assert restored.state.prepared_at == ps.prepared_at
        assert restored.state.venv_path == ps.venv_path


@pytest.mark.unit
class TestDepsStateStoreSave:
    """Test save method."""

    async def test_save_calls_redis_set_with_key_and_ttl(self) -> None:
        """save should store serialized data with correct key and TTL."""
        redis = _mock_redis()
        store = DepsStateStore(redis_client=redis, ttl=5000)
        record = _make_record()

        await store.save(record)

        redis.set.assert_awaited_once()
        call_args = redis.set.call_args
        assert call_args[0][0] == "deps:state:test-plugin:sbx-1"
        # Second positional arg is the serialized JSON
        json.loads(call_args[0][1])  # should not raise
        assert call_args[1]["ex"] == 5000

    async def test_save_adds_to_tracking_set(self) -> None:
        """save should sadd compound id to the tracking set."""
        redis = _mock_redis()
        store = DepsStateStore(redis_client=redis)
        record = _make_record()

        await store.save(record)

        # At least one sadd call to the tracking key
        tracking_calls = [c for c in redis.sadd.call_args_list if c[0][0] == "deps:state:tracking"]
        assert len(tracking_calls) == 1
        assert tracking_calls[0][0][1] == "test-plugin:sbx-1"

    async def test_save_adds_to_project_index(self) -> None:
        """save should sadd compound id to the project index set."""
        redis = _mock_redis()
        store = DepsStateStore(redis_client=redis)
        record = _make_record(project_id="proj-X")

        await store.save(record)

        project_calls = [
            c for c in redis.sadd.call_args_list if c[0][0] == "deps:state:project:proj-X"
        ]
        assert len(project_calls) == 1

    async def test_save_noop_when_redis_is_none(self) -> None:
        """save with no redis_client should not raise."""
        store = DepsStateStore(redis_client=None)
        record = _make_record()
        # Should complete without exception
        await store.save(record)

    async def test_save_handles_redis_exception(self) -> None:
        """save should catch Redis errors and not propagate."""
        redis = _mock_redis()
        redis.set = AsyncMock(side_effect=ConnectionError("Redis down"))
        store = DepsStateStore(redis_client=redis)
        record = _make_record()

        # Should not raise
        await store.save(record)


@pytest.mark.unit
class TestDepsStateStoreLoad:
    """Test load method."""

    async def test_load_returns_deserialized_record(self) -> None:
        """load should return record when Redis key exists."""
        record = _make_record()
        redis = _mock_redis()
        redis.get = AsyncMock(return_value=DepsStateStore._serialize_record(record))
        store = DepsStateStore(redis_client=redis)

        result = await store.load("test-plugin", "sbx-1")

        assert result is not None
        assert result.plugin_id == "test-plugin"
        assert result.sandbox_id == "sbx-1"

    async def test_load_returns_none_when_key_missing(self) -> None:
        """load should return None when Redis key does not exist."""
        redis = _mock_redis()
        redis.get = AsyncMock(return_value=None)
        store = DepsStateStore(redis_client=redis)

        result = await store.load("no-plugin", "no-sbx")

        assert result is None

    async def test_load_returns_none_when_redis_is_none(self) -> None:
        """load with no redis_client should return None."""
        store = DepsStateStore(redis_client=None)
        result = await store.load("p", "s")
        assert result is None

    async def test_load_handles_redis_exception(self) -> None:
        """load should catch Redis errors and return None."""
        redis = _mock_redis()
        redis.get = AsyncMock(side_effect=ConnectionError("timeout"))
        store = DepsStateStore(redis_client=redis)

        result = await store.load("p", "s")

        assert result is None


@pytest.mark.unit
class TestDepsStateStoreRemove:
    """Test remove method."""

    async def test_remove_deletes_and_cleans_sets(self) -> None:
        """remove should delete key and srem from tracking + project."""
        redis = _mock_redis()
        redis.delete = AsyncMock(return_value=1)
        store = DepsStateStore(redis_client=redis)

        result = await store.remove("plug", "sbx", "proj")

        assert result is True
        redis.delete.assert_awaited_once_with("deps:state:plug:sbx")
        # Check tracking srem
        tracking_srem = [c for c in redis.srem.call_args_list if c[0][0] == "deps:state:tracking"]
        assert len(tracking_srem) == 1
        # Check project srem
        project_srem = [
            c for c in redis.srem.call_args_list if c[0][0] == "deps:state:project:proj"
        ]
        assert len(project_srem) == 1

    async def test_remove_returns_true_when_key_existed(self) -> None:
        """remove should return True when redis.delete returns 1."""
        redis = _mock_redis()
        redis.delete = AsyncMock(return_value=1)
        store = DepsStateStore(redis_client=redis)

        assert await store.remove("p", "s", "pr") is True

    async def test_remove_returns_false_when_key_missing(self) -> None:
        """remove should return False when redis.delete returns 0."""
        redis = _mock_redis()
        redis.delete = AsyncMock(return_value=0)
        store = DepsStateStore(redis_client=redis)

        assert await store.remove("p", "s", "pr") is False

    async def test_remove_returns_false_when_redis_is_none(self) -> None:
        """remove with no redis_client should return False."""
        store = DepsStateStore(redis_client=None)
        assert await store.remove("p", "s", "pr") is False


@pytest.mark.unit
class TestDepsStateStoreListByProject:
    """Test list_by_project method."""

    async def test_list_by_project_returns_records(self) -> None:
        """list_by_project should load records for each compound."""
        record = _make_record(plugin_id="pa", sandbox_id="sa")
        redis = _mock_redis()
        redis.smembers = AsyncMock(return_value={"pa:sa"})
        redis.get = AsyncMock(return_value=DepsStateStore._serialize_record(record))
        store = DepsStateStore(redis_client=redis)

        results = await store.list_by_project("proj-1")

        assert len(results) == 1
        assert results[0].plugin_id == "pa"

    async def test_list_by_project_returns_empty_when_redis_none(
        self,
    ) -> None:
        """list_by_project with no redis should return []."""
        store = DepsStateStore(redis_client=None)
        assert await store.list_by_project("proj") == []

    async def test_list_by_project_skips_malformed_compound(self) -> None:
        """Compounds without ':' separator should be skipped."""
        redis = _mock_redis()
        redis.smembers = AsyncMock(return_value={"malformed-no-colon", "plug:sbx"})
        record = _make_record(plugin_id="plug", sandbox_id="sbx")
        redis.get = AsyncMock(return_value=DepsStateStore._serialize_record(record))
        store = DepsStateStore(redis_client=redis)

        results = await store.list_by_project("proj")

        # Only the valid compound should produce a record
        assert len(results) == 1
        assert results[0].plugin_id == "plug"


@pytest.mark.unit
class TestDepsStateStoreListBySandbox:
    """Test list_by_sandbox method."""

    async def test_list_by_sandbox_filters_by_suffix(self) -> None:
        """list_by_sandbox should only load compounds ending in sandbox_id."""
        record = _make_record(plugin_id="pa", sandbox_id="target-sbx")
        redis = _mock_redis()
        redis.smembers = AsyncMock(return_value={"pa:target-sbx", "pb:other-sbx"})
        redis.get = AsyncMock(return_value=DepsStateStore._serialize_record(record))
        store = DepsStateStore(redis_client=redis)

        results = await store.list_by_sandbox("target-sbx")

        assert len(results) == 1
        assert results[0].plugin_id == "pa"

    async def test_list_by_sandbox_returns_empty_when_redis_none(
        self,
    ) -> None:
        """list_by_sandbox with no redis should return []."""
        store = DepsStateStore(redis_client=None)
        assert await store.list_by_sandbox("sbx") == []


@pytest.mark.unit
class TestDepsStateStoreRefreshAll:
    """Test refresh_all method."""

    async def test_refresh_all_returns_loaded_count(self) -> None:
        """refresh_all should return number of successfully loaded records."""
        r1 = _make_record(plugin_id="p1", sandbox_id="s1")
        r2 = _make_record(plugin_id="p2", sandbox_id="s2")
        redis = _mock_redis()
        redis.smembers = AsyncMock(return_value={"p1:s1", "p2:s2"})

        serialized = {
            "deps:state:p1:s1": DepsStateStore._serialize_record(r1),
            "deps:state:p2:s2": DepsStateStore._serialize_record(r2),
        }

        async def _get(key: str) -> str | None:
            return serialized.get(key)

        redis.get = AsyncMock(side_effect=_get)
        store = DepsStateStore(redis_client=redis)

        count = await store.refresh_all()

        assert count == 2

    async def test_refresh_all_returns_zero_when_redis_none(self) -> None:
        """refresh_all with no redis should return 0."""
        store = DepsStateStore(redis_client=None)
        assert await store.refresh_all() == 0


@pytest.mark.unit
class TestDepsStateStoreCleanupExpired:
    """Test cleanup_expired method."""

    async def test_cleanup_expired_removes_stale_entries(self) -> None:
        """Entries whose data key no longer exists should be removed."""
        redis = _mock_redis()
        redis.smembers = AsyncMock(return_value={"p1:s1", "p2:s2"})

        async def _exists(key: str) -> int:
            if key == "deps:state:p1:s1":
                return 1  # still alive
            return 0  # expired

        redis.exists = AsyncMock(side_effect=_exists)
        store = DepsStateStore(redis_client=redis)

        removed = await store.cleanup_expired()

        assert removed == 1
        # srem should have been called for the expired entry
        srem_calls = [c for c in redis.srem.call_args_list if c[0][0] == "deps:state:tracking"]
        assert len(srem_calls) == 1

    async def test_cleanup_expired_returns_zero_when_redis_none(
        self,
    ) -> None:
        """cleanup_expired with no redis should return 0."""
        store = DepsStateStore(redis_client=None)
        assert await store.cleanup_expired() == 0

    async def test_cleanup_expired_returns_zero_when_all_alive(
        self,
    ) -> None:
        """When all keys still exist, nothing should be removed."""
        redis = _mock_redis()
        redis.smembers = AsyncMock(return_value={"p1:s1"})
        redis.exists = AsyncMock(return_value=1)
        store = DepsStateStore(redis_client=redis)

        removed = await store.cleanup_expired()

        assert removed == 0
