"""Unit tests for the I2 agent loop seam wiring in SessionProcessor."""

from __future__ import annotations

import pytest

from src.domain.events.agent_events import AgentStartEvent
from src.domain.model.plugins import (
    CapabilityKind,
    PluginManifest,
    PluginRuntimeKind,
    PluginTrust,
    ProvidedCapability,
)
from src.infrastructure.agent.processor.factory import _default_loop_resolver
from src.infrastructure.agent.processor.processor import (
    ProcessorConfig,
    SessionProcessor,
)
from src.infrastructure.plugins.agent_loop_runtime import (
    AgentLoopResolver,
)
from src.infrastructure.plugins.context import CapabilityRegistry, PluginContext


class _ExternalLoop:
    """Fake non-builtin loop driver capturing its dispatch context."""

    def __init__(self) -> None:
        self.contexts: list[object] = []

    async def run(self, context: object):
        self.contexts.append(context)
        yield {"type": "external_loop_event"}


def _register_loop(
    registry: CapabilityRegistry,
    plugin_id: str,
    capability_id: str,
    implementation: object,
    *,
    trust: PluginTrust = PluginTrust.SIGNED,
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
class TestAgentLoopWiring:
    def test_factory_default_resolver_comes_from_runtime_host(self) -> None:
        resolver = _default_loop_resolver()
        assert isinstance(resolver, AgentLoopResolver)

    def test_resolve_returns_none_without_resolver(self) -> None:
        processor = SessionProcessor(config=ProcessorConfig(model="m"), tools=[])
        assert processor._resolve_agent_loop() is None

    def test_resolve_returns_none_without_provider_id(self) -> None:
        processor = SessionProcessor(
            config=ProcessorConfig(
                model="m", loop_resolver=AgentLoopResolver(CapabilityRegistry())
            ),
            tools=[],
        )
        assert processor._resolve_agent_loop() is None

    def test_resolve_falls_back_to_none_on_resolution_error(self) -> None:
        # Empty registry with no builtin default -> resolution error -> builtin path.
        processor = SessionProcessor(
            config=ProcessorConfig(
                model="m",
                provider_id="deepseek",
                loop_resolver=AgentLoopResolver(CapabilityRegistry()),
            ),
            tools=[],
        )
        assert processor._resolve_agent_loop() is None

    def test_resolve_returns_builtin_selection(self) -> None:
        registry = CapabilityRegistry()
        _register_loop(
            registry, "memstack-kernel", "default", _ExternalLoop(), trust=PluginTrust.BUILTIN
        )
        processor = SessionProcessor(
            config=ProcessorConfig(
                model="v3",
                provider_id="deepseek",
                loop_resolver=AgentLoopResolver(registry),
            ),
            tools=[],
        )
        selection = processor._resolve_agent_loop()
        assert selection is not None
        assert selection.scope == "builtin"

    async def test_process_dispatches_external_loop(self) -> None:
        registry = CapabilityRegistry()
        loop = _ExternalLoop()
        _register_loop(registry, "plugin-x", "deepseek:v3", loop)
        processor = SessionProcessor(
            config=ProcessorConfig(
                model="v3",
                provider_id="deepseek",
                loop_resolver=AgentLoopResolver(registry),
            ),
            tools=[],
        )

        events = [
            event async for event in processor.process("s1", [{"role": "user", "content": "hi"}])
        ]

        assert isinstance(events[0], AgentStartEvent)
        assert {"type": "external_loop_event"} in events
        assert loop.contexts, "external loop driver was not invoked"
        context = loop.contexts[0]
        assert context["session_id"] == "s1"
        assert context["messages"] == [{"role": "user", "content": "hi"}]
        assert processor._loop_selection is not None
        assert processor._loop_selection.scope == "model"

    async def test_execution_summary_records_loop_selection(self) -> None:
        registry = CapabilityRegistry()
        _register_loop(registry, "plugin-x", "deepseek:v3", _ExternalLoop())
        processor = SessionProcessor(
            config=ProcessorConfig(
                model="v3",
                provider_id="deepseek",
                loop_resolver=AgentLoopResolver(registry),
            ),
            tools=[],
        )
        processor._loop_selection = processor._resolve_agent_loop()
        summary = await processor._build_execution_summary("s1")
        assert summary["agent_loop"] == {
            "loop_id": "deepseek:v3",
            "plugin_id": "plugin-x",
            "scope": "model",
        }
