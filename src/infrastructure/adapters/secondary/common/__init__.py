"""
Common infrastructure components for database adapters.

This package provides shared functionality for all repository implementations:
- BaseRepository: Generic CRUD operations
- TransactionManager: Distributed transaction coordination
- QueryBuilder: Fluent query construction
- CachedRepositoryMixin: Redis caching integration
- Health Check: System health monitoring
- Retry Logic: Exponential backoff retry mechanism
- Circuit Breaker: Failure protection pattern
- Query Monitor: Performance tracking and optimization
"""

from src.infrastructure.adapters.secondary.common.base_repository import (
    BaseRepository,
    handle_db_errors,
    transactional,
)
from src.infrastructure.adapters.secondary.common.cached_repository_mixin import (
    CachedRepositoryMixin,
)
from src.infrastructure.adapters.secondary.common.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    CircuitState,
    get_circuit_breaker,
)
from src.infrastructure.adapters.secondary.common.health_check import (
    HealthCheckError,
    HealthStatus,
    Neo4jHealthChecker,
    PostgresHealthChecker,
    RedisHealthChecker,
    SystemHealthChecker,
)
from src.infrastructure.adapters.secondary.common.query_builder import QueryBuilder
from src.infrastructure.adapters.secondary.common.query_monitor import (
    QueryInfo,
    QueryMonitor,
    QueryMonitorConfig,
    QueryStats,
    SlowQueryError,
    get_query_monitor,
)
from src.infrastructure.adapters.secondary.common.retry import (
    MaxRetriesExceededError,
    TransientError,
    is_transient_error,
    retry_decorator,
    retry_with_backoff,
)
from src.infrastructure.adapters.secondary.common.transaction_manager import (
    TransactionManager,
)

__all__ = [
    # Repository patterns
    "BaseRepository",
    "CachedRepositoryMixin",
    # Circuit breaker
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitBreakerOpenError",
    "CircuitState",
    # Health check
    "HealthCheckError",
    "HealthStatus",
    "MaxRetriesExceededError",
    "Neo4jHealthChecker",
    "PostgresHealthChecker",
    "QueryBuilder",
    "QueryInfo",
    # Query monitoring
    "QueryMonitor",
    "QueryMonitorConfig",
    "QueryStats",
    "RedisHealthChecker",
    "SlowQueryError",
    "SystemHealthChecker",
    "TransactionManager",
    # Retry logic
    "TransientError",
    "get_circuit_breaker",
    "get_query_monitor",
    # Decorators
    "handle_db_errors",
    "is_transient_error",
    "retry_decorator",
    "retry_with_backoff",
    "transactional",
]
