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
    "rust-server": frozenset({"builtin://memstack/rust-server/generation-host"}),
    "desktop-sidecar": frozenset({"builtin://memstack/desktop-sidecar/local-capability"}),
    "web": frozenset(
        {
            "builtin://memstack/web/renderer-host",
            "builtin://memstack/web/renderer-contribution-registry",
            "builtin://memstack/web/renderer-contribution",
        }
    ),
    "desktop-renderer": frozenset(
        {
            "builtin://memstack/desktop/renderer-host",
            "builtin://memstack/desktop/renderer-contribution-registry",
            "builtin://memstack/desktop/renderer-contribution",
        }
    ),
}


@pytest.mark.unit
def test_generated_catalog_has_exact_production_modules_per_non_python_target() -> None:
    catalog = json.loads(_CATALOG.read_text(encoding="utf-8"))

    for target, expected_module_refs in _EXPECTED_TARGET_MODULES.items():
        matching = {
            module["module_ref"] for module in catalog["modules"] if target in module["targets"]
        }
        assert matching == expected_module_refs


@pytest.mark.unit
def test_generated_bootstrap_profile_projects_every_production_target() -> None:
    payload = json.loads(_BOOTSTRAP.read_text(encoding="utf-8"))
    snapshot = parse_profile_snapshot_v2(payload)
    modules = {
        module.module_ref: set(module.targets)
        for manifest in snapshot.manifests
        for module in manifest.modules
    }

    for target, module_refs in _EXPECTED_TARGET_MODULES.items():
        for module_ref in module_refs:
            assert target in {item.value for item in modules[module_ref]}
            assert any(
                entry.module_ref == module_ref and entry.enabled for entry in snapshot.entries
            )

    entries = payload["entries"]
    shell_index = next(
        index
        for index, entry in enumerate(entries)
        if entry["entry_id"] == "builtin-desktop-authenticated-shell-surface"
    )
    workbench_index = next(
        index
        for index, entry in enumerate(entries)
        if entry["entry_id"] == "builtin-desktop-workbench-surface"
    )
    assert len(entries) == 257
    assert shell_index < workbench_index
    assert entries[shell_index]["config"] == {
        "id": "desktop.authenticated-shell-surface",
        "kind": "ui-slot",
        "order": 80,
        "payload": {
            "artifact_refs": ["desktop.ui-slots.authenticated-shell-surface.v1"],
            "schema_version": 1,
        },
    }
