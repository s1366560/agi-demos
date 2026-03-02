"""Tests for multi-select decision HITL feature.

Covers selection_mode extraction, DecisionType.MULTI_CHOICE mapping,
list[str] response handling, and passthrough across 3 backend paths:
- hitl_tool_handler.py (handle_decision_tool)
- hitl_strategies.py (DecisionStrategy)
- ray_hitl_handler.py (RayHITLHandler.request_decision)
- AgentDecisionAskedEvent (domain event fields)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.events.agent_events import AgentDecisionAskedEvent
from src.domain.model.agent.hitl.hitl_types import DecisionType
from src.infrastructure.agent.hitl.hitl_strategies import (
    DecisionStrategy,
)

# -------------------------------------------------------------------
# Group A: hitl_tool_handler — selection_mode extraction
# -------------------------------------------------------------------


@pytest.mark.unit
class TestMultiSelectDecision:
    """Multi-select decision HITL tests across all backend paths."""

    # -- A. hitl_tool_handler tests ------------------------------------

    async def test_handle_decision_tool_single_mode_default(
        self,
    ) -> None:
        """No selection_mode arg defaults to 'single'."""
        from src.infrastructure.agent.processor.hitl_tool_handler import (
            handle_decision_tool,
        )

        coordinator = AsyncMock()
        coordinator.prepare_request = AsyncMock(return_value="req-1")
        coordinator.wait_for_response = AsyncMock(return_value="decision")

        tool_part = MagicMock()
        tool_part.tool_execution_id = "exec-1"
        arguments = {
            "question": "Pick a strategy",
            "options": [
                {"id": "a", "label": "Alpha"},
            ],
        }

        events = []
        async for event in handle_decision_tool(
            coordinator=coordinator,
            call_id="call-1",
            tool_name="request_decision",
            arguments=arguments,
            tool_part=tool_part,
        ):
            events.append(event)

        # request_data passed to prepare_request
        request_data = coordinator.prepare_request.call_args.args[1]
        assert request_data["selection_mode"] == "single"

    async def test_handle_decision_tool_multiple_mode_extracted(
        self,
    ) -> None:
        """selection_mode='multiple' is extracted and passed."""
        from src.infrastructure.agent.processor.hitl_tool_handler import (
            handle_decision_tool,
        )

        coordinator = AsyncMock()
        coordinator.prepare_request = AsyncMock(return_value="req-2")
        coordinator.wait_for_response = AsyncMock(return_value="decision")

        tool_part = MagicMock()
        tool_part.tool_execution_id = "exec-2"
        arguments = {
            "question": "Select frameworks",
            "options": [
                {"id": "react", "label": "React"},
                {"id": "vue", "label": "Vue"},
            ],
            "selection_mode": "multiple",
        }

        events = []
        async for event in handle_decision_tool(
            coordinator=coordinator,
            call_id="call-2",
            tool_name="request_decision",
            arguments=arguments,
            tool_part=tool_part,
        ):
            events.append(event)

        request_data = coordinator.prepare_request.call_args.args[1]
        assert request_data["selection_mode"] == "multiple"

        # Also verify the yielded event carries the field
        decision_asked = [e for e in events if isinstance(e, AgentDecisionAskedEvent)]
        assert len(decision_asked) == 1
        assert decision_asked[0].selection_mode == "multiple"

    async def test_handle_decision_tool_max_selections_extracted(
        self,
    ) -> None:
        """max_selections=3 is extracted and passed through."""
        from src.infrastructure.agent.processor.hitl_tool_handler import (
            handle_decision_tool,
        )

        coordinator = AsyncMock()
        coordinator.prepare_request = AsyncMock(return_value="req-3")
        coordinator.wait_for_response = AsyncMock(return_value="decision")

        tool_part = MagicMock()
        tool_part.tool_execution_id = "exec-3"
        arguments = {
            "question": "Select up to 3",
            "options": [
                {"id": "a", "label": "A"},
                {"id": "b", "label": "B"},
                {"id": "c", "label": "C"},
                {"id": "d", "label": "D"},
            ],
            "selection_mode": "multiple",
            "max_selections": 3,
        }

        events = []
        async for event in handle_decision_tool(
            coordinator=coordinator,
            call_id="call-3",
            tool_name="request_decision",
            arguments=arguments,
            tool_part=tool_part,
        ):
            events.append(event)

        request_data = coordinator.prepare_request.call_args.args[1]
        assert request_data["max_selections"] == 3

        decision_asked = [e for e in events if isinstance(e, AgentDecisionAskedEvent)]
        assert len(decision_asked) == 1
        assert decision_asked[0].max_selections == 3

    async def test_handle_decision_tool_multiple_mode_in_request_data(
        self,
    ) -> None:
        """selection_mode is included in request_data dict."""
        from src.infrastructure.agent.processor.hitl_tool_handler import (
            handle_decision_tool,
        )

        coordinator = AsyncMock()
        coordinator.prepare_request = AsyncMock(return_value="req-4")
        coordinator.wait_for_response = AsyncMock(return_value="decision")

        tool_part = MagicMock()
        tool_part.tool_execution_id = "exec-4"
        arguments = {
            "question": "Choose",
            "options": [{"id": "x", "label": "X"}],
            "selection_mode": "multiple",
            "max_selections": 2,
        }

        events = []
        async for event in handle_decision_tool(
            coordinator=coordinator,
            call_id="call-4",
            tool_name="request_decision",
            arguments=arguments,
            tool_part=tool_part,
        ):
            events.append(event)

        request_data = coordinator.prepare_request.call_args.args[1]
        assert "selection_mode" in request_data
        assert "max_selections" in request_data
        assert request_data["selection_mode"] == "multiple"
        assert request_data["max_selections"] == 2

    # -- B. hitl_strategies.py tests -----------------------------------

    def test_decision_strategy_multiple_maps_to_multi_choice(
        self,
    ) -> None:
        """selection_mode='multiple' maps to DecisionType.MULTI_CHOICE."""
        strategy = DecisionStrategy()
        request_data = {
            "question": "Select items",
            "options": [
                {"id": "a", "label": "A"},
                {"id": "b", "label": "B"},
            ],
            "selection_mode": "multiple",
            "decision_type": "single_choice",
        }

        request = strategy.create_request(
            conversation_id="conv-1",
            request_data=request_data,
            timeout_seconds=60.0,
            tenant_id="t-1",
            project_id="p-1",
        )

        assert request.decision_data is not None
        assert request.decision_data.decision_type == DecisionType.MULTI_CHOICE

    def test_decision_strategy_single_maps_to_decision_type_str(
        self,
    ) -> None:
        """selection_mode='single' uses the decision_type_str value."""
        strategy = DecisionStrategy()
        request_data = {
            "question": "Pick one",
            "options": [
                {"id": "a", "label": "A"},
            ],
            "selection_mode": "single",
            "decision_type": "single_choice",
        }

        request = strategy.create_request(
            conversation_id="conv-2",
            request_data=request_data,
            timeout_seconds=60.0,
            tenant_id="t-1",
            project_id="p-1",
        )

        assert request.decision_data is not None
        assert request.decision_data.decision_type == DecisionType.SINGLE_CHOICE

    def test_decision_strategy_max_selections_passed_through(
        self,
    ) -> None:
        """max_selections in request_data reaches the HITLRequest."""
        strategy = DecisionStrategy()
        request_data = {
            "question": "Select up to 2",
            "options": [
                {"id": "a", "label": "A"},
                {"id": "b", "label": "B"},
                {"id": "c", "label": "C"},
            ],
            "selection_mode": "multiple",
            "max_selections": 2,
        }

        request = strategy.create_request(
            conversation_id="conv-3",
            request_data=request_data,
            timeout_seconds=60.0,
            tenant_id="t-1",
            project_id="p-1",
        )

        assert request.decision_data is not None
        assert request.decision_data.max_selections == 2

    def test_decision_strategy_extract_response_value_string(
        self,
    ) -> None:
        """String response_data returns the string directly."""
        strategy = DecisionStrategy()
        result = strategy.extract_response_value("option-a")
        assert result == "option-a"

    def test_decision_strategy_extract_response_value_list(
        self,
    ) -> None:
        """Dict with list decision returns the list."""
        strategy = DecisionStrategy()
        result = strategy.extract_response_value({"decision": ["opt-a", "opt-b"]})
        assert result == ["opt-a", "opt-b"]
        assert isinstance(result, list)

    def test_decision_strategy_extract_response_value_dict_string(
        self,
    ) -> None:
        """Dict with string decision returns the string."""
        strategy = DecisionStrategy()
        result = strategy.extract_response_value({"decision": "opt-a"})
        assert result == "opt-a"
        assert isinstance(result, str)

    # -- C. ray_hitl_handler.py tests ----------------------------------

    @patch(
        "src.infrastructure.agent.hitl.ray_hitl_handler.RayHITLHandler._execute_hitl_request",
        new_callable=AsyncMock,
    )
    async def test_request_decision_passes_selection_mode(
        self,
        mock_execute: AsyncMock,
    ) -> None:
        """selection_mode kwarg appears in request_data."""
        from src.infrastructure.agent.hitl.ray_hitl_handler import (
            RayHITLHandler,
        )

        mock_execute.return_value = "decision"
        handler = RayHITLHandler(
            conversation_id="conv-10",
            tenant_id="t-1",
            project_id="p-1",
        )

        await handler.request_decision(
            question="Select frameworks",
            options=[{"id": "a", "label": "A"}],
            selection_mode="multiple",
        )

        request_data = mock_execute.call_args.args[1]
        assert request_data["selection_mode"] == "multiple"

    @patch(
        "src.infrastructure.agent.hitl.ray_hitl_handler.RayHITLHandler._execute_hitl_request",
        new_callable=AsyncMock,
    )
    async def test_request_decision_passes_max_selections(
        self,
        mock_execute: AsyncMock,
    ) -> None:
        """max_selections kwarg appears in request_data."""
        from src.infrastructure.agent.hitl.ray_hitl_handler import (
            RayHITLHandler,
        )

        mock_execute.return_value = "decision"
        handler = RayHITLHandler(
            conversation_id="conv-11",
            tenant_id="t-1",
            project_id="p-1",
        )

        await handler.request_decision(
            question="Select up to 3",
            options=[{"id": "a", "label": "A"}],
            selection_mode="multiple",
            max_selections=3,
        )

        request_data = mock_execute.call_args.args[1]
        assert request_data["max_selections"] == 3

    @patch(
        "src.infrastructure.agent.hitl.ray_hitl_handler.RayHITLHandler._execute_hitl_request",
        new_callable=AsyncMock,
    )
    async def test_request_decision_default_single_mode(
        self,
        mock_execute: AsyncMock,
    ) -> None:
        """No selection_mode kwarg defaults to 'single'."""
        from src.infrastructure.agent.hitl.ray_hitl_handler import (
            RayHITLHandler,
        )

        mock_execute.return_value = "decision"
        handler = RayHITLHandler(
            conversation_id="conv-12",
            tenant_id="t-1",
            project_id="p-1",
        )

        await handler.request_decision(
            question="Pick one",
            options=[{"id": "a", "label": "A"}],
        )

        request_data = mock_execute.call_args.args[1]
        assert request_data["selection_mode"] == "single"
        assert request_data["max_selections"] is None

    # -- D. AgentDecisionAskedEvent field tests ------------------------

    def test_decision_asked_event_has_selection_mode_field(
        self,
    ) -> None:
        """Event accepts selection_mode='multiple'."""
        event = AgentDecisionAskedEvent(
            request_id="req-100",
            question="Select items",
            decision_type="single_choice",
            options=[],
            selection_mode="multiple",
        )
        assert event.selection_mode == "multiple"

    def test_decision_asked_event_has_max_selections_field(
        self,
    ) -> None:
        """Event accepts max_selections=3."""
        event = AgentDecisionAskedEvent(
            request_id="req-101",
            question="Select items",
            decision_type="single_choice",
            options=[],
            selection_mode="multiple",
            max_selections=3,
        )
        assert event.max_selections == 3

    def test_decision_asked_event_default_selection_mode(
        self,
    ) -> None:
        """Default selection_mode is 'single', max_selections is None."""
        event = AgentDecisionAskedEvent(
            request_id="req-102",
            question="Pick one",
            decision_type="single_choice",
            options=[],
        )
        assert event.selection_mode == "single"
        assert event.max_selections is None
