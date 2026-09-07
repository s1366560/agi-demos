"""Performance gates for the production protocol-v2 composition hot paths."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.agent_runtime_dispatcher import (
    PinnedAgentRuntimeDispatcherV2,
)
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import GenerationManagerV2, LoaderV2

_ITERATIONS = 100
_ROOT = Path(__file__).resolve().parents[6]
_PROFILE = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


def _p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]


def _sources():
    profile = load_profile_document_v2(_PROFILE)
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST.read_text(encoding="utf-8")))
    return profile, {manifest.plugin_id: manifest}


def _scope() -> ScopeV2:
    return ScopeV2(
        kind=ScopeKindV2.SESSION,
        tenant_id="tenant-performance",
        project_id="project-performance",
        session_id="session-performance",
    )


@pytest.mark.unit
def test_profile_v2_compose_p95_within_budget() -> None:
    """Measure production composition alone, not the whole service's latency SLO."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.tests.unit.infrastructure.plugins.v2.profile_compose_benchmark_v2",
        ],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    measurements = json.loads(result.stdout)
    samples = measurements["samples_ms"]
    assert measurements["gc_enabled"] is True
    assert measurements["warmup"] == 10
    assert len(samples) == _ITERATIONS
    p95 = _p95(samples)
    assert p95 < 100.0, (
        f"protocol-v2 profile compose p95 {p95:.2f}ms exceeds 100ms; samples={samples}"
    )


@pytest.mark.unit
async def test_pinned_v2_agent_event_dispatch_p95_within_budget() -> None:
    profile, manifests = _sources()
    snapshot = compose_profile_v2(profile, manifests, generation=1)
    generation = await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)
    manager = GenerationManagerV2()
    await manager.publish(generation)
    dispatcher = PinnedAgentRuntimeDispatcherV2()
    payload = {
        "tenant_id": "tenant-performance",
        "project_id": "project-performance",
        "session_id": "session-performance",
        "conversation_id": "session-performance",
        "session_instructions": [],
        "response_instructions": [],
    }

    try:
        async with pin_operation_context_v2(
            manager,
            operation_id="performance-turn",
            scope=_scope(),
        ):
            for _ in range(10):
                await dispatcher.dispatch("before_response", payload)
            samples: list[float] = []
            for _ in range(_ITERATIONS):
                started = time.perf_counter()
                await dispatcher.dispatch("before_response", payload)
                samples.append((time.perf_counter() - started) * 1000.0)
    finally:
        await manager.close()

    p95 = _p95(samples)
    assert p95 < 20.0, f"pinned protocol-v2 event dispatch p95 {p95:.2f}ms exceeds 20ms"
