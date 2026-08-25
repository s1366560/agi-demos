"""V2 lifecycle and authority coverage for the Reflection runtime."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.infrastructure.adapters.secondary.in_memory.friction_loop import InMemoryFrictionLedger
from src.infrastructure.plugins.v2 import reflection_runtime as runtime_module
from src.infrastructure.plugins.v2.artifact_content_gc_runtime import (
    ASYNC_SESSION_FACTORY_MODULE_V2,
)
from src.infrastructure.plugins.v2.boundary import (
    clear_process_generation_host_v2,
    current_generation_descriptor_v2,
    current_operation_context_v2,
    install_process_generation_host_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.llm_client_service import TENANT_LLM_CLIENT_FACTORY_MODULE_V2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.reflection_runtime import (
    REFLECTION_COMPLETE_EVENT_V2,
    REFLECTION_RUNTIME_LLM_CLIENTS_INJECT_V2,
    REFLECTION_RUNTIME_MODULE_V2,
    REFLECTION_RUNTIME_SERVICE_V2,
    REFLECTION_RUNTIME_SESSIONS_INJECT_V2,
    ReflectionRuntimeManagerV2,
    ReflectionRuntimeServiceProtocolV2,
    ReflectionRuntimeServiceV2,
)
from src.infrastructure.plugins.v2.runtime import LoaderV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


class _FakeRunner:
    def __init__(
        self,
        lifecycle: list[str],
        *,
        fail_start: bool = False,
        **kwargs: Any,
    ) -> None:
        self.lifecycle = lifecycle
        self.fail_start = fail_start
        self.kwargs = kwargs

    def start(self) -> None:
        self.lifecycle.append("start")
        if self.fail_start:
            raise RuntimeError("reflection runner unavailable")

    async def stop(self) -> None:
        self.lifecycle.append("stop")


def _runner_factory(
    lifecycle: list[str],
    created: list[_FakeRunner],
    *,
    fail_start: bool = False,
):
    def factory(**kwargs: Any) -> _FakeRunner:
        runner = _FakeRunner(lifecycle, fail_start=fail_start, **kwargs)
        created.append(runner)
        return runner

    return factory


async def test_reflection_runtime_is_reference_counted_across_generation_leases() -> None:
    lifecycle: list[str] = []
    created: list[_FakeRunner] = []
    runtime = ReflectionRuntimeManagerV2(
        redis_client=object(),
        runner_factory=_runner_factory(lifecycle, created),
    )
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(reflection_runtime_manager=runtime)
    )

    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=151,
        version=151,
    )
    assert first.accepted is True
    old_lease = await host.acquire()
    old_generation = await old_lease.__aenter__()
    old_service = old_generation.resolve(
        REFLECTION_RUNTIME_SERVICE_V2,
        old_generation.snapshot.entries[0].scope,
    )
    assert isinstance(old_service, ReflectionRuntimeServiceProtocolV2)

    second = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=152,
        version=152,
    )

    assert second.accepted is True
    assert runtime.generation_references == 2
    assert lifecycle == ["start"]
    assert len(created) == 1

    await old_lease.__aexit__(None, None, None)
    assert runtime.generation_references == 1
    assert lifecycle == ["start"]

    await host.close()
    assert runtime.generation_references == 0
    assert lifecycle == ["start", "stop"]


async def test_reflection_runtime_start_failure_nacks_and_cleans_candidate() -> None:
    lifecycle: list[str] = []
    created: list[_FakeRunner] = []
    runtime = ReflectionRuntimeManagerV2(
        redis_client=object(),
        runner_factory=_runner_factory(lifecycle, created, fail_start=True),
    )
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(reflection_runtime_manager=runtime)
    )

    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=153,
        version=153,
    )

    assert publication.accepted is False
    assert publication.receipt.error_code == "staging_failed"
    assert host.manager.current is None
    assert runtime.generation_references == 0
    assert lifecycle == ["start", "stop"]


async def test_reflection_runtime_owns_lane_order_and_durable_ingest() -> None:
    lifecycle: list[str] = []
    created: list[_FakeRunner] = []
    ledger = InMemoryFrictionLedger()
    runtime = ReflectionRuntimeManagerV2(
        redis_client=object(),
        runner_factory=_runner_factory(lifecycle, created),
        ledger_factory=lambda _redis: ledger,
    )
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(reflection_runtime_manager=runtime)
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=156,
        version=156,
    )
    assert publication.accepted is True
    lease = await host.acquire()
    generation = await lease.__aenter__()
    service = generation.resolve(
        REFLECTION_RUNTIME_SERVICE_V2,
        generation.snapshot.entries[0].scope,
    )
    assert isinstance(service, ReflectionRuntimeServiceV2)

    signal = await service.record_lane_change(
        project_id="project-a",
        task_id="task-a",
        from_lane="executing",
        to_lane="todo",
    )
    forward = await service.record_lane_change(
        project_id="project-a",
        task_id="task-b",
        from_lane="todo",
        to_lane="executing",
    )

    assert signal is not None
    assert signal.kind.value == "bounce"
    assert forward is None
    assert len(await ledger.query_window("project-a")) == 1
    await lease.__aexit__(None, None, None)
    await host.close()


async def test_reflection_completion_is_dispatched_through_declared_serial_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle: list[str] = []
    created: list[_FakeRunner] = []
    publisher = AsyncMock(return_value=None)
    monkeypatch.setattr(runtime_module, "_publish_reflection_complete_v2", publisher)
    runtime = ReflectionRuntimeManagerV2(
        redis_client=object(),
        runner_factory=_runner_factory(lifecycle, created),
        ledger_factory=lambda _redis: InMemoryFrictionLedger(),
    )
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(reflection_runtime_manager=runtime)
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=157,
        version=157,
    )
    assert publication.accepted is True
    lease = await host.acquire()
    generation = await lease.__aenter__()
    service = generation.resolve(
        REFLECTION_RUNTIME_SERVICE_V2,
        generation.snapshot.entries[0].scope,
    )
    assert isinstance(service, ReflectionRuntimeServiceV2)

    await service._emit_completion(
        project_id="project-a",
        verdicts=[],
        status="success",
        source="tool",
        run_id="run-a",
    )

    publisher.assert_awaited_once()
    payload = publisher.await_args.args[1]
    assert payload["project_id"] == "project-a"
    assert payload["run_id"] == "run-a"
    assert payload["status"] == "success"
    await lease.__aexit__(None, None, None)
    await host.close()


async def test_reflection_sweep_boundary_pins_short_generation_and_operation_lease() -> None:
    lifecycle: list[str] = []
    created: list[_FakeRunner] = []
    runtime = ReflectionRuntimeManagerV2(
        redis_client=object(),
        runner_factory=_runner_factory(lifecycle, created),
    )
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(reflection_runtime_manager=runtime)
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=154,
        version=154,
    )
    assert publication.accepted is True
    install_process_generation_host_v2(host)
    try:
        boundary = created[0].kwargs["sweep_context_factory"]
        async with boundary():
            descriptor = current_generation_descriptor_v2()
            operation = current_operation_context_v2()
            assert descriptor.generation == 154
            assert operation.context.scope.kind is ScopeKindV2.ROOT
            assert operation.operation_id.startswith("reflection-sweep:")
    finally:
        clear_process_generation_host_v2(host)
        await host.close()


@pytest.mark.parametrize(
    ("missing_module", "missing_service"),
    (
        (ASYNC_SESSION_FACTORY_MODULE_V2, "service:persistence.async-session-factory"),
        (TENANT_LLM_CLIENT_FACTORY_MODULE_V2, "service:llm.tenant-client-factory"),
    ),
)
async def test_reflection_runtime_rejects_missing_required_inject_without_fallback(
    missing_module: str,
    missing_service: str,
) -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    keep = {
        "builtin://memstack/runtime/generation-boundary",
        ASYNC_SESSION_FACTORY_MODULE_V2,
        TENANT_LLM_CLIENT_FACTORY_MODULE_V2,
        REFLECTION_RUNTIME_MODULE_V2,
    }
    minimal = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False) if entry.module_ref == missing_module else entry
            for entry in document.entries
            if entry.module_ref in keep
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(minimal, {manifest.plugin_id: manifest}, generation=155)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert missing_service in str(error.value)
    assert "builtin-reflection-runtime" in str(error.value)


def test_reflection_contract_and_static_authority_retirement_are_explicit() -> None:
    profile = load_profile_document_v2(_PROFILE_PATH)
    entry = next(
        item for item in profile.entries if item.module_ref == REFLECTION_RUNTIME_MODULE_V2
    )
    manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    module = next(
        item for item in manifest["modules"] if item["module_ref"] == REFLECTION_RUNTIME_MODULE_V2
    )
    main_source = (_ROOT / "src/infrastructure/adapters/primary/web/main.py").read_text(
        encoding="utf-8"
    )
    container_source = (_ROOT / "src/configuration/di_container.py").read_text(encoding="utf-8")
    friction_source = (_ROOT / "src/application/services/friction_runtime.py").read_text(
        encoding="utf-8"
    )
    tool_source = (_ROOT / "src/infrastructure/agent/tools/reflection_tool.py").read_text(
        encoding="utf-8"
    )
    react_source = (_ROOT / "src/infrastructure/agent/core/react_agent.py").read_text(
        encoding="utf-8"
    )

    assert entry.inject == {
        REFLECTION_RUNTIME_SESSIONS_INJECT_V2: "service:persistence.async-session-factory",
        REFLECTION_RUNTIME_LLM_CLIENTS_INJECT_V2: "service:llm.tenant-client-factory",
    }
    assert entry.restart_policy.value == "process-boundary"
    assert entry.config == {
        "strategy": "periodic-reflection",
        "enabled": True,
        "interval_seconds": 600,
        "per_project_timeout_seconds": 60,
        "window_minutes": 1440,
        "lane_order": [
            "todo",
            "dispatched",
            "executing",
            "reported",
            "adjudicating",
            "done",
        ],
    }
    assert module["contract"]["events"]["emits"][0]["event"] == REFLECTION_COMPLETE_EVENT_V2
    assert module["contract"]["events"]["handles"][0]["event"] == REFLECTION_COMPLETE_EVENT_V2
    assert "reflection_runtime_manager=reflection_runtime_manager" in main_source
    assert "configure_friction_ingest" not in main_source
    assert "configure_reflection_tool" not in main_source
    assert "app.state.reflection_runner" not in main_source
    assert "def reflection_service(" not in container_source
    assert "def reflection_runner(" not in container_source
    assert "def lane_experience_service(" not in container_source
    assert "_ledger" not in friction_source
    assert "configure_friction_ingest" not in friction_source
    assert "configure_reflection_tool" not in tool_source
    assert "_provider" not in tool_source
    assert "get_friction_ledger" not in react_source
    assert "SqlPlaybookRepository" not in react_source
