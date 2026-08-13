#!/usr/bin/env python3
"""Generate the fail-closed Workspace Core route implementation ledger."""

# pyright: reportImplicitStringConcatenation=false, reportUnusedCallResult=false
# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPO_ROOT / "docs/architecture/workspace-core-route-manifest.json"
DEFAULT_CAPABILITIES = (
    REPO_ROOT
    / "third_party/avernet-bcs/crates/bootstrap/memstack-workspace-core/src/capabilities.rs"
)
DEFAULT_OUTPUT = REPO_ROOT / "docs/architecture/workspace-core-implementation-ledger.json"
DEFAULT_EVIDENCE = REPO_ROOT / "docs/architecture/workspace-core-implementation-evidence.json"
DEFAULT_ATTESTATION = (
    REPO_ROOT / ".cache/workspace-core/implementation-evidence-attestation.json"
)
EVIDENCE_EXECUTION_GATE = "scripts/workspace-core/verify-implementation-evidence.py"

CAPABILITY_BLOCK_PATTERN = re.compile(
    r"PublicRouteCapability\s*\{\s*method:\s*\"(?P<method>[A-Z]+)\",\s*"
    r"path:\s*\"(?P<path>[^\"]+)\",\s*\}",
    re.MULTILINE,
)
SCHEMA_REF_PREFIX = "#/components/schemas/"
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
REQUIRED_ROUTE_GATES = frozenset(
    {"status", "permission", "cas", "idempotency", "events", "cloudPostgres", "desktopSqlite"}
)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected an object in {path}")
    return value


def _alembic_head(repo_root: Path) -> str:
    config = Config(str(repo_root / "alembic.ini"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise ValueError(f"expected one Alembic head, found {heads}")
    return heads[0]


def _evidence_suite_sources(
    suite_id: str,
    patterns: object,
    repo_root: Path,
) -> set[Path]:
    if not isinstance(patterns, list) or not patterns:
        raise ValueError(f"evidence suite {suite_id} source patterns are missing")
    source_paths: set[Path] = set()
    for pattern in patterns:
        if not isinstance(pattern, str) or not pattern:
            raise ValueError(f"evidence suite {suite_id} has an invalid source pattern")
        matches = {path for path in repo_root.glob(pattern) if path.is_file()}
        if not matches:
            raise ValueError(f"evidence source pattern matched no files: {pattern}")
        source_paths.update(matches)
    return source_paths


def _normalize_evidence_suite(
    suite: object,
    suite_ids: set[str],
    repo_root: Path,
) -> tuple[dict[str, Any], set[Path]]:
    if not isinstance(suite, Mapping):
        raise ValueError("Workspace implementation evidence suite must be an object")
    suite_id = suite.get("id")
    command = suite.get("command")
    gates = suite.get("gates")
    if not isinstance(suite_id, str) or not suite_id or suite_id in suite_ids:
        raise ValueError(f"invalid or duplicate evidence suite id: {suite_id}")
    suite_ids.add(suite_id)
    if not isinstance(command, str) or not command:
        raise ValueError(f"evidence suite {suite_id} command is missing")
    if not isinstance(gates, list) or not gates:
        raise ValueError(f"evidence suite {suite_id} gates are missing")
    gate_set = {str(gate) for gate in gates}
    unknown_gates = gate_set - REQUIRED_ROUTE_GATES
    if unknown_gates:
        raise ValueError(f"evidence suite {suite_id} has unknown gates: {sorted(unknown_gates)}")
    source_paths = _evidence_suite_sources(suite_id, suite.get("sourcePatterns"), repo_root)
    normalized = {
        "id": suite_id,
        "command": command,
        "gates": sorted(gate_set),
        "sourcePaths": sorted(str(path.relative_to(repo_root)) for path in source_paths),
    }
    return normalized, source_paths


def _source_digest(source_paths: set[Path], repo_root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(source_paths):
        relative_path = str(path.relative_to(repo_root))
        digest.update(relative_path.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def validate_evidence_contract(
    contract: Mapping[str, Any], repo_root: Path = REPO_ROOT
) -> dict[str, Any]:
    if contract.get("evidenceVersion") != 2:
        raise ValueError("unsupported Workspace implementation evidence version")
    schema_revision = contract.get("schemaRevision")
    if "sourceRevision" in contract:
        raise ValueError(
            "Workspace implementation evidence must derive sourceRevision from sourceSha256"
        )
    current_head = _alembic_head(repo_root)
    if schema_revision != current_head:
        raise ValueError(
            "Workspace implementation evidence schema revision drifted: "
            f"evidence={schema_revision}, current={current_head}"
        )
    suites = contract.get("suites")
    if not isinstance(suites, list) or not suites:
        raise ValueError("Workspace implementation evidence suites are missing")
    implementation_sources = _evidence_suite_sources(
        "implementation-runtime",
        contract.get("implementationSourcePatterns"),
        repo_root,
    )

    normalized_suites: list[dict[str, Any]] = []
    all_source_paths: set[Path] = set()
    suite_ids: set[str] = set()
    for suite in suites:
        normalized, source_paths = _normalize_evidence_suite(suite, suite_ids, repo_root)
        all_source_paths.update(source_paths)
        normalized_suites.append(normalized)

    covered_gates = {gate for suite in normalized_suites for gate in suite["gates"]}
    missing_gates = sorted(REQUIRED_ROUTE_GATES - covered_gates)
    if missing_gates:
        raise ValueError(f"missing required route evidence gates: {', '.join(missing_gates)}")

    source_sha256 = _source_digest(implementation_sources, repo_root)

    return {
        "evidenceVersion": 2,
        "sourceRevision": f"sha256:{source_sha256}",
        "schemaRevision": current_head,
        "suites": sorted(normalized_suites, key=lambda suite: suite["id"]),
        "sourceSha256": source_sha256,
        "sourcesSha256": _source_digest(all_source_paths, repo_root),
    }


def load_evidence_contract(path: Path, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    return validate_evidence_contract(load_json(path), repo_root)


def parse_implemented_routes(path: Path) -> list[dict[str, str]]:
    source = path.read_text(encoding="utf-8")
    declaration, separator, _remainder = source.partition("const IMPLEMENTED_CONTRACT_SHA256")
    if not separator:
        raise ValueError("IMPLEMENTED_CONTRACT_SHA256 declaration is missing")

    routes = [match.groupdict() for match in CAPABILITY_BLOCK_PATTERN.finditer(declaration)]
    keys = [(route["method"], route["path"]) for route in routes]
    if not routes:
        raise ValueError("IMPLEMENTED_PUBLIC_ROUTES is empty or cannot be parsed")
    if len(keys) != len(set(keys)):
        raise ValueError("IMPLEMENTED_PUBLIC_ROUTES contains duplicate method/path pairs")
    return routes


def _schema_references(value: object) -> list[str]:
    references: set[str] = set()

    def visit(item: object) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                if key == "$ref" and isinstance(nested, str):
                    references.add(nested.removeprefix(SCHEMA_REF_PREFIX))
                else:
                    visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    return sorted(references)


def _implemented_gate(implemented: bool) -> str:
    return "evidence_bound" if implemented else "pending"


def _write_gate(method: str, implemented: bool) -> str:
    if method in READ_METHODS:
        return "not_applicable"
    return "evidence_bound" if implemented else "pending"


def _route_entry(
    route: dict[str, Any],
    implemented: bool,
    evidence: Mapping[str, Any],
    *,
    route_contract_sha256: object,
    execution_results: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    method = str(route["method"])
    parameters = route.get("parameters", [])
    authorization_parameter = any(
        isinstance(parameter, dict)
        and parameter.get("in") == "header"
        and str(parameter.get("name", "")).lower() == "authorization"
        for parameter in parameters
    )
    gate = _implemented_gate(implemented)
    write_gate = _write_gate(method, implemented)
    suites = [
        suite
        for suite in evidence["suites"]
        if set(suite["gates"]) & REQUIRED_ROUTE_GATES
    ]
    return {
        "method": method,
        "path": route["path"],
        "module": route["module"],
        "handler": route["operationId"],
        "contract": {
            "requestSchemas": _schema_references(route.get("requestBody")),
            "responseSchemas": _schema_references(route.get("responses", {})),
            "responseStatusCodes": list(route.get("responses", {})),
            "authorizationParameter": authorization_parameter,
            "security": route.get("security", []),
        },
        "implementation": {
            "status": gate,
            "permission": gate,
            "cas": write_gate,
            "idempotency": write_gate,
            "events": write_gate,
            "cloudPostgres": gate,
            "desktopSqlite": gate,
        },
        "evidence": {
            "routeContractSha256": route_contract_sha256,
            "sourceRevision": evidence["sourceRevision"],
            "sourceSha256": evidence["sourceSha256"],
            "testSourcesSha256": evidence["sourcesSha256"],
            "testIds": [suite["id"] for suite in suites],
            "executionResults": [
                {
                    "testId": suite["id"],
                    "status": (
                        "passed"
                        if execution_results.get(suite["id"], {}).get("passed") is True
                        else "failed"
                        if suite["id"] in execution_results
                        else "missing"
                    ),
                }
                for suite in suites
            ],
        },
    }


def canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def build_ledger(
    manifest: dict[str, Any],
    implemented_routes: list[dict[str, str]],
    evidence: Mapping[str, Any],
    *,
    attestation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    routes = manifest.get("routes")
    if not isinstance(routes, list):
        raise ValueError("route manifest routes must be a list")
    manifest_keys = {(route["method"], route["path"]) for route in routes}
    implemented_keys = {(route["method"], route["path"]) for route in implemented_routes}
    unknown = sorted(implemented_keys - manifest_keys)
    if unknown:
        raise ValueError(f"implemented routes are absent from the frozen manifest: {unknown}")

    source_sha256 = evidence["sourceSha256"]
    attestation_results = (
        (attestation or {}).get("results", [])
        if (attestation or {}).get("attestationVersion") == 2
        and (attestation or {}).get("sourceSha256") == source_sha256
        and (attestation or {}).get("sourceRevision") == evidence["sourceRevision"]
        else []
    )
    execution_results = {
        str(result["id"]): result
        for result in attestation_results
        if isinstance(result, Mapping) and "id" in result
    }
    entries = [
        _route_entry(
            route,
            (route["method"], route["path"]) in implemented_keys,
            evidence,
            route_contract_sha256=manifest.get("contractSha256"),
            execution_results=execution_results,
        )
        for route in routes
    ]
    canonical_implemented_routes = sorted(
        implemented_routes,
        key=lambda route: (route["path"], route["method"]),
    )
    implemented_route_keys_sha256 = canonical_sha256(canonical_implemented_routes)
    declaration_complete = len(entries) == len(implemented_keys)
    expected_suite_ids = {str(suite["id"]) for suite in evidence["suites"]}
    attested_suite_ids = set(execution_results)
    execution_results_passed = bool(
        attested_suite_ids == expected_suite_ids
        and all(
            result.get("passed") is True
            and result.get("exitCode") == 0
            and result.get("command")
            == next(
                suite["command"]
                for suite in evidence["suites"]
                if suite["id"] == suite_id
            )
            for suite_id, result in execution_results.items()
        )
    )
    attestation_matches = bool(
        attestation is not None
        and attestation.get("attestationVersion") == 2
        and attestation.get("sourceSha256") == source_sha256
        and attestation.get("sourceRevision") == evidence["sourceRevision"]
        and attestation.get("passed") is True
        and attestation.get("schemaRevision") == evidence["schemaRevision"]
        and attestation.get("evidenceSourcesSha256") == evidence["sourcesSha256"]
        and attestation.get("routeContractSha256") == manifest.get("contractSha256")
        and attestation.get("implementedRouteKeysSha256")
        == implemented_route_keys_sha256
        and attestation.get("suiteCount") == len(evidence["suites"])
        and attestation.get("completedSuiteCount") == len(evidence["suites"])
        and execution_results_passed
    )
    ledger: dict[str, Any] = {
        "ledgerVersion": 2,
        "sourceRevision": evidence["sourceRevision"],
        "sourceSha256": source_sha256,
        "sourceManifest": str(DEFAULT_MANIFEST.relative_to(REPO_ROOT)),
        "sourceCapabilities": str(DEFAULT_CAPABILITIES.relative_to(REPO_ROOT)),
        "requiredContractSha256": manifest.get("contractSha256"),
        "requiredRouteCount": len(entries),
        "implementedRouteCount": len(implemented_keys),
        "pendingRouteCount": len(entries) - len(implemented_keys),
        "implementedRouteKeysSha256": implemented_route_keys_sha256,
        "sourceEvidence": str(DEFAULT_EVIDENCE.relative_to(REPO_ROOT)),
        "schemaRevision": evidence["schemaRevision"],
        "evidenceSuiteCount": len(evidence["suites"]),
        "evidenceSourcesSha256": evidence["sourcesSha256"],
        "evidenceSuites": evidence["suites"],
        "declarationComplete": declaration_complete,
        "evidenceAttested": attestation_matches,
        "evidenceExecutionRequired": True,
        "executionGate": EVIDENCE_EXECUTION_GATE,
        "complete": declaration_complete and attestation_matches,
        "routes": entries,
    }
    ledger["ledgerSha256"] = canonical_sha256(ledger)
    return ledger


def render_ledger(ledger: dict[str, Any]) -> str:
    return json.dumps(ledger, ensure_ascii=False, indent=2) + "\n"


def check_output(output: Path, rendered: str, ledger: dict[str, Any]) -> int:
    if not output.is_file():
        print(f"Workspace implementation ledger is missing: {output}")
        return 1
    current = output.read_text(encoding="utf-8")
    if current == rendered:
        if ledger["complete"] is not True:
            print(
                "Workspace implementation ledger is current but executable evidence "
                f"is missing, failed, or stale: {output}"
            )
            return 1
        print(
            "Workspace implementation ledger is current "
            f"({ledger['implementedRouteCount']}/{ledger['requiredRouteCount']} routes): {output}"
        )
        return 0
    print(f"Workspace implementation ledger drifted: {output}")
    for line in difflib.unified_diff(
        current.splitlines(),
        rendered.splitlines(),
        fromfile=str(output),
        tofile="runtime implementation ledger",
        lineterm="",
    ):
        print(line)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--capabilities", type=Path, default=DEFAULT_CAPABILITIES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--attestation", type=Path, default=DEFAULT_ATTESTATION)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    attestation_path = args.attestation.resolve()
    attestation = load_json(attestation_path) if attestation_path.is_file() else None
    ledger = build_ledger(
        load_json(args.manifest.resolve()),
        parse_implemented_routes(args.capabilities.resolve()),
        load_evidence_contract(args.evidence.resolve(), REPO_ROOT),
        attestation=attestation,
    )
    rendered = render_ledger(ledger)
    output = args.output.resolve()
    if args.check:
        return check_output(output, rendered, ledger)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(f"{output.suffix}.tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(output)
    print(
        f"Wrote {ledger['implementedRouteCount']}/{ledger['requiredRouteCount']} routes to "
        f"{output} ({ledger['ledgerSha256']})"
    )
    return 0 if ledger["complete"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
