"""V2 Consumer coverage for generation-owned Agent Worker sandbox runtime."""

from __future__ import annotations

import json
from dataclasses import replace
from inspect import getsource
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.application.services.agent.runtime_bootstrapper import AgentRuntimeBootstrapper
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.ports.services.sandbox_port import SandboxConnectionError
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter
from src.infrastructure.agent.actor import local_chat_worker, project_agent_actor
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry
from src.infrastructure.plugins.v2 import agent_worker_runtime
from src.infrastructure.plugins.v2.agent_orchestration_runtime import (
    AGENT_ORCHESTRATION_RUNTIME_MODULE_V2,
    AgentOrchestrationRuntimeProtocolV2,
)
from src.infrastructure.plugins.v2.agent_worker_runtime import (
    AGENT_WORKER_RUNTIME_MODULE_V2,
    AGENT_WORKER_RUNTIME_SERVICE_V2,
    AgentWorkerRuntimeResolverProtocolV2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.sandbox_runtime import SANDBOX_RUNTIME_MODULE_V2
from src.infrastructure.plugins.v2.subagent_run_registry_service import (
    SUBAGENT_RUN_REGISTRY_MODULE_V2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


class _TrackedSandboxAdapter(MCPSandboxAdapter):
    def __init__(self) -> None:
        self.close_calls = 0

    async def sync_from_docker(self) -> int:
        return 0

    async def close(self) -> None:
        self.close_calls += 1


async def test_agent_worker_runtime_resolves_adapter_from_exact_generation() -> None:
    adapter = _TrackedSandboxAdapter()
    run_registry = SubAgentRunRegistry()
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(
            sandbox_runtime_factory=lambda: adapter,
            subagent_run_registry_factory=lambda _config: run_registry,
        )
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=101,
        version=101,
    )
    assert publication.accepted is True

    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="agent-worker:session-a",
                scope=ScopeV2(
                    kind=ScopeKindV2.SESSION,
                    tenant_id="tenant-a",
                    project_id="project-a",
                    session_id="session-a",
                ),
            ) as operation,
        ):
            resolver = operation.require(AGENT_WORKER_RUNTIME_SERVICE_V2)

            assert isinstance(resolver, AgentWorkerRuntimeResolverProtocolV2)
            services = resolver.resolve(operation)
            assert services.sandbox_adapter is adapter
            assert services.subagent_run_registry is run_registry
            assert isinstance(
                services.orchestration_runtime,
                AgentOrchestrationRuntimeProtocolV2,
            )
            assert services.unavailable_code is None
    finally:
        await host.close()
        run_registry.close()

    assert adapter.close_calls == 1


async def test_agent_worker_runtime_preserves_explicit_optional_unavailability() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=102,
        version=102,
    )
    assert publication.accepted is True

    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="agent-worker:optional-sandbox",
                scope=ScopeV2(
                    kind=ScopeKindV2.SESSION,
                    tenant_id="tenant-a",
                    project_id="project-a",
                    session_id="session-a",
                ),
            ) as operation,
        ):
            resolver = operation.require(AGENT_WORKER_RUNTIME_SERVICE_V2)
            assert isinstance(resolver, AgentWorkerRuntimeResolverProtocolV2)

            services = resolver.resolve(operation)
            assert services.sandbox_adapter is None
            assert services.unavailable_code == "sandbox_runtime_factory_unavailable"
    finally:
        await host.close()


async def test_agent_worker_runtime_rejects_missing_sandbox_provider() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == SANDBOX_RUNTIME_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=103)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "service:sandbox.runtime" in str(error.value)


async def test_agent_worker_runtime_rejects_missing_subagent_registry_provider() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == SUBAGENT_RUN_REGISTRY_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=104)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-agent-worker-runtime" in str(error.value)
    assert "service:agent.subagent-run-registry" in str(error.value)


async def test_agent_worker_runtime_rejects_missing_orchestration_provider() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == AGENT_ORCHESTRATION_RUNTIME_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=105)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-agent-worker-runtime" in str(error.value)
    assert "service:agent.orchestration-runtime" in str(error.value)


def test_agent_worker_runtime_is_an_explicit_profile_entry() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    assert AGENT_WORKER_RUNTIME_MODULE_V2 in enabled_modules
    assert AGENT_ORCHESTRATION_RUNTIME_MODULE_V2 in enabled_modules
    assert enabled_modules.index(SANDBOX_RUNTIME_MODULE_V2) < enabled_modules.index(
        AGENT_WORKER_RUNTIME_MODULE_V2
    )


def test_local_runtime_bootstrap_occurs_inside_the_generation_admission() -> None:
    bootstrap_source = getsource(AgentRuntimeBootstrapper._bootstrap_agent_orchestrator)
    assert "current_agent_worker_runtime_services_v2" in bootstrap_source
    assert "get_shared_subagent_run_registry" not in bootstrap_source
    assert "except RuntimeV2Error:" in bootstrap_source

    for source in (
        getsource(AgentRuntimeBootstrapper._run_chat_local),
        getsource(local_chat_worker._run),
    ):
        assert source.index("async with admission.admit(") < source.index(
            "_ensure_local_runtime_bootstrapped()"
        )


def test_ray_actor_orchestrator_bootstrap_occurs_inside_generation_admission() -> None:
    process_bootstrap_source = getsource(project_agent_actor.ProjectAgentActor._bootstrap_runtime)
    orchestrator_source = getsource(
        project_agent_actor.ProjectAgentActor._ensure_agent_orchestrator_v2
    )
    assert "get_shared_subagent_run_registry" not in process_bootstrap_source
    assert "get_shared_subagent_run_registry" not in orchestrator_source
    assert "current_agent_worker_runtime_services_v2" in orchestrator_source
    assert "except RuntimeV2Error:" in orchestrator_source

    chat_source = getsource(project_agent_actor.ProjectAgentActor._run_chat)
    assert chat_source.index("async with self._admit_plugin_turn(") < chat_source.index(
        "_ensure_agent_orchestrator_v2("
    )

    resume_source = getsource(project_agent_actor.ProjectAgentActor._resume_continue_request)
    assert resume_source.index("async with self._plugin_admission_v2.admit(") < (
        resume_source.index("_ensure_agent_orchestrator_v2(")
    )


def test_agent_worker_sandbox_factory_reports_docker_unavailability_as_optional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter_type = MagicMock(
        side_effect=SandboxConnectionError(
            message="docker unavailable",
            operation="init",
        )
    )
    monkeypatch.setattr(agent_worker_runtime, "MCPSandboxAdapter", adapter_type)

    assert agent_worker_runtime.agent_worker_sandbox_runtime_factory_v2() is None
