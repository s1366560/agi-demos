"""
SSE Bridge for CUA events.

Provides utilities for converting CUA events to MemStack SSE format
and managing event streaming.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, AsyncIterator, Callable, Dict, Optional

from src.infrastructure.agent.core.events import SSEEvent, SSEEventType

logger = logging.getLogger(__name__)


class SSEBridge:
    """
    Bridge for converting CUA events to MemStack SSE events.

    This class provides:
    - Event type mapping between CUA and MemStack
    - Event filtering and transformation
    - Async iterator interface for streaming

    Usage:
        bridge = SSEBridge()

        # Convert single event
        sse_event = bridge.convert_event(cua_event)

        # Stream converted events
        async for event in bridge.stream(cua_event_source):
            yield event
    """

    # Mapping from CUA event types to MemStack SSE event types
    EVENT_TYPE_MAP = {
        # Run lifecycle
        "cua_run_start": SSEEventType.START,
        "cua_run_end": SSEEventType.COMPLETE,
        # Action events
        "act": SSEEventType.ACT,
        "observe": SSEEventType.OBSERVE,
        # Text events
        "text_delta": SSEEventType.TEXT_DELTA,
        "thought": SSEEventType.THOUGHT,
        # Cost tracking
        "cost_update": SSEEventType.COST_UPDATE,
        # Screenshot (custom type)
        "screenshot": "screenshot",  # Pass through as custom type
        # CUA-specific events (pass through)
        "cua_response": "cua_response",
        "cua_execution_start": "cua_execution_start",
        "cua_execution_complete": "cua_execution_complete",
    }

    def __init__(
        self,
        filter_fn: Optional[Callable[[Dict[str, Any]], bool]] = None,
        transform_fn: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    ):
        """
        Initialize SSE Bridge.

        Args:
            filter_fn: Optional function to filter events (return True to include)
            transform_fn: Optional function to transform event data
        """
        self._filter_fn = filter_fn
        self._transform_fn = transform_fn

    def convert_event(self, cua_event: Dict[str, Any]) -> Optional[SSEEvent]:
        """
        Convert a CUA event to MemStack SSEEvent.

        Args:
            cua_event: CUA event dictionary with 'type' and 'data' keys

        Returns:
            SSEEvent or None if event should be filtered out
        """
        event_type = cua_event.get("type", "unknown")
        data = cua_event.get("data", {})

        # Apply filter
        if self._filter_fn and not self._filter_fn(cua_event):
            return None

        # Apply transform
        if self._transform_fn:
            data = self._transform_fn(data)

        # Map event type
        mapped_type = self.EVENT_TYPE_MAP.get(event_type)

        if mapped_type is None:
            # Unknown event type - pass through as custom
            logger.debug(f"Unknown CUA event type: {event_type}")
            return SSEEvent(
                type=SSEEventType.THOUGHT,  # Default to thought
                data={
                    "content": f"CUA event: {event_type}",
                    "original_type": event_type,
                    "original_data": data,
                },
            )

        # Handle string types (custom events)
        if isinstance(mapped_type, str):
            # For custom event types, wrap in a generic SSEEvent
            return SSEEvent(
                type=SSEEventType.OBSERVE,  # Use observe as container
                data={
                    "cua_event_type": mapped_type,
                    **data,
                },
            )

        # Create SSEEvent with mapped type
        return SSEEvent(
            type=mapped_type,
            data=data,
        )

    def convert_to_dict(self, cua_event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Convert a CUA event to MemStack event dictionary format.

        This is a convenience method that returns the dict format
        expected by the existing MemStack SSE system.

        Args:
            cua_event: CUA event dictionary

        Returns:
            Event dictionary or None if filtered out
        """
        sse_event = self.convert_event(cua_event)
        if sse_event is None:
            return None

        return {
            "type": sse_event.type.value
            if hasattr(sse_event.type, "value")
            else str(sse_event.type),
            "data": sse_event.data,
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def stream(
        self,
        event_source: AsyncIterator[Dict[str, Any]],
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Stream and convert CUA events to MemStack format.

        Args:
            event_source: Async iterator of CUA events

        Yields:
            Converted event dictionaries
        """
        async for cua_event in event_source:
            converted = self.convert_to_dict(cua_event)
            if converted:
                yield converted

    async def stream_from_queue(
        self,
        queue: asyncio.Queue,
        timeout: Optional[float] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Stream and convert CUA events from an asyncio Queue.

        Args:
            queue: Queue containing CUA events (None signals end)
            timeout: Optional timeout for queue.get()

        Yields:
            Converted event dictionaries
        """
        while True:
            try:
                if timeout:
                    cua_event = await asyncio.wait_for(queue.get(), timeout=timeout)
                else:
                    cua_event = await queue.get()

                # None signals end of stream
                if cua_event is None:
                    break

                converted = self.convert_to_dict(cua_event)
                if converted:
                    yield converted

            except asyncio.TimeoutError:
                logger.warning("SSE Bridge timeout waiting for event")
                break
            except Exception as e:
                logger.error(f"SSE Bridge error: {e}")
                yield {
                    "type": "error",
                    "data": {"message": str(e), "code": "SSE_BRIDGE_ERROR"},
                    "timestamp": datetime.utcnow().isoformat(),
                }
                break


def create_screenshot_filter(include_screenshots: bool = True) -> Callable[[Dict[str, Any]], bool]:
    """
    Create a filter function for screenshot events.

    Args:
        include_screenshots: Whether to include screenshot events

    Returns:
        Filter function
    """

    def filter_fn(event: Dict[str, Any]) -> bool:
        if not include_screenshots and event.get("type") == "screenshot":
            return False
        return True

    return filter_fn


def create_event_type_filter(
    include_types: Optional[list] = None,
    exclude_types: Optional[list] = None,
) -> Callable[[Dict[str, Any]], bool]:
    """
    Create a filter function based on event types.

    Args:
        include_types: List of event types to include (None = all)
        exclude_types: List of event types to exclude

    Returns:
        Filter function
    """
    exclude_types = exclude_types or []

    def filter_fn(event: Dict[str, Any]) -> bool:
        event_type = event.get("type")

        if event_type in exclude_types:
            return False

        if include_types is not None and event_type not in include_types:
            return False

        return True

    return filter_fn
