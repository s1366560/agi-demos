"""Reject stale desired snapshots inside the PostgreSQL request transaction."""

from dataclasses import replace
from uuid import uuid4

import pytest

from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.layer_composer import desired_bundle_set_digest_v2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.scoped_publication_coordinator import (
    ScopedPublicationCoordinatorV2,
)
from src.tests.integration.test_platform_plugin_scoped_ledger_postgres import sessions  # noqa: F401
from src.tests.unit.infrastructure.plugins.v2.test_scoped_runtime_registry import (
    _SERVICE,
    _profile,
    _registry,
    _scope,
)
from src.tests.unit.routers.test_platform_plugin_desired_bundles_v2_router import _desired_set

pytestmark = pytest.mark.integration


async def test_stale_desired_fence_rolls_back_version_and_prevents_apply(sessions):  # noqa: F811
    scope = _scope(tenant=uuid4().hex)
    first = _desired_set()
    second = replace(first, revision=first.revision + 1)
    second = replace(second, digest=desired_bundle_set_digest_v2(second))
    async with sessions.begin() as session:
        repository = PlatformPluginDesiredBundleSetRepositoryV2(session)
        await repository.record_desired_set(
            scope=scope, desired_set=first, expected_revision=None, actor_id="fixture"
        )
        await repository.record_desired_set(
            scope=scope, desired_set=second, expected_revision=first.revision, actor_id="fixture"
        )
    calls = []

    def apply(context, _config):
        calls.append(True)
        context.provide(_SERVICE, object())

    snapshot = _profile(scope)
    coordinator = ScopedPublicationCoordinatorV2(
        session_factory=sessions, registry=_registry(snapshot, apply)
    )
    try:
        with pytest.raises(RuntimeV2Error) as caught:
            await coordinator.publish(scope, snapshot, expected_desired=first)
        assert caught.value.code == "scope_desired_changed"
        assert calls == []
        async with sessions() as session:
            assert (
                await PlatformPluginRepositoryV2(
                    session, scope=scope
                ).latest_requested_distribution()
                is None
            )
        accepted = await coordinator.publish(scope, snapshot, expected_desired=second)
        assert accepted.accepted
        assert accepted.envelope.version == 1
        assert calls == [True]
    finally:
        await coordinator.close()
