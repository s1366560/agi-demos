"""
Redis Streams implementation of AgentMessageBusPort.

This adapter uses Redis Streams for inter-agent message delivery.

Redis Streams advantages:
- Message persistence (survives disconnects and restarts)
- Efficient range queries for polling
- Blocking reads for subscription
- Automatic cleanup via DELETE

Stream naming convention:
- agent:messages:{session_id} - One stream per agent session
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, cast

import redis.asyncio as redis

from src.domain.ports.services.agent_message_bus_port import (
    AgentMessage,
    AgentMessageBusPort,
    AgentMessageType,
)

logger = logging.getLogger(__name__)


class RedisAgentMessageBusAdapter(AgentMessageBusPort):
    """
    Redis Streams implementation of AgentMessageBusPort.

    Uses Redis Streams with per-session streams for inter-agent messaging.
    Each agent session gets its own stream that other agents write into.
    """

    STREAM_PREFIX = "agent:messages:"

    DEFAULT_MAX_LEN = 500
    DEFAULT_BLOCK_MS = 5000
    DEFAULT_TTL_SECONDS = 3600

    def __init__(
        self,
        redis_client: redis.Redis,
        stream_prefix: str | None = None,
        default_max_len: int | None = None,
    ) -> None:
        self._redis = redis_client
        self._stream_prefix = stream_prefix or self.STREAM_PREFIX
        self._default_max_len = default_max_len or self.DEFAULT_MAX_LEN

    def _get_stream_key(self, session_id: str) -> str:
        """Get the stream key for a session."""
        return f"{self._stream_prefix}{session_id}"

    async def send_message(
        self,
        from_agent_id: str,
        to_agent_id: str,
        session_id: str,
        content: str,
        message_type: AgentMessageType,
        metadata: dict[str, Any] | None = None,
        parent_message_id: str | None = None,
    ) -> str:
        """Send a message to an agent's session stream."""
        stream_key = self._get_stream_key(session_id)

        message_data = {
            "message_id": str(uuid.uuid4()),
            "from_agent_id": from_agent_id,
            "to_agent_id": to_agent_id,
            "session_id": session_id,
            "content": content,
            "message_type": message_type.value,
            "timestamp": datetime.now(UTC).isoformat(),
            "metadata": metadata or {},
            "parent_message_id": parent_message_id,
        }

        try:
            payload = {"data": json.dumps(message_data, default=str)}

            stream_id = await self._redis.xadd(
                stream_key,
                payload,  # type: ignore[arg-type]
                maxlen=self._default_max_len,
                approximate=True,
            )

            if isinstance(stream_id, bytes):
                stream_id = stream_id.decode("utf-8")

            logger.info(
                f"[AgentMessageBus] Sent message to {stream_key}: "
                f"stream_id={stream_id}, "
                f"from={from_agent_id}, to={to_agent_id}, "
                f"type={message_type.value}"
            )

            return cast(str, message_data["message_id"])

        except Exception as e:
            logger.error(f"[AgentMessageBus] Failed to send to {stream_key}: {e}")
            raise

    async def receive_messages(
        self,
        agent_id: str,
        session_id: str,
        since_id: str | None = None,
        limit: int = 50,
    ) -> list[AgentMessage]:
        """Poll for messages in an agent's session stream."""
        stream_key = self._get_stream_key(session_id)
        messages: list[AgentMessage] = []

        start = since_id if since_id else "-"
        # When using since_id, Redis xrange is inclusive on min,
        # so we need to skip the since_id message itself.
        exclude_since = since_id is not None

        try:
            results = await self._redis.xrange(
                stream_key,
                min=start,
                max="+",
                count=limit + (1 if exclude_since else 0),
            )

            if not results:
                return messages

            for msg_id, fields in results:
                if isinstance(msg_id, bytes):
                    msg_id = msg_id.decode("utf-8")

                if exclude_since and msg_id == since_id:
                    continue

                message = self._parse_stream_message(msg_id, fields)
                if message and message.to_agent_id == agent_id:
                    messages.append(message)

            return messages[:limit]

        except Exception as e:
            logger.error(f"[AgentMessageBus] Failed to receive from {stream_key}: {e}")
            raise

    async def subscribe_messages(
        self,
        agent_id: str,
        session_id: str,
        timeout_ms: int = 5000,
    ) -> AsyncIterator[AgentMessage]:
        """Subscribe to messages in an agent's session stream."""
        stream_key = self._get_stream_key(session_id)
        last_id = "$"

        while True:
            try:
                streams = await self._redis.xread(
                    streams={stream_key: last_id},
                    count=10,
                    block=timeout_ms,
                )

                if not streams:
                    continue

                for _stream_name, stream_messages in streams:
                    for msg_id, fields in stream_messages:
                        if isinstance(msg_id, bytes):
                            msg_id = msg_id.decode("utf-8")

                        last_id = msg_id

                        message = self._parse_stream_message(msg_id, fields)
                        if message and message.to_agent_id == agent_id:
                            yield message

            except redis.ConnectionError as e:
                logger.error(f"[AgentMessageBus] Connection error on {stream_key}: {e}")
                raise
            except Exception as e:
                logger.error(f"[AgentMessageBus] Error reading from {stream_key}: {e}")
                raise

    async def get_message_history(
        self,
        session_id: str,
        limit: int = 50,
    ) -> list[AgentMessage]:
        """Get message history for a session."""
        stream_key = self._get_stream_key(session_id)
        messages: list[AgentMessage] = []

        try:
            results = await self._redis.xrevrange(
                stream_key,
                max="+",
                min="-",
                count=limit,
            )

            if not results:
                return messages

            for msg_id, fields in reversed(results):
                message = self._parse_stream_message(msg_id, fields)
                if message:
                    messages.append(message)

            return messages

        except Exception as e:
            logger.error(f"[AgentMessageBus] Failed to get history from {stream_key}: {e}")
            raise

    async def cleanup_session(self, session_id: str) -> None:
        """Delete a session's message stream."""
        stream_key = self._get_stream_key(session_id)

        try:
            await self._redis.delete(stream_key)
            logger.info(f"[AgentMessageBus] Cleaned up stream {stream_key}")
        except Exception as e:
            logger.error(f"[AgentMessageBus] Failed to cleanup {stream_key}: {e}")
            raise

    async def session_has_messages(self, session_id: str) -> bool:
        """Check if a session's stream exists."""
        stream_key = self._get_stream_key(session_id)

        try:
            return cast(bool, await self._redis.exists(stream_key) > 0)
        except Exception as e:
            logger.error(f"[AgentMessageBus] Failed to check existence of {stream_key}: {e}")
            return False

    def _parse_stream_message(
        self, msg_id: bytes | str, fields: dict[Any, Any]
    ) -> AgentMessage | None:
        """Parse a raw Redis stream message into AgentMessage."""
        try:
            if isinstance(msg_id, bytes):
                msg_id = msg_id.decode("utf-8")

            raw_data = fields.get(b"data") or fields.get("data")
            if isinstance(raw_data, bytes):
                raw_data = raw_data.decode("utf-8")

            if not raw_data:
                return None

            data = json.loads(raw_data)

            return AgentMessage(
                message_id=data.get("message_id", ""),
                from_agent_id=data.get("from_agent_id", ""),
                to_agent_id=data.get("to_agent_id", ""),
                session_id=data.get("session_id", ""),
                content=data.get("content", ""),
                message_type=AgentMessageType(
                    data.get(
                        "message_type",
                        AgentMessageType.NOTIFICATION.value,
                    )
                ),
                timestamp=(
                    datetime.fromisoformat(data["timestamp"])
                    if isinstance(data.get("timestamp"), str)
                    else datetime.now(UTC)
                ),
                metadata=data.get("metadata"),
                parent_message_id=data.get("parent_message_id"),
            )

        except Exception as e:
            logger.warning(f"[AgentMessageBus] Failed to parse message {msg_id}: {e}")
            return None


def create_redis_agent_message_bus(
    redis_client: redis.Redis,
    stream_prefix: str | None = None,
) -> RedisAgentMessageBusAdapter:
    """Create a RedisAgentMessageBusAdapter instance."""
    return RedisAgentMessageBusAdapter(
        redis_client=redis_client,
        stream_prefix=stream_prefix,
    )
