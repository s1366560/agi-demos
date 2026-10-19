"""Real SQL revision fences, failed candidates and durable accepted-source reads."""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.application.services.plugin_instance_service_v2 import PluginInstanceServiceV2
from src.domain.model.plugins.generated_v2 import (
    ApplyStatusV2,
    BundleManifestV2,
    BundleReferenceV2,
    ProfileLayerKindV2,
    ProfileLayerV2,
    ScopeKindV2,
    ScopeV2,
    SnapshotApplyReceiptV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_source_repository_v2 import (
    PlatformPluginPublicationSourceRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_v2 import (
    PYTHON_API_DATA_PLANE_ID_V2,
    PlatformPluginPublicationPolicyV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.bundle_archive import VerifiedBundleArchiveV2
from src.infrastructure.plugins.v2.instance_configuration import revise_instance_source_v2
from src.infrastructure.plugins.v2.layer_composer import (
    bundle_manifest_digest_v2,
    desired_bundle_set_digest_v2,
    profile_source_digest_v2,
)
from src.infrastructure.plugins.v2.profile_composition_cache import ProfileCompositionCacheV2
from src.infrastructure.plugins.v2.protocol import control_envelope_v2
from src.infrastructure.plugins.v2.runtime_context import RuntimeV2Error
from src.tests.unit.infrastructure.plugins.v2.test_instance_configuration import SCOPE, fixture

pytestmark = pytest.mark.unit


@pytest.fixture
async def manager(db_session):
    snapshot, source, desired, key = fixture()
    root = ScopeV2(kind=ScopeKindV2.ROOT)
    bundle = BundleManifestV2(
        schema_version=2,
        bundle_id="test-instances",
        version="1.0.0",
        manifests=snapshot.manifests,
        layers=(
            ProfileLayerV2(
                layer_id="base",
                kind=ProfileLayerKindV2.BUNDLE,
                scope=root,
                entries=snapshot.entries,
                replacements=(),
                disabled_entry_ids=(),
            ),
        ),
        artifacts=(),
        digest="sha256:" + "0" * 64,
        signature=None,
        provenance=None,
    )
    bundle = replace(bundle, digest=bundle_manifest_digest_v2(bundle))
    source = replace(
        source,
        layers=(
            ProfileLayerV2(
                layer_id="profile",
                kind=ProfileLayerKindV2.PROFILE,
                scope=root,
                entries=(),
                replacements=(snapshot.entries[0],),
                disabled_entry_ids=(),
            ),
        ),
    )
    source = replace(source, digest=profile_source_digest_v2(source))
    desired = replace(
        desired,
        bundles=(
            BundleReferenceV2(
                bundle_id=bundle.bundle_id,
                version=bundle.version,
                digest=bundle.digest,
                source="builtin://test",
            ),
        ),
        profile_source=replace(desired.profile_source, digest=source.digest),
    )
    desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as session:
        await PlatformPluginProfileSourceRepositoryV2(session).record_source(
            scope=SCOPE, source=source, expected_revision=None
        )
        await PlatformPluginDesiredBundleSetRepositoryV2(session).record_desired_set(
            scope=SCOPE, desired_set=desired, expected_revision=None, actor_id="fixture"
        )
        await session.commit()
    loader = AsyncMock(
        return_value=VerifiedBundleArchiveV2(manifest=bundle, artifacts={}, source="builtin://test")
    )
    result = {"accept": True, "applied": None}

    async def publish():
        current = await service.configuration()
        async with factory() as session:
            repo = PlatformPluginRepositoryV2(session, scope=SCOPE)
            version = await repo.allocate_publication_version()
            envelope = control_envelope_v2(current.snapshot, version=version)
            publication = await repo.record_requested_distribution(
                current.snapshot,
                envelope,
                policy=PlatformPluginPublicationPolicyV2(
                    required_data_plane_ids=(PYTHON_API_DATA_PLANE_ID_V2,)
                ),
            )
            await PlatformPluginPublicationSourceRepositoryV2(session).record(
                scope=SCOPE, publication_id=publication.id, desired_set=current.desired
            )
            if result["accept"]:
                result["applied"] = (version, current.snapshot.digest)
            applied = result["applied"]
            await repo.record_data_plane_receipt(
                data_plane_id=PYTHON_API_DATA_PLANE_ID_V2,
                nonce=envelope.nonce,
                receipt=SnapshotApplyReceiptV2(
                    status=ApplyStatusV2.ACK if result["accept"] else ApplyStatusV2.NACK,
                    requested_version=version,
                    requested_digest=current.snapshot.digest,
                    applied_version=None if applied is None else applied[0],
                    applied_digest=None if applied is None else applied[1],
                    error_code=None if result["accept"] else "candidate_failed",
                    error_message=None if result["accept"] else "candidate failed",
                ),
            )
            await session.commit()

    service = PluginInstanceServiceV2(
        session_factory=factory,
        initializer=AsyncMock(),
        load_bundle=loader,
        publish=publish,
        scope=SCOPE,
        composition_cache=ProfileCompositionCacheV2(),
    )
    await publish()
    return service, key, result


async def test_cached_composition_still_reloads_bundle_authority(manager):
    service, _, _ = manager
    await service.effective_snapshot()
    service._load_bundle.side_effect = RuntimeV2Error("bundle_revoked", "bundle revoked")
    with pytest.raises(RuntimeV2Error, match="revoked"):
        await service.effective_snapshot()


async def test_save_applies_and_stale_revision_cannot_overwrite(manager):
    service, key, _ = manager
    first = await service.view()
    assert first["revision"] == 1 and first["publication"]["status"] == "ready"
    second = await service.apply(
        actor_id="owner", expected_revision=1, changes=[{"entry_id": key, "enabled": False}]
    )
    assert second["revision"] == 2 and second["publication"]["status"] == "ready"
    assert (
        next(row for row in second["instances"] if row["entry_id"] == key)["state"]["status"]
        == "disabled"
    )
    with pytest.raises(RuntimeV2Error, match="revision changed"):
        await service.apply(
            actor_id="owner", expected_revision=1, changes=[{"entry_id": key, "enabled": True}]
        )
    assert (await service.view())["revision"] == 2


async def test_failed_publication_preserves_exact_accepted_source_after_service_restart(manager):
    service, key, result = manager
    result["accept"] = False
    failed = await service.apply(
        actor_id="owner", expected_revision=1, changes=[{"entry_id": key, "enabled": False}]
    )
    assert failed["revision"] == 2 and failed["publication"]["status"] == "degraded"
    assert (
        next(row for row in failed["instances"] if row["entry_id"] == key)["state"]["status"]
        == "failed"
    )
    restarted = PluginInstanceServiceV2(
        session_factory=service._sessions,
        initializer=AsyncMock(),
        load_bundle=service._load_bundle,
        publish=AsyncMock(side_effect=AssertionError("must use durable accepted source")),
        scope=SCOPE,
    )
    effective = await restarted.effective_snapshot()
    assert effective.generation == 1
    assert next(row for row in effective.entries if row.entry_id == key).enabled


async def test_invalid_config_rejects_candidate_without_saving(manager):
    service, key, _ = manager
    with pytest.raises(RuntimeV2Error):
        await service.apply(
            actor_id="owner",
            expected_revision=1,
            changes=[{"entry_id": key, "config": {"unknown": "bad"}}],
        )
    assert (await service.view())["revision"] == 1


async def test_permission_revoked_during_candidate_preparation_cannot_save(manager):
    service, key, _ = manager
    authorize = AsyncMock(side_effect=RuntimeV2Error("scope_write_forbidden", "revoked"))
    with pytest.raises(RuntimeV2Error, match="revoked"):
        await service.apply(
            actor_id="owner",
            expected_revision=1,
            changes=[{"entry_id": key, "enabled": False}],
            authorize=authorize,
        )
    authorize.assert_awaited_once()
    assert (await service.view())["revision"] == 1


async def test_unavailable_renderer_artifact_is_rejected_before_save_or_publish(manager):
    service, key, _ = manager
    snapshot = (await service.configuration()).snapshot
    config = dict(next(row for row in snapshot.entries if row.entry_id == key).config)
    config["contributions"] = [
        {
            "kind": "route",
            "id": "unavailable",
            "order": 10,
            "payload": {"schema_version": 1, "artifact_refs": ["unknown"]},
        }
    ]
    with pytest.raises(RuntimeV2Error, match="not compiled"):
        await service.apply(
            actor_id="owner", expected_revision=1, changes=[{"entry_id": key, "config": config}]
        )
    assert (await service.view())["revision"] == 1


@pytest.mark.parametrize("invalid", ["wrong-kind", "duplicate-artifact"])
async def test_renderer_contract_mismatch_is_rejected_before_save_or_publish(manager, invalid):
    service, key, _ = manager
    snapshot = (await service.configuration()).snapshot
    config = dict(next(row for row in snapshot.entries if row.entry_id == key).config)
    original = config["contributions"][0]
    config["contributions"] = [
        {**original, "kind": "route"} if invalid == "wrong-kind" else original,
    ]
    if invalid == "duplicate-artifact":
        config["contributions"].append({**original, "id": "duplicate-artifact-owner"})
    with pytest.raises(RuntimeV2Error) as caught:
        await service.apply(
            actor_id="owner", expected_revision=1, changes=[{"entry_id": key, "config": config}]
        )
    assert caught.value.code == (
        "renderer_artifact_kind_mismatch"
        if invalid == "wrong-kind"
        else "renderer_artifact_conflict"
    )
    assert (await service.view())["revision"] == 1


@pytest.mark.parametrize("read_method", ["effective_snapshot", "view"])
async def test_deployment_upgrade_reconciles_new_desired_before_reading_old_source(
    manager, read_method
):
    service, key, _ = manager
    current = await service.configuration()
    source, desired = revise_instance_source_v2(
        source=current.source,
        desired=current.desired,
        snapshot=current.snapshot,
        scope=SCOPE,
        expected_revision=1,
        changes=[{"entry_id": key, "enabled": False}],
    )
    # Deployment upgrades use these repositories while the API process is stopped.
    async with service._sessions() as session:
        await PlatformPluginProfileSourceRepositoryV2(session).record_source(
            scope=SCOPE,
            source=source,
            expected_revision=1,
        )
        await PlatformPluginDesiredBundleSetRepositoryV2(session).record_desired_set(
            scope=SCOPE,
            desired_set=desired,
            expected_revision=1,
            actor_id="deployment",
        )
        await session.commit()
    await getattr(service, read_method)()
    view = await service.view()
    assert view["publication"]["status"] == "ready"
    assert view["revision"] == 2
    assert (
        next(row for row in view["instances"] if row["entry_id"] == key)["state"]["status"]
        == "disabled"
    )
