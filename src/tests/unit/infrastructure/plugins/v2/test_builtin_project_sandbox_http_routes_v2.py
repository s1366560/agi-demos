"""Production V2 ownership tests for project sandbox HTTP/WebSocket rows."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2 import builtin_project_sandbox_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, RuntimeV2Error
from src.infrastructure.plugins.v2.sandbox_http_service_registry import (
    SANDBOX_HTTP_SERVICE_REGISTRY_MODULE_V2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


def test_project_sandbox_rows_are_complete_explicit_v2_contributions() -> None:
    definitions = subject.project_sandbox_route_definitions_v2()

    assert tuple(
        (
            definition.replaces_builtin_row_id,
            definition.path,
            tuple(sorted(definition.methods)),
            definition.name,
        )
        for definition in definitions
    ) == (
        (
            "project-sandbox",
            "/api/v1/projects/{project_id}/sandbox/capabilities",
            ("GET",),
            "get_project_sandbox_runtime_capabilities",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/{project_id}/sandbox/files",
            ("GET",),
            "list_project_sandbox_files",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/{project_id}/sandbox/files/content",
            ("GET",),
            "read_project_sandbox_file",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/{project_id}/sandbox/files/download",
            ("GET",),
            "download_project_sandbox_file",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/{project_id}/sandbox/desktop/session",
            ("POST",),
            "create_project_sandbox_desktop_session",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/{project_id}/sandbox",
            ("GET",),
            "get_project_sandbox",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/{project_id}/sandbox/proxy-auth-cookie",
            ("POST",),
            "seed_project_sandbox_proxy_auth_cookie",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/{project_id}/sandbox",
            ("POST",),
            "ensure_project_sandbox",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/{project_id}/sandbox/health",
            ("GET",),
            "check_project_sandbox_health",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/{project_id}/sandbox/stats",
            ("GET",),
            "get_project_sandbox_stats",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/{project_id}/sandbox/execute",
            ("POST",),
            "execute_tool_in_project_sandbox",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/{project_id}/sandbox/restart",
            ("POST",),
            "restart_project_sandbox",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/{project_id}/sandbox",
            ("DELETE",),
            "terminate_project_sandbox",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/{project_id}/sandbox/sync",
            ("GET",),
            "sync_project_sandbox_status",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/sandboxes",
            ("GET",),
            "list_project_sandboxes",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/sandboxes/cleanup",
            ("POST",),
            "cleanup_stale_sandboxes",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/{project_id}/sandbox/desktop",
            ("POST",),
            "start_project_desktop",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/{project_id}/sandbox/desktop",
            ("DELETE",),
            "stop_project_desktop",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/{project_id}/sandbox/terminal",
            ("POST",),
            "start_project_terminal",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/{project_id}/sandbox/terminal",
            ("DELETE",),
            "stop_project_terminal",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/{project_id}/sandbox/http-services",
            ("POST",),
            "register_project_http_service",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/{project_id}/sandbox/http-services",
            ("GET",),
            "list_project_http_services",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/{project_id}/sandbox/http-services/{service_id}/preview-session",
            ("POST",),
            "create_project_http_service_preview_session",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/{project_id}/sandbox/http-services/{service_id}",
            ("DELETE",),
            "stop_project_http_service",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/{project_id}/sandbox/http-services/{service_id}/proxy/{path:path}",
            ("DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"),
            "proxy_project_http_service",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/{project_id}/sandbox/http-services/{service_id}/proxy",
            ("DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"),
            "proxy_project_http_service",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/{project_id}/sandbox/http-services/{service_id}/proxy/ws/{path:path}",
            ("WEBSOCKET",),
            "proxy_project_http_service_websocket",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/{project_id}/sandbox/http-services/{service_id}/proxy/ws",
            ("WEBSOCKET",),
            "proxy_project_http_service_websocket",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/{project_id}/sandbox/desktop/proxy/{path:path}",
            ("GET",),
            "proxy_project_desktop",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/{project_id}/sandbox/desktop/proxy/websockify",
            ("WEBSOCKET",),
            "proxy_project_desktop_websocket",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/{project_id}/sandbox/terminal/proxy/ws",
            ("WEBSOCKET",),
            "proxy_project_terminal_websocket",
        ),
        (
            "project-sandbox",
            "/api/v1/projects/{project_id}/sandbox/mcp/proxy",
            ("WEBSOCKET",),
            "proxy_project_mcp_websocket",
        ),
        (
            "project-sandbox-preview",
            "/{path:path}",
            ("DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"),
            "proxy_project_http_service_preview_host",
        ),
        (
            "project-sandbox-preview",
            "/{path:path}",
            ("WEBSOCKET",),
            "proxy_project_http_service_preview_host_websocket",
        ),
    )
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.PROJECT_SANDBOX_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {
        "project-sandbox",
        "project-sandbox-preview",
    }


def test_project_sandbox_rows_preserve_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="project-sandbox-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.project_sandbox_route_definitions_v2(),
    )

    assert claimed.route_signatures == tuple(
        (
            definition.path,
            definition.name,
            ()
            if definition.methods == ("WEBSOCKET",)
            else tuple(sorted(definition.methods)),
        )
        for definition in claimed.table.definitions
    )
    assert claimed.table.openapi_snapshot(descriptor).schema["openapi"].startswith("3.")
    assert claimed.v2_owned_row_ids == (
        "project-sandbox",
        "project-sandbox-preview",
    )


async def test_project_sandbox_routes_reject_missing_registry_provider() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == SANDBOX_HTTP_SERVICE_REGISTRY_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=94)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert subject.PROJECT_SANDBOX_HTTP_ROUTES_ENTRY_V2 in str(error.value)


def test_project_sandbox_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_project_sandbox_http_routes_definition_v2()

    assert definition.module_ref == subject.PROJECT_SANDBOX_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
