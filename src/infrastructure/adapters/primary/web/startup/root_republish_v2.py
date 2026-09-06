"""Commit explicit ROOT rollback intent before verified local reconciliation."""

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.application.services.marketplace_requested_recovery_v2 import (
    recover_live_requested_root_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2PublicationModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_v2 import (
    PYTHON_API_DATA_PLANE_ID_V2,
    PlatformPluginPublicationPolicyV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginLedgerV2Error,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_rollback_repository_v2 import (
    PlatformPluginRollbackRepositoryV2,
)
from src.infrastructure.plugins.v2.builtin_http_routes import BuiltinRouteGraphV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

from .http_route_publication_v2 import HttpRoutePublicationCoordinatorV2


async def republish_ready_root_v2(
    app: FastAPI,
    session: AsyncSession,
    *,
    actor_id: str,
    policy: PlatformPluginPublicationPolicyV2,
) -> PlatformPluginV2PublicationModel:
    """Restore desired authority and publish a fresh generation of last-ready content.

    The request and desired/source revision commit together. Local reconciliation uses
    independent receipt transactions; an interrupted commit remains recoverable by
    the normal ROOT background/startup path without inventing a receipt.
    """
    publication = await PlatformPluginRollbackRepositoryV2(session).republish_last_ready(
        policy=policy, actor_id=actor_id
    )
    if PYTHON_API_DATA_PLANE_ID_V2 not in policy.required_data_plane_ids:
        await session.commit()
        return publication

    host = getattr(app.state, "platform_plugin_runtime_v2", None)
    coordinator = getattr(app.state, "platform_plugin_http_route_publication_v2", None)
    if (
        not isinstance(host, PlatformPluginRuntimeHostV2)
        or not isinstance(coordinator, HttpRoutePublicationCoordinatorV2)
        or not isinstance(session.bind, AsyncEngine)
    ):
        raise PlatformPluginLedgerV2Error(
            "root_runtime_unavailable", "ROOT rollback requires its runtime and route coordinator"
        )
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    nonce = publication.nonce
    await session.commit()

    def commit_graph(graph: BuiltinRouteGraphV2) -> None:
        app.state.platform_plugin_route_graph_v2 = graph

    _ = await recover_live_requested_root_v2(
        coordinator=coordinator,
        session_factory=factory,
        policy=policy,
        trusted_public_keys=getattr(app.state, "plugin_marketplace_trusted_public_keys_v2", ()),
        allowed_registries=getattr(
            app.state, "plugin_marketplace_allowed_registries_v2", frozenset()
        ),
        on_route_commit=commit_graph,
        superseded_publication=host.pending_receipt,
        expected_nonce=nonce,
    )
    return publication
