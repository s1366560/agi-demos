"""Redis-backed ControlChannel for SubAgent runtime control.

Hybrid approach:
- KILL signals use simple Redis keys for immediate, idempotent delivery
  (matches existing ``subagent:cancel:{execution_id}`` pattern).
- STEER/PAUSE/RESUME use Redis Streams for ordered, auditable delivery.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from src.domain.model.agent.tool_policy import ControlMessageType
from src.domain.ports.agent.control_channel_port import ControlMessage

if TYPE_CHECKING:
    from redis.asyncio import Redis as AsyncRedis

logger = logging.getLogger(__name__)

_KILL_KEY_PREFIX = "agent:control:kill:"
_STREAM_KEY_PREFIX = "agent:control:stream:"
_KILL_TTL_SECONDS = 600


def _kill_key(run_id: str) -> str:
    return f"{_KILL_KEY_PREFIX}{run_id}"


def _stream_key(run_id: str) -> str:
    return f"{_STREAM_KEY_PREFIX}{run_id}"


def _serialize_message(msg: ControlMessage) -> dict[str, str]:
    return {
        "run_id": msg.run_id,
        "message_type": msg.message_type.value,
        "payload": msg.payload,
        "sender_id": msg.sender_id,
        "timestamp": msg.timestamp.isoformat(),
        "cascade": str(msg.cascade),
        "run_input_id": msg.run_input_id,
        "delivery_mode": msg.delivery_mode,
        "run_revision": str(msg.run_revision) if msg.run_revision is not None else "",
        "message_id": msg.message_id,
        "idempotency_key": msg.idempotency_key,
        "target_agent_id": msg.target_agent_id,
        "target_agent_name": msg.target_agent_name,
    }


def _deserialize_message(data: Mapping[Any, Any]) -> ControlMessage:
    raw: dict[str, str] = {}
    for k, v in data.items():
        key = k.decode() if isinstance(k, bytes) else k
        val = v.decode() if isinstance(v, bytes) else v
        raw[key] = val

    run_revision_raw = raw.get("run_revision", "")
    return ControlMessage(
        run_id=raw["run_id"],
        message_type=ControlMessageType(raw["message_type"]),
        payload=raw.get("payload", ""),
        sender_id=raw.get("sender_id", ""),
        timestamp=datetime.fromisoformat(raw["timestamp"])
        if "timestamp" in raw
        else datetime.now(UTC),
        cascade=raw.get("cascade", "False").lower() == "true",
        run_input_id=raw.get("run_input_id", ""),
        delivery_mode=raw.get("delivery_mode", ""),
        run_revision=int(run_revision_raw) if run_revision_raw else None,
        message_id=raw.get("message_id", ""),
        idempotency_key=raw.get("idempotency_key", ""),
        target_agent_id=raw.get("target_agent_id", ""),
        target_agent_name=raw.get("target_agent_name", ""),
    )


class RedisControlChannel:
    """Redis-backed control channel for SubAgent steer/kill/pause/resume.

    Kill signals are stored as simple keys with TTL for instant polling.
    All other message types are appended to a Redis Stream per run_id.
    """

    def __init__(self, redis_client: AsyncRedis) -> None:
        self._redis = redis_client

    async def send_control(self, message: ControlMessage) -> bool:
        try:
            if message.message_type == ControlMessageType.KILL:
                return await self._send_kill(message)
            return await self._send_stream(message)
        except Exception as exc:
            logger.error(
                "Failed to send control message run_id=%s type=%s: %s",
                message.run_id,
                message.message_type.value,
                exc,
            )
            return False

    async def check_control(self, run_id: str) -> ControlMessage | None:
        try:
            kill_data = await self._redis.get(_kill_key(run_id))
            if kill_data is not None:
                raw = kill_data.decode() if isinstance(kill_data, bytes) else kill_data
                payload = json.loads(raw)
                return ControlMessage(
                    run_id=run_id,
                    message_type=ControlMessageType.KILL,
                    payload=payload.get("reason", ""),
                    sender_id=payload.get("sender_id", ""),
                    cascade=payload.get("cascade", False),
                    run_revision=payload.get("run_revision"),
                    idempotency_key=payload.get("idempotency_key", ""),
                    target_agent_id=payload.get("target_agent_id", ""),
                    target_agent_name=payload.get("target_agent_name", ""),
                )

            stream = _stream_key(run_id)
            entries: list[Any] = await self._redis.xrange(stream, count=1)
            if entries:
                _entry_id, entry_data = entries[0]
                return _deserialize_message(entry_data)
        except Exception as exc:
            logger.warning("check_control failed for run_id=%s: %s", run_id, exc)

        return None

    async def consume_control(self, run_id: str) -> list[ControlMessage]:
        messages: list[ControlMessage] = []

        try:
            kill_data = await self._redis.get(_kill_key(run_id))
            if kill_data is not None:
                raw = kill_data.decode() if isinstance(kill_data, bytes) else kill_data
                payload = json.loads(raw)
                messages.append(
                    ControlMessage(
                        run_id=run_id,
                        message_type=ControlMessageType.KILL,
                        payload=payload.get("reason", ""),
                        sender_id=payload.get("sender_id", ""),
                        cascade=payload.get("cascade", False),
                        run_revision=payload.get("run_revision"),
                        idempotency_key=payload.get("idempotency_key", ""),
                        target_agent_id=payload.get("target_agent_id", ""),
                        target_agent_name=payload.get("target_agent_name", ""),
                    )
                )
                await self._redis.delete(_kill_key(run_id))
        except Exception as exc:
            logger.warning("consume_control kill check failed for run_id=%s: %s", run_id, exc)

        try:
            stream = _stream_key(run_id)
            entries: list[Any] = await self._redis.xrange(stream)
            if entries:
                entry_ids: list[str | bytes] = []
                for entry_id, entry_data in entries:
                    messages.append(_deserialize_message(entry_data))
                    entry_ids.append(entry_id)

                if entry_ids:
                    await self._redis.xdel(stream, *entry_ids)
        except Exception as exc:
            logger.warning("consume_control stream read failed for run_id=%s: %s", run_id, exc)

        messages.sort(key=lambda m: m.timestamp)
        return messages

    async def cleanup(self, run_id: str) -> None:
        try:
            pipeline = self._redis.pipeline()
            pipeline.delete(_kill_key(run_id))
            pipeline.delete(_stream_key(run_id))
            await pipeline.execute()
        except Exception as exc:
            logger.warning("cleanup failed for run_id=%s: %s", run_id, exc)

    async def _send_kill(self, message: ControlMessage) -> bool:
        payload = json.dumps(
            {
                "reason": message.payload,
                "sender_id": message.sender_id,
                "cascade": message.cascade,
                "timestamp": message.timestamp.isoformat(),
                "run_revision": message.run_revision,
                "idempotency_key": message.idempotency_key,
                "target_agent_id": message.target_agent_id,
                "target_agent_name": message.target_agent_name,
            }
        )
        await self._redis.set(
            _kill_key(message.run_id),
            payload,
            ex=_KILL_TTL_SECONDS,
        )
        logger.info("Sent KILL control for run_id=%s", message.run_id)
        return True

    async def _send_stream(self, message: ControlMessage) -> bool:
        fields = _serialize_message(message)
        await self._redis.xadd(
            _stream_key(message.run_id),
            cast("dict[Any, Any]", fields),
            maxlen=100,
        )
        logger.info(
            "Sent %s control for run_id=%s",
            message.message_type.value,
            message.run_id,
        )
        return True
