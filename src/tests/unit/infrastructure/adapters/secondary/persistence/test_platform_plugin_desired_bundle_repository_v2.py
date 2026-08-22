"""Immutable, scope-private DesiredBundleSetV2 repository tests."""

from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import (
    DesiredBundleSetV2,
    ProfileLayerKindV2,
    ScopeKindV2,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2DesiredBundleSetModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
    PlatformPluginDesiredBundleSetV2Error,
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


def _desired_set(*, revision: int = 7) -> DesiredBundleSetV2:
    root = _scope()
    bundle = _bundle(
        "base-runtime",
        plugin_id="plugin-a",
        layers=(
            _layer(
                "base",
                ProfileLayerKindV2.BUNDLE,
                entries=(_entry("provider", scope=root),),
            ),
        ),
    )
    source = _source(
        (
            _layer(
                "profile",
                ProfileLayerKindV2.PROFILE,
                entries=(_entry("consumer", scope=root),),
            ),
        )
    )
    desired = _desired((bundle,), source)
    desired = replace(desired, revision=revision, digest=f"sha256:{'0' * 64}")
    return replace(desired, digest=desired_bundle_set_digest_v2(desired))


async def test_records_and_round_trips_one_exact_scoped_desired_set(
    db_session: AsyncSession,
) -> None:
    scope = _scope()
    desired = _desired_set()
    repository = PlatformPluginDesiredBundleSetRepositoryV2(db_session)

    recorded = await repository.record_desired_set(
        scope=scope,
        desired_set=desired,
        expected_revision=None,
        actor_id="admin-a",
    )
    current = await repository.current_desired_set(scope)

    assert current == recorded
    assert current is not None
    assert current.scope == scope
    assert current.desired_set == desired
    assert current.actor_id == "admin-a"


async def test_revision_is_compare_and_swap_and_retries_are_idempotent(
    db_session: AsyncSession,
) -> None:
    scope = _scope()
    first = _desired_set()
    repository = PlatformPluginDesiredBundleSetRepositoryV2(db_session)
    initial = await repository.record_desired_set(
        scope=scope,
        desired_set=first,
        expected_revision=None,
        actor_id="admin-a",
    )

    repeated = await repository.record_desired_set(
        scope=scope,
        desired_set=first,
        expected_revision=None,
        actor_id="admin-b",
    )

    assert repeated.record_id == initial.record_id
    count = await db_session.scalar(
        select(func.count()).select_from(PlatformPluginV2DesiredBundleSetModel)
    )
    assert count == 1

    second = replace(first, revision=first.revision + 1, digest=f"sha256:{'0' * 64}")
    second = replace(second, digest=desired_bundle_set_digest_v2(second))
    updated = await repository.record_desired_set(
        scope=scope,
        desired_set=second,
        expected_revision=first.revision,
        actor_id="admin-b",
    )

    assert updated.desired_set == second
    assert [item.desired_set.revision for item in await repository.list_history(scope)] == [
        second.revision,
        first.revision,
    ]

    stale_desired = replace(
        second,
        revision=second.revision + 1,
        digest=f"sha256:{'0' * 64}",
    )
    stale_desired = replace(
        stale_desired,
        digest=desired_bundle_set_digest_v2(stale_desired),
    )
    with pytest.raises(PlatformPluginDesiredBundleSetV2Error) as stale:
        await repository.record_desired_set(
            scope=scope,
            desired_set=stale_desired,
            expected_revision=first.revision,
            actor_id="admin-c",
        )
    assert stale.value.code == "desired_set_head_conflict"


async def test_rejects_revision_gaps_and_desired_set_identity_changes(
    db_session: AsyncSession,
) -> None:
    scope = _scope()
    first = _desired_set()
    repository = PlatformPluginDesiredBundleSetRepositoryV2(db_session)
    await repository.record_desired_set(
        scope=scope,
        desired_set=first,
        expected_revision=None,
        actor_id=None,
    )

    gap = replace(first, revision=first.revision + 2, digest=f"sha256:{'0' * 64}")
    gap = replace(gap, digest=desired_bundle_set_digest_v2(gap))
    with pytest.raises(PlatformPluginDesiredBundleSetV2Error) as gap_error:
        await repository.record_desired_set(
            scope=scope,
            desired_set=gap,
            expected_revision=first.revision,
            actor_id=None,
        )
    assert gap_error.value.code == "desired_set_revision_gap"

    renamed = replace(
        first,
        desired_set_id="another-desired-set",
        revision=first.revision + 1,
        digest=f"sha256:{'0' * 64}",
    )
    renamed = replace(renamed, digest=desired_bundle_set_digest_v2(renamed))
    with pytest.raises(PlatformPluginDesiredBundleSetV2Error) as identity_error:
        await repository.record_desired_set(
            scope=scope,
            desired_set=renamed,
            expected_revision=first.revision,
            actor_id=None,
        )
    assert identity_error.value.code == "desired_set_identity_conflict"


async def test_scope_heads_are_isolated_and_invalid_scope_is_rejected(
    db_session: AsyncSession,
) -> None:
    tenant_a = _scope(kind=ScopeKindV2.TENANT, tenant_id="tenant-a")
    tenant_b = _scope(kind=ScopeKindV2.TENANT, tenant_id="tenant-b")
    desired = _desired_set()
    repository = PlatformPluginDesiredBundleSetRepositoryV2(db_session)

    await repository.record_desired_set(
        scope=tenant_a,
        desired_set=desired,
        expected_revision=None,
        actor_id=None,
    )
    await repository.record_desired_set(
        scope=tenant_b,
        desired_set=desired,
        expected_revision=None,
        actor_id=None,
    )

    assert (await repository.current_desired_set(tenant_a)) is not None
    assert (await repository.current_desired_set(tenant_b)) is not None
    assert len(await repository.list_history(tenant_a)) == 1
    assert len(await repository.list_history(tenant_b)) == 1

    invalid = replace(tenant_a, project_id="project-without-project-scope")
    with pytest.raises(PlatformPluginDesiredBundleSetV2Error) as scope_error:
        await repository.current_desired_set(invalid)
    assert scope_error.value.code == "desired_set_scope_invalid"
