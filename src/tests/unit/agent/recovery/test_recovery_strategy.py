"""Unit tests for recovery strategies."""

from __future__ import annotations

import pytest

from src.infrastructure.agent.recovery.error_classifier import ErrorType
from src.infrastructure.agent.recovery.recovery_strategy import (
    AbortWithMessageStrategy,
    BreakLoopStrategy,
    CompactContextStrategy,
    ProviderFailoverStrategy,
    RecoveryContext,
    RecoveryStrategy,
    ResetToolStateStrategy,
    RetryWithBackoffStrategy,
)
from src.infrastructure.agent.retry.policy import RetryPolicy


def _make_context(
    error_type: ErrorType = ErrorType.UNKNOWN,
    attempt: int = 1,
    messages: list[dict[str, object]] | None = None,
    extra: dict[str, object] | None = None,
) -> RecoveryContext:
    """Helper to build a RecoveryContext.

    The error carries a ``status_code`` attribute so that
    ``RetryPolicy.is_retryable`` recognises it as retryable when
    the error type is a rate-limit or transient failure.
    """
    error = Exception("rate limit exceeded")
    error.status_code = 429  # type: ignore[attr-defined]
    return RecoveryContext(
        session_id="test-session",
        error=error,
        error_type=error_type,
        attempt=attempt,
        messages=messages or [],
        extra=extra or {},
    )


@pytest.mark.unit
class TestRetryWithBackoffStrategy:
    """Tests for RetryWithBackoffStrategy."""

    async def test_name(self) -> None:
        """Strategy name is 'retry_with_backoff'."""
        strategy = RetryWithBackoffStrategy()
        assert strategy.name == "retry_with_backoff"

    async def test_conforms_to_protocol(self) -> None:
        """Strategy conforms to RecoveryStrategy protocol."""
        strategy = RetryWithBackoffStrategy()
        assert isinstance(strategy, RecoveryStrategy)

    async def test_retry_on_first_attempt(self) -> None:
        """Should retry with delay on first attempt."""
        # Arrange
        policy = RetryPolicy(initial_delay_ms=100, max_attempts=3)
        strategy = RetryWithBackoffStrategy(retry_policy=policy)
        ctx = _make_context(error_type=ErrorType.LLM_RATE_LIMIT, attempt=1)

        # Act
        action = await strategy.execute(ctx)

        # Assert
        assert action.recovered is True
        assert action.should_retry is True
        assert action.delay_ms > 0

    async def test_no_retry_when_max_exceeded(self) -> None:
        """Should not retry when max attempts exceeded."""
        # Arrange
        policy = RetryPolicy(initial_delay_ms=100, max_attempts=2)
        strategy = RetryWithBackoffStrategy(retry_policy=policy)
        ctx = _make_context(error_type=ErrorType.LLM_RATE_LIMIT, attempt=5)

        # Act
        action = await strategy.execute(ctx)

        # Assert
        assert action.recovered is False
        assert action.should_retry is False

    async def test_no_retry_for_provider_protocol_400(self) -> None:
        """Provider protocol 400s should not retry against the same provider."""
        policy = RetryPolicy(initial_delay_ms=100, max_attempts=3)
        error = Exception(
            "litellm.InternalServerError: AnthropicException - 400, "
            'message="Expected HTTP/, RTSP/ or ICE/"'
        )

        assert policy.is_retryable(error) is False


@pytest.mark.unit
class TestCompactContextStrategy:
    """Tests for CompactContextStrategy."""

    async def test_name(self) -> None:
        """Strategy name is 'compact_context'."""
        strategy = CompactContextStrategy()
        assert strategy.name == "compact_context"

    async def test_conforms_to_protocol(self) -> None:
        """Strategy conforms to RecoveryStrategy protocol."""
        strategy = CompactContextStrategy()
        assert isinstance(strategy, RecoveryStrategy)

    async def test_signals_compaction(self) -> None:
        """Should signal compaction with retry."""
        # Arrange
        messages: list[dict[str, object]] = [
            {"role": "user", "content": f"msg-{i}"} for i in range(10)
        ]
        ctx = _make_context(
            error_type=ErrorType.LLM_CONTEXT_OVERFLOW,
            messages=messages,
        )
        strategy = CompactContextStrategy()

        # Act
        action = await strategy.execute(ctx)

        # Assert
        assert action.recovered is True
        assert action.should_retry is True
        assert "10 messages" in action.message


@pytest.mark.unit
class TestProviderFailoverStrategy:
    """Tests for ProviderFailoverStrategy."""

    async def test_name(self) -> None:
        """Strategy name is 'provider_failover'."""
        strategy = ProviderFailoverStrategy()
        assert strategy.name == "provider_failover"

    async def test_conforms_to_protocol(self) -> None:
        """Strategy conforms to RecoveryStrategy protocol."""
        strategy = ProviderFailoverStrategy()
        assert isinstance(strategy, RecoveryStrategy)

    async def test_no_fallback_providers(self) -> None:
        """Should fail when no fallback providers are configured."""
        # Arrange
        strategy = ProviderFailoverStrategy(fallback_providers=[])
        ctx = _make_context(error_type=ErrorType.LLM_PROVIDER_DOWN)

        # Act
        action = await strategy.execute(ctx)

        # Assert
        assert action.recovered is False
        assert action.should_retry is False

    async def test_configured_fallbacks_do_not_fake_switch(self) -> None:
        """Should not claim failover when the strategy cannot switch providers."""
        # Arrange
        strategy = ProviderFailoverStrategy(
            fallback_providers=["openai", "anthropic"],
        )
        ctx = _make_context(
            error_type=ErrorType.LLM_PROVIDER_DOWN,
            attempt=1,
        )

        # Act
        action = await strategy.execute(ctx)

        # Assert
        assert action.recovered is False
        assert action.should_retry is False
        assert "session recovery cannot switch providers" in action.message

    async def test_does_not_round_robin_without_real_failover_executor(self) -> None:
        """Should avoid rotating provider names without applying a real failover."""
        # Arrange
        strategy = ProviderFailoverStrategy(
            fallback_providers=["openai", "anthropic"],
        )
        ctx = _make_context(
            error_type=ErrorType.LLM_PROVIDER_DOWN,
            attempt=2,
        )

        # Act
        action = await strategy.execute(ctx)

        # Assert
        assert action.recovered is False
        assert action.should_retry is False
        assert "anthropic" not in action.message


@pytest.mark.unit
class TestResetToolStateStrategy:
    """Tests for ResetToolStateStrategy."""

    async def test_name(self) -> None:
        """Strategy name is 'reset_tool_state'."""
        strategy = ResetToolStateStrategy()
        assert strategy.name == "reset_tool_state"

    async def test_conforms_to_protocol(self) -> None:
        """Strategy conforms to RecoveryStrategy protocol."""
        strategy = ResetToolStateStrategy()
        assert isinstance(strategy, RecoveryStrategy)

    async def test_reset_with_tool_name(self) -> None:
        """Should reset and retry with tool name in message."""
        # Arrange
        strategy = ResetToolStateStrategy()
        ctx = _make_context(
            error_type=ErrorType.TOOL_EXECUTION_ERROR,
            extra={"tool_name": "terminal"},
        )

        # Act
        action = await strategy.execute(ctx)

        # Assert
        assert action.recovered is True
        assert action.should_retry is True
        assert "terminal" in action.message

    async def test_reset_without_tool_name(self) -> None:
        """Should use 'unknown' when tool name not provided."""
        # Arrange
        strategy = ResetToolStateStrategy()
        ctx = _make_context(error_type=ErrorType.TOOL_EXECUTION_ERROR)

        # Act
        action = await strategy.execute(ctx)

        # Assert
        assert action.recovered is True
        assert "unknown" in action.message


@pytest.mark.unit
class TestAbortWithMessageStrategy:
    """Tests for AbortWithMessageStrategy."""

    async def test_name(self) -> None:
        """Strategy name is 'abort_with_message'."""
        strategy = AbortWithMessageStrategy()
        assert strategy.name == "abort_with_message"

    async def test_conforms_to_protocol(self) -> None:
        """Strategy conforms to RecoveryStrategy protocol."""
        strategy = AbortWithMessageStrategy()
        assert isinstance(strategy, RecoveryStrategy)

    async def test_aborts_with_message(self) -> None:
        """Should abort without retry."""
        # Arrange
        strategy = AbortWithMessageStrategy()
        ctx = _make_context(error_type=ErrorType.LLM_AUTH_ERROR)

        # Act
        action = await strategy.execute(ctx)

        # Assert
        assert action.recovered is False
        assert action.should_retry is False
        assert "Authentication error" in action.message


@pytest.mark.unit
class TestBreakLoopStrategy:
    """Tests for BreakLoopStrategy."""

    async def test_name(self) -> None:
        """Strategy name is 'break_loop'."""
        strategy = BreakLoopStrategy()
        assert strategy.name == "break_loop"

    async def test_conforms_to_protocol(self) -> None:
        """Strategy conforms to RecoveryStrategy protocol."""
        strategy = BreakLoopStrategy()
        assert isinstance(strategy, RecoveryStrategy)

    async def test_injects_intervention_message(self) -> None:
        """Should inject intervention message into conversation."""
        # Arrange
        messages: list[dict[str, object]] = [
            {"role": "user", "content": "Do task X"},
            {"role": "assistant", "content": "Doing X..."},
        ]
        strategy = BreakLoopStrategy()
        ctx = _make_context(
            error_type=ErrorType.DOOM_LOOP,
            messages=messages,
        )

        # Act
        action = await strategy.execute(ctx)

        # Assert
        assert action.recovered is True
        assert action.should_retry is True
        assert action.modified_messages is not None
        assert len(action.modified_messages) == 3
        last_msg = action.modified_messages[-1]
        assert last_msg["role"] == "user"
        assert "SYSTEM INTERVENTION" in str(last_msg["content"])

    async def test_does_not_mutate_original_messages(self) -> None:
        """Should not mutate the original message list."""
        # Arrange
        messages: list[dict[str, object]] = [
            {"role": "user", "content": "Do task X"},
        ]
        original_len = len(messages)
        strategy = BreakLoopStrategy()
        ctx = _make_context(
            error_type=ErrorType.DOOM_LOOP,
            messages=messages,
        )

        # Act
        _ = await strategy.execute(ctx)

        # Assert
        assert len(messages) == original_len
