"""Tests for the WebSocket steer_message handler authority."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.application.schemas.agent_run_authority import CreateRunInputRequest
from src.application.services.agent.run_input_dispatch import (
    SteerDispatchOutcome,
    _canonical_hash,
)
from src.infrastructure.adapters.primary.web.websocket.handlers import steer_handler
from src.infrastructure.adapters.primary.web.websocket.handlers.steer_handler import (
    SteerMessageHandler,
)
from src.infrastructure.adapters.primary.web.websocket.message_router import get_message_router
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

pytestmark = pytest.mark.unit


class _Result:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value

    def scalar_one(self) -> object:
        return self._value


def _conversation() -> SimpleNamespace:
    return SimpleNamespace(
        id="conversation-1",
        tenant_id="tenant-1",
        project_id="project-1",
        user_id="user-1",
        participant_agents=[],
    )


def _run(revision: int = 7, status: str = "running") -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id="run-1",
        tenant_id="tenant-1",
        project_id="project-1",
        conversation_id="conversation-1",
        revision=revision,
        status=status,
        created_at=now,
    )


def _payload_hash(message: str, message_id: str, revision: int) -> str:
    body = CreateRunInputRequest(
        expected_run_revision=revision,
        message=message,
        message_id=message_id,
        idempotency_key=message_id,
        delivery="steer_now",
    )
    return _canonical_hash(body.model_dump(mode="json"))


def _existing_row(
    *,
    message: str = "Focus on the failing test.",
    message_id: str = "desktop-steer-1",
    revision: int = 7,
    dispatch_status: str = "dispatched",
    lease: datetime | None = None,
) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id="input-1",
        tenant_id="tenant-1",
        project_id="project-1",
        conversation_id="conversation-1",
        run_id="run-1",
        expected_run_revision=revision,
        message=message,
        message_id=message_id,
        idempotency_key=message_id,
        payload_hash=_payload_hash(message, message_id, revision),
        dispatch_status=dispatch_status,
        dispatch_attempts=1,
        dispatch_lease_expires_at=lease,
        dispatch_error_code=None,
        updated_at=now,
    )


def _context(db_results: list[object]) -> SimpleNamespace:
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=[_Result(value) for value in db_results]),
        commit=AsyncMock(),
        rollback=AsyncMock(),
        add=lambda _row: None,
    )
    return SimpleNamespace(
        user_id="user-1",
        tenant_id="tenant-1",
        db=db,
        send_json=AsyncMock(),
        send_ack=AsyncMock(),
        send_error=AsyncMock(),
        scoped_profile_runtime_v2=None,
    )


def _bind_scope(
    monkeypatch: pytest.MonkeyPatch,
    conversation: SimpleNamespace | None,
    *,
    scope_active: bool = True,
    pending_hitl: list[object] | None = None,
) -> None:
    @asynccontextmanager
    async def authority(_context: object, *, conversation_id: str):
        yield SimpleNamespace(
            service=SimpleNamespace(find_by_id=AsyncMock(return_value=conversation))
        )

    monkeypatch.setattr(steer_handler, "conversation_access_application_authority_v2", authority)
    monkeypatch.setattr(
        steer_handler,
        "_conversation_scope_is_active",
        AsyncMock(return_value=scope_active),
    )
    monkeypatch.setattr(
        steer_handler,
        "_pending_hitl_requests",
        AsyncMock(return_value=pending_hitl or []),
    )


def _bind_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    outcome: SteerDispatchOutcome,
) -> AsyncMock:
    @asynccontextmanager
    async def pin(_reservation: object, **_kwargs: object):
        yield None

    monkeypatch.setattr(
        steer_handler,
        "_acquire_control_reservation_v2",
        AsyncMock(return_value=object()),
    )
    monkeypatch.setattr(steer_handler, "pin_scoped_agent_turn_operation_v2", pin)
    dispatch = AsyncMock(return_value=outcome)
    monkeypatch.setattr(steer_handler, "dispatch_persisted_steer_control", dispatch)
    return dispatch


def _message(**overrides: object) -> dict[str, object]:
    return {
        "type": "steer_message",
        "conversation_id": "conversation-1",
        "project_id": "project-1",
        "message": "Focus on the failing test.",
        "message_id": "desktop-steer-1",
        **overrides,
    }


async def test_handler_registered_under_steer_message_type() -> None:
    assert SteerMessageHandler().message_type == "steer_message"
    assert "steer_message" in get_message_router().registered_types


@pytest.mark.parametrize(
    "override",
    [
        {"message": ""},
        {"message_id": None},
        {"project_id": 42},
        {"run_id": ""},
        {"expected_run_revision": 0},
        {"expected_run_revision": "7"},
    ],
)
async def test_malformed_payload_returns_invalid_steer_message(
    monkeypatch: pytest.MonkeyPatch,
    override: dict[str, object],
) -> None:
    context = _context([])
    handler = SteerMessageHandler()

    await handler.handle(context, _message(**override))

    assert context.send_error.await_count == 1
    assert context.send_error.await_args.kwargs["code"] in {
        "INVALID_STEER_MESSAGE",
        "INVALID_MESSAGE_ID",
    }
    context.send_ack.assert_not_awaited()


async def test_scope_denial_rejects_without_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context([])
    _bind_scope(monkeypatch, _conversation(), scope_active=False)

    await SteerMessageHandler().handle(context, _message())

    ack = context.send_ack.await_args
    assert ack.args[0] == "steer_message"
    assert ack.kwargs["outcome"] == "rejected"
    assert ack.kwargs["reason_code"] == "conversation_access_denied"
    assert ack.kwargs["message_id"] == "desktop-steer-1"


async def test_pending_hitl_rejects(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context([])
    _bind_scope(monkeypatch, _conversation(), pending_hitl=[object()])

    await SteerMessageHandler().handle(context, _message())

    assert context.send_ack.await_args.kwargs["reason_code"] == "hitl_pending"


async def test_no_active_run_rejects(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context([None])
    _bind_scope(monkeypatch, _conversation())

    await SteerMessageHandler().handle(context, _message())

    assert context.send_ack.await_args.kwargs["reason_code"] == "no_active_run"


async def test_run_revision_conflict_rejects(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context([_run(revision=7)])
    _bind_scope(monkeypatch, _conversation())

    await SteerMessageHandler().handle(context, _message(expected_run_revision=6))

    assert context.send_ack.await_args.kwargs["reason_code"] == "run_revision_conflict"
    context.db.rollback.assert_awaited_once()


async def test_explicit_run_id_not_found_rejects_no_active_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context([None])
    _bind_scope(monkeypatch, _conversation())

    await SteerMessageHandler().handle(context, _message(run_id="run-missing"))

    assert context.send_ack.await_args.kwargs["reason_code"] == "no_active_run"


async def test_accept_dispatches_and_acks(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context([_run(), None, 0])
    _bind_scope(monkeypatch, _conversation())
    dispatch = _bind_dispatch(monkeypatch, SteerDispatchOutcome(accepted=True))

    await SteerMessageHandler().handle(context, _message())

    ack = context.send_ack.await_args
    assert ack.args[0] == "steer_message"
    assert ack.kwargs["outcome"] == "accepted"
    assert ack.kwargs["message_id"] == "desktop-steer-1"
    assert ack.kwargs["conversation_id"] == "conversation-1"
    assert ack.kwargs["run_id"] == "run-1"
    assert ack.kwargs["run_revision"] == 7
    assert ack.kwargs["input_id"]
    dispatch.assert_awaited_once()
    row = dispatch.await_args.kwargs["row"]
    assert row.run_id == "run-1"
    assert row.delivery == "steer_now"
    assert row.idempotency_key == "desktop-steer-1"
    assert row.status == "pending_boundary"
    assert dispatch.await_args.kwargs["sender_id"] == "user-1"
    # Row creation commit + dispatch settlement commit.
    assert context.db.commit.await_count == 2


async def test_idempotent_replay_of_dispatched_row_accepts_without_redispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = _existing_row(dispatch_status="dispatched")
    context = _context([_run(), existing])
    _bind_scope(monkeypatch, _conversation())
    dispatch = _bind_dispatch(monkeypatch, SteerDispatchOutcome(accepted=True))

    await SteerMessageHandler().handle(context, _message())

    ack = context.send_ack.await_args
    assert ack.kwargs["outcome"] == "accepted"
    assert ack.kwargs["input_id"] == "input-1"
    assert ack.kwargs["run_revision"] == 7
    dispatch.assert_not_awaited()


async def test_same_message_id_with_different_payload_rejects_idempotency_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = _existing_row(message="Original instruction.")
    context = _context([_run(), existing])
    _bind_scope(monkeypatch, _conversation())
    dispatch = _bind_dispatch(monkeypatch, SteerDispatchOutcome(accepted=True))

    await SteerMessageHandler().handle(context, _message())

    assert context.send_ack.await_args.kwargs["reason_code"] == "idempotency_conflict"
    dispatch.assert_not_awaited()
    context.db.rollback.assert_awaited_once()


async def test_failed_dispatch_row_is_redispatched_on_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = _existing_row(dispatch_status="failed")
    context = _context([_run(), existing])
    _bind_scope(monkeypatch, _conversation())
    dispatch = _bind_dispatch(monkeypatch, SteerDispatchOutcome(accepted=True))

    await SteerMessageHandler().handle(context, _message())

    assert context.send_ack.await_args.kwargs["outcome"] == "accepted"
    dispatch.assert_awaited_once()
    assert existing.dispatch_attempts == 2


async def test_active_dispatch_lease_rejects_in_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = _existing_row(
        dispatch_status="dispatching",
        lease=datetime.now(UTC) + timedelta(seconds=30),
    )
    context = _context([_run(), existing])
    _bind_scope(monkeypatch, _conversation())
    dispatch = _bind_dispatch(monkeypatch, SteerDispatchOutcome(accepted=True))

    await SteerMessageHandler().handle(context, _message())

    assert context.send_ack.await_args.kwargs["reason_code"] == "steer_dispatch_in_progress"
    dispatch.assert_not_awaited()


async def test_control_channel_rejection_acknowledges_dispatch_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context([_run(), None, 0])
    _bind_scope(monkeypatch, _conversation())
    _bind_dispatch(
        monkeypatch,
        SteerDispatchOutcome(accepted=False, error_code="control_channel_rejected"),
    )

    await SteerMessageHandler().handle(context, _message())

    assert context.send_ack.await_args.kwargs["outcome"] == "rejected"
    assert context.send_ack.await_args.kwargs["reason_code"] == "steer_dispatch_failed"


async def test_unavailable_control_channel_returns_steer_not_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context([_run(), None, 0])
    _bind_scope(monkeypatch, _conversation())
    _bind_dispatch(
        monkeypatch,
        SteerDispatchOutcome(accepted=False, error_code="control_channel_unavailable"),
    )

    await SteerMessageHandler().handle(context, _message())

    assert context.send_error.await_args.kwargs["code"] == "STEER_NOT_SUPPORTED"
    assert context.send_error.await_args.kwargs["extra"] == {"message_id": "desktop-steer-1"}
    context.send_ack.assert_not_awaited()


async def test_missing_scoped_runtime_returns_steer_not_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context([_run(), None, 0])
    _bind_scope(monkeypatch, _conversation())
    monkeypatch.setattr(
        steer_handler,
        "_acquire_control_reservation_v2",
        AsyncMock(side_effect=RuntimeV2Error("scoped_runtime_missing", "unavailable")),
    )
    dispatch = AsyncMock(return_value=SteerDispatchOutcome(accepted=True))
    monkeypatch.setattr(steer_handler, "dispatch_persisted_steer_control", dispatch)

    await SteerMessageHandler().handle(context, _message())

    assert context.send_error.await_args.kwargs["code"] == "STEER_NOT_SUPPORTED"
    dispatch.assert_not_awaited()
