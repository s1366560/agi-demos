"""Transactional ROOT rollback intent; applying and committing belong to the caller."""

from dataclasses import replace

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
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
    PlatformPluginPublicationPolicyV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_recovery_repository_v2 import (
    _distribution,  # pyright: ignore[reportPrivateUsage]  # Shared stored-distribution integrity check.
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginLedgerV2Error,
    PlatformPluginRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_scope_ledger_v2 import (
    ScopeLedgerBindingV2,
)
from src.infrastructure.plugins.v2.layer_composer import desired_bundle_set_digest_v2
from src.infrastructure.plugins.v2.protocol import build_profile_snapshot_v2, control_envelope_v2


class PlatformPluginRollbackRepositoryV2:
    """Append rollback configuration and its request under the existing ROOT scope lock."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self._session = session

    async def republish_last_ready(
        self, *, policy: PlatformPluginPublicationPolicyV2, actor_id: str
    ) -> PlatformPluginV2PublicationModel:
        root = ScopeV2(kind=ScopeKindV2.ROOT)
        binding = ScopeLedgerBindingV2(root, PlatformPluginLedgerV2Error)
        _ = await binding.lock(self._session)
        if not actor_id.strip():
            raise PlatformPluginLedgerV2Error(
                "rollback_actor_invalid", "rollback actor is required"
            )
        source = await self._session.scalar(
            refresh_select_statement(
                select(PlatformPluginV2PublicationModel)
                .where(
                    PlatformPluginV2PublicationModel.scope_key == binding.key,
                    PlatformPluginV2PublicationModel.ready_at.is_not(None),
                )
                .order_by(
                    PlatformPluginV2PublicationModel.requested_version.desc(),
                    PlatformPluginV2PublicationModel.ready_at.desc(),
                    PlatformPluginV2PublicationModel.id.desc(),
                )
                .limit(1)
                .with_for_update()
            )
        )
        if source is None:
            raise PlatformPluginLedgerV2Error(
                "globally_ready_not_found", "no globally-ready ROOT publication is available"
            )
        try:
            distribution = _distribution(source, binding)
            sources = PlatformPluginPublicationSourceRepositoryV2(self._session)
            retained = await sources.read(scope=root, publication_id=source.id)
            desired_repository = PlatformPluginDesiredBundleSetRepositoryV2(self._session)
            current = await desired_repository.current_desired_set(root)
        except ValueError as exc:
            raise PlatformPluginLedgerV2Error(
                "rollback_source_invalid", "ROOT rollback source integrity check failed"
            ) from exc
        if retained is None:
            raise PlatformPluginLedgerV2Error(
                "root_publication_source_missing", "ready ROOT publication has no source binding"
            )
        if current is None:
            raise PlatformPluginLedgerV2Error(
                "root_desired_missing", "ROOT rollback requires existing desired configuration"
            )
        desired = replace(
            retained,
            desired_set_id=current.desired_set.desired_set_id,
            revision=current.desired_set.revision + 1,
        )
        desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))
        _ = await desired_repository.record_desired_set(
            scope=root,
            desired_set=desired,
            expected_revision=current.desired_set.revision,
            actor_id=actor_id,
        )
        highest = await self._session.scalar(
            select(func.max(PlatformPluginV2PublicationModel.generation)).where(
                PlatformPluginV2PublicationModel.scope_key == binding.key
            )
        )
        snapshot = build_profile_snapshot_v2(
            profile_id=distribution.snapshot.profile_id,
            generation=(highest or 0) + 1,
            manifests=distribution.snapshot.manifests,
            entries=distribution.snapshot.entries,
        )
        ledger = PlatformPluginRepositoryV2(self._session)
        envelope = control_envelope_v2(
            snapshot, version=await ledger.allocate_publication_version()
        )
        requested = await ledger.record_requested_distribution(snapshot, envelope, policy=policy)
        requested.republished_from_id = source.id
        _ = await sources.record(scope=root, publication_id=requested.id, desired_set=desired)
        await self._session.flush()
        return requested
