from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, Mock

import pytest

from src.domain.ports.services.agent_message_bus_port import AgentMessageType
from src.infrastructure.adapters.secondary.messaging.redis_agent_message_bus import (
    RedisAgentMessageBusAdapter,
)

LOGGER_NAME = "src.infrastructure.adapters.secondary.messaging.redis_agent_message_bus"


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


@pytest.mark.unit
class TestRedisAgentMessageBusLogging:
    @pytest.mark.asyncio
    async def test_send_message_success_log_redacts_session_and_agent_ids(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        redis_client = Mock()
        redis_client.xadd = AsyncMock(return_value="123-0")
        adapter = RedisAgentMessageBusAdapter(redis_client)  # type: ignore[arg-type]
        secret_session_id = "session-secret-2468"
        secret_from_agent_id = "agent-secret-from"
        secret_to_agent_id = "agent-secret-to"

        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            message_id = await adapter.send_message(
                from_agent_id=secret_from_agent_id,
                to_agent_id=secret_to_agent_id,
                session_id=secret_session_id,
                content="hello",
                message_type=AgentMessageType.REQUEST,
            )

        assert message_id
        assert "[AgentMessageBus] Sent message" in caplog.text
        assert secret_session_id not in caplog.text
        assert secret_from_agent_id not in caplog.text
        assert secret_to_agent_id not in caplog.text
        assert "stream_id=123-0" in caplog.text
        assert "type=request" in caplog.text
        assert "has_session_id=True" in caplog.text
        assert "has_from_agent_id=True" in caplog.text
        assert "has_to_agent_id=True" in caplog.text

    @pytest.mark.asyncio
    async def test_send_message_error_log_redacts_session_id_and_exception_text(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        redis_client = Mock()
        redis_client.xadd = AsyncMock(side_effect=RuntimeError("redis secret unavailable"))
        adapter = RedisAgentMessageBusAdapter(redis_client)  # type: ignore[arg-type]
        secret_session_id = "session-secret-1357"

        with caplog.at_level(logging.ERROR, logger=LOGGER_NAME), pytest.raises(RuntimeError):
            await adapter.send_message(
                from_agent_id="agent-a",
                to_agent_id="agent-b",
                session_id=secret_session_id,
                content="hello",
                message_type=AgentMessageType.REQUEST,
            )

        assert "Failed to send" in caplog.text
        assert secret_session_id not in caplog.text
        assert "redis secret unavailable" not in caplog.text
        assert "error_type=RuntimeError" in caplog.text
        assert "has_session_id=True" in caplog.text

    @pytest.mark.asyncio
    async def test_receive_messages_error_log_redacts_session_id(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        redis_client = Mock()
        redis_client.xrange = AsyncMock(side_effect=RuntimeError("redis secret unavailable"))
        adapter = RedisAgentMessageBusAdapter(redis_client)  # type: ignore[arg-type]
        secret_session_id = "session-secret-9753"

        with caplog.at_level(logging.ERROR, logger=LOGGER_NAME), pytest.raises(RuntimeError):
            await adapter.receive_messages("agent-a", secret_session_id)

        assert "Failed to receive" in caplog.text
        assert secret_session_id not in caplog.text
        assert "redis secret unavailable" not in caplog.text
        assert "error_type=RuntimeError" in caplog.text
        assert "has_session_id=True" in caplog.text

    @pytest.mark.asyncio
    async def test_subscribe_messages_error_log_redacts_session_id(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        redis_client = Mock()
        redis_client.xread = AsyncMock(side_effect=RuntimeError("redis secret unavailable"))
        adapter = RedisAgentMessageBusAdapter(redis_client)  # type: ignore[arg-type]
        secret_session_id = "session-secret-8642"

        stream = adapter.subscribe_messages("agent-a", secret_session_id, timeout_ms=1)
        with caplog.at_level(logging.ERROR, logger=LOGGER_NAME), pytest.raises(RuntimeError):
            await anext(stream)

        assert "Error reading" in caplog.text
        assert secret_session_id not in caplog.text
        assert "redis secret unavailable" not in caplog.text
        assert "error_type=RuntimeError" in caplog.text
        assert "has_session_id=True" in caplog.text

    @pytest.mark.asyncio
    async def test_get_message_history_error_log_redacts_session_id(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        redis_client = Mock()
        redis_client.xrevrange = AsyncMock(side_effect=RuntimeError("redis secret unavailable"))
        adapter = RedisAgentMessageBusAdapter(redis_client)  # type: ignore[arg-type]
        secret_session_id = "session-secret-7531"

        with caplog.at_level(logging.ERROR, logger=LOGGER_NAME), pytest.raises(RuntimeError):
            await adapter.get_message_history(secret_session_id)

        assert "Failed to get history" in caplog.text
        assert secret_session_id not in caplog.text
        assert "redis secret unavailable" not in caplog.text
        assert "error_type=RuntimeError" in caplog.text
        assert "has_session_id=True" in caplog.text

    @pytest.mark.asyncio
    async def test_cleanup_session_logs_redact_session_id(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        redis_client = Mock()
        redis_client.delete = AsyncMock(return_value=1)
        adapter = RedisAgentMessageBusAdapter(redis_client)  # type: ignore[arg-type]
        secret_session_id = "session-secret-6420"

        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            await adapter.cleanup_session(secret_session_id)

        assert "Cleaned up stream" in caplog.text
        assert secret_session_id not in caplog.text
        assert "has_session_id=True" in caplog.text

    @pytest.mark.asyncio
    async def test_session_has_messages_error_log_redacts_session_id(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        redis_client = Mock()
        redis_client.exists = AsyncMock(side_effect=RuntimeError("redis secret unavailable"))
        adapter = RedisAgentMessageBusAdapter(redis_client)  # type: ignore[arg-type]
        secret_session_id = "session-secret-5310"

        with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
            has_messages = await adapter.session_has_messages(secret_session_id)

        assert has_messages is False
        assert "Failed to check existence" in caplog.text
        assert secret_session_id not in caplog.text
        assert "redis secret unavailable" not in caplog.text
        assert "error_type=RuntimeError" in caplog.text
        assert "has_session_id=True" in caplog.text
