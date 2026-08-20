"""Transactional publication of desired HTTP routes through a v2 generation."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from src.configuration.workspace_core import get_workspace_core_settings
from src.infrastructure.adapters.primary.web.startup.http_route_publication_v2 import (
    HttpRoutePublicationCoordinatorV2,
    HttpRoutePublicationRejectedV2,
)
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
)
from src.infrastructure.plugins.http_routes import HttpRouteMountError


def _row(
    *,
    permission: str = "plugin.example.read",
    path: str = "/api/v1/plugins/{tenant_id}/example",
) -> SimpleNamespace:
    return SimpleNamespace(
        plugin_id="example-plugin",
        method="GET",
        path=path,
        permission=permission,
        authorization_mode="tenant_member",
        enabled=True,
    )


def _inventory(
    *,
    path: str = "/api/v1/plugins/{tenant_id}/example",
) -> dict[str, list[SimpleNamespace]]:
    async def handler(tenant_id: str) -> dict[str, str]:
        return {"tenant_id": tenant_id}

    return {
        "example-plugin": [
            SimpleNamespace(
                method="GET",
                path=path,
                plugin_name="example-plugin",
                handler=handler,
                tags=["Example"],
            )
        ]
    }


class FakeFallback:
    def __init__(self) -> None:
        self.disposals = 0

    def dispose(self) -> None:
        self.disposals += 1


async def _coordinator(
    monkeypatch: pytest.MonkeyPatch,
    *,
    inventory: dict[str, list[SimpleNamespace]],
) -> tuple[FastAPI, HttpRoutePublicationCoordinatorV2]:
    monkeypatch.setattr(
        "src.infrastructure.agent.plugins.registry.get_plugin_registry",
        lambda: SimpleNamespace(list_http_routes=lambda: inventory),
    )
    app = FastAPI()
    app.state.workspace_core_settings = get_workspace_core_settings()
    await initialize_plugin_runtime_v2(app)
    coordinator = app.state.platform_plugin_http_route_publication_v2
    assert isinstance(coordinator, HttpRoutePublicationCoordinatorV2)
    return app, coordinator


@pytest.mark.unit
async def test_reconcile_stages_new_generation_then_publishes_routes_and_openapi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, coordinator = await _coordinator(monkeypatch, inventory=_inventory())
    host = app.state.platform_plugin_runtime_v2
    registry = app.state.platform_plugin_route_registry_v2
    first_distribution = host.current_distribution
    first_route_publication = registry.current
    assert first_distribution is not None
    assert first_route_publication is not None
    old_lease = await host.acquire()
    old_generation = await old_lease.__aenter__()
    fallback = FakeFallback()

    result = await coordinator.reconcile(
        (_row(),),
        on_commit=lambda _graph: fallback.dispose(),
    )

    current = host.current_distribution
    assert current is not None
    assert current.descriptor.generation == 2
    assert current.descriptor.digest != first_distribution.descriptor.digest
    assert result.mounted == 1
    assert result.unmounted == 0
    assert result.route_publication is registry.current
    assert result.route_publication.descriptor == current.descriptor
    assert result.route_publication.openapi.descriptor == current.descriptor
    assert result.plugin_publication is not None
    assert result.plugin_publication.accepted
    assert "/api/v1/plugins/{tenant_id}/example" in result.route_publication.openapi.schema["paths"]
    assert registry.resolve(old_generation.descriptor) is first_route_publication
    assert fallback.disposals == 1

    repeated = await coordinator.reconcile(
        (_row(),),
        on_commit=lambda _graph: fallback.dispose(),
    )
    assert repeated.mounted == 0
    assert repeated.unmounted == 0
    assert repeated.plugin_publication is None
    assert host.current_distribution is current
    assert fallback.disposals == 1

    await old_lease.__aexit__(None, None, None)
    await host.close()


@pytest.mark.unit
async def test_reconcile_failure_keeps_last_good_generation_table_and_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, coordinator = await _coordinator(monkeypatch, inventory={})
    host = app.state.platform_plugin_runtime_v2
    registry = app.state.platform_plugin_route_registry_v2
    active = host.current_distribution
    route_publication = registry.current
    fallback = FakeFallback()

    with pytest.raises(HttpRouteMountError, match="handler is not owned"):
        await coordinator.reconcile(
            (_row(),),
            on_commit=lambda _graph: fallback.dispose(),
        )

    assert host.current_distribution is active
    assert registry.current is route_publication
    assert fallback.disposals == 0
    await host.close()


@pytest.mark.unit
async def test_private_graph_conflict_nacks_without_exposing_staged_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conflicting_path = "/api/v1/tenants/{tenant_id}"
    app, coordinator = await _coordinator(
        monkeypatch,
        inventory=_inventory(path=conflicting_path),
    )
    host = app.state.platform_plugin_runtime_v2
    registry = app.state.platform_plugin_route_registry_v2
    active = host.current_distribution
    route_publication = registry.current

    with pytest.raises(
        HttpRoutePublicationRejectedV2,
        match="conflicts with private graph",
    ) as error:
        await coordinator.reconcile((_row(path=conflicting_path),))

    assert not error.value.publication.accepted
    assert error.value.publication.receipt.error_code == "publication_staging_failed"
    assert host.current_distribution is active
    assert registry.current is route_publication
    await host.close()


@pytest.mark.unit
async def test_reconcile_permission_change_reports_replacement_and_new_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, coordinator = await _coordinator(monkeypatch, inventory=_inventory())
    host = app.state.platform_plugin_runtime_v2
    first = await coordinator.reconcile((_row(),))

    changed = await coordinator.reconcile(
        (_row(permission="plugin.example.admin-read"),),
    )

    assert changed.mounted == 0
    assert changed.unmounted == 1
    assert changed.route_publication.descriptor.generation == 3
    assert changed.route_publication.descriptor.digest != first.route_publication.descriptor.digest
    await host.close()
