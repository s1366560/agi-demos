"""Contracts for the generated Workspace Core implementation ledger."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[7]
GENERATOR_PATH = REPO_ROOT / "scripts/workspace-core/generate-implementation-ledger.py"
MANIFEST_PATH = REPO_ROOT / "docs/architecture/workspace-core-route-manifest.json"
CAPABILITIES_PATH = (
    REPO_ROOT
    / "third_party/avernet-bcs/crates/bootstrap/memstack-workspace-core/src/capabilities.rs"
)
LEDGER_PATH = REPO_ROOT / "docs/architecture/workspace-core-implementation-ledger.json"


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "workspace_core_implementation_ledger", GENERATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_implementation_ledger_matches_complete_capabilities() -> None:
    generator = _load_generator()
    manifest = generator.load_json(MANIFEST_PATH)
    implemented = generator.parse_implemented_routes(CAPABILITIES_PATH)
    ledger = generator.build_ledger(manifest, implemented)

    assert ledger["requiredRouteCount"] == 92
    assert ledger["implementedRouteCount"] == len(implemented)
    assert ledger["implementedRouteCount"] == 92
    assert ledger["pendingRouteCount"] == 0
    assert ledger["implementedRouteKeysSha256"] == (
        "e4fea0501bbf438e30f55e0937246fda5709fdf4e3b7831c85147c6303bb3f07"
    )
    assert ledger["complete"] is True
    assert len(ledger["routes"]) == 92
    assert generator.render_ledger(ledger) == LEDGER_PATH.read_text(encoding="utf-8")


def test_implemented_write_route_claims_transaction_and_store_coverage() -> None:
    generator = _load_generator()
    ledger = generator.build_ledger(
        generator.load_json(MANIFEST_PATH),
        generator.parse_implemented_routes(CAPABILITIES_PATH),
    )

    implemented_write = next(
        route
        for route in ledger["routes"]
        if route["implementation"]["status"] == "golden_passed" and route["method"] == "POST"
    )
    assert implemented_write["implementation"] == {
        "status": "golden_passed",
        "permission": "golden_passed",
        "cas": "covered_by_route_golden",
        "idempotency": "covered_by_route_golden",
        "events": "covered_by_route_golden",
        "cloudPostgres": "golden_passed",
        "desktopSqlite": "golden_passed",
    }


def test_read_route_marks_write_only_gates_not_applicable() -> None:
    generator = _load_generator()
    ledger = generator.build_ledger(
        generator.load_json(MANIFEST_PATH),
        generator.parse_implemented_routes(CAPABILITIES_PATH),
    )
    implemented_read = next(
        route
        for route in ledger["routes"]
        if route["implementation"]["status"] == "golden_passed" and route["method"] == "GET"
    )

    assert implemented_read["implementation"]["cas"] == "not_applicable"
    assert implemented_read["implementation"]["idempotency"] == "not_applicable"
    assert implemented_read["implementation"]["events"] == "not_applicable"


def test_implemented_route_hash_is_independent_of_declaration_order() -> None:
    generator = _load_generator()
    manifest = generator.load_json(MANIFEST_PATH)
    implemented = generator.parse_implemented_routes(CAPABILITIES_PATH)

    forward = generator.build_ledger(manifest, implemented)
    reverse = generator.build_ledger(manifest, list(reversed(implemented)))

    assert forward["implementedRouteKeysSha256"] == reverse["implementedRouteKeysSha256"]
