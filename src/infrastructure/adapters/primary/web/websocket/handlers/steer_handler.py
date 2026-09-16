"""Steer message handler: inject session-owner guidance into the active run.

A ``steer_message`` WebSocket command binds to the conversation's latest active
run (or an explicitly addressed run), persists an idempotent ``steer_now`` run
input, and dispatches it through the canonical control channel so the processor
injects it as a user-role message at the next turn boundary. The client learns
the outcome from the ``ack`` (accepted/rejected with a reason code) or from a
typed error for validation and unsupported-runtime failures.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast, override

from pydantic import ValidationError
from sqlalchemy import func, select

from src.application.schemas.agent_run_authority import CreateRunInputRequest
from src.application.services.agent.run_input_dispatch import (
    CONTROL_CHANNEL_UNAVAILABLE,
    RUN_INPUT_DISPATCH_LEASE,
    SteerDispatchOutcome,
    _canonical_hash,
    _dispatch_lease_is_active,
    dispatch_persisted_steer_control,
    settle_steer_dispatch,
)
from src.domain.model.agent.run_input import AgentRunInputStatus
from src.infrastructure.adapters.primary.web.conversation_access_application_authority_v2 import (
    conversation_access_application_authority_v2,
)
from src.infrastructure.adapters.primary.web.websocket.handlers.base_handler import (
    WebSocketMessageHandler,
)
from src.infrastructure.adapters.primary.web.websocket.handlers.chat_handler import (
    _client_message_id_extra,
    _conversation_scope_is_active,
    _pending_hitl_requests,
    _validated_client_message_controls,
)
from src.infrastructure.adapters.primary.web.websocket.handlers.control_handler import (
    _acquire_control_reservation_v2,
)
from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentRunAuthorityModel,
    AgentRunInputModel,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.scoped_boundary import pin_scoped_agent_turn_operation_v2

if TYPE_CHECKING:
    from src.domain.model.agent import Conversation

logger = logging.getLogger(__name__)

_ACTIVE_RUN_STATUSES = frozenset({"queued", "running"})


@dataclass(frozen=True, slots=True)
class _SteerRequest:
    """Validated steer_message fields after structural checks."""

    conversation_id: str
    project_id: str
    message_text: str
    message_id: str
    run_id: str | None
    expected_run_revision: int | None


class SteerMessageHandler(WebSocketMessageHandler):
    """Handle steer_message: inject user guidance into the active run."""

    @property
    @override
    def message_type(self) -> str:
        return "steer_message"

    @override
    async def handle(self, context: MessageContext, message: dict[str, Any]) -> None:
        conversation_id = message.get("conversation_id")
        controls = await _validated_client_message_controls(
            context,
            message=message,
            conversation_id=conversation_id,
        )
        if controls is None:
            return
        client_message_id, _permission_mode = controls
        request = await self._parse_request(
            context,
            message,
            conversation_id=conversation_id,
            client_message_id=client_message_id,
        )
        if request is None:
            return

        try:
            async with conversation_access_application_authority_v2(
                context,
                conversation_id=request.conversation_id,
            ) as authority:
                conversation = await authority.service.find_by_id(request.conversation_id)
                if conversation is None:
                    await self._reject(context, request, "conversation_not_found")
                    return
                if not await self._scope_allows_turn(
                    context,
                    conversation=conversation,
                    request=request,
                ):
                    return

                run = await self._bind_run(context, request=request)
                if run is None:
                    await self._reject(context, request, "no_active_run")
                    return
                if (
                    request.expected_run_revision is not None
                    and run.revision != request.expected_run_revision
                ):
                    await context.db.rollback()
                    await self._reject(context, request, "run_revision_conflict")
                    return

                await self._persist_and_dispatch(
                    context,
                    conversation=conversation,
                    run=run,
                    request=request,
                )
        except Exception as e:
            logger.error(f"[WS] Error handling steer_message: {e}", exc_info=True)
            await context.send_error(
                str(e),
                code=e.code if isinstance(e, RuntimeV2Error) else None,
                conversation_id=request.conversation_id,
                extra=_client_message_id_extra(request.message_id),
            )

    async def _parse_request(
        self,
        context: MessageContext,
        message: dict[str, Any],
        *,
        conversation_id: object,
        client_message_id: str | None,
    ) -> _SteerRequest | None:
        """Validate the raw frame into a structured request, or reject it."""
        user_message = message.get("message")
        project_id = message.get("project_id")
        if (
            not isinstance(conversation_id, str)
            or not conversation_id.strip()
            or not isinstance(user_message, str)
            or not user_message.strip()
            or not isinstance(project_id, str)
            or not project_id.strip()
            or client_message_id is None
        ):
            await self._send_invalid(
                context,
                conversation_id,
                client_message_id,
                _("Missing required fields: conversation_id, project_id, message, message_id"),
            )
            return None

        run_id = message.get("run_id")
        if run_id is not None and (not isinstance(run_id, str) or not run_id.strip()):
            await self._send_invalid(
                context,
                conversation_id,
                client_message_id,
                _("run_id must be a non-empty string"),
            )
            return None

        expected_run_revision = message.get("expected_run_revision")
        if expected_run_revision is not None and (
            not isinstance(expected_run_revision, int)
            or isinstance(expected_run_revision, bool)
            or expected_run_revision < 1
        ):
            await self._send_invalid(
                context,
                conversation_id,
                client_message_id,
                _("expected_run_revision must be a positive integer"),
            )
            return None

        return _SteerRequest(
            conversation_id=conversation_id,
            project_id=project_id,
            message_text=user_message,
            message_id=client_message_id,
            run_id=run_id if isinstance(run_id, str) else None,
            expected_run_revision=(
                expected_run_revision if isinstance(expected_run_revision, int) else None
            ),
        )

    async def _scope_allows_turn(
        self,
        context: MessageContext,
        *,
        conversation: Conversation,
        request: _SteerRequest,
    ) -> bool:
        """Reject unless the persisted scope is active and no HITL is pending."""
        if not await _conversation_scope_is_active(
            context,
            conversation=conversation,
            project_id=request.project_id,
        ):
            await self._reject(context, request, "conversation_access_denied")
            return False
        pending_hitl = await _pending_hitl_requests(
            context,
            conversation_id=request.conversation_id,
            project_id=request.project_id,
        )
        if pending_hitl:
            await self._reject(context, request, "hitl_pending")
            return False
        return True

    async def _bind_run(
        self,
        context: MessageContext,
        *,
        request: _SteerRequest,
    ) -> AgentRunAuthorityModel | None:
        """Bind the addressed run, or the latest active run, under a row lock."""
        statement = select(AgentRunAuthorityModel).where(
            AgentRunAuthorityModel.conversation_id == request.conversation_id,
            AgentRunAuthorityModel.tenant_id == context.tenant_id,
            AgentRunAuthorityModel.project_id == request.project_id,
            AgentRunAuthorityModel.status.in_(_ACTIVE_RUN_STATUSES),
        )
        if request.run_id is not None:
            statement = statement.where(AgentRunAuthorityModel.id == request.run_id)
        else:
            statement = statement.order_by(
                AgentRunAuthorityModel.created_at.desc(),
                AgentRunAuthorityModel.id.desc(),
            ).limit(1)
        result = await context.db.execute(refresh_select_statement(statement.with_for_update()))
        return result.scalar_one_or_none()

    async def _persist_and_dispatch(
        self,
        context: MessageContext,
        *,
        conversation: Conversation,
        run: AgentRunAuthorityModel,
        request: _SteerRequest,
    ) -> None:
        """Create or replay the idempotent steer row, then dispatch it."""
        try:
            body = CreateRunInputRequest(
                expected_run_revision=run.revision,
                message=request.message_text,
                message_id=request.message_id,
                idempotency_key=request.message_id,
                delivery="steer_now",
            )
        except ValidationError:
            await context.db.rollback()
            await self._send_invalid(
                context,
                run.conversation_id,
                request.message_id,
                _("Invalid steer message payload"),
            )
            return
        payload_hash = _canonical_hash(body.model_dump(mode="json"))

        existing_result = await context.db.execute(
            refresh_select_statement(
                select(AgentRunInputModel)
                .where(
                    AgentRunInputModel.run_id == run.id,
                    AgentRunInputModel.idempotency_key == request.message_id,
                )
                .with_for_update()
            )
        )
        existing = existing_result.scalar_one_or_none()
        now = datetime.now(UTC)
        if existing is not None:
            if existing.payload_hash != payload_hash:
                await context.db.rollback()
                await self._reject(context, request, "idempotency_conflict")
                return
            if existing.dispatch_status == "dispatched":
                await context.db.commit()
                await self._accept(context, row=existing)
                return
            if existing.dispatch_status == "dispatching" and _dispatch_lease_is_active(
                existing,
                now=now,
            ):
                await context.db.rollback()
                await self._reject(context, request, "steer_dispatch_in_progress")
                return
            existing.dispatch_status = "dispatching"
            existing.dispatch_attempts += 1
            existing.dispatch_lease_expires_at = now + RUN_INPUT_DISPATCH_LEASE
            existing.dispatch_error_code = None
            existing.updated_at = now
            await context.db.commit()
            row = existing
        else:
            sequence_result = await context.db.execute(
                refresh_select_statement(
                    select(func.coalesce(func.max(AgentRunInputModel.sequence), 0)).where(
                        AgentRunInputModel.run_id == run.id
                    )
                )
            )
            sequence = int(sequence_result.scalar_one()) + 1
            row = AgentRunInputModel(
                id=str(uuid.uuid4()),
                tenant_id=context.tenant_id,
                project_id=run.project_id,
                conversation_id=run.conversation_id,
                run_id=run.id,
                actor_user_id=context.user_id,
                expected_run_revision=run.revision,
                message=request.message_text,
                message_id=request.message_id,
                idempotency_key=request.message_id,
                payload_hash=payload_hash,
                delivery="steer_now",
                references_json=[],
                context_items_json=[],
                status=AgentRunInputStatus.PENDING_BOUNDARY,
                sequence=sequence,
                queue_position=None,
                dispatch_status="dispatching",
                dispatch_attempts=1,
                dispatch_lease_expires_at=now + RUN_INPUT_DISPATCH_LEASE,
                dispatch_error_code=None,
                created_at=now,
                updated_at=now,
            )
            context.db.add(row)
            await context.db.commit()

        await self._dispatch(context, row=row, conversation=conversation)

    async def _dispatch(
        self,
        context: MessageContext,
        *,
        row: AgentRunInputModel,
        conversation: Conversation,
    ) -> None:
        """Dispatch one committed steer row under the scoped control audit pin."""
        try:
            reservation = await _acquire_control_reservation_v2(context, cast(Any, conversation))
            async with pin_scoped_agent_turn_operation_v2(
                reservation,
                operation_id=f"run-input-dispatch:{row.id}",
                tenant_id=row.tenant_id,
                project_id=row.project_id,
                session_id=row.conversation_id,
                services={
                    OPERATION_DB_SESSION_SERVICE_V2: context.db,
                    OPERATION_IDENTITY_SERVICE_V2: {
                        "tenant_id": context.tenant_id,
                        "user_id": context.user_id,
                        "project_id": row.project_id,
                    },
                    OPERATION_METADATA_SERVICE_V2: {
                        "kind": "agent-control",
                        "channel": "websocket",
                        "command_type": "steer_message",
                        "conversation_id": row.conversation_id,
                        "run_id": row.run_id,
                        "run_input_id": row.id,
                    },
                },
            ):
                outcome = await dispatch_persisted_steer_control(
                    row=row,
                    sender_id=context.user_id,
                )
        except RuntimeV2Error:
            outcome = SteerDispatchOutcome(
                accepted=False,
                error_code=CONTROL_CHANNEL_UNAVAILABLE,
            )

        await settle_steer_dispatch(context.db, row=row, outcome=outcome)
        if outcome.accepted:
            await self._accept(context, row=row)
            return
        if outcome.error_code == CONTROL_CHANNEL_UNAVAILABLE:
            await context.send_error(
                _("Steering is not supported by the active runtime"),
                code="STEER_NOT_SUPPORTED",
                conversation_id=row.conversation_id,
                extra={"message_id": row.message_id},
            )
            return
        await context.send_ack(
            "steer_message",
            outcome="rejected",
            reason_code="steer_dispatch_failed",
            message_id=row.message_id,
            conversation_id=row.conversation_id,
        )

    async def _accept(self, context: MessageContext, *, row: AgentRunInputModel) -> None:
        await context.send_ack(
            "steer_message",
            outcome="accepted",
            message_id=row.message_id,
            conversation_id=row.conversation_id,
            run_id=row.run_id,
            run_revision=row.expected_run_revision,
            input_id=row.id,
        )

    async def _reject(
        self,
        context: MessageContext,
        request: _SteerRequest,
        reason_code: str,
    ) -> None:
        await context.send_ack(
            "steer_message",
            outcome="rejected",
            reason_code=reason_code,
            message_id=request.message_id,
            conversation_id=request.conversation_id,
        )

    async def _send_invalid(
        self,
        context: MessageContext,
        conversation_id: object,
        message_id: str | None,
        detail: str,
    ) -> None:
        await context.send_error(
            detail,
            code="INVALID_STEER_MESSAGE",
            conversation_id=conversation_id if isinstance(conversation_id, str) else None,
            extra=_client_message_id_extra(message_id),
        )


__all__ = ["SteerMessageHandler"]
