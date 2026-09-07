"""Concurrent ROOT initialization on a fresh, explicitly configured PostgreSQL slice.

The shared fixture does not reset data. Run this test before other ROOT writers or
on its own migrated slice; existing ROOT rows are never deleted by this test.
"""

import asyncio

import pytest
from sqlalchemy import func, select

from src.application.services.root_profile_initialization_service_v2 import (
    RootProfileInitializationServiceV2,
)
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_model_v2 import (
    PlatformPluginV2ProfileSourceModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.infrastructure.plugins.v2.scope import scope_key_v2
from src.tests.integration.test_platform_plugin_scoped_ledger_postgres import sessions  # noqa: F401

pytestmark = pytest.mark.integration


async def test_concurrent_root_initializers_commit_one_exact_revision(sessions):  # noqa: F811
    scope = ScopeV2(kind=ScopeKindV2.ROOT)
    sources = production_bundle_sources_v2()
    async with sessions() as session:
        assert (
            await PlatformPluginDesiredBundleSetRepositoryV2(session).current_desired_set(scope)
            is None
        ), "requires a fresh isolated PostgreSQL ROOT configuration"
        assert (
            await session.scalar(
                select(func.count())
                .select_from(PlatformPluginV2ProfileSourceModel)
                .where(PlatformPluginV2ProfileSourceModel.scope_key == scope_key_v2(scope))
            )
            == 0
        )
    barrier = asyncio.Barrier(2)

    async def initialize(actor):
        service = RootProfileInitializationServiceV2(
            session_factory=sessions, production_sources=sources
        )
        await barrier.wait()
        return await service.ensure_initialized(workspace_core_enabled=True, actor_id=actor)

    first, second = await asyncio.wait_for(
        asyncio.gather(initialize("first"), initialize("second")), 15
    )
    assert first.record_id == second.record_id
    assert first.desired_set == second.desired_set
    assert first.desired_set.revision == 1
    assert first.actor_id == second.actor_id
    assert first.actor_id in {"first", "second"}
    async with sessions() as session:
        history = await PlatformPluginDesiredBundleSetRepositoryV2(session).list_history(scope)
        assert len(history) == 1
        assert history[0] == first
        rows = (
            await session.scalars(
                select(PlatformPluginV2ProfileSourceModel).where(
                    PlatformPluginV2ProfileSourceModel.scope_key == scope_key_v2(scope)
                )
            )
        ).all()
        assert len(rows) == 1
        reference = first.desired_set.profile_source
        assert (rows[0].source_id, rows[0].revision, rows[0].digest) == (
            reference.source_id,
            1,
            reference.digest,
        )
        stored = await PlatformPluginProfileSourceRepositoryV2(session).read_exact(
            scope=scope,
            source_id=reference.source_id,
            revision=reference.revision,
            digest=reference.digest,
        )
        assert stored is not None
        assert stored.layers[:-1] == sources.profile_source.layers
        replacements = {entry.entry_id: entry for entry in stored.layers[-1].replacements}
        assert len(replacements) == 4
        assert replacements.pop("builtin-agent-pool-runtime").enabled is False
        assert all(entry.enabled for entry in replacements.values())
