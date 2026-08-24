"""Protocol-v2 ownership of memory and skill-evolution Agent lifecycle effects."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.plugins.skill_evolution import plugin as skill_evolution_runtime
from src.infrastructure.plugins.v2.agent_lifecycle_runtime import (
    MEMORY_LIFECYCLE_MODULE_V2,
)
from src.infrastructure.plugins.v2.agent_runtime_dispatcher import PinnedAgentRuntimeDispatcherV2
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import GenerationManagerV2, LoaderV2

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


class _MemoryRuntime:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def recall_for_prompt(self, *, user_message: str, project_id: str):
        self.calls.append(f"recall:{project_id}:{user_message}")
        return SimpleNamespace(
            memory_context="generation-owned memory",
            emitted_events=[{"type": "memory_recalled"}],
        )

    async def flush_on_context_overflow(self, **_kwargs: object):
        self.calls.append("overflow")
        return SimpleNamespace(emitted_events=[{"type": "memory_flushed"}])

    async def capture_after_turn(self, **_kwargs: object):
        self.calls.append("capture")
        return SimpleNamespace(emitted_events=[{"type": "memory_captured"}])


class _Collector:
    def __init__(self) -> None:
        self.payload: dict[str, object] | None = None

    async def capture_from_hook(self, payload, *, session_factory):
        self.payload = dict(payload)
        assert session_factory == "session-factory"
        return []


def _scope() -> ScopeV2:
    return ScopeV2(
        kind=ScopeKindV2.SESSION,
        tenant_id="tenant-a",
        project_id="project-a",
        session_id="session-a",
    )


async def _manager(*, memory_enabled: bool = True) -> GenerationManagerV2:
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    document = load_profile_document_v2(_PROFILE_PATH)
    if not memory_enabled:
        document = replace(
            document,
            entries=tuple(
                replace(entry, enabled=False)
                if entry.module_ref == MEMORY_LIFECYCLE_MODULE_V2
                else entry
                for entry in document.entries
            ),
        )
    snapshot = compose_profile_v2(
        document,
        {manifest.plugin_id: manifest},
        generation=51,
    )
    generation = await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)
    manager = GenerationManagerV2()
    await manager.publish(generation)
    return manager


@pytest.mark.unit
async def test_memory_lifecycle_is_dispatched_only_by_enabled_v2_entry() -> None:
    dispatcher = PinnedAgentRuntimeDispatcherV2()
    runtime = _MemoryRuntime()
    manager = await _manager()
    try:
        async with pin_operation_context_v2(
            manager,
            operation_id="turn-a",
            scope=_scope(),
        ):
            before_prompt = await dispatcher.dispatch(
                "before_prompt_build",
                {
                    "tenant_id": "tenant-a",
                    "project_id": "project-a",
                    "conversation_id": "session-a",
                    "user_message": "hello",
                    "conversation_context": [],
                    "memory_context": None,
                    "memory_runtime": runtime,
                    "mode": "chat",
                    "matched_skill_name": None,
                    "selected_agent_id": "builtin:all-access",
                    "selected_agent_name": "All Access",
                },
            )
            overflow = await dispatcher.dispatch(
                "on_context_overflow",
                {
                    "tenant_id": "tenant-a",
                    "project_id": "project-a",
                    "conversation_id": "session-a",
                    "conversation_context": [],
                    "memory_runtime": runtime,
                    "compression_level": "summary",
                    "summary_text": "summary",
                    "original_message_count": 4,
                    "final_message_count": 2,
                    "summarized_message_count": 2,
                    "estimated_tokens": 20,
                },
            )
            after_turn = await dispatcher.dispatch(
                "after_turn_complete",
                {
                    "tenant_id": "tenant-a",
                    "project_id": "project-a",
                    "conversation_id": "session-a",
                    "conversation_context": [],
                    "memory_runtime": runtime,
                    "user_message": "hello",
                    "final_content": "done",
                    "matched_skill_name": None,
                    "success": True,
                    "execution_time_ms": 10,
                    "tool_call_count": 0,
                    "llm_client_override": None,
                },
            )
    finally:
        await manager.close()

    assert runtime.calls == ["recall:project-a:hello", "overflow", "capture"]
    assert before_prompt.payload["memory_context"] == "generation-owned memory"
    assert before_prompt.payload["emitted_events"] == [{"type": "memory_recalled"}]
    assert overflow.payload["emitted_events"] == [{"type": "memory_flushed"}]
    assert after_turn.payload["emitted_events"] == [{"type": "memory_captured"}]


@pytest.mark.unit
async def test_disabling_memory_lifecycle_entry_removes_behavior_without_fallback() -> None:
    dispatcher = PinnedAgentRuntimeDispatcherV2()
    runtime = _MemoryRuntime()
    manager = await _manager(memory_enabled=False)
    try:
        async with pin_operation_context_v2(
            manager,
            operation_id="turn-a",
            scope=_scope(),
        ):
            result = await dispatcher.dispatch(
                "before_prompt_build",
                {
                    "tenant_id": "tenant-a",
                    "project_id": "project-a",
                    "conversation_id": "session-a",
                    "user_message": "hello",
                    "conversation_context": [],
                    "memory_context": None,
                    "memory_runtime": runtime,
                    "mode": "chat",
                    "matched_skill_name": None,
                    "selected_agent_id": "builtin:all-access",
                    "selected_agent_name": "All Access",
                },
            )
    finally:
        await manager.close()

    assert runtime.calls == []
    assert result.payload["memory_context"] is None
    assert result.payload.get("emitted_events") is None


@pytest.mark.unit
async def test_skill_evolution_attribution_flows_through_v2_events(monkeypatch) -> None:
    collector = _Collector()
    monkeypatch.setattr(skill_evolution_runtime, "_collector", collector)
    monkeypatch.setattr(skill_evolution_runtime, "_session_factory", "session-factory")
    monkeypatch.setattr(skill_evolution_runtime, "_scheduler", None)
    skill_evolution_runtime._loaded_skill_names_by_turn.clear()
    skill_evolution_runtime._tool_events_by_turn.clear()

    dispatcher = PinnedAgentRuntimeDispatcherV2()
    manager = await _manager()
    try:
        async with pin_operation_context_v2(
            manager,
            operation_id="turn-a",
            scope=_scope(),
        ):
            await dispatcher.dispatch(
                "after_tool_execution",
                {
                    "tenant_id": "tenant-a",
                    "project_id": "project-a",
                    "conversation_id": "session-a",
                    "tool_name": "skill_loader",
                    "call_id": "call-a",
                    "result": "loaded",
                    "result_metadata": {"name": "review"},
                },
            )
            await dispatcher.dispatch(
                "after_turn_complete",
                {
                    "tenant_id": "tenant-a",
                    "project_id": "project-a",
                    "conversation_id": "session-a",
                    "conversation_context": [],
                    "memory_runtime": None,
                    "user_message": "review this",
                    "final_content": "done",
                    "matched_skill_name": None,
                    "success": True,
                    "execution_time_ms": 10,
                    "tool_call_count": 1,
                    "llm_client_override": None,
                },
            )
    finally:
        await manager.close()

    assert collector.payload is not None
    assert collector.payload["loaded_skill_names"] == ["review"]
    assert collector.payload["tool_events"][0]["tool_name"] == "skill_loader"
