"""Contracts for the generated Workspace Core implementation ledger."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[7]
GENERATOR_PATH = REPO_ROOT / "scripts/workspace-core/generate-implementation-ledger.py"
MANIFEST_PATH = REPO_ROOT / "docs/architecture/workspace-core-route-manifest.json"
CAPABILITIES_PATH = (
    REPO_ROOT
    / "third_party/avernet-bcs/crates/bootstrap/memstack-workspace-core/src/capabilities.rs"
)
LEDGER_PATH = REPO_ROOT / "docs/architecture/workspace-core-implementation-ledger.json"
EVIDENCE_PATH = REPO_ROOT / "docs/architecture/workspace-core-implementation-evidence.json"


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
    evidence = generator.load_evidence_contract(EVIDENCE_PATH, REPO_ROOT)
    ledger = generator.build_ledger(manifest, implemented, evidence)

    assert ledger["requiredRouteCount"] == 92
    assert ledger["implementedRouteCount"] == len(implemented)
    assert ledger["implementedRouteCount"] == 92
    assert ledger["pendingRouteCount"] == 0
    assert ledger["implementedRouteKeysSha256"] == (
        "e4fea0501bbf438e30f55e0937246fda5709fdf4e3b7831c85147c6303bb3f07"
    )
    assert ledger["declarationComplete"] is True
    assert ledger["complete"] is False
    assert ledger["evidenceAttested"] is False
    assert ledger["evidenceExecutionRequired"] is True
    assert ledger["executionGate"] == "scripts/workspace-core/verify-implementation-evidence.py"
    assert ledger["ledgerVersion"] == 2
    assert len(ledger["sourceSha256"]) == 64
    assert ledger["sourceRevision"] == f"sha256:{ledger['sourceSha256']}"
    assert ledger["schemaRevision"] == generator._alembic_head(REPO_ROOT)
    assert len(ledger["evidenceSourcesSha256"]) == 64
    assert ledger["evidenceSuiteCount"] == 6
    assert len(ledger["routes"]) == 92
    persisted = generator.load_json(LEDGER_PATH)
    assert persisted["requiredRouteCount"] == ledger["requiredRouteCount"]
    assert persisted["implementedRouteKeysSha256"] == ledger["implementedRouteKeysSha256"]
    assert persisted["complete"] in (False, True)


def test_implemented_write_route_claims_transaction_and_store_coverage() -> None:
    generator = _load_generator()
    ledger = generator.build_ledger(
        generator.load_json(MANIFEST_PATH),
        generator.parse_implemented_routes(CAPABILITIES_PATH),
        generator.load_evidence_contract(EVIDENCE_PATH, REPO_ROOT),
    )

    implemented_write = next(
        route
        for route in ledger["routes"]
        if route["implementation"]["status"] == "evidence_bound" and route["method"] == "POST"
    )
    assert implemented_write["implementation"] == {
        "status": "evidence_bound",
        "permission": "evidence_bound",
        "cas": "evidence_bound",
        "idempotency": "evidence_bound",
        "events": "evidence_bound",
        "cloudPostgres": "evidence_bound",
        "desktopSqlite": "evidence_bound",
    }
    assert implemented_write["evidence"]["routeContractSha256"] == ledger[
        "requiredContractSha256"
    ]
    assert implemented_write["evidence"]["sourceSha256"] == ledger["sourceSha256"]
    assert implemented_write["evidence"]["sourceRevision"] == ledger["sourceRevision"]
    assert implemented_write["evidence"]["testSourcesSha256"] == ledger[
        "evidenceSourcesSha256"
    ]
    assert implemented_write["evidence"]["testIds"]
    assert all(
        result["status"] == "missing"
        for result in implemented_write["evidence"]["executionResults"]
    )


def test_read_route_marks_write_only_gates_not_applicable() -> None:
    generator = _load_generator()
    ledger = generator.build_ledger(
        generator.load_json(MANIFEST_PATH),
        generator.parse_implemented_routes(CAPABILITIES_PATH),
        generator.load_evidence_contract(EVIDENCE_PATH, REPO_ROOT),
    )
    implemented_read = next(
        route
        for route in ledger["routes"]
        if route["implementation"]["status"] == "evidence_bound" and route["method"] == "GET"
    )

    assert implemented_read["implementation"]["cas"] == "not_applicable"
    assert implemented_read["implementation"]["idempotency"] == "not_applicable"
    assert implemented_read["implementation"]["events"] == "not_applicable"


def test_implemented_route_hash_is_independent_of_declaration_order() -> None:
    generator = _load_generator()
    manifest = generator.load_json(MANIFEST_PATH)
    implemented = generator.parse_implemented_routes(CAPABILITIES_PATH)
    evidence = generator.load_evidence_contract(EVIDENCE_PATH, REPO_ROOT)

    forward = generator.build_ledger(manifest, implemented, evidence)
    reverse = generator.build_ledger(manifest, list(reversed(implemented)), evidence)

    assert forward["implementedRouteKeysSha256"] == reverse["implementedRouteKeysSha256"]


def test_evidence_contract_fails_closed_when_a_required_route_gate_is_missing() -> None:
    generator = _load_generator()
    evidence = generator.load_json(EVIDENCE_PATH)
    for suite in evidence["suites"]:
        suite["gates"] = [gate for gate in suite["gates"] if gate != "cloudPostgres"]

    with pytest.raises(ValueError, match="missing required route evidence gates: cloudPostgres"):
        generator.build_ledger(
            generator.load_json(MANIFEST_PATH),
            generator.parse_implemented_routes(CAPABILITIES_PATH),
            generator.validate_evidence_contract(evidence, REPO_ROOT),
        )


def test_evidence_contract_fails_closed_when_a_source_pattern_matches_nothing() -> None:
    generator = _load_generator()
    evidence = generator.load_json(EVIDENCE_PATH)
    evidence["suites"][0]["sourcePatterns"].append("missing/evidence/**/*.rs")

    with pytest.raises(ValueError, match="matched no files"):
        generator.validate_evidence_contract(evidence, REPO_ROOT)


def test_ledger_becomes_complete_only_with_a_current_passing_attestation() -> None:
    generator = _load_generator()
    manifest = generator.load_json(MANIFEST_PATH)
    implemented = generator.parse_implemented_routes(CAPABILITIES_PATH)
    evidence = generator.load_evidence_contract(EVIDENCE_PATH, REPO_ROOT)
    unattested = generator.build_ledger(manifest, implemented, evidence)
    attestation = {
        "attestationVersion": 2,
        "sourceSha256": unattested["sourceSha256"],
        "sourceRevision": unattested["sourceRevision"],
        "schemaRevision": evidence["schemaRevision"],
        "evidenceSourcesSha256": evidence["sourcesSha256"],
        "routeContractSha256": unattested["requiredContractSha256"],
        "implementedRouteKeysSha256": unattested["implementedRouteKeysSha256"],
        "suiteCount": len(evidence["suites"]),
        "completedSuiteCount": len(evidence["suites"]),
        "passed": True,
        "results": [
            {
                "id": suite["id"],
                "command": suite["command"],
                "exitCode": 0,
                "passed": True,
            }
            for suite in evidence["suites"]
        ],
    }

    complete = generator.build_ledger(
        manifest,
        implemented,
        evidence,
        attestation=attestation,
    )
    stale = generator.build_ledger(
        manifest,
        implemented,
        evidence,
        attestation={**attestation, "evidenceSourcesSha256": "0" * 64},
    )
    stale_revision = generator.build_ledger(
        manifest,
        implemented,
        evidence,
        attestation={**attestation, "sourceRevision": "0" * 40},
    )

    assert complete["complete"] is True
    assert complete["evidenceAttested"] is True
    assert stale["complete"] is False
    assert stale["evidenceAttested"] is False
    assert stale_revision["complete"] is False
    assert stale_revision["evidenceAttested"] is False


def test_evidence_contract_rejects_a_pinned_git_source_revision() -> None:
    generator = _load_generator()
    evidence = generator.load_json(EVIDENCE_PATH)
    evidence["sourceRevision"] = "0" * 40

    with pytest.raises(ValueError, match="must derive sourceRevision"):
        generator.validate_evidence_contract(evidence, REPO_ROOT)


def test_ledger_check_fails_when_execution_evidence_is_missing(tmp_path: Path) -> None:
    generator = _load_generator()
    ledger = generator.build_ledger(
        generator.load_json(MANIFEST_PATH),
        generator.parse_implemented_routes(CAPABILITIES_PATH),
        generator.load_evidence_contract(EVIDENCE_PATH, REPO_ROOT),
    )
    output = tmp_path / "ledger.json"
    output.write_text(generator.render_ledger(ledger), encoding="utf-8")

    assert ledger["declarationComplete"] is True
    assert ledger["complete"] is False
    assert generator.check_output(output, generator.render_ledger(ledger), ledger) == 1
