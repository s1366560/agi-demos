"""V2 Provider/Consumer authority for ProjectReActAgent lifecycle notifications."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.domain.model.plugins.generated_v2 import EventModeV2, ScopeKindV2, ScopeV2
from src.infrastructure.agent.core import project_react_agent
from src.infrastructure.plugins.v2.agent_lifecycle_notifier import (
    AGENT_LIFECYCLE_CHANGED_EVENT_V2,
    AGENT_LIFECYCLE_NOTIFIER_MODULE_V2,
    AGENT_LIFECYCLE_NOTIFIER_SERVICE_V2,
    AGENT_SUBAGENT_LIFECYCLE_EVENT_V2,
    AgentLifecycleNotifierV2,
)
from src.infrastructure.plugins.v2.agent_loop import (
    AGENT_LOOP_MODULE_V2,
    AGENT_LOOP_RESOLVER_SERVICE_V2,
    BuiltinAgentLoopResolverV2,
)
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import GenerationManagerV2, LoaderV2, RuntimeV2Error

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


class _ConnectionManager:
    def __init__(self, *, result: int = 1, fail: bool = False) -> None:
        self.result = result
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    async def broadcast_to_project(
        self,
        *,
        tenant_id: str,
        project_id: str,
        message: dict[str, Any],
    ) -> int:
        if self.fail:
            raise RuntimeError("websocket unavailable")
        self.calls.append(
            {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "message": message,
            }
        )
        return self.result


class _AlternativeAgentLoopResolver:
    """Structural service implementation used to guard the Consumer seam."""

    def __init__(self, lifecycle_notifier: AgentLifecycleNotifierV2) -> None:
        self.lifecycle_notifier = lifecycle_notifier

    def resolve(self, _provider_id: str, _model_id: str) -> object:
        return object()


def _scope() -> ScopeV2:
    return ScopeV2(
        kind=ScopeKindV2.SESSION,
        tenant_id="tenant-a",
        project_id="project-a",
        session_id="session-a",
    )


def _snapshot(*, notifier_enabled: bool = True, loop_enabled: bool = True):
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    document = load_profile_document_v2(_PROFILE_PATH)
    selected_modules = {
        "builtin://memstack/runtime/generation-boundary",
        AGENT_LIFECYCLE_NOTIFIER_MODULE_V2,
        AGENT_LOOP_MODULE_V2,
    }
    entries = []
    for entry in document.entries:
        if entry.module_ref not in selected_modules:
            continue
        enabled = entry.enabled
        if entry.module_ref == AGENT_LIFECYCLE_NOTIFIER_MODULE_V2:
            enabled = notifier_enabled
        elif entry.module_ref == AGENT_LOOP_MODULE_V2:
            enabled = loop_enabled
        entries.append(replace(entry, enabled=enabled))
    return compose_profile_v2(
        replace(document, entries=tuple(entries)),
        {manifest.plugin_id: manifest},
        generation=73,
    )


async def _manager(
    connection_manager: _ConnectionManager | None,
) -> GenerationManagerV2:
    generation = await LoaderV2(
        builtin_runtime_definitions_v2(
            agent_lifecycle_connection_manager=connection_manager,
        )
    ).stage(_snapshot())
    manager = GenerationManagerV2()
    await manager.publish(generation)
    return manager


@pytest.mark.unit
async def test_agent_loop_receives_generation_owned_lifecycle_notifier() -> None:
    connections = _ConnectionManager(result=2)
    manager = await _manager(connections)
    try:
        async with pin_operation_context_v2(
            manager,
            operation_id="turn-a",
            scope=_scope(),
        ) as operation:
            resolver = operation.require(AGENT_LOOP_RESOLVER_SERVICE_V2)
            assert isinstance(resolver, BuiltinAgentLoopResolverV2)
            assert isinstance(resolver.lifecycle_notifier, AgentLifecycleNotifierV2)
            assert project_react_agent.get_websocket_notifier() is resolver.lifecycle_notifier

            notified = await resolver.lifecycle_notifier.notify_ready(
                tenant_id="tenant-a",
                project_id="project-a",
                tool_count=4,
                builtin_tool_count=3,
                mcp_tool_count=1,
                skill_count=2,
                total_skill_count=5,
                loaded_skill_count=2,
                subagent_count=1,
            )
    finally:
        await manager.close()

    assert notified == 2
    assert connections.calls == [
        {
            "tenant_id": "tenant-a",
            "project_id": "project-a",
            "message": {
                "type": "lifecycle_state_change",
                "tenant_id": "tenant-a",
                "project_id": "project-a",
                "data": {
                    "lifecycle_state": "ready",
                    "is_initialized": True,
                    "is_active": True,
                    "tool_count": 4,
                    "builtin_tool_count": 3,
                    "mcp_tool_count": 1,
                    "skill_count": 2,
                    "total_skill_count": 5,
                    "loaded_skill_count": 2,
                    "subagent_count": 1,
                },
                "timestamp": connections.calls[0]["message"]["timestamp"],
            },
        }
    ]


@pytest.mark.unit
async def test_lifecycle_consumer_accepts_structural_agent_loop_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = await _manager(None)
    try:
        async with pin_operation_context_v2(
            manager,
            operation_id="turn-a",
            scope=_scope(),
        ) as operation:
            notifier = operation.require(AGENT_LIFECYCLE_NOTIFIER_SERVICE_V2)
            assert isinstance(notifier, AgentLifecycleNotifierV2)
            alternative = _AlternativeAgentLoopResolver(notifier)
            monkeypatch.setattr(
                project_react_agent,
                "current_operation_context_v2",
                lambda: SimpleNamespace(require=lambda _service: alternative),
            )

            assert project_react_agent.get_websocket_notifier() is notifier
    finally:
        await manager.close()


@pytest.mark.unit
async def test_subagent_lifecycle_uses_declared_emit_event() -> None:
    connections = _ConnectionManager(result=3)
    manager = await _manager(connections)
    try:
        async with pin_operation_context_v2(
            manager,
            operation_id="turn-a",
            scope=_scope(),
        ) as operation:
            notifier = operation.require(AGENT_LIFECYCLE_NOTIFIER_SERVICE_V2)
            assert isinstance(notifier, AgentLifecycleNotifierV2)
            notified = await notifier.notify_subagent_lifecycle_event(
                tenant_id="tenant-a",
                project_id="project-a",
                event={"type": "subagent_spawned", "run_id": "run-a"},
            )
    finally:
        await manager.close()

    assert notified == 3
    assert connections.calls[0]["message"]["type"] == "subagent_lifecycle"
    assert connections.calls[0]["message"]["data"] == {
        "type": "subagent_spawned",
        "run_id": "run-a",
    }


@pytest.mark.unit
@pytest.mark.parametrize("connection_manager", [None, _ConnectionManager(fail=True)])
async def test_worker_or_broadcast_failure_returns_zero_without_fallback(
    connection_manager: _ConnectionManager | None,
) -> None:
    manager = await _manager(connection_manager)
    try:
        async with pin_operation_context_v2(
            manager,
            operation_id="turn-a",
            scope=_scope(),
        ) as operation:
            notifier = operation.require(AGENT_LIFECYCLE_NOTIFIER_SERVICE_V2)
            assert isinstance(notifier, AgentLifecycleNotifierV2)
            notified = await notifier.notify_initializing(
                tenant_id="tenant-a",
                project_id="project-a",
            )
    finally:
        await manager.close()

    assert notified == 0


@pytest.mark.unit
async def test_agent_loop_fails_preflight_when_notifier_entry_is_disabled() -> None:
    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(_snapshot(notifier_enabled=False))

    assert error.value.code == "missing_inject_provider"
    assert AGENT_LIFECYCLE_NOTIFIER_SERVICE_V2 in str(error.value)


@pytest.mark.unit
async def test_notifier_lookup_only_returns_none_without_pinned_operation() -> None:
    assert project_react_agent.get_websocket_notifier() is None

    generation = await LoaderV2(builtin_runtime_definitions_v2()).stage(
        _snapshot(loop_enabled=False)
    )
    manager = GenerationManagerV2()
    await manager.publish(generation)
    try:
        async with pin_operation_context_v2(
            manager,
            operation_id="turn-a",
            scope=_scope(),
        ):
            with pytest.raises(RuntimeV2Error) as error:
                project_react_agent.get_websocket_notifier()
    finally:
        await manager.close()

    assert error.value.code == "missing_service"


@pytest.mark.unit
def test_manifest_fixes_lifecycle_event_modes_and_loop_injection() -> None:
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    notifier_module = next(
        module
        for module in manifest.modules
        if module.module_ref == AGENT_LIFECYCLE_NOTIFIER_MODULE_V2
    )
    loop_module = next(
        module for module in manifest.modules if module.module_ref == AGENT_LOOP_MODULE_V2
    )
    event_names = {
        AGENT_LIFECYCLE_CHANGED_EVENT_V2,
        AGENT_SUBAGENT_LIFECYCLE_EVENT_V2,
    }

    assert {item.service for item in notifier_module.contract.services.provides} == {
        AGENT_LIFECYCLE_NOTIFIER_SERVICE_V2
    }
    assert {item.event for item in notifier_module.contract.events.emits} == event_names
    assert {item.event for item in notifier_module.contract.events.handles} == event_names
    assert all(
        item.mode is EventModeV2.EMIT
        for item in (
            *notifier_module.contract.events.emits,
            *notifier_module.contract.events.handles,
        )
    )
    assert {(item.alias, item.service) for item in loop_module.contract.services.requires} == {
        ("lifecycle_notifier", AGENT_LIFECYCLE_NOTIFIER_SERVICE_V2)
    }

    profile = load_profile_document_v2(_PROFILE_PATH)
    loop_entry = next(
        entry for entry in profile.entries if entry.module_ref == AGENT_LOOP_MODULE_V2
    )
    assert loop_entry.inject == {
        "lifecycle_notifier": AGENT_LIFECYCLE_NOTIFIER_SERVICE_V2,
    }


@pytest.mark.unit
def test_static_websocket_registration_authority_is_retired() -> None:
    startup_root = _ROOT / "src/infrastructure/adapters/primary/web/startup"
    main_source = (_ROOT / "src/infrastructure/adapters/primary/web/main.py").read_text(
        encoding="utf-8"
    )

    assert "register_websocket_manager" not in vars(project_react_agent)
    assert "_websocket_manager" not in vars(project_react_agent)
    assert not (startup_root / "websocket.py").exists()
    assert "initialize_websocket_manager" not in (startup_root / "__init__.py").read_text(
        encoding="utf-8"
    )
    assert "agent_lifecycle_connection_manager=get_connection_manager()" in main_source
