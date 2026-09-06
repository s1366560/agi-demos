"""First desired revision races use a real PostgreSQL scope-head lock."""

import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
    PlatformPluginDesiredBundleSetV2Error,
)
from src.infrastructure.plugins.v2.layer_composer import desired_bundle_set_digest_v2
from src.tests.integration.test_platform_plugin_scoped_ledger_postgres import sessions  # noqa: F401
from src.tests.unit.routers.test_platform_plugin_desired_bundles_v2_router import _desired_set

pytestmark = pytest.mark.integration


async def test_first_desired_cas_race_has_one_winner(sessions):  # noqa: F811
    scope = ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=uuid4().hex)
    first = _desired_set()
    second = replace(first, desired_set_id="competing-desired")
    second = replace(second, digest=desired_bundle_set_digest_v2(second))
    barrier = asyncio.Barrier(2)

    async def write(desired):
        async with sessions.begin() as session:
            await barrier.wait()
            try:
                await PlatformPluginDesiredBundleSetRepositoryV2(session).record_desired_set(
                    scope=scope, desired_set=desired, expected_revision=None, actor_id="fixture"
                )
            except PlatformPluginDesiredBundleSetV2Error as error:
                assert error.code == "desired_set_head_conflict"
                return False
            return True

    result = await asyncio.wait_for(asyncio.gather(write(first), write(second)), 10)
    assert sorted(result) == [False, True]
    async with sessions() as session:
        history = await PlatformPluginDesiredBundleSetRepositoryV2(session).list_history(scope)
        assert len(history) == 1
