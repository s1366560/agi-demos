"""Restore exact bound ROOT history with fences before and after real staging."""

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from src.domain.model.plugins.generated_v2 import DesiredBundleSetV2, ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_v2 import (
    PYTHON_API_DATA_PLANE_ID_V2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_recovery_repository_v2 import (
    PlatformPluginRecoveryRepositoryV2,
    ScopedRecoveryStateV2,
)
from src.infrastructure.plugins.v2.bundle_archive import VerifiedBundleArchiveV2
from src.infrastructure.plugins.v2.reconciler import GenerationPublicationStagerV2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import (
    PlatformPluginPublicationV2,
    PlatformPluginRuntimeHostV2,
)


async def _read(
    session_factory: Callable[[], Any],
) -> tuple[ScopedRecoveryStateV2, DesiredBundleSetV2 | None]:
    scope = ScopeV2(kind=ScopeKindV2.ROOT)
    async with session_factory() as session:
        state = await PlatformPluginRecoveryRepositoryV2(session).read(
            scope, PYTHON_API_DATA_PLANE_ID_V2
        )
        current = await PlatformPluginDesiredBundleSetRepositoryV2(session).current_desired_set(
            scope
        )
        return state, None if current is None else current.desired_set


async def restore_root_startup_v2(
    host: PlatformPluginRuntimeHostV2,
    *,
    session_factory: Callable[[], Any],
    durable_distribution: Mapping[str, object],
    desired: DesiredBundleSetV2,
    archives: Sequence[VerifiedBundleArchiveV2],
    publication_stager: GenerationPublicationStagerV2,
) -> PlatformPluginPublicationV2 | None:
    state, current = await _read(session_factory)
    if state.last_good is None or state.last_good.to_payload() != durable_distribution:
        raise RuntimeV2Error("root_recovery_changed", "ROOT retained publication changed")
    if state.latest_receipt is None:
        raise RuntimeV2Error("root_receipt_pending", "latest ROOT request has no receipt")
    if state.source is None:
        raise RuntimeV2Error(
            "root_profile_migration_required", "retained ROOT publication has no source binding"
        )
    if current != desired:
        raise RuntimeV2Error("root_recovery_changed", "ROOT desired changed before restore")
    if state.source != desired:
        # Equal runtime bytes with a new configuration revision require a new publication binding.
        return None
    references = {(ref.bundle_id, ref.version, ref.digest) for ref in state.source.bundles}
    verified = {
        (item.manifest.bundle_id, item.manifest.version, item.manifest.digest) for item in archives
    }
    if verified != references:
        raise RuntimeV2Error("root_bundle_reference_mismatch", "ROOT restore archives differ")
    publication = await host.apply_distribution(
        durable_distribution, publication_stager=publication_stager, verified_archives=archives
    )
    if not publication.accepted:
        raise RuntimeV2Error(
            publication.receipt.error_code or "root_recovery_rejected",
            publication.receipt.error_message or "ROOT restore was rejected",
        )
    after, current_after = await _read(session_factory)
    if after != state or current_after != desired:
        raise RuntimeV2Error("root_recovery_changed", "ROOT authority changed during restore")
    return publication
