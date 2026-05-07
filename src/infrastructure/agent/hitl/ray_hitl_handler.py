"""Ray HITL Handler for Actor-based agent runtime."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, cast

from src.domain.model.agent.hitl_request import HITLRequest as HITLRequestEntity, HITLRequestType
from src.domain.model.agent.hitl_types import (
    DecisionType,
    HITLPendingException,
    HITLRequest,
    HITLType,
    PermissionAction,
)
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
    SqlHITLRequestRepository,
)
from src.infrastructure.agent.hitl.hitl_strategies import (
    A2UIActionStrategy,
    ClarificationStrategy,
    DecisionStrategy,
    EnvVarStrategy,
    HITLTypeStrategy,
    PermissionStrategy,
)
from src.infrastructure.agent.hitl.utils import build_stable_hitl_request_id
from src.infrastructure.agent.state.agent_worker_state import get_redis_client

logger = logging.getLogger(__name__)


class RayHITLHandler:
    """HITL handler that persists requests and raises HITLPendingException."""

    _strategies: ClassVar[dict[HITLType, HITLTypeStrategy]] = {
        HITLType.CLARIFICATION: ClarificationStrategy(),
        HITLType.DECISION: DecisionStrategy(),
        HITLType.ENV_VAR: EnvVarStrategy(),
        HITLType.PERMISSION: PermissionStrategy(),
        HITLType.A2UI_ACTION: A2UIActionStrategy(),
    }

    def __init__(
        self,
        conversation_id: str,
        tenant_id: str,
        project_id: str,
        message_id: str | None = None,
        default_timeout: float = 300.0,
        emit_sse_callback: Callable[[str, dict[str, Any]], Any] | None = None,
        preinjected_response: dict[str, Any] | None = None,
    ) -> None:
        self.conversation_id = conversation_id
        self.tenant_id = tenant_id
        self.project_id = project_id
        self.message_id = message_id
        self.default_timeout = default_timeout
        self._emit_sse_callback = emit_sse_callback
        self._preinjected_state: dict[str, dict[str, Any] | None] = {
            "response": preinjected_response,
        }
        self._pending_requests: dict[str, HITLRequest] = {}
        self._request_sequence = 0

    @property
    def _preinjected_response(self) -> dict[str, Any] | None:
        """Backward-compatible view of the shared preinjected response state."""
        return self._preinjected_state["response"]

    @_preinjected_response.setter
    def _preinjected_response(self, value: dict[str, Any] | None) -> None:
        """Update the shared preinjected response state."""
        self._preinjected_state["response"] = value

    def peek_preinjected_response(self, hitl_type: HITLType) -> dict[str, Any] | None:
        """Return preinjected response if it matches the HITL type (non-consuming)."""
        if not self._preinjected_response:
            return None
        if self._preinjected_response.get("hitl_type") != hitl_type.value:
            return None
        return self._preinjected_response

    def with_scope(
        self,
        *,
        tenant_id: str,
        project_id: str | None,
        conversation_id: str | None = None,
        message_id: str | None = None,
    ) -> RayHITLHandler:
        """Clone the handler for a different tenant/project without losing HITL state."""
        scoped_handler = RayHITLHandler(
            conversation_id=conversation_id or self.conversation_id,
            tenant_id=tenant_id,
            project_id=project_id or "",
            message_id=self.message_id if message_id is None else message_id,
            default_timeout=self.default_timeout,
            emit_sse_callback=self._emit_sse_callback,
        )
        scoped_handler._preinjected_state = self._preinjected_state
        return scoped_handler

    def _clear_preinjected_response(self) -> None:
        """Clear the shared preinjected response state."""
        self._preinjected_response = None

    def _matches_preinjected_request(
        self,
        *,
        hitl_type: HITLType,
        preinjected: dict[str, Any],
        request_data: dict[str, Any],
    ) -> bool:
        """Return True when a preinjected response matches the current HITL request."""
        preinjected_type = str(preinjected.get("hitl_type", "") or "")
        if preinjected_type != hitl_type.value:
            logger.warning(
                "[RayHITL] Pre-injected response type mismatch: expected=%s, got=%s",
                hitl_type.value,
                preinjected_type,
            )
            return False

        request_id = request_data.get("_request_id")
        request_id_str = request_id if isinstance(request_id, str) and request_id else None
        if request_id_str is None:
            logger.warning(
                "[RayHITL] Pre-injected response ignored without explicit request_id: type=%s",
                hitl_type.value,
            )
            return False

        preinjected_request_id = preinjected.get("request_id")
        preinjected_request_id_str = (
            preinjected_request_id
            if isinstance(preinjected_request_id, str) and preinjected_request_id
            else None
        )
        if preinjected_request_id_str != request_id_str:
            logger.warning(
                "[RayHITL] Pre-injected response request_id mismatch: expected=%s, got=%s",
                request_id_str,
                preinjected_request_id_str,
            )
            return False

        identity_checks = {
            "conversation_id": self.conversation_id,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "message_id": self.message_id,
        }
        for field_name, current_value in identity_checks.items():
            preinjected_value = preinjected.get(field_name)
            normalized_current_value = "" if current_value is None else str(current_value)
            normalized_preinjected_value = (
                "" if preinjected_value is None else str(preinjected_value)
            )
            if normalized_preinjected_value != normalized_current_value:
                logger.warning(
                    "[RayHITL] Pre-injected response %s mismatch: expected=%s, got=%s",
                    field_name,
                    normalized_current_value,
                    normalized_preinjected_value,
                )
                return False

        return True

    @staticmethod
    def _load_preinjected_response_data(preinjected: dict[str, Any]) -> dict[str, Any] | None:
        """Parse preinjected response data into a validated dict payload."""
        preinjected_data = preinjected.get("response_data", {})
        if isinstance(preinjected_data, str):
            try:
                preinjected_data = json.loads(preinjected_data)
            except (json.JSONDecodeError, TypeError):
                logger.warning("[RayHITL] Ignoring malformed pre-injected response_data")
                return None
        if not isinstance(preinjected_data, dict):
            logger.warning("[RayHITL] Ignoring non-dict pre-injected response_data")
            return None
        return preinjected_data

    @staticmethod
    def _is_valid_preinjected_response(
        hitl_type: HITLType,
        response_data: dict[str, Any],
    ) -> bool:
        """Return True when preinjected data matches the expected HITL response schema."""
        if response_data.get("cancelled") is True or response_data.get("timeout") is True:
            return True
        if hitl_type == HITLType.CLARIFICATION:
            answer = response_data.get("answer")
            return isinstance(answer, str) or (
                isinstance(answer, list) and all(isinstance(item, str) for item in answer)
            )
        if hitl_type == HITLType.DECISION:
            decision = response_data.get("decision")
            return isinstance(decision, str) or (
                isinstance(decision, list) and all(isinstance(item, str) for item in decision)
            )
        if hitl_type == HITLType.ENV_VAR:
            values = response_data.get("values")
            return isinstance(values, dict) and all(
                isinstance(key, str) and isinstance(value, str) for key, value in values.items()
            )
        if hitl_type == HITLType.PERMISSION:
            action = response_data.get("action")
            return (
                isinstance(action, str)
                and action in {permission.value for permission in PermissionAction}
            ) or isinstance(response_data.get("granted"), bool)
        return True

    @staticmethod
    def _validate_choice_response(
        value: object,
        *,
        allowed_values: set[str],
        allow_custom: bool,
        max_selections: int | None = None,
        allow_multiple: bool = True,
    ) -> bool:
        """Validate a string or list response against allowed choice semantics."""
        if isinstance(value, list):
            if (
                not value
                or not allow_multiple
                or (max_selections is not None and len(value) > max_selections)
                or len(set(value)) != len(value)
            ):
                return False
            return all(
                isinstance(item, str)
                and (item in allowed_values or (allow_custom and bool(item.strip())))
                for item in value
            )
        if isinstance(value, str):
            return value in allowed_values or (allow_custom and bool(value.strip()))
        return False

    @staticmethod
    def _allowed_option_values(options: list[Any]) -> set[str]:
        """Return the set of accepted option identifiers and labels."""
        allowed_values: set[str] = set()
        for option in options:
            option_id = getattr(option, "id", None)
            if isinstance(option_id, str) and option_id:
                allowed_values.add(option_id)
            option_label = getattr(option, "label", None)
            if isinstance(option_label, str) and option_label:
                allowed_values.add(option_label)
        return allowed_values

    @classmethod
    def _matches_request_semantics(  # noqa: PLR0912
        cls,
        request: HITLRequest,
        response_data: dict[str, Any],
    ) -> bool:
        """Validate preinjected responses against the original request semantics."""
        if response_data.get("cancelled") is True or response_data.get("timeout") is True:
            return True
        is_valid = False
        if request.hitl_type == HITLType.CLARIFICATION and request.clarification_data:
            is_valid = cls._validate_choice_response(
                response_data.get("answer"),
                allowed_values=cls._allowed_option_values(request.clarification_data.options),
                allow_custom=request.clarification_data.allow_custom,
                allow_multiple=True,
            )
        elif request.hitl_type == HITLType.DECISION and request.decision_data:
            is_valid = cls._validate_choice_response(
                response_data.get("decision"),
                allowed_values=cls._allowed_option_values(request.decision_data.options),
                allow_custom=request.decision_data.allow_custom,
                max_selections=request.decision_data.max_selections,
                allow_multiple=request.decision_data.decision_type == DecisionType.MULTI_CHOICE,
            )
        elif request.hitl_type == HITLType.ENV_VAR and request.env_var_data:
            values = response_data.get("values", response_data)
            allowed_names = {field.name for field in request.env_var_data.fields}
            required_names = {
                field.name
                for field in request.env_var_data.fields
                if getattr(field, "required", False)
            }
            if isinstance(values, dict):
                normalized_values = {
                    name: value.strip()
                    for name, value in values.items()
                    if isinstance(name, str) and isinstance(value, str) and value.strip()
                }
                is_valid = (
                    all(
                        isinstance(name, str) and isinstance(value, str)
                        for name, value in values.items()
                    )
                    and set(values).issubset(allowed_names)
                    and required_names.issubset(normalized_values.keys())
                )
            else:
                is_valid = False
        elif request.hitl_type == HITLType.PERMISSION and request.permission_data:
            action = response_data.get("action")
            granted = response_data.get("granted")
            valid_actions = {permission.value for permission in PermissionAction}
            if isinstance(action, str):
                is_valid = action in valid_actions
                if is_valid and isinstance(granted, bool):
                    is_valid = granted is (action in {"allow", "allow_always"})
            else:
                is_valid = isinstance(granted, bool)
        elif request.hitl_type == HITLType.A2UI_ACTION and request.a2ui_data:
            action_name = response_data.get("action_name")
            source_component_id = response_data.get("source_component_id", "")
            action_context = response_data.get("context", {})
            basic_shape_is_valid = (
                isinstance(action_name, str)
                and bool(action_name.strip())
                and isinstance(source_component_id, str)
                and bool(source_component_id.strip())
                and isinstance(action_context, dict)
            )
            if not basic_shape_is_valid:
                is_valid = False
            else:
                # Strict allowed_actions enforcement: an empty allow-list means
                # the surface published no actionable affordances and MUST NOT
                # accept any client-supplied action (P1-16).
                allowed_pairs = {
                    (entry.get("source_component_id", ""), entry.get("action_name", ""))
                    for entry in request.a2ui_data.allowed_actions
                }
                is_valid = (source_component_id, action_name) in allowed_pairs
        else:
            is_valid = True
        return is_valid

    def _get_strategy(self, hitl_type: HITLType) -> HITLTypeStrategy:
        strategy = self._strategies.get(hitl_type)
        if not strategy:
            raise ValueError(f"No strategy registered for HITL type: {hitl_type}")
        return strategy

    def _next_request_call_id(self, prefix: str) -> str:
        """Return a per-handler unique call id seed for stable request ids."""
        self._request_sequence += 1
        return f"{prefix}:{self._request_sequence}"

    async def request_clarification(
        self,
        question: str,
        options: list[Any] | None = None,
        clarification_type: str = "custom",
        allow_custom: bool = True,
        timeout_seconds: float | None = None,
        context: dict[str, Any] | None = None,
        default_value: str | None = None,
        request_id: str | None = None,
    ) -> str | list[str]:
        # Normalize options (handle None)
        normalized_options = options or []

        # Auto-enable allow_custom when options are empty
        effective_allow_custom = allow_custom
        if not normalized_options:
            effective_allow_custom = True
            logger.info(
                "[RayHITL] Clarification called with empty options, "
                "auto-enabling allow_custom for free-form response"
            )

        request_data = {
            "question": question,
            "options": normalized_options,
            "clarification_type": clarification_type,
            "allow_custom": effective_allow_custom,
            "context": context or {},
            "default_value": default_value,
        }
        if request_id:
            request_data["_request_id"] = request_id

        return cast(
            str | list[str],
            await self._execute_hitl_request(
                HITLType.CLARIFICATION,
                request_data,
                timeout_seconds or self.default_timeout,
            ),
        )

    async def request_decision(
        self,
        question: str,
        options: list[Any],
        decision_type: str = "single_choice",
        allow_custom: bool = False,
        timeout_seconds: float | None = None,
        context: dict[str, Any] | None = None,
        default_option: str | None = None,
        request_id: str | None = None,
        selection_mode: str = "single",
        max_selections: int | None = None,
    ) -> str | list[str]:
        # Normalize options (handle None/empty)
        normalized_options = options if options else []

        # Auto-enable allow_custom when options are empty
        effective_allow_custom = allow_custom
        if not normalized_options:
            effective_allow_custom = True
            logger.info(
                "[RayHITL] Decision called with empty options, "
                "auto-enabling allow_custom for free-form response"
            )

        request_data = {
            "question": question,
            "options": normalized_options,
            "decision_type": decision_type,
            "allow_custom": effective_allow_custom,
            "context": context or {},
            "default_option": default_option,
            "selection_mode": selection_mode,
            "max_selections": max_selections,
        }
        if request_id:
            request_data["_request_id"] = request_id

        return cast(
            str | list[str],
            await self._execute_hitl_request(
                HITLType.DECISION,
                request_data,
                timeout_seconds or self.default_timeout,
            ),
        )

    async def request_env_vars(
        self,
        tool_name: str,
        fields: list[dict[str, Any]],
        message: str | None = None,
        context: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
        allow_save: bool = True,
        save_project_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        request_data = {
            "tool_name": tool_name,
            "fields": fields,
            "message": message,
            "context": context or {},
            "allow_save": allow_save,
        }
        if request_id:
            request_data["_request_id"] = request_id

        return cast(
            dict[str, Any],
            await self._execute_hitl_request(
                HITLType.ENV_VAR,
                request_data,
                timeout_seconds or self.default_timeout,
                save_project_id=save_project_id,
            ),
        )

    async def request_permission(
        self,
        tool_name: str,
        action: str,
        risk_level: str = "medium",
        description: str | None = None,
        details: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
        allow_remember: bool = True,
        request_id: str | None = None,
    ) -> bool:
        request_data = {
            "tool_name": tool_name,
            "action": action,
            "risk_level": risk_level,
            "description": description,
            "details": details or {},
            "allow_remember": allow_remember,
        }
        call_id = request_id or self._next_request_call_id("perm")
        effective_request_id = request_id or build_stable_hitl_request_id(
            "perm",
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            conversation_id=self.conversation_id,
            message_id=self.message_id,
            call_id=call_id,
            payload=request_data,
        )
        request_data["_request_id"] = effective_request_id

        return cast(
            bool,
            await self._execute_hitl_request(
                HITLType.PERMISSION,
                request_data,
                timeout_seconds or 60.0,
            ),
        )

    async def _execute_hitl_request(
        self,
        hitl_type: HITLType,
        request_data: dict[str, Any],
        timeout_seconds: float,
        **strategy_kwargs: Any,
    ) -> Any:
        strategy = self._get_strategy(hitl_type)
        request = strategy.create_request(
            conversation_id=self.conversation_id,
            request_data=request_data,
            timeout_seconds=timeout_seconds,
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            message_id=self.message_id,
            **strategy_kwargs,
        )

        if self._preinjected_response:
            preinjected = self._preinjected_response
            if self._matches_preinjected_request(
                hitl_type=hitl_type,
                preinjected=preinjected,
                request_data=request_data,
            ):
                preinjected_data = self._load_preinjected_response_data(preinjected)
                if (
                    preinjected_data is None
                    or not self._is_valid_preinjected_response(
                        hitl_type,
                        preinjected_data,
                    )
                    or not self._matches_request_semantics(
                        request,
                        preinjected_data,
                    )
                ):
                    self._clear_preinjected_response()
                    logger.warning(
                        "[RayHITL] Ignoring invalid pre-injected response payload for %s",
                        hitl_type.value,
                    )
                else:
                    # Consume the preinjected response
                    self._clear_preinjected_response()
                    logger.info(
                        f"[RayHITL] Using pre-injected response for {hitl_type.value}: "
                        f"request_id={preinjected.get('request_id')}"
                    )
                    if preinjected_data.get("cancelled") or preinjected_data.get("timeout"):
                        if hitl_type == HITLType.ENV_VAR:
                            return preinjected_data
                        return strategy.get_default_response(request)
                    extracted_response = strategy.extract_response_value(preinjected_data)
                    if hitl_type == HITLType.ENV_VAR:
                        return {"values": extracted_response}
                    return extracted_response

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
                created_at=datetime.now(UTC),
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

    def get_pending_requests(self) -> list[HITLRequest]:
        return list(self._pending_requests.values())

    async def cancel_request(self, request_id: str, reason: str | None = None) -> bool:
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
    message_id: str | None,
    timeout_seconds: float,
    type_data: dict[str, Any],
    created_at: datetime,
) -> None:
    type_mapping = {
        "clarification": HITLRequestType.CLARIFICATION,
        "decision": HITLRequestType.DECISION,
        "env_var": HITLRequestType.ENV_VAR,
        "a2ui_action": HITLRequestType.A2UI_ACTION,
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
    type_data: dict[str, Any],
    timeout_seconds: float,
) -> None:
    event_type_mapping = {
        "clarification": "clarification_asked",
        "decision": "decision_asked",
        "env_var": "env_var_requested",
        "permission": "permission_asked",
        "a2ui_action": "a2ui_action_asked",
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
    data: dict[str, Any],
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
