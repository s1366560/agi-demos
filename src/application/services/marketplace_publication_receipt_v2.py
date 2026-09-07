"""Persist the actual ROOT marketplace outcome with a separately owned session."""

from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2PublicationModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_source_repository_v2 import (
    PlatformPluginPublicationSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_v2 import (
    PYTHON_API_DATA_PLANE_ID_V2,
    PlatformPluginPublicationPolicyV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginLedgerV2Error,
    PlatformPluginRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_scope_ledger_v2 import (
    ScopeLedgerBindingV2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginPublicationV2


async def _lock_receipt_source(
    session: AsyncSession,
    publication: PlatformPluginPublicationV2,
    policy: PlatformPluginPublicationPolicyV2,
) -> None:
    """Serialize desired CAS and receipt persistence under the same scope head."""
    root = ScopeV2(kind=ScopeKindV2.ROOT)
    binding = ScopeLedgerBindingV2(root, PlatformPluginLedgerV2Error)
    _ = await binding.lock(session)
    requested = (
        await session.scalars(
            select(PlatformPluginV2PublicationModel).where(
                PlatformPluginV2PublicationModel.scope_key == binding.key,
                PlatformPluginV2PublicationModel.nonce == publication.envelope.nonce,
            )
        )
    ).one_or_none()
    if requested is None:
        raise PlatformPluginLedgerV2Error("publication_not_found", "ROOT request is unavailable")
    binding.require_row(requested)
    if set(requested.required_data_plane_ids) != set(policy.required_data_plane_ids):
        raise RuntimeV2Error("root_recovery_policy_changed", "ROOT request policy changed")
    source = await PlatformPluginPublicationSourceRepositoryV2(session).read(
        scope=root, publication_id=requested.id
    )
    if source is None:
        raise RuntimeV2Error(
            "root_publication_source_missing", "ROOT request has no source binding"
        )
    current = await PlatformPluginDesiredBundleSetRepositoryV2(session).current_desired_set(root)
    if current is None or current.desired_set != source:
        raise RuntimeV2Error("root_recovery_changed", "ROOT desired source changed")


async def persist_marketplace_receipt_v2(
    session_factory: Callable[[], Any],
    publication: PlatformPluginPublicationV2,
    *,
    policy: PlatformPluginPublicationPolicyV2,
) -> None:
    """Write only a receipt for an already committed request, including idempotent retries."""
    async with session_factory() as session:
        await _lock_receipt_source(session, publication, policy)
        repository = PlatformPluginRepositoryV2(session)
        if PYTHON_API_DATA_PLANE_ID_V2 in policy.required_data_plane_ids:
            _ = await repository.record_data_plane_receipt(
                data_plane_id=PYTHON_API_DATA_PLANE_ID_V2,
                nonce=publication.envelope.nonce,
                receipt=publication.receipt,
            )
        else:
            latest = await repository.latest_publication_readiness()
            if latest is None or latest.nonce != publication.envelope.nonce:
                raise RuntimeV2Error("root_publication_changed", "ROOT request was superseded")
        await session.commit()
