"""
Metrics collection for LLM providers.

Provides comprehensive metrics tracking for LLM operations including:
- Request counts and latencies
- Token usage and costs
- Error rates and types
- Provider health metrics

Example:
    collector = get_metrics_collector()

    # Record a request
    with collector.track_request(ProviderType.OPENAI, "gpt-4") as tracker:
        response = await llm_client.generate(messages)
        tracker.set_tokens(prompt_tokens=100, completion_tokens=50)

    # Get metrics
    metrics = collector.get_metrics()
"""

import logging
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import Lock
from typing import Any, Generator, Optional

from src.domain.llm_providers.models import ProviderType

logger = logging.getLogger(__name__)


class MetricType(str, Enum):
    """Types of metrics tracked."""

    REQUEST_COUNT = "request_count"
    SUCCESS_COUNT = "success_count"
    ERROR_COUNT = "error_count"
    LATENCY_MS = "latency_ms"
    PROMPT_TOKENS = "prompt_tokens"
    COMPLETION_TOKENS = "completion_tokens"
    TOTAL_TOKENS = "total_tokens"
    COST_USD = "cost_usd"


@dataclass
class RequestMetrics:
    """Metrics for a single request."""

    provider: ProviderType
    model: str
    start_time: float
    end_time: Optional[float] = None
    success: bool = False
    error_type: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def latency_ms(self) -> float:
        """Calculate request latency in milliseconds."""
        if self.end_time is None:
            return 0.0
        return (self.end_time - self.start_time) * 1000

    @property
    def total_tokens(self) -> int:
        """Calculate total tokens used."""
        return self.prompt_tokens + self.completion_tokens


@dataclass
class AggregatedMetrics:
    """Aggregated metrics for a time window."""

    request_count: int = 0
    success_count: int = 0
    error_count: int = 0
    total_latency_ms: float = 0.0
    min_latency_ms: float = float("inf")
    max_latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_cost_usd: float = 0.0
    error_types: dict[str, int] = field(default_factory=dict)
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: Optional[datetime] = None

    @property
    def avg_latency_ms(self) -> float:
        """Calculate average latency."""
        if self.request_count == 0:
            return 0.0
        return self.total_latency_ms / self.request_count

    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        if self.request_count == 0:
            return 0.0
        return self.success_count / self.request_count

    @property
    def total_tokens(self) -> int:
        """Calculate total tokens."""
        return self.prompt_tokens + self.completion_tokens

    def add_request(self, metrics: RequestMetrics) -> None:
        """Add request metrics to aggregation."""
        self.request_count += 1

        if metrics.success:
            self.success_count += 1
        else:
            self.error_count += 1
            if metrics.error_type:
                self.error_types[metrics.error_type] = (
                    self.error_types.get(metrics.error_type, 0) + 1
                )

        latency = metrics.latency_ms
        self.total_latency_ms += latency
        self.min_latency_ms = min(self.min_latency_ms, latency)
        self.max_latency_ms = max(self.max_latency_ms, latency)

        self.prompt_tokens += metrics.prompt_tokens
        self.completion_tokens += metrics.completion_tokens
        self.total_cost_usd += metrics.cost_usd

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "request_count": self.request_count,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "success_rate": f"{self.success_rate:.2%}",
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "min_latency_ms": round(self.min_latency_ms, 2)
            if self.min_latency_ms != float("inf")
            else 0,
            "max_latency_ms": round(self.max_latency_ms, 2),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "total_cost_usd": round(self.total_cost_usd, 4),
            "error_types": self.error_types,
        }


class RequestTracker:
    """Context manager for tracking a single request."""

    def __init__(
        self,
        collector: "MetricsCollector",
        provider: ProviderType,
        model: str,
    ):
        self._collector = collector
        self._metrics = RequestMetrics(
            provider=provider,
            model=model,
            start_time=time.time(),
        )

    def set_tokens(
        self,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> None:
        """Set token usage for this request."""
        self._metrics.prompt_tokens = prompt_tokens
        self._metrics.completion_tokens = completion_tokens

    def set_cost(self, cost_usd: float) -> None:
        """Set cost for this request."""
        self._metrics.cost_usd = cost_usd

    def set_error(self, error_type: str) -> None:
        """Mark request as failed with error type."""
        self._metrics.success = False
        self._metrics.error_type = error_type

    def _complete(self, success: bool = True) -> None:
        """Complete the request tracking."""
        self._metrics.end_time = time.time()
        if success and self._metrics.error_type is None:
            self._metrics.success = True
        self._collector._record_metrics(self._metrics)


# Cost per 1K tokens for various models (approximate)
MODEL_COSTS: dict[str, dict[str, float]] = {
    # OpenAI
    "gpt-4": {"input": 0.03, "output": 0.06},
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
    # Anthropic
    "claude-3-opus": {"input": 0.015, "output": 0.075},
    "claude-3-sonnet": {"input": 0.003, "output": 0.015},
    "claude-3-haiku": {"input": 0.00025, "output": 0.00125},
    # Gemini
    "gemini-pro": {"input": 0.00025, "output": 0.0005},
    "gemini-1.5-pro": {"input": 0.00125, "output": 0.005},
    "gemini-1.5-flash": {"input": 0.000075, "output": 0.0003},
    # Qwen
    "qwen-max": {"input": 0.004, "output": 0.012},
    "qwen-plus": {"input": 0.0008, "output": 0.002},
    "qwen-turbo": {"input": 0.0003, "output": 0.0006},
    # Deepseek
    "deepseek-chat": {"input": 0.00014, "output": 0.00028},
    "deepseek-coder": {"input": 0.00014, "output": 0.00028},
    # ZhipuAI
    "glm-4": {"input": 0.001, "output": 0.001},
    "glm-4-plus": {"input": 0.0015, "output": 0.0015},
}


def estimate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    """
    Estimate cost for a request.

    Args:
        model: Model name
        prompt_tokens: Number of input tokens
        completion_tokens: Number of output tokens

    Returns:
        Estimated cost in USD
    """
    # Find matching cost entry
    model_lower = model.lower()
    costs = None

    for model_key, model_costs in MODEL_COSTS.items():
        if model_key in model_lower:
            costs = model_costs
            break

    if costs is None:
        # Default fallback costs
        costs = {"input": 0.001, "output": 0.002}

    input_cost = (prompt_tokens / 1000) * costs["input"]
    output_cost = (completion_tokens / 1000) * costs["output"]

    return input_cost + output_cost


class MetricsCollector:
    """
    Collector for LLM operation metrics.

    Tracks metrics by provider, model, and time window.
    Thread-safe for concurrent access.
    """

    def __init__(
        self,
        retention_hours: int = 24,
        aggregation_interval_minutes: int = 5,
    ):
        """
        Initialize the metrics collector.

        Args:
            retention_hours: How long to retain detailed metrics
            aggregation_interval_minutes: Interval for metric aggregation
        """
        self._retention_hours = retention_hours
        self._aggregation_interval = timedelta(minutes=aggregation_interval_minutes)

        # Metrics storage
        self._by_provider: dict[ProviderType, AggregatedMetrics] = defaultdict(AggregatedMetrics)
        self._by_model: dict[str, AggregatedMetrics] = defaultdict(AggregatedMetrics)
        self._overall = AggregatedMetrics()

        # Recent requests for detailed analysis
        self._recent_requests: list[RequestMetrics] = []

        self._lock = Lock()
        self._start_time = datetime.now(timezone.utc)

    @contextmanager
    def track_request(
        self,
        provider: ProviderType,
        model: str,
    ) -> Generator[RequestTracker, None, None]:
        """
        Context manager to track a request.

        Usage:
            with collector.track_request(ProviderType.OPENAI, "gpt-4") as tracker:
                response = await client.generate(...)
                tracker.set_tokens(100, 50)

        Args:
            provider: Provider type
            model: Model name

        Yields:
            RequestTracker for recording metrics
        """
        tracker = RequestTracker(self, provider, model)
        try:
            yield tracker
            tracker._complete(success=True)
        except Exception as e:
            tracker.set_error(type(e).__name__)
            tracker._complete(success=False)
            raise

    def _record_metrics(self, metrics: RequestMetrics) -> None:
        """Record completed request metrics."""
        with self._lock:
            # Auto-calculate cost if not set
            if metrics.cost_usd == 0 and metrics.total_tokens > 0:
                metrics.cost_usd = estimate_cost(
                    metrics.model,
                    metrics.prompt_tokens,
                    metrics.completion_tokens,
                )

            # Update aggregations
            self._by_provider[metrics.provider].add_request(metrics)
            self._by_model[metrics.model].add_request(metrics)
            self._overall.add_request(metrics)

            # Store recent request
            self._recent_requests.append(metrics)

            # Cleanup old requests
            self._cleanup_old_requests()

    def _cleanup_old_requests(self) -> None:
        """Remove requests older than retention period."""
        cutoff = time.time() - (self._retention_hours * 3600)
        self._recent_requests = [r for r in self._recent_requests if r.start_time > cutoff]

    def record_request(
        self,
        provider: ProviderType,
        model: str,
        success: bool,
        latency_ms: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_usd: float = 0.0,
        error_type: Optional[str] = None,
    ) -> None:
        """
        Manually record request metrics.

        Args:
            provider: Provider type
            model: Model name
            success: Whether request succeeded
            latency_ms: Request latency in milliseconds
            prompt_tokens: Number of input tokens
            completion_tokens: Number of output tokens
            cost_usd: Request cost in USD
            error_type: Error type if failed
        """
        metrics = RequestMetrics(
            provider=provider,
            model=model,
            start_time=time.time() - (latency_ms / 1000),
            end_time=time.time(),
            success=success,
            error_type=error_type,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
        )
        self._record_metrics(metrics)

    def get_metrics(self) -> dict[str, Any]:
        """Get all metrics."""
        with self._lock:
            return {
                "overall": self._overall.to_dict(),
                "by_provider": {p.value: m.to_dict() for p, m in self._by_provider.items()},
                "by_model": {model: m.to_dict() for model, m in self._by_model.items()},
                "collection_started": self._start_time.isoformat(),
                "recent_request_count": len(self._recent_requests),
            }

    def get_provider_metrics(self, provider: ProviderType) -> dict[str, Any]:
        """Get metrics for a specific provider."""
        with self._lock:
            metrics = self._by_provider.get(provider)
            if metrics:
                return metrics.to_dict()
            return AggregatedMetrics().to_dict()

    def get_model_metrics(self, model: str) -> dict[str, Any]:
        """Get metrics for a specific model."""
        with self._lock:
            metrics = self._by_model.get(model)
            if metrics:
                return metrics.to_dict()
            return AggregatedMetrics().to_dict()

    def get_recent_errors(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent failed requests."""
        with self._lock:
            errors = [
                {
                    "provider": r.provider.value,
                    "model": r.model,
                    "error_type": r.error_type,
                    "latency_ms": round(r.latency_ms, 2),
                    "timestamp": datetime.fromtimestamp(r.start_time).isoformat(),
                }
                for r in reversed(self._recent_requests)
                if not r.success
            ]
            return errors[:limit]

    def get_latency_percentiles(
        self,
        provider: Optional[ProviderType] = None,
    ) -> dict[str, float]:
        """
        Calculate latency percentiles.

        Args:
            provider: Optional provider filter

        Returns:
            Dict with p50, p90, p95, p99 latencies
        """
        with self._lock:
            latencies = [
                r.latency_ms
                for r in self._recent_requests
                if provider is None or r.provider == provider
            ]

            if not latencies:
                return {"p50": 0, "p90": 0, "p95": 0, "p99": 0}

            latencies.sort()
            n = len(latencies)

            return {
                "p50": round(latencies[int(n * 0.5)], 2),
                "p90": round(latencies[int(n * 0.9)], 2),
                "p95": round(latencies[int(n * 0.95)], 2),
                "p99": round(latencies[min(int(n * 0.99), n - 1)], 2),
            }

    def reset(self) -> None:
        """Reset all metrics."""
        with self._lock:
            self._by_provider.clear()
            self._by_model.clear()
            self._overall = AggregatedMetrics()
            self._recent_requests.clear()
            self._start_time = datetime.now(timezone.utc)
            logger.info("Metrics collector reset")


# Global collector instance
_metrics_collector: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    """Get the global metrics collector."""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector


def reset_metrics() -> None:
    """Reset the global metrics collector."""
    global _metrics_collector
    _metrics_collector = None
