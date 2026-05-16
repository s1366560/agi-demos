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
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, ClassVar

from src.domain.model.agent.hitl_request import HITLRequest as HITLRequestEntity, HITLRequestType
from src.domain.model.agent.hitl_types import HITLRequest, HITLType
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

logger = logging.getLogger(__name__)


@dataclass
class _PendingHITLRequest:
    future: asyncio.Future[Any]
    completion_future: asyncio.Future[None]
    request: HITLRequest


class ResolveResult(str, Enum):
    """Outcome of attempting to resolve a live HITL request."""

    RESOLVED = "resolved"
    NOT_FOUND = "not_found"
    REJECTED = "rejected"


class HITLCoordinator:
    """Manages HITL request Futures for cooperative pausing.

    Each HITL tool call creates a Future via `request()`. The tool awaits the
    Future, which blocks the async generator without unwinding the stack.
    When the user responds, `resolve()` sets the Future result, unblocking
    the generator naturally.
    """

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
    ) -> None:
        self.conversation_id = conversation_id
        self.tenant_id = tenant_id
        self.project_id = project_id
        self.message_id = message_id
        self.default_timeout = default_timeout
        self._pending: dict[str, _PendingHITLRequest] = {}

    def _get_strategy(self, hitl_type: HITLType) -> HITLTypeStrategy:
        strategy = self._strategies.get(hitl_type)
        if not strategy:
            raise ValueError(f"No strategy registered for HITL type: {hitl_type}")
        return strategy

    async def prepare_request(
        self,
        hitl_type: HITLType,
        request_data: dict[str, Any],
        timeout_seconds: float | None = None,
        **strategy_kwargs: Any,
    ) -> str:
        """Create a pending HITL Future and persist to DB. Returns the request_id.

        Call this BEFORE yielding the HITL-asked event so the event carries the
        real request_id. Then call ``wait_for_response()`` to block until the
        user responds.
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
            **strategy_kwargs,
        )
        request_id = hitl_request.request_id

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        completion_future: asyncio.Future[None] = loop.create_future()
        self._pending[request_id] = _PendingHITLRequest(
            future=fut,
            completion_future=completion_future,
            request=hitl_request,
        )
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
                created_at=datetime.now(UTC),
            )
        except Exception:
            self._pending.pop(request_id, None)
            unregister_coordinator(request_id)
            raise

        logger.info(
            f"[HITLCoordinator] Prepared request: "
            f"type={hitl_type.value}, request_id={request_id}, "
            f"timeout={timeout}s"
        )
        return request_id

    async def wait_for_response(
        self,
        request_id: str,
        hitl_type: HITLType,
        timeout_seconds: float | None = None,
    ) -> Any:
        """Await the Future for a previously prepared request.

        Returns the response value extracted by the type strategy.
        Raises ``asyncio.TimeoutError`` if the user doesn't respond in time.
        """
        timeout = timeout_seconds or self.default_timeout
        strategy = self._get_strategy(hitl_type)
        pending = self._pending.get(request_id)
        if pending is None:
            raise ValueError(f"No pending future for request_id={request_id}")
        fut = pending.future

        logger.info(
            f"[HITLCoordinator] Waiting for response: "
            f"type={hitl_type.value}, request_id={request_id}, "
            f"timeout={timeout}s"
        )

        try:
            response_data = await asyncio.wait_for(fut, timeout=timeout)
        except TimeoutError:
            logger.warning(
                f"[HITLCoordinator] Timeout waiting for {hitl_type.value} request_id={request_id}"
            )
            await mark_hitl_request_timeout(request_id)
            self._cleanup_pending_request(request_id)
            raise

        logger.info(
            f"[HITLCoordinator] Received response for {hitl_type.value}: request_id={request_id}"
        )

        # Defensive: handle string response_data (serialization inconsistency)
        if isinstance(response_data, str):
            try:
                response_data = json.loads(response_data)
            except (json.JSONDecodeError, TypeError):
                return response_data

        if response_data.get("timeout"):
            if hitl_type == HITLType.ENV_VAR:
                return response_data
            raise TimeoutError(f"HITL request timed out: {request_id}")

        if response_data.get("cancelled"):
            if hitl_type == HITLType.ENV_VAR:
                return response_data
            return _type_default(hitl_type)

        if hitl_type == HITLType.ENV_VAR:
            return {"values": strategy.extract_response_value(response_data)}

        return strategy.extract_response_value(response_data)

    async def wait_for_completion(
        self,
        request_id: str,
        timeout_seconds: float | None = None,
    ) -> None:
        """Wait until downstream processing durably completes for a resolved request."""
        pending = self._pending.get(request_id)
        if pending is None:
            return
        if timeout_seconds is None:
            await pending.completion_future
            return
        await asyncio.wait_for(pending.completion_future, timeout=timeout_seconds)

    async def complete_request(self, request_id: str) -> None:
        """Persist completion and release any waiters for durable processing."""
        await mark_hitl_request_completed(request_id)
        pending = self._cleanup_pending_request(request_id)
        if pending is not None and not pending.completion_future.done():
            pending.completion_future.set_result(None)

    def _cleanup_pending_request(self, request_id: str) -> _PendingHITLRequest | None:
        pending = self._pending.pop(request_id, None)
        unregister_coordinator(request_id)
        return pending

    def cancel_request_if_pending(self, request_id: str | None) -> None:
        """Idempotent cleanup safe to call from ``finally`` blocks.

        Releases coordinator/future state for ``request_id`` if (and only if)
        it is still pending. Used by tool handlers to guarantee no Future or
        registered-coordinator entry is leaked when a generator is cancelled
        or raises a non-TimeoutError exception between
        ``prepare_request()`` and ``wait_for_response()``.
        """
        if not request_id:
            return
        pending = self._cleanup_pending_request(request_id)
        if pending is None:
            return
        # Wake any pending waiter so awaiters don't hang indefinitely.
        if not pending.future.done():
            pending.future.cancel()
        if not pending.completion_future.done():
            pending.completion_future.set_result(None)

    async def request(
        self,
        hitl_type: HITLType,
        request_data: dict[str, Any],
        timeout_seconds: float | None = None,
        **strategy_kwargs: Any,
    ) -> Any:
        """Convenience wrapper: prepare + wait in one call.

        Prefer ``prepare_request()`` + ``wait_for_response()`` when you need
        to yield events between preparation and waiting (e.g. in generators).
        """
        request_id = await self.prepare_request(
            hitl_type,
            request_data,
            timeout_seconds,
            **strategy_kwargs,
        )
        return await self.wait_for_response(request_id, hitl_type, timeout_seconds)

    @staticmethod
    def _normalize_binding_value(value: str | None) -> str | None:
        if value is None or value == "":
            return None
        return value

    @classmethod
    def _matches_request_binding(
        cls,
        request: HITLRequest,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
        conversation_id: str | None = None,
        message_id: str | None = None,
        strict: bool = False,
    ) -> bool:
        normalized_expected = {
            "tenant_id": cls._normalize_binding_value(request.tenant_id),
            "project_id": cls._normalize_binding_value(request.project_id),
            "conversation_id": cls._normalize_binding_value(request.conversation_id),
            "message_id": cls._normalize_binding_value(request.message_id),
        }
        normalized_received = {
            "tenant_id": cls._normalize_binding_value(tenant_id),
            "project_id": cls._normalize_binding_value(project_id),
            "conversation_id": cls._normalize_binding_value(conversation_id),
            "message_id": cls._normalize_binding_value(message_id),
        }
        for key, received_value in normalized_received.items():
            expected_value = normalized_expected[key]
            if strict and expected_value is not None:
                if received_value != expected_value:
                    logger.warning(
                        "[HITLCoordinator] Rejected response for request_id=%s due to %s mismatch",
                        request.request_id,
                        key,
                    )
                    return False
                continue
            if received_value is None:
                continue
            if expected_value != received_value:
                logger.warning(
                    "[HITLCoordinator] Rejected response for request_id=%s due to %s mismatch",
                    request.request_id,
                    key,
                )
                return False
        return True

    def resolve(
        self,
        request_id: str,
        response_data: object,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
        conversation_id: str | None = None,
        message_id: str | None = None,
    ) -> ResolveResult:
        """Resolve a pending HITL Future with user response data.

        Returns the resolve outcome so callers can distinguish rejection from
        a missing in-memory coordinator during crash recovery.
        """
        pending = self._pending.get(request_id)
        if pending is None:
            logger.warning(f"[HITLCoordinator] No pending future for request_id={request_id}")
            return ResolveResult.NOT_FOUND
        fut = pending.future
        result = ResolveResult.REJECTED

        if fut.done():
            if not pending.completion_future.done():
                logger.info(
                    "[HITLCoordinator] Response already delivered for request_id=%s; "
                    "waiting for durable completion",
                    request_id,
                )
                result = ResolveResult.RESOLVED
            else:
                logger.warning(f"[HITLCoordinator] Future already done for request_id={request_id}")
            return result

        if not isinstance(response_data, dict):
            logger.warning(
                "[HITLCoordinator] Rejected non-dict response for request_id=%s",
                request_id,
            )
        elif not self._matches_request_binding(
            pending.request,
            tenant_id=tenant_id,
            project_id=project_id,
            conversation_id=conversation_id,
            message_id=message_id,
            strict=True,
        ):
            pass
        else:
            from src.infrastructure.agent.hitl.ray_hitl_handler import RayHITLHandler

            if not RayHITLHandler._matches_request_semantics(pending.request, response_data):
                logger.warning(
                    "[HITLCoordinator] Rejected invalid response semantics for request_id=%s",
                    request_id,
                )
            else:
                fut.set_result(response_data)
                logger.info(f"[HITLCoordinator] Resolved future for request_id={request_id}")
                result = ResolveResult.RESOLVED

        return result

    def cancel_all(self, reason: str = "cancelled") -> int:
        """Cancel all pending Futures. Returns count of cancelled requests."""
        count = 0
        request_ids = list(self._pending.keys())
        for pending in list(self._pending.values()):
            if not pending.future.done():
                pending.future.set_result({"cancelled": True, "reason": reason})
            if not pending.completion_future.done():
                pending.completion_future.set_result(None)
            count += 1
        self._pending.clear()
        for request_id in request_ids:
            unregister_coordinator(request_id)
        return count

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def pending_request_ids(self) -> list[str]:
        return list(self._pending.keys())

    def get_request_data(self, request_id: str) -> dict[str, Any] | None:
        """Get the HITLRequest data for a pending request (for state saving)."""
        pending = self._pending.get(request_id)
        if pending is None:
            return None
        return {
            "request_id": request_id,
            "conversation_id": pending.request.conversation_id,
            "message_id": pending.request.message_id,
            "tenant_id": pending.request.tenant_id,
            "project_id": pending.request.project_id,
        }


# ---------------------------------------------------------------------------
# Global coordinator registry (keyed by request_id for response routing)
# ---------------------------------------------------------------------------

_coordinator_registry: dict[str, HITLCoordinator] = {}


def register_coordinator(request_id: str, coordinator: HITLCoordinator) -> None:
    """Register a coordinator for a pending request."""
    _coordinator_registry[request_id] = coordinator


def unregister_coordinator(request_id: str) -> None:
    """Unregister a coordinator for a completed/cancelled request."""
    _coordinator_registry.pop(request_id, None)


def resolve_by_request_id(
    request_id: str,
    response_data: object,
    *,
    tenant_id: str | None = None,
    project_id: str | None = None,
    conversation_id: str | None = None,
    message_id: str | None = None,
) -> ResolveResult:
    """Resolve a pending HITL request by request_id using the global registry.

    Returns a tri-state result so callers can distinguish a missing in-memory
    coordinator from a rejected response payload.
    """
    coordinator = _coordinator_registry.get(request_id)
    if coordinator is None:
        logger.warning(f"[HITLCoordinator] No coordinator registered for request_id={request_id}")
        return ResolveResult.NOT_FOUND
    return coordinator.resolve(
        request_id,
        response_data,
        tenant_id=tenant_id,
        project_id=project_id,
        conversation_id=conversation_id,
        message_id=message_id,
    )


async def wait_for_request_completion(
    request_id: str,
    timeout_seconds: float | None = None,
) -> None:
    """Wait for a live coordinator request to finish durable post-processing."""
    coordinator = _coordinator_registry.get(request_id)
    if coordinator is None:
        return
    await coordinator.wait_for_completion(request_id, timeout_seconds=timeout_seconds)


async def complete_hitl_request(
    request_id: str,
    *,
    lease_owner: str | None = None,
) -> bool:
    """Mark a request completed and release any live completion waiters."""
    coordinator = _coordinator_registry.get(request_id)
    if coordinator is not None:
        await coordinator.complete_request(request_id)
        return True
    return await mark_hitl_request_completed(request_id, lease_owner=lease_owner)


def validate_hitl_response(
    *,
    hitl_type: HITLType,
    request_data: dict[str, Any],
    response_data: object,
    conversation_id: str,
    tenant_id: str | None,
    project_id: str | None,
    message_id: str | None = None,
    received_tenant_id: str | None = None,
    received_project_id: str | None = None,
    received_conversation_id: str | None = None,
    received_message_id: str | None = None,
) -> tuple[bool, str | None]:
    """Validate a HITL response against trusted request metadata."""
    if not isinstance(response_data, dict):
        return False, "Rejected non-dict HITL response"

    timeout_seconds = request_data.get("timeout_seconds", 300.0)
    if not isinstance(timeout_seconds, (int, float)):
        timeout_seconds = 300.0

    try:
        strategy = HITLCoordinator._strategies[hitl_type]
        request = strategy.create_request(
            conversation_id=conversation_id,
            request_data=request_data,
            timeout_seconds=float(timeout_seconds),
            tenant_id=tenant_id,
            project_id=project_id,
            message_id=message_id,
        )
    except Exception as exc:
        logger.warning(
            "[HITLCoordinator] Failed to rebuild HITL request for validation: %s",
            exc,
            exc_info=True,
        )
        return False, "Rejected HITL response with invalid stored request state"

    if not HITLCoordinator._matches_request_binding(
        request,
        tenant_id=received_tenant_id,
        project_id=received_project_id,
        conversation_id=received_conversation_id,
        message_id=received_message_id,
        strict=True,
    ):
        return False, "Rejected HITL response due to binding mismatch"

    from src.infrastructure.agent.hitl.ray_hitl_handler import RayHITLHandler

    if not RayHITLHandler._matches_request_semantics(request, response_data):
        return False, "Rejected invalid HITL response semantics"

    return True, None


# ---------------------------------------------------------------------------
# Persistence helpers (moved from ray_hitl_handler.py to share)
# ---------------------------------------------------------------------------


def _type_default(hitl_type: HITLType) -> Any:
    """Return a safe fallback value for timeout/cancellation without needing the request object."""
    defaults: dict[HITLType, Any] = {
        HITLType.CLARIFICATION: "",
        HITLType.DECISION: "",
        HITLType.ENV_VAR: {},
        HITLType.PERMISSION: False,
        HITLType.A2UI_ACTION: {"action_name": "", "cancelled": True},
    }
    return defaults.get(hitl_type, "")


async def mark_hitl_request_completed(
    request_id: str,
    lease_owner: str | None = None,
) -> bool:
    """Persist the completed status after a response has been consumed."""
    async with async_session_factory() as session:
        repo = SqlHITLRequestRepository(session)
        completed_request = await repo.mark_completed(request_id, lease_owner=lease_owner)
        if completed_request is not None:
            await session.commit()
            return True
        return False


async def mark_hitl_request_timeout(
    request_id: str,
    default_response: str | None = None,
) -> None:
    """Persist TIMEOUT for a pending request after the in-memory wait expires."""
    async with async_session_factory() as session:
        repo = SqlHITLRequestRepository(session)
        timed_out_request = await repo.mark_timeout(request_id, default_response)
        if timed_out_request is not None:
            await session.commit()


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
