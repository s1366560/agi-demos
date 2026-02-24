"""HITL Channel Responder - bridges channel card actions to HITL response flow.

When a user clicks a button on an interactive HITL card in Feishu,
this responder converts the card action into a standard HITL response
using the same flow as the Web UI ``POST /api/v1/agent/hitl/respond``.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class HITLChannelResponder:
    """Converts channel card actions into HITL responses.

    This class bridges the gap between channel interactions (button clicks)
    and the HITL coordinator's Future-based pausing mechanism. It publishes
    the response to the same Redis stream that the Web UI uses.

    When ``tenant_id`` and ``project_id`` are provided (embedded in card
    button values), the responder publishes directly to Redis without any
    database query. This avoids cross-event-loop errors when the Feishu SDK
    invokes the card callback on its own event loop.
    """

    async def respond(
        self,
        request_id: str,
        hitl_type: str,
        response_data: dict[str, Any],
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
        responder_id: str | None = None,
    ) -> bool:
        """Submit a HITL response from a channel interaction.

        Args:
            request_id: The HITL request ID (from the card action value).
            hitl_type: The HITL type (clarification, decision, etc.).
            response_data: The response payload (e.g., {"answer": "PostgreSQL"}).
            tenant_id: Tenant ID (from card button value). Skips DB when provided.
            project_id: Project ID (from card button value). Skips DB when provided.
            responder_id: Optional user ID of the responder.

        Returns:
            True if the response was successfully published.
        """
        try:
            if tenant_id and project_id:
                # Direct Redis publish — no DB needed (safe on any event loop)
                return await self._publish_to_redis(
                    request_id,
                    hitl_type,
                    response_data,
                    tenant_id,
                    project_id,
                    responder_id,
                )

            # Fallback: look up tenant_id/project_id from DB
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )

            async with async_session_factory() as session:
                return await self._submit_response(
                    session, request_id, hitl_type, response_data, responder_id
                )
        except Exception as e:
            logger.error(
                f"[HITLChannelResponder] Failed to submit response for {request_id}: {e}",
                exc_info=True,
            )
            return False

    async def _submit_response(
        self,
        session: AsyncSession,
        request_id: str,
        hitl_type: str,
        response_data: dict[str, Any],
        responder_id: str | None,
    ) -> bool:
        """Internal: load request from DB and publish response to Redis."""
        from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
            SqlHITLRequestRepository,
        )

        repo = SqlHITLRequestRepository(session)
        request = await repo.get_by_id(request_id)
        if not request:
            logger.warning(f"[HITLChannelResponder] Request not found: {request_id}")
            return False

        if request.status not in ("pending", "PENDING"):
            logger.warning(
                f"[HITLChannelResponder] Request {request_id} already in state: {request.status}"
            )
            return False

        return await self._publish_to_redis(
            request_id,
            hitl_type,
            response_data,
            request.tenant_id,
            request.project_id,
            responder_id,
        )

    async def _publish_to_redis(
        self,
        request_id: str,
        hitl_type: str,
        response_data: dict[str, Any],
        tenant_id: str,
        project_id: str,
        responder_id: str | None,
    ) -> bool:
        """Publish HITL response to the Redis stream.

        Uses the same ``{"data": json.dumps(payload)}`` envelope as the
        WebSocket and REST HITL handlers so that
        ``LocalHITLResumeConsumer._handle_message()`` can parse it.
        """
        try:
            from src.configuration.config import get_settings

            settings = get_settings()
            redis_key = f"hitl:response:{tenant_id}:{project_id}"

            import redis.asyncio as aioredis

            redis_client = aioredis.from_url(
                f"redis://{settings.redis_host}:{settings.redis_port}",
                decode_responses=True,
            )
            try:
                message_data = {
                    "request_id": request_id,
                    "hitl_type": hitl_type,
                    "response_data": json.dumps(response_data),
                    "source": "channel",
                    "responder_id": responder_id or "",
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                }
                await redis_client.xadd(
                    redis_key,
                    {"data": json.dumps(message_data)},
                    maxlen=1000,
                )
                logger.info(
                    f"[HITLChannelResponder] Published response for {request_id} to {redis_key}"
                )
                return True
            finally:
                await redis_client.aclose()
        except Exception as e:
            logger.error(f"[HITLChannelResponder] Redis publish failed for {request_id}: {e}")
            return False
