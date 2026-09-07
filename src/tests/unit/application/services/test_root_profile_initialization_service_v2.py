"""ROOT initialization uses real production composition and transactional repositories."""

from dataclasses import replace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
from src.infrastructure.plugins.v2.layer_composer import compose_profile_sources_v2
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2

pytestmark = pytest.mark.unit
ROOT = ScopeV2(kind=ScopeKindV2.ROOT)


@pytest.mark.parametrize("enabled", [True, False])
async def test_explicit_setting_persists_exact_source_and_is_not_overwritten(db_session, enabled):
    sources = production_bundle_sources_v2()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    service = RootProfileInitializationServiceV2(
        session_factory=factory, production_sources=sources
    )
    record = await service.ensure_initialized(
        workspace_core_enabled=enabled, actor_id="initializer"
    )
    assert record.desired_set.revision == 1
    assert (
        await service.ensure_initialized(workspace_core_enabled=not enabled, actor_id="other")
        == record
    )
    async with factory() as db:
        ref = record.desired_set.profile_source
        source = await PlatformPluginProfileSourceRepositoryV2(db).read_exact(
            scope=ROOT, source_id=ref.source_id, revision=ref.revision, digest=ref.digest
        )
        assert source.layers[:-1] == sources.profile_source.layers
        replacements = source.layers[-1].replacements
        assert len(replacements) == 4
        replacements = tuple(
            entry for entry in replacements if entry.entry_id != "builtin-agent-pool-runtime"
        )
        assert all(entry.enabled == enabled for entry in replacements)
        composition = compose_profile_sources_v2(
            desired_set=record.desired_set,
            bundles=(sources.bundle,),
            profile_source=source,
            scope=ROOT,
        )
        replaced = {entry.entry_id for entry in replacements}
        assert all(
            entry.enabled == enabled
            for entry in composition.document.entries
            if entry.entry_id in replaced
        )
        assert len((await db.scalars(select(PlatformPluginV2ProfileSourceModel))).all()) == 1


async def test_existing_legacy_desired_remains_untouched(db_session):
    sources = production_bundle_sources_v2()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as db:
        existing = await PlatformPluginDesiredBundleSetRepositoryV2(db).record_desired_set(
            scope=ROOT,
            desired_set=sources.desired_set,
            expected_revision=None,
            actor_id="explicit-user",
        )
        await db.commit()
    service = RootProfileInitializationServiceV2(
        session_factory=factory, production_sources=sources
    )
    assert await service.ensure_initialized(workspace_core_enabled=True) == existing
    async with factory() as db:
        assert not (await db.scalars(select(PlatformPluginV2ProfileSourceModel))).all()


async def test_commit_failure_rolls_back_both_records(db_session):
    sources = production_bundle_sources_v2()
    error = RuntimeError("commit fault")

    class FailedSession(AsyncSession):
        async def commit(self):
            raise error

    factory = async_sessionmaker(db_session.bind, class_=FailedSession, expire_on_commit=False)
    service = RootProfileInitializationServiceV2(
        session_factory=factory, production_sources=sources
    )
    with pytest.raises(RuntimeError) as failure:
        await service.ensure_initialized(workspace_core_enabled=True)
    assert failure.value is error
    async with async_sessionmaker(db_session.bind)() as db:
        assert (
            await PlatformPluginDesiredBundleSetRepositoryV2(db).current_desired_set(ROOT) is None
        )
        assert not (await db.scalars(select(PlatformPluginV2ProfileSourceModel))).all()


async def test_source_cas_conflict_does_not_create_desired(db_session):
    sources = production_bundle_sources_v2()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    from src.infrastructure.plugins.v2.layer_composer import profile_source_digest_v2

    conflict = replace(
        sources.profile_source, source_id="memstack-root-initialized-profile-source-v2"
    )
    conflict = replace(conflict, digest=profile_source_digest_v2(conflict))
    async with factory() as db:
        await PlatformPluginProfileSourceRepositoryV2(db).record_source(
            scope=ROOT, source=conflict, expected_revision=None
        )
        await db.commit()
    service = RootProfileInitializationServiceV2(
        session_factory=factory, production_sources=sources
    )
    with pytest.raises(ValueError, match="CAS"):
        await service.ensure_initialized(workspace_core_enabled=True)
    async with factory() as db:
        assert (
            await PlatformPluginDesiredBundleSetRepositoryV2(db).current_desired_set(ROOT) is None
        )


@pytest.mark.parametrize("enabled", [True, False])
async def test_explicit_agent_pool_config_is_durable_and_existing_choice_wins(db_session, enabled):
    from src.infrastructure.plugins.v2.agent_pool_runtime import (
        default_agent_pool_runtime_config_v2,
    )

    sources = production_bundle_sources_v2()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    service = RootProfileInitializationServiceV2(
        session_factory=factory, production_sources=sources
    )
    config = default_agent_pool_runtime_config_v2(health_check_interval_seconds=57)
    config["max_total_instances"] = 12
    record = await service.ensure_initialized(
        workspace_core_enabled=False,
        agent_pool_runtime_enabled=enabled,
        agent_pool_runtime_config=config,
    )
    config["max_total_instances"] = 99
    async with factory() as db:
        ref = record.desired_set.profile_source
        source = await PlatformPluginProfileSourceRepositoryV2(db).read_exact(
            scope=ROOT, source_id=ref.source_id, revision=ref.revision, digest=ref.digest
        )
        entry = next(
            entry
            for entry in source.layers[-1].replacements
            if entry.entry_id == "builtin-agent-pool-runtime"
        )
        assert entry.enabled is enabled
        assert entry.config["max_total_instances"] == 12
        assert entry.config["health_check_interval_seconds"] == 57
    assert (
        await service.ensure_initialized(
            workspace_core_enabled=True,
            agent_pool_runtime_enabled=not enabled,
            agent_pool_runtime_config=config,
        )
        == record
    )
