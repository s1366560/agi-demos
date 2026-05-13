"""
Workspace Inbox Loop — Phase 4 of the WTP rollout.

A :class:`WorkspaceInboxLoop` subscribes to a worker session's A2A inbound
stream via :class:`AgentMessageBusPort.subscribe_messages` and dispatches
WTP-shaped messages to a small set of handlers. Each worker session gets
exactly one loop; non-WTP messages fall through to the default handler.

Design goals:

* **Out of the ReAct critical path** — the subscribe loop runs as an
  independent asyncio task, identical in shape to how
  :class:`WorkspaceSupervisor` consumes its fan-in stream.
* **Pluggable handlers** — one callable per verb. Unhandled verbs are
  logged once and skipped; we never crash the loop on a bad envelope.
* **Cooperative shutdown** — :meth:`stop` cancels the task and waits for
  the subscribe generator to drain. Safe to call multiple times.

Wiring into the worker session bootstrap (spawning + lifecycle tie-in) is
intentionally **not** done in this module — that belongs to
``agent_worker_state`` and is the first task of a follow-up PR. This file
ships the primitive + its tests so the plumbing can be unit-tested in
isolation.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from src.domain.model.workspace.wtp_envelope import (
    WtpEnvelope,
    WtpValidationError,
    WtpVerb,
)
from src.domain.ports.services.agent_message_bus_port import (
    AgentMessage,
    AgentMessageBusPort,
)

logger = logging.getLogger(__name__)

WtpHandler = Callable[[WtpEnvelope, AgentMessage], Awaitable[None]]


def _envelope_from_message(message: AgentMessage) -> WtpEnvelope | None:
    """Return a :class:`WtpEnvelope` if ``message`` carries a WTP payload."""
    metadata = message.metadata or {}
    if not isinstance(metadata, dict):
        return None
    if metadata.get("wtp_version") is None and metadata.get("wtp_verb") is None:
        return None

    # Compose the dict shape WtpEnvelope.from_dict expects (mirrors to_dict).
    try:
        payload_text = message.content or "{}"
        payload = json.loads(payload_text) if payload_text.strip() else {}
    except (TypeError, ValueError):
        logger.warning(
            "WorkspaceInboxLoop: WTP message content is not valid JSON "
            "(msg=%s verb=%s); treating as empty payload",
            message.message_id,
            metadata.get("wtp_verb"),
        )
        payload = {}

    data: dict[str, Any] = {
        "verb": metadata.get("wtp_verb"),
        "workspace_id": metadata.get("workspace_id"),
        "task_id": metadata.get("task_id"),
        "attempt_id": metadata.get("attempt_id"),
        "correlation_id": metadata.get("correlation_id"),
        "root_goal_task_id": metadata.get("root_goal_task_id"),
        "parent_message_id": message.parent_message_id,
        "payload": payload if isinstance(payload, dict) else {"_raw": payload},
        "extra_metadata": {
            k: v
            for k, v in metadata.items()
            if k
            not in (
                "wtp_version",
                "wtp_verb",
                "workspace_id",
                "task_id",
                "attempt_id",
                "correlation_id",
                "root_goal_task_id",
            )
        },
    }
    try:
        return WtpEnvelope.from_dict(data)
    except (WtpValidationError, KeyError, ValueError) as exc:
        logger.warning(
            "WorkspaceInboxLoop: failed to parse WTP envelope from msg=%s: %s",
            message.message_id,
            exc,
        )
        return None


class WorkspaceInboxLoop:
    """Per-worker-session subscribe loop.

    Parameters
    ----------
    bus:
        The :class:`AgentMessageBusPort` implementation (typically
        ``RedisAgentMessageBus``).
    agent_id:
        Worker agent id (the sub of ``subscribe_messages``).
    session_id:
        Worker conversation id.
    handlers:
        Mapping of :class:`WtpVerb` → async handler. Each handler receives
        the parsed envelope **and** the original :class:`AgentMessage`.
    timeout_ms:
        Block timeout passed to ``subscribe_messages`` per iteration.
    """

    def __init__(
        self,
        bus: AgentMessageBusPort,
        *,
        agent_id: str,
        session_id: str,
        handlers: dict[WtpVerb, WtpHandler] | None = None,
        timeout_ms: int = 5_000,
    ) -> None:
        self._bus = bus
        self._agent_id = agent_id
        self._session_id = session_id
        self._handlers: dict[WtpVerb, WtpHandler] = dict(handlers or {})
        self._timeout_ms = timeout_ms
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def register(self, verb: WtpVerb, handler: WtpHandler) -> None:
        self._handlers[verb] = handler

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._run(),
            name=f"workspace_inbox_loop:{self._agent_id}:{self._session_id}",
        )
        logger.info(
            "WorkspaceInboxLoop started agent=%s session=%s",
            self._agent_id,
            self._session_id,
        )

    async def stop(self) -> None:
        self._stop_event.set()
        task = self._task
        if task is None:
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        finally:
            self._task = None
            logger.info(
                "WorkspaceInboxLoop stopped agent=%s session=%s",
                self._agent_id,
                self._session_id,
            )

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                async for message in self._bus.subscribe_messages(
                    agent_id=self._agent_id,
                    session_id=self._session_id,
                    timeout_ms=self._timeout_ms,
                ):
                    if self._stop_event.is_set():
                        return
                    await self._handle_message(message)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "WorkspaceInboxLoop iteration failed agent=%s session=%s",
                    self._agent_id,
                    self._session_id,
                )
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=2.0)
                    return
                except TimeoutError:
                    continue

    async def _handle_message(self, message: AgentMessage) -> None:
        envelope = _envelope_from_message(message)
        if envelope is None:
            logger.debug(
                "WorkspaceInboxLoop: non-WTP message passing through (msg=%s)",
                message.message_id,
            )
            return

        handler = self._handlers.get(envelope.verb)
        if handler is None:
            logger.info(
                "WorkspaceInboxLoop: no handler registered for verb=%s (session=%s)",
                envelope.verb.value,
                self._session_id,
            )
            return

        try:
            await handler(envelope, message)
        except Exception:
            logger.exception(
                "WorkspaceInboxLoop handler failed verb=%s session=%s",
                envelope.verb.value,
                self._session_id,
            )


__all__ = [
    "WorkspaceInboxLoop",
    "WtpHandler",
]
