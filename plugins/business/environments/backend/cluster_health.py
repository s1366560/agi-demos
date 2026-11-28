"""Project node count and CPU/memory utilization from a cluster's numeric statistics."""

from collections.abc import Mapping
from math import isfinite
from typing import TypedDict


class HealthProjection(TypedDict):
    node_count: int
    cpu_usage: float | None
    memory_usage: float | None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if isfinite(number) else None


def health_metrics(provider_config: Mapping[str, object]) -> dict[str, float]:
    health = provider_config.get("health")
    if not isinstance(health, Mapping):
        health = {}
    metrics: dict[str, float] = {}
    for key in (
        "total_nodes",
        "used_cpu",
        "total_cpu",
        "cpu_usage",
        "used_memory_gb",
        "total_memory_gb",
        "memory_usage",
    ):
        if (value := _number(health.get(key))) is not None:
            metrics[key] = value
    for key in ("node_count", "nodes"):
        if (value := _number(provider_config.get(key))) is not None:
            metrics[key] = value
    return metrics


def _percent(direct: float | None, used: float | None, total: float | None) -> float | None:
    if direct is not None:
        return direct
    if used is None or total is None or total <= 0:
        return None
    return round(min(max((used / total) * 100, 0), 100), 2)


def project_health(metrics: Mapping[str, float]) -> HealthProjection:
    return {
        "node_count": (
            int(metrics.get("total_nodes", 0))
            or int(metrics.get("node_count", 0))
            or int(metrics.get("nodes", 0))
        ),
        "cpu_usage": _percent(
            metrics.get("cpu_usage"), metrics.get("used_cpu"), metrics.get("total_cpu")
        ),
        "memory_usage": _percent(
            metrics.get("memory_usage"),
            metrics.get("used_memory_gb"),
            metrics.get("total_memory_gb"),
        ),
    }
