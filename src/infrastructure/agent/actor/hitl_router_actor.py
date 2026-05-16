"""Ray Actor that routes HITL responses from Redis Streams to project actors."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import ray
import redis.asyncio as aioredis

from src.configuration.config import get_settings
from src.configuration.ray_config import get_ray_settings
from src.infrastructure.adapters.secondary.ray.client import await_ray
from src.infrastructure.agent.actor.project_agent_actor import ProjectAgentActor
from src.infrastructure.agent.actor.types import ProjectAgentActorConfig

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.infrastructure.agent.hitl.utils import HITLRequestRecord


@ray.remote(max_restarts=5, max_task_retries=3, max_concurrency=10)  # type: ignore[call-overload]
class HITLStreamRouterActor:
    """Routes HITL responses from Redis to ProjectAgentActor instances."""

    STREAM_KEY_PATTERN = "hitl:response:{tenant_id}:{project_id}"
    CONSUMER_GROUP = "hitl-response-router"
    DEFAULT_BLOCK_MS = 1000
    DEFAULT_BATCH_SIZE = 10
    RECLAIM_INTERVAL_SECONDS = 15.0
    RECLAIM_IDLE_MS = 30_000
    STALE_PROCESSING_IDLE_MS = 300_000

    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None
        self._projects: set[tuple[str, str]] = set()
        self._running = False
        self._listen_task: asyncio.Task[None] | None = None
        self._worker_id = f"router-{os.getpid()}"
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._last_reclaim_at = 0.0

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
            with contextlib.suppress(asyncio.CancelledError):
                await self._listen_task
            self._listen_task = None
        if self._background_tasks:
            background_tasks = list(self._background_tasks)
            for task in background_tasks:
                task.cancel()
            with contextlib.suppress(Exception):
                await asyncio.gather(*background_tasks, return_exceptions=True)
            self._background_tasks.clear()

    async def add_project(self, tenant_id: str, project_id: str) -> None:
        """Add a project stream to listen to."""
        await self._ensure_redis()
        stream_key = self._stream_key(tenant_id, project_id)

        try:
            await self._redis.xgroup_create(  # type: ignore[union-attr]
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

                now = time.monotonic()
                if (
                    self._last_reclaim_at == 0.0
                    or now - self._last_reclaim_at >= self.RECLAIM_INTERVAL_SECONDS
                ):
                    await self._reclaim_pending_messages(min_idle_ms=self.RECLAIM_IDLE_MS)
                    self._last_reclaim_at = now

                stream_keys = {self._stream_key(tid, pid): ">" for tid, pid in self._projects}
                streams = await self._redis.xreadgroup(  # type: ignore[union-attr]
                    groupname=self.CONSUMER_GROUP,
                    consumername=self._worker_id,
                    streams=stream_keys,  # type: ignore[arg-type]
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

    async def _handle_message(
        self,
        stream_key: str,
        msg_id: str,
        fields: dict[str, Any],
        *,
        pending_idle_ms: int | None = None,
    ) -> None:
        try:
            raw = fields.get("data") or fields.get(b"data")  # type: ignore[call-overload]
            if not raw:
                await self._redis.xack(stream_key, self.CONSUMER_GROUP, msg_id)  # type: ignore[union-attr]
                return

            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")

            payload = json.loads(raw)
            request_id = payload.get("request_id")
            if not isinstance(request_id, str) or not request_id:
                await self._redis.xack(stream_key, self.CONSUMER_GROUP, msg_id)  # type: ignore[union-attr]
                return
            from src.infrastructure.agent.actor.state.snapshot_repo import (
                load_hitl_snapshot_agent_mode,
            )
            from src.infrastructure.agent.hitl.utils import (
                deserialize_hitl_stream_response,
                load_persisted_hitl_request,
                resolve_trusted_hitl_type,
            )

            hitl_request = await load_persisted_hitl_request(request_id)
            if hitl_request is None:
                logger.warning("[HITLRouter] Request not found: %s", request_id)
                await self._redis.xack(stream_key, self.CONSUMER_GROUP, msg_id)  # type: ignore[union-attr]
                return

            request_status = getattr(
                getattr(hitl_request, "status", None), "value", None
            ) or getattr(hitl_request, "status", None)
            should_stop, use_persisted_response = await self._handle_request_status(
                stream_key=stream_key,
                msg_id=msg_id,
                request_id=request_id,
                hitl_request=hitl_request,
                request_status=request_status,
                pending_idle_ms=pending_idle_ms,
            )
            if should_stop:
                return

            trusted_hitl_type = resolve_trusted_hitl_type(hitl_request)
            if trusted_hitl_type is None:
                logger.warning("[HITLRouter] Request missing trusted type: %s", request_id)
                await self._redis.xack(stream_key, self.CONSUMER_GROUP, msg_id)  # type: ignore[union-attr]
                return

            if use_persisted_response:
                from src.infrastructure.agent.hitl.utils import restore_persisted_hitl_response

                response_data = restore_persisted_hitl_response(hitl_request)
                if response_data is None:
                    logger.warning(
                        "[HITLRouter] Persisted response missing for recovered request %s; "
                        "falling back to stream payload",
                        request_id,
                    )
                    response_data = deserialize_hitl_stream_response(
                        payload,
                        expected_hitl_type=trusted_hitl_type,
                    )
            else:
                response_data = deserialize_hitl_stream_response(
                    payload,
                    expected_hitl_type=trusted_hitl_type,
                )
            agent_mode = await load_hitl_snapshot_agent_mode(request_id) or "default"
            tenant_id = getattr(hitl_request, "tenant_id", None) or payload.get("tenant_id")
            project_id = getattr(hitl_request, "project_id", None) or payload.get("project_id")

            if not tenant_id or not project_id:
                tenant_id, project_id = self._parse_stream_key(stream_key)

            conversation_id = getattr(hitl_request, "conversation_id", None) or payload.get(
                "conversation_id"
            )
            message_id = getattr(hitl_request, "message_id", None) or payload.get("message_id")
            actor = await self._get_or_create_actor(tenant_id, project_id, agent_mode)

            continue_task = asyncio.create_task(
                self._continue_and_ack(
                    stream_key=stream_key,
                    msg_id=msg_id,
                    actor=actor,
                    request_id=request_id,
                    response_data=response_data,
                    conversation_id=conversation_id,
                    message_id=message_id,
                )
            )
            self._background_tasks.add(continue_task)
            continue_task.add_done_callback(self._background_tasks.discard)

        except Exception as e:
            logger.error(f"[HITLRouter] Failed to handle message {msg_id}: {e}", exc_info=True)

    async def _continue_and_ack(
        self,
        *,
        stream_key: str,
        msg_id: str,
        actor: object,
        request_id: str,
        response_data: dict[str, Any],
        conversation_id: str | None,
        message_id: str | None,
    ) -> None:
        """Await actor continuation off the hot path and ACK only when safe."""
        try:
            continue_result = await await_ray(
                cast(Any, actor).continue_chat.remote(
                    request_id,
                    response_data,
                    conversation_id,
                    message_id,
                )
            )
            if isinstance(continue_result, dict) and continue_result.get("ack") is True:
                await self._redis.xack(stream_key, self.CONSUMER_GROUP, msg_id)  # type: ignore[union-attr]
        except Exception as e:
            logger.error(
                "[HITLRouter] Continue failed for request %s: %s",
                request_id,
                e,
                exc_info=True,
            )

    async def _handle_request_status(
        self,
        *,
        stream_key: str,
        msg_id: str,
        request_id: str,
        hitl_request: HITLRequestRecord,
        request_status: object,
        pending_idle_ms: int | None,
    ) -> tuple[bool, bool]:
        """Return True when router handling should stop for the current request status."""
        from src.infrastructure.agent.hitl.utils import (
            get_processing_owner,
            is_processing_lease_stale,
        )

        if not isinstance(request_status, str):
            return False, False
        normalized_status = request_status.lower()
        if normalized_status in {"completed", "cancelled", "timeout", "pending"}:
            if normalized_status == "pending":
                logger.warning(
                    "[HITLRouter] Dropping stream response for non-answered request %s",
                    request_id,
                )
            elif normalized_status != "completed":
                logger.info(
                    "[HITLRouter] Dropping late response for terminal request %s (%s)",
                    request_id,
                    normalized_status,
                )
            await self._redis.xack(stream_key, self.CONSUMER_GROUP, msg_id)  # type: ignore[union-attr]
            return True, False
        if normalized_status != "processing":
            return False, False

        lease_before = datetime.now(UTC) - timedelta(milliseconds=self.STALE_PROCESSING_IDLE_MS)
        if (
            pending_idle_ms is None
            or pending_idle_ms < self.STALE_PROCESSING_IDLE_MS
            or not is_processing_lease_stale(hitl_request, before=lease_before)
        ):
            logger.info(
                "[HITLRouter] Request already processing; leaving stream pending: %s",
                request_id,
            )
            return True, False
        recovered = await self._recover_stale_processing_request(
            request_id,
            lease_before=lease_before,
            lease_owner=get_processing_owner(hitl_request),
        )
        if not recovered:
            logger.info(
                "[HITLRouter] Stale processing recovery skipped; leaving pending: %s",
                request_id,
            )
            return True, False
        logger.warning("[HITLRouter] Recovered stale processing request: %s", request_id)
        return False, True

    async def _recover_stale_processing_request(
        self,
        request_id: str,
        *,
        lease_before: datetime,
        lease_owner: str | None,
    ) -> bool:
        """Reopen a long-idle PROCESSING request so the router can retry it."""
        from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
        from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
            SqlHITLRequestRepository,
        )

        async with async_session_factory() as session:
            repo = SqlHITLRequestRepository(session)
            reverted_request = await repo.revert_to_answered(
                request_id,
                lease_before=lease_before,
                lease_owner=lease_owner,
            )
            if reverted_request is None:
                return False
            await session.commit()
            return True

    async def _reclaim_pending_messages(self, min_idle_ms: int) -> None:
        """Reclaim idle pending messages so failed router deliveries can retry."""
        for tenant_id, project_id in self._projects:
            stream_key = self._stream_key(tenant_id, project_id)
            pending = await self._redis.xpending_range(  # type: ignore[union-attr]
                stream_key,
                self.CONSUMER_GROUP,
                "-",
                "+",
                self.DEFAULT_BATCH_SIZE,
            )
            message_ids: list[str] = []
            idle_by_message_id: dict[str, int] = {}
            for entry in pending:
                idle_time = entry.get("time_since_delivered", 0)
                if idle_time < min_idle_ms:
                    continue
                message_id = entry.get("message_id")
                if isinstance(message_id, bytes):
                    message_id = message_id.decode("utf-8")
                if isinstance(message_id, str) and message_id:
                    message_ids.append(message_id)
                    idle_by_message_id[message_id] = idle_time

            if not message_ids:
                continue

            claimed = await self._redis.xclaim(  # type: ignore[union-attr]
                stream_key,
                self.CONSUMER_GROUP,
                self._worker_id,
                min_idle_ms,
                message_ids,  # type: ignore[arg-type]
            )
            for claimed_msg_id, fields in claimed:
                claimed_msg_id_str = (
                    claimed_msg_id.decode("utf-8")
                    if isinstance(claimed_msg_id, bytes)
                    else claimed_msg_id
                )
                await self._handle_message(
                    stream_key,
                    claimed_msg_id,
                    fields,
                    pending_idle_ms=idle_by_message_id.get(claimed_msg_id_str),
                )

    async def _get_or_create_actor(
        self,
        tenant_id: str,
        project_id: str,
        agent_mode: str,
    ) -> Any:
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
            actor = ProjectAgentActor.options(  # type: ignore[attr-defined]
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
        self._redis = aioredis.from_url(settings.redis_url)  # type: ignore[no-untyped-call]

    def _stream_key(self, tenant_id: str, project_id: str) -> str:
        return self.STREAM_KEY_PATTERN.format(tenant_id=tenant_id, project_id=project_id)

    @staticmethod
    def _parse_stream_key(stream_key: str | bytes) -> tuple[str, str]:
        if isinstance(stream_key, bytes):
            stream_key = stream_key.decode("utf-8")
        parts = stream_key.split(":")
        if len(parts) < 4:
            raise ValueError(f"Invalid stream key: {stream_key}")
        return parts[2], parts[3]
