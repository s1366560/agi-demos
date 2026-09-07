"""Actual persistent startup follows exact ROOT source rather than factory overlays."""

from dataclasses import replace

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.application.services.root_profile_initialization_service_v2 import (
    RootProfileInitializationServiceV2,
)
from src.domain.model.plugins.generated_v2 import (
    ProfileLayerKindV2,
    ProfileLayerV2,
    ProfileSourceReferenceV2,
    ScopeKindV2,
    ScopeV2,
)
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.plugins.v2.composer import compose_profile_v2
from src.infrastructure.plugins.v2.layer_composer import (
    compose_profile_sources_v2,
    desired_bundle_set_digest_v2,
    profile_source_digest_v2,
)
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.infrastructure.plugins.v2.workspace_core_runtime import WorkspaceCoreRuntimeServiceV2
from src.infrastructure.plugins.v2.workspace_core_shadow import (
    WORKSPACE_CORE_CONTRACT_ACTOR_RESOLVER_ENTRY_ID_V2,
    WORKSPACE_CORE_RUNTIME_ENTRY_ID_V2,
    WORKSPACE_PROMPT_CONTEXT_ENTRY_ID_V2,
)

pytestmark = pytest.mark.unit
ROOT = ScopeV2(kind=ScopeKindV2.ROOT)
WORKSPACE_ENTRIES = {
    WORKSPACE_CORE_RUNTIME_ENTRY_ID_V2,
    WORKSPACE_CORE_CONTRACT_ACTOR_RESOLVER_ENTRY_ID_V2,
    WORKSPACE_PROMPT_CONTEXT_ENTRY_ID_V2,
}


async def exact_source(factory):
    async with factory() as db:
        record = await PlatformPluginDesiredBundleSetRepositoryV2(db).current_desired_set(ROOT)
        assert record is not None
        ref = record.desired_set.profile_source
        source = await PlatformPluginProfileSourceRepositoryV2(db).read_exact(
            scope=ROOT, source_id=ref.source_id, revision=ref.revision, digest=ref.digest
        )
        assert source is not None
        return record, source


async def test_disabled_workspace_source_wins_over_factory_and_restart_is_stable(db_session):
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    await RootProfileInitializationServiceV2(
        session_factory=factory, production_sources=production_bundle_sources_v2()
    ).ensure_initialized(workspace_core_enabled=False)
    calls = 0

    async def workspace_factory() -> WorkspaceCoreRuntimeServiceV2:
        nonlocal calls
        calls += 1
        raise AssertionError("disabled Workspace runtime must not be constructed")

    first_app = FastAPI()
    try:
        host = await initialize_plugin_runtime_v2(
            first_app, session_factory=factory, workspace_core_runtime_factory=workspace_factory
        )
        first = host.current_publication.snapshot
        selected = [entry for entry in first.entries if entry.entry_id in WORKSPACE_ENTRIES]
        assert len(selected) == 3 and all(not entry.enabled for entry in selected)
        assert calls == 0
    finally:
        await shutdown_plugin_runtime_v2(first_app)
    second_app = FastAPI()
    try:
        restarted = await initialize_plugin_runtime_v2(
            second_app, session_factory=factory, workspace_core_runtime_factory=workspace_factory
        )
        assert restarted.current_publication.snapshot.generation == first.generation
        assert restarted.current_publication.snapshot.digest == first.digest
        assert calls == 0
    finally:
        await shutdown_plugin_runtime_v2(second_app)


async def test_fresh_startup_persists_source_matching_actual_snapshot(db_session):
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    app = FastAPI()
    try:
        host = await initialize_plugin_runtime_v2(app, session_factory=factory)
        record, source = await exact_source(factory)
        assert record.desired_set.revision == source.revision == 1
        composition = compose_profile_sources_v2(
            desired_set=record.desired_set,
            bundles=(production_bundle_sources_v2().bundle,),
            profile_source=source,
            scope=ROOT,
        )
        actual = host.current_publication.snapshot
        expected = compose_profile_v2(
            composition.document,
            {manifest.plugin_id: manifest for manifest in composition.manifests},
            generation=actual.generation,
        )
        assert actual == expected
        assert all(
            not entry.enabled for entry in actual.entries if entry.entry_id in WORKSPACE_ENTRIES
        )
    finally:
        await shutdown_plugin_runtime_v2(app)


@pytest.mark.parametrize("reject", [False, True])
async def test_new_source_revision_disables_canvas_on_restart(db_session, monkeypatch, reject):
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    app = FastAPI()
    try:
        host = await initialize_plugin_runtime_v2(app, session_factory=factory)
        before = host.current_publication.snapshot
        canvas = next(
            entry
            for entry in before.entries
            if entry.module_ref == "builtin://memstack/agent/tool/canvas"
        )
        assert canvas.enabled
    finally:
        await shutdown_plugin_runtime_v2(app)
    record, source = await exact_source(factory)
    source = replace(
        source,
        revision=source.revision + 1,
        layers=(
            *source.layers,
            ProfileLayerV2(
                layer_id="user-disabled-canvas",
                kind=ProfileLayerKindV2.PROFILE,
                scope=ROOT,
                entries=(),
                replacements=(),
                disabled_entry_ids=(canvas.entry_id,),
            ),
        ),
    )
    source = replace(source, digest=profile_source_digest_v2(source))
    desired = replace(
        record.desired_set,
        revision=record.desired_set.revision + 1,
        profile_source=ProfileSourceReferenceV2(
            source_id=source.source_id, revision=source.revision, digest=source.digest
        ),
    )
    desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))
    async with factory() as db:
        await PlatformPluginProfileSourceRepositoryV2(db).record_source(
            scope=ROOT, source=source, expected_revision=source.revision - 1
        )
        await PlatformPluginDesiredBundleSetRepositoryV2(db).record_desired_set(
            scope=ROOT,
            desired_set=desired,
            expected_revision=record.desired_set.revision,
            actor_id="user",
        )
        await db.commit()
    restarted_app = FastAPI()
    if reject:
        from src.infrastructure.adapters.primary.web.startup import plugin_runtime_v2 as startup
        from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
            PlatformPluginRepositoryV2,
        )
        from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

        def reject_routes(**kwargs):
            raise RuntimeError("configured candidate rejected")

        monkeypatch.setattr(startup, "build_builtin_route_graph_v2", reject_routes)
        with pytest.raises(RuntimeV2Error, match="configured candidate rejected"):
            await initialize_plugin_runtime_v2(restarted_app, session_factory=factory)
        async with factory() as db:
            repository = PlatformPluginRepositoryV2(db)
            retained = await repository.last_good_distribution("python-api-v2")
            requested = await repository.latest_requested_distribution()
        assert retained["snapshot"]["digest"] == before.digest
        assert requested["snapshot"]["generation"] == before.generation + 1
        assert requested["snapshot"]["digest"] != before.digest
        return
    try:
        host = await initialize_plugin_runtime_v2(restarted_app, session_factory=factory)
        after = host.current_publication.snapshot
        assert after.generation == before.generation + 1
        assert after.digest != before.digest
        assert not next(
            entry for entry in after.entries if entry.entry_id == canvas.entry_id
        ).enabled
    finally:
        await shutdown_plugin_runtime_v2(restarted_app)


async def test_legacy_publication_without_desired_requires_explicit_migration(db_session):
    from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
        PlatformPluginRepositoryV2,
    )
    from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

    legacy_app = FastAPI()
    try:
        legacy = await initialize_plugin_runtime_v2(legacy_app)
        publication = legacy.current_publication
        assert publication is not None
    finally:
        await shutdown_plugin_runtime_v2(legacy_app)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as db:
        await PlatformPluginRepositoryV2(db).record_publication_and_receipt(
            publication, data_plane_id="python-api-v2"
        )
        await db.commit()
        assert (
            await PlatformPluginDesiredBundleSetRepositoryV2(db).current_desired_set(ROOT) is None
        )
    app = FastAPI()
    try:
        with pytest.raises(RuntimeV2Error) as failure:
            await initialize_plugin_runtime_v2(app, session_factory=factory)
        assert failure.value.code == "root_profile_migration_required"
        async with factory() as db:
            assert (
                await PlatformPluginDesiredBundleSetRepositoryV2(db).current_desired_set(ROOT)
                is None
            )
    finally:
        await shutdown_plugin_runtime_v2(app)
