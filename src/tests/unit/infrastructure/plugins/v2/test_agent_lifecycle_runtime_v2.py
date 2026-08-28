"""Protocol-v2 ownership of memory and skill-evolution Agent lifecycle effects."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2 import skill_evolution_runtime as skill_evolution_runtime_v2
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


class _SchedulerPlugin:
    def __init__(self) -> None:
        self.loaded_skill_names_by_turn: dict[str, list[str]] = {}
        self.tool_events_by_turn: dict[str, list[dict[str, object]]] = {}
        self.capture_payload: dict[str, object] | None = None

    async def on_enable(self) -> None:
        return None

    async def on_disable(self) -> None:
        return None

    def schedule_evolution(self, **_kwargs: object) -> dict[str, object]:
        return {"scheduled": True}

    async def record_tool_event(self, payload: dict[str, object]) -> dict[str, object]:
        updated = dict(payload)
        conversation_id = str(payload.get("conversation_id", ""))
        self.tool_events_by_turn.setdefault(conversation_id, []).append(
            {"tool_name": payload.get("tool_name")}
        )
        metadata = payload.get("result_metadata")
        if isinstance(metadata, dict) and isinstance(metadata.get("name"), str):
            self.loaded_skill_names_by_turn.setdefault(conversation_id, []).append(
                str(metadata["name"])
            )
        return updated

    async def capture_turn(self, payload: dict[str, object]) -> dict[str, object]:
        updated = dict(payload)
        conversation_id = str(payload.get("conversation_id", ""))
        loaded = self.loaded_skill_names_by_turn.pop(conversation_id, [])
        events = self.tool_events_by_turn.pop(conversation_id, [])
        if loaded:
            updated["loaded_skill_names"] = loaded
        if events:
            updated["tool_events"] = events
        self.capture_payload = updated
        return updated


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
    plugin = _SchedulerPlugin()
    monkeypatch.setattr(
        skill_evolution_runtime_v2,
        "build_skill_evolution_runtime",
        lambda **_kwargs: plugin,
    )

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

    assert plugin.capture_payload is not None
    assert plugin.capture_payload["loaded_skill_names"] == ["review"]
    assert plugin.capture_payload["tool_events"][0]["tool_name"] == "skill_loader"
