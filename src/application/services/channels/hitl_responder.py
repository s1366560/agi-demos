"""HITL Channel Responder - bridges channel card actions to HITL response flow.

When a user clicks a button on an interactive HITL card in Feishu,
this responder converts the card action into a standard HITL response
using the same flow as the Web UI ``POST /api/v1/agent/hitl/respond``.
"""
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class HITLChannelResponder:
    """Converts channel card actions into HITL responses.

    This class bridges the gap between channel interactions (button clicks)
    and the HITL coordinator's Future-based pausing mechanism. It publishes
    the response to the same Redis stream that the Web UI uses.
    """

    async def respond(
        self,
        request_id: str,
        hitl_type: str,
        response_data: Dict[str, Any],
        *,
        responder_id: Optional[str] = None,
    ) -> bool:
        """Submit a HITL response from a channel interaction.

        Args:
            request_id: The HITL request ID (from the card action value).
            hitl_type: The HITL type (clarification, decision, etc.).
            response_data: The response payload (e.g., {"answer": "PostgreSQL"}).
            responder_id: Optional user ID of the responder.

        Returns:
            True if the response was successfully published.
        """
        try:
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )

            async with async_session_factory() as session:
                return await self._submit_response(
                    session, request_id, hitl_type, response_data, responder_id
                )
        except Exception as e:
            logger.error(
                f"[HITLChannelResponder] Failed to submit response "
                f"for {request_id}: {e}",
                exc_info=True,
            )
            return False

    async def _submit_response(
        self,
        session: Any,
        request_id: str,
        hitl_type: str,
        response_data: Dict[str, Any],
        responder_id: Optional[str],
    ) -> bool:
        """Internal: load request from DB and publish response to Redis."""
        from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
            SqlHITLRequestRepository,
        )

        repo = SqlHITLRequestRepository(session)
        request = await repo.find_by_id(request_id)
        if not request:
            logger.warning(
                f"[HITLChannelResponder] Request not found: {request_id}"
            )
            return False

        if request.status not in ("pending", "PENDING"):
            logger.warning(
                f"[HITLChannelResponder] Request {request_id} "
                f"already in state: {request.status}"
            )
            return False

        # Publish to the same Redis stream used by the Web UI
        try:
            from src.configuration.config import get_settings

            settings = get_settings()
            redis_key = (
                f"hitl:response:{request.tenant_id}:{request.project_id}"
            )

            import json

            import redis.asyncio as aioredis

            redis_client = aioredis.from_url(
                f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}",
                decode_responses=True,
            )
            try:
                await redis_client.xadd(
                    redis_key,
                    {
                        "request_id": request_id,
                        "hitl_type": hitl_type,
                        "response_data": json.dumps(response_data),
                        "source": "channel",
                        "responder_id": responder_id or "",
                    },
                )
                logger.info(
                    f"[HITLChannelResponder] Published response for {request_id} "
                    f"to {redis_key}"
                )
                return True
            finally:
                await redis_client.aclose()
        except Exception as e:
            logger.error(
                f"[HITLChannelResponder] Redis publish failed for {request_id}: {e}"
            )
            return False
