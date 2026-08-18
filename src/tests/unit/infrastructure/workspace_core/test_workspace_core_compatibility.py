"""Tests for the fail-closed Workspace public API capability gate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.infrastructure.workspace_core.client import (
    WorkspaceCoreCompatibilityError,
    WorkspaceCorePublicApiCapabilities,
)
from src.infrastructure.workspace_core.compatibility import (
    WORKSPACE_PUBLIC_API_CONTRACT_SHA256,
    WORKSPACE_PUBLIC_API_MANIFEST_VERSION,
    WORKSPACE_PUBLIC_API_ROUTE_COUNT,
    WORKSPACE_PUBLIC_API_ROUTE_KEYS_SHA256,
    require_complete_public_api,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
MANIFEST_PATH = REPO_ROOT / "docs/architecture/workspace-core-route-manifest.json"


def _manifest_routes() -> list[dict[str, str]]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return [{"method": route["method"], "path": route["path"]} for route in manifest["routes"]]


def _capabilities(**overrides: object) -> WorkspaceCorePublicApiCapabilities:
    values: dict[str, object] = {
        "protocol_version": 1,
        "manifest_version": WORKSPACE_PUBLIC_API_MANIFEST_VERSION,
        "required_contract_sha256": WORKSPACE_PUBLIC_API_CONTRACT_SHA256,
        "required_route_count": WORKSPACE_PUBLIC_API_ROUTE_COUNT,
        "required_route_keys_sha256": WORKSPACE_PUBLIC_API_ROUTE_KEYS_SHA256,
        "implemented_contract_sha256": WORKSPACE_PUBLIC_API_CONTRACT_SHA256,
        "implemented_route_count": WORKSPACE_PUBLIC_API_ROUTE_COUNT,
        "implemented_route_keys_sha256": WORKSPACE_PUBLIC_API_ROUTE_KEYS_SHA256,
        "implemented_routes": _manifest_routes(),
        "complete": True,
        **overrides,
    }
    return WorkspaceCorePublicApiCapabilities.model_validate(values)


@pytest.mark.unit
def test_frozen_manifest_satisfies_public_api_capability_gate() -> None:
    require_complete_public_api(_capabilities())


@pytest.mark.unit
def test_incomplete_core_is_rejected_before_gateway_startup() -> None:
    with pytest.raises(
        WorkspaceCoreCompatibilityError,
        match=r"implemented route count 0 != 92.*implemented contract hash is incomplete",
    ):
        require_complete_public_api(
            _capabilities(
                implemented_contract_sha256=None,
                implemented_route_count=0,
                implemented_route_keys_sha256=(
                    "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
                ),
                implemented_routes=[],
                complete=False,
            )
        )


@pytest.mark.unit
def test_advertised_route_hash_must_match_the_route_list() -> None:
    with pytest.raises(
        WorkspaceCoreCompatibilityError,
        match="implemented route key hash does not match the advertised route list",
    ):
        require_complete_public_api(_capabilities(implemented_route_keys_sha256="0" * 64))
