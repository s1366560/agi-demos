#!/usr/bin/env python3
"""Execute revision-bound Workspace implementation evidence suites."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR_PATH = REPO_ROOT / "scripts/workspace-core/generate-implementation-ledger.py"
DEFAULT_EVIDENCE = REPO_ROOT / "docs/architecture/workspace-core-implementation-evidence.json"
DEFAULT_OUTPUT = REPO_ROOT / ".cache/workspace-core/implementation-evidence-attestation.json"


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "workspace_core_implementation_ledger", GENERATOR_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load Workspace implementation ledger generator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_evidence_suites(
    evidence: Mapping[str, Any],
    *,
    repo_root: Path = REPO_ROOT,
    selected_suite_ids: frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    suites = evidence.get("suites")
    if not isinstance(suites, Sequence):
        raise ValueError("Workspace evidence suites are missing")
    known_ids = {str(suite["id"]) for suite in suites}
    if selected_suite_ids is not None:
        unknown_ids = selected_suite_ids - known_ids
        if unknown_ids:
            raise ValueError(f"unknown evidence suite ids: {sorted(unknown_ids)}")

    results: list[dict[str, Any]] = []
    for suite in suites:
        suite_id = str(suite["id"])
        if selected_suite_ids is not None and suite_id not in selected_suite_ids:
            continue
        command = str(suite["command"])
        completed = subprocess.run(
            ["/bin/sh", "-eu", "-c", command],
            cwd=repo_root,
            check=False,
        )
        results.append(
            {
                "id": suite_id,
                "command": command,
                "exitCode": completed.returncode,
                "passed": completed.returncode == 0,
            }
        )
        if completed.returncode != 0:
            break
    return results


def build_attestation(
    evidence: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
    *,
    source_sha256: str,
    source_revision: str,
    route_contract_sha256: str,
    implemented_route_keys_sha256: str,
    expected_suite_ids: frozenset[str] | None = None,
) -> dict[str, Any]:
    if source_revision != evidence.get("sourceRevision"):
        raise ValueError(
            "Workspace evidence attestation source revision drifted: "
            f"evidence={evidence.get('sourceRevision')}, requested={source_revision}"
        )
    all_expected_ids = {str(suite["id"]) for suite in evidence["suites"]}
    expected_ids = set(expected_suite_ids) if expected_suite_ids is not None else all_expected_ids
    unknown_ids = expected_ids - all_expected_ids
    if unknown_ids:
        raise ValueError(f"unknown evidence suite ids: {sorted(unknown_ids)}")
    completed_ids = {str(result["id"]) for result in results}
    passed = completed_ids == expected_ids and all(bool(result["passed"]) for result in results)
    return {
        "attestationVersion": 2,
        "sourceRevision": source_revision,
        "sourceSha256": source_sha256,
        "schemaRevision": evidence["schemaRevision"],
        "evidenceSourcesSha256": evidence["sourcesSha256"],
        "routeContractSha256": route_contract_sha256,
        "implementedRouteKeysSha256": implemented_route_keys_sha256,
        "suiteCount": len(expected_ids),
        "completedSuiteCount": len(completed_ids),
        "passed": passed,
        "results": list(results),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--suite", action="append", default=[])
    args = parser.parse_args()

    generator = _load_generator()
    evidence = generator.load_evidence_contract(args.evidence.resolve(), REPO_ROOT)
    manifest = generator.load_json(generator.DEFAULT_MANIFEST)
    implemented = generator.parse_implemented_routes(generator.DEFAULT_CAPABILITIES)
    ledger = generator.build_ledger(manifest, implemented, evidence)
    selected = frozenset(args.suite) or None
    results = run_evidence_suites(evidence, selected_suite_ids=selected)
    attestation = build_attestation(
        evidence,
        results,
        source_sha256=str(ledger["sourceSha256"]),
        source_revision=str(ledger["sourceRevision"]),
        route_contract_sha256=str(ledger["requiredContractSha256"]),
        implemented_route_keys_sha256=str(ledger["implementedRouteKeysSha256"]),
        expected_suite_ids=selected,
    )
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(attestation, indent=2) + "\n", encoding="utf-8")
    if not attestation["passed"]:
        print(f"Workspace implementation evidence failed: {output}", file=sys.stderr)
        return 1
    completed_ledger = generator.build_ledger(
        manifest,
        implemented,
        evidence,
        attestation=attestation,
    )
    generator.DEFAULT_OUTPUT.write_text(
        generator.render_ledger(completed_ledger),
        encoding="utf-8",
    )
    print(f"Workspace implementation evidence passed: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
