"""
Event Converter - Unified Domain Event to SSE Event Conversion.

This module provides centralized event conversion logic, extracted from
ReActAgent to support the Single Responsibility Principle.

Handles conversion of:
- AgentDomainEvent → SSE dict format
- Backward compatibility transformations for frontend

Reference: Extracted from react_agent.py::_convert_domain_event()
"""

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

from src.domain.events.agent_events import (
    AgentActEvent,
    AgentArtifactCreatedEvent,
    AgentDomainEvent,
    AgentErrorEvent,
    AgentEventType,
    AgentObserveEvent,
    AgentTaskCompleteEvent,
    AgentTaskStartEvent,
    AgentThoughtEvent,
    SubAgentDelegationEvent,
)
from src.domain.events.event_dicts import SSEEventDict

logger = logging.getLogger(__name__)

_EVENT_ENVELOPE_META_KEYS = frozenset(
    {
        "type",
        "data",
        "timestamp",
        "event_time_us",
        "event_counter",
        "correlation_id",
        "id",
    }
)


def normalize_event_dict(
    event: Mapping[str, Any],
    *,
    agent_id: str | None = None,
) -> SSEEventDict | None:
    """Normalize legacy and modern stream events into a standard envelope."""
    event_type = str(event.get("type", "")).strip()
    if not event_type:
        logger.warning("[EventConverter] Skipping event without type: %s", event)
        return None

    normalized: dict[str, Any] = dict(event)
    payload = {
        key: value for key, value in normalized.items() if key not in _EVENT_ENVELOPE_META_KEYS
    }

    raw_data = normalized.get("data")
    data: dict[str, Any]
    if isinstance(raw_data, Mapping):
        data = dict(raw_data)
        for key, value in payload.items():
            data.setdefault(key, value)
    elif raw_data is None:
        data = dict(payload)
    else:
        data = dict(payload)
        data["value"] = raw_data

    if agent_id is not None:
        data.setdefault("agent_id", agent_id)

    normalized["type"] = event_type
    normalized["data"] = data
    normalized.setdefault("timestamp", datetime.now(UTC).isoformat())
    return cast(SSEEventDict, normalized)


class EventConverter:
    """
    Unified event converter for ReActAgent.

    Converts AgentDomainEvent objects to SSE-compatible dictionaries,
    handling backward compatibility transformations for the frontend.

    Usage:
        converter = EventConverter()

        # Convert standard domain events
        event_dict = converter.convert(domain_event)

    """

    def __init__(self, debug_logging: bool = False) -> None:
        """
        Initialize the event converter.

        Args:
            debug_logging: Whether to log debug information during conversion
        """
        self._debug_logging = debug_logging

    def convert(
        self,
        domain_event: AgentDomainEvent,
        agent_id: str | None = None,
    ) -> SSEEventDict | None:
        """
        Convert AgentDomainEvent to SSE event dictionary format.

        Applies backward compatibility transformations for the frontend.

        Args:
            domain_event: AgentDomainEvent from processor
            agent_id: Optional agent ID to inject into event data

        Returns:
            Event dict compatible with SSE streaming, or None to skip
        """
        event_type = domain_event.event_type

        if self._debug_logging:
            logger.info(f"[EventConverter] Converting event: type={event_type}")

        # Use unified serialization for most events
        event_dict = domain_event.to_event_dict()

        # Apply backward compatibility transformations
        result = self._apply_transformations(event_type, domain_event, event_dict)
        if result is None:
            return None
        return normalize_event_dict(result, agent_id=agent_id)

    def _apply_transformations(
        self,
        event_type: AgentEventType,
        domain_event: AgentDomainEvent,
        event_dict: SSEEventDict,
    ) -> SSEEventDict | None:
        """
        Apply backward compatibility transformations to event dict.

        Args:
            event_type: The event type
            domain_event: Original domain event
            event_dict: Base event dictionary

        Returns:
            Transformed event dict or None to skip
        """
        # COMPLETE event is handled separately in stream()
        if event_type == AgentEventType.COMPLETE:
            return None

        # OBSERVE event: add redundant 'observation' field for legacy compat
        if event_type == AgentEventType.OBSERVE and isinstance(domain_event, AgentObserveEvent):
            observation = (
                domain_event.result
                if domain_event.result is not None
                else (domain_event.error or "")
            )
            event_dict["data"]["observation"] = observation
            # Include error field if present - frontend uses this
            if domain_event.error:
                event_dict["data"]["error"] = domain_event.error

        # DOOM_LOOP_DETECTED: rename to 'doom_loop' for frontend
        if event_type == AgentEventType.DOOM_LOOP_DETECTED:
            event_dict["type"] = "doom_loop"

        # THOUGHT: rename content to thought
        if event_type == AgentEventType.THOUGHT and isinstance(domain_event, AgentThoughtEvent):
            event_dict["data"] = {
                "thought": domain_event.content,
                "thought_level": domain_event.thought_level,
            }

        # ACT: normalize call_id and tool_input
        if event_type == AgentEventType.ACT and isinstance(domain_event, AgentActEvent):
            event_dict["data"] = {
                "tool_name": domain_event.tool_name,
                "tool_input": domain_event.tool_input or {},
                "call_id": domain_event.call_id or "",
                "status": domain_event.status,
            }

        # ERROR: provide default code
        if event_type == AgentEventType.ERROR and isinstance(domain_event, AgentErrorEvent):
            event_dict["data"]["code"] = domain_event.code or "UNKNOWN"

        # ARTIFACT_CREATED: forward artifact info to frontend
        if event_type == AgentEventType.ARTIFACT_CREATED and isinstance(
            domain_event, AgentArtifactCreatedEvent
        ):
            event_dict["data"] = {
                "artifact_id": domain_event.artifact_id,
                "filename": domain_event.filename,
                "mime_type": domain_event.mime_type,
                "category": domain_event.category,
                "size_bytes": domain_event.size_bytes,
                "url": domain_event.url,
                "preview_url": domain_event.preview_url,
                "tool_execution_id": domain_event.tool_execution_id,
                "source_tool": domain_event.source_tool,
                "source_path": domain_event.source_path,
            }

        # TASK_START: normalize for timeline rendering
        if event_type == AgentEventType.TASK_START and isinstance(
            domain_event, AgentTaskStartEvent
        ):
            event_dict["data"] = {
                "task_id": domain_event.task_id,
                "content": domain_event.content,
                "order_index": domain_event.order_index,
                "total_tasks": domain_event.total_tasks,
            }

        # TASK_COMPLETE: normalize for timeline rendering
        if event_type == AgentEventType.TASK_COMPLETE and isinstance(
            domain_event, AgentTaskCompleteEvent
        ):
            event_dict["data"] = {
                "task_id": domain_event.task_id,
                "status": domain_event.status,
                "order_index": domain_event.order_index,
                "total_tasks": domain_event.total_tasks,
            }

        # SUBAGENT_DELEGATION: normalize for SubAgent delegation indicator
        if event_type == AgentEventType.SUBAGENT_DELEGATION and isinstance(
            domain_event, SubAgentDelegationEvent
        ):
            event_dict["data"] = {
                "conversation_id": domain_event.conversation_id,
                "from_agent_id": domain_event.from_agent_id,
                "to_subagent_id": domain_event.to_subagent_id,
                "to_subagent_name": domain_event.to_subagent_name,
                "trigger_type": domain_event.trigger_type,
                "task_description": domain_event.task_description,
            }

        # Lifecycle hardening events (SUBAGENT_SPAWN_REJECTED,
        # SUBAGENT_ANNOUNCE_RETRY, SUBAGENT_ORPHAN_DETECTED) pass
        # through without transformation -- their to_event_dict()
        # output is already frontend-compatible.
        return event_dict

    def convert_plan_event(self, event: dict[str, Any]) -> SSEEventDict:
        """
        Convert internal Plan Mode event to SSE event format.

        Args:
            event: Internal event from Plan Mode components

        Returns:
            SSE-compatible event dict
        """
        event_type: str = event.get("type", "unknown")

        # Map internal event types to SSE types
        type_mapping = {
            "PLAN_EXECUTION_START": "plan_execution_start",
            "PLAN_STEP_READY": "plan_step_ready",
            "PLAN_STEP_COMPLETE": "plan_step_complete",
            "PLAN_STEP_SKIPPED": "plan_step_skipped",
            "PLAN_EXECUTION_COMPLETE": "plan_execution_complete",
            "REFLECTION_COMPLETE": "reflection_complete",
            "ADJUSTMENT_APPLIED": "adjustment_applied",
        }

        event_type_str: str = type_mapping.get(event_type, event_type.lower())
        return SSEEventDict(
            type=event_type_str,
            data=event.get("data", {}),
            timestamp=datetime.now(UTC).isoformat(),
        )


# Module-level singleton for convenience
_default_converter: EventConverter | None = None


def get_event_converter() -> EventConverter:
    """
    Get the default event converter singleton.

    Returns:
        EventConverter instance
    """
    global _default_converter
    if _default_converter is None:
        _default_converter = EventConverter()
    return _default_converter


def set_event_converter(converter: EventConverter) -> None:
    """
    Set the default event converter singleton.

    Args:
        converter: EventConverter instance to use
    """
    global _default_converter
    _default_converter = converter
