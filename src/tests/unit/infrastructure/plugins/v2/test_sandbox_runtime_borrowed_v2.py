"""Borrowed sandbox projections never acquire physical resource ownership."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.application.services.sandbox_event_service import SandboxEventPublisher
from src.application.services.sandbox_orchestrator import SandboxOrchestrator
from src.application.services.sandbox_token_service import SandboxTokenService
from src.application.services.sandbox_tool_registry import SandboxToolRegistry
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter
from src.infrastructure.plugins.v2.protocol import (
    build_profile_snapshot_v2,
    parse_plugin_manifest_v2,
)
from src.infrastructure.plugins.v2.runtime import GenerationManagerV2, LoaderV2, RuntimeV2Error
from src.infrastructure.plugins.v2.sandbox_runtime import (
    SANDBOX_RUNTIME_MODULE_V2,
    SANDBOX_RUNTIME_SERVICE_V2,
    SandboxApplicationServicesV2,
    SandboxRuntimeServiceV2,
    sandbox_runtime_definition_v2,
)
from src.tests.unit.infrastructure.plugins.v2.test_runtime import _catalog, _entry

pytestmark = pytest.mark.unit
ROOT = ScopeV2(kind=ScopeKindV2.ROOT)


class _Adapter(MCPSandboxAdapter):
    def __init__(self):
        self.actions = []

    async def sync_from_docker(self):
        self.actions.append("sync")
        raise AssertionError("borrowed runtime must not sync")

    def set_access_persist_callback(self, callback):
        self.actions.append("callback")
        raise AssertionError("borrowed runtime must not change callbacks")

    async def close(self):
        self.actions.append("close")


def _runtime():
    adapter = _Adapter()
    publisher = SandboxEventPublisher()
    return SandboxRuntimeServiceV2(
        services=SandboxApplicationServicesV2(
            adapter=adapter,
            event_publisher=publisher,
            orchestrator=SandboxOrchestrator(sandbox_adapter=adapter, event_publisher=publisher),
            token_service=SandboxTokenService(secret_key="test-only-not-a-credential"),
            tool_registry=SandboxToolRegistry(mcp_adapter=adapter),
        )
    )


def _snapshot(required=False):
    root = Path(__file__).resolve().parents[6]
    manifest = parse_plugin_manifest_v2(
        json.loads(
            (root / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json").read_text()
        )
    )
    manifest = replace(
        manifest,
        modules=tuple(
            module for module in manifest.modules if module.module_ref == SANDBOX_RUNTIME_MODULE_V2
        ),
    )
    entry = replace(
        _entry("sandbox", SANDBOX_RUNTIME_MODULE_V2),
        plugin_ref=manifest.plugin_id,
        config={"strategy": "mcp-docker", "required": required},
    )
    return build_profile_snapshot_v2(
        profile_id="borrowed-sandbox", generation=1, manifests=(manifest,), entries=(entry,)
    )


def _loader(snapshot, definition):
    return LoaderV2(
        (definition,),
        target_catalog=_catalog(snapshot),
    )


async def test_real_loader_borrowed_runtime_has_no_owned_setup_or_cleanup():
    runtime = _runtime()
    snapshot = _snapshot(required=True)
    generation = await _loader(
        snapshot, sandbox_runtime_definition_v2(projected_runtime=runtime)
    ).stage(snapshot)
    assert generation.resolve(SANDBOX_RUNTIME_SERVICE_V2, ROOT) is runtime
    await generation.dispose()
    assert runtime.require().adapter.actions == []


@pytest.mark.parametrize(
    "mode,code",
    [
        ("conflict", "sandbox_runtime_source_conflict"),
        ("invalid", "invalid_sandbox_runtime_projection"),
        ("invalid-services", "invalid_sandbox_runtime_projection"),
        ("unavailable", "sandbox_runtime_unavailable"),
    ],
)
async def test_invalid_borrowed_source_rejects_before_factory_call(mode, code):
    calls = []
    runtime = SandboxRuntimeServiceV2(services=None) if mode == "unavailable" else _runtime()
    if mode == "invalid-services":
        runtime = SandboxRuntimeServiceV2(services=object())
    definition = sandbox_runtime_definition_v2(
        (lambda: calls.append(True)) if mode == "conflict" else None,
        projected_runtime=object() if mode == "invalid" else runtime,
    )
    snapshot = _snapshot(required=True)
    with pytest.raises(RuntimeV2Error) as caught:
        await _loader(snapshot, definition).stage(snapshot)
    assert caught.value.code == code
    assert calls == []


async def test_optional_unavailable_projection_remains_explicit():
    runtime = SandboxRuntimeServiceV2(services=None, unavailable_code="owner-unavailable")
    snapshot = _snapshot()
    generation = await _loader(
        snapshot, sandbox_runtime_definition_v2(projected_runtime=runtime)
    ).stage(snapshot)
    assert generation.resolve(SANDBOX_RUNTIME_SERVICE_V2, ROOT) is runtime
    await generation.dispose()


async def test_owner_generation_lease_controls_physical_disposal():
    runtime = _runtime()
    snapshot = _snapshot(required=True)
    borrowed = sandbox_runtime_definition_v2(projected_runtime=runtime)

    async def owner_apply(context, config):
        await borrowed.apply(context, config)
        return runtime.require().adapter.close

    owner_definition = replace(borrowed, apply=owner_apply)
    owner = await _loader(snapshot, owner_definition).stage(snapshot)
    manager = GenerationManagerV2()
    await manager.publish(owner)
    lease = await manager.acquire()
    scoped = await _loader(snapshot, borrowed).stage(snapshot)
    await manager.close()
    assert runtime.require().adapter.actions == []
    assert scoped.resolve(SANDBOX_RUNTIME_SERVICE_V2, ROOT) is runtime
    await scoped.dispose()
    assert runtime.require().adapter.actions == []
    await lease.release()
    assert runtime.require().adapter.actions == ["close"]
