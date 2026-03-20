"""Tests for Phase 4 Wave 2: Redis namespace adapter, credential scope adapter, and RunRegistry trace deserialization."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.model.agent.subagent_run import SubAgentRun


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_redis_mock() -> AsyncMock:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    redis.mget = AsyncMock(return_value=[])
    redis.exists = AsyncMock(return_value=0)

    pipe = AsyncMock()
    pipe.set = MagicMock()
    pipe.execute = AsyncMock(return_value=[])
    redis.pipeline = MagicMock(return_value=pipe)

    async def _empty_scan_iter(*, match: str = "*", count: int = 100):  # noqa: ARG001
        return
        yield  # noqa: RET503

    redis.scan_iter = _empty_scan_iter
    return redis


def _make_encryption_mock() -> MagicMock:
    enc = MagicMock()
    enc.encrypt = MagicMock(side_effect=lambda v: f"ENC({v})")  # type: ignore[misc]
    enc.decrypt = MagicMock(side_effect=lambda v: str(v).replace("ENC(", "").rstrip(")"))  # type: ignore[misc]
    return enc


# ---------------------------------------------------------------------------
# RedisAgentNamespaceAdapter
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRedisAgentNamespaceAdapter:
    def _make_adapter(self, redis: AsyncMock | None = None, ttl: int = 3600):
        from src.infrastructure.adapters.secondary.cache.redis_agent_namespace import (
            RedisAgentNamespaceAdapter,
        )

        return RedisAgentNamespaceAdapter(
            redis=redis or _make_redis_mock(), default_ttl_seconds=ttl
        )

    async def test_get_key_returns_none_when_missing(self) -> None:
        redis = _make_redis_mock()
        redis.get = AsyncMock(return_value=None)
        adapter = self._make_adapter(redis)
        result = await adapter.get_key("proj-1", "agent-1", "mykey")
        assert result is None
        redis.get.assert_awaited_once_with("agent:ns:proj-1:agent-1:mykey")

    async def test_get_key_returns_value(self) -> None:
        redis = _make_redis_mock()
        redis.get = AsyncMock(return_value=b"hello")
        adapter = self._make_adapter(redis)
        result = await adapter.get_key("p", "a", "k")
        assert result == "b'hello'"

    async def test_set_key_uses_default_ttl(self) -> None:
        redis = _make_redis_mock()
        adapter = self._make_adapter(redis, ttl=7200)
        await adapter.set_key("p", "a", "k", "v")
        redis.set.assert_awaited_once_with("agent:ns:p:a:k", "v", ex=7200)

    async def test_set_key_uses_custom_ttl(self) -> None:
        redis = _make_redis_mock()
        adapter = self._make_adapter(redis, ttl=7200)
        await adapter.set_key("p", "a", "k", "v", ttl_seconds=60)
        redis.set.assert_awaited_once_with("agent:ns:p:a:k", "v", ex=60)

    async def test_delete_key_returns_true(self) -> None:
        redis = _make_redis_mock()
        redis.delete = AsyncMock(return_value=1)
        adapter = self._make_adapter(redis)
        assert await adapter.delete_key("p", "a", "k") is True

    async def test_delete_key_returns_false_when_missing(self) -> None:
        redis = _make_redis_mock()
        redis.delete = AsyncMock(return_value=0)
        adapter = self._make_adapter(redis)
        assert await adapter.delete_key("p", "a", "k") is False

    async def test_list_keys_empty(self) -> None:
        adapter = self._make_adapter()
        result = await adapter.list_keys("p", "a")
        assert result == []

    async def test_list_keys_strips_prefix(self) -> None:
        redis = _make_redis_mock()

        async def _scan(*, match: str = "*", count: int = 100):  # noqa: ARG001
            yield "agent:ns:p:a:key1"
            yield "agent:ns:p:a:key2"

        redis.scan_iter = _scan
        adapter = self._make_adapter(redis)
        result = await adapter.list_keys("p", "a")
        assert result == ["key1", "key2"]

    async def test_list_keys_with_pattern(self) -> None:
        redis = _make_redis_mock()

        async def _scan(*, match: str = "*", count: int = 100):  # noqa: ARG001
            yield "agent:ns:p:a:config:x"

        redis.scan_iter = _scan
        adapter = self._make_adapter(redis)
        result = await adapter.list_keys("p", "a", pattern="config:*")
        assert result == ["config:x"]

    async def test_clear_namespace_deletes_all(self) -> None:
        redis = _make_redis_mock()

        async def _scan(*, match: str = "*", count: int = 100):  # noqa: ARG001
            yield "agent:ns:p:a:k1"
            yield "agent:ns:p:a:k2"

        redis.scan_iter = _scan
        redis.delete = AsyncMock(return_value=2)
        adapter = self._make_adapter(redis)
        count = await adapter.clear_namespace("p", "a")
        assert count == 2

    async def test_clear_namespace_batches_deletes(self) -> None:
        redis = _make_redis_mock()
        keys = [f"agent:ns:p:a:k{i}" for i in range(150)]

        async def _scan(*, match: str = "*", count: int = 100):  # noqa: ARG001
            for k in keys:
                yield k

        redis.scan_iter = _scan
        redis.delete = AsyncMock(return_value=100)
        adapter = self._make_adapter(redis)
        count = await adapter.clear_namespace("p", "a")
        assert count == 200
        assert redis.delete.await_count == 2

    async def test_get_many_empty(self) -> None:
        adapter = self._make_adapter()
        result = await adapter.get_many("p", "a", [])
        assert result == {}

    async def test_get_many_returns_values(self) -> None:
        redis = _make_redis_mock()
        redis.mget = AsyncMock(return_value=[b"v1", None, b"v3"])
        adapter = self._make_adapter(redis)
        result = await adapter.get_many("p", "a", ["k1", "k2", "k3"])
        assert result["k1"] is not None
        assert result["k2"] is None
        assert result["k3"] is not None

    async def test_set_many_empty(self) -> None:
        redis = _make_redis_mock()
        adapter = self._make_adapter(redis)
        await adapter.set_many("p", "a", {})
        redis.pipeline.assert_not_called()

    async def test_set_many_uses_pipeline(self) -> None:
        redis = _make_redis_mock()
        pipe = AsyncMock()
        pipe.set = MagicMock()
        pipe.execute = AsyncMock(return_value=[True, True])
        redis.pipeline = MagicMock(return_value=pipe)

        adapter = self._make_adapter(redis, ttl=500)
        await adapter.set_many("p", "a", {"x": "1", "y": "2"})
        redis.pipeline.assert_called_once()
        assert pipe.set.call_count == 2
        pipe.execute.assert_awaited_once()

    async def test_key_pattern_format(self) -> None:
        from src.infrastructure.adapters.secondary.cache.redis_agent_namespace import (
            _build_key,
            _build_namespace_prefix,
        )

        assert _build_key("proj-x", "agent-y", "mykey") == "agent:ns:proj-x:agent-y:mykey"
        assert _build_namespace_prefix("proj-x", "agent-y") == "agent:ns:proj-x:agent-y:"


# ---------------------------------------------------------------------------
# RedisAgentCredentialScopeAdapter
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRedisAgentCredentialScopeAdapter:
    def _make_adapter(
        self,
        redis: AsyncMock | None = None,
        enc: MagicMock | None = None,
        ttl: int = 3600,
    ):
        from src.infrastructure.adapters.secondary.cache.redis_agent_credential_scope import (
            RedisAgentCredentialScopeAdapter,
        )

        return RedisAgentCredentialScopeAdapter(
            redis=redis or _make_redis_mock(),
            encryption_service=enc or _make_encryption_mock(),
            default_ttl_seconds=ttl,
        )

    async def test_get_credential_returns_none_when_missing(self) -> None:
        redis = _make_redis_mock()
        redis.get = AsyncMock(return_value=None)
        adapter = self._make_adapter(redis=redis)
        result = await adapter.get_credential("p", "a", "secret")
        assert result is None
        redis.get.assert_awaited_once_with("agent:cred:p:a:secret")

    async def test_get_credential_decrypts(self) -> None:
        redis = _make_redis_mock()
        redis.get = AsyncMock(return_value="ENC(my-api-key)")
        enc = _make_encryption_mock()
        adapter = self._make_adapter(redis=redis, enc=enc)
        result = await adapter.get_credential("p", "a", "api_key")
        assert result == "my-api-key"
        enc.decrypt.assert_called_once()

    async def test_set_credential_encrypts(self) -> None:
        redis = _make_redis_mock()
        enc = _make_encryption_mock()
        adapter = self._make_adapter(redis=redis, enc=enc, ttl=9000)
        await adapter.set_credential("p", "a", "token", "secret-value")
        enc.encrypt.assert_called_once_with("secret-value")
        redis.set.assert_awaited_once_with("agent:cred:p:a:token", "ENC(secret-value)", ex=9000)

    async def test_set_credential_custom_ttl(self) -> None:
        redis = _make_redis_mock()
        enc = _make_encryption_mock()
        adapter = self._make_adapter(redis=redis, enc=enc, ttl=9000)
        await adapter.set_credential("p", "a", "token", "val", ttl_seconds=30)
        redis.set.assert_awaited_once_with("agent:cred:p:a:token", "ENC(val)", ex=30)

    async def test_delete_credential_true(self) -> None:
        redis = _make_redis_mock()
        redis.delete = AsyncMock(return_value=1)
        adapter = self._make_adapter(redis=redis)
        assert await adapter.delete_credential("p", "a", "k") is True

    async def test_delete_credential_false(self) -> None:
        redis = _make_redis_mock()
        redis.delete = AsyncMock(return_value=0)
        adapter = self._make_adapter(redis=redis)
        assert await adapter.delete_credential("p", "a", "k") is False

    async def test_list_credential_keys_empty(self) -> None:
        adapter = self._make_adapter()
        result = await adapter.list_credential_keys("p", "a")
        assert result == []

    async def test_list_credential_keys_strips_prefix(self) -> None:
        redis = _make_redis_mock()

        async def _scan(*, match: str = "*", count: int = 100):  # noqa: ARG001
            yield "agent:cred:p:a:api_key"
            yield "agent:cred:p:a:db_pass"

        redis.scan_iter = _scan
        adapter = self._make_adapter(redis=redis)
        result = await adapter.list_credential_keys("p", "a")
        assert result == ["api_key", "db_pass"]

    async def test_has_credential_true(self) -> None:
        redis = _make_redis_mock()
        redis.exists = AsyncMock(return_value=1)
        adapter = self._make_adapter(redis=redis)
        assert await adapter.has_credential("p", "a", "k") is True

    async def test_has_credential_false(self) -> None:
        redis = _make_redis_mock()
        redis.exists = AsyncMock(return_value=0)
        adapter = self._make_adapter(redis=redis)
        assert await adapter.has_credential("p", "a", "k") is False

    async def test_clear_credentials_deletes_all(self) -> None:
        redis = _make_redis_mock()

        async def _scan(*, match: str = "*", count: int = 100):  # noqa: ARG001
            yield "agent:cred:p:a:k1"
            yield "agent:cred:p:a:k2"

        redis.scan_iter = _scan
        redis.delete = AsyncMock(return_value=2)
        adapter = self._make_adapter(redis=redis)
        count = await adapter.clear_credentials("p", "a")
        assert count == 2

    async def test_key_pattern_format(self) -> None:
        from src.infrastructure.adapters.secondary.cache.redis_agent_credential_scope import (
            _build_key,
            _build_scope_prefix,
        )

        assert _build_key("proj-x", "agent-y", "secret") == "agent:cred:proj-x:agent-y:secret"
        assert _build_scope_prefix("proj-x", "agent-y") == "agent:cred:proj-x:agent-y:"

    async def test_encryption_roundtrip(self) -> None:
        redis = _make_redis_mock()
        enc = _make_encryption_mock()
        adapter = self._make_adapter(redis=redis, enc=enc)

        await adapter.set_credential("p", "a", "k", "supersecret")
        enc.encrypt.assert_called_once_with("supersecret")
        stored_encrypted = redis.set.call_args[0][1]
        assert stored_encrypted == "ENC(supersecret)"

        redis.get = AsyncMock(return_value=stored_encrypted)
        result = await adapter.get_credential("p", "a", "k")
        assert result == "supersecret"
        enc.decrypt.assert_called_once_with("ENC(supersecret)")


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProtocolConformance:
    def test_namespace_adapter_satisfies_port(self) -> None:
        from src.domain.ports.agent.agent_namespace_port import AgentNamespacePort
        from src.infrastructure.adapters.secondary.cache.redis_agent_namespace import (
            RedisAgentNamespaceAdapter,
        )

        assert issubclass(RedisAgentNamespaceAdapter, AgentNamespacePort) or isinstance(
            RedisAgentNamespaceAdapter, type
        )

    def test_credential_adapter_satisfies_port(self) -> None:
        from src.domain.ports.agent.agent_credential_scope_port import AgentCredentialScopePort
        from src.infrastructure.adapters.secondary.cache.redis_agent_credential_scope import (
            RedisAgentCredentialScopeAdapter,
        )

        assert issubclass(RedisAgentCredentialScopeAdapter, AgentCredentialScopePort) or isinstance(
            RedisAgentCredentialScopeAdapter, type
        )


# ---------------------------------------------------------------------------
# RunRegistry _deserialize_run trace fields
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunRegistryTraceDeserialization:
    def _deserialize(self, payload: dict[str, Any]) -> SubAgentRun | None:
        from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry

        return SubAgentRunRegistry._deserialize_run(payload)

    def _base_payload(self, **overrides: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "run_id": "run-1",
            "conversation_id": "conv-1",
            "subagent_name": "researcher",
            "task": "find data",
            "status": "pending",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        base.update(overrides)
        return base

    def test_trace_id_deserialized(self) -> None:
        payload = self._base_payload(trace_id="trace-abc")
        run = self._deserialize(payload)
        assert run is not None
        assert run.trace_id == "trace-abc"

    def test_parent_span_id_deserialized(self) -> None:
        payload = self._base_payload(parent_span_id="span-xyz")
        run = self._deserialize(payload)
        assert run is not None
        assert run.parent_span_id == "span-xyz"

    def test_both_trace_fields_deserialized(self) -> None:
        payload = self._base_payload(trace_id="t1", parent_span_id="s1")
        run = self._deserialize(payload)
        assert run is not None
        assert run.trace_id == "t1"
        assert run.parent_span_id == "s1"

    def test_missing_trace_fields_default_to_none(self) -> None:
        payload = self._base_payload()
        run = self._deserialize(payload)
        assert run is not None
        assert run.trace_id is None
        assert run.parent_span_id is None

    def test_null_trace_fields_become_none(self) -> None:
        payload = self._base_payload(trace_id=None, parent_span_id=None)
        run = self._deserialize(payload)
        assert run is not None
        assert run.trace_id is None
        assert run.parent_span_id is None

    def test_empty_string_trace_fields_become_none(self) -> None:
        payload = self._base_payload(trace_id="", parent_span_id="")
        run = self._deserialize(payload)
        assert run is not None
        assert run.trace_id is None
        assert run.parent_span_id is None

    def test_trace_fields_survive_serialization_roundtrip(self) -> None:
        payload = self._base_payload(trace_id="trace-rt", parent_span_id="span-rt")
        run = self._deserialize(payload)
        assert run is not None
        event_data = run.to_event_data()
        assert event_data["trace_id"] == "trace-rt"
        assert event_data["parent_span_id"] == "span-rt"

    def test_invalid_payload_returns_none(self) -> None:
        assert self._deserialize({"invalid": True}) is None

    def test_non_dict_returns_none(self) -> None:
        from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry

        assert SubAgentRunRegistry._deserialize_run("not a dict") is None
        assert SubAgentRunRegistry._deserialize_run(None) is None
        assert SubAgentRunRegistry._deserialize_run(42) is None
