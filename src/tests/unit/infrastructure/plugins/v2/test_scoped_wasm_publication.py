"""Scoped publication must preserve real signed archives through staging and replay."""

import json
from dataclasses import replace

import pytest

from src.infrastructure.plugins.v2.builtin_modules import (
    RUNTIME_BOUNDARY_MODULE_V2,
    builtin_runtime_definitions_v2,
)
from src.infrastructure.plugins.v2.bundle_archive import parse_bundle_archive_v2
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.infrastructure.plugins.v2.protocol import build_profile_snapshot_v2, control_envelope_v2
from src.infrastructure.plugins.v2.scoped_boundary import pin_scoped_agent_turn_operation_v2
from src.infrastructure.plugins.v2.scoped_runtime_registry import ScopedRuntimeRegistryV2
from src.infrastructure.plugins.v2.tool_set import TOOL_SET_CATALOG_SERVICE_V2, TOOL_SET_MODULE_V2
from src.infrastructure.plugins.v2.wasm_tool_runtime import prepare_wasm_operation_tools_v2
from src.tests.unit.infrastructure.plugins.v2.test_external_wasm_admission import (
    verified,  # noqa: F401
)
from src.tests.unit.infrastructure.plugins.v2.test_wasm_tool_runtime import (
    SCOPE,
    Authority,
    resolve,
)


@pytest.mark.parametrize("archive_mode", ["verified", "missing", "forged"])
async def test_scoped_signed_wasm_staging_and_exact_republication(verified, archive_mode):  # noqa: F811
    source = production_bundle_sources_v2()
    base = parse_bundle_archive_v2(
        source.bundle_archive,
        source="builtin://memstack-platform-base/2.0.0",
        require_signature=False,
        approved_permissions=frozenset(
            permission
            for manifest in source.bundle.manifests
            for permission in manifest.permissions
        ),
    )
    modules = {TOOL_SET_MODULE_V2, RUNTIME_BOUNDARY_MODULE_V2}
    entries = tuple(
        entry
        for layer in base.manifest.layers
        for entry in layer.entries
        if entry.module_ref in modules
    )
    builtin = next(
        manifest
        for manifest in base.manifest.manifests
        if any(module.module_ref == TOOL_SET_MODULE_V2 for module in manifest.modules)
    )
    snapshot = build_profile_snapshot_v2(
        profile_id="scoped-wasm",
        generation=1,
        manifests=(builtin, *verified.manifest.manifests),
        entries=(*entries, *verified.manifest.layers[0].entries),
    )
    registry = ScopedRuntimeRegistryV2(
        [d for d in builtin_runtime_definitions_v2() if d.module_ref in modules]
    )
    archives = [base, replace(verified) if archive_mode == "forged" else verified]
    try:
        publication = await registry.publish(
            SCOPE,
            snapshot,
            control_envelope_v2(snapshot, version=1),
            verified_archives=None if archive_mode == "missing" else archives,
        )
        if archive_mode != "verified":
            assert not publication.accepted
            return
        assert publication.accepted, publication.receipt.error_message
        # Identical digest follows the reconciler's active-generation verification path.
        replay = await registry.publish(
            SCOPE, snapshot, control_envelope_v2(snapshot, version=2), verified_archives=archives
        )
        assert replay.accepted, replay.receipt.error_message
        rejected_replay = await registry.publish(
            SCOPE,
            snapshot,
            control_envelope_v2(snapshot, version=3),
            verified_archives=[base, replace(verified)],
        )
        assert not rejected_replay.accepted
        assert rejected_replay.receipt.error_code == "artifact_verification_failed"
        async with pin_scoped_agent_turn_operation_v2(
            await registry.acquire_bound(SCOPE),
            operation_id="scoped-wasm-call",
            tenant_id=SCOPE.tenant_id,
            project_id=SCOPE.project_id,
            session_id=SCOPE.session_id,
        ) as operation:
            catalog = operation.generation.resolve(TOOL_SET_CATALOG_SERVICE_V2, SCOPE)
            assert resolve(catalog).definitions == ()
            assert await prepare_wasm_operation_tools_v2(operation, Authority()) == 1
            (tool,) = resolve(catalog).definitions
            result = json.loads(await tool.execute(input="verified scoped publication"))
            assert result["score"] == 20260914
            assert result["attribution"]["bundle_reference"]["digest"] == verified.manifest.digest
    finally:
        await registry.close()
