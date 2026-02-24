"""
LLM Infrastructure Module.

Provides unified LLM provider management with resilience patterns,
caching, validation, and metrics collection.

Main Components:
- Resilience: CircuitBreaker, RateLimiter, HealthChecker
- Registry: ProviderAdapterRegistry for adapter management
- Cache: ResponseCache for LLM response caching
- Validation: StructuredOutputValidator for JSON validation with retry
- Metrics: MetricsCollector for operation tracking

Example:
    from src.infrastructure.llm import (
        get_provider_adapter_registry,
        get_response_cache,
        get_metrics_collector,
    )

    # Get a provider adapter
    registry = get_provider_adapter_registry()
    adapter = registry.create_adapter(provider_config)

    # Use caching
    cache = get_response_cache()
    cached = await cache.get(messages, model="gpt-4")

    # Track metrics
    collector = get_metrics_collector()
    with collector.track_request(ProviderType.OPENAI, "gpt-4") as tracker:
        response = await adapter.generate(messages)
        tracker.set_tokens(100, 50)
"""

# Resilience components
# Cache
from src.infrastructure.llm.cache import (
    CacheConfig,
    ResponseCache,
    get_response_cache,
)

# Metrics
from src.infrastructure.llm.metrics import (
    MetricsCollector,
    RequestTracker,
    estimate_cost,
    get_metrics_collector,
)

# Registry
from src.infrastructure.llm.registry import (
    ProviderAdapterRegistry,
    get_provider_adapter_registry,
)
from src.infrastructure.llm.resilience import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerRegistry,
    CircuitState,
    HealthCheckConfig,
    HealthChecker,
    HealthCheckResult,
    HealthStatus,
    ProviderRateLimiter,
    RateLimitConfig,
    RateLimitExceededError,
    get_circuit_breaker_registry,
    get_health_checker,
    get_provider_rate_limiter,
)

# Validation
from src.infrastructure.llm.validation import (
    StructuredOutputValidator,
    ValidationConfig,
    ValidationResult,
    get_structured_validator,
)

__all__ = [
    # Cache
    "CacheConfig",
    # Resilience
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitBreakerRegistry",
    "CircuitState",
    "HealthCheckConfig",
    "HealthCheckResult",
    "HealthChecker",
    "HealthStatus",
    # Metrics
    "MetricsCollector",
    # Registry
    "ProviderAdapterRegistry",
    "ProviderRateLimiter",
    "RateLimitConfig",
    "RateLimitExceededError",
    "RequestTracker",
    "ResponseCache",
    # Validation
    "StructuredOutputValidator",
    "ValidationConfig",
    "ValidationResult",
    "estimate_cost",
    "get_circuit_breaker_registry",
    "get_health_checker",
    "get_metrics_collector",
    "get_provider_adapter_registry",
    "get_provider_rate_limiter",
    "get_response_cache",
    "get_structured_validator",
]
