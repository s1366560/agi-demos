"""Ray Actor that routes HITL responses from Redis Streams to project actors."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, Optional, Set, Tuple

import ray
import redis.asyncio as aioredis

from src.configuration.config import get_settings
from src.configuration.ray_config import get_ray_settings
from src.infrastructure.adapters.secondary.ray.client import await_ray
from src.infrastructure.agent.actor.project_agent_actor import ProjectAgentActor
from src.infrastructure.agent.actor.types import ProjectAgentActorConfig

logger = logging.getLogger(__name__)


@ray.remote(max_restarts=5, max_task_retries=3, max_concurrency=10)
class HITLStreamRouterActor:
    """Routes HITL responses from Redis to ProjectAgentActor instances."""

    STREAM_KEY_PATTERN = "hitl:response:{tenant_id}:{project_id}"
    CONSUMER_GROUP = "hitl-response-router"
    DEFAULT_BLOCK_MS = 1000
    DEFAULT_BATCH_SIZE = 10

    def __init__(self) -> None:
        self._redis: Optional[aioredis.Redis] = None
        self._projects: Set[Tuple[str, str]] = set()
        self._running = False
        self._listen_task: Optional[asyncio.Task] = None
        self._worker_id = f"router-{os.getpid()}"

    async def start(self) -> None:
        """Start the router loop."""
        if self._running:
            return
        self._running = True
        self._listen_task = asyncio.create_task(self._listen_loop())

    async def stop(self) -> None:
        """Stop the router loop."""
        self._running = False
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

    async def add_project(self, tenant_id: str, project_id: str) -> None:
        """Add a project stream to listen to."""
        await self._ensure_redis()
        stream_key = self._stream_key(tenant_id, project_id)

        try:
            await self._redis.xgroup_create(
                stream_key,
                self.CONSUMER_GROUP,
                id="0",
                mkstream=True,
            )
        except aioredis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

        self._projects.add((tenant_id, project_id))

    async def remove_project(self, tenant_id: str, project_id: str) -> None:
        """Remove a project stream from listening."""
        self._projects.discard((tenant_id, project_id))

    async def _listen_loop(self) -> None:
        await self._ensure_redis()

        while self._running:
            try:
                if not self._projects:
                    await asyncio.sleep(1)
                    continue

                stream_keys = {self._stream_key(tid, pid): ">" for tid, pid in self._projects}
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
                logger.error(f"[HITLRouter] Redis connection error: {e}")
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"[HITLRouter] Error in loop: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def _handle_message(self, stream_key: str, msg_id: str, fields: Dict[str, Any]) -> None:
        try:
            raw = fields.get("data") or fields.get(b"data")
            if not raw:
                await self._redis.xack(stream_key, self.CONSUMER_GROUP, msg_id)
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
            agent_mode = payload.get("agent_mode", "default")
            tenant_id = payload.get("tenant_id")
            project_id = payload.get("project_id")

            if not tenant_id or not project_id:
                tenant_id, project_id = self._parse_stream_key(stream_key)

            conversation_id = payload.get("conversation_id")
            actor = await self._get_or_create_actor(tenant_id, project_id, agent_mode)

            await await_ray(actor.continue_chat.remote(request_id, response_data, conversation_id))
            await self._redis.xack(stream_key, self.CONSUMER_GROUP, msg_id)

        except Exception as e:
            logger.error(f"[HITLRouter] Failed to handle message {msg_id}: {e}", exc_info=True)

    async def _get_or_create_actor(
        self,
        tenant_id: str,
        project_id: str,
        agent_mode: str,
    ) -> Any:  # noqa: ANN401
        settings = get_settings()
        ray_settings = get_ray_settings()
        actor_id = ProjectAgentActor.actor_id(tenant_id, project_id, agent_mode)

        try:
            return ray.get_actor(actor_id, namespace=ray_settings.ray_namespace)
        except ValueError:
            config = ProjectAgentActorConfig(
                tenant_id=tenant_id,
                project_id=project_id,
                agent_mode=agent_mode,
                model=None,
                api_key=None,
                base_url=None,
                temperature=0.7,
                max_steps=settings.agent_max_steps,
                max_tokens=settings.agent_max_tokens,
                persistent=True,
                mcp_tools_ttl_seconds=300,
                max_concurrent_chats=10,
                enable_skills=True,
                enable_subagents=True,
            )
            actor = ProjectAgentActor.options(
                name=actor_id,
                namespace=ray_settings.ray_namespace,
                lifetime="detached",
            ).remote()
            await await_ray(actor.initialize.remote(config, False))
            return actor

    async def _ensure_redis(self) -> None:
        if self._redis is not None:
            return
        settings = get_settings()
        self._redis = aioredis.from_url(settings.redis_url)

    def _stream_key(self, tenant_id: str, project_id: str) -> str:
        return self.STREAM_KEY_PATTERN.format(tenant_id=tenant_id, project_id=project_id)

    @staticmethod
    def _parse_stream_key(stream_key: str) -> Tuple[str, str]:
        if isinstance(stream_key, bytes):
            stream_key = stream_key.decode("utf-8")
        parts = stream_key.split(":")
        if len(parts) < 4:
            raise ValueError(f"Invalid stream key: {stream_key}")
        return parts[2], parts[3]
