"""Shared dispatch core for persisted steer run inputs.

Both the canonical HTTP authority (``run_input_authority``) and the WebSocket
``steer_message`` handler route through this module so the control-channel
dispatch, retryable transport settlement, canonical payload hashing, and
receipt shaping exist exactly once. Callers own their operation pinning
(HTTP pins via ``pin_agent_turn_operation_v2``; WebSocket pins via
``pin_scoped_agent_turn_operation_v2``) and their response shaping.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.agent_run_authority import RunInputAck, RunInputReceipt
from src.domain.model.agent.tool_policy import ControlMessageType
from src.domain.ports.agent.control_channel_port import ControlMessage
from src.infrastructure.adapters.secondary.persistence.models import AgentRunInputModel
from src.infrastructure.agent.subagent.control_channel import RedisControlChannel
from src.infrastructure.plugins.v2.agent_worker_runtime import (
    current_agent_worker_redis_client_v2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

RUN_INPUT_DISPATCH_LEASE = timedelta(seconds=30)

CONTROL_CHANNEL_UNAVAILABLE = "control_channel_unavailable"
CONTROL_CHANNEL_REJECTED = "control_channel_rejected"


def _canonical_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SteerDispatchOutcome:
    """Transport result of one steer control-channel dispatch attempt."""

    accepted: bool
    error_code: str | None = None


def build_steer_control_message(
    *,
    row: AgentRunInputModel,
    sender_id: str,
) -> ControlMessage:
    """Build the canonical STEER control message for one persisted run input."""
    return ControlMessage(
        run_id=row.run_id,
        message_type=ControlMessageType.STEER,
        payload=row.message,
        sender_id=sender_id,
        run_input_id=row.id,
        delivery_mode="steer_now",
        run_revision=row.expected_run_revision,
        message_id=row.message_id,
        idempotency_key=row.idempotency_key,
    )


async def dispatch_persisted_steer_control(
    *,
    row: AgentRunInputModel,
    sender_id: str,
) -> SteerDispatchOutcome:
    """Send one committed steer row through the generation-owned control channel.

    Must be called inside the caller's pinned agent-turn operation so the Redis
    client resolves against the exact pinned generation.
    """
    try:
        redis_client = current_agent_worker_redis_client_v2()
        accepted = await RedisControlChannel(redis_client).send_control(
            build_steer_control_message(row=row, sender_id=sender_id)
        )
    except RuntimeV2Error:
        return SteerDispatchOutcome(accepted=False, error_code=CONTROL_CHANNEL_UNAVAILABLE)
    if accepted:
        return SteerDispatchOutcome(accepted=True)
    return SteerDispatchOutcome(accepted=False, error_code=CONTROL_CHANNEL_REJECTED)


async def settle_steer_dispatch(
    db: AsyncSession,
    *,
    row: AgentRunInputModel,
    outcome: SteerDispatchOutcome,
) -> None:
    """Settle the retryable transport state of one dispatched steer row."""
    now = datetime.now(UTC)
    row.dispatch_lease_expires_at = None
    row.updated_at = now
    if outcome.accepted:
        row.dispatch_status = "dispatched"
        row.dispatch_error_code = None
    else:
        row.dispatch_status = "failed"
        row.dispatch_error_code = outcome.error_code or CONTROL_CHANNEL_REJECTED
    await db.commit()


def _dispatch_lease_is_active(row: AgentRunInputModel, *, now: datetime) -> bool:
    lease = row.dispatch_lease_expires_at
    if lease is None:
        return False
    if lease.tzinfo is None:
        lease = lease.replace(tzinfo=UTC)
    return lease > now


def _input_receipt(row: AgentRunInputModel) -> RunInputReceipt:
    return RunInputReceipt(
        id=row.id,
        conversation_id=row.conversation_id,
        run_id=row.run_id,
        expected_run_revision=row.expected_run_revision,
        message_id=row.message_id,
        idempotency_key=row.idempotency_key,
        delivery=cast(Literal["steer_now", "queue_next"], row.delivery),
        status=cast(
            Literal[
                "pending_boundary",
                "queued",
                "applied",
                "ready",
                "blocked",
                "promoted_to_plan",
            ],
            row.status,
        ),
        sequence=row.sequence,
        queue_position=row.queue_position,
        content=row.message,
        references=list(row.references_json),
        context_items=list(row.context_items_json),
        applied_round=row.applied_round,
        applied_at=row.applied_at,
        injected_via=row.injected_via,
        dispatch_status=cast(
            Literal["not_required", "dispatching", "dispatched", "failed"],
            row.dispatch_status,
        ),
        dispatch_attempts=row.dispatch_attempts,
        dispatch_lease_expires_at=row.dispatch_lease_expires_at,
        dispatch_error_code=row.dispatch_error_code,
        promotion_idempotency_key=row.promotion_key,
        promoted_at=row.promoted_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _input_ack(
    row: AgentRunInputModel,
    *,
    run_revision: int,
    created: bool,
) -> RunInputAck:
    return RunInputAck(
        accepted=True,
        created=created,
        conversation_id=row.conversation_id,
        message_id=row.message_id,
        delivery_mode=cast(Literal["steer_now", "queue_next"], row.delivery),
        run_id=row.run_id,
        run_revision=run_revision,
        queue_position=row.queue_position,
        input=_input_receipt(row),
    )


__all__ = [
    "CONTROL_CHANNEL_REJECTED",
    "CONTROL_CHANNEL_UNAVAILABLE",
    "RUN_INPUT_DISPATCH_LEASE",
    "SteerDispatchOutcome",
    "_canonical_hash",
    "_dispatch_lease_is_active",
    "_input_ack",
    "_input_receipt",
    "build_steer_control_message",
    "dispatch_persisted_steer_control",
    "settle_steer_dispatch",
]
