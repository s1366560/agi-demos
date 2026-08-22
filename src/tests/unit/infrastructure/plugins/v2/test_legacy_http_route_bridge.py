"""Legacy desired HTTP routes projected into protocol v2 profile effects."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.legacy_http_route_bridge import (
    LEGACY_HTTP_ROUTE_BRIDGE_ENTRY_V2,
    legacy_http_route_bridge_definition_v2,
    project_legacy_http_routes_v2,
)
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.route_effects import (
    ROUTE_AUTHORITY_CATALOG_SERVICE_V2,
    ROUTE_TABLE_BUILDER_SERVICE_V2,
    route_table_builder_definition_v2,
)
from src.infrastructure.plugins.v2.runtime import LoaderV2

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


def _row(*, permission: str = "plugin.example.read") -> SimpleNamespace:
    return SimpleNamespace(
        plugin_id="example-plugin",
        method="get",
        path="/api/v1/plugins/{tenant_id}/example",
        permission=permission,
        authorization_mode="tenant_member",
        enabled=True,
    )


def _manifest():
    return parse_plugin_manifest_v2(json.loads(_MANIFEST.read_text(encoding="utf-8")))


def _route_only_document(rows: tuple[SimpleNamespace, ...]):
    document = project_legacy_http_routes_v2(load_profile_document_v2(_PROFILE), rows)
    return replace(
        document,
        entries=tuple(
            replace(entry, parent_entry_id=None)
            for entry in document.entries
            if entry.entry_id in {"builtin-route-table-builder", LEGACY_HTTP_ROUTE_BRIDGE_ENTRY_V2}
        ),
        patches=(),
    )


@pytest.mark.unit
def test_legacy_route_projection_is_canonical_and_changes_snapshot_digest() -> None:
    document = load_profile_document_v2(_PROFILE)
    manifest = _manifest()

    first = project_legacy_http_routes_v2(document, (_row(),))
    repeated = project_legacy_http_routes_v2(document, (_row(),))
    changed = project_legacy_http_routes_v2(
        document,
        (_row(permission="plugin.example.admin-read"),),
    )

    first_entry = next(
        entry for entry in first.entries if entry.entry_id == LEGACY_HTTP_ROUTE_BRIDGE_ENTRY_V2
    )
    assert first == repeated
    assert first_entry.config == {
        "routes": [
            {
                "authorization_mode": "tenant_member",
                "enabled": True,
                "method": "GET",
                "path": "/api/v1/plugins/{tenant_id}/example",
                "permission": "plugin.example.read",
                "plugin_id": "example-plugin",
            }
        ]
    }
    first_snapshot = compose_profile_v2(
        first,
        {manifest.plugin_id: manifest},
        generation=2,
    )
    changed_snapshot = compose_profile_v2(
        changed,
        {manifest.plugin_id: manifest},
        generation=2,
    )
    assert first_snapshot.digest != changed_snapshot.digest


@pytest.mark.unit
async def test_legacy_route_entry_contributes_and_disposes_a_real_route_effect() -> None:
    async def handler(tenant_id: str) -> dict[str, str]:
        return {"tenant_id": tenant_id}

    async def authorize() -> None:
        return None

    registry_routes = {
        "example-plugin": [
            SimpleNamespace(
                method="GET",
                path="/api/v1/plugins/{tenant_id}/example",
                plugin_name="example-plugin",
                handler=handler,
            )
        ]
    }
    document = _route_only_document((_row(),))
    manifest = _manifest()
    snapshot = compose_profile_v2(
        document,
        {manifest.plugin_id: manifest},
        generation=1,
    )
    loader = LoaderV2(
        (
            route_table_builder_definition_v2(),
            legacy_http_route_bridge_definition_v2(
                inventory_provider=lambda: registry_routes,
                authorization_factory=lambda _row: authorize,
            ),
        )
    )

    generation = await loader.stage(snapshot)
    builder = generation.resolve(
        ROUTE_TABLE_BUILDER_SERVICE_V2,
        ScopeV2(kind=ScopeKindV2.ROOT),
    )
    authority_catalog = generation.resolve(
        ROUTE_AUTHORITY_CATALOG_SERVICE_V2,
        ScopeV2(kind=ScopeKindV2.ROOT),
    )
    definitions = builder.definitions

    assert len(definitions) == 1
    assert definitions[0].owner_entry_id == LEGACY_HTTP_ROUTE_BRIDGE_ENTRY_V2
    assert definitions[0].endpoint is handler
    assert len(definitions[0].dependencies) == 1
    assert definitions[0].dependencies[0].dependency is authorize
    assert authority_catalog.authorities[0].owner_entry_id == LEGACY_HTTP_ROUTE_BRIDGE_ENTRY_V2
    assert authority_catalog.authorities[0].plugin_id == "example-plugin"

    await generation.dispose()
    assert builder.definitions == ()
    assert authority_catalog.authorities == ()


@pytest.mark.unit
async def test_legacy_route_entry_rejects_missing_handler_before_publication() -> None:
    document = _route_only_document((_row(),))
    manifest = _manifest()
    snapshot = compose_profile_v2(
        document,
        {manifest.plugin_id: manifest},
        generation=1,
    )
    loader = LoaderV2(
        (
            route_table_builder_definition_v2(),
            legacy_http_route_bridge_definition_v2(
                inventory_provider=dict,
                authorization_factory=lambda _row: lambda: None,
            ),
        )
    )

    with pytest.raises(RuntimeError, match="handler is not owned"):
        await loader.stage(snapshot)
