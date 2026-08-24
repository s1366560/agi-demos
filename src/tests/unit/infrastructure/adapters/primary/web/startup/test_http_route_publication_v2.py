"""Transactional publication of V2-owned HTTP route generations."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi import FastAPI

from src.configuration.workspace_core import get_workspace_core_settings
from src.infrastructure.adapters.primary.web.startup.http_route_publication_v2 import (
    HttpRoutePublicationCoordinatorV2,
)
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
)
from src.infrastructure.plugins.v2.composer import ProfileDocumentV2, compose_profile_v2
from src.infrastructure.plugins.v2.protocol import control_envelope_v2


class FakeFallback:
    def __init__(self) -> None:
        self.disposals = 0

    def dispose(self) -> None:
        self.disposals += 1


async def _coordinator(
) -> tuple[FastAPI, HttpRoutePublicationCoordinatorV2]:
    app = FastAPI()
    app.state.workspace_core_settings = get_workspace_core_settings()
    await initialize_plugin_runtime_v2(app)
    coordinator = app.state.platform_plugin_http_route_publication_v2
    assert isinstance(coordinator, HttpRoutePublicationCoordinatorV2)
    return app, coordinator

@pytest.mark.unit
async def test_publish_snapshot_uses_same_atomic_route_graph_transaction(
) -> None:
    app, coordinator = await _coordinator()
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
    entry_id: str,
    row_id: str,
) -> None:
    app, coordinator = await _coordinator()
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
    assert f"required V2 route contributions are missing: {row_id}" in (
        result.plugin_publication.receipt.error_message or ""
    )
    assert host.current_distribution is current
    assert registry.current is current_routes
    await host.close()
