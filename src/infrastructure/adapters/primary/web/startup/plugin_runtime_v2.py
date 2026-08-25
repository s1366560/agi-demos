"""Protocol v2 plugin runtime startup and shutdown."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from starlette.types import Scope

from src.domain.model.plugins.generated_v2 import (
    ControlPlaneEnvelopeV2,
    ProfileSnapshotV2,
    ScopeKindV2,
    ScopeV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_v2 import (
    PlatformPluginPublicationPolicyV2,
)
from src.infrastructure.plugins.v2.agent_pool_profile import (
    agent_pool_profile_matches_v2,
    compose_agent_pool_profile_upgrade_v2,
    project_agent_pool_runtime_v2,
)
from src.infrastructure.plugins.v2.agent_pool_runtime import (
    AgentPoolRuntimeFactoryV2,
    default_agent_pool_runtime_config_v2,
)
from src.infrastructure.plugins.v2.boundary import (
    clear_process_generation_host_v2,
    install_process_generation_host_v2,
)
from src.infrastructure.plugins.v2.builtin_http_routes import (
    REQUIRED_V2_BUILTIN_ROUTE_ROW_IDS,
    build_builtin_route_graph_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.channel_runtime import ChannelRuntimeManagerV2
from src.infrastructure.plugins.v2.composer import ProfileDocumentV2
from src.infrastructure.plugins.v2.graph_runtime import GraphRuntimeFactoryV2
from src.infrastructure.plugins.v2.http_routes import RouteTableBuilderV2, RouteTableRegistryV2
from src.infrastructure.plugins.v2.protocol import (
    control_envelope_v2,
    parse_control_envelope_v2,
    parse_profile_snapshot_v2,
)
from src.infrastructure.plugins.v2.reconciler import (
    GenerationPublicationStagerV2,
    PreparedGenerationPublicationV2,
)
from src.infrastructure.plugins.v2.retrieval_runtime import RetrievalRuntimeFactoryV2
from src.infrastructure.plugins.v2.route_effects import ROUTE_TABLE_BUILDER_SERVICE_V2
from src.infrastructure.plugins.v2.runtime import RuntimeGenerationV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import (
    PlatformPluginPublicationV2,
    PlatformPluginRuntimeHostV2,
)
from src.infrastructure.plugins.v2.sandbox_runtime import SandboxRuntimeFactoryV2
from src.infrastructure.plugins.v2.target_profiles import (
    PRODUCTION_TARGET_MANIFEST_V2_PATHS,
    compose_production_target_upgrade_v2,
    include_production_target_hosts_v2,
    production_target_hosts_active_v2,
)
from src.infrastructure.plugins.v2.telemetry_runtime import TelemetryRuntimeManagerV2
from src.infrastructure.plugins.v2.workspace_core_runtime import WorkspaceCoreRuntimeFactoryV2
from src.infrastructure.plugins.v2.workspace_core_shadow import (
    activate_workspace_core_shadow_v2,
    compose_workspace_core_shadow_upgrade_v2,
    workspace_core_shadow_active_v2,
)

from .http_route_publication_v2 import HttpRoutePublicationCoordinatorV2

logger = logging.getLogger(__name__)
_ROOT = Path(__file__).resolve().parents[6]
DEFAULT_PROFILE_V2_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
DEFAULT_MANIFEST_V2_PATHS = (
    *PRODUCTION_TARGET_MANIFEST_V2_PATHS,
    _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",
)
DEFAULT_PUBLICATION_POLICY_V2 = PlatformPluginPublicationPolicyV2.local_default()


async def initialize_plugin_runtime_v2(  # noqa: PLR0913
    app: FastAPI,
    *,
    session_factory: Callable[[], Any] | None = None,
    agent_pool_runtime_enabled: bool = False,
    agent_pool_runtime_config: Mapping[str, object] | None = None,
    agent_pool_runtime_factory: AgentPoolRuntimeFactoryV2 | None = None,
    graph_runtime_factory: GraphRuntimeFactoryV2 | None = None,
    retrieval_runtime_factory: RetrievalRuntimeFactoryV2 | None = None,
    sandbox_runtime_factory: SandboxRuntimeFactoryV2 | None = None,
    sandbox_redis_client: object | None = None,
    telemetry_runtime_manager: TelemetryRuntimeManagerV2 | None = None,
    channel_runtime_manager: ChannelRuntimeManagerV2 | None = None,
    workspace_core_runtime_factory: WorkspaceCoreRuntimeFactoryV2 | None = None,
    publication_policy: PlatformPluginPublicationPolicyV2 = DEFAULT_PUBLICATION_POLICY_V2,
) -> PlatformPluginRuntimeHostV2:
    """Compose and publish the required initial v2 generation."""
    resolved_agent_pool_config = (
        default_agent_pool_runtime_config_v2()
        if agent_pool_runtime_config is None
        else dict(agent_pool_runtime_config)
    )
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(
            agent_pool_runtime_factory=agent_pool_runtime_factory,
            graph_runtime_factory=graph_runtime_factory,
            retrieval_runtime_factory=retrieval_runtime_factory,
            sandbox_runtime_factory=sandbox_runtime_factory,
            sandbox_redis_client=sandbox_redis_client,
            telemetry_runtime_manager=telemetry_runtime_manager,
            channel_runtime_manager=channel_runtime_manager,
            workspace_core_runtime_factory=workspace_core_runtime_factory,
        )
    )
    route_registry = RouteTableRegistryV2()
    route_graph = None
    route_publication = None
    try:
        workspace_core_settings = getattr(app.state, "workspace_core_settings", None)
        if workspace_core_settings is None:
            from src.configuration.workspace_core import get_workspace_core_settings

            workspace_core_settings = get_workspace_core_settings()

        async def stage_routes(
            generation: RuntimeGenerationV2,
        ) -> PreparedGenerationPublicationV2:
            nonlocal route_graph, route_publication
            route_builder = generation.resolve(
                ROUTE_TABLE_BUILDER_SERVICE_V2,
                ScopeV2(kind=ScopeKindV2.ROOT),
            )
            if not isinstance(route_builder, RouteTableBuilderV2):
                raise TypeError("plugin runtime v2 staged an invalid route table builder")
            contributed_routes = route_builder.freeze().definitions
            graph = build_builtin_route_graph_v2(
                workspace_core_settings=workspace_core_settings,
                route_definitions=contributed_routes,
                required_v2_row_ids=REQUIRED_V2_BUILTIN_ROUTE_ROW_IDS,
                dependency_overrides=app.dependency_overrides,
            )
            staged = route_registry.stage(generation.descriptor, graph.table)
            route_graph = graph
            route_publication = staged
            return PreparedGenerationPublicationV2(
                commit=lambda: route_registry.activate(staged),
                rollback=lambda: route_registry.discard(staged),
            )

        durable_distribution = await _last_good_distribution_v2(session_factory)
        latest_distribution = await _latest_requested_distribution_v2(session_factory)
        publication, record_startup_publication = await _publish_startup_generation_v2(
            host,
            durable_distribution=durable_distribution,
            latest_distribution=latest_distribution,
            agent_pool_runtime_enabled=agent_pool_runtime_enabled,
            agent_pool_runtime_config=resolved_agent_pool_config,
            activate_workspace_core_shadow=workspace_core_runtime_factory is not None,
            publication_stager=stage_routes,
        )
        if not publication.accepted:
            await _record_startup_publication_v2(
                session_factory,
                publication,
                publication_policy=publication_policy,
                retain_requested_as_last_good=durable_distribution is not None,
            )
            failure = publication.receipt
            raise RuntimeV2Error(
                failure.error_code or "plugin_runtime_bootstrap_failed",
                failure.error_message or "plugin runtime v2 bootstrap failed",
            )
        distribution = host.current_distribution
        if distribution is None:
            raise RuntimeError("plugin runtime v2 published without a current distribution")
        generation = host.manager.current
        if generation is None:
            raise RuntimeError("plugin runtime v2 published without a current generation")
        if route_graph is None or route_publication is None:
            raise RuntimeError("plugin runtime v2 published without a staged route graph")
        if record_startup_publication:
            await _record_startup_publication_v2(
                session_factory,
                publication,
                publication_policy=publication_policy,
            )
    except Exception:
        await host.close()
        raise

    app.state.platform_plugin_runtime_v2 = host
    app.state.platform_plugin_route_registry_v2 = route_registry
    app.state.platform_plugin_route_graph_v2 = route_graph
    app.state.platform_plugin_http_route_publication_v2 = HttpRoutePublicationCoordinatorV2(
        host=host,
        registry=route_registry,
        workspace_core_settings=workspace_core_settings,
        dependency_overrides=app.dependency_overrides,
    )
    app.state.platform_plugin_publication_policy_v2 = publication_policy
    install_process_generation_host_v2(host)
    logger.info(
        "Published plugin runtime v2 generation=%d digest=%s",
        publication.snapshot.generation,
        publication.snapshot.digest,
    )
    logger.info(
        "Published shadow HTTP route generation=%d rows=%d routes=%d",
        route_publication.descriptor.generation,
        len(route_graph.mounted_row_ids),
        len(route_graph.route_signatures),
    )
    return host


async def _publish_startup_generation_v2(
    host: PlatformPluginRuntimeHostV2,
    *,
    durable_distribution: Mapping[str, object] | None,
    latest_distribution: Mapping[str, object] | None,
    agent_pool_runtime_enabled: bool,
    agent_pool_runtime_config: dict[str, object],
    activate_workspace_core_shadow: bool,
    publication_stager: GenerationPublicationStagerV2,
) -> tuple[PlatformPluginPublicationV2, bool]:
    if durable_distribution is None:
        publication = await host.bootstrap(
            profile_path=DEFAULT_PROFILE_V2_PATH,
            manifest_paths=DEFAULT_MANIFEST_V2_PATHS,
            generation=1,
            version=1,
            profile_projector=lambda document: _project_startup_profile_v2(
                document,
                agent_pool_runtime_enabled=agent_pool_runtime_enabled,
                agent_pool_runtime_config=agent_pool_runtime_config,
                activate_workspace_core_shadow=activate_workspace_core_shadow,
            ),
            publication_stager=publication_stager,
        )
        return publication, True

    durable_snapshot = parse_profile_snapshot_v2(durable_distribution.get("snapshot"))
    durable_envelope = parse_control_envelope_v2(durable_distribution.get("envelope"))
    agent_pool_upgrade_required = not agent_pool_profile_matches_v2(
        durable_snapshot,
        enabled=agent_pool_runtime_enabled,
        config=agent_pool_runtime_config,
    )
    target_upgrade_required = not production_target_hosts_active_v2(durable_snapshot)
    workspace_core_upgrade_required = (
        activate_workspace_core_shadow and not workspace_core_shadow_active_v2(durable_snapshot)
    )

    if agent_pool_upgrade_required:
        generation, version = _next_startup_publication_v2(
            durable_snapshot,
            durable_envelope,
            latest_distribution,
        )
        snapshot = durable_snapshot
        if target_upgrade_required:
            snapshot = compose_production_target_upgrade_v2(
                snapshot,
                generation=generation,
            )
        if workspace_core_upgrade_required:
            snapshot = compose_workspace_core_shadow_upgrade_v2(
                snapshot,
                generation=generation,
            )
        snapshot = compose_agent_pool_profile_upgrade_v2(
            snapshot,
            generation=generation,
            enabled=agent_pool_runtime_enabled,
            config=agent_pool_runtime_config,
        )
        upgraded = await host.apply(
            snapshot,
            control_envelope_v2(snapshot, version=version),
            publication_stager=publication_stager,
        )
        return upgraded, True

    publication = await host.apply_distribution(
        durable_distribution,
        publication_stager=publication_stager,
    )
    if not publication.accepted:
        return publication, False

    target_upgrade_required = not production_target_hosts_active_v2(publication.snapshot)
    workspace_core_upgrade_required = (
        activate_workspace_core_shadow and not workspace_core_shadow_active_v2(publication.snapshot)
    )
    if not target_upgrade_required and not workspace_core_upgrade_required:
        return publication, False

    generation, version = _next_startup_publication_v2(
        publication.snapshot,
        publication.envelope,
        latest_distribution,
    )
    snapshot = publication.snapshot
    if target_upgrade_required:
        snapshot = compose_production_target_upgrade_v2(
            snapshot,
            generation=generation,
        )
    if workspace_core_upgrade_required:
        snapshot = compose_workspace_core_shadow_upgrade_v2(
            snapshot,
            generation=generation,
        )
    upgraded = await host.apply(
        snapshot,
        control_envelope_v2(snapshot, version=version),
        publication_stager=publication_stager,
    )
    return upgraded, True


def _project_startup_profile_v2(
    document: ProfileDocumentV2,
    *,
    agent_pool_runtime_enabled: bool,
    agent_pool_runtime_config: dict[str, object],
    activate_workspace_core_shadow: bool,
) -> ProfileDocumentV2:
    projected = project_agent_pool_runtime_v2(
        document,
        enabled=agent_pool_runtime_enabled,
        config=agent_pool_runtime_config,
    )
    projected = include_production_target_hosts_v2(projected)
    if activate_workspace_core_shadow:
        projected = activate_workspace_core_shadow_v2(projected)
    return projected


async def _last_good_distribution_v2(
    session_factory: Callable[[], Any] | None,
) -> Mapping[str, object] | None:
    if session_factory is None:
        return None
    from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
        PYTHON_API_DATA_PLANE_ID_V2,
        PlatformPluginRepositoryV2,
    )

    async with session_factory() as session:
        return await PlatformPluginRepositoryV2(session).last_good_distribution(
            PYTHON_API_DATA_PLANE_ID_V2
        )


async def _latest_requested_distribution_v2(
    session_factory: Callable[[], Any] | None,
) -> Mapping[str, object] | None:
    if session_factory is None:
        return None
    from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
        PlatformPluginRepositoryV2,
    )

    async with session_factory() as session:
        return await PlatformPluginRepositoryV2(session).latest_requested_distribution()


def _next_startup_publication_v2(
    last_good_snapshot: ProfileSnapshotV2,
    last_good_envelope: ControlPlaneEnvelopeV2,
    latest_distribution: Mapping[str, object] | None,
) -> tuple[int, int]:
    generation = last_good_snapshot.generation
    version = last_good_envelope.version
    if latest_distribution is not None:
        snapshot = parse_profile_snapshot_v2(latest_distribution.get("snapshot"))
        envelope = parse_control_envelope_v2(latest_distribution.get("envelope"))
        generation = max(generation, snapshot.generation)
        version = max(version, envelope.version)
    return generation + 1, version + 1


async def _record_startup_publication_v2(
    session_factory: Callable[[], Any] | None,
    publication: PlatformPluginPublicationV2,
    *,
    publication_policy: PlatformPluginPublicationPolicyV2,
    retain_requested_as_last_good: bool = False,
) -> None:
    if session_factory is None:
        return
    from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
        PYTHON_API_DATA_PLANE_ID_V2,
        PlatformPluginRepositoryV2,
    )

    if (
        retain_requested_as_last_good
        and not publication.accepted
        and publication.receipt.applied_version is None
    ):
        publication = replace(
            publication,
            receipt=replace(
                publication.receipt,
                applied_version=publication.envelope.version,
                applied_digest=publication.snapshot.digest,
            ),
        )
    async with session_factory() as session:
        repository = PlatformPluginRepositoryV2(session)
        if PYTHON_API_DATA_PLANE_ID_V2 in publication_policy.required_data_plane_ids:
            _ = await repository.record_publication_and_receipt(
                publication,
                data_plane_id=PYTHON_API_DATA_PLANE_ID_V2,
                policy=publication_policy,
            )
        else:
            _ = await repository.record_publication(
                publication,
                policy=publication_policy,
            )
        await session.commit()


async def shutdown_plugin_runtime_v2(app: FastAPI) -> None:
    """Retire the current v2 generation and wait for Fiber disposal."""
    host = getattr(app.state, "platform_plugin_runtime_v2", None)
    if not isinstance(host, PlatformPluginRuntimeHostV2):
        return
    clear_process_generation_host_v2(host)
    await host.close()
    app.state.platform_plugin_runtime_v2 = None
    app.state.platform_plugin_route_registry_v2 = None
    app.state.platform_plugin_route_graph_v2 = None
    app.state.platform_plugin_http_route_publication_v2 = None
    app.state.platform_plugin_publication_policy_v2 = None


def plugin_publication_policy_v2_from_app(app: object) -> PlatformPluginPublicationPolicyV2:
    """Resolve the deployment policy installed with the production generation host."""
    policy = getattr(getattr(app, "state", None), "platform_plugin_publication_policy_v2", None)
    if policy is None:
        return PlatformPluginPublicationPolicyV2.local_default()
    if not isinstance(policy, PlatformPluginPublicationPolicyV2):
        raise TypeError("plugin v2 publication policy has an invalid type")
    return policy


def plugin_runtime_host_v2_from_scope(scope: Scope) -> PlatformPluginRuntimeHostV2:
    """Resolve the initialized host for the request generation middleware."""
    app = scope.get("app")
    host = getattr(getattr(app, "state", None), "platform_plugin_runtime_v2", None)
    if not isinstance(host, PlatformPluginRuntimeHostV2):
        raise RuntimeError("plugin runtime v2 is not initialized")
    return host
