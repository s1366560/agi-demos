"""Live delivery and terminal outcome contract for an approved plan stream."""

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import aclosing
from typing import Any, Literal, cast


async def consume_approved_plan_stream(
    stream: AsyncGenerator[dict[str, Any], None],
    *,
    conversation_id: str,
    broadcast: Callable[[str, dict[str, Any]], Awaitable[None]],
) -> Literal["ready_review", "cancelled"]:
    """Broadcast the scoped stream and require an explicit terminal receipt."""
    async with aclosing(stream) as events:
        async for event in events:
            event_type = event.get("type")
            event_data = event.get("data", {})
            await broadcast(
                conversation_id,
                {**event, "conversation_id": conversation_id, "seq": event.get("id")},
            )
            if event_type == "error":
                detail = (
                    cast(dict[str, object], event_data).get("message")
                    if isinstance(event_data, dict)
                    else None
                )
                raise RuntimeError(
                    detail
                    if isinstance(detail, str) and detail
                    else "Approved plan execution failed"
                )
            if event_type == "cancelled":
                return "cancelled"
            if event_type == "complete":
                return "ready_review"
    raise RuntimeError("Approved plan stream ended without a terminal event")
