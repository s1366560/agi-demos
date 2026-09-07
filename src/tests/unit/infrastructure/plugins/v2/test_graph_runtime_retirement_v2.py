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


def test_lifespan_publishes_graph_before_legacy_di_consumers() -> None:
    source = (_ROOT / "src/infrastructure/adapters/primary/web/main.py").read_text(encoding="utf-8")

    assert "initialize_graph_service" not in source
    assert "shutdown_graph_service" not in source
    publication = source.index("await initialize_plugin_runtime_v2(")
    container = source.index("container = initialize_container(")
    assert publication < container


def test_lifespan_does_not_hold_a_graph_generation_lease_until_shutdown() -> None:
    source = (_ROOT / "src/infrastructure/adapters/primary/web/main.py").read_text(encoding="utf-8")

    assert "graph_generation_lease" not in source
    assert "pin_generation_v2" not in source
    assert "graph_runtime_factory=graph_runtime_factory" in source
    assert "retrieval_runtime_factory=retrieval_runtime_factory" in source
    assert "graph_runtime_factory=create_native_graph_adapter" not in source


def test_legacy_di_and_agent_services_do_not_retain_graph_runtime_objects() -> None:
    paths = (
        "src/configuration/di_container.py",
        "src/configuration/containers/agent_container.py",
        "src/application/services/agent_service.py",
    )

    for relative_path in paths:
        source = (_ROOT / relative_path).read_text(encoding="utf-8")
        assert "_graph_service" not in source, relative_path

    di_source = (_ROOT / paths[0]).read_text(encoding="utf-8")
    assert "def graph_service(" not in di_source
    assert "def neo4j_client(" not in di_source


def test_router_scoped_container_clones_do_not_copy_graph_objects() -> None:
    assert not (_ROOT / "src/infrastructure/adapters/primary/web/routers/agent/utils.py").exists()
    paths = (
        "src/infrastructure/adapters/primary/web/routers/clusters.py",
        "src/infrastructure/adapters/primary/web/routers/deploy.py",
        "src/infrastructure/adapters/primary/web/routers/instances.py",
        "src/infrastructure/adapters/primary/web/routers/instance_files.py",
        "src/infrastructure/adapters/primary/web/routers/instance_templates.py",
        "src/infrastructure/adapters/primary/web/routers/skills.py",
        "src/infrastructure/adapters/primary/web/routers/subagents.py",
        "src/infrastructure/adapters/primary/web/routers/tenant_skill_configs.py",
        "src/infrastructure/adapters/primary/web/routers/agent/__init__.py",
    )

    for relative_path in paths:
        source = (_ROOT / relative_path).read_text(encoding="utf-8")
        assert "app_container.graph_service" not in source, relative_path


def test_graph_dependencies_resolve_from_the_pinned_generation() -> None:
    assert not (_ROOT / "src/infrastructure/adapters/primary/web/dependencies.py").exists()
    source = (_ROOT / "src/infrastructure/adapters/primary/web/dependencies/__init__.py").read_text(
        encoding="utf-8"
    )

    assert "GRAPH_RUNTIME_SERVICE_V2" in source
    assert "current_generation_v2()" in source
    assert "request.app.state.container.graph_service" not in source
    assert "get_env_default_store" not in source
