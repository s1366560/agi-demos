"""Tests for DefaultContextEngine -- Phase 3 Wave 4.

Verifies that DefaultContextEngine correctly implements ContextEnginePort
by wrapping ContextFacade, compaction, and ContextBridge.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.model.agent.assembled_context import AssembledContext
from src.domain.model.agent.context_segment import ContextSegment
from src.domain.model.agent.conversation.conversation import Conversation
from src.domain.model.agent.conversation.message import Message, MessageRole, MessageType
from src.domain.model.agent.subagent_result import SubAgentResult
from src.domain.ports.agent.context_engine_port import ContextEnginePort
from src.infrastructure.agent.context.default_context_engine import DefaultContextEngine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_context_facade() -> MagicMock:
    facade = MagicMock()
    facade.build_context = AsyncMock()
    facade.estimate_tokens = MagicMock(return_value=100)
    facade.estimate_messages_tokens = MagicMock(return_value=500)
    return facade


@pytest.fixture()
def mock_context_bridge() -> MagicMock:
    bridge = MagicMock()
    return bridge


@pytest.fixture()
def sample_conversation() -> Conversation:
    return Conversation(
        project_id="proj-1",
        tenant_id="t-1",
        user_id="u-1",
        title="Test conversation",
    )


@pytest.fixture()
def sample_message() -> Message:
    return Message(
        conversation_id="conv-1",
        role=MessageRole.USER,
        content="Hello, world!",
        message_type=MessageType.TEXT,
    )


@pytest.fixture()
def sample_subagent_result() -> SubAgentResult:
    return SubAgentResult(
        subagent_id="sa-1",
        subagent_name="researcher",
        summary="Found 3 relevant papers on quantum computing.",
        success=True,
        tool_calls_count=5,
        tokens_used=1200,
        execution_time_ms=3500,
    )


@pytest.fixture()
def engine(
    mock_context_facade: MagicMock,
    mock_context_bridge: MagicMock,
) -> DefaultContextEngine:
    return DefaultContextEngine(
        context_facade=mock_context_facade,
        context_bridge=mock_context_bridge,
    )


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    """DefaultContextEngine must satisfy ContextEnginePort at runtime."""

    def test_is_instance_of_context_engine_port(self, engine: DefaultContextEngine) -> None:
        assert isinstance(engine, ContextEnginePort)

    def test_has_all_required_methods(self, engine: DefaultContextEngine) -> None:
        assert callable(getattr(engine, "on_message_ingest", None))
        assert callable(getattr(engine, "assemble_context", None))
        assert callable(getattr(engine, "compact_context", None))
        assert callable(getattr(engine, "after_turn", None))
        assert callable(getattr(engine, "on_subagent_ended", None))


# ---------------------------------------------------------------------------
# on_message_ingest
# ---------------------------------------------------------------------------


class TestOnMessageIngest:
    """on_message_ingest is a no-op hook in the default implementation."""

    async def test_on_message_ingest_returns_none(
        self,
        engine: DefaultContextEngine,
        sample_conversation: Conversation,
        sample_message: Message,
    ) -> None:
        result = await engine.on_message_ingest(sample_message, sample_conversation)
        assert result is None

    async def test_on_message_ingest_does_not_raise(
        self,
        engine: DefaultContextEngine,
        sample_conversation: Conversation,
        sample_message: Message,
    ) -> None:
        await engine.on_message_ingest(sample_message, sample_conversation)


# ---------------------------------------------------------------------------
# assemble_context
# ---------------------------------------------------------------------------


class TestAssembleContext:
    """assemble_context delegates to ContextFacade.build_context."""

    async def test_assemble_context_returns_assembled_context(
        self,
        engine: DefaultContextEngine,
        mock_context_facade: MagicMock,
        sample_conversation: Conversation,
    ) -> None:
        mock_context_facade.build_context.return_value = MagicMock(
            messages=[
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Hi"},
            ],
            was_compressed=False,
            estimated_tokens=200,
        )
        mock_context_facade.estimate_messages_tokens.return_value = 200

        result = await engine.assemble_context(sample_conversation, token_budget=4000)

        assert isinstance(result, AssembledContext)
        assert result.budget_tokens == 4000
        assert result.total_tokens == 200

    async def test_assemble_context_extracts_system_prompt(
        self,
        engine: DefaultContextEngine,
        mock_context_facade: MagicMock,
        sample_conversation: Conversation,
    ) -> None:
        mock_context_facade.build_context.return_value = MagicMock(
            messages=[
                {"role": "system", "content": "System prompt here"},
                {"role": "user", "content": "Hi"},
            ],
            was_compressed=False,
            estimated_tokens=100,
        )
        mock_context_facade.estimate_messages_tokens.return_value = 100

        result = await engine.assemble_context(sample_conversation, token_budget=4000)

        assert result.system_prompt == "System prompt here"

    async def test_assemble_context_sets_compacted_when_compressed(
        self,
        engine: DefaultContextEngine,
        mock_context_facade: MagicMock,
        sample_conversation: Conversation,
    ) -> None:
        mock_context_facade.build_context.return_value = MagicMock(
            messages=[
                {"role": "system", "content": "prompt"},
                {"role": "user", "content": "msg"},
            ],
            was_compressed=True,
            estimated_tokens=500,
        )
        mock_context_facade.estimate_messages_tokens.return_value = 500

        result = await engine.assemble_context(sample_conversation, token_budget=4000)

        assert result.is_compacted is True

    async def test_assemble_context_with_empty_conversation(
        self,
        engine: DefaultContextEngine,
        mock_context_facade: MagicMock,
        sample_conversation: Conversation,
    ) -> None:
        mock_context_facade.build_context.return_value = MagicMock(
            messages=[{"role": "system", "content": "prompt"}],
            was_compressed=False,
            estimated_tokens=50,
        )
        mock_context_facade.estimate_messages_tokens.return_value = 50

        result = await engine.assemble_context(sample_conversation, token_budget=4000)

        assert result.message_count == 0
        assert result.system_prompt == "prompt"

    async def test_assemble_context_calls_facade_build_context(
        self,
        engine: DefaultContextEngine,
        mock_context_facade: MagicMock,
        sample_conversation: Conversation,
    ) -> None:
        mock_context_facade.build_context.return_value = MagicMock(
            messages=[{"role": "system", "content": "p"}],
            was_compressed=False,
            estimated_tokens=10,
        )
        mock_context_facade.estimate_messages_tokens.return_value = 10

        await engine.assemble_context(sample_conversation, token_budget=2000)

        mock_context_facade.build_context.assert_called_once()


# ---------------------------------------------------------------------------
# compact_context
# ---------------------------------------------------------------------------


class TestCompactContext:
    """compact_context prunes tool outputs and returns a compacted AssembledContext."""

    async def test_compact_context_returns_assembled_context(
        self,
        engine: DefaultContextEngine,
        mock_context_facade: MagicMock,
    ) -> None:
        original = AssembledContext(
            system_prompt="prompt",
            messages=(
                Message(
                    conversation_id="c1",
                    role=MessageRole.USER,
                    content="Hello",
                ),
            ),
            total_tokens=5000,
            budget_tokens=4000,
            is_compacted=False,
        )

        mock_context_facade.estimate_tokens.return_value = 50

        result = await engine.compact_context(original, target_tokens=3000)

        assert isinstance(result, AssembledContext)
        assert result.is_compacted is True
        assert result.budget_tokens == 3000

    async def test_compact_context_preserves_system_prompt(
        self,
        engine: DefaultContextEngine,
        mock_context_facade: MagicMock,
    ) -> None:
        original = AssembledContext(
            system_prompt="Keep this prompt",
            messages=(),
            total_tokens=100,
            budget_tokens=200,
        )

        result = await engine.compact_context(original, target_tokens=50)

        assert result.system_prompt == "Keep this prompt"

    async def test_compact_context_preserves_injected_context(
        self,
        engine: DefaultContextEngine,
        mock_context_facade: MagicMock,
    ) -> None:
        segment = ContextSegment(
            source="memory",
            content="relevant memory",
            token_count=20,
        )
        original = AssembledContext(
            system_prompt="prompt",
            messages=(),
            injected_context=(segment,),
            total_tokens=100,
            budget_tokens=200,
        )

        result = await engine.compact_context(original, target_tokens=50)

        assert result.injected_context == (segment,)


# ---------------------------------------------------------------------------
# after_turn
# ---------------------------------------------------------------------------


class TestAfterTurn:
    """after_turn is a no-op hook in the default implementation."""

    async def test_after_turn_returns_none(
        self,
        engine: DefaultContextEngine,
        sample_conversation: Conversation,
    ) -> None:
        turn_result: dict[str, Any] = {"status": "completed"}
        result = await engine.after_turn(sample_conversation, turn_result)
        assert result is None

    async def test_after_turn_does_not_raise(
        self,
        engine: DefaultContextEngine,
        sample_conversation: Conversation,
    ) -> None:
        await engine.after_turn(sample_conversation, None)


# ---------------------------------------------------------------------------
# on_subagent_ended
# ---------------------------------------------------------------------------


class TestOnSubagentEnded:
    """on_subagent_ended uses SubAgentResult.to_context_message for formatting."""

    async def test_on_subagent_ended_returns_none(
        self,
        engine: DefaultContextEngine,
        sample_conversation: Conversation,
        sample_subagent_result: SubAgentResult,
    ) -> None:
        result = await engine.on_subagent_ended(sample_conversation, sample_subagent_result)
        assert result is None

    async def test_on_subagent_ended_does_not_raise(
        self,
        engine: DefaultContextEngine,
        sample_conversation: Conversation,
        sample_subagent_result: SubAgentResult,
    ) -> None:
        await engine.on_subagent_ended(sample_conversation, sample_subagent_result)

    async def test_on_subagent_ended_with_failed_result(
        self,
        engine: DefaultContextEngine,
        sample_conversation: Conversation,
    ) -> None:
        failed_result = SubAgentResult(
            subagent_id="sa-2",
            subagent_name="coder",
            summary="",
            success=False,
            error="Timeout after 30s",
        )
        await engine.on_subagent_ended(sample_conversation, failed_result)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    """Tests for DefaultContextEngine construction and defaults."""

    def test_construct_with_facade_only(self, mock_context_facade: MagicMock) -> None:
        engine = DefaultContextEngine(context_facade=mock_context_facade)
        assert isinstance(engine, ContextEnginePort)

    def test_construct_with_all_dependencies(
        self,
        mock_context_facade: MagicMock,
        mock_context_bridge: MagicMock,
    ) -> None:
        engine = DefaultContextEngine(
            context_facade=mock_context_facade,
            context_bridge=mock_context_bridge,
        )
        assert isinstance(engine, ContextEnginePort)

    def test_context_bridge_defaults_to_none(self, mock_context_facade: MagicMock) -> None:
        engine = DefaultContextEngine(context_facade=mock_context_facade)
        assert engine._context_bridge is None
