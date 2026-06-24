import logging
from unittest.mock import AsyncMock, Mock

import pytest
import redis.asyncio as redis

from src.infrastructure.adapters.secondary.messaging.redis_hitl_message_bus import (
    RedisHITLMessageBusAdapter,
)

LOGGER_NAME = "src.infrastructure.adapters.secondary.messaging.redis_hitl_message_bus"


@pytest.mark.unit
class TestRedisHITLMessageBusLogging:
    @pytest.mark.asyncio
    async def test_publish_response_success_log_redacts_request_id_and_response_key(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        redis_client = Mock()
        redis_client.xadd = AsyncMock(return_value="123-0")
        adapter = RedisHITLMessageBusAdapter(redis_client)  # type: ignore[arg-type]
        secret_request_id = "hitl-secret-request-2468"
        secret_response_key = "secret-decision-key"

        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            message_id = await adapter.publish_response(
                request_id=secret_request_id,
                response_key=secret_response_key,
                response_value="approved",
            )

        assert message_id == "123-0"
        assert "Published response" in caplog.text
        assert secret_request_id not in caplog.text
        assert secret_response_key not in caplog.text
        assert "message_id=123-0" in caplog.text
        assert "has_request_id=True" in caplog.text
        assert "has_response_key=True" in caplog.text

    @pytest.mark.asyncio
    async def test_publish_response_error_log_redacts_request_id_and_exception_text(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        redis_client = Mock()
        redis_client.xadd = AsyncMock(side_effect=RuntimeError("redis secret unavailable"))
        adapter = RedisHITLMessageBusAdapter(redis_client)  # type: ignore[arg-type]
        secret_request_id = "hitl-secret-request-1357"

        with caplog.at_level(logging.ERROR, logger=LOGGER_NAME), pytest.raises(RuntimeError):
            await adapter.publish_response(
                request_id=secret_request_id,
                response_key="decision",
                response_value="approved",
            )

        assert "Failed to publish" in caplog.text
        assert secret_request_id not in caplog.text
        assert "redis secret unavailable" not in caplog.text
        assert "error_type=RuntimeError" in caplog.text
        assert "has_request_id=True" in caplog.text

    @pytest.mark.asyncio
    async def test_acknowledge_success_log_redacts_request_id_and_group(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        redis_client = Mock()
        redis_client.xack = AsyncMock(return_value=2)
        adapter = RedisHITLMessageBusAdapter(redis_client)  # type: ignore[arg-type]
        secret_request_id = "hitl-secret-request-9753"
        secret_consumer_group = "secret-consumer-group"

        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            acked = await adapter.acknowledge(
                request_id=secret_request_id,
                consumer_group=secret_consumer_group,
                message_ids=["1-0", "2-0"],
            )

        assert acked == 2
        assert "Acknowledged messages" in caplog.text
        assert secret_request_id not in caplog.text
        assert secret_consumer_group not in caplog.text
        assert "acked=2" in caplog.text
        assert "message_count=2" in caplog.text
        assert "has_request_id=True" in caplog.text
        assert "has_consumer_group=True" in caplog.text

    @pytest.mark.asyncio
    async def test_acknowledge_error_log_redacts_request_id_group_and_exception_text(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        redis_client = Mock()
        redis_client.xack = AsyncMock(side_effect=RuntimeError("redis secret unavailable"))
        adapter = RedisHITLMessageBusAdapter(redis_client)  # type: ignore[arg-type]
        secret_request_id = "hitl-secret-request-8642"
        secret_consumer_group = "secret-consumer-group"

        with caplog.at_level(logging.ERROR, logger=LOGGER_NAME), pytest.raises(RuntimeError):
            await adapter.acknowledge(
                request_id=secret_request_id,
                consumer_group=secret_consumer_group,
                message_ids=["1-0"],
            )

        assert "Failed to ack messages" in caplog.text
        assert secret_request_id not in caplog.text
        assert secret_consumer_group not in caplog.text
        assert "redis secret unavailable" not in caplog.text
        assert "error_type=RuntimeError" in caplog.text
        assert "has_request_id=True" in caplog.text

    @pytest.mark.asyncio
    async def test_cleanup_stream_delete_log_redacts_request_id(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        redis_client = Mock()
        redis_client.delete = AsyncMock(return_value=1)
        adapter = RedisHITLMessageBusAdapter(redis_client)  # type: ignore[arg-type]
        secret_request_id = "hitl-secret-request-7531"

        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            removed = await adapter.cleanup_stream(secret_request_id)

        assert removed == 0
        assert "Cleaned up stream" in caplog.text
        assert secret_request_id not in caplog.text
        assert "operation=delete" in caplog.text
        assert "has_request_id=True" in caplog.text

    @pytest.mark.asyncio
    async def test_cleanup_stream_trim_log_redacts_request_id(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        redis_client = Mock()
        redis_client.xtrim = AsyncMock(return_value=7)
        adapter = RedisHITLMessageBusAdapter(redis_client)  # type: ignore[arg-type]
        secret_request_id = "hitl-secret-request-6420"

        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            removed = await adapter.cleanup_stream(secret_request_id, max_len=25)

        assert removed == 7
        assert "Cleaned up stream" in caplog.text
        assert secret_request_id not in caplog.text
        assert "operation=trim" in caplog.text
        assert "removed=7" in caplog.text
        assert "max_len=25" in caplog.text
        assert "has_request_id=True" in caplog.text

    @pytest.mark.asyncio
    async def test_cleanup_stream_error_log_redacts_request_id_and_exception_text(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        redis_client = Mock()
        redis_client.delete = AsyncMock(side_effect=RuntimeError("redis secret unavailable"))
        adapter = RedisHITLMessageBusAdapter(redis_client)  # type: ignore[arg-type]
        secret_request_id = "hitl-secret-request-5310"

        with caplog.at_level(logging.ERROR, logger=LOGGER_NAME), pytest.raises(RuntimeError):
            await adapter.cleanup_stream(secret_request_id)

        assert "Failed to cleanup" in caplog.text
        assert secret_request_id not in caplog.text
        assert "redis secret unavailable" not in caplog.text
        assert "error_type=RuntimeError" in caplog.text
        assert "has_request_id=True" in caplog.text

    @pytest.mark.asyncio
    async def test_stream_exists_error_log_redacts_request_id_and_exception_text(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        redis_client = Mock()
        redis_client.exists = AsyncMock(side_effect=RuntimeError("redis secret unavailable"))
        adapter = RedisHITLMessageBusAdapter(redis_client)  # type: ignore[arg-type]
        secret_request_id = "hitl-secret-request-4200"

        with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
            exists = await adapter.stream_exists(secret_request_id)

        assert exists is False
        assert "Failed to check stream existence" in caplog.text
        assert secret_request_id not in caplog.text
        assert "redis secret unavailable" not in caplog.text
        assert "error_type=RuntimeError" in caplog.text
        assert "has_request_id=True" in caplog.text

    @pytest.mark.asyncio
    async def test_create_consumer_group_success_log_redacts_request_id_and_group(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        redis_client = Mock()
        redis_client.xgroup_create = AsyncMock(return_value=True)
        adapter = RedisHITLMessageBusAdapter(redis_client)  # type: ignore[arg-type]
        secret_request_id = "hitl-secret-request-3100"
        secret_consumer_group = "secret-consumer-group"

        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            created = await adapter.create_consumer_group(
                request_id=secret_request_id,
                consumer_group=secret_consumer_group,
                start_from_latest=False,
            )

        assert created is True
        assert "Created consumer group" in caplog.text
        assert secret_request_id not in caplog.text
        assert secret_consumer_group not in caplog.text
        assert "start_from_latest=False" in caplog.text
        assert "has_request_id=True" in caplog.text
        assert "has_consumer_group=True" in caplog.text

    @pytest.mark.asyncio
    async def test_create_consumer_group_busy_log_redacts_request_id_and_group(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        redis_client = Mock()
        redis_client.xgroup_create = AsyncMock(
            side_effect=redis.ResponseError("BUSYGROUP secret group already exists")
        )
        adapter = RedisHITLMessageBusAdapter(redis_client)  # type: ignore[arg-type]
        secret_request_id = "hitl-secret-request-3110"
        secret_consumer_group = "secret-consumer-group"

        with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
            created = await adapter.create_consumer_group(
                request_id=secret_request_id,
                consumer_group=secret_consumer_group,
            )

        assert created is True
        assert "Consumer group already exists" in caplog.text
        assert secret_request_id not in caplog.text
        assert secret_consumer_group not in caplog.text
        assert "secret group already exists" not in caplog.text
        assert "has_request_id=True" in caplog.text
        assert "has_consumer_group=True" in caplog.text

    @pytest.mark.asyncio
    async def test_create_consumer_group_error_log_redacts_request_id_group_and_exception_text(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        redis_client = Mock()
        redis_client.xgroup_create = AsyncMock(
            side_effect=redis.ResponseError("ERR secret backend unavailable")
        )
        adapter = RedisHITLMessageBusAdapter(redis_client)  # type: ignore[arg-type]
        secret_request_id = "hitl-secret-request-3120"
        secret_consumer_group = "secret-consumer-group"

        with caplog.at_level(logging.ERROR, logger=LOGGER_NAME), pytest.raises(redis.ResponseError):
            await adapter.create_consumer_group(
                request_id=secret_request_id,
                consumer_group=secret_consumer_group,
            )

        assert "Failed to create group" in caplog.text
        assert secret_request_id not in caplog.text
        assert secret_consumer_group not in caplog.text
        assert "secret backend unavailable" not in caplog.text
        assert "error_type=ResponseError" in caplog.text
        assert "has_request_id=True" in caplog.text
        assert "has_consumer_group=True" in caplog.text

    @pytest.mark.asyncio
    async def test_get_pending_messages_error_log_redacts_request_id_group_and_exception_text(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        redis_client = Mock()
        redis_client.xpending_range = AsyncMock(
            side_effect=RuntimeError("redis secret unavailable")
        )
        adapter = RedisHITLMessageBusAdapter(redis_client)  # type: ignore[arg-type]
        secret_request_id = "hitl-secret-request-3130"
        secret_consumer_group = "secret-consumer-group"

        with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
            messages = await adapter.get_pending_messages(
                request_id=secret_request_id,
                consumer_group=secret_consumer_group,
                count=3,
            )

        assert messages == []
        assert "Failed to get pending messages" in caplog.text
        assert secret_request_id not in caplog.text
        assert secret_consumer_group not in caplog.text
        assert "redis secret unavailable" not in caplog.text
        assert "error_type=RuntimeError" in caplog.text
        assert "count=3" in caplog.text
        assert "has_request_id=True" in caplog.text
        assert "has_consumer_group=True" in caplog.text

    @pytest.mark.asyncio
    async def test_claim_pending_messages_success_log_redacts_request_group_and_consumer(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        redis_client = Mock()
        redis_client.xclaim = AsyncMock(return_value=[])
        adapter = RedisHITLMessageBusAdapter(redis_client)  # type: ignore[arg-type]
        secret_request_id = "hitl-secret-request-3140"
        secret_consumer_group = "secret-consumer-group"
        secret_consumer_name = "secret-consumer-name"

        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            messages = await adapter.claim_pending_messages(
                request_id=secret_request_id,
                consumer_group=secret_consumer_group,
                consumer_name=secret_consumer_name,
                min_idle_ms=1000,
                message_ids=["1-0", "2-0"],
            )

        assert messages == []
        assert "Claimed pending messages" in caplog.text
        assert secret_request_id not in caplog.text
        assert secret_consumer_group not in caplog.text
        assert secret_consumer_name not in caplog.text
        assert "claimed=0" in caplog.text
        assert "message_count=2" in caplog.text
        assert "has_request_id=True" in caplog.text
        assert "has_consumer_group=True" in caplog.text
        assert "has_consumer_name=True" in caplog.text

    @pytest.mark.asyncio
    async def test_claim_pending_messages_error_log_redacts_request_group_consumer_and_exception(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        redis_client = Mock()
        redis_client.xclaim = AsyncMock(side_effect=RuntimeError("redis secret unavailable"))
        adapter = RedisHITLMessageBusAdapter(redis_client)  # type: ignore[arg-type]
        secret_request_id = "hitl-secret-request-3150"
        secret_consumer_group = "secret-consumer-group"
        secret_consumer_name = "secret-consumer-name"

        with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
            messages = await adapter.claim_pending_messages(
                request_id=secret_request_id,
                consumer_group=secret_consumer_group,
                consumer_name=secret_consumer_name,
                min_idle_ms=1000,
                message_ids=["1-0"],
            )

        assert messages == []
        assert "Failed to claim messages" in caplog.text
        assert secret_request_id not in caplog.text
        assert secret_consumer_group not in caplog.text
        assert secret_consumer_name not in caplog.text
        assert "redis secret unavailable" not in caplog.text
        assert "error_type=RuntimeError" in caplog.text
        assert "message_count=1" in caplog.text
        assert "has_request_id=True" in caplog.text
        assert "has_consumer_group=True" in caplog.text
        assert "has_consumer_name=True" in caplog.text
