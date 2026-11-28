"""Cluster statistics can be projected without exposing provider configuration."""

from plugins.business.environments.backend.cluster_health import health_metrics, project_health


def test_numeric_statistics_are_the_only_worker_inputs():
    metrics = health_metrics(
        {
            "provider_credentials": {"internal": "private"},
            "nodes": "5",
            "health": {
                "used_cpu": "1",
                "total_cpu": 3,
                "memory_usage": 0,
                "internal": "private",
                "total_nodes": True,
            },
        }
    )
    assert metrics == {"nodes": 5, "used_cpu": 1, "total_cpu": 3, "memory_usage": 0}
    assert project_health(metrics) == {"node_count": 5, "cpu_usage": 33.33, "memory_usage": 0}


def test_missing_or_nonfinite_readings_are_omitted():
    assert project_health(health_metrics({"nodes": "inf", "health": {"total_cpu": 0}})) == {
        "node_count": 0,
        "cpu_usage": None,
        "memory_usage": None,
    }


def test_node_fallback_and_clamped_ratios():
    assert project_health(
        {
            "total_nodes": 0,
            "node_count": 2,
            "nodes": 3,
            "used_cpu": 7,
            "total_cpu": 1,
            "used_memory_gb": -1,
            "total_memory_gb": 2,
        }
    ) == {
        "node_count": 2,
        "cpu_usage": 100,
        "memory_usage": 0,
    }
