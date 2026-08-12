from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[7]
GENERATOR_PATH = REPO_ROOT / "scripts/workspace-core/generate-route-manifest.py"
MANIFEST_PATH = REPO_ROOT / "docs/architecture/workspace-core-route-manifest.json"

EXPECTED_CONTRACT_SHA256 = "a20b3f3a5065b9ff4fad23310b4fa6c4eb6cc4f666be7957ec6c4b1ad65a9623"
EXPECTED_MODULE_COUNTS = {
    "src.infrastructure.adapters.primary.web.routers.blackboard": 19,
    "src.infrastructure.adapters.primary.web.routers.cyber_genes": 5,
    "src.infrastructure.adapters.primary.web.routers.cyber_objectives": 6,
    "src.infrastructure.adapters.primary.web.routers.topology": 10,
    "src.infrastructure.adapters.primary.web.routers.workspace_agent_policy": 4,
    "src.infrastructure.adapters.primary.web.routers.workspace_autonomy": 1,
    "src.infrastructure.adapters.primary.web.routers.workspace_chat": 3,
    "src.infrastructure.adapters.primary.web.routers.workspace_collaboration_mutations": 3,
    "src.infrastructure.adapters.primary.web.routers.workspace_context": 2,
    "src.infrastructure.adapters.primary.web.routers.workspace_plans": 11,
    "src.infrastructure.adapters.primary.web.routers.workspace_tasks": 14,
    "src.infrastructure.adapters.primary.web.routers.workspaces": 14,
}


def _load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _canonical_contract_sha256(manifest: dict[str, Any]) -> str:
    contract = {key: value for key, value in manifest.items() if key != "contractSha256"}
    payload = json.dumps(
        contract,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


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


def test_checked_in_manifest_matches_runtime_routes() -> None:
    result = subprocess.run(
        [sys.executable, str(GENERATOR_PATH), "--check"],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "WORKSPACE_CORE_BACKEND": "avernet",
            "WORKSPACE_CORE_BASE_URL": "http://workspace-core.test",
            "WORKSPACE_CORE_SERVICE_TOKEN": "manifest-service-token",
            "WORKSPACE_CORE_PROVIDER_WEBHOOK_TOKEN": "manifest-webhook-token",
            "WORKSPACE_CORE_PROVIDER_EVENT_TOKEN": "manifest-event-token",
            "WORKSPACE_CORE_AGENT_REGISTRY_TOKEN": "manifest-registry-token",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_manifest_freezes_workspace_route_inventory() -> None:
    manifest = _load_manifest()
    routes = manifest["routes"]
    route_keys = {(route["method"], route["path"]) for route in routes}

    assert manifest["manifestVersion"] == 1
    assert manifest["routeCount"] == 92
    assert len(routes) == 92
    assert len(route_keys) == 92
    assert manifest["moduleCounts"] == EXPECTED_MODULE_COUNTS
    assert manifest["routerModules"] == sorted(EXPECTED_MODULE_COUNTS)
    assert manifest["contractSha256"] == EXPECTED_CONTRACT_SHA256
    assert manifest["contractSha256"] == _canonical_contract_sha256(manifest)


def test_manifest_preserves_openapi_contract_summaries() -> None:
    manifest = _load_manifest()
    schemas = manifest["components"]["schemas"]

    for route in manifest["routes"]:
        assert route["operationId"]
        assert isinstance(route["parameters"], list)
        assert route["requestBody"] is None or isinstance(route["requestBody"], dict)
        assert route["responses"]

    schema_prefix = "#/components/schemas/"
    referenced_schemas = {
        ref.removeprefix(schema_prefix)
        for ref in _iter_refs(manifest["routes"])
        if ref.startswith(schema_prefix)
    }
    assert referenced_schemas
    assert referenced_schemas <= schemas.keys()
