"""Consume trusted native control without classifying arbitrary tool text."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress

from src.infrastructure.agent.errors import AgentError, ErrorCategory
from src.infrastructure.agent.tools.result import ToolControlOutcome, ToolResult
from src.infrastructure.i18n import gettext as _


class NativeControlWaitError(AgentError):
    """A paused call lost authority; further agent steps must not infer user intent."""

    def __init__(self, cause: Exception | None = None) -> None:
        super().__init__(
            _("Computer Use lost authority while paused. Resume or Stop was not confirmed."),
            category=ErrorCategory.COMMUNICATION,
            cause=cause,
        )


def trusted_control(result: object) -> ToolControlOutcome | None:
    if (
        not isinstance(result, ToolResult)
        or not isinstance(result.control_outcome, ToolControlOutcome)
        or result.is_error
        or result.attachments
    ):
        return None
    try:
        payload = json.loads(result.output)
    except ValueError:
        return None
    if (
        payload
        != {
            "type": "computer_use_control",
            "status": result.control_outcome.value,
            "retry_allowed": False,
        }
        or payload.get("retry_allowed") is not False
    ):
        return None
    return result.control_outcome


async def await_native_control(
    result: ToolResult, abort: asyncio.Event | None
) -> ToolControlOutcome | None:
    if result.control_outcome == ToolControlOutcome.USER_STOPPED:
        return ToolControlOutcome.USER_STOPPED
    if result.control_wait is None:
        raise NativeControlWaitError
    try:
        pending = asyncio.ensure_future(result.control_wait())
    except Exception as exc:
        raise NativeControlWaitError(cause=exc) from exc
    cancelled = asyncio.create_task((abort or asyncio.Event()).wait())
    try:
        done, _ = await asyncio.wait({pending, cancelled}, return_when=asyncio.FIRST_COMPLETED)
        if cancelled in done:
            raise asyncio.CancelledError
        return pending.result()
    except Exception as exc:
        # Cancellation remains a run cancellation. A failed authority wait is a
        # real error, not a tool result the model may reinterpret as user Stop.
        raise NativeControlWaitError(cause=exc) from exc
    finally:
        for task in (pending, cancelled):
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task
