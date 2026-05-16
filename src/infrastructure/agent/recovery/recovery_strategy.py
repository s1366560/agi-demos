"""Recovery strategies for agent session recovery.

Defines the RecoveryStrategy protocol and concrete strategy implementations
for each classified error type. Each strategy encapsulates the logic for
attempting recovery from a specific failure mode.

Reference: OpenCode session recovery patterns.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from src.infrastructure.agent.recovery.error_classifier import ErrorType
from src.infrastructure.agent.retry.policy import RetryPolicy

logger = logging.getLogger(__name__)


@dataclass(kw_only=True)
class RecoveryContext:
    """Context information passed to recovery strategies.

    Attributes:
        session_id: The active session identifier.
        error: The original exception that triggered recovery.
        error_type: The classified error type.
        attempt: Current recovery attempt number (1-based).
        messages: Current conversation messages (for context strategies).
        extra: Additional strategy-specific context data.
    """

    session_id: str
    error: Exception
    error_type: ErrorType
    attempt: int = 1
    messages: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(kw_only=True, frozen=True)
class RecoveryAction:
    """Result of a recovery strategy execution.

    Attributes:
        recovered: Whether recovery was successful.
        message: Human-readable description of the action taken.
        should_retry: Whether the caller should retry the failed operation.
        modified_messages: Optionally modified messages for context strategies.
        delay_ms: Delay in milliseconds before retrying (0 = no delay).
    """

    recovered: bool
    message: str
    should_retry: bool = False
    modified_messages: list[dict[str, Any]] | None = None
    delay_ms: int = 0


@runtime_checkable
class RecoveryStrategy(Protocol):
    """Protocol for recovery strategies.

    Each strategy handles a specific error type and returns a
    RecoveryAction describing what was done and whether the caller
    should retry.
    """

    @property
    def name(self) -> str:
        """Human-readable strategy name."""
        ...

    async def execute(self, context: RecoveryContext) -> RecoveryAction:
        """Execute the recovery strategy.

        Args:
            context: Recovery context with error details and session state.

        Returns:
            RecoveryAction describing the outcome.
        """
        ...


class RetryWithBackoffStrategy:
    """Recovery strategy for rate limit errors.

    Uses the existing RetryPolicy to calculate exponential backoff
    delays and determine retryability. Waits the calculated delay
    before signaling the caller to retry.
    """

    def __init__(
        self,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._retry_policy = retry_policy or RetryPolicy()

    @property
    def name(self) -> str:
        return "retry_with_backoff"

    async def execute(self, context: RecoveryContext) -> RecoveryAction:
        """Calculate backoff delay and signal retry.

        Args:
            context: Recovery context with rate limit error.

        Returns:
            RecoveryAction with delay and retry flag.
        """
        if not self._retry_policy.should_retry(context.attempt, context.error):
            return RecoveryAction(
                recovered=False,
                message=(f"Rate limit: max retries ({context.attempt}) exceeded"),
                should_retry=False,
            )

        delay_ms = self._retry_policy.calculate_delay(context.attempt, context.error)
        logger.info(
            "Rate limit recovery: waiting %dms (attempt %d)",
            delay_ms,
            context.attempt,
        )

        await asyncio.sleep(delay_ms / 1000.0)

        return RecoveryAction(
            recovered=True,
            message=(f"Rate limit: waited {delay_ms}ms (attempt {context.attempt})"),
            should_retry=True,
            delay_ms=delay_ms,
        )


class CompactContextStrategy:
    """Recovery strategy for context overflow errors.

    Signals that context compaction is needed by returning a
    RecoveryAction with should_retry=True. The caller is responsible
    for performing the actual compaction using the context module.
    """

    @property
    def name(self) -> str:
        return "compact_context"

    async def execute(self, context: RecoveryContext) -> RecoveryAction:
        """Signal that context compaction is needed.

        Args:
            context: Recovery context with overflow error.

        Returns:
            RecoveryAction signaling compaction needed.
        """
        msg_count = len(context.messages)
        logger.info(
            "Context overflow recovery: signaling compaction (session=%s, messages=%d)",
            context.session_id,
            msg_count,
        )
        return RecoveryAction(
            recovered=True,
            message=(f"Context overflow: compaction needed ({msg_count} messages in session)"),
            should_retry=True,
        )


class ProviderFailoverStrategy:
    """Recovery strategy for provider outages.

    Provider switching is owned by the LLM invocation layer
    (``LLMInvoker``/``FailoverChain``), where the failed operation and
    alternate model configuration are available. Session recovery cannot
    safely switch providers by returning a message, so this strategy
    reports an unrecovered outage instead of causing the ReAct loop to
    retry the same provider.
    """

    def __init__(
        self,
        fallback_providers: list[str] | None = None,
    ) -> None:
        self._fallback_providers = fallback_providers or []

    @property
    def name(self) -> str:
        return "provider_failover"

    async def execute(self, context: RecoveryContext) -> RecoveryAction:
        """Report provider outage recovery status.

        Args:
            context: Recovery context with provider error.

        Returns:
            RecoveryAction indicating that session-level recovery cannot
            perform provider failover.
        """
        fallback_hint = (
            f" configured candidates={', '.join(self._fallback_providers)}"
            if self._fallback_providers
            else " no candidates configured"
        )
        logger.warning(
            "Provider outage cannot be recovered in session recovery layer (session=%s, attempt=%d,%s)",
            context.session_id,
            context.attempt,
            fallback_hint,
        )
        return RecoveryAction(
            recovered=False,
            message=(
                "Provider unavailable: session recovery cannot switch providers; "
                "configure LLMInvoker FailoverChain for automatic provider failover"
            ),
            should_retry=False,
        )


class ResetToolStateStrategy:
    """Recovery strategy for tool execution errors.

    Signals that the tool state should be reset and the operation
    retried. The caller is responsible for performing the actual
    tool state reset.
    """

    @property
    def name(self) -> str:
        return "reset_tool_state"

    async def execute(self, context: RecoveryContext) -> RecoveryAction:
        """Signal tool state reset and retry.

        Args:
            context: Recovery context with tool error.

        Returns:
            RecoveryAction signaling reset and retry.
        """
        tool_name = context.extra.get("tool_name", "unknown")
        logger.info(
            "Tool error recovery: resetting state for tool=%s (session=%s, attempt=%d)",
            tool_name,
            context.session_id,
            context.attempt,
        )
        return RecoveryAction(
            recovered=True,
            message=(
                f"Tool error: reset state for '{tool_name}', retrying (attempt {context.attempt})"
            ),
            should_retry=True,
        )


class AbortWithMessageStrategy:
    """Recovery strategy for non-recoverable errors (auth errors).

    Immediately aborts with a user-facing error message. Does not
    signal retry since these errors require user intervention
    (e.g., providing a valid API key).
    """

    @property
    def name(self) -> str:
        return "abort_with_message"

    async def execute(self, context: RecoveryContext) -> RecoveryAction:
        """Abort and return user-facing error message.

        Args:
            context: Recovery context with auth error.

        Returns:
            RecoveryAction with recovered=False and no retry.
        """
        logger.warning(
            "Non-recoverable error: aborting session=%s, error_type=%s",
            context.session_id,
            context.error_type.value,
        )
        return RecoveryAction(
            recovered=False,
            message=(f"Authentication error: {context.error}. Please check your API credentials."),
            should_retry=False,
        )


class BreakLoopStrategy:
    """Recovery strategy for doom loop detection.

    Injects a 'step back' instruction into the conversation messages
    to force the agent to change its approach. Returns modified
    messages with the intervention and signals retry.
    """

    INTERVENTION_MESSAGE: str = (
        "SYSTEM INTERVENTION: You appear to be stuck in a "
        "repetitive loop. Stop repeating the same actions. "
        "Step back and reconsider your approach. Try a "
        "completely different strategy to achieve the goal."
    )

    @property
    def name(self) -> str:
        return "break_loop"

    async def execute(self, context: RecoveryContext) -> RecoveryAction:
        """Inject intervention message to break the loop.

        Args:
            context: Recovery context with doom loop detection.

        Returns:
            RecoveryAction with modified messages and retry flag.
        """
        logger.info(
            "Doom loop recovery: injecting intervention (session=%s, attempt=%d)",
            context.session_id,
            context.attempt,
        )

        modified = list(context.messages)
        modified.append(
            {
                "role": "user",
                "content": self.INTERVENTION_MESSAGE,
            }
        )

        return RecoveryAction(
            recovered=True,
            message=(
                f"Doom loop detected: injected step-back instruction (attempt {context.attempt})"
            ),
            should_retry=True,
            modified_messages=modified,
        )
