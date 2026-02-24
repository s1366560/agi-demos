"""
Query Performance Monitoring.

Provides:
- Slow query logging (>100ms threshold configurable)
- Query statistics tracking
- Performance dashboard data aggregation
"""

import asyncio
import hashlib
import logging
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SlowQueryError(Exception):
    """
    Raised when a query exceeds the slow query threshold.

    Attributes:
        query: The slow query text
        duration_ms: Query duration in milliseconds
        threshold_ms: The threshold that was exceeded
    """

    def __init__(self, query: str, duration_ms: float, threshold_ms: float):
        self.query = query
        self.duration_ms = duration_ms
        self.threshold_ms = threshold_ms
        super().__init__(f"Slow query detected: {duration_ms}ms > {threshold_ms}ms - {query[:100]}")


@dataclass
class QueryMonitorConfig:
    """
    Configuration for query monitoring.

    Attributes:
        slow_query_threshold_ms: Threshold for slow query logging
        max_query_history: Maximum number of queries to keep in history
        enable_logging: Enable query execution logging
        enable_statistics: Enable statistics collection
        log_slow_queries: Log slow queries separately
    """

    slow_query_threshold_ms: int = 100
    max_query_history: int = 1000
    enable_logging: bool = True
    enable_statistics: bool = True
    log_slow_queries: bool = True


@dataclass
class QueryInfo:
    """
    Information about a query execution.

    Attributes:
        query_hash: Hash of the query (for grouping)
        query_text: Full query text
        duration_ms: Execution time in milliseconds
        rows_affected: Number of rows affected
        timestamp: When the query was executed
        error: Error if query failed
    """

    query_hash: str
    query_text: str
    duration_ms: float
    rows_affected: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error: Optional[str] = None

    def is_slow(self, threshold_ms: int = 100) -> bool:
        """Check if query is slow."""
        return self.duration_ms >= threshold_ms

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "query_hash": self.query_hash,
            "query_text": self.query_text,
            "duration_ms": self.duration_ms,
            "rows_affected": self.rows_affected,
            "timestamp": self.timestamp.isoformat(),
            "error": self.error,
        }


class QueryStats:
    """
    Statistics for query executions.

    Tracks:
    - Total queries
    - Slow queries
    - Average/min/max duration
    - Percentiles
    """

    def __init__(self, threshold_ms: int = 100) -> None:
        """
        Initialize query statistics.

        Args:
            threshold_ms: Threshold for slow query detection
        """
        self._threshold_ms = threshold_ms
        self._total_queries: int = 0
        self._slow_queries: int = 0
        self._failed_queries: int = 0
        self._total_duration_ms: float = 0
        self._min_duration_ms: float = float("inf")
        self._max_duration_ms: float = 0
        self._durations: List[float] = []

    def record(self, duration_ms: float, failed: bool = False) -> None:
        """
        Record a query execution.

        Args:
            duration_ms: Query duration in milliseconds
            failed: Whether the query failed
        """
        self._total_queries += 1
        self._total_duration_ms += duration_ms
        self._min_duration_ms = min(self._min_duration_ms, duration_ms)
        self._max_duration_ms = max(self._max_duration_ms, duration_ms)
        self._durations.append(duration_ms)

        if duration_ms >= self._threshold_ms:
            self._slow_queries += 1

        if failed:
            self._failed_queries += 1

    @property
    def total_queries(self) -> int:
        return self._total_queries

    @property
    def slow_queries(self) -> int:
        return self._slow_queries

    @property
    def failed_queries(self) -> int:
        return self._failed_queries

    @property
    def total_duration_ms(self) -> float:
        return self._total_duration_ms

    @property
    def min_duration_ms(self) -> float:
        return self._min_duration_ms if self._total_queries > 0 else 0

    @property
    def max_duration_ms(self) -> float:
        return self._max_duration_ms

    @property
    def avg_duration_ms(self) -> float:
        return self._total_duration_ms / self._total_queries if self._total_queries > 0 else 0

    def percentile(self, p: int) -> float:
        """
        Calculate percentile of query durations.

        Args:
            p: Percentile to calculate (0-100)

        Returns:
            Duration at percentile p
        """
        if not self._durations:
            return 0

        sorted_durations = sorted(self._durations)
        index = int(len(sorted_durations) * p / 100)
        return sorted_durations[min(index, len(sorted_durations) - 1)]

    def reset(self) -> None:
        """Reset all statistics."""
        self._total_queries = 0
        self._slow_queries = 0
        self._failed_queries = 0
        self._total_duration_ms = 0
        self._min_duration_ms = float("inf")
        self._max_duration_ms = 0
        self._durations = []

    def to_dict(self) -> Dict[str, Any]:
        """Convert statistics to dictionary."""
        slow_percentage = (
            (self._slow_queries / self._total_queries * 100) if self._total_queries > 0 else 0
        )
        return {
            "total_queries": self._total_queries,
            "slow_queries": self._slow_queries,
            "failed_queries": self._failed_queries,
            "slow_query_percentage": round(slow_percentage, 2),
            "total_duration_ms": round(self._total_duration_ms, 2),
            "min_duration_ms": round(self._min_duration_ms, 2),
            "max_duration_ms": round(self._max_duration_ms, 2),
            "avg_duration_ms": round(self.avg_duration_ms, 2),
            "p50_duration_ms": round(self.percentile(50), 2),
            "p95_duration_ms": round(self.percentile(95), 2),
            "p99_duration_ms": round(self.percentile(99), 2),
        }


class QueryMonitor:
    """
    Monitor and track query performance.

    Features:
    - Track all queries with timing
    - Log slow queries
    - Calculate statistics
    - Provide dashboard data

    Example:
        monitor = QueryMonitor(name="user_queries")

        async with monitor.track("get_user"):
            result = await db.execute(query)

        stats = monitor.get_statistics()
    """

    def __init__(
        self,
        name: str,
        config: Optional[QueryMonitorConfig] = None,
    ) -> None:
        """
        Initialize query monitor.

        Args:
            name: Monitor name (for identification)
            config: Monitor configuration
        """
        self._name = name
        self._config = config or QueryMonitorConfig()
        self._stats = QueryStats(threshold_ms=self._config.slow_query_threshold_ms)
        self._query_history: List[QueryInfo] = []
        self._query_counts: Dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()

    @property
    def name(self) -> str:
        """Get monitor name."""
        return self._name

    @property
    def config(self) -> QueryMonitorConfig:
        """Get monitor configuration."""
        return self._config

    @property
    def stats(self) -> QueryStats:
        """Get query statistics."""
        return self._stats

    @property
    def query_history(self) -> List[QueryInfo]:
        """Get query history."""
        return list(self._query_history)

    def _generate_hash(self, query_text: str) -> str:
        """
        Generate hash for query text.

        Normalizes whitespace and parameter values for grouping.

        Args:
            query_text: SQL query text

        Returns:
            Hash string
        """
        # Normalize whitespace
        normalized = " ".join(query_text.split())
        # Simple hash for grouping similar queries
        return hashlib.md5(normalized.encode()).hexdigest()[:16]

    async def execute(
        self,
        session: Any,  # noqa: ANN401
        query: Any,  # noqa: ANN401
        params: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[float] = None,
    ) -> Any:  # noqa: ANN401
        """
        Execute and monitor a query.

        Args:
            session: Database session
            query: SQL query
            params: Query parameters
            duration_ms: Pre-calculated duration (for testing)

        Returns:
            Query result

        Raises:
            Exception: If query execution fails
        """
        start_time = time.time()
        query_text = str(query)
        query_hash = self._generate_hash(query_text)

        try:
            # Execute query
            result = await session.execute(query, params or {})

            # Calculate duration
            actual_duration_ms = duration_ms or (time.time() - start_time) * 1000

            # Record query info
            await self._record_query(
                query_hash=query_hash,
                query_text=query_text,
                duration_ms=actual_duration_ms,
                error=None,
            )

            return result

        except Exception as e:
            # Record failed query
            actual_duration_ms = duration_ms or (time.time() - start_time) * 1000

            await self._record_query(
                query_hash=query_hash,
                query_text=query_text,
                duration_ms=actual_duration_ms,
                error=str(e),
            )

            raise

    async def _record_query(
        self,
        query_hash: str,
        query_text: str,
        duration_ms: float,
        error: Optional[str] = None,
    ) -> None:
        """
        Record query execution information.

        Args:
            query_hash: Hash of the query
            query_text: Full query text
            duration_ms: Execution time
            error: Error if failed
        """
        async with self._lock:
            # Create query info
            query_info = QueryInfo(
                query_hash=query_hash,
                query_text=query_text,
                duration_ms=duration_ms,
                error=error,
            )

            # Add to history
            self._query_history.append(query_info)

            # Trim history if needed
            if len(self._query_history) > self._config.max_query_history:
                self._query_history = self._query_history[-self._config.max_query_history :]

            # Update statistics
            self._stats.record(duration_ms, failed=error is not None)

            # Update query counts
            self._query_counts[query_hash] += 1

            # Log slow query
            if self._config.log_slow_queries and query_info.is_slow(
                self._config.slow_query_threshold_ms
            ):
                logger.warning(
                    f"Slow query in '{self._name}': {duration_ms:.2f}ms - {query_text[:200]}"
                )

    def get_slow_queries(
        self,
        threshold_ms: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> List[QueryInfo]:
        """
        Get list of slow queries.

        Args:
            threshold_ms: Override threshold (uses config default if None)
            limit: Max number of queries to return

        Returns:
            List of slow queries
        """
        threshold = threshold_ms or self._config.slow_query_threshold_ms

        slow_queries = [q for q in self._query_history if q.is_slow(threshold)]

        # Sort by duration (slowest first)
        slow_queries.sort(key=lambda q: q.duration_ms, reverse=True)

        if limit:
            slow_queries = slow_queries[:limit]

        return slow_queries

    def get_slowest_queries(self, limit: int = 10) -> List[QueryInfo]:
        """
        Get the slowest queries.

        Args:
            limit: Max number of queries to return

        Returns:
            List of slowest queries
        """
        queries = sorted(self._query_history, key=lambda q: q.duration_ms, reverse=True)
        return queries[:limit]

    def get_most_frequent_queries(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get most frequently executed queries.

        Args:
            limit: Max number of queries to return

        Returns:
            List of queries with execution counts
        """
        # Group by hash
        query_groups: Dict[str, Dict[str, Any]] = {}

        for q in self._query_history:
            if q.query_hash not in query_groups:
                query_groups[q.query_hash] = {
                    "query_text": q.query_text,
                    "query_hash": q.query_hash,
                    "count": 0,
                    "total_duration_ms": 0,
                    "avg_duration_ms": 0,
                }

            group = query_groups[q.query_hash]
            group["count"] += 1
            group["total_duration_ms"] += q.duration_ms

        # Calculate averages and sort
        for group in query_groups.values():
            group["avg_duration_ms"] = group["total_duration_ms"] / group["count"]

        # Sort by count (most frequent first)
        result = sorted(query_groups.values(), key=lambda x: x["count"], reverse=True)

        return result[:limit]

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get aggregated statistics.

        Returns:
            Dictionary of statistics
        """
        return self._stats.to_dict()

    def get_dashboard_data(self) -> Dict[str, Any]:
        """
        Get data for performance dashboard.

        Returns:
            Dictionary with dashboard data
        """
        return {
            "monitor": self._name,
            "overview": {
                "total_queries": self._stats.total_queries,
                "slow_queries": self._stats.slow_queries,
                "failed_queries": self._stats.failed_queries,
                "avg_duration_ms": round(self._stats.avg_duration_ms, 2),
            },
            "slow_queries": [q.to_dict() for q in self.get_slowest_queries(5)],
            "frequent_queries": self.get_most_frequent_queries(5),
            "statistics": self._stats.to_dict(),
        }

    def reset(self) -> None:
        """Reset all statistics and history."""
        self._stats.reset()
        self._query_history = []
        self._query_counts = defaultdict(int)

    @contextmanager
    def track(self, operation: str):
        """
        Context manager for tracking operation timing.

        Args:
            operation: Name of the operation

        Yields:
            Tracker with record() method

        Example:
            with monitor.track("user_lookup") as tracker:
                result = await lookup_user(user_id)
                tracker.record(rows=1)
        """
        start_time = time.time()
        query_text = f"Operation: {operation}"

        class Tracker:
            def __init__(self, monitor_obj: QueryMonitor, query: str, start: float):
                self._monitor = monitor_obj
                self._query = query
                self._start = start

            def record(self, rows: int = 0) -> None:
                """Record operation completion."""
                duration_ms = (time.time() - self._start) * 1000
                # Create sync task for recording
                asyncio.create_task(
                    self._monitor._record_query(
                        query_hash=self._monitor._generate_hash(self._query),
                        query_text=self._query,
                        duration_ms=duration_ms,
                        error=None,
                    )
                )

        yield Tracker(self, query_text, start_time)


class QueryMonitorRegistry:
    """
    Registry for managing multiple query monitors.

    Provides centralized access to monitors by name.
    """

    def __init__(self) -> None:
        self._monitors: Dict[str, QueryMonitor] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(
        self,
        name: str,
        config: Optional[QueryMonitorConfig] = None,
    ) -> QueryMonitor:
        """
        Get existing monitor or create new one.

        Args:
            name: Monitor name
            config: Configuration for new monitor

        Returns:
            QueryMonitor instance
        """
        async with self._lock:
            if name not in self._monitors:
                self._monitors[name] = QueryMonitor(name, config)
            return self._monitors[name]

    async def get(self, name: str) -> Optional[QueryMonitor]:
        """
        Get monitor by name.

        Args:
            name: Monitor name

        Returns:
            QueryMonitor instance or None
        """
        async with self._lock:
            return self._monitors.get(name)

    async def get_all_dashboard_data(self) -> Dict[str, Any]:
        """Get dashboard data for all monitors."""
        async with self._lock:
            return {name: monitor.get_dashboard_data() for name, monitor in self._monitors.items()}

    async def reset_all(self) -> None:
        """Reset all monitors."""
        async with self._lock:
            for monitor in self._monitors.values():
                monitor.reset()


# Global monitor registry
_global_monitor_registry = QueryMonitorRegistry()


async def get_query_monitor(
    name: str,
    config: Optional[QueryMonitorConfig] = None,
) -> QueryMonitor:
    """Get or create query monitor from global registry."""
    return await _global_monitor_registry.get_or_create(name, config)
