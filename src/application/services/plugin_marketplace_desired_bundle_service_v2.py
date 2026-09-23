"""Protocol-v2 marketplace mutations over immutable DesiredBundleSet revisions."""

from __future__ import annotations

from dataclasses import dataclass, replace

from src.domain.model.plugins.generated_v2 import (
    BundleReferenceV2,
    DesiredBundleSetV2,
    ScopeKindV2,
    ScopeV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRecordV2,
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.plugins.v2.layer_composer import desired_bundle_set_digest_v2
from src.infrastructure.plugins.v2.protocol import (
    desired_bundle_set_v2_to_payload,
    parse_desired_bundle_set_v2,
)

_ZERO_DIGEST_V2 = f"sha256:{'0' * 64}"


@dataclass(frozen=True, kw_only=True)
class MarketplaceDesiredBundleMutationV2:
    """One idempotent desired-state mutation and its immutable resulting head."""

    record: PlatformPluginDesiredBundleSetRecordV2
    changed: bool


class PluginMarketplaceDesiredBundleServiceV2:
    """Install and remove exact Bundle references without touching protocol v1 state."""

    def __init__(  # pyright: ignore[reportMissingSuperCall]
        self,
        repository: PlatformPluginDesiredBundleSetRepositoryV2,
        *,
        baseline: DesiredBundleSetV2,
    ) -> None:
        self._repository = repository
        self._baseline = parse_desired_bundle_set_v2(desired_bundle_set_v2_to_payload(baseline))
        self._protected_bundle_ids = frozenset(
            reference.bundle_id for reference in self._baseline.bundles
        )

    async def install(
        self,
        *,
        scope: ScopeV2,
        bundle: BundleReferenceV2,
        actor_id: str | None,
    ) -> MarketplaceDesiredBundleMutationV2:
        """Append or explicitly replace one exact marketplace Bundle reference."""
        self._require_root_scope(scope)
        if bundle.bundle_id in self._protected_bundle_ids:
            raise ValueError("marketplace bundle cannot replace a protected baseline bundle")
        head = await self._head(scope=scope, actor_id=actor_id)
        current = head.desired_set
        positions = {reference.bundle_id: index for index, reference in enumerate(current.bundles)}
        position = positions.get(bundle.bundle_id)
        if position is not None and current.bundles[position] == bundle:
            return MarketplaceDesiredBundleMutationV2(record=head, changed=False)

        bundles = list(current.bundles)
        if position is None:
            bundles.append(bundle)
        else:
            bundles[position] = bundle
        desired = self._next_revision(current, tuple(bundles))
        record = await self._repository.record_desired_set(
            scope=scope,
            desired_set=desired,
            expected_revision=current.revision,
            actor_id=actor_id,
        )
        return MarketplaceDesiredBundleMutationV2(record=record, changed=True)

    async def uninstall(
        self,
        *,
        scope: ScopeV2,
        bundle_id: str,
        version: str | None = None,
        actor_id: str | None,
    ) -> MarketplaceDesiredBundleMutationV2:
        """Remove one exact marketplace Bundle reference while preserving baseline order."""
        self._require_root_scope(scope)
        if bundle_id in self._protected_bundle_ids:
            raise ValueError("protected baseline bundle cannot be uninstalled")
        head = await self._head(scope=scope, actor_id=actor_id)
        current_reference = next(
            (
                reference
                for reference in head.desired_set.bundles
                if reference.bundle_id == bundle_id
            ),
            None,
        )
        if current_reference is None or (
            version is not None and current_reference.version != version
        ):
            return MarketplaceDesiredBundleMutationV2(record=head, changed=False)
        bundles = tuple(
            reference for reference in head.desired_set.bundles if reference.bundle_id != bundle_id
        )

        desired = self._next_revision(head.desired_set, bundles)
        record = await self._repository.record_desired_set(
            scope=scope,
            desired_set=desired,
            expected_revision=head.desired_set.revision,
            actor_id=actor_id,
        )
        return MarketplaceDesiredBundleMutationV2(record=record, changed=True)

    async def _head(
        self,
        *,
        scope: ScopeV2,
        actor_id: str | None,
    ) -> PlatformPluginDesiredBundleSetRecordV2:
        current = await self._repository.current_desired_set(scope)
        if current is not None:
            return current
        if scope.kind is not ScopeKindV2.ROOT:
            raise ValueError("marketplace scope must be initialized before mutation")
        return await self._repository.record_desired_set(
            scope=scope,
            desired_set=self._baseline,
            expected_revision=None,
            actor_id=actor_id,
        )

    @staticmethod
    def _next_revision(
        current: DesiredBundleSetV2,
        bundles: tuple[BundleReferenceV2, ...],
    ) -> DesiredBundleSetV2:
        desired = replace(
            current,
            revision=current.revision + 1,
            bundles=bundles,
            digest=_ZERO_DIGEST_V2,
        )
        return replace(desired, digest=desired_bundle_set_digest_v2(desired))

    @staticmethod
    def _require_root_scope(scope: ScopeV2) -> None:
        from src.infrastructure.plugins.v2.scope import validate_scope_v2

        validate_scope_v2(scope)
        if scope.kind is ScopeKindV2.SESSION:
            raise ValueError("marketplace installation requires tenant or project scope")


__all__ = [
    "MarketplaceDesiredBundleMutationV2",
    "PluginMarketplaceDesiredBundleServiceV2",
]
