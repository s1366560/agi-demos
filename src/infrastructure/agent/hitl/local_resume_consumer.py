"""Local HITL resume consumer for non-Ray environments.

When Ray is unavailable, this consumer listens on Redis Streams for HITL
responses and resumes agent execution locally by calling continue_project_chat.

This mirrors the HITLStreamRouterActor but runs as an in-process asyncio task
instead of a Ray actor.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.infrastructure.agent.hitl.utils import HITLRequestRecord


class LocalHITLResumeConsumer:
    """Consumes HITL responses from Redis and resumes agent execution locally."""

    STREAM_KEY_PATTERN = "hitl:response:{tenant_id}:{project_id}"
    CONSUMER_GROUP = "hitl-local-resume"
    DEFAULT_BLOCK_MS = 1000
    DEFAULT_BATCH_SIZE = 10
    RECLAIM_INTERVAL_SECONDS = 15.0
    RECLAIM_IDLE_MS = 30_000
    STALE_PROCESSING_IDLE_MS = 300_000

    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client
        self._projects: set[tuple[str, str]] = set()
        self._running = False
        self._listen_task: asyncio.Task[None] | None = None
        self._worker_id = f"local-resume-{os.getpid()}"
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._last_reclaim_at = 0.0

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
        logger.info("[LocalHITL] Stopped local HITL resume consumer")

    async def add_project(self, tenant_id: str, project_id: str) -> None:
        stream_key = self._stream_key(tenant_id, project_id)
        try:
            await self._redis.xgroup_create(stream_key, self.CONSUMER_GROUP, id="0", mkstream=True)
        except aioredis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
        self._projects.add((tenant_id, project_id))
        logger.info(f"[LocalHITL] Registered project {tenant_id}:{project_id} for HITL resume")

    async def _listen_loop(self) -> None:
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
                streams = await self._redis.xreadgroup(
                    groupname=self.CONSUMER_GROUP,
                    consumername=self._worker_id,
                    streams=stream_keys,  # type: ignore[arg-type]  # Redis type stubs overly strict
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
                await self._ack(stream_key, msg_id)
                return

            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")

            payload = json.loads(raw)
            request_id = payload.get("request_id")
            if not isinstance(request_id, str) or not request_id:
                await self._ack(stream_key, msg_id)
                return

            from src.infrastructure.agent.hitl.utils import (
                deserialize_hitl_stream_response,
                load_persisted_hitl_request,
                resolve_trusted_hitl_type,
            )

            hitl_request = await load_persisted_hitl_request(request_id)
            if hitl_request is None:
                logger.warning("[LocalHITL] Request not found for stream message: %s", request_id)
                await self._ack(stream_key, msg_id)
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
                logger.warning("[LocalHITL] Request %s has no trusted HITL type", request_id)
                await self._ack(stream_key, msg_id)
                return

            if use_persisted_response:
                from src.infrastructure.agent.hitl.utils import restore_persisted_hitl_response

                response_data = restore_persisted_hitl_response(hitl_request)
                if response_data is None:
                    logger.warning(
                        "[LocalHITL] Persisted response missing for recovered request %s; "
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
            tenant_id = getattr(hitl_request, "tenant_id", None) or payload.get("tenant_id")
            project_id = getattr(hitl_request, "project_id", None) or payload.get("project_id")
            conversation_id = getattr(hitl_request, "conversation_id", None) or payload.get(
                "conversation_id"
            )
            message_id = getattr(hitl_request, "message_id", None) or payload.get("message_id")

            if not tenant_id or not project_id:
                tenant_id, project_id = self._parse_stream_key(stream_key)

            logger.info(
                f"[LocalHITL] Resuming agent: request_id={request_id}, "
                f"project={tenant_id}:{project_id}"
            )

            _resume_task = asyncio.create_task(
                self._resume_and_ack(
                    stream_key,
                    msg_id,
                    tenant_id,
                    project_id,
                    request_id,
                    response_data,
                    conversation_id,
                    message_id,
                )
            )
            self._background_tasks.add(_resume_task)
            _resume_task.add_done_callback(self._background_tasks.discard)

        except Exception as e:
            logger.error(f"[LocalHITL] Failed to handle message {msg_id}: {e}", exc_info=True)

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
        """Return True when message handling should stop for the current request status."""
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
                    "[LocalHITL] Dropping stream response for non-answered request %s",
                    request_id,
                )
            elif normalized_status != "completed":
                logger.info(
                    "[LocalHITL] Dropping late response for terminal request %s (%s)",
                    request_id,
                    normalized_status,
                )
            await self._ack(stream_key, msg_id)
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
                "[LocalHITL] Request already processing; leaving stream pending: %s",
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
                "[LocalHITL] Stale processing recovery skipped; leaving pending: %s",
                request_id,
            )
            return True, False
        logger.warning("[LocalHITL] Recovered stale processing request: %s", request_id)
        return False, True

    async def _resume_and_ack(
        self,
        stream_key: str,
        msg_id: str,
        tenant_id: str,
        project_id: str,
        request_id: str,
        response_data: dict[str, Any],
        conversation_id: str | None,
        message_id: str | None,
    ) -> None:
        """Resume a response and ACK only after terminal handling succeeds."""
        should_ack = await self._resume_agent(
            tenant_id,
            project_id,
            request_id,
            response_data,
            conversation_id,
            message_id,
        )
        if should_ack:
            await self._ack(stream_key, msg_id)

    async def _resume_agent(
        self,
        tenant_id: str,
        project_id: str,
        request_id: str,
        response_data: dict[str, Any],
        conversation_id: str | None,
        message_id: str | None,
    ) -> bool:
        """Resolve the pending HITL Future and return whether the stream entry can be ACKed."""
        from src.infrastructure.agent.hitl.coordinator import (
            ResolveResult,
            resolve_by_request_id,
            wait_for_request_completion,
        )

        try:
            resolve_result = resolve_by_request_id(
                request_id,
                response_data,
                tenant_id=tenant_id,
                project_id=project_id,
                conversation_id=conversation_id,
                message_id=message_id,
            )
            if resolve_result is ResolveResult.RESOLVED:
                await wait_for_request_completion(request_id)
                logger.info(f"[LocalHITL] Resolved HITL future: request_id={request_id}")
                return True

            if resolve_result is ResolveResult.REJECTED:
                reopened = await self._reopen_answered_request(request_id)
                logger.warning(
                    "[LocalHITL] Rejected HITL response for request_id=%s; reopened=%s",
                    request_id,
                    reopened,
                )
                return reopened

            logger.warning(
                f"[LocalHITL] No active coordinator for request_id={request_id}, "
                f"falling back to continue_project_chat"
            )
            return await self._resume_via_continue(
                tenant_id,
                project_id,
                request_id,
                response_data,
                conversation_id,
                message_id,
            )
        except Exception as e:
            logger.error(
                f"[LocalHITL] Resume error: request_id={request_id} error={e}",
                exc_info=True,
            )
            return False

    async def _revert_processing_request(self, request_id: str) -> None:
        """Move a failed processing claim back to ANSWERED for later retry."""
        from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
        from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
            SqlHITLRequestRepository,
        )

        async with async_session_factory() as session:
            repo = SqlHITLRequestRepository(session)
            reverted_request = await repo.revert_to_answered(
                request_id,
                lease_owner=self._worker_id,
            )
            if reverted_request is not None:
                await session.commit()

    async def _recover_stale_processing_request(
        self,
        request_id: str,
        *,
        lease_before: datetime,
        lease_owner: str | None,
    ) -> bool:
        """Reopen a long-idle PROCESSING request so it can be retried."""
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

    async def _reopen_answered_request(self, request_id: str) -> bool:
        """Clear an invalid answered response so the request becomes retryable again."""
        from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
        from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
            SqlHITLRequestRepository,
        )

        async with async_session_factory() as session:
            repo = SqlHITLRequestRepository(session)
            reopened_request = await repo.reopen_pending(request_id)
            if reopened_request is None:
                return False
            await session.commit()
            return True

    async def _resume_via_continue(
        self,
        tenant_id: str,
        project_id: str,
        request_id: str,
        response_data: dict[str, Any],
        conversation_id: str | None,
        message_id: str | None,
    ) -> bool:
        """Crash recovery fallback: create a fresh agent and replay."""
        from src.configuration.config import get_settings
        from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
        from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
            SqlHITLRequestRepository,
        )
        from src.infrastructure.agent.actor.execution import continue_project_chat
        from src.infrastructure.agent.actor.state.snapshot_repo import load_hitl_snapshot_agent_mode
        from src.infrastructure.agent.core.project_react_agent import (
            ProjectAgentConfig,
            ProjectReActAgent,
        )
        from src.infrastructure.agent.hitl.utils import (
            is_permanent_hitl_resume_error,
            processing_lease_heartbeat,
        )

        try:
            async with async_session_factory() as session:
                repo = SqlHITLRequestRepository(session)
                if await repo.claim_for_processing(
                    request_id,
                    lease_owner=self._worker_id,
                ) is None:
                    logger.info(
                        "[LocalHITL] Request already claimed for processing: %s",
                        request_id,
                    )
                    return False
                await session.commit()

            settings = get_settings()
            agent_mode = await load_hitl_snapshot_agent_mode(request_id) or "default"

            agent_config = ProjectAgentConfig(
                tenant_id=tenant_id,
                project_id=project_id,
                agent_mode=agent_mode,
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
            try:
                await agent.initialize()

                async with processing_lease_heartbeat(
                    request_id,
                    lease_owner=self._worker_id,
                ):
                    result = await continue_project_chat(
                        agent,
                        request_id,
                        response_data,
                        lease_owner=self._worker_id,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        conversation_id=conversation_id,
                        message_id=message_id,
                    )

                if result.is_error:
                    if is_permanent_hitl_resume_error(result.error_message):
                        from src.infrastructure.agent.hitl.coordinator import complete_hitl_request

                        await complete_hitl_request(request_id, lease_owner=self._worker_id)
                        logger.warning(
                            "[LocalHITL] Permanently rejected fallback resume: request_id=%s "
                            "error=%s",
                            request_id,
                            result.error_message,
                        )
                        return True
                    logger.warning(
                        f"[LocalHITL] Fallback resume failed: request_id={request_id} "
                        f"error={result.error_message}"
                    )
                    await self._revert_processing_request(request_id)
                    return False

                logger.info(
                    f"[LocalHITL] Fallback resume completed: request_id={request_id} "
                    f"events={result.event_count}"
                )
                return True
            finally:
                with contextlib.suppress(Exception):
                    await agent.stop()
        except Exception as e:
            logger.error(
                f"[LocalHITL] Fallback resume error: request_id={request_id} error={e}",
                exc_info=True,
            )
            await self._revert_processing_request(request_id)
            return False

    async def _ack(self, stream_key: str | bytes, msg_id: str | bytes) -> None:
        try:
            if isinstance(stream_key, bytes):
                stream_key = stream_key.decode("utf-8")
            if isinstance(msg_id, bytes):
                msg_id = msg_id.decode("utf-8")
            await self._redis.xack(stream_key, self.CONSUMER_GROUP, msg_id)
        except Exception as e:
            logger.warning(f"[LocalHITL] Failed to ack {msg_id!r}: {e}")

    async def _reclaim_pending_messages(self, min_idle_ms: int) -> None:
        """Claim idle pending messages so crashed consumers do not strand responses."""
        for tenant_id, project_id in self._projects:
            stream_key = self._stream_key(tenant_id, project_id)
            pending = await self._redis.xpending_range(
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

            claimed = await self._redis.xclaim(
                stream_key,
                self.CONSUMER_GROUP,
                self._worker_id,
                min_idle_ms,
                message_ids,  # type: ignore[arg-type]  # Redis type stubs overly strict
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


# Module-level singleton
_local_consumer: LocalHITLResumeConsumer | None = None


async def get_or_create_local_consumer() -> LocalHITLResumeConsumer:
    """Get or create the local HITL resume consumer singleton."""
    global _local_consumer
    if _local_consumer is None:
        from src.infrastructure.agent.hitl.recovery_service import recover_hitl_on_startup
        from src.infrastructure.agent.state.agent_worker_state import (
            get_redis_client,
        )

        redis = await get_redis_client()
        _local_consumer = LocalHITLResumeConsumer(redis)
        await recover_hitl_on_startup()
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
