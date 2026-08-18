"""Rollout parity evidence for typed agent events and tool generations."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import src.infrastructure.agent.actor.local_chat_worker as local_chat_worker_module
import src.infrastructure.agent.actor.project_agent_actor as project_agent_actor_module
import src.infrastructure.plugins.shadow_rollout as shadow_rollout_module
from src.domain.model.plugins import PluginEventMode
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository import (
    PlatformPluginRepository,
)
from src.infrastructure.agent.plugins.registry import HookDispatchResult
from src.infrastructure.plugins.agent_events import AgentPluginEventDispatcher
from src.infrastructure.plugins.agent_tools import AgentToolSetService
from src.infrastructure.plugins.context import PluginScopeContext
from src.infrastructure.plugins.events import PluginEventBus
from src.infrastructure.plugins.shadow_rollout import (
    ShadowRolloutWorker,
    enqueue_shadow_rollout_event,
    make_shadow_rollout_event,
    queued_event_count,
    reset_shadow_rollout_queue_for_test,
)


class ParityLegacyRegistry:
    """Apply one deterministic, mode-compatible transformation per hook."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def apply_hook(
        self,
        hook_name: str,
        *,
        payload: dict[str, Any],
        runtime_overrides: list[dict[str, Any]] | None = None,
    ) -> HookDispatchResult:
        self.calls.append(hook_name)
        if hook_name in {"before_prompt_build", "before_response", "before_tool_execution"}:
            return HookDispatchResult(payload={**payload, "rollout": "parity"}, diagnostics=[])
        if hook_name == "after_tool_execution":
            return HookDispatchResult(payload={**payload, "rollout": "parity"}, diagnostics=[])
        return HookDispatchResult(payload=dict(payload), diagnostics=[])


def parity_event_bus() -> PluginEventBus:
    bus = PluginEventBus()
    definitions = {
        name: bus.definition(name)
        for name in (
            "agent.before_step",
            "agent.before_request",
            "tools.before_execute",
            "tools.after_execute",
            "agent.after_turn",
        )
    }

    async def waterfall(payload: dict[str, Any]) -> dict[str, Any]:
        downstream = await payload["next"]()
        return {**downstream, "rollout": "parity"}

    async def serial(payload: dict[str, Any]) -> dict[str, Any]:
        return {**payload, "rollout": "parity"}

    async def observer(payload: dict[str, Any]) -> None:
        _ = payload

    for definition in definitions.values():
        handler = (
            waterfall
            if definition.mode == PluginEventMode.WATERFALL
            else serial
            if definition.mode == PluginEventMode.SERIAL
            else observer
        )
        bus.subscribe(definition.name, "typed-parity", handler)
    return bus


@pytest.mark.integration
async def test_all_migrated_agent_events_have_zero_shadow_diff() -> None:
    registry = ParityLegacyRegistry()
    cases = {
        "before_prompt_build": {"input": "goal"},
        "before_response": {"model": "demo"},
        "before_tool_execution": {"tool": "demo"},
        "after_tool_execution": {"result": "ok"},
        "after_turn_complete": {"turn": 3},
    }
    dispatcher = AgentPluginEventDispatcher(
        legacy_registry=registry,
        event_bus=parity_event_bus(),
        shadow_enabled=True,
    )

    results = [
        await dispatcher.dispatch(hook_name, payload) for hook_name, payload in cases.items()
    ]

    assert all(result.shadow_diff is not None for result in results)
    assert all(result.shadow_diff.equal for result in results)  # type: ignore[union-attr]
    assert all(result.payload["rollout"] == "parity" for result in results[:4])
    assert registry.calls == list(cases)


@pytest.mark.integration
async def test_v2_event_adapter_preserves_legacy_payload() -> None:
    registry = ParityLegacyRegistry()
    dispatcher = AgentPluginEventDispatcher(
        legacy_registry=registry,
        event_bus=PluginEventBus(),
        v2_enabled=True,
    )

    result = await dispatcher.dispatch("before_response", {"model": "demo"})

    assert result.payload == {"model": "demo", "rollout": "parity"}
    assert result.shadow_diff is None
    assert registry.calls == ["before_response"]


@pytest.mark.integration
def test_agent_tool_shadow_generation_has_zero_diff_until_inventory_changes() -> None:
    tool = SimpleNamespace(
        name="demo",
        description="Demo",
        parameters={"type": "object"},
    )
    changed = SimpleNamespace(
        name="demo",
        description="Changed",
        parameters={"type": "object"},
    )
    scope = PluginScopeContext(tenant_id="tenant", project_id="project")
    service = AgentToolSetService(profile_digest="rollout-profile")
    service.publish(scope, {"demo": tool}, profile_digest="rollout-profile")

    assert service.shadow_diff(scope, {"demo": tool}) is False
    assert service.shadow_diff(scope, {"demo": changed}) is True


@pytest.mark.integration
async def test_shadow_dispatcher_enqueues_durable_rollout_evidence() -> None:
    reset_shadow_rollout_queue_for_test()
    registry = ParityLegacyRegistry()
    dispatcher = AgentPluginEventDispatcher(
        legacy_registry=registry,
        event_bus=parity_event_bus(),
        shadow_enabled=True,
        scope_type="tenant",
        scope_id="tenant-rollout",
    )

    await dispatcher.dispatch("before_response", {"model": "demo"})

    assert queued_event_count() == 1
    # The dispatcher retains in-process detail for diagnosis, while the durable
    # queue record contains only typed scalar digests.
    assert dispatcher.shadow_diffs()[0].legacy_payload["model"] == "demo"


@pytest.mark.integration
async def test_shadow_rollout_repository_persists_and_summarizes_evidence(db_session) -> None:
    repository = PlatformPluginRepository(db_session)
    equal_event = make_shadow_rollout_event(
        capability="agent_events",
        event_name="agent.before_request",
        hook_name="before_response",
        scope_type="tenant",
        scope_id="tenant-rollout",
        equal=True,
        legacy_payload={"model": "demo", "rollout": "parity"},
        typed_payload={"model": "demo", "rollout": "parity"},
    )
    diff_event = make_shadow_rollout_event(
        capability="agent_tools",
        event_name="agent.tool_generation",
        hook_name="tool_generation",
        scope_type="project",
        scope_id="project-rollout",
        equal=False,
        legacy_payload={"demo": "Demo:Demo"},
        typed_payload={"demo": "Demo:Changed"},
    )

    await repository.record_shadow_rollout_events([equal_event.record(), diff_event.record()])
    events = await repository.list_shadow_rollout_events(limit=10)
    summary = {
        (row["capability"], row["event_name"]): row
        for row in await repository.shadow_rollout_summary()
    }
    event_rows = {(event.capability, event.event_name): event for event in events}

    assert len(events) == 2
    assert summary[("agent_events", "agent.before_request")]["equal"] is True
    assert summary[("agent_tools", "agent.tool_generation")]["equal"] is False
    assert event_rows[("agent_events", "agent.before_request")].scope_id == "tenant-rollout"
    assert event_rows[("agent_tools", "agent.tool_generation")].scope_id == "project-rollout"


@pytest.mark.integration
async def test_shadow_rollout_worker_batches_without_blocking_dispatch() -> None:
    reset_shadow_rollout_queue_for_test()
    persisted: list[list[dict[str, object]]] = []

    class FakeRepository:
        async def record_shadow_rollout_events(self, records: list[dict[str, object]]) -> object:
            persisted.append(records)
            return None

    class FakeSession:
        def __init__(self, repository: FakeRepository) -> None:
            self.repository = repository

        async def __aenter__(self) -> FakeSession:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def commit(self) -> None:
            return None

    repository = FakeRepository()
    worker = ShadowRolloutWorker(
        lambda: FakeSession(repository),
        repository_factory=lambda session: session.repository,
    )
    worker.start()
    enqueue_shadow_rollout_event(
        make_shadow_rollout_event(
            capability="agent_events",
            event_name="agent.before_request",
            hook_name="before_response",
            scope_type="tenant",
            scope_id="tenant-rollout",
            equal=True,
            legacy_payload={"model": "demo"},
            typed_payload={"model": "demo"},
        )
    )
    enqueue_shadow_rollout_event(
        make_shadow_rollout_event(
            capability="agent_tools",
            event_name="agent.tool_generation",
            hook_name="tool_generation",
            scope_type="project",
            scope_id="project-rollout",
            equal=False,
            legacy_payload={"demo": "Demo:Demo"},
            typed_payload={"demo": "Demo:Changed"},
        )
    )
    await worker.stop()

    assert len(persisted) == 1
    assert len(persisted[0]) == 2
    first_record = cast(dict[str, Any], persisted[0][0])
    assert isinstance(first_record["legacy_payload"]["model"], dict)
    assert first_record["legacy_payload"]["model"]["type"] == "str"
    assert len(first_record["legacy_payload"]["model"]["sha256"]) == 64
    assert queued_event_count() == 0


@pytest.mark.integration
async def test_ray_actor_runtime_owns_shadow_evidence_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_class = cast(
        type,
        project_agent_actor_module.ProjectAgentActor.__ray_actor_class__,
    )
    actor = actor_class()
    started: list[object] = []
    stopped: list[bool] = []

    def fake_initialize(session_factory: object) -> object:
        started.append(session_factory)
        return object()

    async def fake_shutdown() -> None:
        stopped.append(True)

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.startup.shadow_rollout."
        "initialize_shadow_rollout_worker",
        fake_initialize,
    )
    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.startup.shadow_rollout."
        "shutdown_shadow_rollout_worker",
        fake_shutdown,
    )

    await actor._ensure_shadow_rollout_runtime()
    await actor._shutdown_shadow_rollout_runtime()

    assert len(started) == 1
    assert stopped == [True]


@pytest.mark.integration
async def test_ray_actor_bootstrap_starts_shadow_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor_class = cast(
        type,
        project_agent_actor_module.ProjectAgentActor.__ray_actor_class__,
    )
    actor = actor_class()
    lifecycle: list[str] = []

    async def fake_ensure_shadow() -> None:
        lifecycle.append("shadow")

    monkeypatch.setattr(actor, "_ensure_shadow_rollout_runtime", fake_ensure_shadow)
    monkeypatch.setattr(
        project_agent_actor_module,
        "initialize_default_llm_providers",
        fake_noop,
    )
    monkeypatch.setattr(
        project_agent_actor_module,
        "create_native_graph_adapter",
        fake_graph_adapter,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.state.agent_worker_state.set_agent_graph_service",
        lambda value: None,
    )
    monkeypatch.setattr(
        project_agent_actor_module,
        "MCPSandboxAdapter",
        FakeSandboxAdapter,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.state.agent_worker_state.sync_mcp_sandbox_adapter_from_docker",
        fake_async_noop,
    )
    monkeypatch.setattr(
        project_agent_actor_module,
        "get_settings",
        lambda: SimpleNamespace(multi_agent_enabled=False),
    )

    await actor._bootstrap_runtime()

    assert lifecycle == ["shadow"]
    assert actor._bootstrapped is True


def fake_noop() -> None:
    return None


async def fake_async_noop() -> None:
    return None


async def fake_graph_adapter() -> object:
    return object()


class FakeSandboxAdapter:
    def __init__(self, **kwargs: object) -> None:
        _ = kwargs


@pytest.mark.integration
async def test_local_chat_subprocess_owns_shadow_evidence_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[object] = []
    stopped: list[bool] = []

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.startup.shadow_rollout."
        "initialize_shadow_rollout_worker",
        lambda session_factory: started.append(session_factory),
    )
    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.startup.shadow_rollout."
        "shutdown_shadow_rollout_worker",
        async_lambda(stopped),
    )

    local_chat_worker_module._initialize_local_shadow_rollout_writer()
    await local_chat_worker_module._shutdown_local_shadow_rollout_writer()

    assert len(started) == 1
    assert stopped == [True]


@pytest.mark.integration
async def test_local_chat_execution_drains_shadow_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.infrastructure.agent.actor.types import ProjectChatResult

    lifecycle: list[str] = []
    request_file = tmp_path / "request.json"
    request_file.write_text(
        json.dumps(
            {
                "config": {"tenant_id": "tenant", "project_id": "project"},
                "request": {
                    "conversation_id": "conversation",
                    "message_id": "message",
                    "user_message": "hello",
                    "user_id": "user",
                },
            }
        ),
        encoding="utf-8",
    )

    class FakeBootstrapper:
        async def _ensure_local_runtime_bootstrapped(self) -> None:
            lifecycle.append("local-runtime")

    class FakeAgent:
        def __init__(self, config: object) -> None:
            _ = config

        async def initialize(self) -> bool:
            return True

    async def fake_execute(
        agent: object,
        request: object,
        *,
        abort_signal: object,
    ) -> ProjectChatResult:
        return ProjectChatResult(
            conversation_id="conversation",
            message_id="message",
            content="ok",
        )

    monkeypatch.setattr(
        "src.application.services.agent.runtime_bootstrapper.AgentRuntimeBootstrapper",
        FakeBootstrapper,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.core.project_react_agent.ProjectReActAgent",
        FakeAgent,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.actor.execution.execute_project_chat",
        fake_execute,
    )
    monkeypatch.setattr(
        local_chat_worker_module,
        "_initialize_local_shadow_rollout_writer",
        lambda: lifecycle.append("start-shadow"),
    )

    async def stop_shadow() -> None:
        lifecycle.append("stop-shadow")

    monkeypatch.setattr(
        local_chat_worker_module,
        "_shutdown_local_shadow_rollout_writer",
        stop_shadow,
    )

    exit_code = await local_chat_worker_module._run(request_file)

    assert exit_code == 0
    assert lifecycle == ["start-shadow", "local-runtime", "stop-shadow"]
    assert not request_file.exists()


@pytest.mark.integration
def test_shadow_evidence_queue_fails_open_under_backpressure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shadow_rollout_module, "_queue", asyncio.Queue(maxsize=1))
    monkeypatch.setattr(shadow_rollout_module, "_dropped_events", 0)
    first = make_shadow_rollout_event(
        capability="agent_events",
        event_name="agent.before_request",
        hook_name="before_response",
        scope_type="tenant",
        scope_id="tenant-rollout",
        equal=True,
        legacy_payload={"model": "demo"},
        typed_payload={"model": "demo"},
    )
    second = make_shadow_rollout_event(
        capability="agent_tools",
        event_name="agent.tool_generation",
        hook_name="tool_generation",
        scope_type="project",
        scope_id="project-rollout",
        equal=False,
        legacy_payload={"demo": "Demo:Demo"},
        typed_payload={"demo": "Demo:Changed"},
    )

    assert enqueue_shadow_rollout_event(first) is True
    started = time.perf_counter_ns()
    assert enqueue_shadow_rollout_event(second) is False
    elapsed = time.perf_counter_ns() - started

    assert shadow_rollout_module.dropped_event_count() == 1
    assert elapsed < 10_000_000
    assert shadow_rollout_module.queued_event_count() == 1


def async_lambda(records: list[bool]):
    async def record() -> None:
        records.append(True)

    return record
