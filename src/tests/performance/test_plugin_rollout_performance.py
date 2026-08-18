"""Performance gates for the platform plugin rollout hot paths."""

from __future__ import annotations

import time
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

from src.infrastructure.plugins.agent_events import AgentPluginEventDispatcher
from src.infrastructure.plugins.agent_tools import AgentToolSetService
from src.infrastructure.plugins.builtin_manifests import default_builtin_manifests
from src.infrastructure.plugins.context import PluginScopeContext
from src.infrastructure.plugins.events import PluginEventBus
from src.infrastructure.plugins.llm_runtime import LlmRouteResolver, ProviderRouteConfig
from src.infrastructure.plugins.profile import compose_profile, parse_profile_document


def percentile(values: list[float], fraction: float) -> float:
    """Return a nearest-rank percentile in milliseconds."""
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * fraction))
    return ordered[index] / 1_000_000


def benchmark(call: Callable[[], object], iterations: int) -> list[float]:
    """Measure per-call nanoseconds after one warm-up."""
    call()
    samples: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        call()
        samples.append(time.perf_counter_ns() - started)
    return samples


@pytest.mark.performance
def test_default_profile_compose_p95_remains_under_100ms() -> None:
    manifests = default_builtin_manifests()
    document = parse_profile_document(
        {
            "profile": {
                "id": "performance-default",
                "layers": [{"id": "base", "rows": [{"id": plugin_id} for plugin_id in manifests]}],
            }
        }
    )

    samples = benchmark(lambda: compose_profile(document, manifests), 500)
    p95 = percentile(samples, 0.95)

    assert p95 < 100, f"profile compose P95 was {p95:.3f}ms"


@pytest.mark.performance
async def test_typed_event_dispatch_with_twenty_listeners_p95_is_under_2ms() -> None:
    bus = PluginEventBus()

    async def listener(payload: dict[str, Any]) -> dict[str, Any]:
        return await payload["next"]()

    for index in range(20):
        bus.subscribe("llm.request", f"listener-{index}", listener)
    dispatcher = AgentPluginEventDispatcher(legacy_registry=None, event_bus=bus, v2_enabled=True)

    async def dispatch() -> None:
        await dispatcher.dispatch("before_response", {"model": "demo"})

    await dispatch()
    samples: list[float] = []
    for _ in range(500):
        started = time.perf_counter_ns()
        await dispatch()
        samples.append(time.perf_counter_ns() - started)
    p95 = percentile(samples, 0.95)

    assert p95 < 2, f"20-listener event dispatch P95 was {p95:.3f}ms"


@pytest.mark.performance
def test_scoped_tool_current_lookup_overhead_stays_under_five_percent() -> None:
    tools = {
        f"tool-{index}": SimpleNamespace(
            name=f"tool-{index}",
            description=f"Benchmark tool {index}",
            parameters={"type": "object"},
        )
        for index in range(500)
    }
    scope = PluginScopeContext(tenant_id="tenant", project_id="project")
    service = AgentToolSetService(profile_digest="performance-profile")
    service.publish(scope, tools, profile_digest="performance-profile")

    legacy_samples = benchmark(lambda: dict(tools), 2_000)
    v2_samples = benchmark(lambda: service.current(scope), 2_000)
    legacy_p95 = percentile(legacy_samples, 0.95)
    v2_p95 = percentile(v2_samples, 0.95)
    allowed = legacy_p95 * 1.05

    assert v2_p95 <= allowed, (
        f"tool current P95 {v2_p95:.6f}ms exceeded legacy {legacy_p95:.6f}ms + 5%"
    )


@pytest.mark.performance
def test_llm_route_resolution_p95_is_under_10ms() -> None:
    class Lease:
        async def resolve(self, *_args: object, **_kwargs: object) -> None:
            return None

    route = ProviderRouteConfig(
        provider_id="benchmark-provider",
        provider_type="openai",
        model_id="benchmark-model",
        base_url="https://benchmark.invalid/v1",
        credential_ref="vault://benchmarks/provider",
        credential_revision=1,
    )
    resolver = LlmRouteResolver(providers={route.provider_id: route}, lease_resolver=Lease())

    samples = benchmark(lambda: resolver.resolve(route.provider_id), 2_000)
    p95 = percentile(samples, 0.95)

    assert p95 < 10, f"LLM route resolution P95 was {p95:.3f}ms"
