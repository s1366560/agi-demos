"""Protocol-v2 marketplace desired Bundle mutation tests."""

from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.plugin_marketplace_desired_bundle_service_v2 import (
    PluginMarketplaceDesiredBundleServiceV2,
)
from src.domain.model.plugins.generated_v2 import (
    BundleReferenceV2,
    ProfileLayerKindV2,
    ScopeKindV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.plugins.v2.layer_composer import desired_bundle_set_digest_v2
from src.tests.unit.infrastructure.plugins.v2.layer_composer_test_support import (
    _bundle,
    _desired,
    _entry,
    _layer,
    _scope,
    _source,
)

pytestmark = pytest.mark.unit

_ZERO_DIGEST_V2 = f"sha256:{'0' * 64}"


def _baseline():
    root = _scope()
    base = _bundle(
        "memstack-platform-base",
        plugin_id="memstack-runtime-kernel",
        layers=(
            _layer(
                "memstack-base",
                ProfileLayerKindV2.BUNDLE,
                entries=(_entry("runtime", scope=root),),
            ),
        ),
    )
    source = _source(
        (
            _layer(
                "memstack-profile",
                ProfileLayerKindV2.PROFILE,
                entries=(_entry("profile", scope=root),),
            ),
        )
    )
    desired = _desired((base,), source)
    desired = replace(
        desired,
        desired_set_id="memstack-default-v2",
        revision=1,
        digest=_ZERO_DIGEST_V2,
    )
    return replace(desired, digest=desired_bundle_set_digest_v2(desired))


def _marketplace_bundle(*, version: str = "1.0.0", digest_digit: str = "a"):
    return BundleReferenceV2(
        bundle_id="third-party-tools",
        version=version,
        digest=f"sha256:{digest_digit * 64}",
        source=f"marketplace://third-party-tools/{version}",
    )


def _service(db: AsyncSession) -> PluginMarketplaceDesiredBundleServiceV2:
    return PluginMarketplaceDesiredBundleServiceV2(
        PlatformPluginDesiredBundleSetRepositoryV2(db),
        baseline=_baseline(),
    )


async def test_install_seeds_baseline_then_appends_exact_bundle(
    db_session: AsyncSession,
) -> None:
    scope = _scope()
    mutation = await _service(db_session).install(
        scope=scope,
        bundle=_marketplace_bundle(),
        actor_id="admin-a",
    )

    history = await PlatformPluginDesiredBundleSetRepositoryV2(db_session).list_history(scope)
    assert mutation.changed is True
    assert mutation.record.desired_set.revision == 2
    assert [reference.bundle_id for reference in mutation.record.desired_set.bundles] == [
        "memstack-platform-base",
        "third-party-tools",
    ]
    assert [record.desired_set.revision for record in history] == [2, 1]


async def test_install_is_idempotent_and_explicit_upgrade_keeps_order(
    db_session: AsyncSession,
) -> None:
    scope = _scope()
    service = _service(db_session)
    first = await service.install(
        scope=scope,
        bundle=_marketplace_bundle(),
        actor_id="admin-a",
    )

    repeated = await service.install(
        scope=scope,
        bundle=_marketplace_bundle(),
        actor_id="admin-b",
    )
    upgraded = await service.install(
        scope=scope,
        bundle=_marketplace_bundle(version="1.1.0", digest_digit="b"),
        actor_id="admin-b",
    )

    assert repeated.changed is False
    assert repeated.record.record_id == first.record.record_id
    assert upgraded.changed is True
    assert upgraded.record.desired_set.revision == 3
    assert [reference.bundle_id for reference in upgraded.record.desired_set.bundles] == [
        "memstack-platform-base",
        "third-party-tools",
    ]
    assert upgraded.record.desired_set.bundles[-1].version == "1.1.0"


async def test_uninstall_removes_only_marketplace_bundle_and_is_idempotent(
    db_session: AsyncSession,
) -> None:
    scope = _scope()
    service = _service(db_session)
    installed = await service.install(
        scope=scope,
        bundle=_marketplace_bundle(),
        actor_id="admin-a",
    )

    removed = await service.uninstall(
        scope=scope,
        bundle_id="third-party-tools",
        version="1.0.0",
        actor_id="admin-a",
    )
    repeated = await service.uninstall(
        scope=scope,
        bundle_id="third-party-tools",
        version="1.0.0",
        actor_id="admin-b",
    )

    assert installed.record.desired_set.revision == 2
    assert removed.changed is True
    assert removed.record.desired_set.revision == 3
    assert [reference.bundle_id for reference in removed.record.desired_set.bundles] == [
        "memstack-platform-base"
    ]
    assert repeated.changed is False
    assert repeated.record.record_id == removed.record.record_id


async def test_uninstall_of_old_version_preserves_current_upgrade(
    db_session: AsyncSession,
) -> None:
    scope = _scope()
    service = _service(db_session)
    _ = await service.install(
        scope=scope,
        bundle=_marketplace_bundle(version="1.1.0", digest_digit="b"),
        actor_id="admin-a",
    )

    old_version = await service.uninstall(
        scope=scope,
        bundle_id="third-party-tools",
        version="1.0.0",
        actor_id="admin-b",
    )

    assert old_version.changed is False
    assert old_version.record.desired_set.revision == 2
    assert old_version.record.desired_set.bundles[-1].version == "1.1.0"


async def test_rejects_non_root_scope_and_protected_bundle_mutation(
    db_session: AsyncSession,
) -> None:
    service = _service(db_session)
    root = _scope()

    with pytest.raises(ValueError, match="initialized"):
        await service.install(
            scope=replace(root, kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            bundle=_marketplace_bundle(),
            actor_id=None,
        )
    with pytest.raises(ValueError, match="protected baseline"):
        await service.uninstall(
            scope=root,
            bundle_id="memstack-platform-base",
            actor_id=None,
        )
