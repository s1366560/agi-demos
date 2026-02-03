"""
Unit tests for HITLHandler.

Tests the Human-in-the-Loop tool handling logic extracted from SessionProcessor.
"""

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.agent.hitl.handler import (
    HITLContext,
    HITLHandler,
    HITLToolType,
    get_hitl_handler,
    set_hitl_handler,
)


# ============================================================
# Test Fixtures
# ============================================================


@pytest.fixture
def handler():
    """Create a fresh HITLHandler instance."""
    return HITLHandler(debug_logging=False)


@pytest.fixture
def context():
    """Create a valid HITL context."""
    return HITLContext(
        tenant_id="tenant-123",
        project_id="proj-456",
        conversation_id="conv-789",
        message_id="msg-001",
    )


@dataclass
class MockToolPart:
    """Mock tool part for testing."""

    tool_execution_id: Optional[str] = "exec-001"
    status: Any = None
    output: Any = None
    error: Optional[str] = None
    end_time: Optional[float] = None


@pytest.fixture
def tool_part():
    """Create a mock tool part."""
    return MockToolPart()


@pytest.fixture
def mock_clarification_manager():
    """Create a mock clarification manager."""
    manager = AsyncMock()
    manager.wait_for_response = AsyncMock(return_value="User selected option A")
    return manager


@pytest.fixture
def mock_decision_manager():
    """Create a mock decision manager."""
    manager = AsyncMock()
    manager.wait_for_response = AsyncMock(return_value="proceed")
    return manager


@pytest.fixture
def mock_env_var_manager():
    """Create a mock env var manager."""
    manager = AsyncMock()
    manager.wait_for_response = AsyncMock(return_value={"API_KEY": "test-key-123"})
    return manager


# ============================================================
# Test HITLContext
# ============================================================


@pytest.mark.unit
class TestHITLContext:
    """Test HITLContext dataclass."""

    def test_to_dict(self, context):
        """Test converting context to dictionary."""
        result = context.to_dict()

        assert result["tenant_id"] == "tenant-123"
        assert result["project_id"] == "proj-456"
        assert result["conversation_id"] == "conv-789"
        assert result["message_id"] == "msg-001"

    def test_empty_context(self):
        """Test empty context."""
        ctx = HITLContext()
        result = ctx.to_dict()

        assert result["tenant_id"] is None
        assert result["project_id"] is None


# ============================================================
# Test HITLToolType
# ============================================================


@pytest.mark.unit
class TestHITLToolType:
    """Test HITLToolType enum."""

    def test_clarification_value(self):
        """Test clarification tool value."""
        assert HITLToolType.CLARIFICATION.value == "ask_clarification"

    def test_decision_value(self):
        """Test decision tool value."""
        assert HITLToolType.DECISION.value == "request_decision"

    def test_env_var_value(self):
        """Test env var tool value."""
        assert HITLToolType.ENV_VAR.value == "request_env_var"


# ============================================================
# Test is_hitl_tool
# ============================================================


@pytest.mark.unit
class TestIsHITLTool:
    """Test is_hitl_tool method."""

    def test_clarification_is_hitl(self, handler):
        """Test that clarification tool is recognized."""
        assert handler.is_hitl_tool("ask_clarification") is True

    def test_decision_is_hitl(self, handler):
        """Test that decision tool is recognized."""
        assert handler.is_hitl_tool("request_decision") is True

    def test_env_var_is_hitl(self, handler):
        """Test that env var tool is recognized."""
        assert handler.is_hitl_tool("request_env_var") is True

    def test_other_tool_not_hitl(self, handler):
        """Test that other tools are not recognized as HITL."""
        assert handler.is_hitl_tool("web_search") is False
        assert handler.is_hitl_tool("memory_search") is False

    def test_get_hitl_tool_type(self, handler):
        """Test getting HITL tool type."""
        assert handler.get_hitl_tool_type("ask_clarification") == HITLToolType.CLARIFICATION
        assert handler.get_hitl_tool_type("request_decision") == HITLToolType.DECISION
        assert handler.get_hitl_tool_type("request_env_var") == HITLToolType.ENV_VAR
        assert handler.get_hitl_tool_type("unknown") is None


# ============================================================
# Test Context Normalization
# ============================================================


@pytest.mark.unit
class TestContextNormalization:
    """Test context normalization helpers."""

    def test_normalize_string_context(self, handler, context):
        """Test normalizing string context."""
        result = handler._normalize_context("Some description", context)

        assert result["description"] == "Some description"
        assert result["conversation_id"] == "conv-789"

    def test_normalize_dict_context(self, handler, context):
        """Test normalizing dict context."""
        raw = {"key": "value", "other": "data"}
        result = handler._normalize_context(raw, context)

        assert result["key"] == "value"
        assert result["other"] == "data"
        assert result["conversation_id"] == "conv-789"

    def test_normalize_empty_context(self, handler, context):
        """Test normalizing empty context."""
        result = handler._normalize_context(None, context)

        assert result["conversation_id"] == "conv-789"

    def test_normalize_without_conversation_id(self, handler):
        """Test normalizing without conversation_id."""
        ctx = HITLContext(tenant_id="t1", project_id="p1")
        result = handler._normalize_context({}, ctx)

        assert "conversation_id" not in result


# ============================================================
# Test Option Conversion
# ============================================================


@pytest.mark.unit
class TestOptionConversion:
    """Test option conversion helpers."""

    def test_convert_clarification_options(self, handler):
        """Test converting clarification options."""
        raw = [
            {"id": "opt1", "label": "Option 1", "description": "Desc 1", "recommended": True},
            {"id": "opt2", "label": "Option 2"},
        ]

        result = handler._convert_clarification_options(raw)

        assert len(result) == 2
        assert result[0]["id"] == "opt1"
        assert result[0]["recommended"] is True
        assert result[1]["recommended"] is False

    def test_convert_decision_options(self, handler):
        """Test converting decision options."""
        raw = [
            {
                "id": "opt1",
                "label": "Option 1",
                "estimated_time": "5 min",
                "estimated_cost": "$10",
                "risks": ["Risk 1"],
            },
        ]

        result = handler._convert_decision_options(raw)

        assert len(result) == 1
        assert result[0]["estimated_time"] == "5 min"
        assert result[0]["estimated_cost"] == "$10"
        assert result[0]["risks"] == ["Risk 1"]

    def test_convert_decision_options_defaults(self, handler):
        """Test decision option defaults."""
        raw = [{"id": "opt1", "label": "Option 1"}]

        result = handler._convert_decision_options(raw)

        assert result[0]["risks"] == []
        assert result[0]["estimated_time"] is None


# ============================================================
# Test Env Var Field Conversion
# ============================================================


@pytest.mark.unit
class TestEnvVarFieldConversion:
    """Test env var field conversion."""

    def test_convert_env_var_fields(self, handler):
        """Test converting env var fields."""
        raw = [
            {
                "variable_name": "API_KEY",
                "display_name": "API Key",
                "description": "Your API key",
                "input_type": "password",
                "is_required": True,
            },
            {
                "name": "DEBUG",  # Alternative field name
                "label": "Debug Mode",  # Alternative field name
                "input_type": "text",
                "required": False,  # Alternative field name
            },
        ]

        fields_for_sse, env_var_fields = handler._convert_env_var_fields(raw)

        # Check SSE format
        assert len(fields_for_sse) == 2
        assert fields_for_sse[0]["name"] == "API_KEY"
        assert fields_for_sse[0]["label"] == "API Key"
        assert fields_for_sse[0]["input_type"] == "password"

        # Check second field using alternative names
        assert fields_for_sse[1]["name"] == "DEBUG"
        assert fields_for_sse[1]["label"] == "Debug Mode"
        assert fields_for_sse[1]["required"] is False


# ============================================================
# Test Tool Part Helpers
# ============================================================


@pytest.mark.unit
class TestToolPartHelpers:
    """Test tool part helper methods."""

    def test_complete_tool_part(self, handler, tool_part):
        """Test completing tool part."""
        handler._complete_tool_part(tool_part, "result data", 123.456)

        assert tool_part.output == "result data"
        assert tool_part.end_time == 123.456

    def test_error_tool_part(self, handler, tool_part):
        """Test error on tool part."""
        handler._error_tool_part(tool_part, "Something went wrong")

        assert tool_part.error == "Something went wrong"
        assert tool_part.end_time is not None


# ============================================================
# Test Clarification Handler
# ============================================================


@pytest.mark.unit
class TestClarificationHandler:
    """Test clarification tool handling."""

    async def test_handle_clarification_success(
        self, handler, context, tool_part, mock_clarification_manager
    ):
        """Test successful clarification handling."""
        arguments = {
            "question": "Which option do you prefer?",
            "clarification_type": "custom",
            "options": [
                {"id": "a", "label": "Option A"},
                {"id": "b", "label": "Option B"},
            ],
            "allow_custom": True,
            "timeout": 60.0,
        }

        with patch(
            "src.infrastructure.agent.tools.clarification.get_clarification_manager",
            return_value=mock_clarification_manager,
        ):
            events = []
            async for event in handler.handle_clarification(
                session_id="sess-001",
                call_id="call-001",
                arguments=arguments,
                tool_part=tool_part,
                context=context,
            ):
                events.append(event)

        # Should emit: asked, answered, observe
        assert len(events) >= 2
        # First event is asked
        assert hasattr(events[0], "question")
        assert events[0].question == "Which option do you prefer?"

    async def test_handle_clarification_timeout(
        self, handler, context, tool_part, mock_clarification_manager
    ):
        """Test clarification timeout handling."""
        mock_clarification_manager.wait_for_response = AsyncMock(
            side_effect=asyncio.TimeoutError()
        )
        arguments = {
            "question": "Test question?",
            "options": [],
            "timeout": 1.0,
        }

        with patch(
            "src.infrastructure.agent.tools.clarification.get_clarification_manager",
            return_value=mock_clarification_manager,
        ):
            events = []
            async for event in handler.handle_clarification(
                session_id="sess-001",
                call_id="call-001",
                arguments=arguments,
                tool_part=tool_part,
                context=context,
            ):
                events.append(event)

        # Should have error in observe event
        assert any(
            hasattr(e, "error") and e.error and "timed out" in e.error for e in events
        )


# ============================================================
# Test Decision Handler
# ============================================================


@pytest.mark.unit
class TestDecisionHandler:
    """Test decision tool handling."""

    async def test_handle_decision_success(
        self, handler, context, tool_part, mock_decision_manager
    ):
        """Test successful decision handling."""
        arguments = {
            "question": "Do you want to proceed?",
            "decision_type": "confirmation",
            "options": [
                {"id": "yes", "label": "Yes, proceed"},
                {"id": "no", "label": "No, cancel"},
            ],
            "default_option": "yes",
            "timeout": 60.0,
        }

        with patch(
            "src.infrastructure.agent.tools.decision.get_decision_manager",
            return_value=mock_decision_manager,
        ):
            events = []
            async for event in handler.handle_decision(
                session_id="sess-001",
                call_id="call-001",
                arguments=arguments,
                tool_part=tool_part,
                context=context,
            ):
                events.append(event)

        assert len(events) >= 2
        # First event is asked
        assert hasattr(events[0], "question")

    async def test_handle_decision_timeout(
        self, handler, context, tool_part, mock_decision_manager
    ):
        """Test decision timeout handling."""
        mock_decision_manager.wait_for_response = AsyncMock(
            side_effect=asyncio.TimeoutError()
        )
        arguments = {
            "question": "Test?",
            "options": [],
            "timeout": 1.0,
        }

        with patch(
            "src.infrastructure.agent.tools.decision.get_decision_manager",
            return_value=mock_decision_manager,
        ):
            events = []
            async for event in handler.handle_decision(
                session_id="sess-001",
                call_id="call-001",
                arguments=arguments,
                tool_part=tool_part,
                context=context,
            ):
                events.append(event)

        assert any(
            hasattr(e, "error") and e.error and "timed out" in e.error for e in events
        )


# ============================================================
# Test Env Var Handler
# ============================================================


@pytest.mark.unit
class TestEnvVarHandler:
    """Test env var tool handling."""

    async def test_handle_env_var_success(
        self, handler, context, tool_part, mock_env_var_manager
    ):
        """Test successful env var handling."""
        arguments = {
            "tool_name": "openai_chat",
            "fields": [
                {
                    "variable_name": "OPENAI_API_KEY",
                    "display_name": "OpenAI API Key",
                    "input_type": "password",
                    "is_required": True,
                }
            ],
            "timeout": 60.0,
        }

        with patch(
            "src.infrastructure.agent.tools.env_var_tools.get_env_var_manager",
            return_value=mock_env_var_manager,
        ):
            events = []
            async for event in handler.handle_env_var(
                session_id="sess-001",
                call_id="call-001",
                arguments=arguments,
                tool_part=tool_part,
                context=context,
            ):
                events.append(event)

        assert len(events) >= 2
        # First event is requested
        assert hasattr(events[0], "tool_name")

    async def test_handle_env_var_with_save_callback(
        self, handler, context, tool_part, mock_env_var_manager
    ):
        """Test env var handling with save callback."""
        arguments = {
            "tool_name": "test_tool",
            "fields": [{"variable_name": "TEST_VAR"}],
            "save_to_project": True,
        }

        save_callback = AsyncMock(return_value=["TEST_VAR"])

        with patch(
            "src.infrastructure.agent.tools.env_var_tools.get_env_var_manager",
            return_value=mock_env_var_manager,
        ):
            events = []
            async for event in handler.handle_env_var(
                session_id="sess-001",
                call_id="call-001",
                arguments=arguments,
                tool_part=tool_part,
                context=context,
                save_callback=save_callback,
            ):
                events.append(event)

        # Callback should have been called
        save_callback.assert_called_once()

    async def test_handle_env_var_timeout(
        self, handler, context, tool_part, mock_env_var_manager
    ):
        """Test env var timeout handling."""
        mock_env_var_manager.wait_for_response = AsyncMock(
            side_effect=asyncio.TimeoutError()
        )
        arguments = {
            "tool_name": "test_tool",
            "fields": [],
            "timeout": 1.0,
        }

        with patch(
            "src.infrastructure.agent.tools.env_var_tools.get_env_var_manager",
            return_value=mock_env_var_manager,
        ):
            events = []
            async for event in handler.handle_env_var(
                session_id="sess-001",
                call_id="call-001",
                arguments=arguments,
                tool_part=tool_part,
                context=context,
            ):
                events.append(event)

        assert any(
            hasattr(e, "error") and e.error and "timed out" in e.error for e in events
        )


# ============================================================
# Test Singleton Functions
# ============================================================


@pytest.mark.unit
class TestSingletonFunctions:
    """Test singleton getter/setter functions."""

    def test_get_hitl_handler(self):
        """Test getting default handler."""
        handler = get_hitl_handler()
        assert isinstance(handler, HITLHandler)

    def test_get_returns_same_instance(self):
        """Test that getter returns same instance."""
        h1 = get_hitl_handler()
        h2 = get_hitl_handler()
        assert h1 is h2

    def test_set_hitl_handler(self):
        """Test setting custom handler."""
        custom = HITLHandler(debug_logging=True)
        set_hitl_handler(custom)

        result = get_hitl_handler()
        assert result is custom

        # Cleanup
        set_hitl_handler(HITLHandler())


# ============================================================
# Test Error Handling
# ============================================================


@pytest.mark.unit
class TestErrorHandling:
    """Test error handling in HITL handlers."""

    async def test_clarification_exception_handling(
        self, handler, context, tool_part, mock_clarification_manager
    ):
        """Test exception handling in clarification."""
        mock_clarification_manager.register_request = AsyncMock(
            side_effect=Exception("Registration failed")
        )
        arguments = {"question": "Test?", "options": []}

        with patch(
            "src.infrastructure.agent.tools.clarification.get_clarification_manager",
            return_value=mock_clarification_manager,
        ):
            events = []
            async for event in handler.handle_clarification(
                session_id="sess-001",
                call_id="call-001",
                arguments=arguments,
                tool_part=tool_part,
                context=context,
            ):
                events.append(event)

        # Should emit error observe event
        assert any(
            hasattr(e, "error") and e.error and "Registration failed" in e.error
            for e in events
        )

    async def test_decision_exception_handling(
        self, handler, context, tool_part, mock_decision_manager
    ):
        """Test exception handling in decision."""
        mock_decision_manager.register_request = AsyncMock(
            side_effect=Exception("Decision error")
        )
        arguments = {"question": "Test?", "options": []}

        with patch(
            "src.infrastructure.agent.tools.decision.get_decision_manager",
            return_value=mock_decision_manager,
        ):
            events = []
            async for event in handler.handle_decision(
                session_id="sess-001",
                call_id="call-001",
                arguments=arguments,
                tool_part=tool_part,
                context=context,
            ):
                events.append(event)

        assert any(
            hasattr(e, "error") and e.error and "Decision error" in e.error
            for e in events
        )
