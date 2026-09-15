"""Real signed archive → Loader → leased ToolDefinition → Wasmtime execution."""

import json

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import (
    RUNTIME_BOUNDARY_MODULE_V2,
    builtin_runtime_definitions_v2,
)
from src.infrastructure.plugins.v2.bundle_archive import parse_bundle_archive_v2
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.infrastructure.plugins.v2.protocol import build_profile_snapshot_v2
from src.infrastructure.plugins.v2.runtime import GenerationManagerV2, LoaderV2, RuntimeV2Error
from src.infrastructure.plugins.v2.tool_set import (
    TOOL_SET_CATALOG_SERVICE_V2,
    TOOL_SET_MODULE_V2,
    PreparedToolProviderV2,
)
from src.infrastructure.plugins.v2.wasm_tool_runtime import prepare_wasm_operation_tools_v2
from src.tests.unit.infrastructure.plugins.v2.test_external_wasm_admission import (
    verified,  # noqa: F401
)

SCOPE = ScopeV2(
    kind=ScopeKindV2.SESSION, tenant_id="tenant", project_id="project", session_id="session"
)


class Authority:
    allowed = True

    def __init__(self):
        self.attributions = []

    async def authorize(self, *, operation, attribution):
        assert operation.context.scope == SCOPE
        self.attributions.append(attribution)
        return self.allowed


@pytest.fixture
async def staged(verified):  # noqa: F811
    source = production_bundle_sources_v2()
    base = parse_bundle_archive_v2(
        source.bundle_archive,
        source="builtin://memstack-platform-base/2.0.0",
        require_signature=False,
        approved_permissions=frozenset(
            p for manifest in source.bundle.manifests for p in manifest.permissions
        ),
    )
    entries = [
        entry
        for layer in base.manifest.layers
        for entry in layer.entries
        if entry.module_ref in {TOOL_SET_MODULE_V2, RUNTIME_BOUNDARY_MODULE_V2}
    ]
    builtin = next(
        manifest
        for manifest in base.manifest.manifests
        if any(module.module_ref == TOOL_SET_MODULE_V2 for module in manifest.modules)
    )
    snapshot = build_profile_snapshot_v2(
        profile_id="wasm-test",
        generation=1,
        manifests=(builtin, *verified.manifest.manifests),
        entries=(*entries, *verified.manifest.layers[0].entries),
    )
    generation = await LoaderV2(
        [
            d
            for d in builtin_runtime_definitions_v2()
            if d.module_ref in {TOOL_SET_MODULE_V2, RUNTIME_BOUNDARY_MODULE_V2}
        ]
    ).stage(snapshot, verified_archives=[base, verified])
    manager = GenerationManagerV2()
    await manager.publish(generation)
    catalog = generation.resolve(TOOL_SET_CATALOG_SERVICE_V2, SCOPE)
    try:
        yield manager, catalog
    finally:
        await manager.close()


def resolve(catalog):
    return catalog.resolve(
        agent=object(),
        selection_context=None,
        prepared_tool_provider=PreparedToolProviderV2(tools={}),
    )


async def test_catalog_without_pinned_operation_is_empty(staged):
    _, catalog = staged
    assert resolve(catalog).definitions == ()


async def test_unprepared_and_denied_operation_exposes_no_tools(staged):
    manager, catalog = staged
    authority = Authority()
    authority.allowed = False
    async with pin_operation_context_v2(manager, operation_id="deny", scope=SCOPE) as operation:
        assert resolve(catalog).definitions == ()
        assert await prepare_wasm_operation_tools_v2(operation, authority) == 0
        assert resolve(catalog).definitions == ()


async def test_verified_tool_executes_real_bytes_and_revokes_retained_lease(staged, verified):  # noqa: F811
    manager, catalog = staged
    authority = Authority()
    async with pin_operation_context_v2(manager, operation_id="allowed", scope=SCOPE) as operation:
        assert await prepare_wasm_operation_tools_v2(operation, authority) == 1
        (definition,) = resolve(catalog).definitions
        assert definition.parameters["additionalProperties"] is False
        result = json.loads(await definition.execute(input="中文"))
        assert result["score"] == 20260914
        assert result["input_bytes"] == len('{"input":"中文"}'.encode())
        identity = result["attribution"]
        assert identity["bundle_reference"]["bundle_id"] == verified.manifest.bundle_id
        assert identity["bundle_reference"]["digest"] == verified.manifest.digest
        assert identity["plugin_id"] != identity["bundle_reference"]["bundle_id"]
        assert (
            identity["artifact_digest"] == verified.manifest.manifests[0].modules[0].artifact.digest
        )
        assert identity["effect"] == "pure"
        authority.allowed = False
        with pytest.raises(RuntimeV2Error, match="permission"):
            await definition.execute(input="revoked")
    with pytest.raises(RuntimeV2Error, match="no longer active"):
        await definition.execute(input="disposed")


async def test_leased_tool_cannot_cross_operation_even_with_same_scope(staged):
    manager, catalog = staged
    async with pin_operation_context_v2(manager, operation_id="owner", scope=SCOPE) as operation:
        await prepare_wasm_operation_tools_v2(operation, Authority())
        (definition,) = resolve(catalog).definitions
        async with pin_operation_context_v2(manager, operation_id="other", scope=SCOPE):
            with pytest.raises(RuntimeV2Error, match="another operation"):
                await definition.execute(input="cross")


async def test_authority_failure_never_installs_partial_tools(staged):
    manager, catalog = staged

    class Unavailable:
        async def authorize(self, **kwargs):
            raise RuntimeError("authority unavailable")

    async with pin_operation_context_v2(
        manager, operation_id="unavailable", scope=SCOPE
    ) as operation:
        with pytest.raises(RuntimeError, match="authority unavailable"):
            await prepare_wasm_operation_tools_v2(operation, Unavailable())
        assert resolve(catalog).definitions == ()


async def test_root_scope_cannot_prepare_wasm_tools(staged):
    manager, catalog = staged
    async with pin_operation_context_v2(
        manager, operation_id="root", scope=ScopeV2(kind=ScopeKindV2.ROOT)
    ) as operation:
        with pytest.raises(RuntimeV2Error, match="scoped session"):
            await prepare_wasm_operation_tools_v2(operation, Authority())
        assert resolve(catalog).definitions == ()
