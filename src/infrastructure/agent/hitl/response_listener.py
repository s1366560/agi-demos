"""
HITL Response Listener for Real-time Response Delivery.

This module provides a listener that consumes HITL responses from Redis Streams
and delivers them directly to Agent sessions in memory.

Architecture:
- Runs as a background task in each Agent Worker
- Subscribes to Redis Streams for all projects handled by this Worker
- Uses Consumer Groups for reliable delivery and load balancing
- Delivers responses directly to AgentSessionRegistry

Benefits:
- ~30ms latency
- Direct in-memory delivery when session is on same Worker

Reliability:
- Consumer Groups ensure at-least-once delivery
- Message acknowledgment after successful delivery
"""

import asyncio
import contextlib
import json
import logging
import os
from typing import Any

import redis.asyncio as aioredis

from src.infrastructure.agent.hitl.session_registry import (
    AgentSessionRegistry,
    get_session_registry,
)

logger = logging.getLogger(__name__)


class HITLResponseListener:
    """
    Listens for HITL responses from Redis Streams.

    This component enables real-time HITL response delivery by:
    1. Subscribing to project-specific Redis Streams
    2. Consuming messages using Consumer Groups
    3. Delivering responses directly to in-memory sessions
    4. Acknowledging messages after successful delivery

    Usage:
        listener = HITLResponseListener(redis_client)

        # Add projects to listen to
        await listener.add_project("tenant1", "project1")
        await listener.add_project("tenant1", "project2")

        # Start listening (runs forever)
        await listener.start()

        # Stop when shutting down
        await listener.stop()
    """

    # Stream key pattern
    STREAM_KEY_PATTERN = "hitl:response:{tenant_id}:{project_id}"

    # Consumer group name
    CONSUMER_GROUP = "hitl-response-workers"

    # Default settings
    DEFAULT_BLOCK_MS = 1000  # 1 second block timeout
    DEFAULT_BATCH_SIZE = 10  # Max messages per read

    def __init__(
        self,
        redis_client: aioredis.Redis,
        session_registry: AgentSessionRegistry | None = None,
        worker_id: str | None = None,
    ) -> None:
        """
        Initialize the HITL Response Listener.

        Args:
            redis_client: Async Redis client
            session_registry: Registry for finding target sessions
            worker_id: Unique ID for this worker (auto-generated if not provided)
        """
        self._redis = redis_client
        self._registry = session_registry or get_session_registry()
        self._worker_id = worker_id or f"worker-{os.getpid()}"

        # Projects being listened to
        self._projects: set[tuple[str, str]] = set()  # Set of (tenant_id, project_id)

        # Running state
        self._running = False
        self._listen_task: asyncio.Task[None] | None = None

        # Metrics
        self._messages_received = 0
        self._messages_delivered = 0
        self._messages_skipped = 0
        self._errors = 0

    def _get_stream_key(self, tenant_id: str, project_id: str) -> str:
        """Get the Redis Stream key for a project."""
        return self.STREAM_KEY_PATTERN.format(
            tenant_id=tenant_id,
            project_id=project_id,
        )

    async def add_project(self, tenant_id: str, project_id: str) -> None:
        """
        Add a project to listen for HITL responses.

        This creates the consumer group if it doesn't exist.

        Args:
            tenant_id: Tenant ID
            project_id: Project ID
        """
        stream_key = self._get_stream_key(tenant_id, project_id)

        # Ensure consumer group exists
        try:
            await self._redis.xgroup_create(
                stream_key,
                self.CONSUMER_GROUP,
                id="0",  # Start from beginning
                mkstream=True,  # Create stream if doesn't exist
            )
            logger.debug(f"[HITLListener] Created consumer group for {stream_key}")
        except aioredis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                # Group already exists, this is fine
                pass
            else:
                raise

        self._projects.add((tenant_id, project_id))
        logger.info(f"[HITLListener] Added project: tenant={tenant_id}, project={project_id}")

    async def remove_project(self, tenant_id: str, project_id: str) -> None:
        """Remove a project from listening."""
        self._projects.discard((tenant_id, project_id))
        logger.info(f"[HITLListener] Removed project: tenant={tenant_id}, project={project_id}")

    async def start(self) -> None:
        """
        Start listening for HITL responses.

        This creates a background task that runs until stop() is called.
        """
        if self._running:
            logger.warning("[HITLListener] Already running")
            return

        self._running = True
        self._listen_task = asyncio.create_task(self._listen_loop())
        logger.info(
            f"[HITLListener] Started with worker_id={self._worker_id}, "
            f"projects={len(self._projects)}"
        )

    async def stop(self) -> None:
        """Stop listening for HITL responses."""
        self._running = False

        if self._listen_task:
            self._listen_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listen_task
            self._listen_task = None

        logger.info(
            f"[HITLListener] Stopped. Stats: received={self._messages_received}, "
            f"delivered={self._messages_delivered}, skipped={self._messages_skipped}, "
            f"errors={self._errors}"
        )

    async def _listen_loop(self) -> None:
        """Main listening loop."""
        logger.info("[HITLListener] Listen loop started")

        while self._running:
            try:
                if not self._projects:
                    # No projects to listen to, sleep briefly
                    await asyncio.sleep(1)
                    continue

                # Build stream keys to read from
                stream_keys = {self._get_stream_key(tid, pid): ">" for tid, pid in self._projects}

                # Read from all streams using consumer group
                streams = await self._redis.xreadgroup(
                    groupname=self.CONSUMER_GROUP,
                    consumername=self._worker_id,
                    streams=stream_keys,
                    count=self.DEFAULT_BATCH_SIZE,
                    block=self.DEFAULT_BLOCK_MS,
                )

                if not streams:
                    # No new messages, continue
                    continue

                # Process messages
                for stream_key, messages in streams:
                    for msg_id, fields in messages:
                        await self._handle_message(stream_key, msg_id, fields)

            except asyncio.CancelledError:
                break
            except aioredis.ConnectionError as e:
                logger.error(f"[HITLListener] Redis connection error: {e}")
                self._errors += 1
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"[HITLListener] Error in listen loop: {e}", exc_info=True)
                self._errors += 1
                await asyncio.sleep(1)

        logger.info("[HITLListener] Listen loop ended")

    async def _handle_message(
        self,
        stream_key: str | bytes,
        msg_id: str | bytes,
        fields: dict[bytes, bytes],
    ) -> None:
        """
        Handle a single HITL response message.

        Args:
            stream_key: Redis Stream key
            msg_id: Message ID
            fields: Message fields
        """
        self._messages_received += 1

        try:
            # Decode message ID
            if isinstance(msg_id, bytes):
                msg_id = msg_id.decode("utf-8")
            if isinstance(stream_key, bytes):
                stream_key = stream_key.decode("utf-8")

            # Parse message data
            raw_data = fields.get(b"data") or fields.get("data")
            if isinstance(raw_data, bytes):
                raw_data = raw_data.decode("utf-8")

            if not raw_data:
                logger.warning(f"[HITLListener] Empty message: {msg_id}")
                await self._ack_message(stream_key, msg_id)
                return

            data = json.loads(raw_data)

            request_id = data.get("request_id")
            response_data_raw = data.get("response_data", {})

            # response_data may be a JSON string (from API serialization)
            if isinstance(response_data_raw, str):
                try:
                    response_data = json.loads(response_data_raw)
                except json.JSONDecodeError:
                    # If not valid JSON, treat as plain string
                    response_data = {"answer": response_data_raw}
            else:
                response_data = response_data_raw

            if not request_id:
                logger.warning(f"[HITLListener] Message missing request_id: {msg_id}")
                await self._ack_message(stream_key, msg_id)
                return

            # Try to deliver to registry
            delivered = await self._registry.deliver_response(
                request_id=request_id,
                response_data=response_data,
            )

            if delivered:
                self._messages_delivered += 1
                logger.info(
                    f"[HITLListener] Delivered response: request_id={request_id}, "
                    f"latency_hint=in-memory"
                )
            else:
                self._messages_skipped += 1
                logger.debug(
                    f"[HITLListener] No local waiter for request: {request_id} "
                    f"(awaiting actor recovery or stream replay)"
                )

            # Always acknowledge the message
            # Even if not delivered locally, stream replay or actor routing can handle it
            await self._ack_message(stream_key, msg_id)

        except json.JSONDecodeError as e:
            logger.error(f"[HITLListener] Invalid JSON in message {msg_id}: {e}")
            self._errors += 1
            await self._ack_message(stream_key, msg_id)
        except Exception as e:
            logger.error(
                f"[HITLListener] Error handling message {msg_id}: {e}",
                exc_info=True,
            )
            self._errors += 1
            # Don't ack on error - message will be redelivered

    async def _ack_message(self, stream_key: str, msg_id: str) -> None:
        """Acknowledge a message in the consumer group."""
        try:
            await self._redis.xack(stream_key, self.CONSUMER_GROUP, msg_id)
        except Exception as e:
            logger.warning(f"[HITLListener] Failed to ack message {msg_id}: {e}")

    def get_stats(self) -> dict[str, Any]:
        """Get listener statistics."""
        return {
            "running": self._running,
            "worker_id": self._worker_id,
            "projects_count": len(self._projects),
            "messages_received": self._messages_received,
            "messages_delivered": self._messages_delivered,
            "messages_skipped": self._messages_skipped,
            "errors": self._errors,
            "delivery_rate": (
                self._messages_delivered / self._messages_received
                if self._messages_received > 0
                else 0.0
            ),
        }


# Global singleton for the current Worker process
_listener_instance: HITLResponseListener | None = None


async def get_hitl_response_listener(
    redis_client: aioredis.Redis | None = None,
) -> HITLResponseListener:
    """
    Get or create the global HITLResponseListener instance.

    Args:
        redis_client: Redis client (required on first call)

    Returns:
        HITLResponseListener instance
    """
    global _listener_instance

    if _listener_instance is None:
        if redis_client is None:
            raise ValueError("redis_client required for first initialization")
        _listener_instance = HITLResponseListener(redis_client)

    return _listener_instance


async def shutdown_hitl_response_listener() -> None:
    """Shutdown the global listener if running."""
    global _listener_instance

    if _listener_instance:
        await _listener_instance.stop()
        _listener_instance = None
