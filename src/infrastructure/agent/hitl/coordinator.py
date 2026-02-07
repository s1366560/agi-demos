"""
HITLCoordinator - Future-based cooperative HITL management.

Replaces the exception-based HITLPendingException flow with asyncio.Future-based
cooperative yielding. The processor generator stays alive while waiting for user
input, enabling clean consecutive HITL support.

Architecture:
    Tool → coordinator.request() → creates Future, persists request
    Tool yields hitl_asked event → generator yields to caller
    Caller saves state for crash recovery
    Redis listener → coordinator.resolve(request_id, data) → Future resolves
    Tool continues → yields hitl_answered event → processor continues
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.domain.model.agent.hitl_request import HITLRequest as HITLRequestEntity, HITLRequestType
from src.domain.model.agent.hitl_types import HITLType
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
    SqlHITLRequestRepository,
)
from src.infrastructure.adapters.secondary.temporal.agent_worker_state import get_redis_client
from src.infrastructure.agent.hitl.temporal_hitl_handler import (
    ClarificationStrategy,
    DecisionStrategy,
    EnvVarStrategy,
    HITLTypeStrategy,
    PermissionStrategy,
)

logger = logging.getLogger(__name__)


class HITLCoordinator:
    """Manages HITL request Futures for cooperative pausing.

    Each HITL tool call creates a Future via `request()`. The tool awaits the
    Future, which blocks the async generator without unwinding the stack.
    When the user responds, `resolve()` sets the Future result, unblocking
    the generator naturally.
    """

    _strategies: Dict[HITLType, HITLTypeStrategy] = {
        HITLType.CLARIFICATION: ClarificationStrategy(),
        HITLType.DECISION: DecisionStrategy(),
        HITLType.ENV_VAR: EnvVarStrategy(),
        HITLType.PERMISSION: PermissionStrategy(),
    }

    def __init__(
        self,
        conversation_id: str,
        tenant_id: str,
        project_id: str,
        message_id: Optional[str] = None,
        default_timeout: float = 300.0,
    ):
        self.conversation_id = conversation_id
        self.tenant_id = tenant_id
        self.project_id = project_id
        self.message_id = message_id
        self.default_timeout = default_timeout
        self._pending: Dict[str, asyncio.Future] = {}

    def _get_strategy(self, hitl_type: HITLType) -> HITLTypeStrategy:
        strategy = self._strategies.get(hitl_type)
        if not strategy:
            raise ValueError(f"No strategy registered for HITL type: {hitl_type}")
        return strategy

    async def request(
        self,
        hitl_type: HITLType,
        request_data: Dict[str, Any],
        timeout_seconds: Optional[float] = None,
    ) -> Any:
        """Create a pending HITL request and return an awaitable Future.

        Persists the request to the database and publishes an SSE event, then
        returns a Future that will be resolved when ``resolve()`` is called with
        the matching ``request_id``.

        Returns the response value extracted by the type strategy.
        Raises ``asyncio.TimeoutError`` if the user doesn't respond in time.
        """
        timeout = timeout_seconds or self.default_timeout
        strategy = self._get_strategy(hitl_type)

        hitl_request = strategy.create_request(
            conversation_id=self.conversation_id,
            request_data=request_data,
            timeout_seconds=timeout,
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            message_id=self.message_id,
        )
        request_id = hitl_request.request_id

        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[request_id] = fut
        register_coordinator(request_id, self)

        try:
            await _persist_hitl_request(
                request_id=request_id,
                hitl_type=hitl_type,
                conversation_id=self.conversation_id,
                tenant_id=self.tenant_id,
                project_id=self.project_id,
                message_id=self.message_id,
                timeout_seconds=timeout,
                type_data=hitl_request.type_specific_data,
                created_at=datetime.utcnow(),
            )

            await _emit_hitl_sse_event(
                request_id=request_id,
                hitl_type=hitl_type,
                conversation_id=self.conversation_id,
                tenant_id=self.tenant_id,
                project_id=self.project_id,
                type_data=hitl_request.type_specific_data,
                timeout_seconds=timeout,
            )
        except Exception:
            self._pending.pop(request_id, None)
            unregister_coordinator(request_id)
            raise

        logger.info(
            f"[HITLCoordinator] Waiting for response: "
            f"type={hitl_type.value}, request_id={request_id}, "
            f"timeout={timeout}s"
        )

        try:
            response_data = await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(
                f"[HITLCoordinator] Timeout waiting for {hitl_type.value} request_id={request_id}"
            )
            return strategy.get_default_response(hitl_request)
        finally:
            self._pending.pop(request_id, None)
            unregister_coordinator(request_id)

        logger.info(
            f"[HITLCoordinator] Received response for {hitl_type.value}: request_id={request_id}"
        )

        if response_data.get("cancelled") or response_data.get("timeout"):
            return strategy.get_default_response(hitl_request)

        return strategy.extract_response_value(response_data)

    def resolve(self, request_id: str, response_data: Dict[str, Any]) -> bool:
        """Resolve a pending HITL Future with user response data.

        Returns True if the request was found and resolved, False otherwise.
        """
        fut = self._pending.get(request_id)
        if fut is None:
            logger.warning(f"[HITLCoordinator] No pending future for request_id={request_id}")
            return False

        if fut.done():
            logger.warning(f"[HITLCoordinator] Future already done for request_id={request_id}")
            return False

        fut.set_result(response_data)
        logger.info(f"[HITLCoordinator] Resolved future for request_id={request_id}")
        return True

    def cancel_all(self, reason: str = "cancelled") -> int:
        """Cancel all pending Futures. Returns count of cancelled requests."""
        count = 0
        for req_id, fut in list(self._pending.items()):
            if not fut.done():
                fut.set_result({"cancelled": True, "reason": reason})
                count += 1
        self._pending.clear()
        return count

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def pending_request_ids(self) -> List[str]:
        return list(self._pending.keys())

    def get_request_data(self, request_id: str) -> Optional[Dict[str, Any]]:
        """Get the HITLRequest data for a pending request (for state saving)."""
        return {"request_id": request_id} if request_id in self._pending else None


# ---------------------------------------------------------------------------
# Global coordinator registry (keyed by request_id for response routing)
# ---------------------------------------------------------------------------

_coordinator_registry: Dict[str, HITLCoordinator] = {}


def register_coordinator(request_id: str, coordinator: HITLCoordinator) -> None:
    """Register a coordinator for a pending request."""
    _coordinator_registry[request_id] = coordinator


def unregister_coordinator(request_id: str) -> None:
    """Unregister a coordinator for a completed/cancelled request."""
    _coordinator_registry.pop(request_id, None)


def resolve_by_request_id(request_id: str, response_data: Dict[str, Any]) -> bool:
    """Resolve a pending HITL request by request_id using the global registry.

    Returns True if the request was found and resolved, False otherwise.
    """
    coordinator = _coordinator_registry.get(request_id)
    if coordinator is None:
        logger.warning(f"[HITLCoordinator] No coordinator registered for request_id={request_id}")
        return False
    return coordinator.resolve(request_id, response_data)


# ---------------------------------------------------------------------------
# Persistence helpers (moved from ray_hitl_handler.py to share)
# ---------------------------------------------------------------------------


async def _persist_hitl_request(
    request_id: str,
    hitl_type: HITLType,
    conversation_id: str,
    tenant_id: str,
    project_id: str,
    message_id: Optional[str],
    timeout_seconds: float,
    type_data: Dict[str, Any],
    created_at: datetime,
) -> None:
    type_mapping = {
        "clarification": HITLRequestType.CLARIFICATION,
        "decision": HITLRequestType.DECISION,
        "env_var": HITLRequestType.ENV_VAR,
    }
    request_type = type_mapping.get(hitl_type.value, HITLRequestType.CLARIFICATION)

    question = type_data.get("question", "")
    if not question and hitl_type.value == "env_var":
        question = type_data.get("message", "Please provide environment variables")

    entity = HITLRequestEntity(
        id=request_id,
        request_type=request_type,
        conversation_id=conversation_id,
        message_id=message_id,
        tenant_id=tenant_id,
        project_id=project_id,
        question=question,
        options=type_data.get("options", []),
        context=type_data.get("context", {}),
        metadata={
            "hitl_type": hitl_type.value,
            **{k: v for k, v in type_data.items() if k not in ("question", "options", "context")},
        },
        created_at=created_at,
        expires_at=created_at + timedelta(seconds=timeout_seconds),
    )

    async with async_session_factory() as session:
        repo = SqlHITLRequestRepository(session)
        await repo.create(entity)
        await session.commit()


async def _emit_hitl_sse_event(
    request_id: str,
    hitl_type: HITLType,
    conversation_id: str,
    tenant_id: str,
    project_id: str,
    type_data: Dict[str, Any],
    timeout_seconds: float,
) -> None:
    event_type_mapping = {
        "clarification": "clarification_asked",
        "decision": "decision_asked",
        "env_var": "env_var_requested",
        "permission": "permission_asked",
    }
    event_type = event_type_mapping.get(hitl_type.value, "clarification_asked")

    event_data = {
        "request_id": request_id,
        "timeout_seconds": timeout_seconds,
        **type_data,
    }

    await _publish_to_unified_event_bus(
        event_type=event_type,
        conversation_id=conversation_id,
        data=event_data,
    )


async def _publish_to_unified_event_bus(
    event_type: str,
    conversation_id: str,
    data: Dict[str, Any],
) -> None:
    try:
        from src.domain.events.envelope import EventEnvelope
        from src.domain.ports.services.unified_event_bus_port import RoutingKey
        from src.infrastructure.adapters.secondary.messaging.redis_unified_event_bus import (
            RedisUnifiedEventBusAdapter,
        )

        redis_client = await get_redis_client()
        if redis_client:
            event_bus = RedisUnifiedEventBusAdapter(redis_client)
            envelope = EventEnvelope(
                event_type=event_type,
                payload=data,
                metadata={"conversation_id": conversation_id},
            )
            routing_key = RoutingKey(
                namespace="agent",
                entity_id=conversation_id,
            )
            await event_bus.publish(event=envelope, routing_key=routing_key)
        else:
            logger.warning("[HITLCoordinator] Redis client not available for SSE event")
    except Exception as e:
        logger.error(f"[HITLCoordinator] Failed to publish SSE event: {e}")
