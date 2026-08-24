"""Bundle-owned route authority catalog and retirement readiness tests."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.domain.model.plugins.generated_v2 import (
    ServiceContractV2,
    ServiceRequiredV2,
)
from src.infrastructure.plugins.v2.http_routes import RouteDefinitionV2
from src.infrastructure.plugins.v2.protocol import parse_profile_snapshot_v2
from src.infrastructure.plugins.v2.route_authority import (
    ROUTE_AUTHORITY_CATALOG_INJECT_V2,
    ROUTE_AUTHORITY_CATALOG_SERVICE_V2,
    ROUTE_TABLE_BUILDER_INJECT_V2,
    PluginRouteAuthorityV2,
    RouteAuthorityCatalogV2,
    verify_bundle_route_authority_v2,
)
from src.infrastructure.plugins.v2.route_effects import ROUTE_TABLE_BUILDER_SERVICE_V2

pytestmark = pytest.mark.unit
_ROOT = Path(__file__).resolve().parents[6]


def _snapshot(*, target_enabled: bool = True):
    snapshot = parse_profile_snapshot_v2(
        json.loads(
            (_ROOT / "shared/fixtures/platform-plugin-profile.v2.json").read_text(encoding="utf-8")
        )
    )
    source_manifest = snapshot.manifests[0]
    source_module = source_manifest.modules[0]
    route_module = replace(
        source_module,
        module_ref="builtin://example/http-routes",
        contract=replace(
            source_module.contract,
            services=ServiceContractV2(
                provides=(),
                requires=(
                    ServiceRequiredV2(
                        alias=ROUTE_TABLE_BUILDER_INJECT_V2,
                        service=ROUTE_TABLE_BUILDER_SERVICE_V2,
                        version="1.0.0",
                    ),
                    ServiceRequiredV2(
                        alias=ROUTE_AUTHORITY_CATALOG_INJECT_V2,
                        service=ROUTE_AUTHORITY_CATALOG_SERVICE_V2,
                        version="1.0.0",
                    ),
                ),
            ),
        ),
    )
    manifest = replace(
        source_manifest,
        plugin_id="example-plugin",
        modules=(route_module,),
    )
    target_entry = replace(
        snapshot.entries[0],
        entry_id="example-http-routes",
        plugin_ref=manifest.plugin_id,
        module_ref=route_module.module_ref,
        enabled=target_enabled,
        inject={
            ROUTE_TABLE_BUILDER_INJECT_V2: ROUTE_TABLE_BUILDER_SERVICE_V2,
            ROUTE_AUTHORITY_CATALOG_INJECT_V2: ROUTE_AUTHORITY_CATALOG_SERVICE_V2,
        },
    )
    return replace(
        snapshot,
        manifests=(manifest,),
        entries=(target_entry,),
    )


def _desired_row() -> SimpleNamespace:
    return SimpleNamespace(
        plugin_id="example-plugin",
        method="GET",
        path="/api/v1/plugins/example",
        permission="plugin.example.read",
        authorization_mode="tenant_member",
        enabled=True,
    )


def _definition(owner_entry_id: str = "example-http-routes") -> RouteDefinitionV2:
    async def endpoint() -> dict[str, bool]:
        return {"ok": True}

    return RouteDefinitionV2(
        owner_entry_id=owner_entry_id,
        path="/api/v1/plugins/example",
        methods=("GET",),
        endpoint=endpoint,
        name="example-plugin-route",
    )


def _authority(owner_entry_id: str = "example-http-routes") -> PluginRouteAuthorityV2:
    return PluginRouteAuthorityV2(
        owner_entry_id=owner_entry_id,
        plugin_id="example-plugin",
        method="GET",
        path="/api/v1/plugins/example",
        permission="plugin.example.read",
        authorization_mode="tenant_member",
    )


async def test_route_authority_catalog_is_unique_reversible_and_freezes() -> None:
    catalog = RouteAuthorityCatalogV2()
    first = _authority()
    dispose = catalog.contribute(first)

    with pytest.raises(ValueError, match="duplicate route authority"):
        catalog.contribute(first)

    frozen = catalog.freeze()
    assert frozen.authorities == (first,)
    with pytest.raises(ValueError, match="frozen"):
        catalog.contribute(
            replace(first, method="POST"),
        )

    await dispose()
    assert catalog.authorities == ()
    assert frozen.authorities == (first,)


def test_bundle_route_authority_requires_exact_owner_and_route_effect() -> None:
    evidence = verify_bundle_route_authority_v2(
        snapshot=_snapshot(),
        route_definitions=(_definition(),),
        authorities=(_authority(),),
        desired_rows=(_desired_row(),),
    )

    assert evidence.ready is True
    assert evidence.required_route_count == 1
    assert evidence.bound_route_count == 1
    assert evidence.reasons == ()
    assert evidence.bindings[0].target_entry_id == "example-http-routes"
    assert evidence.bindings[0].target_plugin_ref == "example-plugin"


@pytest.mark.parametrize(
    ("snapshot", "definitions", "authorities", "reason"),
    [
        (
            _snapshot(),
            (),
            (_authority(),),
            "route_effect_missing:GET /api/v1/plugins/example",
        ),
        (
            _snapshot(target_enabled=False),
            (_definition(),),
            (_authority(),),
            "route_owner_entry_inactive:example-http-routes",
        ),
        (
            _snapshot(),
            (_definition(),),
            (replace(_authority(), permission="plugin.example.admin"),),
            "route_authority_mismatch:GET /api/v1/plugins/example",
        ),
    ],
)
def test_bundle_route_authority_fails_closed_with_stable_reasons(
    snapshot,
    definitions: tuple[RouteDefinitionV2, ...],
    authorities: tuple[PluginRouteAuthorityV2, ...],
    reason: str,
) -> None:
    evidence = verify_bundle_route_authority_v2(
        snapshot=snapshot,
        route_definitions=definitions,
        authorities=authorities,
        desired_rows=(_desired_row(),),
    )

    assert evidence.ready is False
    assert reason in evidence.reasons


def test_route_authority_requires_module_contract_to_consume_route_builder() -> None:
    snapshot = _snapshot()
    manifest = snapshot.manifests[0]
    module = manifest.modules[0]
    without_route_contract = replace(
        module,
        contract=replace(
            module.contract,
            services=replace(module.contract.services, requires=()),
        ),
    )
    snapshot = replace(
        snapshot,
        manifests=(replace(manifest, modules=(without_route_contract,)),),
    )

    evidence = verify_bundle_route_authority_v2(
        snapshot=snapshot,
        route_definitions=(_definition(),),
        authorities=(_authority(),),
        desired_rows=(_desired_row(),),
    )

    assert evidence.ready is False
    assert (
        "route_owner_contract_missing:example-http-routes:service:http.route-table-builder"
        in evidence.reasons
    )


def test_route_authority_rejects_non_canonical_method() -> None:
    with pytest.raises(ValueError, match="method must use canonical uppercase form"):
        replace(_authority(), method="get")


@pytest.mark.parametrize(
    ("missing_service", "reason"),
    (
        (
            ROUTE_TABLE_BUILDER_SERVICE_V2,
            "route_owner_contract_missing:example-http-routes:service:http.route-table-builder",
        ),
        (
            ROUTE_AUTHORITY_CATALOG_SERVICE_V2,
            "route_owner_contract_missing:example-http-routes:service:http.route-authority-catalog",
        ),
    ),
)
def test_route_authority_requires_both_module_contract_services(
    missing_service: str,
    reason: str,
) -> None:
    snapshot = _snapshot()
    manifest = snapshot.manifests[0]
    module = manifest.modules[0]
    incomplete = replace(
        module,
        contract=replace(
            module.contract,
            services=replace(
                module.contract.services,
                requires=tuple(
                    requirement
                    for requirement in module.contract.services.requires
                    if requirement.service != missing_service
                ),
            ),
        ),
    )

    evidence = verify_bundle_route_authority_v2(
        snapshot=replace(
            snapshot,
            manifests=(replace(manifest, modules=(incomplete,)),),
        ),
        route_definitions=(_definition(),),
        authorities=(_authority(),),
        desired_rows=(_desired_row(),),
    )

    assert evidence.ready is False
    assert reason in evidence.reasons


@pytest.mark.parametrize(
    ("missing_alias", "service"),
    (
        (ROUTE_TABLE_BUILDER_INJECT_V2, ROUTE_TABLE_BUILDER_SERVICE_V2),
        (ROUTE_AUTHORITY_CATALOG_INJECT_V2, ROUTE_AUTHORITY_CATALOG_SERVICE_V2),
    ),
)
def test_route_authority_requires_both_exact_entry_injects(
    missing_alias: str,
    service: str,
) -> None:
    snapshot = _snapshot()
    (target,) = snapshot.entries
    inject = dict(target.inject)
    del inject[missing_alias]

    evidence = verify_bundle_route_authority_v2(
        snapshot=replace(snapshot, entries=(replace(target, inject=inject),)),
        route_definitions=(_definition(),),
        authorities=(_authority(),),
        desired_rows=(_desired_row(),),
    )

    assert evidence.ready is False
    assert (
        f"route_owner_inject_missing:example-http-routes:{missing_alias}:{service}"
        in evidence.reasons
    )
