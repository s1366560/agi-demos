"""Model Failover Chain for LLM providers.

Manages ordered fallback sequences across LLM providers. When a primary
provider fails with a failover-worthy error (rate limit, server error,
timeout), the chain automatically tries the next provider in sequence.

This works alongside the circuit breaker (per-provider fault tolerance)
at a higher level -- routing across providers rather than retrying within
one.

Error classification:
    FAILOVER-worthy: 429, 500, 502, 503, 504, connection errors, timeouts
    NOT failover-worthy: 401/403 auth, validation errors, context too long

Example:
    chain = FailoverChain(
        fallback_sequence=[
            ("gemini", "gemini-2.0-flash"),
            ("openai", "gpt-4o"),
            ("deepseek", "deepseek-chat"),
        ],
    )

    async def call_provider(provider: str, model: str):
        client = get_client_for(provider, model)
        return await client.generate(messages)

    result = await chain.execute(call_provider)
    print(f"Used: {result.provider_used}/{result.model_used}")
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.infrastructure.llm.load_balancer import ProviderHealthStore

logger = logging.getLogger(__name__)

# HTTP status codes that warrant failover to another provider.
_FAILOVER_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

# HTTP status codes that should NOT trigger failover (would fail everywhere).
_NON_FAILOVER_STATUS_CODES: frozenset[int] = frozenset({401, 403})

# Error message patterns indicating failover-worthy transient failures.
_FAILOVER_PATTERNS: list[str] = [
    r"rate.?limit",
    r"too_many_requests",
    r"overloaded",
    r"server.?error",
    r"bad.?gateway",
    r"gateway.?timeout",
    r"service.?unavailable",
    r"unavailable",
    r"timeout",
    r"timed?\s*out",
    r"connection.?reset",
    r"connection.?refused",
    r"connection.?error",
    r"temporary.?failure",
]

# Error message patterns indicating non-failover-worthy errors.
_NON_FAILOVER_PATTERNS: list[str] = [
    r"auth",
    r"unauthorized",
    r"forbidden",
    r"invalid.?api.?key",
    r"context.?(length|too\s*long|window)",
    r"max.?tokens?.?exceeded",
    r"validation",
    r"invalid.?request",
]


@dataclass(frozen=True, kw_only=True)
class FailoverConfig:
    """Immutable configuration for the failover chain.

    Attributes:
        max_failover_attempts: Maximum number of providers to try before
            giving up. Capped at the length of the fallback sequence.
        failover_timeout_seconds: Total wall-clock budget for all attempts.
        track_provider_health: Whether to track per-provider health and
            skip unhealthy providers.
        cooldown_seconds: How long to skip a provider after it fails
            before considering it healthy again.
    """

    max_failover_attempts: int = 3
    failover_timeout_seconds: float = 30.0
    track_provider_health: bool = True
    cooldown_seconds: float = 60.0


@dataclass(kw_only=True)
class ProviderHealth:
    """Read-only view of a provider/model's health.

    The authoritative state lives in :class:`ProviderHealthStore` (shared
    with the load balancer). This dataclass exists as a backwards-compatible
    surface for callers and tests: a :class:`FailoverChain` builds a fresh
    ``ProviderHealth`` on demand from the underlying store record.

    Fields remain mutable so legacy code that manually adjusts them in
    tests still works — mutations do NOT propagate back to the store.
    """

    provider: str
    model: str
    consecutive_failures: int = 0
    last_failure_at: datetime | None = None
    is_healthy: bool = True


@dataclass(kw_only=True)
class FailoverResult:
    """Result of a failover chain execution.

    Attributes:
        success: Whether any provider succeeded.
        provider_used: Provider that handled the request (empty on failure).
        model_used: Model that handled the request (empty on failure).
        attempts: Log of each attempt with provider, error, and duration.
        total_duration_ms: Wall-clock time for the entire chain execution.
        response: The actual response from the successful provider, or None.
    """

    success: bool
    provider_used: str
    model_used: str
    attempts: list[dict[str, Any]]
    total_duration_ms: float
    response: Any = None


def is_failover_worthy(error: Exception) -> bool:
    """Classify whether an error should trigger failover.

    Failover-worthy errors are transient provider-side issues that a
    different provider might not have (rate limit, outage, timeout).
    Non-failover-worthy errors would fail on any provider (auth,
    validation, context too long).

    Args:
        error: The exception to classify.

    Returns:
        True if failover to another provider should be attempted.
    """
    # Check explicit non-failover status codes first.
    status_code = _extract_status_code(error)
    if status_code is not None:
        if status_code in _NON_FAILOVER_STATUS_CODES:
            return False
        if status_code in _FAILOVER_STATUS_CODES:
            return True

    error_str = str(error).lower()

    # Check non-failover patterns (auth, validation, context).
    for pattern in _NON_FAILOVER_PATTERNS:
        if re.search(pattern, error_str, re.IGNORECASE):
            return False

    # Check failover patterns (rate limit, timeout, server error).
    for pattern in _FAILOVER_PATTERNS:
        if re.search(pattern, error_str, re.IGNORECASE):
            return True

    # Check error type name as fallback.
    error_type = type(error).__name__.lower()
    failover_type_keywords = ("timeout", "connection", "temporary")
    return any(kw in error_type for kw in failover_type_keywords)


def _extract_status_code(error: Exception) -> int | None:
    """Extract HTTP status code from an exception, if present."""
    for attr in ("status_code", "status", "code", "http_status"):
        code = getattr(error, attr, None)
        if code is not None:
            try:
                return int(code)
            except (ValueError, TypeError):
                pass

    for attr in ("response", "http_response", "_response"):
        response = getattr(error, attr, None)
        if response is not None:
            for code_attr in ("status_code", "status", "code"):
                code = getattr(response, code_attr, None)
                if code is not None:
                    try:
                        return int(code)
                    except (ValueError, TypeError):
                        pass

    return None


class FailoverChain:
    """Ordered failover chain across LLM providers.

    Executes a callable against providers in sequence, failing over to
    the next on transient errors. Tracks per-provider health to skip
    providers that are in cooldown.

    The ``call_fn`` passed to :meth:`execute` receives ``(provider, model)``
    as the first two positional arguments, followed by any extra ``*args``
    and ``**kwargs``.

    Example::

        chain = FailoverChain([("openai", "gpt-4o"), ("gemini", "gemini-2.0-flash")])

        result = await chain.execute(my_llm_call, system_prompt="Hello")
        if result.success:
            print(result.response)
    """

    def __init__(
        self,
        fallback_sequence: list[tuple[str, str]],
        config: FailoverConfig | None = None,
        *,
        health_store: ProviderHealthStore | None = None,
    ) -> None:
        """Initialize the failover chain.

        Args:
            fallback_sequence: Ordered list of ``(provider, model)`` tuples.
                The first entry is the primary; subsequent entries are
                fallbacks tried in order.
            config: Optional configuration. Uses defaults if not provided.
            health_store: Optional shared :class:`ProviderHealthStore`.
                When omitted, a private store is created using
                ``config.cooldown_seconds``. Provide an explicit store
                only when the chain should share health state with the
                load balancer or another chain.

        Raises:
            ValueError: If ``fallback_sequence`` is empty.
        """
        if not fallback_sequence:
            raise ValueError("fallback_sequence must contain at least one entry")

        self._sequence = list(fallback_sequence)
        self._config = config or FailoverConfig()
        self._health_store = health_store or ProviderHealthStore(
            cooldown_seconds=self._config.cooldown_seconds,
        )

    @property
    def config(self) -> FailoverConfig:
        """Return the chain configuration."""
        return self._config

    @property
    def fallback_sequence(self) -> list[tuple[str, str]]:
        """Return a copy of the full fallback sequence."""
        return list(self._sequence)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(
        self,
        call_fn: Callable[..., Coroutine[Any, Any, Any]],
        *args: Any,  # noqa: ANN401
        **kwargs: Any,  # noqa: ANN401
    ) -> FailoverResult:
        """Execute ``call_fn`` with failover across providers.

        The callable is invoked as ``call_fn(provider, model, *args, **kwargs)``
        for each provider in the healthy sequence until one succeeds or
        all attempts are exhausted.

        Args:
            call_fn: Async callable accepting ``(provider, model, ...)``
            *args: Extra positional arguments forwarded to ``call_fn``.
            **kwargs: Extra keyword arguments forwarded to ``call_fn``.

        Returns:
            :class:`FailoverResult` with success/failure details.
        """
        start = time.monotonic()
        attempts: list[dict[str, Any]] = []

        sequence = self.get_healthy_sequence()
        if not sequence:
            # All providers in cooldown -- fall back to full sequence.
            sequence = list(self._sequence)

        max_attempts = min(self._config.max_failover_attempts, len(sequence))

        for idx in range(max_attempts):
            provider, model = sequence[idx]

            # Check timeout budget.
            elapsed = time.monotonic() - start
            if elapsed >= self._config.failover_timeout_seconds:
                logger.warning(
                    "Failover chain timeout after %.1fs, tried %d providers",
                    elapsed,
                    idx,
                )
                break

            attempt_start = time.monotonic()
            try:
                response = await call_fn(provider, model, *args, **kwargs)

                attempt_ms = (time.monotonic() - attempt_start) * 1000
                attempts.append(
                    {
                        "provider": provider,
                        "model": model,
                        "success": True,
                        "duration_ms": round(attempt_ms, 2),
                    }
                )

                if self._config.track_provider_health:
                    self.mark_provider_recovered(provider, model)

                total_ms = (time.monotonic() - start) * 1000
                if idx > 0:
                    logger.info(
                        "Failover succeeded on attempt %d: %s/%s (%.1fms)",
                        idx + 1,
                        provider,
                        model,
                        total_ms,
                    )

                return FailoverResult(
                    success=True,
                    provider_used=provider,
                    model_used=model,
                    attempts=attempts,
                    total_duration_ms=round(total_ms, 2),
                    response=response,
                )

            except Exception as exc:
                attempt_ms = (time.monotonic() - attempt_start) * 1000
                attempts.append(
                    {
                        "provider": provider,
                        "model": model,
                        "success": False,
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                        "duration_ms": round(attempt_ms, 2),
                    }
                )

                if self._config.track_provider_health:
                    self.mark_provider_failed(provider, model)

                if not is_failover_worthy(exc):
                    logger.warning(
                        "Non-failover-worthy error from %s/%s: %s",
                        provider,
                        model,
                        exc,
                    )
                    total_ms = (time.monotonic() - start) * 1000
                    return FailoverResult(
                        success=False,
                        provider_used=provider,
                        model_used=model,
                        attempts=attempts,
                        total_duration_ms=round(total_ms, 2),
                    )

                logger.warning(
                    "Provider %s/%s failed (attempt %d/%d): %s",
                    provider,
                    model,
                    idx + 1,
                    max_attempts,
                    exc,
                )

        # All attempts exhausted.
        total_ms = (time.monotonic() - start) * 1000
        logger.error(
            "Failover chain exhausted after %d attempts (%.1fms)",
            len(attempts),
            total_ms,
        )

        last_provider = attempts[-1]["provider"] if attempts else ""
        last_model = attempts[-1]["model"] if attempts else ""

        return FailoverResult(
            success=False,
            provider_used=last_provider,
            model_used=last_model,
            attempts=attempts,
            total_duration_ms=round(total_ms, 2),
        )

    # ------------------------------------------------------------------
    # Health tracking (delegates to ProviderHealthStore)
    # ------------------------------------------------------------------

    def is_provider_healthy(self, provider: str, model: str | None = None) -> bool:
        """Check if a provider is considered healthy.

        A provider is unhealthy if it has failed and is still within its
        cooldown window.

        Args:
            provider: Provider identifier.
            model: Optional model identifier. When None, checks all models
                for the provider and returns True if any are healthy.

        Returns:
            True if the provider is healthy or past cooldown.
        """
        if model is not None:
            return self._health_store.is_healthy(self._health_key(provider, model))

        tracked_models = [m for p, m in self._sequence if p == provider]
        if not tracked_models:
            # Unknown provider — treat as healthy.
            return True
        return any(
            self._health_store.is_healthy(self._health_key(provider, m))
            for m in tracked_models
        )

    def mark_provider_failed(self, provider: str, model: str | None = None) -> None:
        """Record a failure for a provider/model pair."""
        model = model or self._default_model(provider)
        key = self._health_key(provider, model)
        self._health_store.record_failure(key)
        rec = self._health_store.get(key)
        logger.debug(
            "Provider %s/%s marked failed (consecutive: %d)",
            provider,
            model,
            rec.consecutive_failures,
        )

    def mark_provider_recovered(self, provider: str, model: str | None = None) -> None:
        """Record a success and reset failure state for a provider."""
        model = model or self._default_model(provider)
        key = self._health_key(provider, model)
        self._health_store.record_success(key)
        logger.debug("Provider %s/%s marked recovered", provider, model)

    def get_healthy_sequence(self) -> list[tuple[str, str]]:
        """Return the fallback sequence filtered to healthy providers."""
        if not self._config.track_provider_health:
            return list(self._sequence)
        return [
            (p, m)
            for p, m in self._sequence
            if self._health_store.is_healthy(self._health_key(p, m))
        ]

    def get_provider_health(
        self, provider: str, model: str | None = None
    ) -> ProviderHealth | None:
        """Build a :class:`ProviderHealth` view from the store record.

        Returns a default-healthy view for any provider/model in the
        configured sequence (matching the legacy pre-populated behaviour);
        returns ``None`` for unknown provider/model pairs.
        """
        model = model or self._default_model(provider)
        if (provider, model) not in self._sequence:
            return None
        key = self._health_key(provider, model)
        rec = self._health_store.get(key)
        return ProviderHealth(
            provider=provider,
            model=model,
            consecutive_failures=rec.consecutive_failures,
            last_failure_at=rec.last_failure_at,
            is_healthy=self._health_store.is_healthy(key),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _health_key(provider: str, model: str) -> str:
        """Create a unique key for a provider/model pair.

        Prefixed with ``chain:`` so chain entries cannot collide with
        pool candidate keys (``{provider_id}:{model_name}``) when the
        same :class:`ProviderHealthStore` is shared.
        """
        return f"chain:{provider}:{model}"

    def _default_model(self, provider: str) -> str:
        """Find the first model for a provider in the sequence."""
        for p, m in self._sequence:
            if p == provider:
                return m
        return "unknown"
