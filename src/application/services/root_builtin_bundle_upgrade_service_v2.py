"""Explicit maintenance upgrade of an exact scoped builtin Bundle reference."""

from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import BundleReferenceV2, ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRecordV2,
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.plugins.v2.bundle_archive import VerifiedBundleArchiveV2
from src.infrastructure.plugins.v2.composer import compose_profile_v2
from src.infrastructure.plugins.v2.layer_composer import (
    compose_profile_sources_v2,
    desired_bundle_set_digest_v2,
)
from src.infrastructure.plugins.v2.production_bundle import ProductionBundleSourcesV2
from src.infrastructure.plugins.v2.scope import validate_scope_v2


async def upgrade_root_builtin_bundle_v2(
    session: AsyncSession,
    *,
    sources: ProductionBundleSourcesV2,
    load_verified_bundle: Callable[[BundleReferenceV2], Awaitable[VerifiedBundleArchiveV2]],
    expected_revision: int,
    expected_bundle: BundleReferenceV2,
    actor_id: str,
    scope: ScopeV2 | None = None,
) -> PlatformPluginDesiredBundleSetRecordV2:
    """Validate then append a CAS revision; the authorized caller owns the transaction.

    This maintenance operation does not activate the runtime. Normal startup must
    still verify and publish the new desired revision. No startup auto-rebinding.
    """
    canonical = validate_scope_v2(scope or ScopeV2(kind=ScopeKindV2.ROOT))
    repository = PlatformPluginDesiredBundleSetRepositoryV2(session)
    head = await repository.current_desired_set(canonical)
    if head is None or head.desired_set.revision != expected_revision:
        raise ValueError("scope desired revision differs from the expected maintenance revision")
    current = head.desired_set
    replacement = sources.desired_set.bundles[0]
    if (expected_bundle.bundle_id, expected_bundle.source) != (
        replacement.bundle_id,
        replacement.source,
    ):
        raise ValueError("maintenance can only upgrade the builtin baseline bundle")
    if expected_bundle not in current.bundles:
        raise ValueError("scope builtin bundle differs from the expected exact reference")
    if expected_bundle == replacement:
        raise ValueError("scope builtin bundle already matches the current production source")
    reference = current.profile_source
    source = await PlatformPluginProfileSourceRepositoryV2(session).read_exact(
        scope=canonical,
        source_id=reference.source_id,
        revision=reference.revision,
        digest=reference.digest,
    )
    if source is None:
        raise ValueError("the existing exact scoped ProfileSource is unavailable")
    desired = replace(
        current,
        revision=current.revision + 1,
        bundles=tuple(replacement if item == expected_bundle else item for item in current.bundles),
    )
    desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))
    archives = [await load_verified_bundle(item) for item in desired.bundles]
    for item, archive in zip(desired.bundles, archives, strict=True):
        if not isinstance(cast(object, archive), VerifiedBundleArchiveV2) or (
            archive.manifest.bundle_id,
            archive.manifest.version,
            archive.manifest.digest,
        ) != (item.bundle_id, item.version, item.digest):
            raise ValueError(
                "maintenance requires verified archives matching every exact reference"
            )
    composition = compose_profile_sources_v2(
        desired_set=desired,
        bundles=tuple(archive.manifest for archive in archives),
        profile_source=source,
        scope=canonical,
    )
    _ = compose_profile_v2(
        composition.document,
        {manifest.plugin_id: manifest for manifest in composition.manifests},
        generation=desired.revision,
    )
    return await repository.record_desired_set(
        scope=canonical,
        desired_set=desired,
        expected_revision=expected_revision,
        actor_id=actor_id,
    )
