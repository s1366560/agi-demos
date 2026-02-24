"""Pool Metrics Analyzer - Historical metrics analysis for auto-scaling.

Analyzes historical metrics to provide scaling recommendations
and predict resource requirements.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


@dataclass
class MetricsDataPoint:
    """Single metrics data point."""

    timestamp: datetime
    cpu_percent: float
    memory_mb: float
    request_count: int
    average_latency_ms: float
    error_count: int
    active_requests: int = 0


@dataclass
class TrendAnalysis:
    """Result of trend analysis."""

    metric_name: str
    trend_direction: str  # "increasing", "decreasing", "stable"
    trend_strength: float  # 0.0 to 1.0
    predicted_value: float | None = None
    confidence: float = 0.0


@dataclass
class PoolTrendAnalysis:
    """Comprehensive pool trend analysis."""

    cpu_trend: TrendAnalysis
    memory_trend: TrendAnalysis
    request_trend: TrendAnalysis
    latency_trend: TrendAnalysis
    error_rate_trend: TrendAnalysis
    peak_hours: list[int]  # Hours of day with highest load (0-23)
    recommended_instance_count: int
    confidence_score: float
    analysis_timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class ScalingRecommendation:
    """Scaling recommendation based on analysis."""

    action: str  # "scale_up", "scale_down", "maintain"
    target_count: int
    reason: str
    confidence: float
    urgency: str  # "low", "medium", "high", "critical"
    estimated_cost_impact: float | None = None


class PoolMetricsAnalyzer:
    """
    Analyzes historical metrics for agent pool scaling decisions.

    Features:
    - Trend detection (CPU, memory, requests, latency, errors)
    - Peak hour identification
    - Scaling recommendations
    - Cost optimization suggestions
    """

    def __init__(
        self,
        min_data_points: int = 10,
        analysis_window_hours: int = 24,
        prediction_horizon_hours: int = 4,
    ) -> None:
        """Initialize the analyzer.

        Args:
            min_data_points: Minimum data points required for analysis
            analysis_window_hours: Hours of historical data to analyze
            prediction_horizon_hours: Hours ahead to predict
        """
        self._min_data_points = min_data_points
        self._analysis_window_hours = analysis_window_hours
        self._prediction_horizon_hours = prediction_horizon_hours

    def analyze_trends(
        self,
        metrics_history: list[MetricsDataPoint],
        current_instance_count: int = 1,
    ) -> PoolTrendAnalysis:
        """Analyze trends from historical metrics.

        Args:
            metrics_history: List of historical metrics data points
            current_instance_count: Current number of instances

        Returns:
            PoolTrendAnalysis with all trend information
        """
        if len(metrics_history) < self._min_data_points:
            logger.warning(
                f"Insufficient data points: {len(metrics_history)} < {self._min_data_points}"
            )
            return self._create_default_analysis(current_instance_count)

        # Analyze individual trends
        cpu_trend = self._analyze_single_metric(
            [(m.timestamp, m.cpu_percent) for m in metrics_history],
            "cpu_percent",
        )
        memory_trend = self._analyze_single_metric(
            [(m.timestamp, m.memory_mb) for m in metrics_history],
            "memory_mb",
        )
        request_trend = self._analyze_single_metric(
            [(m.timestamp, float(m.request_count)) for m in metrics_history],
            "request_count",
        )
        latency_trend = self._analyze_single_metric(
            [(m.timestamp, m.average_latency_ms) for m in metrics_history],
            "average_latency_ms",
        )
        error_rate_trend = self._analyze_error_rate(metrics_history)

        # Identify peak hours
        peak_hours = self._identify_peak_hours(metrics_history)

        # Calculate recommended instance count
        recommended_count = self._calculate_recommended_instances(
            metrics_history=metrics_history,
            current_count=current_instance_count,
            cpu_trend=cpu_trend,
            request_trend=request_trend,
        )

        # Calculate confidence score
        confidence = self._calculate_confidence(
            data_points=len(metrics_history),
            trend_consistency=self._check_trend_consistency(
                [cpu_trend, request_trend, latency_trend]
            ),
        )

        return PoolTrendAnalysis(
            cpu_trend=cpu_trend,
            memory_trend=memory_trend,
            request_trend=request_trend,
            latency_trend=latency_trend,
            error_rate_trend=error_rate_trend,
            peak_hours=peak_hours,
            recommended_instance_count=recommended_count,
            confidence_score=confidence,
        )

    def get_scaling_recommendation(
        self,
        analysis: PoolTrendAnalysis,
        current_instance_count: int,
        min_instances: int = 1,
        max_instances: int = 10,
    ) -> ScalingRecommendation:
        """Get scaling recommendation based on analysis.

        Args:
            analysis: Pool trend analysis
            current_instance_count: Current number of instances
            min_instances: Minimum allowed instances
            max_instances: Maximum allowed instances

        Returns:
            ScalingRecommendation with action and details
        """
        target_count = analysis.recommended_instance_count

        # Determine action
        if target_count > current_instance_count:
            action = "scale_up"
            urgency = self._determine_urgency(analysis, action)
            reason = self._generate_scale_up_reason(analysis)
        elif target_count < current_instance_count:
            action = "scale_down"
            urgency = self._determine_urgency(analysis, action)
            reason = self._generate_scale_down_reason(analysis)
        else:
            action = "maintain"
            urgency = "low"
            reason = "Current capacity meets demand"

        # Clamp to limits
        target_count = max(min_instances, min(max_instances, target_count))

        return ScalingRecommendation(
            action=action,
            target_count=target_count,
            reason=reason,
            confidence=analysis.confidence_score,
            urgency=urgency,
        )

    def _analyze_single_metric(
        self,
        data: list[tuple[float, float]],
        metric_name: str,
    ) -> TrendAnalysis:
        """Analyze trend for a single metric."""
        if len(data) < 2:
            return TrendAnalysis(
                metric_name=metric_name,
                trend_direction="stable",
                trend_strength=0.0,
            )

        # Simple linear regression for trend detection
        values = [v for _, v in data]
        n = len(values)

        # Calculate slope
        x_mean = (n - 1) / 2
        y_mean = sum(values) / n

        numerator = sum((i - x_mean) * (values[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            slope = 0
        else:
            slope = numerator / denominator

        # Determine direction and strength
        if abs(slope) < 0.01 * y_mean:  # Less than 1% change per data point
            direction = "stable"
            strength = 0.0
        elif slope > 0:
            direction = "increasing"
            strength = min(1.0, slope / y_mean * 10)  # Normalize
        else:
            direction = "decreasing"
            strength = min(1.0, abs(slope) / y_mean * 10)

        # Predict next value
        predicted = values[-1] + slope * self._prediction_horizon_hours

        return TrendAnalysis(
            metric_name=metric_name,
            trend_direction=direction,
            trend_strength=strength,
            predicted_value=predicted if predicted > 0 else None,
            confidence=min(1.0, n / self._min_data_points),
        )

    def _analyze_error_rate(
        self,
        metrics: list[MetricsDataPoint],
    ) -> TrendAnalysis:
        """Analyze error rate trend."""
        error_rates = []
        for m in metrics:
            if m.request_count > 0:
                rate = m.error_count / m.request_count
                error_rates.append((m.timestamp, rate))

        if not error_rates:
            return TrendAnalysis(
                metric_name="error_rate",
                trend_direction="stable",
                trend_strength=0.0,
            )

        return self._analyze_single_metric(error_rates, "error_rate")

    def _identify_peak_hours(self, metrics: list[MetricsDataPoint]) -> list[int]:
        """Identify peak hours from metrics."""
        hourly_load: dict[int, list[float]] = {}

        for m in metrics:
            hour = m.timestamp.hour
            if hour not in hourly_load:
                hourly_load[hour] = []
            hourly_load[hour].append(m.request_count)

        if not hourly_load:
            return []

        # Calculate average load per hour
        hour_averages = {hour: sum(loads) / len(loads) for hour, loads in hourly_load.items()}

        # Find hours above 75th percentile
        if len(hour_averages) < 4:
            return list(hour_averages.keys())

        all_averages = list(hour_averages.values())
        threshold = sorted(all_averages)[int(len(all_averages) * 0.75)]

        peak_hours = [hour for hour, avg in hour_averages.items() if avg >= threshold]
        return sorted(peak_hours)

    def _calculate_recommended_instances(
        self,
        metrics_history: list[MetricsDataPoint],
        current_count: int,
        cpu_trend: TrendAnalysis,
        request_trend: TrendAnalysis,
    ) -> int:
        """Calculate recommended instance count."""
        # Get recent metrics
        recent = metrics_history[-10:] if len(metrics_history) >= 10 else metrics_history

        # Calculate average CPU utilization
        avg_cpu = sum(m.cpu_percent for m in recent) / len(recent)

        # Base calculation on CPU utilization
        # Target: 60-80% CPU utilization per instance
        if avg_cpu > 80 or (avg_cpu > 70 and cpu_trend.trend_direction == "increasing"):
            cpu_based = current_count + 1
        elif avg_cpu < 30 and cpu_trend.trend_direction == "decreasing":
            cpu_based = max(1, current_count - 1)
        else:
            cpu_based = current_count

        # Consider request trend
        if request_trend.trend_direction == "increasing" and request_trend.trend_strength > 0.5:
            request_based = current_count + 1
        else:
            request_based = current_count

        # Take the maximum recommendation
        return max(cpu_based, request_based)

    def _calculate_confidence(
        self,
        data_points: int,
        trend_consistency: float,
    ) -> float:
        """Calculate overall confidence score."""
        # Data points factor (0.0 to 1.0)
        data_factor = min(1.0, data_points / (self._min_data_points * 2))

        # Combine factors
        return data_factor * 0.6 + trend_consistency * 0.4

    def _check_trend_consistency(self, trends: list[TrendAnalysis]) -> float:
        """Check if trends are consistent (all pointing same direction)."""
        if not trends:
            return 0.5

        increasing = sum(1 for t in trends if t.trend_direction == "increasing")
        decreasing = sum(1 for t in trends if t.trend_direction == "decreasing")

        # More consistent = higher score
        if increasing == len(trends) or decreasing == len(trends):
            return 1.0
        elif increasing == 0 and decreasing == 0:
            return 0.8  # All stable
        else:
            return 0.4  # Mixed signals

    def _determine_urgency(
        self,
        analysis: PoolTrendAnalysis,
        action: str,
    ) -> str:
        """Determine urgency of scaling action."""
        if action == "scale_up":
            if analysis.cpu_trend.trend_strength > 0.8:
                return "critical"
            elif (
                analysis.cpu_trend.trend_strength > 0.5
                or analysis.error_rate_trend.trend_direction == "increasing"
            ):
                return "high"
            else:
                return "medium"
        elif action == "scale_down":
            return "low"  # Scale down is rarely urgent
        else:
            return "low"

    def _generate_scale_up_reason(self, analysis: PoolTrendAnalysis) -> str:
        """Generate human-readable reason for scale up."""
        reasons = []

        if analysis.cpu_trend.trend_direction == "increasing":
            reasons.append(f"CPU trend {analysis.cpu_trend.trend_direction}")
        if analysis.request_trend.trend_direction == "increasing":
            reasons.append("Request volume increasing")
        if analysis.latency_trend.trend_direction == "increasing":
            reasons.append("Latency degradation detected")

        return "; ".join(reasons) if reasons else "Proactive scaling"

    def _generate_scale_down_reason(self, analysis: PoolTrendAnalysis) -> str:
        """Generate human-readable reason for scale down."""
        reasons = []

        if analysis.cpu_trend.trend_direction == "decreasing":
            reasons.append("Low CPU utilization")
        if analysis.request_trend.trend_direction == "decreasing":
            reasons.append("Reduced request volume")

        return "; ".join(reasons) if reasons else "Cost optimization"

    def _create_default_analysis(self, current_count: int) -> PoolTrendAnalysis:
        """Create default analysis when insufficient data."""
        return PoolTrendAnalysis(
            cpu_trend=TrendAnalysis(
                metric_name="cpu_percent",
                trend_direction="stable",
                trend_strength=0.0,
            ),
            memory_trend=TrendAnalysis(
                metric_name="memory_mb",
                trend_direction="stable",
                trend_strength=0.0,
            ),
            request_trend=TrendAnalysis(
                metric_name="request_count",
                trend_direction="stable",
                trend_strength=0.0,
            ),
            latency_trend=TrendAnalysis(
                metric_name="average_latency_ms",
                trend_direction="stable",
                trend_strength=0.0,
            ),
            error_rate_trend=TrendAnalysis(
                metric_name="error_rate",
                trend_direction="stable",
                trend_strength=0.0,
            ),
            peak_hours=[],
            recommended_instance_count=current_count,
            confidence_score=0.0,
        )
