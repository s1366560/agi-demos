"""Unit tests for the I2 agent loop seam wiring in SessionProcessor."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.domain.events.agent_events import AgentStartEvent
from src.infrastructure.agent.processor.factory import ProcessorFactory, _default_loop_resolver
from src.infrastructure.agent.processor.processor import (
    ProcessorConfig,
    SessionProcessor,
)
from src.infrastructure.plugins.v2.agent_loop import (
    AgentLoopSelectionV2,
    BuiltinAgentLoopResolverV2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error


class _ExternalLoop:
    """Fake non-builtin loop driver capturing its dispatch context."""

    def __init__(self) -> None:
        self.contexts: list[object] = []

    async def run(self, context: object):
        self.contexts.append(context)
        yield {"type": "external_loop_event"}


class _StaticLoopResolverV2:
    def __init__(self, implementation: object) -> None:
        self._implementation = implementation

    def resolve(self, provider_id: str, model_id: str) -> AgentLoopSelectionV2:
        return AgentLoopSelectionV2(
            loop_id=f"{provider_id}:{model_id}",
            plugin_id="plugin-x",
            scope="model",
            implementation=self._implementation,
        )


class _FailingLoopResolverV2:
    def resolve(self, provider_id: str, model_id: str) -> AgentLoopSelectionV2:
        raise ValueError(f"no loop for {provider_id}/{model_id}")


@pytest.mark.unit
class TestAgentLoopWiring:
    def test_factory_default_resolver_requires_pinned_v2_operation(self) -> None:
        with pytest.raises(RuntimeV2Error) as error:
            _default_loop_resolver()

        assert error.value.code == "operation_context_not_pinned"

    def test_factory_main_processor_requires_pinned_v2_operation(self) -> None:
        config = ProcessorConfig(model="m", provider_id="provider")

        with pytest.raises(RuntimeV2Error) as error:
            ProcessorFactory().create_for_main(config, [])

        assert error.value.code == "operation_context_not_pinned"

    def test_resolve_fails_without_resolver(self) -> None:
        processor = SessionProcessor(config=ProcessorConfig(model="m"), tools=[])

        with pytest.raises(RuntimeV2Error) as error:
            processor._resolve_agent_loop()

        assert error.value.code == "agent_loop_resolver_missing"

    def test_resolve_fails_without_provider_id(self) -> None:
        resolver = MagicMock()
        processor = SessionProcessor(
            config=ProcessorConfig(model="m", loop_resolver=resolver),
            tools=[],
        )

        with pytest.raises(RuntimeV2Error) as error:
            processor._resolve_agent_loop()

        assert error.value.code == "agent_loop_provider_missing"
        resolver.resolve.assert_not_called()

    def test_resolve_fails_without_model_id(self) -> None:
        resolver = MagicMock()
        processor = SessionProcessor(
            config=ProcessorConfig(
                model="",
                provider_id="deepseek",
                loop_resolver=resolver,
            ),
            tools=[],
        )

        with pytest.raises(RuntimeV2Error) as error:
            processor._resolve_agent_loop()

        assert error.value.code == "agent_loop_model_missing"
        resolver.resolve.assert_not_called()

    def test_resolve_wraps_resolution_error_without_builtin_fallback(self) -> None:
        processor = SessionProcessor(
            config=ProcessorConfig(
                model="m",
                provider_id="deepseek",
                loop_resolver=_FailingLoopResolverV2(),
            ),
            tools=[],
        )

        with pytest.raises(RuntimeV2Error) as error:
            processor._resolve_agent_loop()

        assert error.value.code == "agent_loop_resolution_failed"
        assert isinstance(error.value.__cause__, ValueError)

    def test_resolve_returns_explicit_v2_builtin_selection(self) -> None:
        loop = _ExternalLoop()
        resolver = BuiltinAgentLoopResolverV2(
            loop_id="builtin-react",
            plugin_id="memstack-kernel",
            implementation=loop,
        )
        processor = SessionProcessor(
            config=ProcessorConfig(
                model="v3",
                provider_id="deepseek",
                loop_resolver=resolver,
            ),
            tools=[],
        )
        selection = processor._resolve_agent_loop()
        assert selection is not None
        assert selection.scope == "builtin"
        assert selection.implementation is loop

    async def test_process_keeps_explicit_v2_builtin_selection_on_native_path(self) -> None:
        loop = _ExternalLoop()
        resolver = BuiltinAgentLoopResolverV2(
            loop_id="builtin-react",
            plugin_id="memstack-kernel",
            implementation=loop,
        )
        processor = SessionProcessor(
            config=ProcessorConfig(
                model="v3",
                provider_id="deepseek",
                loop_resolver=resolver,
            ),
            tools=[],
        )

        events = processor.process("s1", [{"role": "user", "content": "hi"}])
        first = await anext(events)
        await events.aclose()

        assert isinstance(first, AgentStartEvent)
        assert processor._loop_selection is not None
        assert processor._loop_selection.scope == "builtin"
        assert loop.contexts == []

    async def test_process_dispatches_external_loop(self) -> None:
        loop = _ExternalLoop()
        processor = SessionProcessor(
            config=ProcessorConfig(
                model="v3",
                provider_id="deepseek",
                loop_resolver=_StaticLoopResolverV2(loop),
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
        processor = SessionProcessor(
            config=ProcessorConfig(
                model="v3",
                provider_id="deepseek",
                loop_resolver=_StaticLoopResolverV2(_ExternalLoop()),
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
