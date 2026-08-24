"""Final protocol-v1 HTTP route bridge retirement gate."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from fastapi import FastAPI

from src.configuration.workspace_core import get_workspace_core_settings
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
)
from src.infrastructure.plugins.v2.builtin_http_routes import REQUIRED_V2_BUILTIN_ROUTE_ROW_IDS
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2

_ROOT = Path(__file__).resolve().parents[6]
_FORBIDDEN_TOKENS = (
    "builtin-routes.v1.json",
    "builtin-http-route-rows.v2.json",
    "install_builtin_routes",
    "legacy-http-route-bridge",
    "builtin://memstack/http/legacy-route-bridge",
    "legacy_http_route_bridge",
)
_PROTOCOL_V1_RUNTIME_TOKENS = (
    "platform-plugins/snapshot",
    "platform-plugins/apply-state",
    "platform-plugins/frontend/",
    "platformPluginAdminService",
    "PlatformPluginApplyState",
    "PlatformPluginSnapshot",
    "getPlatformPluginFrontendModule",
    "SignedUiModuleBoundary",
    "UiSlotRuntime",
    "listTenantPlugins",
    "installTenantPlugin",
    "enableTenantPlugin",
    "disableTenantPlugin",
    "uninstallTenantPlugin",
    "reloadTenantPlugins",
    "getTenantPluginConfigSchema",
    "getTenantPluginConfig",
    "updateTenantPluginConfig",
    "listManagedPlugins",
    "getManagedPluginRuntime",
    "setManagedPluginEnabled",
    "installManagedPlugin",
    "reloadManagedPlugins",
    "uninstallManagedPlugin",
    "getManagedPluginConfigSchema",
    "getManagedPluginConfig",
    "updateManagedPluginConfig",
    "pluginManagementModel",
    "PluginRuntimeActivity",
)
_V1_RENDERER_ROOTS = (
    _ROOT / "agi-stack/packages/plugin-slots/src",
    _ROOT / "agi-stack/apps/desktop/src",
    _ROOT / "web/src",
)
_PRODUCTION_ROOTS = (
    _ROOT / "src/infrastructure",
    _ROOT / "config/plugin-manifests-v2",
    _ROOT / "config/plugin-profiles",
    _ROOT / "shared/catalogs",
    _ROOT / "shared/graphs",
    _ROOT / "shared/profiles",
    _ROOT / "agi-stack/crates/plugin-host/src/protocol_v2",
    _ROOT / "agi-stack/packages/plugin-runtime/src",
    *_V1_RENDERER_ROOTS,
)


def _production_text_files(roots: tuple[Path, ...] = _PRODUCTION_ROOTS) -> tuple[Path, ...]:
    files: list[Path] = []
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if (
                "tests" in path.parts
                or "test" in path.parts
                or path.suffix not in {".json", ".py", ".rs", ".ts", ".tsx", ".yaml"}
            ):
                continue
            files.append(path)
    return tuple(files)


@pytest.mark.unit
def test_protocol_v1_http_route_bridge_has_no_production_contract_or_runtime_path() -> None:
    violations = {
        str(path.relative_to(_ROOT)): token
        for path in _production_text_files()
        for token in _FORBIDDEN_TOKENS
        if token in path.read_text(encoding="utf-8")
    }

    assert violations == {}
    assert not (_ROOT / "src/infrastructure/plugins/route_loader.py").exists()
    assert "desired_http_route_rows" not in inspect.signature(
        initialize_plugin_runtime_v2
    ).parameters
    assert all(
        definition.module_ref != "builtin://memstack/http/legacy-route-bridge"
        for definition in builtin_runtime_definitions_v2()
    )


@pytest.mark.unit
async def test_v2_http_graph_owns_every_required_row_without_static_inventory() -> None:
    app = FastAPI()
    app.state.workspace_core_settings = get_workspace_core_settings()
    host = await initialize_plugin_runtime_v2(app)
    graph = app.state.platform_plugin_route_graph_v2

    assert graph.static_mounted_row_ids == ()
    assert set(graph.mounted_row_ids) == REQUIRED_V2_BUILTIN_ROUTE_ROW_IDS
    assert set(graph.v2_owned_row_ids) == REQUIRED_V2_BUILTIN_ROUTE_ROW_IDS
    assert graph.mounted_row_ids == graph.v2_owned_row_ids

    await host.close()


@pytest.mark.unit
def test_protocol_v1_runtime_has_no_web_or_desktop_production_reference() -> None:
    violations = {
        str(path.relative_to(_ROOT)): token
        for path in _production_text_files(_V1_RENDERER_ROOTS)
        for token in _PROTOCOL_V1_RUNTIME_TOKENS
        if token in path.read_text(encoding="utf-8")
    }

    assert violations == {}
