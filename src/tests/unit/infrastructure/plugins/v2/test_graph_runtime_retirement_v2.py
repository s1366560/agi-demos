"""Production composition gates for the generation-owned graph runtime."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import load_profile_document_v2
from src.infrastructure.plugins.v2.graph_runtime import GRAPH_RUNTIME_MODULE_V2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


def test_graph_runtime_is_an_explicit_profile_manifest_and_runtime_module() -> None:
    profile = load_profile_document_v2(_PROFILE_PATH)
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))

    enabled_modules = {entry.module_ref for entry in profile.entries if entry.enabled}
    manifest_modules = {module.module_ref for module in manifest.modules}
    runtime_modules = {definition.module_ref for definition in builtin_runtime_definitions_v2()}

    assert GRAPH_RUNTIME_MODULE_V2 in enabled_modules
    assert GRAPH_RUNTIME_MODULE_V2 in manifest_modules
    assert GRAPH_RUNTIME_MODULE_V2 in runtime_modules


def test_static_graph_startup_owner_is_removed() -> None:
    assert not (_ROOT / "src/infrastructure/adapters/primary/web/startup/graph.py").exists()

    startup_exports = (
        _ROOT / "src/infrastructure/adapters/primary/web/startup/__init__.py"
    ).read_text(encoding="utf-8")
    assert "initialize_graph_service" not in startup_exports
    assert "shutdown_graph_service" not in startup_exports


def test_lifespan_resolves_graph_after_v2_publication_before_legacy_consumers() -> None:
    source = (_ROOT / "src/infrastructure/adapters/primary/web/main.py").read_text(encoding="utf-8")

    assert "initialize_graph_service" not in source
    assert "shutdown_graph_service" not in source
    publication = source.index("await initialize_plugin_runtime_v2(")
    workflow = source.index("await initialize_workflow_engine(graph_service)")
    container = source.index("container = initialize_container(")
    assert publication < workflow < container


def test_graph_dependencies_resolve_from_the_pinned_generation() -> None:
    source = (_ROOT / "src/infrastructure/adapters/primary/web/dependencies/__init__.py").read_text(
        encoding="utf-8"
    )

    assert "GRAPH_RUNTIME_SERVICE_V2" in source
    assert "current_generation_v2()" in source
    assert "request.app.state.container.graph_service" not in source
    assert "get_env_default_store" not in source
