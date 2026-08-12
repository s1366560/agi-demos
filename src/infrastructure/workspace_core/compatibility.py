"""Fail-closed validation for the Avernet public Workspace API surface."""

from __future__ import annotations

import hashlib
import json

from src.infrastructure.workspace_core.client import (
    WorkspaceCoreCompatibilityError,
    WorkspaceCorePublicApiCapabilities,
)

WORKSPACE_PUBLIC_API_MANIFEST_VERSION = 1
WORKSPACE_PUBLIC_API_ROUTE_COUNT = 92
WORKSPACE_PUBLIC_API_CONTRACT_SHA256 = (
    "a20b3f3a5065b9ff4fad23310b4fa6c4eb6cc4f666be7957ec6c4b1ad65a9623"
)
WORKSPACE_PUBLIC_API_ROUTE_KEYS_SHA256 = (
    "e4fea0501bbf438e30f55e0937246fda5709fdf4e3b7831c85147c6303bb3f07"
)


def require_complete_public_api(capabilities: WorkspaceCorePublicApiCapabilities) -> None:
    """Reject an Avernet authority unless it proves the entire frozen route contract."""
    route_keys = [(route.method, route.path) for route in capabilities.implemented_routes]
    route_keys_sha256 = _route_keys_sha256(route_keys)
    checks = (
        (
            capabilities.manifest_version == WORKSPACE_PUBLIC_API_MANIFEST_VERSION,
            f"manifest version {capabilities.manifest_version} != "
            + str(WORKSPACE_PUBLIC_API_MANIFEST_VERSION),
        ),
        (
            capabilities.required_contract_sha256 == WORKSPACE_PUBLIC_API_CONTRACT_SHA256,
            "required contract hash differs from the gateway manifest",
        ),
        (
            capabilities.required_route_count == WORKSPACE_PUBLIC_API_ROUTE_COUNT,
            f"required route count {capabilities.required_route_count} != "
            + str(WORKSPACE_PUBLIC_API_ROUTE_COUNT),
        ),
        (
            capabilities.required_route_keys_sha256 == WORKSPACE_PUBLIC_API_ROUTE_KEYS_SHA256,
            "required route key hash differs from the gateway manifest",
        ),
        (
            capabilities.implemented_route_count == len(route_keys),
            "implemented route count does not match the advertised route list",
        ),
        (
            len(set(route_keys)) == len(route_keys),
            "implemented route list contains duplicate method/path pairs",
        ),
        (
            capabilities.implemented_route_keys_sha256 == route_keys_sha256,
            "implemented route key hash does not match the advertised route list",
        ),
        (
            capabilities.implemented_route_count == WORKSPACE_PUBLIC_API_ROUTE_COUNT,
            f"implemented route count {capabilities.implemented_route_count} != "
            + str(WORKSPACE_PUBLIC_API_ROUTE_COUNT),
        ),
        (
            capabilities.implemented_route_keys_sha256 == WORKSPACE_PUBLIC_API_ROUTE_KEYS_SHA256,
            "implemented route key hash is incomplete",
        ),
        (
            capabilities.implemented_contract_sha256 == WORKSPACE_PUBLIC_API_CONTRACT_SHA256,
            "implemented contract hash is incomplete",
        ),
        (capabilities.complete, "Core did not declare the public API complete"),
    )
    mismatches = [message for valid, message in checks if not valid]

    if mismatches:
        raise WorkspaceCoreCompatibilityError(
            "Workspace Core public API capability mismatch: " + "; ".join(mismatches)
        )


def _route_keys_sha256(route_keys: list[tuple[str, str]]) -> str:
    canonical_routes = [
        {"method": method, "path": path}
        for method, path in sorted(route_keys, key=lambda route: (route[1], route[0]))
    ]
    payload = json.dumps(
        canonical_routes,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "WORKSPACE_PUBLIC_API_CONTRACT_SHA256",
    "WORKSPACE_PUBLIC_API_MANIFEST_VERSION",
    "WORKSPACE_PUBLIC_API_ROUTE_COUNT",
    "WORKSPACE_PUBLIC_API_ROUTE_KEYS_SHA256",
    "require_complete_public_api",
]
