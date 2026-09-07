"""Commit the exact ROOT candidate and source before startup performs any apply."""

from collections.abc import Callable, Sequence
from typing import Any

from src.domain.model.plugins.generated_v2 import (
    ControlPlaneEnvelopeV2,
    DesiredBundleSetV2,
    ProfileSnapshotV2,
    ScopeKindV2,
    ScopeV2,
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
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.bundle_archive import VerifiedBundleArchiveV2
from src.infrastructure.plugins.v2.composer import ProfileDocumentV2, compose_profile_v2
from src.infrastructure.plugins.v2.protocol import control_envelope_v2, parse_profile_snapshot_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error


async def prepare_root_startup_request_v2(
    *,
    session_factory: Callable[[], Any],
    candidate: ProfileSnapshotV2,
    desired: DesiredBundleSetV2,
    archives: Sequence[VerifiedBundleArchiveV2],
    policy: PlatformPluginPublicationPolicyV2,
) -> tuple[ProfileSnapshotV2, ControlPlaneEnvelopeV2]:
    scope = ScopeV2(kind=ScopeKindV2.ROOT)
    references = {(ref.bundle_id, ref.version, ref.digest) for ref in desired.bundles}
    verified = {
        (item.manifest.bundle_id, item.manifest.version, item.manifest.digest) for item in archives
    }
    if references != verified:
        raise RuntimeV2Error("root_bundle_reference_mismatch", "ROOT archives differ from desired")
    async with session_factory() as session:
        repository = PlatformPluginRepositoryV2(session)
        version = await repository.allocate_publication_version()
        current = await PlatformPluginDesiredBundleSetRepositoryV2(session).current_desired_set(
            scope
        )
        if current is None or current.desired_set != desired:
            raise RuntimeV2Error("root_desired_changed", "ROOT source changed before publication")
        latest = await repository.latest_requested_distribution()
        if latest is not None:
            previous = parse_profile_snapshot_v2(latest.get("snapshot"))
            if previous.generation >= candidate.generation:
                candidate = compose_profile_v2(
                    ProfileDocumentV2(profile_id=candidate.profile_id, entries=candidate.entries),
                    {manifest.plugin_id: manifest for manifest in candidate.manifests},
                    generation=previous.generation + 1,
                )
        envelope = control_envelope_v2(candidate, version=version)
        requested = await repository.record_requested_distribution(
            candidate, envelope, policy=policy
        )
        _ = await PlatformPluginPublicationSourceRepositoryV2(session).record(
            scope=scope, publication_id=requested.id, desired_set=desired
        )
        await session.commit()
    return candidate, envelope
