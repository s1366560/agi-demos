"""Generated builtin HTTP route-row contract catalog tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from src.infrastructure.plugins.route_inventory import INVENTORY_PATH
from src.infrastructure.plugins.v2 import builtin_route_contracts as route_contracts_module
from src.infrastructure.plugins.v2.builtin_http_routes import (
    REQUIRED_V2_BUILTIN_ROUTE_ROW_IDS,
)
from src.infrastructure.plugins.v2.builtin_route_contracts import (
    BuiltinRouteContractCatalogErrorV2,
    build_builtin_route_contract_catalog_v2,
    load_builtin_route_contract_catalog_v2,
    load_builtin_route_inventory_v2,
)
from src.infrastructure.plugins.v2.route_registration import (
    RouteRegistrationClassificationV2,
)

_ROOT = Path(__file__).resolve().parents[6]
_INVENTORY = _ROOT / INVENTORY_PATH


@pytest.fixture(scope="module")
def route_catalog():
    return build_builtin_route_contract_catalog_v2(inventory_path=_INVENTORY)


@pytest.mark.unit
def test_catalog_covers_authoritative_inventory_in_order(route_catalog) -> None:
    inventory = load_builtin_route_inventory_v2(_INVENTORY)

    assert len(inventory.entries) == 72
    assert route_catalog.inventory_digest == inventory.digest
    assert [row.row_id for row in route_catalog.rows] == [
        entry.row_id for entry in inventory.entries
    ]
    assert route_catalog.source_fingerprint.startswith("sha256:")
    assert route_catalog.catalog_digest.startswith("sha256:")
    assert route_catalog.runtime_row_count == 71
    assert len(route_catalog.runtime_rows) == 71
    assert route_catalog.excluded_row_ids == ("http-route-capabilities",)
    assert {row.row_id for row in route_catalog.runtime_rows} == {
        entry.row_id for entry in inventory.entries
    } - {"http-route-capabilities"}
    assert {row.runtime_ownership_evidence for row in route_catalog.runtime_rows} == {
        "route-loader:inventory-owned"
    }
    excluded = next(row for row in route_catalog.rows if not row.runtime_owned)
    assert excluded.row_id == "http-route-capabilities"
    assert excluded.runtime_ownership_evidence == "lifespan:explicit-exclusion"
    with pytest.raises(BuiltinRouteContractCatalogErrorV2, match="explicitly excluded"):
        route_catalog.runtime_row("http-route-capabilities")


@pytest.mark.unit
def test_every_existing_v2_owned_row_has_a_routes_only_contract(route_catalog) -> None:
    by_id = {row.row_id: row for row in route_catalog.rows}

    assert len(REQUIRED_V2_BUILTIN_ROUTE_ROW_IDS) == 66
    assert "task-session" in REQUIRED_V2_BUILTIN_ROUTE_ROW_IDS
    assert all(
        by_id[row_id].classification is RouteRegistrationClassificationV2.ROUTES_ONLY
        for row_id in REQUIRED_V2_BUILTIN_ROUTE_ROW_IDS
    )


@pytest.mark.unit
def test_factory_and_helper_classification_uses_structural_effects(route_catalog) -> None:
    by_id = {row.row_id: row for row in route_catalog.rows}

    assert by_id["create-pool"].classification is RouteRegistrationClassificationV2.HYBRID
    assert (
        by_id["create-project-pool"].classification is RouteRegistrationClassificationV2.ROUTES_ONLY
    )
    assert (
        by_id["workspace-core-runtime"].classification is RouteRegistrationClassificationV2.HYBRID
    )
    assert (
        by_id["http-route-capabilities"].classification
        is RouteRegistrationClassificationV2.NON_ROUTE
    )
    assert by_id["workspace-core-static"].ordered_signatures
    assert by_id["workspace-core"].ordered_signatures
    assert by_id["task-session"].ordered_signatures


@pytest.mark.unit
def test_row_contract_digests_and_openapi_are_complete(route_catalog) -> None:
    for row in route_catalog.rows:
        assert row.source_fingerprint.startswith("sha256:")
        assert row.contract_digest.startswith("sha256:")
        if row.classification is RouteRegistrationClassificationV2.ROUTES_ONLY:
            assert row.ordered_signatures, row.row_id
            assert row.openapi_digest is not None
            assert row.openapi_digest.startswith("sha256:")
        else:
            assert row.ordered_signatures == ()
            assert row.openapi_digest is None
            assert row.rejections, row.row_id


@pytest.mark.unit
def test_actual_runtime_helpers_and_factories_are_isolated_from_host_process() -> None:
    inventory = load_builtin_route_inventory_v2(_INVENTORY)
    initial_catalog = build_builtin_route_contract_catalog_v2(inventory_path=_INVENTORY)
    contract_by_id = {row.row_id: row for row in initial_catalog.rows}
    candidate_modules = []
    for entry in inventory.entries:
        contract = contract_by_id[entry.row_id]
        if contract.runtime_owned and (entry.kind == "helper" or entry.expression.endswith("()")):
            candidate_modules.append(entry.module.rsplit(".", maxsplit=1)[0])

    assert len(candidate_modules) == 6
    before = {name: sys.modules.get(name) for name in candidate_modules}
    rebuilt_catalog = build_builtin_route_contract_catalog_v2(inventory_path=_INVENTORY)
    assert {name: sys.modules.get(name) for name in candidate_modules} == before
    assert rebuilt_catalog.to_payload() == initial_catalog.to_payload()


@pytest.mark.unit
def test_inventory_digest_drift_is_rejected_before_import(tmp_path: Path) -> None:
    payload = json.loads(_INVENTORY.read_text(encoding="utf-8"))
    payload["entries"][0]["line"] += 1
    stale = tmp_path / "stale-inventory.json"
    stale.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BuiltinRouteContractCatalogErrorV2, match="inventory digest mismatch"):
        build_builtin_route_contract_catalog_v2(inventory_path=stale)


@pytest.mark.unit
def test_duplicate_inventory_row_is_rejected(tmp_path: Path) -> None:
    payload = json.loads(_INVENTORY.read_text(encoding="utf-8"))
    payload["entries"].append(dict(payload["entries"][0]))
    payload["digest"] = _inventory_entries_digest(payload["entries"])
    duplicate = tmp_path / "duplicate-inventory.json"
    duplicate.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BuiltinRouteContractCatalogErrorV2, match="duplicate inventory row"):
        build_builtin_route_contract_catalog_v2(inventory_path=duplicate)


@pytest.mark.unit
def test_explicit_runtime_exclusion_must_exist_in_inventory(tmp_path: Path) -> None:
    payload = json.loads(_INVENTORY.read_text(encoding="utf-8"))
    payload["entries"] = [
        entry for entry in payload["entries"] if entry["row_id"] != "http-route-capabilities"
    ]
    payload["digest"] = _inventory_entries_digest(payload["entries"])
    incomplete = tmp_path / "missing-explicit-exclusion.json"
    incomplete.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        BuiltinRouteContractCatalogErrorV2,
        match="explicit runtime exclusions are absent from inventory",
    ):
        build_builtin_route_contract_catalog_v2(inventory_path=incomplete)


@pytest.mark.unit
def test_catalog_loader_rejects_stale_contract_digest(
    route_catalog,
    tmp_path: Path,
) -> None:
    payload = route_catalog.to_payload()
    payload["rows"][0]["contract_digest"] = "sha256:" + "0" * 64
    stale = tmp_path / "stale-catalog.json"
    stale.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BuiltinRouteContractCatalogErrorV2, match="contract digest mismatch"):
        load_builtin_route_contract_catalog_v2(
            catalog_path=stale,
            inventory_path=_INVENTORY,
        )


@pytest.mark.unit
def test_catalog_loader_rejects_duplicate_and_reordered_rows(
    route_catalog,
    tmp_path: Path,
) -> None:
    payload = route_catalog.to_payload()
    payload["rows"][1] = dict(payload["rows"][0])
    duplicate = tmp_path / "duplicate-catalog.json"
    duplicate.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BuiltinRouteContractCatalogErrorV2, match="duplicate catalog row"):
        load_builtin_route_contract_catalog_v2(
            catalog_path=duplicate,
            inventory_path=_INVENTORY,
        )


@pytest.mark.unit
def test_catalog_loader_rehashes_source_artifacts_before_target_import(
    route_catalog,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    imported = False

    def fail_import(_name: str) -> object:
        nonlocal imported
        imported = True
        raise AssertionError("target import must not run before artifact validation")

    payload = route_catalog.to_payload()
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(payload), encoding="utf-8")
    artifact = route_catalog.rows[0].source_artifacts[0]
    stale_root = tmp_path / "stale-root"
    stale_path = stale_root / artifact.path
    stale_path.parent.mkdir(parents=True)
    stale_path.write_text("stale route source", encoding="utf-8")
    monkeypatch.setattr(route_contracts_module, "_ROOT", stale_root)
    monkeypatch.setattr(route_contracts_module.importlib, "import_module", fail_import)

    with pytest.raises(
        BuiltinRouteContractCatalogErrorV2,
        match="route source artifact digest mismatch",
    ):
        load_builtin_route_contract_catalog_v2(
            catalog_path=catalog_path,
            inventory_path=_INVENTORY,
        )
    assert imported is False


def _inventory_entries_digest(entries: list[dict[str, object]]) -> str:
    import hashlib

    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
