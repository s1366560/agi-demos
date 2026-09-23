"""Local cleanup excludes builtin/business data, fences active calls and restores backups."""

from dataclasses import replace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select

from src.application.services.marketplace_legacy_cleanup_v2 import (
    MarketplaceLegacyCleanupV2,
    require_local_development,
)
from src.domain.model.plugins.generated_v2 import BundleReferenceV2, ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginPackageModel,
    PlatformPluginQuotaUsageModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_desired_bundle_repository_v2 import (
    PlatformPluginDesiredBundleSetRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.plugins.v2.layer_composer import desired_bundle_set_digest_v2
from src.infrastructure.plugins.v2.production_bundle import production_bundle_sources_v2
from src.infrastructure.plugins.v2.protocol import bundle_manifest_v2_to_payload
from src.tests.unit.application.services.test_plugin_marketplace_install_service import (
    _signed_bundle,
)

pytestmark = pytest.mark.unit


@pytest.fixture
async def setup(db_session):
    bundle, _ = _signed_bundle(Ed25519PrivateKey.generate())
    repository = PlatformPluginGovernanceRepository(db_session)
    await repository.upsert_package(
        plugin_id=bundle.bundle_id,
        version=bundle.version,
        publisher="fixture",
        artifact_digest="a" * 64,
        artifact_registry="https://registry.example",
        artifact_repository="fixture",
        oci_manifest_digest="b" * 64,
        manifest=bundle_manifest_v2_to_payload(bundle),
        signature={},
        provenance={},
        security_scan_status="passed",
    )
    await repository.grant_permission(
        plugin_id=bundle.bundle_id,
        permission="tools.execute",
        scope_type="tenant",
        scope_id="old-tenant",
    )
    await db_session.commit()
    service = MarketplaceLegacyCleanupV2(
        db_session, database_url="postgresql://localhost/local-test", environment="development"
    )
    return service, bundle, repository


@pytest.mark.parametrize(
    "url,environment",
    [
        ("postgresql://remote.example/prod", "development"),
        ("postgresql://localhost/prod", "production"),
    ],
)
def test_cleanup_refuses_other_deployments(url, environment):
    with pytest.raises(ValueError, match="local development"):
        require_local_development(url, environment)


async def test_dry_run_then_exact_backup_cleanup_and_restore(setup, db_session, tmp_path):
    service, bundle, repository = setup
    plan = await service.plan()
    assert plan["blockers"] == [] and plan["files"] == []
    assert await repository.get_package_version(bundle.bundle_id, bundle.version)
    backup = tmp_path / "backup.json"
    result = await service.apply(plan["digest"], backup)
    assert result["deleted"]["platform_plugin_packages"] == 1
    assert result["deleted"]["platform_plugin_permissions"] == 1
    assert backup.stat().st_mode & 0o777 == 0o600
    assert await repository.get_package_version(bundle.bundle_id, bundle.version) is None
    restored = await service.restore(backup)
    assert restored["platform_plugin_packages"] == 1
    assert await repository.get_package_version(bundle.bundle_id, bundle.version)


async def test_changed_plan_and_existing_backup_fail_closed(setup, db_session, tmp_path):
    service, bundle, repository = setup
    plan = await service.plan()
    await repository.grant_permission(
        plugin_id=bundle.bundle_id, permission="changed", scope_type="tenant", scope_id="old-tenant"
    )
    with pytest.raises(ValueError, match="changed"):
        await service.apply(plan["digest"], tmp_path / "backup.json")
    current = await service.plan()
    backup = tmp_path / "existing.json"
    backup.write_text("preserve")
    with pytest.raises(FileExistsError):
        await service.apply(current["digest"], backup)
    assert backup.read_text() == "preserve"
    assert await repository.get_package_version(bundle.bundle_id, bundle.version)


async def test_inflight_calls_and_current_desired_block_before_deletion(
    setup, db_session, tmp_path
):
    service, bundle, repository = setup
    db_session.add(
        PlatformPluginQuotaUsageModel(
            plugin_id=bundle.bundle_id,
            concurrent_calls=1,
            requests_in_window=1,
            output_bytes=0,
            storage_bytes=0,
            usd_micros=0,
        )
    )
    desired = production_bundle_sources_v2().desired_set
    desired = replace(
        desired,
        bundles=(
            *desired.bundles,
            BundleReferenceV2(
                bundle_id=bundle.bundle_id,
                version=bundle.version,
                digest=bundle.digest,
                source=f"marketplace://{bundle.bundle_id}/{bundle.version}",
            ),
        ),
    )
    desired = replace(desired, digest=desired_bundle_set_digest_v2(desired))
    await PlatformPluginDesiredBundleSetRepositoryV2(db_session).record_desired_set(
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
        desired_set=desired,
        expected_revision=None,
        actor_id="fixture",
    )
    await db_session.commit()
    plan = await service.plan()
    assert {row["kind"] for row in plan["blockers"]} == {"desired_reference", "in_flight_calls"}
    with pytest.raises(ValueError, match="drain"):
        await service.apply(plan["digest"], tmp_path / "blocked.json")
    assert not (tmp_path / "blocked.json").exists()
    assert await repository.get_package_version(bundle.bundle_id, bundle.version)


async def test_builtin_catalog_is_preserved(setup, db_session, tmp_path):
    service, _bundle, repository = setup
    builtin = production_bundle_sources_v2().bundle
    await repository.upsert_package(
        plugin_id=builtin.bundle_id,
        version=builtin.version,
        publisher="builtin",
        artifact_digest="c" * 64,
        artifact_registry="builtin",
        artifact_repository="builtin",
        oci_manifest_digest="d" * 64,
        manifest=bundle_manifest_v2_to_payload(builtin),
        signature={},
        provenance={},
        security_scan_status="passed",
    )
    await db_session.commit()
    plan = await service.plan()
    await service.apply(plan["digest"], tmp_path / "backup.json")
    assert await db_session.scalar(
        select(PlatformPluginPackageModel).where(
            PlatformPluginPackageModel.plugin_id == builtin.bundle_id
        )
    )


async def test_retirement_never_fabricates_ack_and_preserves_profile_source(
    setup, db_session, tmp_path, monkeypatch
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from src.application.services import marketplace_legacy_retirement_v2 as module

    cleanup, _, _ = setup
    source = production_bundle_sources_v2()
    scope = ScopeV2(kind=ScopeKindV2.SESSION, tenant_id="t", project_id="p", session_id="s")
    desired = replace(
        source.desired_set,
        bundles=(replace(source.desired_set.bundles[0], digest="sha256:" + "a" * 64),),
    )
    record = SimpleNamespace(scope=scope, desired_set=desired)
    repository = SimpleNamespace(
        current_desired_set=AsyncMock(return_value=record), record_desired_set=AsyncMock()
    )
    monkeypatch.setattr(
        module, "PlatformPluginDesiredBundleSetRepositoryV2", lambda _db: repository
    )
    cleanup.db = SimpleNamespace(
        get=AsyncMock(
            return_value=SimpleNamespace(
                scope_kind="session", tenant_id="t", project_id="p", session_id="s"
            )
        ),
        commit=AsyncMock(),
    )
    cleanup.plan = AsyncMock(
        return_value={"digest": "exact", "blockers": [{"kind": "applied_reference", "id": "old"}]}
    )
    publication = SimpleNamespace(accepted=False, envelope=SimpleNamespace(version=2))
    publish = AsyncMock(return_value=publication)
    with pytest.raises(ValueError, match="not acknowledged"):
        await module.retire_legacy_applied_scopes(
            cleanup, expected_digest="exact", backup_path=tmp_path / "backup.json", publish=publish
        )
    assert (tmp_path / "backup.json").exists()
    replacement = repository.record_desired_set.call_args.kwargs["desired_set"]
    assert replacement.profile_source == desired.profile_source
    assert replacement.bundles == source.desired_set.bundles
    publish.assert_awaited_once_with(scope)


async def test_cleanup_preserves_new_scoped_installations(setup, db_session):
    from src.infrastructure.adapters.secondary.persistence.plugin_marketplace_models_v3 import (
        MarketplaceRecordV3,
    )

    service, bundle, _ = setup
    db_session.add(
        MarketplaceRecordV3(
            id="new-scoped",
            tenant_id="new-tenant",
            project_id="",
            kind="signed_installation",
            record_key=bundle.bundle_id,
            payload={"status": "enabled"},
        )
    )
    await db_session.commit()
    plan = await service.plan()
    assert not plan["tables"]["platform_plugin_packages"]
    assert not plan["tables"]["platform_plugin_permissions"]


async def test_maintenance_runtime_never_starts_global_application_services(db_session):
    from src.application.services.marketplace_legacy_retirement_v2 import maintenance_scoped_runtime
    from src.infrastructure.plugins.v2.builtin_modules import RUNTIME_BOUNDARY_MODULE_V2
    from src.infrastructure.plugins.v2.sandbox_runtime import SANDBOX_RUNTIME_MODULE_V2

    runtime, host = await maintenance_scoped_runtime(db_session)
    try:
        assert {entry.module_ref for entry in host.current_distribution.snapshot.entries} == {
            RUNTIME_BOUNDARY_MODULE_V2,
            SANDBOX_RUNTIME_MODULE_V2,
        }
    finally:
        await runtime.close()
        await host.close()
