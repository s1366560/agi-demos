#!/usr/bin/env python3
"""Generate the checked-in Workspace HTTP/OpenAPI compatibility manifest."""

# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnusedCallResult=false

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import sys
from collections import Counter, deque
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi.routing import APIRoute
from pydantic import HttpUrl, SecretStr

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from fastapi import FastAPI


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO_ROOT / "docs/architecture/workspace-core-route-manifest.json"

WORKSPACE_ROUTER_MODULES = frozenset(
    {
        "src.infrastructure.adapters.primary.web.routers.blackboard",
        "src.infrastructure.adapters.primary.web.routers.cyber_genes",
        "src.infrastructure.adapters.primary.web.routers.cyber_objectives",
        "src.infrastructure.adapters.primary.web.routers.topology",
        "src.infrastructure.adapters.primary.web.routers.workspace_agent_policy",
        "src.infrastructure.adapters.primary.web.routers.workspace_autonomy",
        "src.infrastructure.adapters.primary.web.routers.workspace_chat",
        "src.infrastructure.adapters.primary.web.routers.workspace_collaboration_mutations",
        "src.infrastructure.adapters.primary.web.routers.workspace_context",
        "src.infrastructure.adapters.primary.web.routers.workspace_plans",
        "src.infrastructure.adapters.primary.web.routers.workspace_tasks",
        "src.infrastructure.adapters.primary.web.routers.workspaces",
    }
)

SCHEMA_REF_PREFIX = "#/components/schemas/"


def _create_application() -> FastAPI:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    # Importing ``main`` constructs its ASGI application at module scope. Supply
    # manifest-only credentials for that import, then restore the caller's
    # environment so this evidence command never mutates operator state.
    environment = {
        "WORKSPACE_CORE_BASE_URL": "http://workspace-core.manifest.invalid",
        "WORKSPACE_CORE_SERVICE_TOKEN": "manifest-service-token",
        "WORKSPACE_CORE_PROVIDER_WEBHOOK_TOKEN": "manifest-webhook-token",
        "WORKSPACE_CORE_PROVIDER_EVENT_TOKEN": "manifest-event-token",
        "WORKSPACE_CORE_AGENT_REGISTRY_TOKEN": "manifest-registry-token",
    }
    original = {name: os.environ.get(name) for name in environment}
    os.environ.update(environment)
    try:
        from src.infrastructure.adapters.primary.web.main import create_app
    finally:
        for name, value in original.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    from src.configuration.workspace_core import WorkspaceCoreSettings

    return create_app(
        workspace_core_settings=WorkspaceCoreSettings(
            WORKSPACE_CORE_BASE_URL=HttpUrl("http://workspace-core.manifest.invalid"),
            WORKSPACE_CORE_SERVICE_TOKEN=SecretStr("manifest-service-token"),
            WORKSPACE_CORE_PROVIDER_WEBHOOK_TOKEN=SecretStr("manifest-webhook-token"),
            WORKSPACE_CORE_PROVIDER_EVENT_TOKEN=SecretStr("manifest-event-token"),
            WORKSPACE_CORE_AGENT_REGISTRY_TOKEN=SecretStr("manifest-registry-token"),
        )
    )


def _iter_refs(value: object) -> Iterator[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "$ref" and isinstance(item, str):
                yield item
            else:
                yield from _iter_refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_refs(item)


def collect_referenced_schemas(
    values: Iterable[Any],
    available_schemas: dict[str, Any],
) -> dict[str, Any]:
    pending = deque(
        sorted(
            {
                ref.removeprefix(SCHEMA_REF_PREFIX)
                for value in values
                for ref in _iter_refs(value)
                if ref.startswith(SCHEMA_REF_PREFIX)
            }
        )
    )
    selected: dict[str, Any] = {}

    while pending:
        schema_name = pending.popleft()
        if schema_name in selected:
            continue
        if schema_name not in available_schemas:
            raise RuntimeError(f"OpenAPI schema reference is missing: {schema_name}")

        schema = available_schemas[schema_name]
        selected[schema_name] = schema
        nested_names = sorted(
            {
                ref.removeprefix(SCHEMA_REF_PREFIX)
                for ref in _iter_refs(schema)
                if ref.startswith(SCHEMA_REF_PREFIX)
            }
        )
        pending.extend(name for name in nested_names if name not in selected)

    return {name: selected[name] for name in sorted(selected)}


def canonical_sha256(manifest: dict[str, Any]) -> str:
    contract = {key: value for key, value in manifest.items() if key != "contractSha256"}
    payload = json.dumps(
        contract,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def build_manifest() -> dict[str, Any]:
    app = _create_application()
    openapi = app.openapi()
    routes: list[dict[str, Any]] = []

    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        endpoint = route.endpoint
        module = getattr(
            endpoint,
            "__workspace_contract_module__",
            getattr(endpoint, "__module__", ""),
        )
        if module not in WORKSPACE_ROUTER_MODULES:
            continue

        path = route.path
        for method in sorted(route.methods):
            operation = openapi["paths"][path][method.lower()]
            routes.append(
                {
                    "method": method,
                    "path": path,
                    "module": module,
                    "operationId": operation["operationId"],
                    "tags": operation.get("tags", []),
                    "parameters": operation.get("parameters", []),
                    "requestBody": operation.get("requestBody"),
                    "responses": operation.get("responses", {}),
                    "security": operation.get("security", []),
                    "deprecated": operation.get("deprecated", False),
                }
            )

    routes.sort(key=lambda route: (route["path"], route["method"], route["operationId"]))
    route_keys = {(route["method"], route["path"]) for route in routes}
    if len(route_keys) != len(routes):
        raise RuntimeError("Workspace route inventory contains duplicate method/path pairs")

    available_components = openapi.get("components", {})
    schemas = collect_referenced_schemas(
        routes,
        available_components.get("schemas", {}),
    )
    security_scheme_names = sorted(
        {name for route in routes for requirement in route["security"] for name in requirement}
    )
    available_security_schemes = available_components.get("securitySchemes", {})
    security_schemes = {
        name: available_security_schemes[name]
        for name in security_scheme_names
        if name in available_security_schemes
    }

    module_counts = Counter(route["module"] for route in routes)
    manifest: dict[str, Any] = {
        "manifestVersion": 1,
        "source": "create_app().routes and create_app().openapi()",
        "routerModules": sorted(WORKSPACE_ROUTER_MODULES),
        "moduleCounts": {name: module_counts[name] for name in sorted(module_counts)},
        "routeCount": len(routes),
        "routes": routes,
        "components": {
            "schemas": schemas,
            "securitySchemes": security_schemes,
        },
    }
    manifest["contractSha256"] = canonical_sha256(manifest)
    return manifest


def _render_manifest(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def _check_manifest(output: Path, rendered: str, route_count: int) -> int:
    if not output.is_file():
        print(f"Workspace route manifest is missing: {output}", file=sys.stderr)
        return 1

    current = output.read_text(encoding="utf-8")
    if current == rendered:
        print(f"Workspace route manifest is current ({route_count} routes): {output}")
        return 0

    print(f"Workspace route manifest drifted: {output}", file=sys.stderr)
    diff = difflib.unified_diff(
        current.splitlines(),
        rendered.splitlines(),
        fromfile=str(output),
        tofile="runtime Workspace routes",
        lineterm="",
    )
    for line in diff:
        print(line, file=sys.stderr)
    print("Re-run the generator without --check to accept the contract change.", file=sys.stderr)
    return 1


def _write_manifest(output: Path, rendered: str, route_count: int, contract_hash: str) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_suffix(f"{output.suffix}.tmp")
    temporary_output.write_text(rendered, encoding="utf-8")
    temporary_output.replace(output)
    print(f"Wrote {route_count} Workspace routes to {output} ({contract_hash})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when the checked-in manifest differs from the runtime routes",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"manifest path (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()

    manifest = build_manifest()
    rendered = _render_manifest(manifest)
    output = args.output.resolve()
    if args.check:
        return _check_manifest(output, rendered, manifest["routeCount"])
    return _write_manifest(
        output,
        rendered,
        manifest["routeCount"],
        manifest["contractSha256"],
    )


if __name__ == "__main__":
    raise SystemExit(main())
