"""
Unit tests for Health Check System.

Tests the health check functionality for:
- PostgreSQL health check
- Neo4j health check
- Redis health check
- Aggregate health status
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.adapters.secondary.common.health_check import (
    HealthCheckError,
    HealthStatus,
    Neo4jHealthChecker,
    PostgresHealthChecker,
    RedisHealthChecker,
    SystemHealthChecker,
)


class TestPostgresHealthChecker:
    """Tests for PostgreSQL health checker."""

    @pytest.fixture
    def mock_engine(self):
        """Create a mock database engine."""
        engine = MagicMock()
        engine.connect = MagicMock()
        return engine

    @pytest.fixture
    def mock_connection(self):
        """Create a mock database connection."""
        conn = AsyncMock()
        conn.execute = AsyncMock()
        conn.close = AsyncMock()
        return conn

    @pytest.fixture
    def checker(self, mock_engine):
        """Create a PostgresHealthChecker instance."""
        return PostgresHealthChecker(engine=mock_engine)

    async def test_health_check_success(self, checker, mock_engine, mock_connection):
        """Test successful health check."""
        # Setup: Mock successful connection and query
        mock_engine.connect.return_value.__aenter__.return_value = mock_connection
        mock_connection.execute.return_value.scalar.return_value = 1

        # Execute
        result = await checker.check()

        # Assert
        assert result.healthy is True
        assert result.service == "postgres"
        assert result.latency_ms >= 0
        assert result.message == "PostgreSQL connection healthy"
        assert result.details["version"] is not None

    async def test_health_check_connection_failure(self, checker, mock_engine):
        """Test health check with connection failure."""
        # Setup: Mock connection failure
        mock_engine.connect.side_effect = Exception("Connection refused")

        # Execute
        result = await checker.check()

        # Assert
        assert result.healthy is False
        assert result.service == "postgres"
        assert "Connection refused" in result.message or "failed" in result.message.lower()

    async def test_health_check_query_failure(self, checker, mock_engine, mock_connection):
        """Test health check with query execution failure."""
        # Setup: Mock query failure
        mock_engine.connect.return_value.__aenter__.return_value = mock_connection
        mock_connection.execute.side_effect = Exception("Query timeout")

        # Execute
        result = await checker.check()

        # Assert
        assert result.healthy is False
        assert "Query timeout" in result.message or "failed" in result.message.lower()

    async def test_health_check_with_custom_query(self, mock_engine, mock_connection):
        """Test health check with custom query."""
        # Setup
        mock_engine.connect.return_value.__aenter__.return_value = mock_connection
        mock_connection.execute.return_value.scalar.return_value = 5

        checker = PostgresHealthChecker(engine=mock_engine, query="SELECT COUNT(*) FROM users")

        # Execute
        result = await checker.check()

        # Assert
        assert result.healthy is True
        assert result.details["custom_query"] is True

    async def test_health_check_timeout(self, checker, mock_engine):
        """Test health check respects timeout."""

        # Setup: Mock timeout
        async def slow_connect():
            import asyncio

            await asyncio.sleep(2)  # Longer than timeout

        mock_engine.connect.side_effect = slow_connect

        checker = PostgresHealthChecker(engine=mock_engine, timeout=0.1)

        # Execute
        result = await checker.check()

        # Assert - should handle timeout gracefully
        assert result.healthy is False


class TestRedisHealthChecker:
    """Tests for Redis health checker."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        redis = AsyncMock()
        redis.ping = AsyncMock()
        redis.info = AsyncMock()
        return redis

    @pytest.fixture
    def checker(self, mock_redis):
        """Create a RedisHealthChecker instance."""
        return RedisHealthChecker(redis=mock_redis)

    async def test_health_check_success(self, checker, mock_redis):
        """Test successful health check."""
        # Setup
        mock_redis.ping.return_value = True
        mock_redis.info.return_value = {
            "redis_version": "7.0.0",
            "connected_clients": 10,
            "used_memory": "1024",
        }

        # Execute
        result = await checker.check()

        # Assert
        assert result.healthy is True
        assert result.service == "redis"
        assert result.latency_ms >= 0
        assert result.message == "Redis connection healthy"
        assert result.details["version"] == "7.0.0"

    async def test_health_check_ping_failure(self, checker, mock_redis):
        """Test health check when PING fails."""
        # Setup
        mock_redis.ping.return_value = False
        mock_redis.info.side_effect = Exception("Connection lost")

        # Execute
        result = await checker.check()

        # Assert
        assert result.healthy is False
        assert "ping failed" in result.message.lower() or "failed" in result.message.lower()

    async def test_health_check_exception(self, checker, mock_redis):
        """Test health check with exception."""
        # Setup
        mock_redis.ping.side_effect = Exception("Redis connection refused")

        # Execute
        result = await checker.check()

        # Assert
        assert result.healthy is False
        assert "Redis connection refused" in result.message

    async def test_health_check_without_info(self, checker, mock_redis):
        """Test health check when INFO fails but PING succeeds."""
        # Setup
        mock_redis.ping.return_value = True
        mock_redis.info.side_effect = Exception("INFO command not available")

        # Execute
        result = await checker.check()

        # Assert - Should still be healthy if PING succeeds
        assert result.healthy is True
        # Version is set to 'unknown' when INFO fails
        assert result.details.get("version") == "unknown"


class TestNeo4jHealthChecker:
    """Tests for Neo4j health checker."""

    @pytest.fixture
    def mock_driver(self):
        """Create a mock Neo4j driver."""
        driver = MagicMock()
        # verify_connectivity can be sync or async depending on driver version
        driver.verify_connectivity = MagicMock(return_value=None)
        # execute_query returns (result, summary) tuple
        driver.execute_query = MagicMock()
        return driver

    @pytest.fixture
    def checker(self, mock_driver):
        """Create a Neo4jHealthChecker instance."""
        return Neo4jHealthChecker(driver=mock_driver)

    async def test_health_check_success(self, checker, mock_driver):
        """Test successful health check."""
        # Setup
        mock_result = MagicMock()
        mock_result.records = [{"version": "5.26.0"}]
        mock_summary = MagicMock()
        mock_summary.result_available_after = 50
        mock_result.__iter__.return_value = iter(mock_result.records)
        mock_driver.execute_query.return_value = (mock_result, mock_summary)

        # Execute
        result = await checker.check()

        # Assert
        assert result.healthy is True
        assert result.service == "neo4j"
        assert result.latency_ms >= 0
        assert result.message == "Neo4j connection healthy"

    async def test_health_check_verify_failure(self, checker, mock_driver):
        """Test health check when verify_connectivity fails."""
        # Setup
        mock_driver.verify_connectivity.side_effect = Exception("Neo4j unavailable")

        # Execute
        result = await checker.check()

        # Assert
        assert result.healthy is False
        assert "Neo4j unavailable" in result.message

    async def test_health_check_query_failure(self, checker, mock_driver):
        """Test health check when query fails after successful connection."""
        # Setup
        mock_driver.execute_query.side_effect = Exception("Query failed")

        # Execute
        result = await checker.check()

        # Assert
        assert result.healthy is False
        assert "Query failed" in result.message

    async def test_health_check_with_custom_query(self, mock_driver):
        """Test health check with custom Cypher query."""
        # Setup
        mock_result = MagicMock()
        mock_result.records = [{"count": 42}]
        mock_summary = MagicMock()
        mock_summary.result_available_after = 30
        mock_result.__iter__.return_value = iter(mock_result.records)
        mock_driver.execute_query.return_value = (mock_result, mock_summary)

        checker = Neo4jHealthChecker(driver=mock_driver, query="RETURN count(*) AS count")

        # Execute
        result = await checker.check()

        # Assert
        assert result.healthy is True
        assert result.details.get("custom_query") is True


class TestSystemHealthChecker:
    """Tests for system-wide health checker."""

    @pytest.fixture
    def mock_postgres_checker(self):
        """Create a mock PostgreSQL checker."""
        checker = AsyncMock()
        checker.check.return_value = HealthStatus(
            service="postgres",
            healthy=True,
            message="PostgreSQL OK",
            latency_ms=10,
        )
        return checker

    @pytest.fixture
    def mock_redis_checker(self):
        """Create a mock Redis checker."""
        checker = AsyncMock()
        checker.check.return_value = HealthStatus(
            service="redis",
            healthy=True,
            message="Redis OK",
            latency_ms=5,
        )
        return checker

    @pytest.fixture
    def mock_neo4j_checker(self):
        """Create a mock Neo4j checker."""
        checker = AsyncMock()
        checker.check.return_value = HealthStatus(
            service="neo4j",
            healthy=True,
            message="Neo4j OK",
            latency_ms=15,
        )
        return checker

    @pytest.fixture
    def system_checker(
        self,
        mock_postgres_checker,
        mock_redis_checker,
        mock_neo4j_checker,
    ):
        """Create a SystemHealthChecker instance."""
        return SystemHealthChecker(
            postgres=mock_postgres_checker,
            redis=mock_redis_checker,
            neo4j=mock_neo4j_checker,
        )

    async def test_all_healthy(self, system_checker):
        """Test when all services are healthy."""
        # Execute
        result = await system_checker.check_all()

        # Assert
        assert result.healthy is True
        assert result.service == "system"
        # Checks are in details["checks"]
        checks = result.details.get("checks", {})
        assert len(checks) == 3
        assert checks["postgres"]["healthy"] is True
        assert checks["redis"]["healthy"] is True
        assert checks["neo4j"]["healthy"] is True

    async def test_postgres_unhealthy(self, system_checker, mock_postgres_checker):
        """Test when PostgreSQL is unhealthy."""
        # Setup
        mock_postgres_checker.check.return_value = HealthStatus(
            service="postgres",
            healthy=False,
            message="PostgreSQL down",
            latency_ms=0,
        )

        # Execute
        result = await system_checker.check_all()

        # Assert
        assert result.healthy is False
        checks = result.details.get("checks", {})
        assert checks["postgres"]["healthy"] is False
        assert "PostgreSQL down" in checks["postgres"]["message"]

    async def test_redis_unhealthy(self, system_checker, mock_redis_checker):
        """Test when Redis is unhealthy."""
        # Setup
        mock_redis_checker.check.return_value = HealthStatus(
            service="redis",
            healthy=False,
            message="Redis down",
            latency_ms=0,
        )

        # Execute
        result = await system_checker.check_all()

        # Assert
        assert result.healthy is False
        checks = result.details.get("checks", {})
        assert checks["redis"]["healthy"] is False

    async def test_neo4j_unhealthy(self, system_checker, mock_neo4j_checker):
        """Test when Neo4j is unhealthy."""
        # Setup
        mock_neo4j_checker.check.return_value = HealthStatus(
            service="neo4j",
            healthy=False,
            message="Neo4j down",
            latency_ms=0,
        )

        # Execute
        result = await system_checker.check_all()

        # Assert
        assert result.healthy is False
        checks = result.details.get("checks", {})
        assert checks["neo4j"]["healthy"] is False

    async def test_multiple_unhealthy(
        self, system_checker, mock_postgres_checker, mock_redis_checker
    ):
        """Test when multiple services are unhealthy."""
        # Setup
        mock_postgres_checker.check.return_value = HealthStatus(
            service="postgres",
            healthy=False,
            message="PostgreSQL down",
            latency_ms=0,
        )
        mock_redis_checker.check.return_value = HealthStatus(
            service="redis",
            healthy=False,
            message="Redis down",
            latency_ms=0,
        )

        # Execute
        result = await system_checker.check_all()

        # Assert
        assert result.healthy is False
        checks = result.details.get("checks", {})
        assert checks["postgres"]["healthy"] is False
        assert checks["redis"]["healthy"] is False
        assert checks["neo4j"]["healthy"] is True

    async def test_check_specific_service(self, system_checker):
        """Test checking a specific service only."""
        # Execute
        result = await system_checker.check_service("postgres")

        # Assert
        assert result.healthy is True
        assert result.service == "postgres"

    async def test_check_unknown_service(self, system_checker):
        """Test checking an unknown service."""
        # Execute and Assert
        with pytest.raises(ValueError, match="Unknown service"):
            await system_checker.check_service("unknown")

    async def test_parallel_execution(
        self, system_checker, mock_postgres_checker, mock_redis_checker, mock_neo4j_checker
    ):
        """Test that health checks run in parallel."""

        # Setup: Make checks take some time
        async def slow_check(service_name):
            import asyncio

            await asyncio.sleep(0.1)
            return HealthStatus(
                service=service_name,
                healthy=True,
                message=f"{service_name} OK",
                latency_ms=100,
            )

        mock_postgres_checker.check = lambda: slow_check("postgres")
        mock_redis_checker.check = lambda: slow_check("redis")
        mock_neo4j_checker.check = lambda: slow_check("neo4j")

        # Execute
        import time

        start = time.time()
        result = await system_checker.check_all()
        elapsed = time.time() - start

        # Assert - Should complete in ~0.1s if parallel, ~0.3s if sequential
        assert elapsed < 0.2  # Allow some margin
        assert result.healthy is True

    async def test_get_health_dict(self, system_checker):
        """Test getting health status as dict."""
        # Execute
        result = await system_checker.check_all()
        health_dict = result.to_dict()

        # Assert
        assert health_dict["healthy"] is True
        assert health_dict["service"] == "system"
        assert "timestamp" in health_dict
        # Checks are in details["checks"]
        assert "checks" in health_dict["details"]
        assert isinstance(health_dict["timestamp"], str)


class TestHealthStatus:
    """Tests for HealthStatus data class."""

    def test_health_status_creation(self):
        """Test creating a health status."""
        status = HealthStatus(
            service="test",
            healthy=True,
            message="OK",
            latency_ms=100,
            details={"key": "value"},
        )

        assert status.service == "test"
        assert status.healthy is True
        assert status.message == "OK"
        assert status.latency_ms == 100
        assert status.details == {"key": "value"}

    def test_to_dict(self):
        """Test converting health status to dict."""
        status = HealthStatus(
            service="test",
            healthy=True,
            message="OK",
            latency_ms=100,
        )

        result = status.to_dict()

        assert result["service"] == "test"
        assert result["healthy"] is True
        assert result["message"] == "OK"
        assert result["latency_ms"] == 100
        assert "timestamp" in result
        assert isinstance(result["timestamp"], str)

    def test_to_dict_with_details(self):
        """Test converting health status with details to dict."""
        status = HealthStatus(
            service="test",
            healthy=False,
            message="Error",
            latency_ms=0,
            details={"error": "Connection failed"},
        )

        result = status.to_dict()

        assert result["details"]["error"] == "Connection failed"


class TestHealthCheckError:
    """Tests for HealthCheckError exception."""

    def test_health_check_error_creation(self):
        """Test creating a health check error."""
        error = HealthCheckError("Service unavailable", service="postgres")

        assert str(error) == "Service unavailable"
        assert error.service == "postgres"

    def test_health_check_error_without_service(self):
        """Test creating a health check error without service."""
        error = HealthCheckError("Generic error")

        assert str(error) == "Generic error"
        assert error.service is None
