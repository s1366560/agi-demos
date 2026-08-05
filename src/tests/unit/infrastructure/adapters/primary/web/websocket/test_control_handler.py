"""Tests for revision-bound SubAgent WebSocket control authority."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.adapters.primary.web.websocket.handlers.control_handler import (
    KillRunHandler,
    SteerSubAgentHandler,
)
from src.infrastructure.adapters.primary.web.websocket.message_router import get_message_router


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeRedis:
    def __init__(self, state: dict[str, object]) -> None:
        self.values = {
            "subagent:state:conversation-1:execution-1": json.dumps(state),
        }

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: str, **kwargs):
        if kwargs.get("nx") and key in self.values:
            return False
        self.values[key] = value
        return True

    async def delete(self, key: str):
        return int(self.values.pop(key, None) is not None)


def _context(*, participants: list[str] | None = None):
    conversation = SimpleNamespace(
        id="conversation-1",
        project_id="project-1",
        participant_agents=participants or ["agent-1"],
    )
    parent_run = SimpleNamespace(id="parent-run-1", revision=7, status="running")
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _Result(conversation),
                _Result(parent_run),
                _Result(conversation),
                _Result(parent_run),
                _Result(conversation),
                _Result(parent_run),
            ]
        )
    )
    redis = _FakeRedis(
        {
            "execution_id": "execution-1",
            "subagent_id": "agent-1",
            "subagent_name": "Researcher",
            "conversation_id": "conversation-1",
            "status": "running",
        }
    )
    context = SimpleNamespace(
        user_id="user-1",
        tenant_id="tenant-1",
        db=db,
        container=SimpleNamespace(redis_client=redis),
        send_json=AsyncMock(),
    )
    return context, redis


@pytest.mark.unit
async def test_steer_is_revision_bound_and_exact_replay_returns_same_receipt(monkeypatch) -> None:
    context, _redis = _context()
    send_control = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.websocket.handlers.control_handler."
        "RedisControlChannel.send_control",
        send_control,
    )
    command = {
        "type": "steer",
        "conversation_id": "conversation-1",
        "run_id": "execution-1",
        "instruction": "Inspect the failed authority test.",
        "expected_run_revision": 7,
        "idempotency_key": "control-key-1",
    }
    handler = SteerSubAgentHandler()

    await handler.handle(context, command)
    await handler.handle(context, command)
    await handler.handle(
        context,
        {**command, "instruction": "A different instruction under the same key."},
    )

    assert context.send_json.await_count == 3
    first, replay, conflict = [call.args[0] for call in context.send_json.await_args_list]
    assert first["type"] == "control_command_ack"
    assert first["accepted"] is True
    assert first["run_revision"] == 7
    assert replay == {**first, "duplicate": True}
    assert conflict["accepted"] is False
    assert conflict["reason_code"] == "idempotency_conflict"
    send_control.assert_awaited_once()
    control = send_control.await_args.args[0]
    assert control.run_id == "execution-1"
    assert control.target_agent_id == "agent-1"
    assert control.idempotency_key == "control-key-1"


@pytest.mark.unit
async def test_control_rejects_roster_mismatch_before_dispatch(monkeypatch) -> None:
    context, _redis = _context(participants=["different-agent"])
    send_control = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.websocket.handlers.control_handler."
        "RedisControlChannel.send_control",
        send_control,
    )

    await KillRunHandler().handle(
        context,
        {
            "type": "kill_run",
            "conversation_id": "conversation-1",
            "run_id": "execution-1",
            "expected_run_revision": 7,
            "idempotency_key": "control-key-2",
            "cascade": True,
        },
    )

    ack = context.send_json.await_args.args[0]
    assert ack["type"] == "control_command_ack"
    assert ack["accepted"] is False
    assert ack["reason_code"] == "subagent_control_denied"
    send_control.assert_not_awaited()


@pytest.mark.unit
async def test_control_rejects_stale_revision_with_authority_revision() -> None:
    context, _redis = _context()
    await SteerSubAgentHandler().handle(
        context,
        {
            "type": "steer",
            "conversation_id": "conversation-1",
            "run_id": "execution-1",
            "instruction": "Use the current revision.",
            "expected_run_revision": 6,
            "idempotency_key": "control-key-3",
        },
    )

    ack = context.send_json.await_args.args[0]
    assert ack["accepted"] is False
    assert ack["reason_code"] == "run_revision_conflict"
    assert ack["run_revision"] == 7


@pytest.mark.unit
def test_handlers_expose_client_protocol_message_types() -> None:
    assert KillRunHandler().message_type == "kill_run"
    assert SteerSubAgentHandler().message_type == "steer"
    assert {"kill_run", "steer"}.issubset(get_message_router().registered_types)
