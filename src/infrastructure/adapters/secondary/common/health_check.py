"""
Health Check System for infrastructure components.

Provides health monitoring for:
- PostgreSQL database
- Neo4j graph database
- Redis cache

Each health checker returns a HealthStatus with:
- Service name
- Healthy status (True/False)
- Message describing status
- Latency in milliseconds
- Additional details (version, etc.)
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from neo4j import AsyncDriver
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


class HealthCheckError(Exception):
    """Exception raised when a critical health check fails."""

    def __init__(self, message: str, service: str | None = None) -> None:
        super().__init__(message)
        self.service = service
        self.message = message


@dataclass
class HealthStatus:
    """
    Status result from a health check.

    Attributes:
        service: Name of the service being checked
        healthy: True if service is healthy, False otherwise
        message: Human-readable status message
        latency_ms: Time taken for health check in milliseconds
        details: Additional service-specific details
        timestamp: When the health check was performed
    """

    service: str
    healthy: bool
    message: str
    latency_ms: float
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convert health status to dictionary."""
        return {
            "service": self.service,
            "healthy": self.healthy,
            "message": self.message,
            "latency_ms": self.latency_ms,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
        }


class PostgresHealthChecker:
    """
    Health checker for PostgreSQL database.

    Uses a simple SELECT 1 query to verify connectivity.
    Can be configured with a custom query for more thorough checks.
    """

    def __init__(
        self,
        engine: AsyncEngine,
        query: str = "SELECT 1",
        timeout: float = 5.0,
    ) -> None:
        """
        Initialize PostgreSQL health checker.

        Args:
            engine: SQLAlchemy engine instance
            query: Health check query (default: SELECT 1)
            timeout: Query timeout in seconds
        """
        self._engine = engine
        self._query = query
        self._timeout = timeout

    async def check(self) -> HealthStatus:
        """
        Perform health check on PostgreSQL.

        Returns:
            HealthStatus with check results
        """
        start_time = time.time()
        details: dict[str, Any] = {}

        try:
            async with asyncio.timeout(self._timeout):
                async with self._engine.connect() as conn:
                    result = await conn.execute(self._query)
                    value = result.scalar()

            latency_ms = (time.time() - start_time) * 1000

            # Try to get version information
            try:
                async with self._engine.connect() as conn:
                    version_result = await conn.execute("SELECT version()")
                    version = version_result.scalar()
                    details["version"] = version.split()[1] if version else "unknown"
            except Exception:
                details["version"] = "unknown"

            # Check if custom query was used
            if self._query != "SELECT 1":
                details["custom_query"] = True
                details["query_result"] = value

            return HealthStatus(
                service="postgres",
                healthy=True,
                message="PostgreSQL connection healthy",
                latency_ms=latency_ms,
                details=details,
            )

        except TimeoutError:
            latency_ms = (time.time() - start_time) * 1000
            return HealthStatus(
                service="postgres",
                healthy=False,
                message=f"PostgreSQL health check timeout after {self._timeout}s",
                latency_ms=latency_ms,
            )

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            logger.warning(f"PostgreSQL health check failed: {e}")
            return HealthStatus(
                service="postgres",
                healthy=False,
                message=f"PostgreSQL health check failed: {e!s}",
                latency_ms=latency_ms,
            )


class RedisHealthChecker:
    """
    Health checker for Redis cache.

    Uses PING command to verify connectivity.
    Also retrieves Redis INFO for version details.
    """

    def __init__(
        self,
        redis: Redis,
        timeout: float = 2.0,
    ) -> None:
        """
        Initialize Redis health checker.

        Args:
            redis: Redis client instance (async)
            timeout: Query timeout in seconds
        """
        self._redis = redis
        self._timeout = timeout

    async def check(self) -> HealthStatus:
        """
        Perform health check on Redis.

        Returns:
            HealthStatus with check results
        """
        start_time = time.time()
        details: dict[str, Any] = {}

        try:
            async with asyncio.timeout(self._timeout):
                # Use PING command
                pong = await self._redis.ping()

            if not pong:
                latency_ms = (time.time() - start_time) * 1000
                return HealthStatus(
                    service="redis",
                    healthy=False,
                    message="Redis PING failed",
                    latency_ms=latency_ms,
                )

            latency_ms = (time.time() - start_time) * 1000

            # Try to get version information
            try:
                info = await self._redis.info()
                details["version"] = info.get("redis_version", "unknown")
                details["connected_clients"] = info.get("connected_clients", 0)
            except Exception:
                # INFO failed but PING succeeded, still healthy
                details["version"] = "unknown"

            return HealthStatus(
                service="redis",
                healthy=True,
                message="Redis connection healthy",
                latency_ms=latency_ms,
                details=details,
            )

        except TimeoutError:
            latency_ms = (time.time() - start_time) * 1000
            return HealthStatus(
                service="redis",
                healthy=False,
                message=f"Redis health check timeout after {self._timeout}s",
                latency_ms=latency_ms,
            )

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            logger.warning(f"Redis health check failed: {e}")
            return HealthStatus(
                service="redis",
                healthy=False,
                message=f"Redis health check failed: {e!s}",
                latency_ms=latency_ms,
            )


class Neo4jHealthChecker:
    """
    Health checker for Neo4j graph database.

    Uses verify_connectivity and a simple Cypher query.
    """

    def __init__(
        self,
        driver: AsyncDriver,
        query: str = "RETURN 1",
        timeout: float = 5.0,
    ) -> None:
        """
        Initialize Neo4j health checker.

        Args:
            driver: Neo4j driver instance
            query: Cypher query for health check
            timeout: Query timeout in seconds
        """
        self._driver = driver
        self._query = query
        self._timeout = timeout

    async def check(self) -> HealthStatus:
        """
        Perform health check on Neo4j.

        Returns:
            HealthStatus with check results
        """
        start_time = time.time()
        details: dict[str, Any] = {}

        try:
            # Verify connectivity (may be sync or async)
            verify_fn = self._driver.verify_connectivity
            if asyncio.iscoroutinefunction(verify_fn):
                async with asyncio.timeout(self._timeout):
                    await verify_fn()
            else:
                verify_fn()

            # Execute simple query (may be sync or async)
            execute_fn = self._driver.execute_query
            if asyncio.iscoroutinefunction(execute_fn):
                async with asyncio.timeout(self._timeout):
                    result, summary = await execute_fn(self._query)
            else:
                result, summary = execute_fn(self._query)

            latency_ms = (time.time() - start_time) * 1000

            # Get version from result if available
            if hasattr(result, "records") and result.records:
                details["query_result"] = result.records[0]

            # Check if custom query was used
            if self._query != "RETURN 1":
                details["custom_query"] = True

            # Add server info if available
            if hasattr(summary, "server"):
                details["server"] = str(summary.server)

            return HealthStatus(
                service="neo4j",
                healthy=True,
                message="Neo4j connection healthy",
                latency_ms=latency_ms,
                details=details,
            )

        except TimeoutError:
            latency_ms = (time.time() - start_time) * 1000
            return HealthStatus(
                service="neo4j",
                healthy=False,
                message=f"Neo4j health check timeout after {self._timeout}s",
                latency_ms=latency_ms,
            )

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            logger.warning(f"Neo4j health check failed: {e}")
            return HealthStatus(
                service="neo4j",
                healthy=False,
                message=f"Neo4j health check failed: {e!s}",
                latency_ms=latency_ms,
            )


class SystemHealthChecker:
    """
    Aggregated health checker for all system components.

    Runs health checks in parallel and returns aggregated status.
    """

    def __init__(
        self,
        postgres: PostgresHealthChecker | None = None,
        redis: RedisHealthChecker | None = None,
        neo4j: Neo4jHealthChecker | None = None,
    ) -> None:
        """
        Initialize system health checker.

        Args:
            postgres: PostgreSQL health checker
            redis: Redis health checker
            neo4j: Neo4j health checker
        """
        self._postgres = postgres
        self._redis = redis
        self._neo4j = neo4j

    async def check_all(self) -> HealthStatus:
        """
        Check health of all configured services.

        Returns:
            HealthStatus with aggregated results
        """
        checks: dict[str, HealthStatus] = {}
        tasks = []

        # Collect and run all configured health checks
        if self._postgres:
            tasks.append(("postgres", self._postgres.check()))
        if self._redis:
            tasks.append(("redis", self._redis.check()))
        if self._neo4j:
            tasks.append(("neo4j", self._neo4j.check()))

        # Run checks in parallel
        if tasks:
            results = await asyncio.gather(
                *[task for _, task in tasks],
                return_exceptions=True,
            )

            for (name, _), result in zip(tasks, results, strict=False):
                if isinstance(result, Exception):
                    checks[name] = HealthStatus(
                        service=name,
                        healthy=False,
                        message=f"Health check error: {result!s}",
                        latency_ms=0,
                    )
                else:
                    checks[name] = result

        # Determine overall health
        all_healthy = all(status.healthy for status in checks.values())
        unhealthy_services = [name for name, status in checks.items() if not status.healthy]

        if all_healthy:
            message = "All services healthy"
        else:
            message = f"Unhealthy services: {', '.join(unhealthy_services)}"

        return HealthStatus(
            service="system",
            healthy=all_healthy,
            message=message,
            latency_ms=max((s.latency_ms for s in checks.values()), default=0),
            details={"checks": {name: s.to_dict() for name, s in checks.items()}},
        )

    async def check_service(self, service: str) -> HealthStatus:
        """
        Check health of a specific service.

        Args:
            service: Service name (postgres, redis, neo4j)

        Returns:
            HealthStatus for the requested service

        Raises:
            ValueError: If service is not configured
        """
        checkers = {
            "postgres": self._postgres,
            "redis": self._redis,
            "neo4j": self._neo4j,
        }

        checker = checkers.get(service)
        if checker is None:
            raise ValueError(f"Unknown service: {service}")

        return await checker.check()

    def to_dict(self, status: HealthStatus) -> dict[str, Any]:
        """
        Convert health status to dictionary (alias for to_dict).

        Args:
            status: HealthStatus to convert

        Returns:
            Dictionary representation
        """
        return status.to_dict()
