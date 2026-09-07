"""Real SQL first initialization, exact source isolation and atomic rollback."""

import json
from dataclasses import replace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.application.services.scoped_profile_initialization_service_v2 import (
    ScopedProfileInitializationServiceV2,
    ScopedProfileInitializationV2Error,
)
from src.domain.model.plugins.generated_v2 import (
    ProfileLayerKindV2,
    ProfileSourceReferenceV2,
    ScopeKindV2,
    ScopeV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_model_v2 import (
    PlatformPluginV2ProfileSourceModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.plugins.v2.layer_composer import (
    desired_bundle_set_digest_v2,
    profile_source_digest_v2,
)
from src.infrastructure.plugins.v2.production_bundle import ProductionBundleSourcesV2
from src.infrastructure.plugins.v2.scope import scope_key_v2
from src.tests.unit.infrastructure.plugins.v2.test_profile_watcher_v2 import _candidate_inputs

pytestmark = pytest.mark.unit
ROOT = ScopeV2(kind=ScopeKindV2.ROOT)
TENANT = ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="t")
PROJECT = ScopeV2(kind=ScopeKindV2.PROJECT, tenant_id="t", project_id="p")
SESSION = ScopeV2(kind=ScopeKindV2.SESSION, tenant_id="t", project_id="p", session_id="s")


def desired_for(desired, source):
    desired = replace(
        desired,
        profile_source=ProfileSourceReferenceV2(
            source_id=source.source_id, revision=source.revision, digest=source.digest
        ),
    )
    return replace(desired, digest=desired_bundle_set_digest_v2(desired))


@pytest.fixture
async def setup(db_session):
    bundle, raw, source, desired = _candidate_inputs(Ed25519PrivateKey.generate())
    from src.tests.unit.infrastructure.plugins.v2.layer_composer_test_support import _layer

    source = replace(
        source,
        layers=(
            _layer(
                "baseline", ProfileLayerKindV2.PROFILE, scope=ROOT, disabled_entry_ids=("disabled",)
            ),
        ),
    )
    source = replace(source, digest=profile_source_digest_v2(source))
    desired = desired_for(desired, source)
    production = ProductionBundleSourcesV2(
        bundle=bundle, bundle_archive=raw, profile_source=source, desired_set=desired
    )
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    service = ScopedProfileInitializationServiceV2(
        session_factory=factory, production_sources=production
    )
    return service, factory, source, desired


async def seed(factory, scope, source, desired, store_source=True):
    async with factory() as db:
        if store_source:
            await PlatformPluginProfileSourceRepositoryV2(db).record_source(
                scope=scope, source=source, expected_revision=None
            )
        record = await PlatformPluginDesiredBundleSetRepositoryV2(db).record_desired_set(
            scope=scope, desired_set=desired, expected_revision=None, actor_id="parent"
        )
        await db.commit()
        return record


async def test_root_builtin_clone_then_idempotent_private_snapshot(setup):
    service, factory, source, desired = setup
    await seed(factory, ROOT, source, desired, store_source=False)
    result = await service.ensure_initialized(SESSION, "actor")
    assert result.scope == SESSION and result.actor_id == "actor"
    assert result.desired_set.bundles == desired.bundles
    assert result.desired_set.revision == 1
    assert result.desired_set.desired_set_id != desired.desired_set_id
    reference = result.desired_set.profile_source
    async with factory() as db:
        clone = await PlatformPluginProfileSourceRepositoryV2(db).read_exact(
            scope=SESSION, source_id=reference.source_id, revision=1, digest=reference.digest
        )
        assert clone.layers == source.layers
        provenance = json.loads(clone.provenance)
        assert provenance["parent_scope"] == {"kind": "root"}
        assert provenance["source"]["digest"] == source.digest
        assert provenance["original_provenance"] == source.provenance
        assert len(clone.source_id) < 255
        newer = replace(desired, revision=2)
        newer = replace(newer, digest=desired_bundle_set_digest_v2(newer))
        await PlatformPluginDesiredBundleSetRepositoryV2(db).record_desired_set(
            scope=ROOT, desired_set=newer, expected_revision=1, actor_id="root"
        )
        await db.commit()
    assert await service.ensure_initialized(SESSION, "different") == result
    sibling = replace(SESSION, session_id="s2")
    other = await service.ensure_initialized(sibling, "actor")
    assert other.desired_set.profile_source.source_id != reference.source_id


async def test_nearest_parent_chosen_without_merging(setup):
    service, factory, source, desired = setup
    await seed(factory, ROOT, source, desired, store_source=False)
    await service.ensure_initialized(TENANT, "actor")
    project_source = replace(source, source_id="project-only", provenance="project")
    project_source = replace(project_source, digest=profile_source_digest_v2(project_source))
    project_desired = desired_for(desired, project_source)
    await seed(factory, PROJECT, project_source, project_desired)
    result = await service.ensure_initialized(SESSION, "actor")
    async with factory() as db:
        ref = result.desired_set.profile_source
        clone = await PlatformPluginProfileSourceRepositoryV2(db).read_exact(
            scope=SESSION, source_id=ref.source_id, revision=1, digest=ref.digest
        )
        assert json.loads(clone.provenance)["parent_scope"]["kind"] == "project"
        assert json.loads(clone.provenance)["original_provenance"] == "project"


async def test_broken_nearest_parent_does_not_fallback_and_no_target_writes(setup):
    service, factory, source, desired = setup
    await seed(factory, ROOT, source, desired, store_source=False)
    await seed(factory, PROJECT, source, desired, store_source=False)
    with pytest.raises(ScopedProfileInitializationV2Error) as failure:
        await service.ensure_initialized(SESSION, "actor")
    assert failure.value.code == "scoped_initialization_source_missing"
    async with factory() as db:
        assert (
            await PlatformPluginDesiredBundleSetRepositoryV2(db).current_desired_set(SESSION)
            is None
        )
        assert not (
            await db.scalars(
                select(PlatformPluginV2ProfileSourceModel).where(
                    PlatformPluginV2ProfileSourceModel.scope_key == scope_key_v2(SESSION)
                )
            )
        ).all()


async def test_existing_child_missing_source_is_not_repaired_from_parent(setup):
    service, factory, source, desired = setup
    await seed(factory, ROOT, source, desired, store_source=False)
    await seed(factory, SESSION, source, desired, store_source=False)
    with pytest.raises(ScopedProfileInitializationV2Error):
        await service.ensure_initialized(SESSION, "actor")


async def test_missing_ancestor_and_root_target_fail(setup):
    service, _, _, _ = setup
    with pytest.raises(ScopedProfileInitializationV2Error) as missing:
        await service.ensure_initialized(TENANT, "actor")
    assert missing.value.code == "scoped_initialization_parent_missing"
    with pytest.raises(ScopedProfileInitializationV2Error) as root:
        await service.ensure_initialized(ROOT, "actor")
    assert root.value.code == "scoped_initialization_root_forbidden"


async def test_existing_configuration_does_not_lock_heads(setup, monkeypatch):
    from src.infrastructure.adapters.secondary.persistence.platform_plugin_scope_ledger_v2 import (
        ScopeLedgerBindingV2,
    )

    service, factory, source, desired = setup
    await seed(factory, SESSION, source, desired)

    async def forbidden(*args, **kwargs):
        raise AssertionError("existing source must not acquire ancestor locks")

    monkeypatch.setattr(ScopeLedgerBindingV2, "lock", forbidden)
    result = await service.ensure_initialized(SESSION, "actor")
    assert result.desired_set == desired


async def test_lock_order_is_root_to_leaf_with_real_repository_locks(setup, monkeypatch):
    from src.infrastructure.adapters.secondary.persistence.platform_plugin_scope_ledger_v2 import (
        ScopeLedgerBindingV2,
    )

    service, factory, source, desired = setup
    await seed(factory, ROOT, source, desired, store_source=False)
    original = ScopeLedgerBindingV2.lock
    observed = []

    async def record(binding, session):
        observed.append(binding.scope)
        return await original(binding, session)

    monkeypatch.setattr(ScopeLedgerBindingV2, "lock", record)
    await service.ensure_initialized(SESSION, "actor")
    assert observed[:4] == [ROOT, TENANT, PROJECT, SESSION]
    assert all(scope == SESSION for scope in observed[4:])


async def test_commit_failure_rolls_back_source_and_desired(setup):
    from sqlalchemy.ext.asyncio import AsyncSession

    service, factory, source, desired = setup
    await seed(factory, ROOT, source, desired, store_source=False)
    original = RuntimeError("commit fault")

    class FailingSession(AsyncSession):
        async def commit(self):
            raise original

    async with factory() as db:
        bind = db.bind
    failing_factory = async_sessionmaker(bind, class_=FailingSession, expire_on_commit=False)
    failing = ScopedProfileInitializationServiceV2(
        session_factory=failing_factory, production_sources=service._production_sources
    )
    with pytest.raises(RuntimeError) as failure:
        await failing.ensure_initialized(SESSION, "actor")
    assert failure.value is original
    async with factory() as db:
        assert (
            await PlatformPluginDesiredBundleSetRepositoryV2(db).current_desired_set(SESSION)
            is None
        )
        assert not (await db.scalars(select(PlatformPluginV2ProfileSourceModel))).all()
    assert (await service.ensure_initialized(SESSION, "actor")).desired_set.revision == 1
