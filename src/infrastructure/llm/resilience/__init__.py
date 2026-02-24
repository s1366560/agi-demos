"""
LLM Provider Resilience Module.

This module provides resilience patterns for LLM provider management:
- CircuitBreaker: Automatic failure detection and recovery
- RateLimiter: Per-provider rate limiting
- HealthChecker: Periodic health monitoring

Example usage:
    from src.infrastructure.llm.resilience import (
        get_circuit_breaker_registry,
        get_provider_rate_limiter,
        get_health_checker,
    )

    # Get global instances
    circuit_breaker_registry = get_circuit_breaker_registry()
    rate_limiter = get_provider_rate_limiter()
    health_checker = get_health_checker()

    # Use circuit breaker
    breaker = circuit_breaker_registry.get(ProviderType.OPENAI)
    if breaker.can_execute():
        try:
            result = await llm_call()
            breaker.record_success()
        except Exception:
            breaker.record_failure()

    # Use rate limiter
    async with rate_limiter.acquire(ProviderType.OPENAI):
        result = await llm_call()

    # Check health
    status = await health_checker.get_health(ProviderType.OPENAI)
    if status.is_healthy:
        # Use provider
        pass
"""

from src.infrastructure.llm.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerRegistry,
    CircuitState,
    get_circuit_breaker_registry,
)
from src.infrastructure.llm.resilience.health_checker import (
    HealthCheckConfig,
    HealthChecker,
    HealthCheckResult,
    HealthStatus,
    get_health_checker,
    start_health_checker,
    stop_health_checker,
)
from src.infrastructure.llm.resilience.rate_limiter import (
    DEFAULT_RATE_LIMITS,
    ProviderRateLimiter,
    RateLimitConfig,
    RateLimitExceededError,
    RateLimitStats,
    get_provider_rate_limiter,
    reset_rate_limiter,
)

__all__ = [
    # Rate Limiter
    "DEFAULT_RATE_LIMITS",
    # Circuit Breaker
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitBreakerRegistry",
    "CircuitState",
    # Health Checker
    "HealthCheckConfig",
    "HealthCheckResult",
    "HealthChecker",
    "HealthStatus",
    "ProviderRateLimiter",
    "RateLimitConfig",
    "RateLimitExceededError",
    "RateLimitStats",
    "get_circuit_breaker_registry",
    "get_health_checker",
    "get_provider_rate_limiter",
    "reset_rate_limiter",
    "start_health_checker",
    "stop_health_checker",
]
