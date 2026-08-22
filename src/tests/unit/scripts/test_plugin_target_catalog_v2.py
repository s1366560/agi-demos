"""Production target-catalog coverage for protocol v2."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.infrastructure.plugins.v2.protocol import parse_profile_snapshot_v2

_ROOT = Path(__file__).resolve().parents[4]
_CATALOG = _ROOT / "shared/catalogs/plugin-module-catalog.v2.json"
_BOOTSTRAP = _ROOT / "shared/profiles/memstack-default-bootstrap.v2.json"

_EXPECTED_TARGET_MODULES = {
    "rust-server": "builtin://memstack/rust-server/generation-host",
    "desktop-sidecar": "builtin://memstack/desktop-sidecar/local-capability",
    "web": "builtin://memstack/web/renderer-host",
    "desktop-renderer": "builtin://memstack/desktop/renderer-host",
}


@pytest.mark.unit
def test_generated_catalog_has_one_production_host_module_per_non_python_target() -> None:
    catalog = json.loads(_CATALOG.read_text(encoding="utf-8"))

    for target, module_ref in _EXPECTED_TARGET_MODULES.items():
        matching = [module for module in catalog["modules"] if target in module["targets"]]
        assert [module["module_ref"] for module in matching] == [module_ref]


@pytest.mark.unit
def test_generated_bootstrap_profile_projects_every_production_target() -> None:
    snapshot = parse_profile_snapshot_v2(json.loads(_BOOTSTRAP.read_text(encoding="utf-8")))
    modules = {
        module.module_ref: set(module.targets)
        for manifest in snapshot.manifests
        for module in manifest.modules
    }

    for target, module_ref in _EXPECTED_TARGET_MODULES.items():
        assert target in {item.value for item in modules[module_ref]}
        assert any(entry.module_ref == module_ref and entry.enabled for entry in snapshot.entries)
