"""Recovery evidence exported for the one-shot protocol-v1 retirement."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import (
    ApplyStatusV2,
    PublicationStatusV2,
    SnapshotApplyReceiptV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_v1_migration_repository import (
    PlatformPluginV1MigrationRepository,
    PlatformPluginV1MigrationRepositoryError,
    digest_payload_v1_to_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit
_ROOT = Path(__file__).resolve().parents[7]
_PROFILE = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFESTS = (_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",)


async def _publication(*, generation: int, version: int):
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE,
        manifest_paths=_MANIFESTS,
        generation=generation,
        version=version,
        nonce=f"migration-ready-{version}",
    )
    await host.close()
    return replace(
        publication,
        receipt=SnapshotApplyReceiptV2(
            status=ApplyStatusV2.ACK,
            requested_version=version,
            requested_digest=publication.snapshot.digest,
            applied_version=version,
            applied_digest=publication.snapshot.digest,
            error_code=None,
            error_message=None,
        ),
    )


async def test_export_last_globally_ready_v2_is_exact_and_ignores_newer_pending(
    db_session: AsyncSession,
) -> None:
    ready = await _publication(generation=1, version=1)
    pending = await _publication(generation=2, version=2)
    publication_repository = PlatformPluginRepositoryV2(db_session)
    await publication_repository.record_publication_and_receipt(
        ready,
        data_plane_id="python-api-v2",
    )
    readiness = await publication_repository.latest_publication_readiness()
    assert readiness is not None and readiness.status is PublicationStatusV2.READY
    await publication_repository.record_publication(pending)

    exported = await PlatformPluginV1MigrationRepository(db_session).export_globally_ready_v2()

    payload = exported.to_payload()
    assert exported.nonce == ready.envelope.nonce
    assert exported.requested_version == ready.envelope.version
    assert exported.snapshot_digest == ready.snapshot.digest
    assert payload["digest"] == digest_payload_v1_to_v2(
        {key: value for key, value in payload.items() if key != "digest"}
    )
    assert payload["distribution"]["snapshot"]["digest"] == ready.snapshot.digest  # type: ignore[index]


async def test_export_globally_ready_v2_requires_historical_ready_receipt(
    db_session: AsyncSession,
) -> None:
    pending = await _publication(generation=1, version=1)
    await PlatformPluginRepositoryV2(db_session).record_publication(pending)

    with pytest.raises(PlatformPluginV1MigrationRepositoryError) as error:
        await PlatformPluginV1MigrationRepository(db_session).export_globally_ready_v2()

    assert error.value.code == "migration_globally_ready_missing"
