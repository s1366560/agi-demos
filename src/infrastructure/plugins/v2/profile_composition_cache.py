"""Bounded, runtime-owned memoization of pure profile compilation.

Callers must reload and authorize every bundle before consulting this cache. It
does not cache installed status, grants, accepted revisions or caller authority.
"""

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass

from src.domain.model.plugins.generated_v2 import (
    BundleManifestV2,
    DesiredBundleSetV2,
    ProfileSnapshotV2,
    ProfileSourceV2,
    ScopeV2,
)
from src.infrastructure.plugins.v2.composer import compose_profile_v2
from src.infrastructure.plugins.v2.layer_composer import compose_profile_sources_v2


@dataclass(frozen=True)
class _Compilation:
    desired: DesiredBundleSetV2
    source: ProfileSourceV2
    bundles: tuple[BundleManifestV2, ...]
    snapshot: ProfileSnapshotV2


class ProfileCompositionCacheV2:
    """Reuse exact validated values without sharing their mutable config mappings."""

    def __init__(self, *, capacity: int = 64) -> None:
        if capacity < 1:
            raise ValueError("profile compilation cache capacity must be positive")
        self._capacity = capacity
        self._entries: OrderedDict[tuple[ScopeV2, str, str, tuple[str, ...]], _Compilation] = (
            OrderedDict()
        )

    def compose(
        self,
        *,
        desired: DesiredBundleSetV2,
        source: ProfileSourceV2,
        bundles: tuple[BundleManifestV2, ...],
        scope: ScopeV2,
    ) -> ProfileSnapshotV2:
        key = (scope, desired.digest, source.digest, tuple(bundle.digest for bundle in bundles))
        previous = self._entries.get(key)
        # Compare complete values as well as references: altered input retaining
        # an old digest must go through normal validation and fail closed.
        if (
            previous is not None
            and previous.desired == desired
            and previous.source == source
            and previous.bundles == bundles
        ):
            self._entries.move_to_end(key)
            return deepcopy(previous.snapshot)
        composed = compose_profile_sources_v2(
            desired_set=desired, bundles=bundles, profile_source=source, scope=scope
        )
        snapshot = compose_profile_v2(
            composed.document,
            {manifest.plugin_id: manifest for manifest in composed.manifests},
            generation=desired.revision,
        )
        self._entries[key] = deepcopy(_Compilation(desired, source, bundles, snapshot))
        self._entries.move_to_end(key)
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)
        return snapshot

    def clear(self) -> None:
        self._entries.clear()
