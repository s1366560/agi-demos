"""Unit tests for SubAgent independent execution engine.

Tests for:
- SubAgentResult (domain model)
- ContextBridge (context transfer)
- SubAgentProcess (independent ReAct loop)
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.model.agent.subagent import AgentModel, AgentTrigger, SubAgent
from src.domain.model.agent.subagent_result import SubAgentResult
from src.infrastructure.agent.subagent.context_bridge import (
    ContextBridge,
    SubAgentContext,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_subagent() -> SubAgent:
    """Create a sample SubAgent for testing."""
    return SubAgent.create(
        tenant_id="tenant-1",
        name="test-coder",
        display_name="Test Coder",
        system_prompt="You are a coding assistant.",
        trigger_description="Coding tasks",
        trigger_keywords=["code", "implement", "fix"],
        trigger_examples=["Write a function", "Fix the bug"],
        model=AgentModel.INHERIT,
        color="green",
        allowed_tools=["*"],
        max_tokens=4096,
        temperature=0.7,
        max_iterations=10,
    )


@pytest.fixture
def sample_conversation_context() -> list:
    """Create sample conversation context."""
    return [
        {"role": "user", "content": "Hello, I need help with my project."},
        {"role": "assistant", "content": "Sure, what do you need help with?"},
        {"role": "user", "content": "I have a bug in my authentication code."},
        {"role": "assistant", "content": "Let me take a look at the auth module."},
        {"role": "user", "content": "The login function is not validating tokens properly."},
        {"role": "assistant", "content": "I see the issue in the token validation logic."},
        {"role": "user", "content": "Can you fix it?"},
    ]


# ============================================================================
# SubAgentResult Tests
# ============================================================================


@pytest.mark.unit
class TestSubAgentResult:
    """Tests for SubAgentResult domain model."""

    def test_create_successful_result(self):
        result = SubAgentResult(
            subagent_id="sa-1",
            subagent_name="Test Agent",
            summary="Task completed successfully.",
            success=True,
            tool_calls_count=3,
            tokens_used=1500,
            execution_time_ms=2000,
            final_content="Full output content here.",
        )
        assert result.success is True
        assert result.tool_calls_count == 3
        assert result.tokens_used == 1500
        assert result.error is None

    def test_create_failed_result(self):
        result = SubAgentResult(
            subagent_id="sa-1",
            subagent_name="Test Agent",
            summary="Failed due to timeout.",
            success=False,
            error="Execution timed out after 30s",
        )
        assert result.success is False
        assert result.error == "Execution timed out after 30s"

    def test_to_context_message_success(self):
        result = SubAgentResult(
            subagent_id="sa-1",
            subagent_name="Coder",
            summary="Fixed the authentication bug.",
            success=True,
            tool_calls_count=5,
            tokens_used=2000,
        )
        msg = result.to_context_message()
        assert "[SubAgent 'Coder' completed successfully]" in msg
        assert "Fixed the authentication bug." in msg
        assert "5 tool calls" in msg

    def test_to_context_message_failure(self):
        result = SubAgentResult(
            subagent_id="sa-1",
            subagent_name="Coder",
            summary="",
            success=False,
            error="Rate limit exceeded",
        )
        msg = result.to_context_message()
        assert "failed" in msg
        assert "Rate limit exceeded" in msg

    def test_to_event_data(self):
        result = SubAgentResult(
            subagent_id="sa-1",
            subagent_name="Coder",
            summary="Done.",
            success=True,
            tool_calls_count=2,
            tokens_used=800,
            execution_time_ms=1500,
        )
        data = result.to_event_data()
        assert data["subagent_id"] == "sa-1"
        assert data["subagent_name"] == "Coder"
        assert data["success"] is True
        assert data["tool_calls_count"] == 2
        assert data["tokens_used"] == 800
        assert data["execution_time_ms"] == 1500

    def test_frozen_immutability(self):
        result = SubAgentResult(
            subagent_id="sa-1",
            subagent_name="Test",
            summary="Done.",
            success=True,
        )
        with pytest.raises(AttributeError):
            result.success = False

    def test_completed_at_auto_generated(self):
        result = SubAgentResult(
            subagent_id="sa-1",
            subagent_name="Test",
            summary="Done.",
            success=True,
        )
        assert isinstance(result.completed_at, datetime)


# ============================================================================
# ContextBridge Tests
# ============================================================================


@pytest.mark.unit
class TestContextBridge:
    """Tests for ContextBridge context transfer."""

    def test_build_subagent_context_basic(self):
        bridge = ContextBridge()
        ctx = bridge.build_subagent_context(
            user_message="Fix the bug in auth.py",
            subagent_system_prompt="You are a coder.",
            project_id="proj-1",
            tenant_id="tenant-1",
        )
        assert ctx.task_description == "Fix the bug in auth.py"
        assert ctx.system_prompt == "You are a coder."
        assert ctx.metadata["project_id"] == "proj-1"
        assert ctx.metadata["tenant_id"] == "tenant-1"

    def test_build_subagent_context_with_history(self, sample_conversation_context):
        bridge = ContextBridge(max_context_messages=3)
        ctx = bridge.build_subagent_context(
            user_message="Fix the bug",
            subagent_system_prompt="You are a coder.",
            conversation_context=sample_conversation_context,
        )
        # Should take only last 3 messages
        assert len(ctx.context_messages) <= 3

    def test_token_budget_ratio(self):
        bridge = ContextBridge(budget_ratio=0.3)
        ctx = bridge.build_subagent_context(
            user_message="Task",
            subagent_system_prompt="Prompt",
            main_token_budget=200000,
        )
        assert ctx.token_budget == 60000

    def test_token_budget_custom_ratio(self):
        bridge = ContextBridge(budget_ratio=0.5)
        ctx = bridge.build_subagent_context(
            user_message="Task",
            subagent_system_prompt="Prompt",
            main_token_budget=100000,
        )
        assert ctx.token_budget == 50000

    def test_build_messages_structure(self):
        bridge = ContextBridge()
        ctx = SubAgentContext(
            task_description="Fix the login bug",
            system_prompt="You are a coding expert.",
            context_messages=[
                {"role": "user", "content": "Previous context"},
            ],
            token_budget=60000,
        )
        messages = bridge.build_messages(ctx)
        assert len(messages) == 3
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are a coding expert."
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "Previous context"
        assert messages[2]["role"] == "user"
        assert messages[2]["content"] == "Fix the login bug"

    def test_build_messages_no_context(self):
        bridge = ContextBridge()
        ctx = SubAgentContext(
            task_description="Do something",
            system_prompt="System prompt",
        )
        messages = bridge.build_messages(ctx)
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_condense_context_truncation(self):
        bridge = ContextBridge(max_context_chars=50)
        context = [
            {"role": "user", "content": "A" * 100},
            {"role": "assistant", "content": "B" * 100},
        ]
        condensed = bridge._condense_context(context)
        total_len = sum(len(m["content"]) for m in condensed)
        # Should respect the char limit (roughly)
        assert total_len <= 70  # 50 + truncation marker

    def test_condense_context_empty(self):
        bridge = ContextBridge()
        assert bridge._condense_context(None) == []
        assert bridge._condense_context([]) == []

    def test_condense_context_respects_max_messages(self):
        bridge = ContextBridge(max_context_messages=2, max_context_chars=10000)
        context = [
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "msg2"},
            {"role": "user", "content": "msg3"},
            {"role": "assistant", "content": "msg4"},
            {"role": "user", "content": "msg5"},
        ]
        condensed = bridge._condense_context(context)
        assert len(condensed) == 2
        # Should be the last 2 messages
        assert condensed[0]["content"] == "msg4"
        assert condensed[1]["content"] == "msg5"

    def test_subagent_context_frozen(self):
        ctx = SubAgentContext(
            task_description="Task",
            system_prompt="Prompt",
        )
        with pytest.raises(AttributeError):
            ctx.task_description = "Changed"


# ============================================================================
# SubAgentProcess Tests
# ============================================================================


@pytest.mark.unit
class TestSubAgentProcess:
    """Tests for SubAgentProcess independent execution."""

    async def test_process_creation(self, sample_subagent):
        from src.infrastructure.agent.subagent.process import SubAgentProcess

        ctx = SubAgentContext(
            task_description="Fix the bug",
            system_prompt="You are a coder.",
            token_budget=60000,
        )
        process = SubAgentProcess(
            subagent=sample_subagent,
            context=ctx,
            tools=[],
            base_model="qwen-max",
        )
        assert process.result is None

    async def test_process_inherits_model(self, sample_subagent):
        from src.infrastructure.agent.subagent.process import SubAgentProcess

        ctx = SubAgentContext(
            task_description="Task",
            system_prompt="Prompt",
        )
        process = SubAgentProcess(
            subagent=sample_subagent,
            context=ctx,
            tools=[],
            base_model="qwen-max",
        )
        assert process._model == "qwen-max"

    async def test_process_overrides_model(self):
        from src.infrastructure.agent.subagent.process import SubAgentProcess

        subagent = SubAgent.create(
            tenant_id="t1",
            name="test",
            display_name="Test",
            system_prompt="Prompt",
            trigger_description="Test",
            model=AgentModel.GPT4O,
        )
        ctx = SubAgentContext(
            task_description="Task",
            system_prompt="Prompt",
        )
        process = SubAgentProcess(
            subagent=subagent,
            context=ctx,
            tools=[],
            base_model="qwen-max",
        )
        assert process._model == "gpt-4o"

    async def test_process_extract_summary_short(self, sample_subagent):
        from src.infrastructure.agent.subagent.process import SubAgentProcess

        ctx = SubAgentContext(
            task_description="Task",
            system_prompt="Prompt",
        )
        process = SubAgentProcess(
            subagent=sample_subagent,
            context=ctx,
            tools=[],
            base_model="qwen-max",
        )
        summary = process._extract_summary("Short content.")
        assert summary == "Short content."

    async def test_process_extract_summary_long(self, sample_subagent):
        from src.infrastructure.agent.subagent.process import SubAgentProcess

        ctx = SubAgentContext(
            task_description="Task",
            system_prompt="Prompt",
        )
        process = SubAgentProcess(
            subagent=sample_subagent,
            context=ctx,
            tools=[],
            base_model="qwen-max",
        )
        long_content = "This is a sentence. " * 50  # ~1000 chars
        summary = process._extract_summary(long_content, max_length=100)
        assert len(summary) <= 105  # 100 + small margin for "..."

    async def test_process_extract_summary_empty(self, sample_subagent):
        from src.infrastructure.agent.subagent.process import SubAgentProcess

        ctx = SubAgentContext(
            task_description="Task",
            system_prompt="Prompt",
        )
        process = SubAgentProcess(
            subagent=sample_subagent,
            context=ctx,
            tools=[],
            base_model="qwen-max",
        )
        assert process._extract_summary("") == "No output produced."

    async def test_process_execute_yields_lifecycle_events(self, sample_subagent):
        """Test that execute yields subagent_started and subagent_completed events."""
        from src.infrastructure.agent.subagent.process import SubAgentProcess

        ctx = SubAgentContext(
            task_description="Test task",
            system_prompt="You are a test agent.",
        )
        process = SubAgentProcess(
            subagent=sample_subagent,
            context=ctx,
            tools=[],
            base_model="qwen-max",
        )

        # Mock the SessionProcessor to avoid actual LLM calls
        mock_processor_cls = MagicMock()

        async def mock_process(*args, **kwargs):
            return
            yield  # make it an async generator

        mock_processor_instance = MagicMock()
        mock_processor_instance.process = mock_process
        mock_processor_cls.return_value = mock_processor_instance

        events = []
        with patch(
            "src.infrastructure.agent.core.processor.SessionProcessor",
            mock_processor_cls,
        ):
            async for event in process.execute():
                events.append(event)

        # Should have at least started + completed events
        event_types = [e["type"] for e in events]
        assert "subagent_started" in event_types
        assert "subagent_completed" in event_types

        # Verify started event data
        started = next(e for e in events if e["type"] == "subagent_started")
        assert started["data"]["subagent_id"] == sample_subagent.id
        assert started["data"]["subagent_name"] == "Test Coder"

        # Verify result is set
        assert process.result is not None
        assert process.result.success is True

    async def test_process_execute_handles_error(self, sample_subagent):
        """Test that execution errors yield subagent_failed event."""
        from src.infrastructure.agent.subagent.process import SubAgentProcess

        ctx = SubAgentContext(
            task_description="Task",
            system_prompt="Prompt",
        )
        process = SubAgentProcess(
            subagent=sample_subagent,
            context=ctx,
            tools=[],
            base_model="qwen-max",
        )

        mock_processor_cls = MagicMock()

        async def mock_process_error(*args, **kwargs):
            raise RuntimeError("LLM connection failed")
            yield  # noqa: unreachable

        mock_processor_instance = MagicMock()
        mock_processor_instance.process = mock_process_error
        mock_processor_cls.return_value = mock_processor_instance

        events = []
        with patch(
            "src.infrastructure.agent.core.processor.SessionProcessor",
            mock_processor_cls,
        ):
            async for event in process.execute():
                events.append(event)

        event_types = [e["type"] for e in events]
        assert "subagent_started" in event_types
        assert "subagent_failed" in event_types
        assert "subagent_completed" in event_types

        assert process.result is not None
        assert process.result.success is False
        assert "LLM connection failed" in process.result.error


# ============================================================================
# AgentEventType Tests
# ============================================================================


@pytest.mark.unit
class TestSubAgentEventTypes:
    """Tests for SubAgent event type definitions."""

    def test_subagent_event_types_exist(self):
        from src.domain.events.types import AgentEventType

        assert AgentEventType.SUBAGENT_ROUTED.value == "subagent_routed"
        assert AgentEventType.SUBAGENT_STARTED.value == "subagent_started"
        assert AgentEventType.SUBAGENT_COMPLETED.value == "subagent_completed"
        assert AgentEventType.SUBAGENT_FAILED.value == "subagent_failed"
