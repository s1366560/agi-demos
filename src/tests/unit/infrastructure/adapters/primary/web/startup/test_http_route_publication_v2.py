"""Transactional publication of desired HTTP routes through a v2 generation."""

from __future__ import annotations

from dataclasses import replace
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
from src.infrastructure.plugins.v2.composer import ProfileDocumentV2, compose_profile_v2
from src.infrastructure.plugins.v2.protocol import control_envelope_v2


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
async def test_publish_snapshot_uses_same_atomic_route_graph_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, coordinator = await _coordinator(monkeypatch, inventory=_inventory())
    host = app.state.platform_plugin_runtime_v2
    registry = app.state.platform_plugin_route_registry_v2
    current = host.current_distribution
    assert current is not None
    snapshot = compose_profile_v2(
        ProfileDocumentV2(
            profile_id=current.snapshot.profile_id,
            entries=current.snapshot.entries,
        ),
        {manifest.plugin_id: manifest for manifest in current.snapshot.manifests},
        generation=current.snapshot.generation + 1,
    )
    callback = FakeFallback()

    result = await coordinator.publish_snapshot(
        snapshot,
        control_envelope_v2(snapshot, version=current.envelope.version + 1),
        on_commit=lambda _graph: callback.dispose(),
    )

    assert result.plugin_publication.accepted is True
    assert result.graph is not None
    assert result.route_publication is registry.current
    assert result.route_publication is not None
    assert result.route_publication.descriptor.generation == snapshot.generation
    assert callback.disposals == 1
    await host.close()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("entry_id", "row_id"),
    (
        ("builtin-billing-http-routes", "billing"),
        (
            "builtin-workspace-core-static-http-routes",
            "workspace-core-static",
        ),
        ("builtin-workspace-core-http-routes", "workspace-core"),
        (
            "builtin-enhanced-search-http-routes",
            "enhanced-search, enhanced-search-memory",
        ),
        ("builtin-data-export-http-routes", "data-export"),
        ("builtin-episodes-http-routes", "episodes"),
        ("builtin-graph-http-routes", "graph"),
        ("builtin-graph-stores-http-routes", "graph-stores"),
        ("builtin-memories-http-routes", "memories"),
        ("builtin-project-my-work-http-routes", "project-my-work"),
        ("builtin-projects-http-routes", "projects"),
        ("builtin-recall-http-routes", "recall"),
        ("builtin-reflection-http-routes", "reflection"),
        ("builtin-schema-http-routes", "schema"),
        ("builtin-retrieval-stores-http-routes", "retrieval-stores"),
        ("builtin-system-http-routes", "system"),
        ("builtin-tenants-http-routes", "tenants"),
        ("builtin-tenant-webhooks-http-routes", "tenant-webhooks"),
        ("builtin-invitations-http-routes", "invitations"),
        ("builtin-invitations-public-http-routes", "invitations-public"),
        ("builtin-smtp-config-http-routes", "smtp-config"),
        ("builtin-trust-workspace-http-routes", "trust-workspace"),
    ),
)
async def test_disabling_migrated_builtin_row_nacks_and_keeps_last_good(
    monkeypatch: pytest.MonkeyPatch,
    entry_id: str,
    row_id: str,
) -> None:
    app, coordinator = await _coordinator(monkeypatch, inventory=_inventory())
    host = app.state.platform_plugin_runtime_v2
    registry = app.state.platform_plugin_route_registry_v2
    current = host.current_distribution
    current_routes = registry.current
    assert current is not None
    entries = tuple(
        replace(entry, enabled=False) if entry.entry_id == entry_id else entry
        for entry in current.snapshot.entries
    )
    snapshot = compose_profile_v2(
        ProfileDocumentV2(
            profile_id=current.snapshot.profile_id,
            entries=entries,
        ),
        {manifest.plugin_id: manifest for manifest in current.snapshot.manifests},
        generation=current.snapshot.generation + 1,
    )

    result = await coordinator.publish_snapshot(
        snapshot,
        control_envelope_v2(snapshot, version=current.envelope.version + 1),
    )

    assert result.plugin_publication.accepted is False
    assert result.plugin_publication.receipt.error_code == "publication_staging_failed"
    assert f"required V2 builtin route row claims missing: {row_id}" in (
        result.plugin_publication.receipt.error_message or ""
    )
    assert host.current_distribution is current
    assert registry.current is current_routes
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
    conflicting_path = (
        "/api/v1/tenants/{tenant_id}/projects/{project_id}/pool/instances/{agent_mode}"
    )
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
        match="duplicate v2 route",
    ) as error:
        await coordinator.reconcile((_row(path=conflicting_path),))

    assert not error.value.publication.accepted
    assert error.value.publication.receipt.error_code == "staging_failed"
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
