"""Re-attest an exact persisted publication inside each consuming worker process."""

from collections.abc import Awaitable, Callable, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.model.plugins.generated_v2 import (
    BundleReferenceV2,
    DataPlaneTargetV2,
    ScopeKindV2,
    ScopeV2,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2PublicationModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_source_repository_v2 import (
    PlatformPluginPublicationSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_recovery_repository_v2 import (
    PlatformPluginRecoveryV2Error,
    _distribution,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_scope_ledger_v2 import (
    ScopeLedgerBindingV2,
)
from src.infrastructure.plugins.v2.bundle_archive import VerifiedBundleArchiveV2
from src.infrastructure.plugins.v2.protocol import (
    parse_control_envelope_v2,
    parse_profile_snapshot_v2,
)
from src.infrastructure.plugins.v2.runtime_context import RuntimeV2Error, scope_contains_v2
from src.infrastructure.plugins.v2.runtime_contracts import generated_target_catalog_v2


class PublicationArchiveLoaderV2:
    """Load exact lineage, never infer trusted bundle references from snapshot modules."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        bundle_loader: Callable[[BundleReferenceV2], Awaitable[VerifiedBundleArchiveV2]],
    ) -> None:
        self._sessions = session_factory
        self._load_bundle = bundle_loader

    async def __call__(
        self, payload: Mapping[str, object], scope: ScopeV2
    ) -> Sequence[VerifiedBundleArchiveV2] | None:
        if not distribution_needs_external_archives_v2(payload):
            return None
        envelope = parse_control_envelope_v2(payload["envelope"])
        async with self._sessions() as session:
            row = await session.scalar(
                select(PlatformPluginV2PublicationModel).where(
                    PlatformPluginV2PublicationModel.nonce == envelope.nonce
                )
            )
            if row is None:
                raise RuntimeV2Error(
                    "publication_archive_source_missing", "requested publication is not retained"
                )
            owner = ScopeV2(
                kind=ScopeKindV2(row.scope_kind),
                tenant_id=row.tenant_id,
                project_id=row.project_id,
                session_id=row.session_id,
            )
            if not scope_contains_v2(owner, scope):
                raise RuntimeV2Error(
                    "publication_archive_scope_mismatch",
                    "requested publication belongs to another scope",
                )
            distribution = _distribution(
                row, ScopeLedgerBindingV2(owner, PlatformPluginRecoveryV2Error)
            )
            if distribution.to_payload() != dict(payload):
                raise RuntimeV2Error(
                    "publication_archive_distribution_mismatch",
                    "requested distribution differs from retained publication",
                )
            desired = await PlatformPluginPublicationSourceRepositoryV2(session).read(
                scope=owner, publication_id=row.id
            )
            if desired is None:
                raise RuntimeV2Error(
                    "publication_archive_source_missing",
                    "requested publication has no retained bundle references",
                )
            references = desired.bundles
        archives = []
        for reference in references:
            archive = await self._load_bundle(reference)
            if (
                archive.manifest.bundle_id,
                archive.manifest.version,
                archive.manifest.digest,
                archive.source,
            ) != (reference.bundle_id, reference.version, reference.digest, reference.source):
                raise RuntimeV2Error(
                    "publication_archive_reference_mismatch",
                    "verified archive differs from retained reference",
                )
            archives.append(archive)
        return tuple(archives)


def distribution_needs_external_archives_v2(payload: Mapping[str, object]) -> bool:
    snapshot = parse_profile_snapshot_v2(payload.get("snapshot"))
    catalog = generated_target_catalog_v2(DataPlaneTargetV2.PYTHON)
    return any(
        DataPlaneTargetV2.PYTHON in module.targets and module.module_ref not in catalog
        for manifest in snapshot.manifests
        for module in manifest.modules
    )


async def load_agent_generation_archives_v2(
    payload: Mapping[str, object], scope: ScopeV2
) -> Sequence[VerifiedBundleArchiveV2] | None:
    """Production callback: process-local settings, repository and authenticated OCI verification."""
    if not distribution_needs_external_archives_v2(payload):
        return None
    from src.configuration.config import get_settings
    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
    from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2

    from .scoped_installed_bundle_loader_v2 import ScopedInstalledBundleLoaderV2

    settings = get_settings()
    # Only operator-configured public PEM files are read; each archive verifies the signer anew.
    keys = tuple(
        path.read_text(encoding="utf-8") for path in settings.plugin_marketplace_trusted_key_files
    )
    loader = ScopedInstalledBundleLoaderV2(
        session_factory=async_session_factory,
        production_sources=production_bundle_sources_v2(),
        trusted_public_keys=keys,
        allowed_registries=frozenset(settings.plugin_marketplace_allowed_registries),
    )
    return await PublicationArchiveLoaderV2(
        session_factory=async_session_factory, bundle_loader=loader
    )(payload, scope)
