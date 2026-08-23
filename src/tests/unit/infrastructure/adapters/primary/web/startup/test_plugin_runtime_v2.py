"""Application lifecycle tests for the protocol v2 runtime."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.startup.generation_http_v2 import (
    mount_generation_http_dispatcher_v2,
)
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    DEFAULT_MANIFEST_V2_PATHS,
    DEFAULT_PROFILE_V2_PATH,
    initialize_plugin_runtime_v2,
    plugin_runtime_host_v2_from_scope,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2ApplyStateEventModel,
    PlatformPluginV2ApplyStateModel,
    PlatformPluginV2PublicationModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginPublicationPolicyV2,
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.boundary import (
    PluginGenerationMiddlewareV2,
    current_process_generation_host_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.graph_runtime import (
    GRAPH_RUNTIME_SERVICE_V2,
    GraphRuntimeFactoryV2,
    GraphRuntimeServiceV2,
)
from src.infrastructure.plugins.v2.http_routes import RouteDefinitionV2, RouteTableBuilderV2
from src.infrastructure.plugins.v2.legacy_http_route_bridge import (
    configured_legacy_http_routes_v2,
)
from src.infrastructure.plugins.v2.route_effects import ROUTE_TABLE_BUILDER_SERVICE_V2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2


@pytest.mark.unit
async def test_initialize_and_shutdown_plugin_runtime_v2() -> None:
    app = FastAPI()

    host = await initialize_plugin_runtime_v2(app)

    assert plugin_runtime_host_v2_from_scope({"app": app}) is host
    assert current_process_generation_host_v2() is host
    assert host.manager.current is not None
    route_registry = app.state.platform_plugin_route_registry_v2
    route_graph = app.state.platform_plugin_route_graph_v2
    assert app.state.platform_plugin_http_route_publication_v2 is not None
    assert route_registry.current is not None
    assert route_registry.current.descriptor == host.manager.current.descriptor
    assert len(route_graph.mounted_row_ids) == 71
    assert len(route_graph.static_mounted_row_ids) == 37
    assert route_graph.v2_owned_row_ids == (
        "tenants",
        "project-sandbox",
        "project-my-work",
        "projects",
        "shares",
        "memories",
        "graph",
        "graph-stores",
        "retrieval-stores",
        "schema",
        "episodes",
        "recall",
        "reflection",
        "enhanced-search",
        "enhanced-search-memory",
        "data-export",
        "cron",
        "ai-tools",
        "background-tasks",
        "billing",
        "notifications",
        "support",
        "support-2",
        "mcp",
        "sandbox",
        "trust-workspace",
        "smtp-config",
        "tenant-webhooks",
        "system",
        "events",
        "engines",
        "invitations",
        "invitations-public",
        "project-sandbox-preview",
    )
    assert {definition.owner_entry_id for definition in route_graph.table.definitions} >= {
        "builtin-billing-http-routes",
        "builtin-background-tasks-http-routes",
        "builtin-ai-tools-http-routes",
        "builtin-data-export-http-routes",
        "builtin-cron-http-routes",
        "builtin-enhanced-search-http-routes",
        "builtin-episodes-http-routes",
        "builtin-events-http-routes",
        "builtin-engines-http-routes",
        "builtin-invitations-http-routes",
        "builtin-invitations-public-http-routes",
        "builtin-graph-http-routes",
        "builtin-graph-stores-http-routes",
        "builtin-memories-http-routes",
        "builtin-mcp-http-routes",
        "builtin-sandbox-http-routes",
        "builtin-shares-http-routes",
        "builtin-notifications-http-routes",
        "builtin-project-sandbox-http-routes",
        "builtin-support-http-routes",
        "builtin-project-my-work-http-routes",
        "builtin-projects-http-routes",
        "builtin-recall-http-routes",
        "builtin-reflection-http-routes",
        "builtin-schema-http-routes",
        "builtin-retrieval-stores-http-routes",
        "builtin-smtp-config-http-routes",
        "builtin-system-http-routes",
        "builtin-tenants-http-routes",
        "builtin-tenant-webhooks-http-routes",
        "builtin-trust-workspace-http-routes",
    }
    assert len(route_graph.route_signatures) > 72
    assert route_registry.current.openapi.descriptor == host.manager.current.descriptor
    route_builder = host.manager.current.resolve(
        ROUTE_TABLE_BUILDER_SERVICE_V2,
        ScopeV2(kind=ScopeKindV2.ROOT),
    )
    assert isinstance(route_builder, RouteTableBuilderV2)
    with pytest.raises(RuntimeV2Error) as error:
        route_builder.contribute(
            RouteDefinitionV2(
                owner_entry_id="late-route",
                path="/api/v2/late",
                methods=("GET",),
                endpoint=lambda: {"ok": True},
                name="late-route",
            )
        )
    assert error.value.code == "route_table_frozen"
    await shutdown_plugin_runtime_v2(app)
    assert app.state.platform_plugin_runtime_v2 is None
    assert host.manager.current is None
    assert app.state.platform_plugin_route_registry_v2 is None
    assert app.state.platform_plugin_route_graph_v2 is None
    assert app.state.platform_plugin_http_route_publication_v2 is None
    with pytest.raises(RuntimeV2Error) as error:
        current_process_generation_host_v2()
    assert error.value.code == "process_generation_host_not_configured"


@pytest.mark.unit
async def test_initialize_plugin_runtime_v2_activates_graph_factory() -> None:
    app = FastAPI()
    closed = False

    class GraphService:
        async def close(self) -> None:
            nonlocal closed
            closed = True

    graph_service = GraphService()

    async def graph_factory() -> object:
        return graph_service

    host = await initialize_plugin_runtime_v2(
        app,
        graph_runtime_factory=cast("GraphRuntimeFactoryV2", graph_factory),
    )
    generation = host.manager.current
    assert generation is not None
    runtime = generation.resolve(
        GRAPH_RUNTIME_SERVICE_V2,
        ScopeV2(kind=ScopeKindV2.ROOT),
    )

    assert isinstance(runtime, GraphRuntimeServiceV2)
    assert runtime.graph_service is graph_service

    await shutdown_plugin_runtime_v2(app)

    assert closed is True


@pytest.mark.unit
def test_scope_resolution_fails_before_runtime_startup() -> None:
    app = FastAPI()

    with pytest.raises(RuntimeError, match="not initialized"):
        plugin_runtime_host_v2_from_scope({"app": app})


def _desired_route(*, path: str = "/plugin-startup/{tenant_id}/hello") -> SimpleNamespace:
    return SimpleNamespace(
        plugin_id="startup-plugin",
        method="GET",
        path=path,
        permission="plugin.startup.read",
        authorization_mode="tenant_member",
        enabled=True,
    )


def _route_inventory(
    *,
    path: str = "/plugin-startup/{tenant_id}/hello",
) -> dict[str, list[SimpleNamespace]]:
    async def handler(tenant_id: str) -> dict[str, str]:
        return {"tenant_id": tenant_id, "source": "generation-one"}

    return {
        "startup-plugin": [
            SimpleNamespace(
                plugin_name="startup-plugin",
                method="GET",
                path=path,
                handler=handler,
                tags=("Startup",),
            )
        ]
    }


async def _allow_route() -> None:
    return None


@pytest.mark.unit
async def test_generation_one_projects_desired_routes_without_outer_mount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = "/plugin-startup/{tenant_id}/hello"
    monkeypatch.setattr(
        "src.infrastructure.plugins.v2.legacy_http_route_bridge._legacy_inventory",
        _route_inventory,
    )
    monkeypatch.setattr(
        "src.infrastructure.plugins.v2.legacy_http_route_bridge._legacy_authorization",
        lambda _row: _allow_route,
    )
    app = FastAPI()
    app.add_middleware(
        PluginGenerationMiddlewareV2,
        host_provider=plugin_runtime_host_v2_from_scope,
    )
    mount_generation_http_dispatcher_v2(app)

    host = await initialize_plugin_runtime_v2(
        app,
        desired_http_route_rows=(_desired_route(),),
    )

    distribution = host.current_distribution
    assert distribution is not None
    assert distribution.descriptor.generation == 1
    assert configured_legacy_http_routes_v2(distribution.snapshot.entries)[0].path == path
    assert path not in {getattr(route, "path", None) for route in app.router.routes}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/plugin-startup/tenant-1/hello")
    assert response.status_code == 200
    assert response.json() == {"tenant_id": "tenant-1", "source": "generation-one"}
    await host.close()


@pytest.mark.unit
async def test_restart_uses_durable_last_good_instead_of_unpublished_desired_rows(
    db_session: AsyncSession,
) -> None:
    @asynccontextmanager
    async def session_factory():
        yield db_session

    first_app = FastAPI()
    first = await initialize_plugin_runtime_v2(
        first_app,
        session_factory=session_factory,
    )
    first_distribution = first.current_distribution
    assert first_distribution is not None
    assert (
        await PlatformPluginRepositoryV2(db_session).last_good_distribution("python-api-v2")
        == first_distribution.to_payload()
    )
    await first.close()

    restarted_app = FastAPI()
    restarted = await initialize_plugin_runtime_v2(
        restarted_app,
        desired_http_route_rows=(_desired_route(path="not-an-absolute-path"),),
        session_factory=session_factory,
    )

    restarted_distribution = restarted.current_distribution
    assert restarted_distribution is not None
    assert restarted_distribution.to_payload() == first_distribution.to_payload()
    assert configured_legacy_http_routes_v2(restarted_distribution.snapshot.entries) == ()
    await restarted.close()


@pytest.mark.unit
async def test_restart_upgrades_legacy_empty_target_snapshot_with_monotonic_publication(
    db_session: AsyncSession,
) -> None:
    @asynccontextmanager
    async def session_factory():
        yield db_session

    legacy_host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    legacy = await legacy_host.bootstrap(
        profile_path=DEFAULT_PROFILE_V2_PATH,
        manifest_paths=(DEFAULT_MANIFEST_V2_PATHS[-1],),
        generation=7,
        version=11,
        nonce="legacy-empty-target-snapshot",
    )
    assert legacy.accepted
    await PlatformPluginRepositoryV2(db_session).record_publication_and_receipt(
        legacy,
        data_plane_id="python-api-v2",
    )
    await db_session.commit()
    await legacy_host.close()

    newer_requested_host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    newer_requested = await newer_requested_host.bootstrap(
        profile_path=DEFAULT_PROFILE_V2_PATH,
        manifest_paths=(DEFAULT_MANIFEST_V2_PATHS[-1],),
        generation=9,
        version=15,
        nonce="newer-unapplied-empty-target-snapshot",
    )
    await PlatformPluginRepositoryV2(db_session).record_publication(newer_requested)
    await db_session.commit()
    await newer_requested_host.close()

    app = FastAPI()
    upgraded = await initialize_plugin_runtime_v2(app, session_factory=session_factory)

    distribution = upgraded.current_distribution
    assert distribution is not None
    assert distribution.snapshot.generation == 10
    assert distribution.envelope.version == 16
    enabled_modules = {entry.module_ref for entry in distribution.snapshot.entries if entry.enabled}
    assert {
        "builtin://memstack/rust-server/generation-host",
        "builtin://memstack/desktop-sidecar/local-capability",
        "builtin://memstack/web/renderer-host",
        "builtin://memstack/web/renderer-contribution-registry",
        "builtin://memstack/web/renderer-contribution",
        "builtin://memstack/desktop/renderer-host",
        "builtin://memstack/desktop/renderer-contribution-registry",
        "builtin://memstack/desktop/renderer-contribution",
    } <= enabled_modules
    assert (
        await PlatformPluginRepositoryV2(db_session).latest_requested_distribution()
        == distribution.to_payload()
    )
    await upgraded.close()


@pytest.mark.unit
async def test_startup_records_publication_without_unrequired_local_receipt(
    db_session: AsyncSession,
) -> None:
    @asynccontextmanager
    async def session_factory():
        yield db_session

    policy = PlatformPluginPublicationPolicyV2(
        required_data_plane_ids=("rust-server",),
        ack_deadline_seconds=30,
    )
    app = FastAPI()

    host = await initialize_plugin_runtime_v2(
        app,
        session_factory=session_factory,
        publication_policy=policy,
    )

    publication = await db_session.scalar(select(PlatformPluginV2PublicationModel))
    state = await db_session.scalar(select(PlatformPluginV2ApplyStateModel))
    assert publication is not None
    assert publication.required_data_plane_ids == ["rust-server"]
    assert state is None
    assert app.state.platform_plugin_publication_policy_v2 is policy
    await host.close()


@pytest.mark.unit
async def test_restart_nack_is_durable_and_retains_last_good(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @asynccontextmanager
    async def session_factory():
        yield db_session

    first_app = FastAPI()
    first = await initialize_plugin_runtime_v2(first_app, session_factory=session_factory)
    first_distribution = first.current_distribution
    assert first_distribution is not None
    await first.close()

    def reject_route_graph(**_kwargs: object) -> None:
        raise RuntimeError("route graph rejected during restart")

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2.build_builtin_route_graph_v2",
        reject_route_graph,
    )

    with pytest.raises(RuntimeV2Error, match="route graph rejected during restart"):
        await initialize_plugin_runtime_v2(FastAPI(), session_factory=session_factory)

    state = await db_session.scalar(select(PlatformPluginV2ApplyStateModel))
    assert state is not None
    assert state.status == "nack"
    assert state.requested_version == 1
    assert state.applied_version == 1
    assert state.applied_digest == first_distribution.descriptor.digest
    assert (
        await PlatformPluginRepositoryV2(db_session).last_good_distribution("python-api-v2")
        == first_distribution.to_payload()
    )
    event_count = await db_session.scalar(
        select(func.count()).select_from(PlatformPluginV2ApplyStateEventModel)
    )
    assert event_count == 2


@pytest.mark.unit
async def test_generation_one_fails_closed_when_desired_handler_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.infrastructure.plugins.v2.legacy_http_route_bridge._legacy_inventory",
        dict,
    )
    app = FastAPI()

    with pytest.raises(RuntimeError, match="handler is not owned"):
        await initialize_plugin_runtime_v2(app, desired_http_route_rows=(_desired_route(),))

    assert not hasattr(app.state, "platform_plugin_runtime_v2")


@pytest.mark.unit
async def test_generation_one_fails_closed_when_desired_path_is_unsafe() -> None:
    app = FastAPI()

    with pytest.raises(ValueError, match="unsafe legacy HTTP route definition"):
        await initialize_plugin_runtime_v2(
            app,
            desired_http_route_rows=(_desired_route(path="not-an-absolute-path"),),
        )

    assert not hasattr(app.state, "platform_plugin_runtime_v2")


@pytest.mark.unit
async def test_generation_one_fails_closed_on_builtin_route_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = "/api/v1/llm-providers/tenants/{tenant_id}/assignments"
    monkeypatch.setattr(
        "src.infrastructure.plugins.v2.legacy_http_route_bridge._legacy_inventory",
        lambda: _route_inventory(path=path),
    )
    monkeypatch.setattr(
        "src.infrastructure.plugins.v2.legacy_http_route_bridge._legacy_authorization",
        lambda _row: _allow_route,
    )
    app = FastAPI()

    with pytest.raises(RuntimeV2Error, match="conflicts with private graph"):
        await initialize_plugin_runtime_v2(
            app,
            desired_http_route_rows=(_desired_route(path=path),),
        )

    assert not hasattr(app.state, "platform_plugin_runtime_v2")
