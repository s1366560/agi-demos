"""Ray HITL Handler for Actor-based agent runtime."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from src.domain.model.agent.hitl_request import HITLRequest as HITLRequestEntity
from src.domain.model.agent.hitl_request import HITLRequestType
from src.domain.model.agent.hitl_types import (
    HITLPendingException,
    HITLRequest,
    HITLType,
)
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


class RayHITLHandler:
    """HITL handler that persists requests and raises HITLPendingException."""

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
        emit_sse_callback: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
        preinjected_response: Optional[Dict[str, Any]] = None,
    ):
        self.conversation_id = conversation_id
        self.tenant_id = tenant_id
        self.project_id = project_id
        self.message_id = message_id
        self.default_timeout = default_timeout
        self._emit_sse_callback = emit_sse_callback
        self._preinjected_response = preinjected_response
        self._pending_requests: Dict[str, HITLRequest] = {}

    def peek_preinjected_response(self, hitl_type: HITLType) -> Optional[Dict[str, Any]]:
        """Return preinjected response if it matches the HITL type (non-consuming)."""
        if not self._preinjected_response:
            return None
        if self._preinjected_response.get("hitl_type") != hitl_type.value:
            return None
        return self._preinjected_response

    def _get_strategy(self, hitl_type: HITLType) -> HITLTypeStrategy:
        strategy = self._strategies.get(hitl_type)
        if not strategy:
            raise ValueError(f"No strategy registered for HITL type: {hitl_type}")
        return strategy

    async def request_clarification(
        self,
        question: str,
        options: Optional[List[Any]] = None,
        clarification_type: str = "custom",
        allow_custom: bool = True,
        timeout_seconds: Optional[float] = None,
        context: Optional[Dict[str, Any]] = None,
        default_value: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> str:
        request_data = {
            "question": question,
            "options": options or [],
            "clarification_type": clarification_type,
            "allow_custom": allow_custom,
            "context": context or {},
            "default_value": default_value,
        }
        if request_id:
            request_data["_request_id"] = request_id

        return await self._execute_hitl_request(
            HITLType.CLARIFICATION,
            request_data,
            timeout_seconds or self.default_timeout,
        )

    async def request_decision(
        self,
        question: str,
        options: List[Any],
        decision_type: str = "single_choice",
        allow_custom: bool = False,
        timeout_seconds: Optional[float] = None,
        context: Optional[Dict[str, Any]] = None,
        default_option: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> str:
        request_data = {
            "question": question,
            "options": options,
            "decision_type": decision_type,
            "allow_custom": allow_custom,
            "context": context or {},
            "default_option": default_option,
        }
        if request_id:
            request_data["_request_id"] = request_id

        return await self._execute_hitl_request(
            HITLType.DECISION,
            request_data,
            timeout_seconds or self.default_timeout,
        )

    async def request_env_vars(
        self,
        tool_name: str,
        fields: List[Dict[str, Any]],
        message: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        allow_save: bool = True,
        request_id: Optional[str] = None,
    ) -> Dict[str, str]:
        request_data = {
            "tool_name": tool_name,
            "fields": fields,
            "message": message,
            "allow_save": allow_save,
        }
        if request_id:
            request_data["_request_id"] = request_id

        return await self._execute_hitl_request(
            HITLType.ENV_VAR,
            request_data,
            timeout_seconds or self.default_timeout,
        )

    async def request_permission(
        self,
        tool_name: str,
        action: str,
        risk_level: str = "medium",
        description: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        timeout_seconds: Optional[float] = None,
        allow_remember: bool = True,
    ) -> bool:
        request_data = {
            "tool_name": tool_name,
            "action": action,
            "risk_level": risk_level,
            "description": description,
            "details": details or {},
            "allow_remember": allow_remember,
        }

        return await self._execute_hitl_request(
            HITLType.PERMISSION,
            request_data,
            timeout_seconds or 60.0,
        )

    async def _execute_hitl_request(
        self,
        hitl_type: HITLType,
        request_data: Dict[str, Any],
        timeout_seconds: float,
    ) -> Any:
        strategy = self._get_strategy(hitl_type)

        if self._preinjected_response:
            preinjected = self._preinjected_response
            preinjected_type = preinjected.get("hitl_type", "")
            preinjected_data = preinjected.get("response_data", {})

            if preinjected_type == hitl_type.value:
                # Consume the preinjected response
                self._preinjected_response = None
                logger.info(
                    f"[RayHITL] Using pre-injected response for {hitl_type.value}: "
                    f"request_id={preinjected.get('request_id')}"
                )
                if preinjected_data.get("cancelled") or preinjected_data.get("timeout"):
                    request = strategy.create_request(
                        conversation_id=self.conversation_id,
                        request_data=request_data,
                        timeout_seconds=timeout_seconds,
                        tenant_id=self.tenant_id,
                        project_id=self.project_id,
                        message_id=self.message_id,
                    )
                    return strategy.get_default_response(request)
                return strategy.extract_response_value(preinjected_data)
            else:
                # Type mismatch - log warning but don't consume
                logger.warning(
                    f"[RayHITL] Pre-injected response type mismatch: "
                    f"expected={hitl_type.value}, got={preinjected_type}"
                )

        request = strategy.create_request(
            conversation_id=self.conversation_id,
            request_data=request_data,
            timeout_seconds=timeout_seconds,
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            message_id=self.message_id,
        )

        self._pending_requests[request.request_id] = request

        try:
            await _persist_hitl_request(
                request_id=request.request_id,
                hitl_type=request.hitl_type,
                conversation_id=request.conversation_id,
                tenant_id=self.tenant_id,
                project_id=self.project_id,
                message_id=request.message_id,
                timeout_seconds=timeout_seconds,
                type_data=request.type_specific_data,
                created_at=datetime.utcnow(),
            )

            await _emit_hitl_sse_event(
                request_id=request.request_id,
                hitl_type=request.hitl_type,
                conversation_id=request.conversation_id,
                tenant_id=self.tenant_id,
                project_id=self.project_id,
                type_data=request.type_specific_data,
                timeout_seconds=timeout_seconds,
            )

            raise HITLPendingException(
                request_id=request.request_id,
                hitl_type=request.hitl_type,
                request_data=request.type_specific_data,
                conversation_id=request.conversation_id,
                message_id=request.message_id,
                timeout_seconds=timeout_seconds,
            )

        finally:
            self._pending_requests.pop(request.request_id, None)

    def get_pending_requests(self) -> List[HITLRequest]:
        return list(self._pending_requests.values())

    async def cancel_request(self, request_id: str, reason: Optional[str] = None) -> bool:
        if request_id not in self._pending_requests:
            return False

        if self._emit_sse_callback:
            await self._emit_sse_callback(
                "hitl_cancelled",
                {
                    "request_id": request_id,
                    "reason": reason,
                },
            )

        self._pending_requests.pop(request_id, None)
        return True


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
        question = type_data.get("message") or "Please provide environment variables"

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
            logger.warning("[RayHITL] Redis client not available for SSE event")
    except Exception as e:
        logger.error(f"[RayHITL] Failed to publish SSE event: {e}")
