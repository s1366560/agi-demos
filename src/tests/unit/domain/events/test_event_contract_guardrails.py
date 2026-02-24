"""Guardrail tests for frontend-facing agent event contracts."""

import pytest

from src.domain.events.types import (
    INTERNAL_EVENT_TYPES,
    AgentEventType,
    get_frontend_event_types,
)


@pytest.mark.unit
class TestEventContractGuardrails:
    """Protect critical event contract expectations during refactors."""

    def test_agent_event_type_values_are_unique(self):
        values = [event_type.value for event_type in AgentEventType]
        assert len(values) == len(set(values))

    def test_internal_event_types_are_not_exposed_to_frontend(self):
        frontend_event_types = set(get_frontend_event_types())
        for event_type in INTERNAL_EVENT_TYPES:
            assert event_type.value not in frontend_event_types

    def test_critical_runtime_event_types_are_exposed_to_frontend(self):
        frontend_event_types = set(get_frontend_event_types())
        expected_event_types = {
            "thought",
            "act",
            "observe",
            "text_start",
            "text_delta",
            "text_end",
            "complete",
            "error",
            "tools_updated",
            "task_list_updated",
            "task_updated",
            "task_start",
            "task_complete",
            "mcp_app_result",
            "mcp_app_registered",
            "memory_recalled",
            "memory_captured",
        }

        missing_event_types = expected_event_types - frontend_event_types
        assert not missing_event_types, (
            f"Critical frontend event types missing: {sorted(missing_event_types)}"
        )
