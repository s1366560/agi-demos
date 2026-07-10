"""Unit tests for historical pool metrics analysis."""

from datetime import UTC, datetime, timedelta

import pytest

from src.infrastructure.agent.pool.metrics_analyzer import (
    MetricsDataPoint,
    PoolMetricsAnalyzer,
    PoolTrendAnalysis,
    TrendAnalysis,
)

pytestmark = pytest.mark.unit


def _point(
    *,
    hour: int = 0,
    cpu: float = 50.0,
    memory: float = 512.0,
    requests: int = 100,
    latency: float = 25.0,
    errors: int = 1,
) -> MetricsDataPoint:
    return MetricsDataPoint(
        timestamp=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=hour),
        cpu_percent=cpu,
        memory_mb=memory,
        request_count=requests,
        average_latency_ms=latency,
        error_count=errors,
    )


def _trend(
    metric_name: str,
    direction: str = "stable",
    strength: float = 0.0,
) -> TrendAnalysis:
    return TrendAnalysis(
        metric_name=metric_name,
        trend_direction=direction,
        trend_strength=strength,
    )


def _analysis(
    *,
    recommended: int,
    cpu: TrendAnalysis | None = None,
    requests: TrendAnalysis | None = None,
    latency: TrendAnalysis | None = None,
    errors: TrendAnalysis | None = None,
) -> PoolTrendAnalysis:
    return PoolTrendAnalysis(
        cpu_trend=cpu or _trend("cpu_percent"),
        memory_trend=_trend("memory_mb"),
        request_trend=requests or _trend("request_count"),
        latency_trend=latency or _trend("average_latency_ms"),
        error_rate_trend=errors or _trend("error_rate"),
        peak_hours=[],
        recommended_instance_count=recommended,
        confidence_score=0.75,
    )


def test_analyze_trends_returns_default_when_history_is_insufficient() -> None:
    analyzer = PoolMetricsAnalyzer(min_data_points=3)

    result = analyzer.analyze_trends([_point()], current_instance_count=4)

    assert result.recommended_instance_count == 4
    assert result.confidence_score == 0.0
    assert result.peak_hours == []
    assert {
        result.cpu_trend.trend_direction,
        result.memory_trend.trend_direction,
        result.request_trend.trend_direction,
        result.latency_trend.trend_direction,
        result.error_rate_trend.trend_direction,
    } == {"stable"}


def test_analyze_trends_builds_complete_analysis_and_scales_for_demand() -> None:
    analyzer = PoolMetricsAnalyzer(min_data_points=10)
    history = [
        _point(
            hour=index,
            cpu=20.0 + index * 6,
            memory=400.0 + index * 5,
            requests=100 + index * 20,
            latency=20.0 + index * 2,
            errors=1 + index,
        )
        for index in range(12)
    ]

    result = analyzer.analyze_trends(history, current_instance_count=2)

    assert result.cpu_trend.trend_direction == "increasing"
    assert result.memory_trend.trend_direction == "increasing"
    assert result.request_trend.trend_direction == "increasing"
    assert result.latency_trend.trend_direction == "increasing"
    assert result.recommended_instance_count == 3
    assert result.peak_hours == [9, 10, 11]
    assert result.confidence_score == pytest.approx(0.76)


@pytest.mark.parametrize(
    ("values", "direction", "predicted"),
    [
        ([10.0, 20.0, 30.0], "increasing", 70.0),
        ([30.0, 20.0, 10.0], "decreasing", None),
        ([10.0, 10.0, 10.0], "stable", 10.0),
    ],
)
def test_analyze_single_metric_classifies_direction_and_prediction(
    values: list[float],
    direction: str,
    predicted: float | None,
) -> None:
    analyzer = PoolMetricsAnalyzer(min_data_points=3, prediction_horizon_hours=4)

    result = analyzer._analyze_single_metric(
        [(float(index), value) for index, value in enumerate(values)],
        "metric",
    )

    assert result.trend_direction == direction
    assert result.predicted_value == predicted
    assert result.confidence == 1.0


def test_analyze_single_metric_with_one_value_is_stable() -> None:
    result = PoolMetricsAnalyzer()._analyze_single_metric([(0.0, 12.0)], "metric")

    assert result == TrendAnalysis(
        metric_name="metric",
        trend_direction="stable",
        trend_strength=0.0,
    )


def test_analyze_single_metric_with_all_zero_values_is_stable() -> None:
    result = PoolMetricsAnalyzer()._analyze_single_metric(
        [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)],
        "metric",
    )

    assert result.trend_direction == "stable"
    assert result.trend_strength == 0.0
    assert result.predicted_value is None


def test_analyze_error_rate_without_requests_is_stable() -> None:
    result = PoolMetricsAnalyzer()._analyze_error_rate(
        [_point(requests=0, errors=2), _point(hour=1, requests=0, errors=3)]
    )

    assert result.metric_name == "error_rate"
    assert result.trend_direction == "stable"


def test_analyze_error_rate_uses_only_points_with_requests() -> None:
    result = PoolMetricsAnalyzer(min_data_points=2)._analyze_error_rate(
        [
            _point(requests=0, errors=99),
            _point(hour=1, requests=100, errors=1),
            _point(hour=2, requests=100, errors=10),
        ]
    )

    assert result.trend_direction == "increasing"
    assert result.confidence == 1.0


def test_identify_peak_hours_handles_empty_and_small_samples() -> None:
    analyzer = PoolMetricsAnalyzer()

    assert analyzer._identify_peak_hours([]) == []
    assert analyzer._identify_peak_hours(
        [_point(hour=3, requests=10), _point(hour=1, requests=20)]
    ) == [3, 1]


def test_identify_peak_hours_uses_hourly_average_and_percentile() -> None:
    result = PoolMetricsAnalyzer()._identify_peak_hours(
        [
            _point(hour=0, requests=10),
            _point(hour=0, requests=30),
            _point(hour=1, requests=20),
            _point(hour=2, requests=30),
            _point(hour=3, requests=40),
        ]
    )

    assert result == [3]


@pytest.mark.parametrize(
    ("cpu", "requests", "current_count", "expected"),
    [
        ((_trend("cpu", "stable"), 85.0), _trend("requests"), 2, 3),
        ((_trend("cpu", "increasing"), 75.0), _trend("requests"), 2, 3),
        (
            (_trend("cpu", "decreasing"), 20.0),
            _trend("requests"),
            2,
            1,
        ),
        (
            (_trend("cpu", "stable"), 50.0),
            _trend("requests", "increasing", 0.75),
            2,
            3,
        ),
        ((_trend("cpu", "stable"), 50.0), _trend("requests"), 2, 2),
    ],
)
def test_calculate_recommended_instances_covers_capacity_signals(
    cpu: tuple[TrendAnalysis, float],
    requests: TrendAnalysis,
    current_count: int,
    expected: int,
) -> None:
    cpu_trend, cpu_value = cpu

    result = PoolMetricsAnalyzer()._calculate_recommended_instances(
        metrics_history=[_point(cpu=cpu_value) for _ in range(12)],
        current_count=current_count,
        cpu_trend=cpu_trend,
        request_trend=requests,
    )

    assert result == expected


@pytest.mark.parametrize(
    ("trends", "expected"),
    [
        ([], 0.5),
        ([_trend("a", "increasing"), _trend("b", "increasing")], 1.0),
        ([_trend("a", "decreasing"), _trend("b", "decreasing")], 1.0),
        ([_trend("a"), _trend("b")], 0.8),
        ([_trend("a", "increasing"), _trend("b", "decreasing")], 0.4),
    ],
)
def test_check_trend_consistency(trends: list[TrendAnalysis], expected: float) -> None:
    assert PoolMetricsAnalyzer()._check_trend_consistency(trends) == expected


def test_calculate_confidence_caps_data_factor() -> None:
    analyzer = PoolMetricsAnalyzer(min_data_points=10)

    assert analyzer._calculate_confidence(10, 0.5) == pytest.approx(0.5)
    assert analyzer._calculate_confidence(100, 1.0) == 1.0


@pytest.mark.parametrize(
    ("analysis", "current", "limits", "action", "target", "urgency", "reason"),
    [
        (
            _analysis(
                recommended=12,
                cpu=_trend("cpu", "increasing", 0.9),
                requests=_trend("requests", "increasing", 0.6),
                latency=_trend("latency", "increasing"),
            ),
            2,
            (1, 5),
            "scale_up",
            5,
            "critical",
            "CPU trend increasing; Request volume increasing; Latency degradation detected",
        ),
        (
            _analysis(
                recommended=3,
                cpu=_trend("cpu", "stable", 0.1),
                errors=_trend("errors", "increasing"),
            ),
            2,
            (1, 5),
            "scale_up",
            3,
            "high",
            "Proactive scaling",
        ),
        (
            _analysis(
                recommended=0,
                cpu=_trend("cpu", "decreasing"),
                requests=_trend("requests", "decreasing"),
            ),
            3,
            (1, 5),
            "scale_down",
            1,
            "low",
            "Low CPU utilization; Reduced request volume",
        ),
        (
            _analysis(recommended=2),
            2,
            (1, 5),
            "maintain",
            2,
            "low",
            "Current capacity meets demand",
        ),
    ],
)
def test_get_scaling_recommendation(
    analysis: PoolTrendAnalysis,
    current: int,
    limits: tuple[int, int],
    action: str,
    target: int,
    urgency: str,
    reason: str,
) -> None:
    result = PoolMetricsAnalyzer().get_scaling_recommendation(
        analysis,
        current_instance_count=current,
        min_instances=limits[0],
        max_instances=limits[1],
    )

    assert result.action == action
    assert result.target_count == target
    assert result.urgency == urgency
    assert result.reason == reason
    assert result.confidence == 0.75


def test_scale_up_with_weak_signal_has_medium_urgency() -> None:
    result = PoolMetricsAnalyzer().get_scaling_recommendation(
        _analysis(recommended=2, cpu=_trend("cpu", "increasing", 0.2)),
        current_instance_count=1,
    )

    assert result.urgency == "medium"


def test_scale_down_without_decreasing_trends_uses_cost_reason() -> None:
    result = PoolMetricsAnalyzer().get_scaling_recommendation(
        _analysis(recommended=1),
        current_instance_count=2,
    )

    assert result.reason == "Cost optimization"


def test_determine_urgency_for_unknown_action_is_low() -> None:
    assert PoolMetricsAnalyzer()._determine_urgency(_analysis(recommended=1), "unknown") == "low"
