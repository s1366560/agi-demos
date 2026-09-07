"""Atomic first-use configuration materialization under real PostgreSQL locks."""

import asyncio
from uuid import uuid4

import pytest

from src.application.services.scoped_profile_initialization_service_v2 import (
    ScopedProfileInitializationServiceV2,
)
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.tests.integration.test_platform_plugin_scoped_ledger_postgres import sessions  # noqa: F401

pytestmark = pytest.mark.integration


async def test_two_process_initializers_share_one_exact_materialized_revision(sessions):  # noqa: F811
    sources = production_bundle_sources_v2()
    tenant = uuid4().hex
    parent = ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=tenant)
    scope = ScopeV2(kind=ScopeKindV2.SESSION, tenant_id=tenant, project_id="p", session_id="s")
    async with sessions.begin() as session:
        await PlatformPluginProfileSourceRepositoryV2(session).record_source(
            scope=parent, source=sources.profile_source, expected_revision=None
        )
        await PlatformPluginDesiredBundleSetRepositoryV2(session).record_desired_set(
            scope=parent, desired_set=sources.desired_set, expected_revision=None, actor_id="parent"
        )
    barrier = asyncio.Barrier(2)

    async def initialize(actor):
        service = ScopedProfileInitializationServiceV2(
            session_factory=sessions, production_sources=sources
        )
        await barrier.wait()
        return await service.ensure_initialized(scope, actor_id=actor)

    first, second = await asyncio.wait_for(
        asyncio.gather(initialize("first"), initialize("second")), 15
    )
    assert first.record_id == second.record_id
    assert first.desired_set == second.desired_set
    assert first.desired_set.revision == 1
    async with sessions() as session:
        history = await PlatformPluginDesiredBundleSetRepositoryV2(session).list_history(scope)
        assert len(history) == 1
        ref = first.desired_set.profile_source
        stored = await PlatformPluginProfileSourceRepositoryV2(session).read_exact(
            scope=scope, source_id=ref.source_id, revision=ref.revision, digest=ref.digest
        )
        assert stored is not None
        assert stored.layers == sources.profile_source.layers
