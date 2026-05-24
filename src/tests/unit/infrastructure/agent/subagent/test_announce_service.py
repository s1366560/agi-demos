"""Tests for AnnounceService."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.domain.model.agent.announce_config import AnnounceConfig
from src.infrastructure.agent.subagent.announce_service import (
    AnnounceService,
    ErrorCategory,
)


def _make_service(
    *,
    xadd_side_effect: list[Exception | None] | None = None,
    config: AnnounceConfig | None = None,
) -> tuple[AnnounceService, AsyncMock]:
    redis = AsyncMock()
    if xadd_side_effect is not None:
        results: list[Exception | AsyncMock] = []
        for effect in xadd_side_effect:
            if effect is None:
                results.append(AsyncMock(return_value="1-0"))
            else:
                results.append(effect)
        redis.xadd.side_effect = results
    else:
        redis.xadd.return_value = "1-0"

    svc = AnnounceService(redis_client=redis, config=config)
    return svc, redis


_CALL_KWARGS = {
    "agent_id": "agent-1",
    "parent_session_id": "parent-sess",
    "child_session_id": "child-sess",
    "result_content": "done",
    "success": True,
    "event_count": 5,
    "execution_time_ms": 123.456,
}


@pytest.mark.unit
class TestAnnounceService:
    async def test_publish_announce_success(self) -> None:
        svc, redis = _make_service()

        result = await svc.publish_announce(**_CALL_KWARGS)

        assert result is True
        redis.xadd.assert_awaited_once()
        stream_key = redis.xadd.call_args[0][0]
        assert stream_key == "agent:messages:parent-sess"

    async def test_publish_announce_payload_format(self) -> None:
        svc, redis = _make_service()

        await svc.publish_announce(**_CALL_KWARGS)

        call_args = redis.xadd.call_args[0]
        envelope: dict[str, str] = call_args[1]
        message_data = json.loads(envelope["data"])

        assert message_data["from_agent_id"] == "agent-1"
        assert message_data["to_agent_id"] == ""
        assert message_data["session_id"] == "parent-sess"
        assert message_data["message_type"] == "announce"
        assert message_data["parent_message_id"] is None
        assert "message_id" in message_data
        assert "timestamp" in message_data

        content = json.loads(message_data["content"])
        assert content["agent_id"] == "agent-1"
        assert content["session_id"] == "child-sess"
        assert content["result"] == "done"
        assert content["artifacts"] == []
        assert content["success"] is True
        assert content["metadata"]["event_count"] == 5
        assert content["metadata"]["execution_time_ms"] == 123.46

        metadata = message_data["metadata"]
        assert "announce_payload" in metadata
        assert metadata["announce_payload"] == content

    async def test_publish_announce_truncates_result(self) -> None:
        svc, redis = _make_service()
        long_result = "x" * 1000

        await svc.publish_announce(
            agent_id="a",
            parent_session_id="p",
            child_session_id="c",
            result_content=long_result,
            success=True,
        )

        message_data = json.loads(redis.xadd.call_args[0][1]["data"])
        content = json.loads(message_data["content"])
        assert len(content["result"]) == 500

    async def test_publish_announce_transient_error_retries(self) -> None:
        config = AnnounceConfig(max_retries=3, retry_delay_ms=0)
        svc, redis = _make_service(
            xadd_side_effect=[ConnectionError("conn lost"), None],
            config=config,
        )

        result = await svc.publish_announce(**_CALL_KWARGS)

        assert result is True
        assert redis.xadd.await_count == 2

        events = svc.consume_pending_events()
        assert len(events) == 1
        assert events[0].attempt == 1
        assert events[0].error_category == "transient"

    async def test_publish_announce_permanent_error_no_retry(self) -> None:
        svc, redis = _make_service(
            xadd_side_effect=[ValueError("bad data")],
        )

        result = await svc.publish_announce(**_CALL_KWARGS)

        assert result is False
        assert redis.xadd.await_count == 1
        assert svc.consume_pending_events() == []

    async def test_publish_announce_unknown_error_retry_once(self) -> None:
        config = AnnounceConfig(max_retries=5, retry_delay_ms=0)
        svc, redis = _make_service(
            xadd_side_effect=[
                RuntimeError("mysterious"),
                RuntimeError("still mysterious"),
            ],
            config=config,
        )

        result = await svc.publish_announce(**_CALL_KWARGS)

        assert result is False
        assert redis.xadd.await_count == 2

        events = svc.consume_pending_events()
        assert len(events) == 1
        assert events[0].error_category == "unknown"

    async def test_publish_announce_all_retries_exhausted(self) -> None:
        config = AnnounceConfig(max_retries=2, retry_delay_ms=0)
        svc, redis = _make_service(
            xadd_side_effect=[
                ConnectionError("fail 1"),
                ConnectionError("fail 2"),
                ConnectionError("fail 3"),
            ],
            config=config,
        )

        result = await svc.publish_announce(**_CALL_KWARGS)

        assert result is False
        assert redis.xadd.await_count == 3

        events = svc.consume_pending_events()
        assert len(events) == 2
        assert events[0].attempt == 1
        assert events[1].attempt == 2

    async def test_classify_error_categories(self) -> None:
        assert AnnounceService.classify_error(ConnectionError()) == ErrorCategory.TRANSIENT
        assert AnnounceService.classify_error(TimeoutError()) == ErrorCategory.TRANSIENT
        assert AnnounceService.classify_error(OSError()) == ErrorCategory.TRANSIENT

        assert AnnounceService.classify_error(ValueError()) == ErrorCategory.PERMANENT
        assert AnnounceService.classify_error(TypeError()) == ErrorCategory.PERMANENT
        assert AnnounceService.classify_error(KeyError()) == ErrorCategory.PERMANENT

        assert AnnounceService.classify_error(RuntimeError()) == ErrorCategory.UNKNOWN
        assert AnnounceService.classify_error(Exception()) == ErrorCategory.UNKNOWN

    async def test_consume_pending_events(self) -> None:
        config = AnnounceConfig(max_retries=2, retry_delay_ms=0)
        svc, _ = _make_service(
            xadd_side_effect=[ConnectionError("oops"), None],
            config=config,
        )

        await svc.publish_announce(**_CALL_KWARGS)

        events = svc.consume_pending_events()
        assert len(events) == 1
        assert events[0].agent_id == "agent-1"
        assert events[0].session_id == "child-sess"

        assert svc.consume_pending_events() == []
