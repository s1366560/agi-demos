"""Unit tests for the Phase 4 WorkspaceInboxLoop primitive."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.model.workspace.wtp_envelope import WtpVerb
from src.domain.ports.services.agent_message_bus_port import (
    AgentMessage,
    AgentMessageType,
)
from src.infrastructure.agent.workspace.workspace_inbox_loop import (
    WorkspaceInboxLoop,
    _envelope_from_message,
)

pytestmark = pytest.mark.unit


def _wtp_message(verb: str = "task.assign", **overrides) -> AgentMessage:
    meta = {
        "wtp_version": "1",
        "wtp_verb": verb,
        "workspace_id": "ws-1",
        "task_id": "t-1",
        "attempt_id": "a-1",
        "correlation_id": "corr-1",
    }
    meta.update(overrides.get("metadata", {}))
    return AgentMessage(
        message_id=overrides.get("message_id", "m-1"),
        from_agent_id="leader",
        to_agent_id="worker",
        session_id="worker-session",
        content=overrides.get("content", json.dumps({"title": "T", "description": "D"})),
        message_type=AgentMessageType.REQUEST,
        metadata=meta,
    )


class TestEnvelopeParsing:
    def test_non_wtp_message_returns_none(self):
        msg = AgentMessage(
            message_id="m-0",
            from_agent_id="x",
            to_agent_id="y",
            session_id="s",
            content="hi",
            message_type=AgentMessageType.NOTIFICATION,
            metadata={"foo": "bar"},
        )
        assert _envelope_from_message(msg) is None

    def test_unparseable_json_uses_empty_payload(self):
        msg = _wtp_message(content="not json{{{")
        env = _envelope_from_message(msg)
        # envelope may or may not validate depending on verb; task.assign requires
        # title+description so it will fail validation → returns None.
        assert env is None

    def test_valid_envelope_parses(self):
        msg = _wtp_message()
        env = _envelope_from_message(msg)
        assert env is not None
        assert env.verb == WtpVerb.TASK_ASSIGN
        assert env.task_id == "t-1"
        assert env.payload["title"] == "T"


class TestInboxLoopDispatch:
    async def test_handler_invoked_for_registered_verb(self):
        handler = AsyncMock()
        call_count = {"n": 0}

        async def _subscribe(**_kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                yield _wtp_message()
            else:
                await asyncio.sleep(0.1)
            return

        bus = MagicMock()
        bus.subscribe_messages = _subscribe
        loop = WorkspaceInboxLoop(
            bus,
            agent_id="worker",
            session_id="worker-session",
            handlers={WtpVerb.TASK_ASSIGN: handler},
        )
        await loop.start()
        await asyncio.sleep(0.05)
        await loop.stop()
        handler.assert_awaited()
        env_arg = handler.await_args.args[0]
        assert env_arg.verb == WtpVerb.TASK_ASSIGN

    async def test_unregistered_verb_skipped(self):
        handler = AsyncMock()
        call_count = {"n": 0}

        async def _subscribe(**_kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                yield _wtp_message(verb="task.progress", content=json.dumps({"phase": "x", "summary": "y"}))
            else:
                await asyncio.sleep(0.1)
            return

        bus = MagicMock()
        bus.subscribe_messages = _subscribe
        loop = WorkspaceInboxLoop(
            bus,
            agent_id="worker",
            session_id="worker-session",
            handlers={WtpVerb.TASK_ASSIGN: handler},  # wrong verb registered
        )
        await loop.start()
        await asyncio.sleep(0.05)
        await loop.stop()
        handler.assert_not_awaited()

    async def test_handler_exception_does_not_kill_loop(self):
        calls = []

        async def _boom(envelope, _msg):
            calls.append(envelope.verb)
            raise RuntimeError("boom")

        call_count = {"n": 0}

        async def _subscribe(**_kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                yield _wtp_message()
                yield _wtp_message(message_id="m-2")
            else:
                await asyncio.sleep(0.1)
            return

        bus = MagicMock()
        bus.subscribe_messages = _subscribe
        loop = WorkspaceInboxLoop(
            bus,
            agent_id="worker",
            session_id="worker-session",
            handlers={WtpVerb.TASK_ASSIGN: _boom},
        )
        await loop.start()
        await asyncio.sleep(0.05)
        await loop.stop()
        assert len(calls) == 2  # both messages were dispatched despite error

    async def test_stop_is_idempotent(self):
        async def _subscribe(**_kwargs):
            await asyncio.sleep(0.1)
            if False:
                yield  # pragma: no cover
            return

        bus = MagicMock()
        bus.subscribe_messages = _subscribe
        loop = WorkspaceInboxLoop(
            bus, agent_id="w", session_id="s", handlers={}
        )
        await loop.start()
        await loop.stop()
        await loop.stop()  # second stop must not raise
        assert loop.running is False
