"""HITL Channel Responder - bridges channel card actions to HITL response flow.

When a user clicks a button on an interactive HITL card in Feishu,
this responder converts the card action into a standard HITL response
using the same flow as the Web UI ``POST /api/v1/agent/hitl/respond``.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol

from src.application.services.channels._session import with_session

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.domain.model.agent.hitl_request import HITLRequest


class HITLChannelResponseOutcome(str, Enum):
    """Channel-facing outcome for a HITL card action."""

    QUEUED = "queued"
    DELIVERY_PENDING = "delivery_pending"
    REJECTED = "rejected"


class _HITLRequestRepository(Protocol):
    """Minimal repository protocol for channel HITL response flow."""

    async def get_by_id(self, request_id: str) -> HITLRequest | None: ...

    async def update_response(
        self,
        request_id: str,
        response: str,
        response_metadata: dict[str, Any] | None = None,
    ) -> HITLRequest | None: ...

    async def mark_timeout(self, request_id: str) -> HITLRequest | None: ...


class HITLChannelResponder:
    """Converts channel card actions into HITL responses.

    This class bridges the gap between channel interactions (button clicks)
    and the HITL coordinator's Future-based pausing mechanism. It publishes
    the response to the same Redis stream that the Web UI uses.

    Optional tenant/project hints from the card payload are treated as
    consistency checks, but the responder always loads the authoritative HITL
    request from the database before claiming and publishing the response.
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
    ) -> HITLChannelResponseOutcome:
        """Submit a HITL response from a channel interaction.

        Args:
            request_id: The HITL request ID (from the card action value).
            hitl_type: The HITL type (clarification, decision, etc.).
            response_data: The response payload (e.g., {"answer": "PostgreSQL"}).
            tenant_id: Tenant ID hint from the card button value.
            project_id: Project ID hint from the card button value.
            responder_id: Optional user ID of the responder.

        Returns:
            Delivery outcome describing whether the response was queued,
            persisted for later delivery, or rejected.
        """
        try:
            async with with_session() as session:
                return await self._submit_response(
                    session,
                    request_id,
                    hitl_type,
                    response_data,
                    responder_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                )
        except Exception as e:
            logger.error(
                f"[HITLChannelResponder] Failed to submit response for {request_id}: {e}",
                exc_info=True,
            )
            return HITLChannelResponseOutcome.REJECTED

    async def _submit_response(
        self,
        session: AsyncSession,
        request_id: str,
        hitl_type: str,
        response_data: dict[str, Any],
        responder_id: str | None,
        *,
        tenant_id: str | None,
        project_id: str | None,
    ) -> HITLChannelResponseOutcome:
        """Internal: load, validate, claim, and publish a HITL response."""
        from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
            SqlHITLRequestRepository,
        )

        repo = SqlHITLRequestRepository(session)
        hitl_request = await self._load_validated_request(
            session=session,
            repo=repo,
            request_id=request_id,
            hitl_type=hitl_type,
            response_data=response_data,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        if hitl_request is None:
            return HITLChannelResponseOutcome.REJECTED

        if not await self._is_authorized_responder(
            session=session,
            hitl_request=hitl_request,
            responder_id=responder_id,
        ):
            return HITLChannelResponseOutcome.REJECTED

        validated_response = self._validate_and_summarize_response(
            hitl_request=hitl_request,
            hitl_type=hitl_type,
            response_data=response_data,
        )
        if validated_response is None:
            return HITLChannelResponseOutcome.REJECTED
        stored_hitl_type, response_str, response_metadata = validated_response
        updated_request = await repo.update_response(
            request_id,
            response_str,
            response_metadata=response_metadata,
        )
        if updated_request is None:
            logger.warning(
                "[HITLChannelResponder] Request %s could not be claimed for response",
                request_id,
            )
            return HITLChannelResponseOutcome.REJECTED
        await session.commit()

        redis_sent = await self._publish_to_redis(
            request_id,
            stored_hitl_type,
            response_data,
            hitl_request.tenant_id,
            hitl_request.project_id,
            hitl_request.conversation_id,
            hitl_request.message_id,
            responder_id,
        )
        if not redis_sent:
            logger.warning(
                "[HITLChannelResponder] Publish failed for %s; leaving request answered",
                request_id,
            )
            return HITLChannelResponseOutcome.DELIVERY_PENDING

        return HITLChannelResponseOutcome.QUEUED

    async def _load_validated_request(  # noqa: PLR0911
        self,
        *,
        session: AsyncSession,
        repo: _HITLRequestRepository,
        request_id: str,
        hitl_type: str,
        response_data: dict[str, Any],
        tenant_id: str | None,
        project_id: str | None,
    ) -> HITLRequest | None:
        """Return a pending request when hints and basic shape checks are valid."""
        hitl_request = await repo.get_by_id(request_id)
        if hitl_request is None:
            logger.warning(f"[HITLChannelResponder] Request not found: {request_id}")
            return None

        if not self._is_pending_request(hitl_request):
            return None

        if await self._mark_timeout_if_expired(
            session=session,
            repo=repo,
            hitl_request=hitl_request,
        ):
            logger.warning(
                "[HITLChannelResponder] Request %s expired before channel response",
                request_id,
            )
            return None

        if not self._request_hints_match(
            hitl_request=hitl_request,
            request_id=request_id,
            tenant_id=tenant_id,
            project_id=project_id,
        ):
            return None

        stored_hitl_type = self._trusted_hitl_type(hitl_request)
        if stored_hitl_type is None or stored_hitl_type != hitl_type:
            logger.warning(
                "[HITLChannelResponder] HITL type mismatch for %s: stored=%s received=%s",
                request_id,
                stored_hitl_type,
                hitl_type,
            )
            return None

        if not self._validate_response_shape(stored_hitl_type, response_data):
            return None

        return hitl_request

    async def _mark_timeout_if_expired(
        self,
        *,
        session: AsyncSession,
        repo: _HITLRequestRepository,
        hitl_request: HITLRequest,
    ) -> bool:
        """Mark expired requests timed out before any late response can claim them."""
        expires_at = getattr(hitl_request, "expires_at", None)
        if expires_at is None or expires_at > datetime.now(UTC):
            return False
        timed_out_request = await repo.mark_timeout(hitl_request.id)
        if timed_out_request is not None:
            await session.commit()
        return True

    async def _is_authorized_responder(
        self,
        *,
        session: AsyncSession,
        hitl_request: HITLRequest,
        responder_id: str | None,
    ) -> bool:
        """Fail closed unless the channel responder matches the trusted request binding."""
        from src.infrastructure.adapters.secondary.persistence.models import Conversation

        if not responder_id:
            logger.warning(
                "[HITLChannelResponder] Missing responder_id for channel HITL request %s",
                hitl_request.id,
            )
            return False

        expected_responder = getattr(hitl_request, "user_id", None)
        if not isinstance(expected_responder, str) or not expected_responder:
            conversation = await session.get(Conversation, hitl_request.conversation_id)
            if conversation is None:
                logger.warning(
                    "[HITLChannelResponder] Conversation %s not found for HITL request %s",
                    hitl_request.conversation_id,
                    hitl_request.id,
                )
                return False

            conversation_meta = conversation.meta if isinstance(conversation.meta, dict) else {}
            expected_responder = conversation_meta.get("sender_id")
            if not isinstance(expected_responder, str) or not expected_responder:
                logger.warning(
                    "[HITLChannelResponder] Conversation %s has no trusted sender binding",
                    hitl_request.conversation_id,
                )
                return False

        if responder_id != expected_responder:
            logger.warning(
                "[HITLChannelResponder] Unauthorized responder for %s: expected=%s got=%s",
                hitl_request.id,
                expected_responder,
                responder_id,
            )
            return False

        return True

    @staticmethod
    def _is_pending_request(hitl_request: HITLRequest) -> bool:
        """Return True when the HITL request is still pending."""
        request_status = getattr(hitl_request.status, "value", hitl_request.status)
        if request_status in ("pending", "PENDING"):
            return True
        logger.warning(
            "[HITLChannelResponder] Request %s already in state: %s",
            hitl_request.id,
            hitl_request.status,
        )
        return False

    @staticmethod
    def _request_hints_match(
        *,
        hitl_request: HITLRequest,
        request_id: str,
        tenant_id: str | None,
        project_id: str | None,
    ) -> bool:
        """Return True when tenant/project hints match the stored request."""
        if tenant_id and tenant_id != hitl_request.tenant_id:
            logger.warning(
                "[HITLChannelResponder] Tenant hint mismatch for %s: %s != %s",
                request_id,
                tenant_id,
                hitl_request.tenant_id,
            )
            return False
        if project_id and project_id != hitl_request.project_id:
            logger.warning(
                "[HITLChannelResponder] Project hint mismatch for %s: %s != %s",
                request_id,
                project_id,
                hitl_request.project_id,
            )
            return False
        return True

    def _validate_and_summarize_response(
        self,
        *,
        hitl_request: HITLRequest,
        hitl_type: str,
        response_data: dict[str, Any],
    ) -> tuple[str, str, dict[str, Any] | None] | None:
        """Return stored type plus persistence payload when the response is valid."""
        from src.domain.model.agent.hitl_types import HITLType
        from src.infrastructure.agent.hitl.coordinator import validate_hitl_response
        from src.infrastructure.agent.hitl.utils import (
            build_hitl_request_data_from_record,
            summarize_hitl_response,
        )

        stored_hitl_type = self._trusted_hitl_type(hitl_request)
        if stored_hitl_type is None:
            return None

        request_data = build_hitl_request_data_from_record(hitl_request)
        is_valid, validation_error = validate_hitl_response(
            hitl_type=HITLType(stored_hitl_type),
            request_data=request_data,
            response_data=response_data,
            conversation_id=hitl_request.conversation_id,
            tenant_id=hitl_request.tenant_id,
            project_id=hitl_request.project_id,
            message_id=hitl_request.message_id,
            received_tenant_id=hitl_request.tenant_id,
            received_project_id=hitl_request.project_id,
            received_conversation_id=hitl_request.conversation_id,
            received_message_id=hitl_request.message_id,
        )
        if not is_valid:
            logger.warning(
                "[HITLChannelResponder] Rejected invalid response for %s: %s",
                hitl_request.id,
                validation_error or "invalid HITL response",
            )
            return None

        response_str, response_metadata = summarize_hitl_response(stored_hitl_type, response_data)
        return stored_hitl_type, response_str, response_metadata

    @staticmethod
    def _trusted_hitl_type(hitl_request: HITLRequest) -> str | None:
        """Return the logical HITL type persisted with the request."""
        from src.infrastructure.agent.hitl.utils import resolve_trusted_hitl_type

        return resolve_trusted_hitl_type(hitl_request)

    @staticmethod
    def _validate_response_shape(hitl_type: str, response_data: dict[str, Any]) -> bool:
        """Return False when ingress payload shape is invalid."""
        has_cancelled = response_data.get("cancelled") is True
        has_timeout = response_data.get("timeout") is True

        if hitl_type != "env_var" and (has_cancelled or has_timeout):
            return False

        if hitl_type != "env_var":
            return True

        has_values = "values" in response_data
        variant_count = sum((has_values, has_cancelled, has_timeout))
        if variant_count != 1:
            return False

        return not has_values or isinstance(response_data.get("values"), dict)

    async def _publish_to_redis(
        self,
        request_id: str,
        hitl_type: str,
        response_data: dict[str, Any],
        tenant_id: str,
        project_id: str,
        conversation_id: str,
        message_id: str | None,
        responder_id: str | None,
    ) -> bool:
        """Publish HITL response to the Redis stream.

        Uses the same ``{"data": json.dumps(payload)}`` envelope as the
        WebSocket and REST HITL handlers so that
        ``LocalHITLResumeConsumer._handle_message()`` can parse it.
        """
        try:
            from src.configuration.config import get_settings
            from src.infrastructure.agent.hitl.utils import serialize_hitl_stream_response

            settings = get_settings()
            redis_key = f"hitl:response:{tenant_id}:{project_id}"

            import redis.asyncio as aioredis

            redis_client = aioredis.from_url(  # type: ignore[no-untyped-call]  # redis stubs incomplete
                f"redis://{settings.redis_host}:{settings.redis_port}",
                decode_responses=True,
            )
            published = False
            try:
                message_data: dict[str, Any] = {
                    "request_id": request_id,
                    "hitl_type": hitl_type,
                    "source": "channel",
                    "responder_id": responder_id or "",
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                }
                message_data.update(serialize_hitl_stream_response(hitl_type, response_data))
                await redis_client.xadd(
                    redis_key,
                    {"data": json.dumps(message_data)},
                    maxlen=1000,
                )
                published = True
                logger.info(
                    f"[HITLChannelResponder] Published response for {request_id} to {redis_key}"
                )
                return True
            finally:
                try:
                    await redis_client.aclose()
                except Exception:
                    logger.warning(
                        "[HITLChannelResponder] Redis close failed for %s after publish=%s",
                        request_id,
                        published,
                        exc_info=True,
                    )
                    if not published:
                        raise
        except Exception as e:
            logger.error(f"[HITLChannelResponder] Redis publish failed for {request_id}: {e}")
            return False
