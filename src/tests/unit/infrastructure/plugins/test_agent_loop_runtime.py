"""Unit tests for per-turn agent loop resolution (P2 seam)."""

from __future__ import annotations

import pytest

from src.domain.model.plugins import (
    CapabilityKind,
    PluginManifest,
    PluginRuntimeKind,
    PluginTrust,
    ProvidedCapability,
)
from src.infrastructure.plugins.agent_loop_runtime import (
    AgentLoopResolutionError,
    AgentLoopResolver,
    validate_loop_implementation,
)
from src.infrastructure.plugins.context import CapabilityRegistry, PluginContext


class _Loop:
    def __init__(self, priority: int | None = None) -> None:
        self.priority = priority

    async def run(self, context: object) -> str:
        return "ok"

    def supports(self, context: dict[str, str]) -> int | None:
        return self.priority


def _register_loop(
    registry: CapabilityRegistry,
    plugin_id: str,
    capability_id: str,
    implementation: object,
    *,
    trust: PluginTrust = PluginTrust.BUILTIN,
) -> None:
    manifest = PluginManifest(
        schema_version=1,
        id=plugin_id,
        version="1.0.0",
        runtime=PluginRuntimeKind.PYTHON_TRUSTED,
        trust=trust,
        provides=(
            ProvidedCapability(
                kind=CapabilityKind.AGENT_LOOP,
                id=capability_id,
                contract=f"agent-loop:{capability_id}",
            ),
        ),
    )
    context = PluginContext(registry, manifest)
    context.register_capability(CapabilityKind.AGENT_LOOP, capability_id, implementation)


@pytest.mark.unit
def test_model_scoped_beats_provider_scoped() -> None:
    registry = CapabilityRegistry()
    _register_loop(registry, "plugin-a", "deepseek", _Loop())
    _register_loop(registry, "plugin-b", "deepseek:v3", _Loop())
    resolver = AgentLoopResolver(registry)

    selection = resolver.resolve("deepseek", "v3")

    assert selection.scope == "model"
    assert selection.plugin_id == "plugin-b"


@pytest.mark.unit
def test_provider_scoped_used_when_no_model_match() -> None:
    registry = CapabilityRegistry()
    _register_loop(registry, "plugin-a", "deepseek", _Loop())
    resolver = AgentLoopResolver(registry)

    selection = resolver.resolve("deepseek", "r1")

    assert selection.scope == "provider"
    assert selection.plugin_id == "plugin-a"


@pytest.mark.unit
def test_auto_selects_highest_supports_priority() -> None:
    registry = CapabilityRegistry()
    _register_loop(registry, "plugin-low", "loop-low", _Loop(priority=10))
    _register_loop(registry, "plugin-high", "loop-high", _Loop(priority=90))
    _register_loop(registry, "plugin-abstain", "loop-abstain", _Loop(priority=None))
    resolver = AgentLoopResolver(registry)

    selection = resolver.resolve("openai", "gpt-5")

    assert selection.scope == "auto"
    assert selection.plugin_id == "plugin-high"


@pytest.mark.unit
def test_builtin_default_is_the_fallback() -> None:
    registry = CapabilityRegistry()
    _register_loop(registry, "kernel", "default", _Loop())
    resolver = AgentLoopResolver(registry)

    selection = resolver.resolve("anthropic", "claude")

    assert selection.scope == "builtin"
    assert selection.plugin_id == "kernel"


@pytest.mark.unit
def test_explicit_builtin_loop_sentinel_when_no_default_row() -> None:
    registry = CapabilityRegistry()
    resolver = AgentLoopResolver(registry, builtin_loop=_Loop())

    selection = resolver.resolve("anthropic", "claude")

    assert selection.scope == "builtin"
    assert selection.loop_id == "builtin-default"


@pytest.mark.unit
def test_resolution_never_pins_across_turns() -> None:
    registry = CapabilityRegistry()
    _register_loop(registry, "plugin-a", "deepseek", _Loop())
    resolver = AgentLoopResolver(registry)
    first = resolver.resolve("deepseek", "v3")

    _register_loop(registry, "plugin-b", "deepseek:v3", _Loop())
    second = resolver.resolve("deepseek", "v3")

    assert first.scope == "provider"
    assert second.scope == "model"


@pytest.mark.unit
def test_invalid_inputs_raise() -> None:
    resolver = AgentLoopResolver(CapabilityRegistry())

    with pytest.raises(AgentLoopResolutionError):
        resolver.resolve("", "v3")
    with pytest.raises(AgentLoopResolutionError):
        resolver.resolve("deepseek", "  ")


@pytest.mark.unit
def test_non_conforming_loop_rejected() -> None:
    with pytest.raises(AgentLoopResolutionError, match="no callable run"):
        validate_loop_implementation(object())


@pytest.mark.unit
def test_missing_everything_raises_actionable_error() -> None:
    resolver = AgentLoopResolver(CapabilityRegistry())

    with pytest.raises(AgentLoopResolutionError, match="no agent_loop capability"):
        resolver.resolve("openai", "gpt-5")
