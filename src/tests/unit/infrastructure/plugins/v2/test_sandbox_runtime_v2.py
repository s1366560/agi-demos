"""V2 Provider/Consumer coverage for sandbox runtime composition."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.sandbox_runtime import (
    SANDBOX_APPLICATION_MODULE_V2,
    SANDBOX_APPLICATION_SERVICE_V2,
    SANDBOX_RUNTIME_MODULE_V2,
    SandboxApplicationResolverV2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


class _TrackedSandboxAdapter(MCPSandboxAdapter):
    def __init__(self) -> None:
        self.sync_calls = 0
        self.close_calls = 0

    async def sync_from_docker(self) -> int:
        self.sync_calls += 1
        return 0

    async def close(self) -> None:
        self.close_calls += 1


class _FailingSyncSandboxAdapter(_TrackedSandboxAdapter):
    async def sync_from_docker(self) -> int:
        self.sync_calls += 1
        raise RuntimeError("sandbox discovery failed")


async def test_sandbox_resolver_uses_generation_owned_adapter() -> None:
    adapter = _TrackedSandboxAdapter()
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(sandbox_runtime_factory=lambda: adapter)
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=71,
        version=71,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="sandbox-application:project-a",
                scope=ScopeV2(
                    kind=ScopeKindV2.PROJECT,
                    tenant_id="tenant-a",
                    project_id="project-a",
                ),
            ) as operation,
        ):
            resolver = operation.require(SANDBOX_APPLICATION_SERVICE_V2)

            assert isinstance(resolver, SandboxApplicationResolverV2)
            services = resolver.resolve(operation)
            assert services.adapter is adapter
            assert services.orchestrator._adapter is adapter
            assert adapter.sync_calls == 1
    finally:
        await host.close()

    assert adapter.close_calls == 1


async def test_sandbox_runtime_closes_adapter_when_candidate_activation_fails() -> None:
    adapter = _FailingSyncSandboxAdapter()
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(sandbox_runtime_factory=lambda: adapter)
    )

    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=72,
        version=72,
    )

    assert publication.accepted is False
    assert host.manager.current is None
    assert adapter.sync_calls == 1
    assert adapter.close_calls == 1

    await host.close()


async def test_sandbox_runtime_disposes_only_after_generation_lease_drains() -> None:
    adapters = [_TrackedSandboxAdapter(), _TrackedSandboxAdapter()]
    factory_calls = 0

    def factory() -> MCPSandboxAdapter:
        nonlocal factory_calls
        adapter = adapters[factory_calls]
        factory_calls += 1
        return adapter

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(sandbox_runtime_factory=factory)
    )
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=72,
        version=72,
    )
    assert first.accepted is True
    lease = await host.acquire()
    _ = await lease.__aenter__()
    try:
        second = await host.bootstrap(
            profile_path=_PROFILE_PATH,
            manifest_paths=(_MANIFEST_PATH,),
            generation=73,
            version=73,
        )

        assert second.accepted is True
        assert adapters[0].close_calls == 0
        assert adapters[1].close_calls == 0
    finally:
        await lease.__aexit__(None, None, None)

    assert adapters[0].close_calls == 1
    await host.close()
    assert adapters[1].close_calls == 1


async def test_optional_sandbox_runtime_without_factory_fails_on_consumer_require() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=74,
        version=74,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="sandbox-unavailable",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            resolver = operation.require(SANDBOX_APPLICATION_SERVICE_V2)
            assert isinstance(resolver, SandboxApplicationResolverV2)

            with pytest.raises(RuntimeV2Error) as error:
                resolver.resolve(operation)

            assert error.value.code == "sandbox_runtime_factory_unavailable"
    finally:
        await host.close()


async def test_sandbox_application_rejects_missing_runtime_inject_without_fallback() -> None:
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
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=75)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-sandbox-services" in str(error.value)
    assert "service:sandbox.runtime@1.0.0" in str(error.value)


def test_sandbox_modules_are_explicit_ordered_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    assert SANDBOX_RUNTIME_MODULE_V2 in enabled_modules
    assert SANDBOX_APPLICATION_MODULE_V2 in enabled_modules
    assert enabled_modules.index(SANDBOX_RUNTIME_MODULE_V2) < enabled_modules.index(
        SANDBOX_APPLICATION_MODULE_V2
    )
    runtime_entry = next(
        entry for entry in document.entries if entry.module_ref == SANDBOX_RUNTIME_MODULE_V2
    )
    assert runtime_entry.config == {"required": False, "strategy": "mcp-docker"}
    application_entry = next(
        entry for entry in document.entries if entry.module_ref == SANDBOX_APPLICATION_MODULE_V2
    )
    assert application_entry.inject == {"runtime": "service:sandbox.runtime"}
