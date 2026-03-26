"""Workspace presence tracking service backed by Redis."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from src.domain.events.envelope import EventEnvelope
from src.infrastructure.adapters.secondary.messaging.redis_unified_event_bus import (
    RedisUnifiedEventBusAdapter,
)

logger = logging.getLogger(__name__)

_PRESENCE_TTL_SECONDS = 300


class WorkspacePresenceService:
    """Tracks user presence in workspaces using Redis SETs and HASHes."""

    def __init__(self, redis_client: Any) -> None:  # noqa: ANN401
        self._redis_client = redis_client

    async def join(
        self,
        workspace_id: str,
        user_id: str,
        display_name: str,
    ) -> list[dict[str, str]]:
        now = datetime.now(UTC).isoformat()
        set_key = f"workspace:{workspace_id}:presence:users"
        hash_key = f"workspace:{workspace_id}:presence:user:{user_id}"

        await self._redis_client.sadd(set_key, user_id)
        await self._redis_client.hset(
            hash_key,
            mapping={
                "display_name": display_name,
                "joined_at": now,
                "last_heartbeat": now,
            },
        )
        await self._redis_client.expire(hash_key, _PRESENCE_TTL_SECONDS)

        await self._publish_event(
            event_type="workspace.presence.joined",
            payload={"user_id": user_id, "display_name": display_name},
            routing_key=f"workspace:{workspace_id}:presence",
        )

        return await self.get_online_users(workspace_id)

    async def leave(self, workspace_id: str, user_id: str) -> None:
        set_key = f"workspace:{workspace_id}:presence:users"
        hash_key = f"workspace:{workspace_id}:presence:user:{user_id}"

        await self._redis_client.srem(set_key, user_id)
        await self._redis_client.delete(hash_key)

        await self._publish_event(
            event_type="workspace.presence.left",
            payload={"user_id": user_id},
            routing_key=f"workspace:{workspace_id}:presence",
        )

    async def heartbeat(self, workspace_id: str, user_id: str) -> None:
        hash_key = f"workspace:{workspace_id}:presence:user:{user_id}"
        now = datetime.now(UTC).isoformat()

        await self._redis_client.hset(hash_key, "last_heartbeat", now)
        await self._redis_client.expire(hash_key, _PRESENCE_TTL_SECONDS)

    async def get_online_users(self, workspace_id: str) -> list[dict[str, str]]:
        set_key = f"workspace:{workspace_id}:presence:users"
        member_ids: set[Any] = await self._redis_client.smembers(set_key)

        users: list[dict[str, str]] = []
        for raw_id in member_ids:
            uid = raw_id.decode("utf-8") if isinstance(raw_id, bytes) else str(raw_id)
            hash_key = f"workspace:{workspace_id}:presence:user:{uid}"
            data: dict[Any, Any] = await self._redis_client.hgetall(hash_key)
            if not data:
                await self._redis_client.srem(set_key, uid)
                continue
            decoded: dict[str, str] = {}
            for k, v in data.items():
                dk = k.decode("utf-8") if isinstance(k, bytes) else str(k)
                dv = v.decode("utf-8") if isinstance(v, bytes) else str(v)
                decoded[dk] = dv
            users.append(
                {
                    "user_id": uid,
                    "display_name": decoded.get("display_name", ""),
                    "joined_at": decoded.get("joined_at", ""),
                    "last_heartbeat": decoded.get("last_heartbeat", ""),
                }
            )
        return users

    async def broadcast_agent_status(
        self,
        workspace_id: str,
        agent_id: str,
        status: str,
        display_name: str,
    ) -> None:
        await self._publish_event(
            event_type="workspace.agent_status.changed",
            payload={
                "agent_id": agent_id,
                "status": status,
                "display_name": display_name,
            },
            routing_key=f"workspace:{workspace_id}:agent_status",
        )

    async def _publish_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        routing_key: str,
    ) -> None:
        bus = RedisUnifiedEventBusAdapter(self._redis_client)
        envelope = EventEnvelope(event_type=event_type, payload=payload)
        _ = await bus.publish(event=envelope, routing_key=routing_key)
