"""
Event Converter - Unified Domain Event to SSE Event Conversion.

This module provides centralized event conversion logic, extracted from
ReActAgent to support the Single Responsibility Principle.

Handles conversion of:
- AgentDomainEvent → SSE dict format
- Skill execution events → SSE dict format
- Backward compatibility transformations for frontend

Reference: Extracted from react_agent.py::_convert_domain_event() and
           _convert_skill_domain_event()
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Protocol

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
)
from src.domain.events.event_dicts import SSEEventDict

logger = logging.getLogger(__name__)


class SkillLike(Protocol):
    """Protocol for Skill-like objects to avoid circular imports."""

    @property
    def id(self) -> str:
        ...

    @property
    def name(self) -> str:
        ...

    @property
    def tools(self) -> list:
        ...


class EventConverter:
    """
    Unified event converter for ReActAgent.

    Converts AgentDomainEvent objects to SSE-compatible dictionaries,
    handling backward compatibility transformations for the frontend.

    Usage:
        converter = EventConverter()

        # Convert standard domain events
        event_dict = converter.convert(domain_event)

        # Convert skill execution events
        event_dict = converter.convert_skill_event(domain_event, skill, step)
    """

    def __init__(self, debug_logging: bool = False):
        """
        Initialize the event converter.

        Args:
            debug_logging: Whether to log debug information during conversion
        """
        self._debug_logging = debug_logging

    def convert(self, domain_event: AgentDomainEvent) -> Optional[SSEEventDict]:
        """
        Convert AgentDomainEvent to SSE event dictionary format.

        Applies backward compatibility transformations for the frontend.

        Args:
            domain_event: AgentDomainEvent from processor

        Returns:
            Event dict compatible with SSE streaming, or None to skip
        """
        event_type = domain_event.event_type

        if self._debug_logging:
            logger.info(f"[EventConverter] Converting event: type={event_type}")

        # Use unified serialization for most events
        event_dict = domain_event.to_event_dict()

        # Apply backward compatibility transformations
        return self._apply_transformations(event_type, domain_event, event_dict)

    def _apply_transformations(
        self,
        event_type: AgentEventType,
        domain_event: AgentDomainEvent,
        event_dict: SSEEventDict,
    ) -> Optional[SSEEventDict]:
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
        if event_type == AgentEventType.OBSERVE and isinstance(
            domain_event, AgentObserveEvent
        ):
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
        if event_type == AgentEventType.THOUGHT and isinstance(
            domain_event, AgentThoughtEvent
        ):
            event_dict["data"] = {
                "thought": domain_event.content,
                "thought_level": domain_event.thought_level,
            }

        # ACT: normalize call_id and tool_input
        if event_type == AgentEventType.ACT and isinstance(
            domain_event, AgentActEvent
        ):
            event_dict["data"] = {
                "tool_name": domain_event.tool_name,
                "tool_input": domain_event.tool_input or {},
                "call_id": domain_event.call_id or "",
                "status": domain_event.status,
            }

        # ERROR: provide default code
        if event_type == AgentEventType.ERROR and isinstance(
            domain_event, AgentErrorEvent
        ):
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

        return event_dict

    def convert_skill_event(
        self,
        domain_event: AgentDomainEvent,
        skill: SkillLike,
        current_step: int,
    ) -> Optional[SSEEventDict]:
        """
        Convert SkillExecutor domain event to SSE event format.

        Args:
            domain_event: Domain event from SkillExecutor
            skill: The skill being executed
            current_step: Current step index in the skill execution

        Returns:
            Converted event dict or None to skip
        """
        event_type = domain_event.event_type
        timestamp = datetime.fromtimestamp(domain_event.timestamp).isoformat()

        if event_type == AgentEventType.THOUGHT:
            return self._convert_skill_thought(domain_event, skill, timestamp)

        elif event_type == AgentEventType.ACT:
            return self._convert_skill_act(domain_event, skill, current_step, timestamp)

        elif event_type == AgentEventType.OBSERVE:
            return self._convert_skill_observe(
                domain_event, skill, current_step, timestamp
            )

        elif event_type == AgentEventType.SKILL_EXECUTION_COMPLETE:
            # Completion handled in _execute_skill_directly
            return None

        # Skip other event types
        return None

    def _convert_skill_thought(
        self,
        domain_event: AgentDomainEvent,
        skill: SkillLike,
        timestamp: str,
    ) -> Optional[SSEEventDict]:
        """Convert skill thought event."""
        if not isinstance(domain_event, AgentThoughtEvent):
            return None

        thought_level = domain_event.thought_level

        # Map skill thoughts to appropriate event types
        if thought_level == "skill":
            return {
                "type": "thought",
                "data": {
                    "thought": domain_event.content,
                    "thought_level": "skill",
                    "skill_id": skill.id,
                },
                "timestamp": timestamp,
            }
        elif thought_level == "skill_complete":
            # Skill completion thought - handled separately
            return None

        return {
            "type": "thought",
            "data": {
                "thought": domain_event.content,
                "thought_level": thought_level,
            },
            "timestamp": timestamp,
        }

    def _convert_skill_act(
        self,
        domain_event: AgentDomainEvent,
        skill: SkillLike,
        current_step: int,
        timestamp: str,
    ) -> Optional[SSEEventDict]:
        """Convert skill act event."""
        if not isinstance(domain_event, AgentActEvent):
            return None

        return {
            "type": "skill_tool_start",
            "data": {
                "skill_id": skill.id,
                "skill_name": skill.name,
                "tool_name": domain_event.tool_name,
                "tool_input": domain_event.tool_input or {},
                "step_index": current_step,
                "total_steps": len(skill.tools),
                "status": domain_event.status,
            },
            "timestamp": timestamp,
        }

    def _convert_skill_observe(
        self,
        domain_event: AgentDomainEvent,
        skill: SkillLike,
        current_step: int,
        timestamp: str,
    ) -> Optional[SSEEventDict]:
        """Convert skill observe event."""
        if not isinstance(domain_event, AgentObserveEvent):
            return None

        return {
            "type": "skill_tool_result",
            "data": {
                "skill_id": skill.id,
                "skill_name": skill.name,
                "tool_name": domain_event.tool_name,
                "result": domain_event.result,
                "error": domain_event.error,
                "duration_ms": domain_event.duration_ms or 0,
                "step_index": current_step,
                "total_steps": len(skill.tools),
                "status": domain_event.status,
            },
            "timestamp": timestamp,
        }

    def convert_plan_event(self, event: Dict[str, Any]) -> SSEEventDict:
        """
        Convert internal Plan Mode event to SSE event format.

        Args:
            event: Internal event from Plan Mode components

        Returns:
            SSE-compatible event dict
        """
        event_type = event.get("type", "unknown")

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

        return {
            "type": type_mapping.get(event_type, event_type.lower()),
            "data": event.get("data", {}),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# Module-level singleton for convenience
_default_converter: Optional[EventConverter] = None


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
