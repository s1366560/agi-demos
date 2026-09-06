"""Apply an unreceipted ROOT request through the running route coordinator."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.startup.http_route_publication_v2 import (
    HttpRoutePublicationCoordinatorV2,
)
from src.infrastructure.adapters.primary.web.startup.root_requested_recovery_v2 import (
    load_requested_root_recovery_v2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_v2 import (
    PYTHON_API_DATA_PLANE_ID_V2,
    PlatformPluginPublicationPolicyV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_recovery_repository_v2 import (
    PlatformPluginRecoveryRepositoryV2,
)
from src.infrastructure.plugins.v2.builtin_http_routes import BuiltinRouteGraphV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginPublicationV2

from .marketplace_publication_receipt_v2 import persist_marketplace_receipt_v2


async def recover_live_requested_root_v2(
    *,
    coordinator: HttpRoutePublicationCoordinatorV2,
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    policy: PlatformPluginPublicationPolicyV2,
    trusted_public_keys: tuple[str, ...],
    allowed_registries: frozenset[str],
    on_route_commit: Callable[[BuiltinRouteGraphV2], None] | None,
) -> bool:
    async with session_factory() as session:
        state = await PlatformPluginRecoveryRepositoryV2(session).read(
            ScopeV2(kind=ScopeKindV2.ROOT),
            PYTHON_API_DATA_PLANE_ID_V2,
        )
    if state.latest is None or state.latest_receipt is not None:
        return False
    prepared = await load_requested_root_recovery_v2(
        session_factory=session_factory,
        latest_distribution=state.latest.to_payload(),
        durable_distribution=None if state.last_good is None else state.last_good.to_payload(),
        trusted_public_keys=trusted_public_keys,
        allowed_registries=allowed_registries,
        publication_policy=policy,
    )
    if prepared is None:
        return False

    async def persist(publication: PlatformPluginPublicationV2) -> None:
        await persist_marketplace_receipt_v2(session_factory, publication, policy=policy)

    _ = await coordinator.publish_snapshot(
        prepared.distribution.snapshot,
        prepared.distribution.envelope,
        verified_archives=prepared.archives,
        pre_apply_check=prepared.check_authority,
        receipt_persister=persist,
        receipt_check=prepared.check_receipt_authority,
        on_commit=on_route_commit,
    )
    return True
