import logging
from unittest.mock import AsyncMock, Mock

import pytest

from src.domain.events.types import AgentEventType
from src.infrastructure.adapters.secondary.messaging.redis_agent_event_bus import (
    RedisAgentEventBusAdapter,
)

LOGGER_NAME = "src.infrastructure.adapters.secondary.messaging.redis_agent_event_bus"


@pytest.mark.unit
class TestRedisAgentEventBusLogging:
    @pytest.mark.asyncio
    async def test_publish_event_success_log_redacts_conversation_and_message(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        redis_client = Mock()
        redis_client.xadd = AsyncMock(return_value="123-0")
        adapter = RedisAgentEventBusAdapter(redis_client)  # type: ignore[arg-type]
        secret_conversation_id = "conversation-secret-8642"
        secret_message_id = "message-secret-7531"

        with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
            event_id = await adapter.publish_event(
                conversation_id=secret_conversation_id,
                message_id=secret_message_id,
                event_type=AgentEventType.THOUGHT,
                data={"content": "hello"},
                event_time_us=123,
                event_counter=1,
            )

        assert event_id == "123-0"
        assert "Published event" in caplog.text
        assert secret_conversation_id not in caplog.text
        assert secret_message_id not in caplog.text
        assert "event_time_us=123" in caplog.text
        assert "type=thought" in caplog.text
        assert "event_id=123-0" in caplog.text
        assert "has_conversation_id=True" in caplog.text
        assert "has_message_id=True" in caplog.text

    @pytest.mark.asyncio
    async def test_publish_event_error_log_redacts_conversation_message_and_exception(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        redis_client = Mock()
        redis_client.xadd = AsyncMock(side_effect=RuntimeError("redis secret unavailable"))
        adapter = RedisAgentEventBusAdapter(redis_client)  # type: ignore[arg-type]
        secret_conversation_id = "conversation-secret-2468"
        secret_message_id = "message-secret-1357"

        with caplog.at_level(logging.ERROR, logger=LOGGER_NAME), pytest.raises(RuntimeError):
            await adapter.publish_event(
                conversation_id=secret_conversation_id,
                message_id=secret_message_id,
                event_type=AgentEventType.THOUGHT,
                data={"content": "hello"},
                event_time_us=123,
                event_counter=1,
            )

        assert "Failed to publish" in caplog.text
        assert secret_conversation_id not in caplog.text
        assert secret_message_id not in caplog.text
        assert "redis secret unavailable" not in caplog.text
        assert "error_type=RuntimeError" in caplog.text
        assert "type=thought" in caplog.text
        assert "has_conversation_id=True" in caplog.text
        assert "has_message_id=True" in caplog.text
