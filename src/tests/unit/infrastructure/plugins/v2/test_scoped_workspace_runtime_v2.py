"""Scoped Workspace Core borrows owner resources and preserves their lifetime."""

import json
from dataclasses import replace

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2, ServiceRequiredV2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import control_envelope_v2, parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.scoped_builtin_runtime import (
    scoped_builtin_runtime_definitions_v2,
)
from src.infrastructure.plugins.v2.scoped_runtime_registry import ScopedRuntimeRegistryV2
from src.infrastructure.plugins.v2.service_closure import project_service_closure_v2
from src.infrastructure.plugins.v2.workspace_core_runtime import (
    WORKSPACE_CORE_RUNTIME_SERVICE_V2,
    workspace_core_runtime_definition_v2,
)
from src.infrastructure.plugins.v2.workspace_core_shadow import activate_workspace_core_shadow_v2
from src.infrastructure.plugins.v2.workspace_prompt_context_services import (
    WORKSPACE_PROMPT_CONTEXT_SERVICE_V2,
    WorkspacePromptContextProtocolV2,
)
from src.tests.unit.infrastructure.plugins.v2.test_workspace_prompt_context_services_v2 import (
    _MANIFEST_PATH,
    _PROFILE_PATH,
    _ProviderAdapter,
    _runtime,
)

pytestmark = pytest.mark.unit
ROOT = ScopeV2(kind=ScopeKindV2.ROOT)


def _project(service, scope=ROOT):
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text()))
    document = activate_workspace_core_shadow_v2(load_profile_document_v2(_PROFILE_PATH))
    snapshot = compose_profile_v2(document, {manifest.plugin_id: manifest}, generation=1)
    return project_service_closure_v2(
        snapshot,
        scope=scope,
        required_services=(ServiceRequiredV2(alias="selected", service=service, version="1.0.0"),),
    )


def _scope(tenant):
    return ScopeV2(kind=ScopeKindV2.SESSION, tenant_id=tenant, project_id="p", session_id="s")


async def test_two_scopes_retain_workspace_owner_until_last_operation_drains():
    adapter = _ProviderAdapter()
    runtime = _runtime(object(), adapter)
    snapshot = _project(WORKSPACE_CORE_RUNTIME_SERVICE_V2)
    owner = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(workspace_core_runtime_factory=lambda: runtime)
    )
    assert (await owner.apply(snapshot, control_envelope_v2(snapshot, version=1))).accepted
    registry = ScopedRuntimeRegistryV2(
        definitions_factory=lambda scope: scoped_builtin_runtime_definitions_v2(
            scope, sandbox_owner_host=owner, redis_client=None
        )
    )
    a, b = _scope("a"), _scope("b")
    try:
        for scope in (a, b):
            projected = _project(WORKSPACE_PROMPT_CONTEXT_SERVICE_V2, scope)
            assert (
                await registry.publish(scope, projected, control_envelope_v2(projected, version=1))
            ).accepted
        lease = await registry.acquire(b)
        assert lease.generation.resolve(WORKSPACE_CORE_RUNTIME_SERVICE_V2, b) is runtime
        assert isinstance(
            lease.generation.resolve(WORKSPACE_PROMPT_CONTEXT_SERVICE_V2, b),
            WorkspacePromptContextProtocolV2,
        )
        await owner.close()
        await registry.close_scope(a)
        await registry.close_scope(b)
        assert adapter.wait_calls == 0
        await lease.release()
        assert adapter.wait_calls == 1
    finally:
        await registry.close()
        await owner.close()


async def test_invalid_workspace_owner_releases_failed_candidate_lease():
    adapter = _ProviderAdapter()
    snapshot = _project(WORKSPACE_CORE_RUNTIME_SERVICE_V2)
    definition = workspace_core_runtime_definition_v2()

    async def invalid(context, config):
        context.provide(WORKSPACE_CORE_RUNTIME_SERVICE_V2, object())
        return adapter.wait_until_idle

    owner = PlatformPluginRuntimeHostV2(
        tuple(
            replace(item, apply=invalid) if item.module_ref == definition.module_ref else item
            for item in builtin_runtime_definitions_v2()
        )
    )
    assert (await owner.apply(snapshot, control_envelope_v2(snapshot, version=1))).accepted
    try:
        with pytest.raises(RuntimeV2Error, match="invalid Workspace Core runtime"):
            await LoaderV2(
                scoped_builtin_runtime_definitions_v2(
                    _scope("test"), sandbox_owner_host=owner, redis_client=None
                )
            ).stage(snapshot)
    finally:
        await owner.close()
    assert adapter.wait_calls == 1


async def test_missing_workspace_owner_service_fails_without_allocating_a_bridge():
    owner = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    empty = _project("service:runtime-generation-boundary")
    assert (await owner.apply(empty, control_envelope_v2(empty, version=1))).accepted
    try:
        with pytest.raises(RuntimeV2Error):
            await LoaderV2(
                scoped_builtin_runtime_definitions_v2(
                    _scope("test"), sandbox_owner_host=owner, redis_client=None
                )
            ).stage(_project(WORKSPACE_CORE_RUNTIME_SERVICE_V2))
    finally:
        await owner.close()
