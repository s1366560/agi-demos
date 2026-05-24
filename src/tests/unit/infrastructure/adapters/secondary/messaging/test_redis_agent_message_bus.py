from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.domain.ports.services.agent_message_bus_port import AgentMessageType
from src.infrastructure.adapters.secondary.messaging.redis_agent_message_bus import (
    RedisAgentMessageBusAdapter,
)


@pytest.mark.unit
class TestRedisAgentMessageBusParsing:
    def test_parse_canonical_data_payload_attaches_stream_id(self) -> None:
        adapter = RedisAgentMessageBusAdapter(AsyncMock())
        payload = {
            "message_id": "msg-1",
            "from_agent_id": "agent-a",
            "to_agent_id": "agent-b",
            "session_id": "sess-1",
            "content": "hello",
            "message_type": "request",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "metadata": {"correlation_id": "corr-1"},
            "parent_message_id": None,
        }

        message = adapter._parse_stream_message("10-0", {"data": json.dumps(payload)})

        assert message is not None
        assert message.stream_id == "10-0"
        assert message.message_id == "msg-1"
        assert message.message_type == AgentMessageType.REQUEST
        assert message.metadata == {"correlation_id": "corr-1"}

    def test_parse_legacy_raw_announce_payload(self) -> None:
        adapter = RedisAgentMessageBusAdapter(AsyncMock())
        announce_payload = {
            "agent_id": "child-agent",
            "session_id": "child-session",
            "result": "done",
            "artifacts": [],
            "success": True,
            "metadata": {},
        }
        fields = {
            b"message_id": b"msg-legacy",
            b"from_agent_id": b"child-agent",
            b"to_agent_id": b"",
            b"session_id": b"parent-session",
            b"content": json.dumps(announce_payload).encode("utf-8"),
            b"message_type": b"announce",
            b"timestamp": b"2026-01-01T00:00:00+00:00",
            b"metadata": json.dumps({"announce_payload": announce_payload}).encode("utf-8"),
            b"parent_message_id": b"",
        }

        message = adapter._parse_stream_message(b"11-0", fields)

        assert message is not None
        assert message.stream_id == "11-0"
        assert message.message_id == "msg-legacy"
        assert message.message_type == AgentMessageType.ANNOUNCE
        assert message.parent_message_id is None
        assert message.metadata == {"announce_payload": announce_payload}
