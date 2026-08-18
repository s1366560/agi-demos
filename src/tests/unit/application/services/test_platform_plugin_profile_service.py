import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.platform_plugin_profile_service import (
    PlatformPluginProfileService,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository import (
    PlatformPluginRepository,
)
from src.infrastructure.plugins import CapabilityRegistry, compose_profile, parse_profile_document
from src.infrastructure.plugins.builtin_manifests import default_builtin_manifests
from src.infrastructure.plugins.compatibility import activate_profile_snapshot


@pytest.mark.unit
async def test_publish_records_snapshot_audit_and_ack(db_session: AsyncSession) -> None:
    repository = PlatformPluginRepository(db_session)
    service = PlatformPluginProfileService(repository)

    publication = await service.publish(version=4, nonce="nonce-4", actor_id="admin-1")
    await service.record_ack(publication, data_plane_id="desktop-local", applied_version=4)

    assert publication.snapshot.profile_id == "memstack-default"
    assert publication.envelope.version == 4
    snapshot = await repository.get_snapshot(4)
    assert snapshot is not None
    assert snapshot.nonce == "nonce-4"


@pytest.mark.unit
async def test_nack_requires_reason_and_retains_applied_version(db_session: AsyncSession) -> None:
    repository = PlatformPluginRepository(db_session)
    service = PlatformPluginProfileService(repository)
    publication = await service.publish(version=5)

    with pytest.raises(ValueError, match="error_message is required"):
        await service.record_nack(
            publication,
            data_plane_id="desktop-local",
            applied_version=4,
            error_message=" ",
        )
    await service.record_nack(
        publication,
        data_plane_id="desktop-local",
        applied_version=4,
        error_message="validation failed",
    )


@pytest.mark.unit
def test_snapshot_activation_is_reversible() -> None:
    snapshot = compose_profile(
        parse_profile_document(
            {
                "profile": {
                    "id": "activation-test",
                    "layers": [{"id": "base", "plugins": [{"id": "workspace-runtime"}]}],
                }
            }
        ),
        default_builtin_manifests(),
    )
    registry = CapabilityRegistry()
    dispose = activate_profile_snapshot(snapshot, registry)

    assert registry.list_capabilities("workspace-runtime")
    dispose()
    assert registry.list_capabilities("workspace-runtime") == ()


@pytest.mark.unit
def test_snapshot_carries_signed_call_pricing_to_every_data_plane() -> None:
    snapshot = compose_profile(
        parse_profile_document(
            {
                "profile": {
                    "id": "billing-test",
                    "layers": [{"id": "marketplace", "plugins": [{"id": "third-party-tool"}]}],
                }
            }
        ),
        {
            "third-party-tool": {
                "schemaVersion": 1,
                "id": "third-party-tool",
                "version": "1.0.0",
                "runtime": "wasm",
                "trust": "signed",
                "provides": [{"kind": "tool", "id": "demo"}],
                "activation": {"quotas": {"max_monthly_usd": 0.01}},
                "billing": {"usdMicrosPerCall": 1_000},
            }
        },
    )

    row = next(item for item in snapshot.rows if item.manifest.id == "third-party-tool")
    assert row.to_payload()["billing"] == {"usd_micros_per_call": 1_000}
