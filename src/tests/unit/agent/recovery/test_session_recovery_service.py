"""Unit tests for SessionRecoveryService."""

from __future__ import annotations

from typing import Any

import pytest

from src.infrastructure.agent.recovery.error_classifier import (
    ErrorType,
)
from src.infrastructure.agent.recovery.recovery_strategy import (
    RecoveryAction,
    RecoveryContext,
)
from src.infrastructure.agent.recovery.session_recovery_service import (
    SessionRecoveryService,
)


class _FakeStrategy:
    """Fake strategy for testing."""

    def __init__(
        self,
        name: str = "fake",
        recovered: bool = True,
        should_retry: bool = True,
    ) -> None:
        self._name = name
        self._recovered = recovered
        self._should_retry = should_retry
        self.last_context: RecoveryContext | None = None

    @property
    def name(self) -> str:
        return self._name

    async def execute(self, context: RecoveryContext) -> RecoveryAction:
        self.last_context = context
        return RecoveryAction(
            recovered=self._recovered,
            message=f"Fake: {self._name}",
            should_retry=self._should_retry,
        )


class _FailingStrategy:
    """Strategy that raises an exception on execute."""

    @property
    def name(self) -> str:
        return "failing"

    async def execute(self, context: RecoveryContext) -> RecoveryAction:
        raise RuntimeError("Strategy exploded")


@pytest.mark.unit
class TestSessionRecoveryService:
    """Tests for SessionRecoveryService orchestration."""

    async def test_successful_recovery(self) -> None:
        """Should classify error and execute matching strategy."""
        # Arrange
        fake_strategy = _FakeStrategy(name="test_strategy")
        service = SessionRecoveryService(
            strategy_overrides={ErrorType.UNKNOWN: fake_strategy},
        )
        error = Exception("Something unknown")

        # Act
        result = await service.attempt_recovery(
            session_id="sess-1",
            error=error,
        )

        # Assert
        assert result.recovered is True
        assert result.strategy_used == "test_strategy"
        assert result.should_retry is True
        assert fake_strategy.last_context is not None
        assert fake_strategy.last_context.session_id == "sess-1"
        assert fake_strategy.last_context.attempt == 1

    async def test_failed_recovery(self) -> None:
        """Should return failure when strategy reports not recovered."""
        # Arrange
        fake_strategy = _FakeStrategy(
            name="fail_strategy",
            recovered=False,
            should_retry=False,
        )
        service = SessionRecoveryService(
            strategy_overrides={ErrorType.UNKNOWN: fake_strategy},
        )

        # Act
        result = await service.attempt_recovery(
            session_id="sess-1",
            error=Exception("fail"),
        )

        # Assert
        assert result.recovered is False
        assert result.strategy_used == "fail_strategy"
        assert result.should_retry is False

    async def test_max_attempts_exceeded(self) -> None:
        """Should block recovery after max attempts."""
        # Arrange
        fake_strategy = _FakeStrategy()
        service = SessionRecoveryService(
            max_attempts=2,
            strategy_overrides={ErrorType.UNKNOWN: fake_strategy},
        )
        error = Exception("repeated error")

        # Act -- exhaust max attempts
        _ = await service.attempt_recovery(session_id="sess-1", error=error)
        _ = await service.attempt_recovery(session_id="sess-1", error=error)
        result = await service.attempt_recovery(session_id="sess-1", error=error)

        # Assert
        assert result.recovered is False
        assert result.strategy_used == "none"
        assert "Max recovery attempts" in result.message
        assert result.should_retry is False

    async def test_attempt_tracking_per_session(self) -> None:
        """Should track attempts independently per session."""
        # Arrange
        fake_strategy = _FakeStrategy()
        service = SessionRecoveryService(
            max_attempts=2,
            strategy_overrides={ErrorType.UNKNOWN: fake_strategy},
        )
        error = Exception("error")

        # Act
        _ = await service.attempt_recovery(session_id="sess-1", error=error)
        _ = await service.attempt_recovery(session_id="sess-2", error=error)

        # Assert
        assert service.get_attempt_count("sess-1") == 1
        assert service.get_attempt_count("sess-2") == 1

    async def test_reset_attempts(self) -> None:
        """Should reset attempt count for a session."""
        # Arrange
        fake_strategy = _FakeStrategy()
        service = SessionRecoveryService(
            strategy_overrides={ErrorType.UNKNOWN: fake_strategy},
        )
        error = Exception("error")
        _ = await service.attempt_recovery(session_id="sess-1", error=error)
        assert service.get_attempt_count("sess-1") == 1

        # Act
        service.reset_attempts("sess-1")

        # Assert
        assert service.get_attempt_count("sess-1") == 0

    async def test_reset_nonexistent_session(self) -> None:
        """Should not raise when resetting a session that has no attempts."""
        # Arrange
        service = SessionRecoveryService()

        # Act / Assert -- no exception
        service.reset_attempts("nonexistent")
        assert service.get_attempt_count("nonexistent") == 0

    async def test_get_attempt_count_default(self) -> None:
        """Should return 0 for sessions with no attempts."""
        # Arrange
        service = SessionRecoveryService()

        # Act / Assert
        assert service.get_attempt_count("new-session") == 0

    async def test_passes_messages_and_extra(self) -> None:
        """Should pass messages and extra to the strategy context."""
        # Arrange
        fake_strategy = _FakeStrategy()
        service = SessionRecoveryService(
            strategy_overrides={ErrorType.UNKNOWN: fake_strategy},
        )
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": "hello"},
        ]
        extra: dict[str, Any] = {"tool_name": "terminal"}

        # Act
        _ = await service.attempt_recovery(
            session_id="sess-1",
            error=Exception("error"),
            messages=messages,
            extra=extra,
        )

        # Assert
        assert fake_strategy.last_context is not None
        assert fake_strategy.last_context.messages == messages
        assert fake_strategy.last_context.extra == extra

    async def test_strategy_exception_returns_failure(self) -> None:
        """Should return failure if strategy raises exception."""
        # Arrange
        service = SessionRecoveryService(
            strategy_overrides={ErrorType.UNKNOWN: _FailingStrategy()},
        )

        # Act
        result = await service.attempt_recovery(
            session_id="sess-1",
            error=Exception("error"),
        )

        # Assert
        assert result.recovered is False
        assert result.strategy_used == "failing"
        assert "failed" in result.message.lower()
        assert result.should_retry is False

    async def test_result_includes_action(self) -> None:
        """Should include the RecoveryAction in the result."""
        # Arrange
        fake_strategy = _FakeStrategy()
        service = SessionRecoveryService(
            strategy_overrides={ErrorType.UNKNOWN: fake_strategy},
        )

        # Act
        result = await service.attempt_recovery(
            session_id="sess-1",
            error=Exception("error"),
        )

        # Assert
        assert result.action is not None
        assert result.action.recovered is True

    async def test_provider_down_does_not_retry_without_llm_failover_chain(self) -> None:
        """Provider outages must not trigger a fake retry through session recovery."""

        class ProviderDownError(Exception):
            status_code = 503

        service = SessionRecoveryService()

        result = await service.attempt_recovery(
            session_id="sess-1",
            error=ProviderDownError("service unavailable"),
        )

        assert result.recovered is False
        assert result.strategy_used == "provider_failover"
        assert result.should_retry is False
        assert "FailoverChain" in result.message

    async def test_default_strategies_present(self) -> None:
        service = SessionRecoveryService()
        strategies = service.get_strategies()
        for error_type in ErrorType:
            assert error_type in strategies, f"No default strategy for {error_type}"

    async def test_strategy_overrides(self) -> None:
        custom = _FakeStrategy(name="custom")
        service = SessionRecoveryService(
            strategy_overrides={ErrorType.LLM_RATE_LIMIT: custom},
        )
        strategies = service.get_strategies()
        assert strategies[ErrorType.LLM_RATE_LIMIT] is custom
