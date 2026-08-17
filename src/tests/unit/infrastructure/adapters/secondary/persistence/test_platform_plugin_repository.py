import pytest

from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginApplyStateModel,
    PlatformPluginCatalogModel,
    PlatformPluginDesiredStateModel,
    PlatformPluginSnapshotModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository import (
    PlatformPluginRepository,
)
from src.infrastructure.plugins.builtin_manifests import workspace_runtime_manifest


@pytest.mark.unit
async def test_catalog_snapshot_desired_and_apply_state_roundtrip(db_session):
    repository = PlatformPluginRepository(db_session)
    manifest = workspace_runtime_manifest()

    catalog_row = await repository.upsert_catalog_manifest(manifest)
    desired = await repository.set_desired_state(
        plugin_id=manifest.id,
        enabled=True,
        config={"mode": "default"},
    )

    assert isinstance(catalog_row, PlatformPluginCatalogModel)
    assert isinstance(desired, PlatformPluginDesiredStateModel)
    assert catalog_row.manifest["id"] == manifest.id
    assert desired.revision == 1

    desired_again = await repository.set_desired_state(
        plugin_id=manifest.id,
        enabled=False,
        config={},
    )
    assert desired_again.revision == 2


@pytest.mark.unit
async def test_snapshot_apply_and_audit_rows_are_persisted(db_session):
    repository = PlatformPluginRepository(db_session)
    snapshot = compose_default_snapshot()
    snapshot_row = await repository.record_snapshot(snapshot, version=3)
    audit_row = await repository.record_capability_transition(
        snapshot_digest=snapshot.digest,
        plugin_id="workspace-runtime",
        action="register",
        capability_kind="hook",
        capability_id="before_response",
        actor_id="user-1",
        before_state={},
        after_state={"owner": "workspace-runtime"},
    )
    apply_row = await repository.record_apply_state(
        data_plane_id="desktop-local-1",
        snapshot_digest=snapshot.digest,
        requested_version=3,
        applied_version=2,
        status="nack",
        error_message="invalid capability",
    )

    assert isinstance(snapshot_row, PlatformPluginSnapshotModel)
    assert isinstance(audit_row, object)
    assert isinstance(apply_row, PlatformPluginApplyStateModel)
    assert apply_row.status == "nack"


def compose_default_snapshot():
    from src.infrastructure.plugins import compose_profile, parse_profile_document
    from src.infrastructure.plugins.builtin_manifests import default_builtin_manifests

    document = parse_profile_document(
        {
            "profile": {
                "id": "repository-test",
                "layers": [
                    {"id": "base", "plugins": [{"id": "workspace-runtime"}]},
                ],
            }
        }
    )
    return compose_profile(document, default_builtin_manifests())
