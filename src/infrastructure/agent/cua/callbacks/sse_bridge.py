"""
SSE Bridge for CUA events.

Provides utilities for converting CUA events to MemStack SSE format
and managing event streaming.
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, AsyncIterator, Callable, Dict, Optional

from src.domain.events.agent_events import (
    AgentDomainEvent,
    AgentEventType,
    AgentThoughtEvent,
    AgentTextDeltaEvent,
    AgentActEvent,
    AgentObserveEvent,
    AgentCostUpdateEvent,
    AgentStartEvent,
    AgentCompleteEvent,
)

logger = logging.getLogger(__name__)


class SSEBridge:
    """
    Bridge for converting CUA events to MemStack AgentDomainEvent events.

    This class provides:
    - Event type mapping between CUA and MemStack
    - Event filtering and transformation
    - Async iterator interface for streaming

    Usage:
        bridge = SSEBridge()

        # Convert single event
        domain_event = bridge.convert_event(cua_event)

        # Stream converted events
        async for event in bridge.stream(cua_event_source):
            yield event
    """

    # Mapping from CUA event types to MemStack AgentEventType
    EVENT_TYPE_MAP = {
        # Run lifecycle
        "cua_run_start": AgentEventType.START,
        "cua_run_end": AgentEventType.COMPLETE,
        # Action events
        "act": AgentEventType.ACT,
        "observe": AgentEventType.OBSERVE,
        # Text events
        "text_delta": AgentEventType.TEXT_DELTA,
        "thought": AgentEventType.THOUGHT,
        # Cost tracking
        "cost_update": AgentEventType.COST_UPDATE,
        # Screenshot (custom type - no direct mapping in core events yet, mapped to OBSERVE)
        "screenshot": AgentEventType.OBSERVE,
        # CUA-specific events (pass through)
        "cua_response": AgentEventType.OBSERVE,
        "cua_execution_start": AgentEventType.THOUGHT,
        "cua_execution_complete": AgentEventType.THOUGHT,
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

    def convert_event(self, cua_event: Dict[str, Any]) -> Optional[AgentDomainEvent]:
        """
        Convert a CUA event to MemStack AgentDomainEvent.

        Args:
            cua_event: CUA event dictionary with 'type' and 'data' keys

        Returns:
            AgentDomainEvent or None if event should be filtered out
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

        if mapped_type == AgentEventType.START:
            return AgentStartEvent()

        elif mapped_type == AgentEventType.COMPLETE:
            return AgentCompleteEvent(result=data)

        elif mapped_type == AgentEventType.ACT:
            return AgentActEvent(
                tool_name=data.get("tool_name", "unknown"),
                tool_input=data.get("tool_input", {}),
                call_id=data.get("call_id"),
                status=data.get("status", "running"),
            )

        elif mapped_type == AgentEventType.OBSERVE:
            # Handle special screenshot case
            if event_type == "screenshot":
                return AgentObserveEvent(
                    tool_name="screenshot",
                    result=data,
                    status="completed",
                )
            
            return AgentObserveEvent(
                tool_name=data.get("tool_name", "unknown"),
                result=data.get("result"),
                error=data.get("error"),
                duration_ms=data.get("duration_ms"),
                call_id=data.get("call_id"),
                status=data.get("status", "completed"),
            )

        elif mapped_type == AgentEventType.TEXT_DELTA:
            return AgentTextDeltaEvent(delta=data.get("delta", ""))

        elif mapped_type == AgentEventType.THOUGHT:
            content = data.get("content", "")
            if not content and event_type == "cua_execution_start":
                content = "Starting CUA execution..."
            elif not content and event_type == "cua_execution_complete":
                content = "CUA execution completed."
                
            return AgentThoughtEvent(
                content=content,
                thought_level="task"
            )

        elif mapped_type == AgentEventType.COST_UPDATE:
            return AgentCostUpdateEvent(
                cost=data.get("cost", 0.0),
                tokens=data.get("tokens", {})
            )

        # Default fallback for unknown types
        logger.debug(f"Unknown CUA event type: {event_type}, mapping to Thought")
        return AgentThoughtEvent(
            content=f"CUA event: {event_type} - {data}",
            thought_level="debug"
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
        domain_event = self.convert_event(cua_event)
        if domain_event is None:
            return None

        # Convert domain event to SSE-compatible dict using our new adapter method
        # But here we need to return a dict, not SSEEvent object, as the stream method expects dicts
        # We can implement a local helper or import the adapter
        
        # Simple manual conversion for now to match legacy behavior
        event_type = domain_event.event_type.value
        timestamp = datetime.fromtimestamp(domain_event.timestamp).isoformat()
        
        data = domain_event.model_dump(exclude={"event_type", "timestamp"})
        
        return {
            "type": event_type,
            "data": data,
            "timestamp": timestamp,
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
