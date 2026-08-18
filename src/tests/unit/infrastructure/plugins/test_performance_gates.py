"""Performance gates for the platform plugin kernel hot paths.

Thresholds come from the Phase 3-6 plan: profile compose P95 < 100ms,
event dispatch with 20 listeners P95 < 2ms, provider route resolution
P95 < 10ms, and tool generation build/publish staying within a small
absolute budget (the relative <5% overhead target is validated against
production profiles in shadow-rollout evidence).
"""

from __future__ import annotations

import statistics
import time
from types import SimpleNamespace
from typing import Any

import pytest

from src.infrastructure.plugins.agent_tools import AgentToolSetService
from src.infrastructure.plugins.builtin_manifests import default_builtin_manifests
from src.infrastructure.plugins.context import PluginScopeContext
from src.infrastructure.plugins.events import PluginEventBus
from src.infrastructure.plugins.llm_runtime import LlmRouteResolver, ProviderRouteConfig
from src.infrastructure.plugins.profile import compose_profile, parse_profile_document

_ITERATIONS = 100
_WARMUP = 10


def _percentile_95(samples: list[float]) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, int(len(ordered) * 0.95))
    return ordered[index]


def _measure(call: Any, *, iterations: int = _ITERATIONS) -> list[float]:
    for _ in range(_WARMUP):
        call()
    samples: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter()
        call()
        samples.append((time.perf_counter() - started) * 1000.0)
    return samples


class _UnusedLeaseResolver:
    async def resolve(self, scope: PluginScopeContext, credential: Any) -> Any:
        raise AssertionError("lease resolution must not run in the resolution gate")


@pytest.mark.unit
def test_profile_compose_p95_within_budget() -> None:
    document = parse_profile_document(
        {
            "profile": {
                "id": "perf-default",
                "layers": [
                    {
                        "id": "base",
                        "plugins": [
                            {"id": "workspace-runtime"},
                            {"id": "sisyphus-runtime"},
                        ],
                    }
                ],
            }
        }
    )
    manifests = default_builtin_manifests()

    samples = _measure(lambda: compose_profile(document, manifests))

    p95 = _percentile_95(samples)
    assert p95 < 100.0, f"profile compose p95 {p95:.2f}ms exceeds the 100ms budget"


@pytest.mark.unit
async def test_event_waterfall_twenty_listeners_p95_within_budget() -> None:
    bus = PluginEventBus()

    async def listener(payload: Any) -> Any:
        return await payload["next"]()

    for index in range(20):
        bus.subscribe("agent.before_step", f"plugin-{index}", listener)

    async def dispatch() -> None:
        await bus.waterfall("agent.before_step", {"value": 1})

    samples: list[float] = []
    for _ in range(_WARMUP):
        await dispatch()
    for _ in range(_ITERATIONS):
        started = time.perf_counter()
        await dispatch()
        samples.append((time.perf_counter() - started) * 1000.0)

    p95 = _percentile_95(samples)
    assert p95 < 2.0, f"waterfall dispatch p95 {p95:.2f}ms exceeds the 2ms budget"


@pytest.mark.unit
def test_provider_route_resolution_p95_within_budget() -> None:
    resolver = LlmRouteResolver(
        providers={
            "openai": ProviderRouteConfig(
                provider_id="openai",
                provider_type="openai",
                model_id="gpt-5",
                base_url="https://api.example.test/v1",
                credential_ref="vault://llm/openai",
                credential_revision=3,
            )
        },
        lease_resolver=_UnusedLeaseResolver(),
    )

    samples = _measure(lambda: resolver.resolve("openai"))

    p95 = _percentile_95(samples)
    assert p95 < 10.0, f"route resolution p95 {p95:.2f}ms exceeds the 10ms budget"


@pytest.mark.unit
def test_tool_generation_publish_and_build_within_budget() -> None:
    service = AgentToolSetService()
    scope = PluginScopeContext(project_id="perf-project")
    tools = {
        f"tool-{index}": SimpleNamespace(
            name=f"tool-{index}",
            description=f"perf tool {index}",
            parameters={"type": "object", "properties": {}},
            permission=None,
        )
        for index in range(100)
    }

    publish_samples = _measure(lambda: service.publish(scope, tools))
    snapshot = service.current(scope)
    assert snapshot is not None

    def build_all() -> None:
        for tool_id in tools:
            _ = service.implementation(tool_id, snapshot)

    build_samples = _measure(build_all, iterations=20)

    publish_p95 = _percentile_95(publish_samples)
    build_median = statistics.median(build_samples)
    assert publish_p95 < 50.0, (
        f"tool generation publish p95 {publish_p95:.2f}ms exceeds the 50ms budget"
    )
    assert build_median < 10.0, (
        f"building 100 pinned tools took {build_median:.2f}ms median, expected < 10ms"
    )
