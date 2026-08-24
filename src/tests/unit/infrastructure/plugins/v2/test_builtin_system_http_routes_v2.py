"""Production V2 ownership tests for the builtin system HTTP row."""

from __future__ import annotations

from typing import Any

import pytest

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2 import builtin_system_http_routes as subject
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2


@pytest.mark.unit
def test_system_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.system_route_definitions_v2()

    assert {
        (method, definition.path) for definition in definitions for method in definition.methods
    } == {
        ("GET", "/api/v1/system/features"),
        ("GET", "/api/v1/system/info"),
    }
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.SYSTEM_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"system"}


@pytest.mark.unit
def test_system_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="system-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.system_route_definitions_v2(),
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
    assert claimed.v2_owned_row_ids == ("system",)


@pytest.mark.unit
async def test_system_v2_handlers_delegate_without_static_router_mount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []

    async def features(current_user: object) -> list[dict[str, Any]]:
        calls.append(("features", current_user))
        return [{"name": "v2"}]

    async def info(current_user: object) -> dict[str, Any]:
        calls.append(("info", current_user))
        return {"source": "v2"}

    monkeypatch.setattr(subject, "_list_features", features)
    monkeypatch.setattr(subject, "_get_system_info", info)
    user = object()

    assert await subject.list_system_features_v2(user) == [{"name": "v2"}]
    assert await subject.get_system_info_v2(user) == {"source": "v2"}
    assert calls == [("features", user), ("info", user)]


@pytest.mark.unit
def test_system_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_system_http_routes_definition_v2()

    assert definition.module_ref == subject.SYSTEM_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
