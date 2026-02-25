"""Tests for RunContext plumbing through SessionProcessor.process().

Wave 6a.5: Verifies that:
1. RunContext fields are forwarded to processor internals
2. Legacy params are auto-wrapped into RunContext when run_ctx is not provided
3. run_ctx takes precedence over legacy params when both are supplied
4. SubAgentProcess creates RunContext and passes it through
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src.infrastructure.agent.processor.processor import ProcessorConfig, SessionProcessor
from src.infrastructure.agent.processor.run_context import RunContext

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def minimal_config() -> ProcessorConfig:
    """Create a minimal ProcessorConfig for testing."""
    return ProcessorConfig(
        model="test-model",
        api_key="test-key",
    )


@pytest.fixture
def mock_tools() -> list:
    """Create an empty tool list."""
    return []


@pytest.fixture
def processor(minimal_config: ProcessorConfig, mock_tools: list) -> SessionProcessor:
    """Create a SessionProcessor instance for testing."""
    return SessionProcessor(config=minimal_config, tools=mock_tools)


@pytest.fixture
def sample_messages() -> list[dict]:
    """Create sample conversation messages."""
    return [{"role": "user", "content": "Hello"}]


@pytest.fixture
def sample_langfuse_context() -> dict:
    """Create a sample langfuse_context dict."""
    return {
        "conversation_id": "conv-test-123",
        "user_id": "user-1",
        "tenant_id": "tenant-1",
        "project_id": "project-1",
    }


# ============================================================================
# RunContext dataclass tests
# ============================================================================


@pytest.mark.unit
class TestRunContextDataclass:
    """Test RunContext dataclass behavior."""

    def test_default_values(self) -> None:
        """RunContext has sensible defaults."""
        ctx = RunContext()
        assert ctx.abort_signal is None
        assert ctx.conversation_id is None
        assert ctx.trace_id is None
        assert ctx.langfuse_context is None
        assert ctx.start_time > 0

    def test_all_fields_set(self) -> None:
        """RunContext accepts all fields."""
        event = asyncio.Event()
        lf_ctx = {"conversation_id": "c1", "user_id": "u1"}
        ctx = RunContext(
            abort_signal=event,
            conversation_id="conv-1",
            trace_id="trace-1",
            langfuse_context=lf_ctx,
        )
        assert ctx.abort_signal is event
        assert ctx.conversation_id == "conv-1"
        assert ctx.trace_id == "trace-1"
        assert ctx.langfuse_context is lf_ctx

    def test_start_time_auto_set(self) -> None:
        """RunContext auto-generates start_time."""
        ctx1 = RunContext()
        ctx2 = RunContext()
        # Both should have positive timestamps, ctx2 >= ctx1
        assert ctx1.start_time > 0
        assert ctx2.start_time >= ctx1.start_time


# ============================================================================
# SessionProcessor.process() RunContext plumbing tests
# ============================================================================


@pytest.mark.unit
class TestProcessorRunContextPlumbing:
    """Test that SessionProcessor.process() correctly handles RunContext."""

    async def test_run_ctx_sets_abort_event(
        self,
        processor: SessionProcessor,
        sample_messages: list[dict],
    ) -> None:
        """When run_ctx is provided, its abort_signal is used."""
        abort = asyncio.Event()
        abort.set()  # Signal abort immediately to stop the loop
        ctx = RunContext(abort_signal=abort)

        events = []
        async for event in processor.process(
            session_id="test-session",
            messages=sample_messages,
            run_ctx=ctx,
        ):
            events.append(event)

        # Should have gotten at least a start event + abort event
        assert len(events) >= 1
        # The processor should have used our abort signal
        assert processor._abort_event is abort

    async def test_run_ctx_sets_langfuse_context(
        self,
        processor: SessionProcessor,
        sample_messages: list[dict],
        sample_langfuse_context: dict,
    ) -> None:
        """When run_ctx is provided, its langfuse_context is stored."""
        abort = asyncio.Event()
        abort.set()
        ctx = RunContext(
            abort_signal=abort,
            langfuse_context=sample_langfuse_context,
        )

        events = []
        async for event in processor.process(
            session_id="test-session",
            messages=sample_messages,
            run_ctx=ctx,
        ):
            events.append(event)

        assert processor._langfuse_context is sample_langfuse_context

    async def test_legacy_params_auto_wrapped(
        self,
        processor: SessionProcessor,
        sample_messages: list[dict],
        sample_langfuse_context: dict,
    ) -> None:
        """When run_ctx is None, legacy params are wrapped into RunContext."""
        abort = asyncio.Event()
        abort.set()

        events = []
        async for event in processor.process(
            session_id="test-session",
            messages=sample_messages,
            abort_signal=abort,
            langfuse_context=sample_langfuse_context,
        ):
            events.append(event)

        # Legacy path should still set internal state correctly
        assert processor._abort_event is abort
        assert processor._langfuse_context is sample_langfuse_context

    async def test_run_ctx_takes_precedence(
        self,
        processor: SessionProcessor,
        sample_messages: list[dict],
    ) -> None:
        """When both run_ctx and legacy params are provided, run_ctx wins."""
        legacy_abort = asyncio.Event()
        ctx_abort = asyncio.Event()
        ctx_abort.set()

        legacy_lf = {"conversation_id": "legacy-conv"}
        ctx_lf = {"conversation_id": "ctx-conv"}

        ctx = RunContext(
            abort_signal=ctx_abort,
            langfuse_context=ctx_lf,
        )

        events = []
        async for event in processor.process(
            session_id="test-session",
            messages=sample_messages,
            abort_signal=legacy_abort,
            langfuse_context=legacy_lf,
            run_ctx=ctx,
        ):
            events.append(event)

        # run_ctx should take precedence
        assert processor._abort_event is ctx_abort
        assert processor._langfuse_context is ctx_lf

    async def test_no_abort_creates_default_event(
        self,
        processor: SessionProcessor,
        sample_messages: list[dict],
    ) -> None:
        """When no abort_signal in run_ctx, a default Event is created."""
        ctx = RunContext()
        # Set the default event immediately to prevent infinite loop
        # We'll patch _check_abort_and_limits to stop after first iteration
        with patch.object(processor, "_check_abort_and_limits") as mock_check:
            # Return an abort event to stop the loop
            mock_event = MagicMock()
            mock_check.return_value = mock_event

            events = []
            async for event in processor.process(
                session_id="test-session",
                messages=sample_messages,
                run_ctx=ctx,
            ):
                events.append(event)

        # _abort_event should be a fresh asyncio.Event (not None)
        assert isinstance(processor._abort_event, asyncio.Event)
        assert not processor._abort_event.is_set()


# ============================================================================
# SubAgentProcess RunContext creation tests
# ============================================================================


@pytest.mark.unit
class TestSubAgentProcessRunContext:
    """Test that SubAgentProcess creates and passes RunContext."""

    async def test_subagent_creates_run_context(self) -> None:
        """SubAgentProcess.execute() creates RunContext with abort_signal."""
        from src.domain.model.agent.subagent import AgentModel, AgentTrigger, SubAgent
        from src.infrastructure.agent.subagent.context_bridge import SubAgentContext
        from src.infrastructure.agent.subagent.process import SubAgentProcess

        subagent = SubAgent(
            id="sa-1",
            tenant_id="tenant-1",
            name="test-subagent",
            display_name="Test SubAgent",
            system_prompt="You are a test subagent.",
            trigger=AgentTrigger(description="Test trigger", keywords=["test"]),
            model=AgentModel.INHERIT,
            max_iterations=1,
        )
        context = SubAgentContext(
            task_description="Do something",
            system_prompt="You are a test agent",
        )
        abort = asyncio.Event()

        # Use factory path
        mock_factory = MagicMock()
        mock_processor = MagicMock()

        # Make processor.process return an empty async iterator
        async def empty_process(**kwargs):
            # Verify RunContext is passed
            assert "run_ctx" in kwargs, "RunContext not passed to processor.process()"
            run_ctx = kwargs["run_ctx"]
            assert isinstance(run_ctx, RunContext)
            assert run_ctx.abort_signal is abort
            assert run_ctx.conversation_id == f"subagent-{subagent.id}"
            return
            yield  # unreachable yield makes this an async generator

        mock_processor.process = empty_process
        mock_factory.create_for_subagent.return_value = mock_processor

        process = SubAgentProcess(
            subagent=subagent,
            context=context,
            tools=[],
            base_model="test-model",
            abort_signal=abort,
            factory=mock_factory,
        )

        events = []
        async for event in process.execute():
            events.append(event)

        # Should have started and completed events
        event_types = [e.get("type", "") for e in events]
        assert "subagent_started" in event_types
        assert "subagent_completed" in event_types
