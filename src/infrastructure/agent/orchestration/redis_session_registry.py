"""Redis-backed implementation of AgentSessionRegistry."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable
from typing import Any, cast

from redis.asyncio import Redis

from src.infrastructure.agent.orchestration.session_registry import AgentSession

logger = logging.getLogger(__name__)


class RedisAgentSessionRegistry:
    def __init__(
        self,
        redis_client: Redis,
        *,
        namespace: str = "agent:session",
        ttl_seconds: int = 86400,
    ) -> None:
        self._redis = redis_client
        self._namespace = namespace
        self._ttl = ttl_seconds

    def _session_key(self, project_id: str, conversation_id: str) -> str:
        return f"{self._namespace}:{project_id}:{conversation_id}"

    def _project_index_key(self, project_id: str) -> str:
        return f"{self._namespace}:project:{project_id}"

    @staticmethod
    def _compound_member(project_id: str, conversation_id: str) -> str:
        return f"{project_id}:{conversation_id}"

    @staticmethod
    def _serialize(session: AgentSession) -> str:
        return json.dumps(
            {
                "agent_id": session.agent_id,
                "conversation_id": session.conversation_id,
                "project_id": session.project_id,
                "registered_at": session.registered_at,
            }
        )

    @staticmethod
    def _deserialize(raw: str | bytes) -> AgentSession:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        data: dict[str, Any] = json.loads(raw)
        return AgentSession(
            agent_id=data["agent_id"],
            conversation_id=data["conversation_id"],
            project_id=data["project_id"],
            registered_at=data["registered_at"],
        )

    async def register(
        self,
        agent_id: str,
        conversation_id: str,
        project_id: str,
    ) -> AgentSession:
        session = AgentSession(
            agent_id=agent_id,
            conversation_id=conversation_id,
            project_id=project_id,
        )

        key = self._session_key(project_id, conversation_id)
        index_key = self._project_index_key(project_id)
        compound = self._compound_member(project_id, conversation_id)

        try:
            pipe = self._redis.pipeline()
            pipe.setex(key, self._ttl, self._serialize(session))
            pipe.sadd(index_key, compound)  # type: ignore[arg-type]
            await pipe.execute()

            logger.debug(
                "Registered agent session: agent=%s conv=%s project=%s",
                agent_id,
                conversation_id,
                project_id,
            )
        except Exception:
            logger.exception("Failed to register session in Redis")

        return session

    async def unregister(
        self,
        conversation_id: str,
        project_id: str,
    ) -> AgentSession | None:
        key = self._session_key(project_id, conversation_id)
        index_key = self._project_index_key(project_id)
        compound = self._compound_member(project_id, conversation_id)

        try:
            raw = await self._redis.get(key)
            if raw is None:
                return None

            session = self._deserialize(raw)

            pipe = self._redis.pipeline()
            pipe.delete(key)
            pipe.srem(index_key, compound)  # type: ignore[arg-type]
            await pipe.execute()

            return session
        except Exception:
            logger.exception("Failed to unregister session from Redis")
            return None

    async def get_session_for_conversation(
        self,
        conversation_id: str,
        project_id: str,
    ) -> AgentSession | None:
        key = self._session_key(project_id, conversation_id)

        try:
            raw = await self._redis.get(key)
            if raw is None:
                return None
            return self._deserialize(raw)
        except Exception:
            logger.exception("Failed to get session from Redis")
            return None

    async def get_sessions(
        self,
        project_id: str,
    ) -> list[AgentSession]:
        index_key = self._project_index_key(project_id)

        try:
            members: set[Any] = await cast(Awaitable[set[Any]], self._redis.smembers(index_key))

            sessions: list[AgentSession] = []
            for compound in members:
                if isinstance(compound, bytes):
                    compound = compound.decode("utf-8")
                parts = str(compound).split(":", 1)
                if len(parts) != 2:
                    continue
                pid, cid = parts
                session = await self.get_session_for_conversation(cid, pid)
                if session is not None:
                    sessions.append(session)

            return sessions
        except Exception:
            logger.exception("Failed to get sessions from Redis")
            return []

    async def get_active_agent_ids(
        self,
        project_id: str,
    ) -> set[str]:
        sessions = await self.get_sessions(project_id)
        return {s.agent_id for s in sessions}

    async def clear_project(self, project_id: str) -> int:
        index_key = self._project_index_key(project_id)

        try:
            members: set[Any] = await cast(Awaitable[set[Any]], self._redis.smembers(index_key))

            if not members:
                return 0

            keys_to_delete: list[str] = []
            for compound in members:
                if isinstance(compound, bytes):
                    compound = compound.decode("utf-8")
                parts = str(compound).split(":", 1)
                if len(parts) != 2:
                    continue
                pid, cid = parts
                keys_to_delete.append(self._session_key(pid, cid))

            if keys_to_delete:
                pipe = self._redis.pipeline()
                for k in keys_to_delete:
                    pipe.delete(k)
                pipe.delete(index_key)
                await pipe.execute()

            count = len(keys_to_delete)
            logger.debug("Cleared %d sessions for project %s", count, project_id)
            return count
        except Exception:
            logger.exception("Failed to clear project sessions from Redis")
            return 0
