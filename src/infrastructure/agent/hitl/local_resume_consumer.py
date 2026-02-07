"""Local HITL resume consumer for non-Ray environments.

When Ray is unavailable, this consumer listens on Redis Streams for HITL
responses and resumes agent execution locally by calling continue_project_chat.

This mirrors the HITLStreamRouterActor but runs as an in-process asyncio task
instead of a Ray actor.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, Optional, Set, Tuple

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class LocalHITLResumeConsumer:
    """Consumes HITL responses from Redis and resumes agent execution locally."""

    STREAM_KEY_PATTERN = "hitl:response:{tenant_id}:{project_id}"
    CONSUMER_GROUP = "hitl-local-resume"
    DEFAULT_BLOCK_MS = 1000
    DEFAULT_BATCH_SIZE = 10

    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client
        self._projects: Set[Tuple[str, str]] = set()
        self._running = False
        self._listen_task: Optional[asyncio.Task] = None
        self._worker_id = f"local-resume-{os.getpid()}"

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._listen_task = asyncio.create_task(self._listen_loop())
        logger.info("[LocalHITL] Started local HITL resume consumer")

    async def stop(self) -> None:
        self._running = False
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None
        logger.info("[LocalHITL] Stopped local HITL resume consumer")

    async def add_project(self, tenant_id: str, project_id: str) -> None:
        stream_key = self._stream_key(tenant_id, project_id)
        try:
            await self._redis.xgroup_create(
                stream_key, self.CONSUMER_GROUP, id="0", mkstream=True
            )
        except aioredis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
        self._projects.add((tenant_id, project_id))
        logger.info(
            f"[LocalHITL] Registered project {tenant_id}:{project_id} for HITL resume"
        )

    async def _listen_loop(self) -> None:
        while self._running:
            try:
                if not self._projects:
                    await asyncio.sleep(1)
                    continue

                stream_keys = {
                    self._stream_key(tid, pid): ">"
                    for tid, pid in self._projects
                }
                streams = await self._redis.xreadgroup(
                    groupname=self.CONSUMER_GROUP,
                    consumername=self._worker_id,
                    streams=stream_keys,
                    count=self.DEFAULT_BATCH_SIZE,
                    block=self.DEFAULT_BLOCK_MS,
                )

                if not streams:
                    continue

                for stream_key, messages in streams:
                    for msg_id, fields in messages:
                        await self._handle_message(stream_key, msg_id, fields)

            except asyncio.CancelledError:
                break
            except aioredis.ConnectionError as e:
                logger.error(f"[LocalHITL] Redis connection error: {e}")
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"[LocalHITL] Error in listen loop: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def _handle_message(
        self, stream_key: str, msg_id: str, fields: Dict[str, Any]
    ) -> None:
        try:
            raw = fields.get("data") or fields.get(b"data")
            if not raw:
                await self._ack(stream_key, msg_id)
                return

            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")

            payload = json.loads(raw)
            request_id = payload.get("request_id")
            response_data_raw = payload.get("response_data")
            response_data = (
                json.loads(response_data_raw)
                if isinstance(response_data_raw, str)
                else response_data_raw
            )
            tenant_id = payload.get("tenant_id")
            project_id = payload.get("project_id")

            if not tenant_id or not project_id:
                tenant_id, project_id = self._parse_stream_key(stream_key)

            logger.info(
                f"[LocalHITL] Resuming agent: request_id={request_id}, "
                f"project={tenant_id}:{project_id}"
            )

            asyncio.create_task(
                self._resume_agent(tenant_id, project_id, request_id, response_data)
            )
            await self._ack(stream_key, msg_id)

        except Exception as e:
            logger.error(
                f"[LocalHITL] Failed to handle message {msg_id}: {e}", exc_info=True
            )

    async def _resume_agent(
        self,
        tenant_id: str,
        project_id: str,
        request_id: str,
        response_data: Dict[str, Any],
    ) -> None:
        """Create a fresh agent and call continue_project_chat."""
        from src.configuration.config import get_settings
        from src.infrastructure.agent.actor.execution import continue_project_chat
        from src.infrastructure.agent.core.project_react_agent import (
            ProjectAgentConfig,
            ProjectReActAgent,
        )

        try:
            settings = get_settings()

            agent_config = ProjectAgentConfig(
                tenant_id=tenant_id,
                project_id=project_id,
                agent_mode="default",
                model=None,
                api_key=None,
                base_url=None,
                temperature=0.7,
                max_tokens=settings.agent_max_tokens,
                max_steps=settings.agent_max_steps,
                persistent=False,
                max_concurrent_chats=10,
                mcp_tools_ttl_seconds=300,
                enable_skills=True,
                enable_subagents=True,
            )

            agent = ProjectReActAgent(agent_config)
            await agent.initialize()

            result = await continue_project_chat(agent, request_id, response_data)

            if result.is_error:
                logger.warning(
                    f"[LocalHITL] Resume failed: request_id={request_id} "
                    f"error={result.error_message}"
                )
            else:
                logger.info(
                    f"[LocalHITL] Resume completed: request_id={request_id} "
                    f"events={result.event_count}"
                )
        except Exception as e:
            logger.error(
                f"[LocalHITL] Resume error: request_id={request_id} error={e}",
                exc_info=True,
            )

    async def _ack(self, stream_key: str, msg_id: str) -> None:
        try:
            if isinstance(stream_key, bytes):
                stream_key = stream_key.decode("utf-8")
            if isinstance(msg_id, bytes):
                msg_id = msg_id.decode("utf-8")
            await self._redis.xack(stream_key, self.CONSUMER_GROUP, msg_id)
        except Exception as e:
            logger.warning(f"[LocalHITL] Failed to ack {msg_id}: {e}")

    def _stream_key(self, tenant_id: str, project_id: str) -> str:
        return self.STREAM_KEY_PATTERN.format(
            tenant_id=tenant_id, project_id=project_id
        )

    @staticmethod
    def _parse_stream_key(stream_key: str) -> Tuple[str, str]:
        if isinstance(stream_key, bytes):
            stream_key = stream_key.decode("utf-8")
        parts = stream_key.split(":")
        if len(parts) < 4:
            raise ValueError(f"Invalid stream key: {stream_key}")
        return parts[2], parts[3]


# Module-level singleton
_local_consumer: Optional[LocalHITLResumeConsumer] = None


async def get_or_create_local_consumer() -> LocalHITLResumeConsumer:
    """Get or create the local HITL resume consumer singleton."""
    global _local_consumer
    if _local_consumer is None:
        from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
            get_redis_client,
        )

        redis = await get_redis_client()
        _local_consumer = LocalHITLResumeConsumer(redis)
        await _local_consumer.start()
    return _local_consumer


async def register_project_local(tenant_id: str, project_id: str) -> None:
    """Register a project for local HITL resume listening."""
    consumer = await get_or_create_local_consumer()
    await consumer.add_project(tenant_id, project_id)


async def shutdown_local_consumer() -> None:
    """Shut down the local HITL resume consumer."""
    global _local_consumer
    if _local_consumer:
        await _local_consumer.stop()
        _local_consumer = None
