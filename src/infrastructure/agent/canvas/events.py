"""Canvas event helpers.

Re-exports the domain event for convenience and provides a factory
function to build canvas event dicts from CanvasBlock instances.
"""

from __future__ import annotations

from typing import Any

# Re-export for convenience
from src.domain.events.agent_events import AgentCanvasUpdatedEvent
from src.domain.events.types import AgentEventType
from src.infrastructure.agent.canvas.models import CanvasBlock

__all__ = [
    "AgentCanvasUpdatedEvent",
    "AgentEventType",
    "build_canvas_event_dict",
]


def build_canvas_event_dict(
    conversation_id: str,
    block_id: str,
    action: str,
    block: CanvasBlock | None = None,
) -> dict[str, Any]:
    """Build a raw event dict suitable for ``ctx.emit()``.

    Args:
        conversation_id: Conversation scope.
        block_id: The affected block ID.
        action: One of "created", "updated", "deleted".
        block: The CanvasBlock (None for deletes).

    Returns:
        Dict matching the ``canvas_updated`` SSE event shape.
    """
    return {
        "type": AgentEventType.CANVAS_UPDATED.value,
        "data": {
            "conversation_id": conversation_id,
            "block_id": block_id,
            "action": action,
            "block": block.to_dict() if block is not None else None,
        },
    }
