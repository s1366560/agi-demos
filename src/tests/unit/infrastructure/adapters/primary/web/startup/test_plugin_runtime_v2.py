"""Application lifecycle tests for the protocol v2 runtime."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
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
from src.infrastructure.adapters.secondary.persistence.platform_plugin_deadline_reconciler_v2 import (
    PlatformPluginDeadlineReconcilerV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginPublicationPolicyV2,
    PlatformPluginRepositoryV2,
)
from src.infrastructure.agent.hitl import local_resume_consumer as local_resume_consumer_mod
from src.infrastructure.plugins.v2.boundary import current_process_generation_host_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.graph_runtime import (
    GRAPH_RUNTIME_SERVICE_V2,
    GraphRuntimeFactoryV2,
    GraphRuntimeServiceV2,
)
from src.infrastructure.plugins.v2.http_routes import RouteDefinitionV2, RouteTableBuilderV2
from src.infrastructure.plugins.v2.route_effects import ROUTE_TABLE_BUILDER_SERVICE_V2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2


@pytest.mark.unit
async def test_shutdown_stops_publication_deadline_reconciler_without_runtime_host() -> None:
    app = FastAPI()
    deadline_reconciler = AsyncMock(spec=PlatformPluginDeadlineReconcilerV2)
    app.state.platform_plugin_deadline_reconciler_v2 = deadline_reconciler

    await shutdown_plugin_runtime_v2(app)

    deadline_reconciler.stop.assert_awaited_once_with()
    assert app.state.platform_plugin_deadline_reconciler_v2 is None


@pytest.mark.unit
async def test_initialize_and_shutdown_plugin_runtime_v2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    assert route_graph.static_mounted_row_ids == ()
    assert route_graph.v2_owned_row_ids == (
        "auth",
        "workspace-core-static",
        "tenants",
        "project-my-work",
        "projects",
        "agent",
        "shares",
        "memories",
        "graph",
        "graph-stores",
        "retrieval-stores",
        "episodes",
        "enhanced-search",
        "enhanced-search-memory",
        "recall",
        "reflection",
        "schema",
        "llm-providers",
        "data-export",
        "maintenance",
        "tasks",
        "workspace-core",
        "workspace-core-runtime",
        "task-session",
        "cron",
        "ai-tools",
        "billing",
        "background-tasks",
        "notifications",
        "events",
        "tunnel",
        "support",
        "support-2",
        "trust-workspace",
        "smtp-config",
        "webhooks",
        "tenant-webhooks",
        "system",
        "plugin-marketplace",
        "platform-plugins",
        "admin-dlq",
        "invitations",
        "invitations-public",
        "skills",
        "tenant-skill-configs",
        "subagents",
        "mcp",
        "sandbox",
        "terminal",
        "artifacts",
        "attachments-upload",
        "channels",
        "instances",
        "instance-files",
        "instance-channels",
        "deploy",
        "clusters",
        "genes",
        "instance-templates",
        "audit",
        "trust",
        "project-sandbox",
        "engines",
        "security-ws",
        "websocket",
        "acp",
        "observability",
        "voice-websocket",
        "create-pool",
        "create-project-pool",
        "project-sandbox-preview",
    )
    assert {definition.owner_entry_id for definition in route_graph.table.definitions} >= {
        "builtin-admin-dlq-http-routes",
        "builtin-acp-http-routes",
        "builtin-agent-http-routes",
        "builtin-billing-http-routes",
        "builtin-clusters-http-routes",
        "builtin-genes-http-routes",
        "builtin-channels-http-routes",
        "builtin-background-tasks-http-routes",
        "builtin-ai-tools-http-routes",
        "builtin-artifacts-http-routes",
        "builtin-attachments-upload-http-routes",
        "builtin-audit-http-routes",
        "builtin-auth-http-routes",
        "builtin-data-export-http-routes",
        "builtin-deploy-http-routes",
        "builtin-cron-http-routes",
        "builtin-enhanced-search-http-routes",
        "builtin-episodes-http-routes",
        "builtin-events-http-routes",
        "builtin-engines-http-routes",
        "builtin-invitations-http-routes",
        "builtin-invitations-public-http-routes",
        "builtin-agent-pool-http-routes",
        "builtin-instances-http-routes",
        "builtin-llm-providers-http-routes",
        "builtin-maintenance-http-routes",
        "builtin-instance-files-http-routes",
        "builtin-instance-templates-http-routes",
        "builtin-instance-channels-http-routes",
        "builtin-graph-http-routes",
        "builtin-graph-stores-http-routes",
        "builtin-memories-http-routes",
        "builtin-mcp-http-routes",
        "builtin-sandbox-http-routes",
        "builtin-security-ws-http-routes",
        "builtin-shares-http-routes",
        "builtin-notifications-http-routes",
        "builtin-observability-http-routes",
        "builtin-platform-plugins-http-routes",
        "builtin-plugin-marketplace-http-routes",
        "builtin-project-sandbox-http-routes",
        "builtin-support-http-routes",
        "builtin-subagents-http-routes",
        "builtin-project-my-work-http-routes",
        "builtin-projects-http-routes",
        "builtin-recall-http-routes",
        "builtin-reflection-http-routes",
        "builtin-schema-http-routes",
        "builtin-skills-http-routes",
        "builtin-retrieval-stores-http-routes",
        "builtin-smtp-config-http-routes",
        "builtin-system-http-routes",
        "builtin-task-session-http-routes",
        "builtin-tasks-http-routes",
        "builtin-tenant-skill-configs-http-routes",
        "builtin-tenants-http-routes",
        "builtin-tenant-webhooks-http-routes",
        "builtin-terminal-http-routes",
        "builtin-trust-http-routes",
        "builtin-trust-workspace-http-routes",
        "builtin-tunnel-http-routes",
        "builtin-voice-websocket-http-routes",
        "builtin-websocket-http-routes",
        "builtin-webhooks-http-routes",
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

    async def shutdown_local_consumer() -> None:
        assert host.manager.current is not None

    shutdown_consumer = AsyncMock(side_effect=shutdown_local_consumer)
    monkeypatch.setattr(
        local_resume_consumer_mod,
        "shutdown_local_consumer",
        shutdown_consumer,
    )
    await shutdown_plugin_runtime_v2(app)
    shutdown_consumer.assert_awaited_once_with()
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


@pytest.mark.unit
async def test_restart_reuses_durable_last_good_distribution(
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
        session_factory=session_factory,
    )

    restarted_distribution = restarted.current_distribution
    assert restarted_distribution is not None
    assert restarted_distribution.to_payload() == first_distribution.to_payload()
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
