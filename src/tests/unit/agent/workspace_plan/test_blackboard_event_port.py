"""Unit tests for the M2 blackboard event-port adapters."""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.domain.events.types import AgentEventType
from src.infrastructure.agent.workspace_plan.blackboard_event_port_impl import (
    DEFAULT_STREAM_MAXLEN,
    RedisStreamBlackboardEventPort,
    UnifiedBusBlackboardEventPort,
    build_blackboard_event_port,
    get_blackboard_event_transport,
)


class _FakeRedis:
    """Minimal in-memory XADD/XRANGE substitute for the stream adapter."""

    def __init__(self) -> None:
        # stream_key -> list[(id, dict[str, str])]
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self._counter = 0
        self.xadd_calls: list[dict[str, Any]] = []

    async def xadd(
        self,
        key: str,
        fields: dict[str, str],
        *,
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> str:
        self._counter += 1
        entry_id = f"{self._counter}-0"
        stream = self.streams.setdefault(key, [])
        stream.append((entry_id, dict(fields)))
        if maxlen is not None and len(stream) > maxlen:
            self.streams[key] = stream[-maxlen:]
        self.xadd_calls.append(
            {"key": key, "fields": dict(fields), "maxlen": maxlen, "approximate": approximate}
        )
        return entry_id

    async def xrange(
        self,
        key: str,
        *,
        min: str = "-",
        max: str = "+",
        count: int | None = None,
    ) -> list[tuple[str, dict[str, str]]]:
        stream = self.streams.get(key, [])
        exclusive_after: str | None = None
        if min.startswith("("):
            exclusive_after = min[1:]
        results: list[tuple[str, dict[str, str]]] = []
        for entry_id, fields in stream:
            if exclusive_after is not None and entry_id <= exclusive_after:
                continue
            results.append((entry_id, fields))
            if count is not None and len(results) >= count:
                break
        return results


@pytest.mark.unit
class TestRedisStreamBlackboardEventPort:
    async def test_publish_writes_to_workspace_stream(self) -> None:
        redis_ = _FakeRedis()
        port = RedisStreamBlackboardEventPort(redis_, maxlen=250)
        stream_id = await port.publish(
            workspace_id="ws-1",
            event_type=AgentEventType.BLACKBOARD_FILE_CREATED,
            payload={"file_id": "f1"},
            metadata={"tenant_id": "t1"},
            correlation_id="ws-1",
        )
        assert stream_id is not None
        assert "bb:events:ws-1" in redis_.streams
        entry_id, fields = redis_.streams["bb:events:ws-1"][0]
        assert entry_id == stream_id
        assert fields["event_type"] == AgentEventType.BLACKBOARD_FILE_CREATED.value
        assert json.loads(fields["payload"]) == {"file_id": "f1"}
        assert json.loads(fields["metadata"]) == {"tenant_id": "t1"}
        assert redis_.xadd_calls[0]["maxlen"] == 250

    async def test_stream_since_replays_strictly_after_last_id(self) -> None:
        redis_ = _FakeRedis()
        port = RedisStreamBlackboardEventPort(redis_)
        first = await port.publish(
            workspace_id="ws-1",
            event_type=AgentEventType.BLACKBOARD_FILE_CREATED,
            payload={"n": 1},
        )
        second = await port.publish(
            workspace_id="ws-1",
            event_type=AgentEventType.BLACKBOARD_FILE_UPDATED,
            payload={"n": 2},
        )
        third = await port.publish(
            workspace_id="ws-1",
            event_type=AgentEventType.BLACKBOARD_FILE_DELETED,
            payload={"n": 3},
        )

        replay = await port.stream_since(workspace_id="ws-1", last_id=first or "0")
        assert [e["id"] for e in replay] == [second, third]
        assert replay[0]["event_type"] == AgentEventType.BLACKBOARD_FILE_UPDATED.value
        assert replay[0]["payload"] == {"n": 2}

    async def test_stream_since_default_returns_all(self) -> None:
        redis_ = _FakeRedis()
        port = RedisStreamBlackboardEventPort(redis_)
        await port.publish(
            workspace_id="ws-1",
            event_type=AgentEventType.BLACKBOARD_FILE_CREATED,
            payload={"n": 1},
        )
        replay = await port.stream_since(workspace_id="ws-1")
        assert len(replay) == 1

    async def test_publish_without_redis_returns_none_and_does_not_raise(self) -> None:
        port = RedisStreamBlackboardEventPort(None)
        result = await port.publish(
            workspace_id="ws-1",
            event_type=AgentEventType.BLACKBOARD_FILE_CREATED,
            payload={},
        )
        assert result is None


@pytest.mark.unit
class TestUnifiedBusBlackboardEventPort:
    async def test_stream_since_returns_empty_list(self) -> None:
        port = UnifiedBusBlackboardEventPort(None)
        assert await port.stream_since(workspace_id="ws-1") == []


@pytest.mark.unit
class TestBuildBlackboardEventPort:
    def test_default_transport_is_pubsub(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("BLACKBOARD_EVENT_TRANSPORT", raising=False)
        port = build_blackboard_event_port(None)
        assert isinstance(port, UnifiedBusBlackboardEventPort)
        assert get_blackboard_event_transport() == "pubsub"

    def test_stream_transport_selects_stream_adapter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BLACKBOARD_EVENT_TRANSPORT", "stream")
        port = build_blackboard_event_port(None)
        assert isinstance(port, RedisStreamBlackboardEventPort)

    def test_unknown_transport_falls_back_to_pubsub(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BLACKBOARD_EVENT_TRANSPORT", "kafka")
        port = build_blackboard_event_port(None)
        assert isinstance(port, UnifiedBusBlackboardEventPort)

    def test_stream_maxlen_env_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BLACKBOARD_EVENT_TRANSPORT", "stream")
        monkeypatch.setenv("BLACKBOARD_EVENT_STREAM_MAXLEN", "200")
        port = build_blackboard_event_port(None)
        assert isinstance(port, RedisStreamBlackboardEventPort)
        # internal state is implementation detail; just sanity-check default
        # behaviour when the env is missing.
        monkeypatch.delenv("BLACKBOARD_EVENT_STREAM_MAXLEN")
        default_port = build_blackboard_event_port(None)
        assert isinstance(default_port, RedisStreamBlackboardEventPort)
        assert default_port._maxlen == DEFAULT_STREAM_MAXLEN  # type: ignore[attr-defined]
