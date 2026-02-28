"""Unified context for tool execution.

Provides ToolContext (passed to every tool) and ToolAbortedError.
ToolContext replaces scattered dependencies and the _pending_events pattern
with a single object that carries identity, cancellation, event emission,
and permission request capabilities.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import Any


class ToolAbortedError(Exception):
    """Raised when a tool execution is aborted by user or timeout."""


@dataclass
class ToolContext:
    """Unified context passed to every tool execution.

    Replaces scattered dependencies and the _pending_events pattern.
    Every tool receives this context for identity, cancellation, event
    emission, and permission requests.

    Attributes:
        session_id: Current session identifier.
        message_id: Identifier of the triggering message.
        call_id: Unique identifier for this tool invocation.
        agent_name: Name of the agent executing the tool.
        conversation_id: Conversation scope for this execution.
        abort_signal: Cancellation signal; set to request abort.
        messages: Read-only snapshot of conversation messages.
    """

    session_id: str
    message_id: str
    call_id: str
    agent_name: str
    conversation_id: str

    # Cancellation
    abort_signal: asyncio.Event = field(default_factory=asyncio.Event)

    # Conversation access (read-only snapshot)
    messages: list[Any] = field(default_factory=list)

    # Project / user identity (populated by pipeline when available)
    project_id: str = ""
    user_id: str = ""

    # Internal event collection (pipeline reads these)
    _pending_events: list[Any] = field(default_factory=list, repr=False)

    async def metadata(self, data: dict[str, Any]) -> None:
        """Emit metadata update to the UI in real-time.

        Args:
            data: Key-value metadata to send to the frontend.
        """
        from src.infrastructure.agent.tools.result import ToolEvent

        self._pending_events.append(
            ToolEvent(
                type="metadata",
                tool_name="",  # Filled by pipeline
                data=data,
            )
        )

    async def emit(self, event: Any) -> None:
        """Emit a domain event (task update, artifact, etc.).

        Replaces the _pending_events + consume_pending_events() pattern.
        Events are collected by the ToolPipeline automatically.

        Args:
            event: Domain event object to emit.
        """
        self._pending_events.append(event)

    async def ask(self, permission: str, description: str = "") -> bool:
        """Request user permission. Blocks until response.

        This is a placeholder that the ToolPipeline will wire up
        to the actual PermissionManager.

        Args:
            permission: Permission identifier to request.
            description: Human-readable description of what is requested.

        Returns:
            True if permission is granted, False otherwise.
        """
        # Default implementation - pipeline will override this
        _ = permission
        _ = description
        return True

    async def race(
        self,
        awaitable: Awaitable[Any],
        timeout: float | None = None,
    ) -> Any:
        """Race an awaitable against the abort signal and optional timeout.

        Use for long-running tool operations (terminal commands, HTTP
        requests). Raises ToolAbortedError if abort signal fires.
        Raises asyncio.TimeoutError if timeout expires.

        Args:
            awaitable: The coroutine or future to race.
            timeout: Maximum seconds to wait (None = no timeout).

        Returns:
            The result of the awaitable.

        Raises:
            ToolAbortedError: If abort signal fires or task is cancelled.
            TimeoutError: If timeout expires before completion.
        """
        main_task = asyncio.ensure_future(awaitable)
        abort_task = asyncio.ensure_future(self.abort_signal.wait())

        try:
            done, pending = await asyncio.wait(
                {main_task, abort_task},
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in pending:
                _ = task.cancel()

            if abort_task in done:
                raise ToolAbortedError("Tool execution aborted by user")

            if not done:
                raise TimeoutError(f"Tool execution timed out after {timeout}s")

            return done.pop().result()
        except asyncio.CancelledError:
            raise ToolAbortedError("Tool execution cancelled") from None

    def consume_pending_events(self) -> list[Any]:
        """Consume and return all pending events.

        Used by ToolPipeline to collect events after tool execution.

        Returns:
            List of events that were pending.
        """
        events = self._pending_events[:]
        self._pending_events.clear()
        return events
