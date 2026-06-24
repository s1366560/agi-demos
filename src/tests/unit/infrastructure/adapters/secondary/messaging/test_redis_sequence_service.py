import logging
from unittest.mock import AsyncMock, Mock

import pytest

from src.infrastructure.adapters.secondary.messaging.redis_sequence_service import (
    RedisSequenceService,
)

LOGGER_NAME = "src.infrastructure.adapters.secondary.messaging.redis_sequence_service"


class _Pipeline:
    def __init__(self, current_value: str | None) -> None:
        self._current_value = current_value

    async def __aenter__(self) -> "_Pipeline":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def watch(self, _key: str) -> None:
        return None

    async def get(self, _key: str) -> str | None:
        return self._current_value

    def multi(self) -> None:
        return None

    def set(self, _key: str, _value: int) -> None:
        return None

    def expire(self, _key: str, _ttl: int) -> None:
        return None

    async def execute(self) -> list[object]:
        return []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_next_sequence_error_log_redacts_conversation_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_conversation_id = "conversation-secret-2468"
    redis_client = Mock()
    redis_client.incr = AsyncMock(side_effect=RuntimeError("redis unavailable"))
    service = RedisSequenceService(redis_client)  # type: ignore[arg-type]

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME), pytest.raises(RuntimeError):
        await service.get_next_sequence(secret_conversation_id)

    assert "Failed to get next sequence" in caplog.text
    assert secret_conversation_id not in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "has_conversation_id=True" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_current_sequence_error_log_redacts_conversation_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_conversation_id = "conversation-secret-1357"
    redis_client = Mock()
    redis_client.get = AsyncMock(side_effect=RuntimeError("redis unavailable"))
    service = RedisSequenceService(redis_client)  # type: ignore[arg-type]

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        current = await service.get_current_sequence(secret_conversation_id)

    assert current == 0
    assert "Failed to get current sequence" in caplog.text
    assert secret_conversation_id not in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "has_conversation_id=True" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sync_from_db_log_redacts_conversation_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_conversation_id = "conversation-secret-9753"
    redis_client = Mock()
    redis_client.get = AsyncMock(return_value="2")
    redis_client.pipeline = Mock(return_value=_Pipeline(current_value="2"))
    service = RedisSequenceService(redis_client)  # type: ignore[arg-type]

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        synced = await service.sync_from_db(secret_conversation_id, db_last_seq=5)

    assert synced is True
    assert "Synced sequence" in caplog.text
    assert secret_conversation_id not in caplog.text
    assert "current=2" in caplog.text
    assert "target=5" in caplog.text
    assert "has_conversation_id=True" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reset_sequence_log_redacts_conversation_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_conversation_id = "conversation-secret-8642"
    redis_client = Mock()
    redis_client.delete = AsyncMock(return_value=1)
    service = RedisSequenceService(redis_client)  # type: ignore[arg-type]

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        await service.reset_sequence(secret_conversation_id)

    assert "Reset sequence" in caplog.text
    assert secret_conversation_id not in caplog.text
    assert "has_conversation_id=True" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_batch_sequences_error_log_redacts_conversation_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_conversation_id = "conversation-secret-7531"
    redis_client = Mock()
    redis_client.incrby = AsyncMock(side_effect=RuntimeError("redis unavailable"))
    service = RedisSequenceService(redis_client)  # type: ignore[arg-type]

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME), pytest.raises(RuntimeError):
        await service.get_batch_sequences(secret_conversation_id, count=3)

    assert "Failed to get batch sequences" in caplog.text
    assert secret_conversation_id not in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "count=3" in caplog.text
    assert "has_conversation_id=True" in caplog.text
