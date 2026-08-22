"""Protocol-v2 platform plugin distribution transport tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers import platform_plugins
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2ApplyStateModel,
    User,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginPublicationPolicyV2,
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

_ROOT = Path(__file__).resolve().parents[4]
_PROFILE = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFESTS = (_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",)


async def _publication():
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE,
        manifest_paths=_MANIFESTS,
        generation=5,
        version=5,
        nonce="transport-v2-5",
    )
    distribution = host.current_distribution
    assert distribution is not None
    await host.close()
    return publication, distribution.to_payload()


def _client(db: AsyncSession, *, superuser: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(platform_plugins.router)

    async def override_db() -> AsyncSession:
        return db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: User(
        id="plugin-v2-user",
        email="plugin-v2@example.com",
        hashed_password="hashed",
        full_name="Plugin V2 User",
        is_active=True,
        is_superuser=superuser,
    )
    return TestClient(app)


@pytest.mark.unit
async def test_v2_distribution_endpoint_returns_complete_snapshot(
    db_session: AsyncSession,
) -> None:
    publication, distribution = await _publication()
    await PlatformPluginRepositoryV2(db_session).record_publication(publication)
    await db_session.commit()

    response = _client(db_session).get("/api/v1/platform-plugins/v2/distribution")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"schema_version": 2, **distribution}


@pytest.mark.unit
async def test_v2_distribution_endpoint_allows_authenticated_non_admin(
    db_session: AsyncSession,
) -> None:
    publication, distribution = await _publication()
    await PlatformPluginRepositoryV2(db_session).record_publication(publication)
    await db_session.commit()

    response = _client(db_session, superuser=False).get("/api/v1/platform-plugins/v2/distribution")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"schema_version": 2, **distribution}


@pytest.mark.unit
@pytest.mark.parametrize(
    ("method", "path"),
    (
        ("post", "/api/v1/platform-plugins/v2/data-plane-state"),
        ("get", "/api/v1/platform-plugins/v2/readiness"),
        ("get", "/api/v1/platform-plugins/v2/publications/unknown/readiness"),
        ("post", "/api/v1/platform-plugins/v2/publications/republish-last-ready"),
    ),
)
async def test_v2_management_endpoints_require_admin(
    db_session: AsyncSession,
    method: str,
    path: str,
) -> None:
    response = _client(db_session, superuser=False).request(method, path, json={})

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.unit
async def test_v2_distribution_endpoint_returns_404_without_publication(
    db_session: AsyncSession,
) -> None:
    response = _client(db_session).get("/api/v1/platform-plugins/v2/distribution")

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.unit
async def test_v2_receipt_endpoint_records_exact_publication(
    db_session: AsyncSession,
) -> None:
    publication, _distribution = await _publication()
    await PlatformPluginRepositoryV2(db_session).record_publication(
        publication,
        policy=PlatformPluginPublicationPolicyV2(
            required_data_plane_ids=("desktop-sidecar",),
            ack_deadline_seconds=30,
        ),
    )
    await db_session.commit()
    receipt = publication.receipt
    payload = {
        "schema_version": 2,
        "data_plane_id": "desktop-sidecar",
        "nonce": publication.envelope.nonce,
        "receipt": {
            "status": receipt.status.value,
            "requested_version": receipt.requested_version,
            "requested_digest": receipt.requested_digest,
            "applied_version": receipt.applied_version,
            "applied_digest": receipt.applied_digest,
            "error_code": receipt.error_code,
            "error_message": receipt.error_message,
        },
    }

    response = _client(db_session).post(
        "/api/v1/platform-plugins/v2/data-plane-state",
        json=payload,
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == payload
    state = await db_session.scalar(select(PlatformPluginV2ApplyStateModel))
    assert state is not None
    assert state.data_plane_id == "desktop-sidecar"
    assert state.status == "ack"


@pytest.mark.unit
async def test_v2_receipt_endpoint_rejects_v1_with_stable_409(
    db_session: AsyncSession,
) -> None:
    response = _client(db_session).post(
        "/api/v1/platform-plugins/v2/data-plane-state",
        json={
            "schema_version": 1,
            "data_plane_id": "legacy-sidecar",
            "snapshot_digest": "a" * 64,
            "requested_version": 1,
            "applied_version": 1,
            "status": "ack",
        },
    )

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["detail"]["code"] == "plugin_protocol_incompatible"


@pytest.mark.unit
async def test_v2_receipt_endpoint_rejects_unknown_publication(
    db_session: AsyncSession,
) -> None:
    response = _client(db_session).post(
        "/api/v1/platform-plugins/v2/data-plane-state",
        json={
            "schema_version": 2,
            "data_plane_id": "desktop-sidecar",
            "nonce": "missing-publication",
            "receipt": {
                "status": "nack",
                "requested_version": 9,
                "requested_digest": "a" * 64,
                "applied_version": None,
                "applied_digest": None,
                "error_code": "staging_failed",
                "error_message": "rejected",
            },
        },
    )

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["detail"]["code"] == "plugin_publication_unknown"


@pytest.mark.unit
async def test_v2_receipt_endpoint_rejects_inconsistent_ack(
    db_session: AsyncSession,
) -> None:
    publication, _distribution = await _publication()
    await PlatformPluginRepositoryV2(db_session).record_publication(
        publication,
        policy=PlatformPluginPublicationPolicyV2(
            required_data_plane_ids=("desktop-sidecar",),
            ack_deadline_seconds=30,
        ),
    )
    await db_session.commit()

    response = _client(db_session).post(
        "/api/v1/platform-plugins/v2/data-plane-state",
        json={
            "schema_version": 2,
            "data_plane_id": "desktop-sidecar",
            "nonce": publication.envelope.nonce,
            "receipt": {
                "status": "ack",
                "requested_version": publication.envelope.version,
                "requested_digest": publication.snapshot.digest,
                "applied_version": None,
                "applied_digest": None,
                "error_code": None,
                "error_message": None,
            },
        },
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert response.json()["detail"]["code"] == "plugin_protocol_invalid"


@pytest.mark.unit
async def test_v2_readiness_endpoint_returns_required_plane_progress(
    db_session: AsyncSession,
) -> None:
    publication, _distribution = await _publication()
    await PlatformPluginRepositoryV2(db_session).record_publication(
        publication,
        policy=PlatformPluginPublicationPolicyV2(
            required_data_plane_ids=("python-api-v2", "rust-server"),
            ack_deadline_seconds=30,
        ),
    )
    await db_session.commit()

    response = _client(db_session).get("/api/v1/platform-plugins/v2/readiness")

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["schema_version"] == 2
    assert payload["nonce"] == publication.envelope.nonce
    assert payload["status"] == "reconciling"
    assert payload["required_data_plane_ids"] == ["python-api-v2", "rust-server"]
    assert [plane["data_plane_id"] for plane in payload["data_planes"]] == [
        "python-api-v2",
        "rust-server",
    ]


@pytest.mark.unit
async def test_v2_receipt_endpoint_rejects_unregistered_ephemeral_plane(
    db_session: AsyncSession,
) -> None:
    publication, _distribution = await _publication()
    await PlatformPluginRepositoryV2(db_session).record_publication(
        publication,
        policy=PlatformPluginPublicationPolicyV2(
            required_data_plane_ids=("rust-server",),
            ack_deadline_seconds=30,
        ),
    )
    await db_session.commit()
    receipt = publication.receipt

    response = _client(db_session).post(
        "/api/v1/platform-plugins/v2/data-plane-state",
        json={
            "schema_version": 2,
            "data_plane_id": "web-ephemeral-session",
            "nonce": publication.envelope.nonce,
            "receipt": {
                "status": receipt.status.value,
                "requested_version": receipt.requested_version,
                "requested_digest": receipt.requested_digest,
                "applied_version": receipt.applied_version,
                "applied_digest": receipt.applied_digest,
                "error_code": receipt.error_code,
                "error_message": receipt.error_message,
            },
        },
    )

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["detail"]["code"] == "plugin_data_plane_unregistered"


@pytest.mark.unit
async def test_v2_republish_endpoint_creates_auditable_new_publication(
    db_session: AsyncSession,
) -> None:
    publication, _distribution = await _publication()
    await PlatformPluginRepositoryV2(db_session).record_publication_and_receipt(
        publication,
        data_plane_id="python-api-v2",
    )
    await db_session.commit()
    client = _client(db_session)
    client.app.state.platform_plugin_publication_policy_v2 = PlatformPluginPublicationPolicyV2(
        required_data_plane_ids=("python-api-v2", "rust-server"),
        ack_deadline_seconds=30,
    )

    response = client.post("/api/v1/platform-plugins/v2/publications/republish-last-ready")

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["requested_version"] == publication.envelope.version + 1
    assert payload["snapshot_digest"] == publication.snapshot.digest
    assert payload["republished_from_nonce"] == publication.envelope.nonce
    assert payload["required_data_plane_ids"] == ["python-api-v2", "rust-server"]
    assert payload["status"] == "reconciling"


@pytest.mark.unit
async def test_v2_republish_endpoint_rejects_without_globally_ready_snapshot(
    db_session: AsyncSession,
) -> None:
    response = _client(db_session).post(
        "/api/v1/platform-plugins/v2/publications/republish-last-ready"
    )

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["detail"] == {
        "code": "plugin_globally_ready_missing",
        "reason": "globally_ready_not_found",
        "message": "Plugin protocol receipt conflicts with control-plane state",
    }


@pytest.mark.unit
async def test_v2_republish_endpoint_reconciles_required_local_python_plane(
    db_session: AsyncSession,
) -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE,
        manifest_paths=_MANIFESTS,
        generation=5,
        version=5,
        nonce="transport-local-republish-5",
    )
    await PlatformPluginRepositoryV2(db_session).record_publication_and_receipt(
        publication,
        data_plane_id="python-api-v2",
    )
    await db_session.commit()
    client = _client(db_session)
    client.app.state.platform_plugin_runtime_v2 = host
    client.app.state.platform_plugin_publication_policy_v2 = (
        PlatformPluginPublicationPolicyV2.local_default()
    )

    response = client.post("/api/v1/platform-plugins/v2/publications/republish-last-ready")

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["requested_version"] == 6
    assert payload["status"] == "ready"
    assert payload["data_planes"][0]["status"] == "ack"
    assert host.current_publication is not None
    assert host.current_publication.envelope.version == 6
    await host.close()


@pytest.mark.unit
async def test_v2_readiness_endpoint_persists_timeout_and_accepts_late_recovery(
    db_session: AsyncSession,
) -> None:
    publication, _distribution = await _publication()
    repository = PlatformPluginRepositoryV2(db_session)
    await repository.record_publication(
        publication,
        policy=PlatformPluginPublicationPolicyV2(
            required_data_plane_ids=("desktop-sidecar",),
            ack_deadline_seconds=30,
        ),
        now=datetime.now(UTC) - timedelta(seconds=31),
    )
    await db_session.commit()
    client = _client(db_session)

    timed_out = client.get("/api/v1/platform-plugins/v2/readiness")

    assert timed_out.status_code == status.HTTP_200_OK
    assert timed_out.json()["status"] == "degraded"

    receipt = publication.receipt
    recovered = client.post(
        "/api/v1/platform-plugins/v2/data-plane-state",
        json={
            "schema_version": 2,
            "data_plane_id": "desktop-sidecar",
            "nonce": publication.envelope.nonce,
            "receipt": {
                "status": receipt.status.value,
                "requested_version": receipt.requested_version,
                "requested_digest": receipt.requested_digest,
                "applied_version": receipt.applied_version,
                "applied_digest": receipt.applied_digest,
                "error_code": receipt.error_code,
                "error_message": receipt.error_message,
            },
        },
    )
    assert recovered.status_code == status.HTTP_200_OK
    readiness = client.get("/api/v1/platform-plugins/v2/readiness")
    assert readiness.status_code == status.HTTP_200_OK
    assert readiness.json()["status"] == "ready"
