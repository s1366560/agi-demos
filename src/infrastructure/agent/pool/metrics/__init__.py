"""
Pool Metrics Module.

Prometheus 指标收集，用于池化管理的可观测性。
"""

from .collector import PoolMetricsCollector, get_metrics_collector

__all__ = [
    "PoolMetricsCollector",
    "get_metrics_collector",
]
