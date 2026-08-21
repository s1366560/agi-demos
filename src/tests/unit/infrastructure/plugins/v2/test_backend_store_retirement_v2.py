"""Zero-reference gates for the retired backend-store shadow seam."""

from __future__ import annotations

import json
from inspect import signature
from pathlib import Path

import pytest

from src.infrastructure.adapters.primary.web.routers import projects
from src.infrastructure.plugins.v2.backend_store_services import (
    BACKEND_STORE_APPLICATION_MODULE_V2,
    BACKEND_STORE_PROVIDER_MODULE_V2,
    backend_store_service_definitions_v2,
)
from src.infrastructure.plugins.v2.composer import load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_SHADOW_MODULE_V2 = "builtin://memstack/application/backend-store-shadow"
_SHADOW_MARKERS = (
    "backend_store_shadow",
    "backend-store-shadow",
    "BackendStoreShadow",
)
_PRODUCTION_PATHS = (
    _ROOT / "src/application",
    _ROOT / "src/configuration",
    _ROOT / "src/domain",
    _ROOT / "src/infrastructure",
    _ROOT / "config/plugin-manifests-v2",
    _ROOT / "config/plugin-profiles",
    _ROOT / "agi-stack/crates/plugin-host/src/protocol_v2/generated_catalog.rs",
    _ROOT / "agi-stack/packages/plugin-runtime/src/generatedCatalog.ts",
)


def test_backend_store_runtime_definitions_only_keep_authoritative_modules() -> None:
    module_refs = tuple(
        definition.module_ref for definition in backend_store_service_definitions_v2()
    )

    assert module_refs == (
        BACKEND_STORE_PROVIDER_MODULE_V2,
        BACKEND_STORE_APPLICATION_MODULE_V2,
    )


def test_backend_store_profile_and_manifest_do_not_publish_shadow_module() -> None:
    profile = load_profile_document_v2(_PROFILE_PATH)
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))

    enabled_modules = {entry.module_ref for entry in profile.entries if entry.enabled}
    manifest_modules = {module.module_ref for module in manifest.modules}

    assert _SHADOW_MODULE_V2 not in enabled_modules
    assert _SHADOW_MODULE_V2 not in manifest_modules


def test_backend_store_shadow_adapter_and_route_dependency_are_removed() -> None:
    assert not (
        _ROOT / "src/infrastructure/adapters/primary/web/backend_store_shadow_v2.py"
    ).exists()
    assert "_backend_store_shadow" not in signature(projects.list_projects).parameters


def test_backend_store_shadow_has_no_production_references() -> None:
    references: list[str] = []
    for root in _PRODUCTION_PATHS:
        paths = root.rglob("*") if root.is_dir() else (root,)
        for path in paths:
            if not path.is_file() or path.suffix not in {".json", ".py", ".rs", ".ts", ".yaml"}:
                continue
            content = path.read_text(encoding="utf-8")
            if any(marker in content for marker in _SHADOW_MARKERS):
                references.append(str(path.relative_to(_ROOT)))

    assert references == []
