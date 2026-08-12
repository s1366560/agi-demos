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
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPO_ROOT / "docs/architecture/workspace-core-route-manifest.json"
DEFAULT_CAPABILITIES = (
    REPO_ROOT
    / "third_party/avernet-bcs/crates/bootstrap/memstack-workspace-core/src/capabilities.rs"
)
DEFAULT_OUTPUT = REPO_ROOT / "docs/architecture/workspace-core-implementation-ledger.json"

CAPABILITY_BLOCK_PATTERN = re.compile(
    r"PublicRouteCapability\s*\{\s*method:\s*\"(?P<method>[A-Z]+)\",\s*"
    r"path:\s*\"(?P<path>[^\"]+)\",\s*\}",
    re.MULTILINE,
)
SCHEMA_REF_PREFIX = "#/components/schemas/"
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected an object in {path}")
    return value


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
    return "golden_passed" if implemented else "pending"


def _write_gate(method: str, implemented: bool) -> str:
    if method in READ_METHODS:
        return "not_applicable"
    return "covered_by_route_golden" if implemented else "pending"


def _route_entry(route: dict[str, Any], implemented: bool) -> dict[str, Any]:
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
    manifest: dict[str, Any], implemented_routes: list[dict[str, str]]
) -> dict[str, Any]:
    routes = manifest.get("routes")
    if not isinstance(routes, list):
        raise ValueError("route manifest routes must be a list")
    manifest_keys = {(route["method"], route["path"]) for route in routes}
    implemented_keys = {(route["method"], route["path"]) for route in implemented_routes}
    unknown = sorted(implemented_keys - manifest_keys)
    if unknown:
        raise ValueError(f"implemented routes are absent from the frozen manifest: {unknown}")

    entries = [
        _route_entry(route, (route["method"], route["path"]) in implemented_keys)
        for route in routes
    ]
    canonical_implemented_routes = sorted(
        implemented_routes,
        key=lambda route: (route["path"], route["method"]),
    )
    implemented_route_keys_sha256 = canonical_sha256(canonical_implemented_routes)
    ledger: dict[str, Any] = {
        "ledgerVersion": 1,
        "sourceManifest": str(DEFAULT_MANIFEST.relative_to(REPO_ROOT)),
        "sourceCapabilities": str(DEFAULT_CAPABILITIES.relative_to(REPO_ROOT)),
        "requiredContractSha256": manifest.get("contractSha256"),
        "requiredRouteCount": len(entries),
        "implementedRouteCount": len(implemented_keys),
        "pendingRouteCount": len(entries) - len(implemented_keys),
        "implementedRouteKeysSha256": implemented_route_keys_sha256,
        "complete": len(entries) == len(implemented_keys),
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
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    ledger = build_ledger(
        load_json(args.manifest.resolve()),
        parse_implemented_routes(args.capabilities.resolve()),
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
