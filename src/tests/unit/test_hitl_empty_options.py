"""Tests for empty-options auto-enable allow_custom feature.

When HITL tools receive empty options ([], None, or missing), the
allow_custom flag should be automatically set to True so the user
can provide free-form input instead of being stuck with no choices.

Covers 3 backend files:
- hitl_tool_handler.py (handle_clarification_tool, handle_decision_tool)
- ray_hitl_handler.py (request_clarification, request_decision)
- hitl_strategies.py (ClarificationStrategy, DecisionStrategy)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.agent.hitl.hitl_strategies import (
    ClarificationStrategy,
    DecisionStrategy,
)

# ---------------------------------------------------------------------------
# Group 1: hitl_tool_handler empty-options tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHITLToolHandlerEmptyOptions:
    """Test hitl_tool_handler empty-options behavior.

    handle_clarification_tool and handle_decision_tool parse arguments,
    build clarification_options/decision_options lists, and auto-enable
    allow_custom when the resulting list is empty.
    """

    # -- Clarification tool ------------------------------------------------

    async def test_handle_clarification_empty_options_enables_allow_custom(
        self,
    ) -> None:
        """Empty options=[] should auto-enable allow_custom=True."""
        from src.infrastructure.agent.processor.hitl_tool_handler import (
            handle_clarification_tool,
        )

        # Arrange
        coordinator = AsyncMock()
        coordinator.prepare_request = AsyncMock(return_value="req-1")
        coordinator.wait_for_response = AsyncMock(return_value="user answer")

        tool_part = MagicMock()
        tool_part.tool_execution_id = "test-exec-id"
        arguments = {
            "question": "What do you prefer?",
            "options": [],
            "allow_custom": False,
        }

        # Act
        events = []
        async for event in handle_clarification_tool(
            coordinator=coordinator,
            call_id="call-1",
            tool_name="ask_clarification",
            arguments=arguments,
            tool_part=tool_part,
        ):
            events.append(event)

        # Assert - coordinator.prepare_request receives allow_custom=True
        prepare_call = coordinator.prepare_request.call_args
        request_data = prepare_call.args[1]
        assert request_data["allow_custom"] is True

    async def test_handle_clarification_null_options_enables_allow_custom(
        self,
    ) -> None:
        """Missing options key defaults to [] and auto-enables allow_custom."""
        from src.infrastructure.agent.processor.hitl_tool_handler import (
            handle_clarification_tool,
        )

        # Arrange
        coordinator = AsyncMock()
        coordinator.prepare_request = AsyncMock(return_value="req-2")
        coordinator.wait_for_response = AsyncMock(return_value="answer")

        tool_part = MagicMock()
        tool_part.tool_execution_id = "test-exec-id"
        arguments = {
            "question": "What next?",
            # "options" key is absent -> defaults to []
            "allow_custom": False,
        }

        # Act
        events = []
        async for event in handle_clarification_tool(
            coordinator=coordinator,
            call_id="call-2",
            tool_name="ask_clarification",
            arguments=arguments,
            tool_part=tool_part,
        ):
            events.append(event)

        # Assert
        request_data = coordinator.prepare_request.call_args.args[1]
        assert request_data["allow_custom"] is True

    async def test_handle_clarification_nonempty_options_preserves_allow_custom_false(
        self,
    ) -> None:
        """Non-empty options should preserve the original allow_custom=False."""
        from src.infrastructure.agent.processor.hitl_tool_handler import (
            handle_clarification_tool,
        )

        # Arrange
        coordinator = AsyncMock()
        coordinator.prepare_request = AsyncMock(return_value="req-3")
        coordinator.wait_for_response = AsyncMock(return_value="opt-a")

        tool_part = MagicMock()
        tool_part.tool_execution_id = "test-exec-id"
        arguments = {
            "question": "Pick one",
            "options": [
                {"id": "a", "label": "Option A"},
                {"id": "b", "label": "Option B"},
            ],
            "allow_custom": False,
        }

        # Act
        events = []
        async for event in handle_clarification_tool(
            coordinator=coordinator,
            call_id="call-3",
            tool_name="ask_clarification",
            arguments=arguments,
            tool_part=tool_part,
        ):
            events.append(event)

        # Assert
        request_data = coordinator.prepare_request.call_args.args[1]
        assert request_data["allow_custom"] is False

    # -- Decision tool -----------------------------------------------------

    async def test_handle_decision_empty_options_enables_allow_custom(
        self,
    ) -> None:
        """Empty options=[] should auto-enable allow_custom=True for decisions."""
        from src.infrastructure.agent.processor.hitl_tool_handler import (
            handle_decision_tool,
        )

        # Arrange
        coordinator = AsyncMock()
        coordinator.prepare_request = AsyncMock(return_value="req-4")
        coordinator.wait_for_response = AsyncMock(return_value="user decision")

        tool_part = MagicMock()
        tool_part.tool_execution_id = "test-exec-id"
        arguments = {
            "question": "How to proceed?",
            "options": [],
            "allow_custom": False,
        }

        # Act
        events = []
        async for event in handle_decision_tool(
            coordinator=coordinator,
            call_id="call-4",
            tool_name="request_decision",
            arguments=arguments,
            tool_part=tool_part,
        ):
            events.append(event)

        # Assert
        request_data = coordinator.prepare_request.call_args.args[1]
        assert request_data["allow_custom"] is True

    async def test_handle_decision_null_options_enables_allow_custom(
        self,
    ) -> None:
        """Missing options key defaults to [] and auto-enables allow_custom."""
        from src.infrastructure.agent.processor.hitl_tool_handler import (
            handle_decision_tool,
        )

        # Arrange
        coordinator = AsyncMock()
        coordinator.prepare_request = AsyncMock(return_value="req-5")
        coordinator.wait_for_response = AsyncMock(return_value="decision")

        tool_part = MagicMock()
        tool_part.tool_execution_id = "test-exec-id"
        arguments = {
            "question": "Next step?",
            # "options" key absent -> defaults to []
            "allow_custom": False,
        }

        # Act
        events = []
        async for event in handle_decision_tool(
            coordinator=coordinator,
            call_id="call-5",
            tool_name="request_decision",
            arguments=arguments,
            tool_part=tool_part,
        ):
            events.append(event)

        # Assert
        request_data = coordinator.prepare_request.call_args.args[1]
        assert request_data["allow_custom"] is True

    async def test_handle_decision_nonempty_options_preserves_allow_custom_false(
        self,
    ) -> None:
        """Non-empty options should preserve the original allow_custom=False."""
        from src.infrastructure.agent.processor.hitl_tool_handler import (
            handle_decision_tool,
        )

        # Arrange
        coordinator = AsyncMock()
        coordinator.prepare_request = AsyncMock(return_value="req-6")
        coordinator.wait_for_response = AsyncMock(return_value="opt-x")

        tool_part = MagicMock()
        tool_part.tool_execution_id = "test-exec-id"
        arguments = {
            "question": "Choose deployment",
            "options": [
                {"id": "x", "label": "Staging"},
                {"id": "y", "label": "Production"},
            ],
            "allow_custom": False,
        }

        # Act
        events = []
        async for event in handle_decision_tool(
            coordinator=coordinator,
            call_id="call-6",
            tool_name="request_decision",
            arguments=arguments,
            tool_part=tool_part,
        ):
            events.append(event)

        # Assert
        request_data = coordinator.prepare_request.call_args.args[1]
        assert request_data["allow_custom"] is False


# ---------------------------------------------------------------------------
# Group 2: ray_hitl_handler empty-options tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRayHITLHandlerEmptyOptions:
    """Test ray_hitl_handler empty-options behavior.

    RayHITLHandler.request_clarification and request_decision normalize
    options and compute effective_allow_custom before building request_data.
    We mock _execute_hitl_request to capture the request_data dict.
    """

    # -- Clarification -----------------------------------------------------

    @patch(
        "src.infrastructure.agent.hitl.ray_hitl_handler.RayHITLHandler._execute_hitl_request",
        new_callable=AsyncMock,
    )
    async def test_request_clarification_empty_options_auto_enables(
        self,
        mock_execute: AsyncMock,
    ) -> None:
        """Empty options=[] should set effective_allow_custom=True."""
        from src.infrastructure.agent.hitl.ray_hitl_handler import (
            RayHITLHandler,
        )

        mock_execute.return_value = "answer"
        handler = RayHITLHandler(
            conversation_id="conv-1",
            tenant_id="t-1",
            project_id="p-1",
        )

        # Act
        await handler.request_clarification(
            question="What?",
            options=[],
            allow_custom=False,
        )

        # Assert
        call_args = mock_execute.call_args
        request_data = call_args.args[1]
        assert request_data["allow_custom"] is True

    @patch(
        "src.infrastructure.agent.hitl.ray_hitl_handler.RayHITLHandler._execute_hitl_request",
        new_callable=AsyncMock,
    )
    async def test_request_clarification_none_options_auto_enables(
        self,
        mock_execute: AsyncMock,
    ) -> None:
        """options=None should normalize to [] and auto-enable allow_custom."""
        from src.infrastructure.agent.hitl.ray_hitl_handler import (
            RayHITLHandler,
        )

        mock_execute.return_value = "answer"
        handler = RayHITLHandler(
            conversation_id="conv-2",
            tenant_id="t-1",
            project_id="p-1",
        )

        # Act
        await handler.request_clarification(
            question="What?",
            options=None,
            allow_custom=False,
        )

        # Assert
        request_data = mock_execute.call_args.args[1]
        assert request_data["allow_custom"] is True

    @patch(
        "src.infrastructure.agent.hitl.ray_hitl_handler.RayHITLHandler._execute_hitl_request",
        new_callable=AsyncMock,
    )
    async def test_request_clarification_with_options_respects_param(
        self,
        mock_execute: AsyncMock,
    ) -> None:
        """Non-empty options should preserve the caller's allow_custom value."""
        from src.infrastructure.agent.hitl.ray_hitl_handler import (
            RayHITLHandler,
        )

        mock_execute.return_value = "answer"
        handler = RayHITLHandler(
            conversation_id="conv-3",
            tenant_id="t-1",
            project_id="p-1",
        )

        # Act
        await handler.request_clarification(
            question="Pick one",
            options=[{"id": "a", "label": "A"}],
            allow_custom=False,
        )

        # Assert
        request_data = mock_execute.call_args.args[1]
        assert request_data["allow_custom"] is False

    # -- Decision ----------------------------------------------------------

    @patch(
        "src.infrastructure.agent.hitl.ray_hitl_handler.RayHITLHandler._execute_hitl_request",
        new_callable=AsyncMock,
    )
    async def test_request_decision_empty_options_auto_enables(
        self,
        mock_execute: AsyncMock,
    ) -> None:
        """Empty options=[] should set effective_allow_custom=True."""
        from src.infrastructure.agent.hitl.ray_hitl_handler import (
            RayHITLHandler,
        )

        mock_execute.return_value = "decision"
        handler = RayHITLHandler(
            conversation_id="conv-4",
            tenant_id="t-1",
            project_id="p-1",
        )

        # Act
        await handler.request_decision(
            question="How?",
            options=[],
            allow_custom=False,
        )

        # Assert
        request_data = mock_execute.call_args.args[1]
        assert request_data["allow_custom"] is True

    @patch(
        "src.infrastructure.agent.hitl.ray_hitl_handler.RayHITLHandler._execute_hitl_request",
        new_callable=AsyncMock,
    )
    async def test_request_decision_none_options_auto_enables(
        self,
        mock_execute: AsyncMock,
    ) -> None:
        """options=None should normalize to [] and auto-enable allow_custom."""
        from src.infrastructure.agent.hitl.ray_hitl_handler import (
            RayHITLHandler,
        )

        mock_execute.return_value = "decision"
        handler = RayHITLHandler(
            conversation_id="conv-5",
            tenant_id="t-1",
            project_id="p-1",
        )

        # Act -- options=None triggers normalization path
        await handler.request_decision(
            question="How?",
            options=None,  # type: ignore[arg-type]
            allow_custom=False,
        )

        # Assert
        request_data = mock_execute.call_args.args[1]
        assert request_data["allow_custom"] is True

    @patch(
        "src.infrastructure.agent.hitl.ray_hitl_handler.RayHITLHandler._execute_hitl_request",
        new_callable=AsyncMock,
    )
    async def test_request_decision_with_options_respects_param(
        self,
        mock_execute: AsyncMock,
    ) -> None:
        """Non-empty options should preserve the caller's allow_custom value."""
        from src.infrastructure.agent.hitl.ray_hitl_handler import (
            RayHITLHandler,
        )

        mock_execute.return_value = "decision"
        handler = RayHITLHandler(
            conversation_id="conv-6",
            tenant_id="t-1",
            project_id="p-1",
        )

        # Act
        await handler.request_decision(
            question="Pick",
            options=[{"id": "a", "label": "A"}],
            allow_custom=False,
        )

        # Assert
        request_data = mock_execute.call_args.args[1]
        assert request_data["allow_custom"] is False


# ---------------------------------------------------------------------------
# Group 3: hitl_strategies empty-options tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHITLStrategiesEmptyOptions:
    """Test hitl_strategies empty-options behavior.

    ClarificationStrategy.create_request and DecisionStrategy.create_request
    auto-enable allow_custom when the parsed options list is empty.
    """

    # -- Clarification Strategy --------------------------------------------

    def test_clarification_strategy_empty_options_enables_allow_custom(
        self,
    ) -> None:
        """options=[] in request_data should set allow_custom=True."""
        # Arrange
        strategy = ClarificationStrategy()
        request_data = {
            "question": "What do you need?",
            "options": [],
            "allow_custom": False,
        }

        # Act
        request = strategy.create_request(
            conversation_id="conv-1",
            request_data=request_data,
            timeout_seconds=60.0,
            tenant_id="t-1",
            project_id="p-1",
        )

        # Assert
        assert request.clarification_data is not None
        assert request.clarification_data.allow_custom is True

    def test_clarification_strategy_none_options_enables_allow_custom(
        self,
    ) -> None:
        """options=None in request_data should be treated as empty."""
        # Arrange
        strategy = ClarificationStrategy()
        request_data = {
            "question": "What do you need?",
            "options": None,
            "allow_custom": False,
        }

        # Act
        request = strategy.create_request(
            conversation_id="conv-2",
            request_data=request_data,
            timeout_seconds=60.0,
            tenant_id="t-1",
            project_id="p-1",
        )

        # Assert
        assert request.clarification_data is not None
        assert request.clarification_data.allow_custom is True

    def test_clarification_strategy_missing_options_enables_allow_custom(
        self,
    ) -> None:
        """Missing options key should default to [] and enable allow_custom."""
        # Arrange
        strategy = ClarificationStrategy()
        request_data = {
            "question": "What do you need?",
            # "options" key is absent
            "allow_custom": False,
        }

        # Act
        request = strategy.create_request(
            conversation_id="conv-3",
            request_data=request_data,
            timeout_seconds=60.0,
            tenant_id="t-1",
            project_id="p-1",
        )

        # Assert
        assert request.clarification_data is not None
        assert request.clarification_data.allow_custom is True

    def test_clarification_strategy_with_options_preserves_original(
        self,
    ) -> None:
        """Non-empty options should preserve allow_custom=False."""
        # Arrange
        strategy = ClarificationStrategy()
        request_data = {
            "question": "Pick one",
            "options": [
                {"id": "a", "label": "Option A"},
                {"id": "b", "label": "Option B"},
            ],
            "allow_custom": False,
        }

        # Act
        request = strategy.create_request(
            conversation_id="conv-4",
            request_data=request_data,
            timeout_seconds=60.0,
            tenant_id="t-1",
            project_id="p-1",
        )

        # Assert
        assert request.clarification_data is not None
        assert request.clarification_data.allow_custom is False

    # -- Decision Strategy -------------------------------------------------

    def test_decision_strategy_empty_options_enables_allow_custom(
        self,
    ) -> None:
        """options=[] in request_data should set allow_custom=True."""
        # Arrange
        strategy = DecisionStrategy()
        request_data = {
            "question": "How to proceed?",
            "options": [],
            "allow_custom": False,
        }

        # Act
        request = strategy.create_request(
            conversation_id="conv-5",
            request_data=request_data,
            timeout_seconds=60.0,
            tenant_id="t-1",
            project_id="p-1",
        )

        # Assert
        assert request.decision_data is not None
        assert request.decision_data.allow_custom is True

    def test_decision_strategy_none_options_enables_allow_custom(
        self,
    ) -> None:
        """options=None in request_data should be treated as empty."""
        # Arrange
        strategy = DecisionStrategy()
        request_data = {
            "question": "How to proceed?",
            "options": None,
            "allow_custom": False,
        }

        # Act
        request = strategy.create_request(
            conversation_id="conv-6",
            request_data=request_data,
            timeout_seconds=60.0,
            tenant_id="t-1",
            project_id="p-1",
        )

        # Assert
        assert request.decision_data is not None
        assert request.decision_data.allow_custom is True

    def test_decision_strategy_missing_options_enables_allow_custom(
        self,
    ) -> None:
        """Missing options key should default to [] and enable allow_custom."""
        # Arrange
        strategy = DecisionStrategy()
        request_data = {
            "question": "How to proceed?",
            # "options" key absent
            "allow_custom": False,
        }

        # Act
        request = strategy.create_request(
            conversation_id="conv-7",
            request_data=request_data,
            timeout_seconds=60.0,
            tenant_id="t-1",
            project_id="p-1",
        )

        # Assert
        assert request.decision_data is not None
        assert request.decision_data.allow_custom is True

    def test_decision_strategy_with_options_preserves_original(
        self,
    ) -> None:
        """Non-empty options should preserve allow_custom=False."""
        # Arrange
        strategy = DecisionStrategy()
        request_data = {
            "question": "Choose deployment",
            "options": [
                {"id": "staging", "label": "Staging"},
                {"id": "prod", "label": "Production"},
            ],
            "allow_custom": False,
        }

        # Act
        request = strategy.create_request(
            conversation_id="conv-8",
            request_data=request_data,
            timeout_seconds=60.0,
            tenant_id="t-1",
            project_id="p-1",
        )

        # Assert
        assert request.decision_data is not None
        assert request.decision_data.allow_custom is False
