"""Unit tests for the platform plugin control-plane transport."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers import platform_plugins
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginApplyStateModel,
    User,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository import (
    PlatformPluginRepository,
)
from src.infrastructure.plugins import compose_profile, parse_profile_document
from src.infrastructure.plugins.builtin_manifests import default_builtin_manifests
from src.infrastructure.plugins.profile import ProfileSnapshot


def compose_snapshot(profile_id: str) -> ProfileSnapshot:
    document = parse_profile_document(
        {
            "profile": {
                "id": profile_id,
                "layers": [{"id": "base", "plugins": [{"id": "workspace-runtime"}]}],
            }
        }
    )
    return compose_profile(document, default_builtin_manifests())


def make_client(db: AsyncSession) -> TestClient:
    app = FastAPI()
    app.include_router(platform_plugins.router)

    async def override_db() -> AsyncSession:
        return db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: User(
        id="platform-plugin-user",
        email="platform-plugin@example.com",
        hashed_password="hashed",
        full_name="Platform Plugin User",
        is_active=True,
    )
    return TestClient(app)


@pytest.mark.unit
async def test_snapshot_endpoint_returns_latest_snapshot(db_session: AsyncSession) -> None:
    repository = PlatformPluginRepository(db_session)
    latest_snapshot = compose_snapshot("router-test-latest")
    for version in (3, 7):
        snapshot = latest_snapshot if version == 7 else compose_snapshot("router-test-previous")
        await repository.record_snapshot(snapshot, version=version, nonce=f"nonce-{version}")
    await db_session.commit()

    response = make_client(db_session).get("/api/v1/platform-plugins/snapshot")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "version": 7,
        "nonce": "nonce-7",
        "profile_id": latest_snapshot.profile_id,
        "digest": latest_snapshot.digest,
        "payload": latest_snapshot.to_payload(),
    }


@pytest.mark.unit
async def test_snapshot_endpoint_returns_404_without_published_snapshot(
    db_session: AsyncSession,
) -> None:
    response = make_client(db_session).get("/api/v1/platform-plugins/snapshot")

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.unit
async def test_data_plane_ack_is_persisted(db_session: AsyncSession) -> None:
    repository = PlatformPluginRepository(db_session)
    snapshot = compose_snapshot("router-test-ack")
    await repository.record_snapshot(snapshot, version=9, nonce="nonce-9")
    await db_session.commit()

    response = make_client(db_session).post(
        "/api/v1/platform-plugins/data-plane-state",
        json={
            "data_plane_id": "desktop-local",
            "snapshot_digest": snapshot.digest,
            "requested_version": 9,
            "applied_version": 9,
            "status": "ack",
        },
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "ack"
    apply_state_result = await db_session.execute(
        select(PlatformPluginApplyStateModel).where(
            PlatformPluginApplyStateModel.data_plane_id == "desktop-local"
        )
    )
    apply_state = apply_state_result.scalar_one()
    assert apply_state is not None
    assert apply_state.snapshot_digest == snapshot.digest
    assert apply_state.requested_version == 9
    assert apply_state.applied_version == 9


@pytest.mark.unit
async def test_data_plane_nack_requires_reason(db_session: AsyncSession) -> None:
    repository = PlatformPluginRepository(db_session)
    snapshot = compose_snapshot("router-test-nack")
    await repository.record_snapshot(snapshot, version=11, nonce="nonce-11")
    await db_session.commit()

    response = make_client(db_session).post(
        "/api/v1/platform-plugins/data-plane-state",
        json={
            "data_plane_id": "desktop-local",
            "snapshot_digest": snapshot.digest,
            "requested_version": 11,
            "applied_version": 10,
            "status": "nack",
            "error_message": " ",
        },
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.unit
async def test_first_data_plane_nack_can_report_no_previously_applied_version(
    db_session: AsyncSession,
) -> None:
    repository = PlatformPluginRepository(db_session)
    snapshot = compose_snapshot("router-test-first-nack")
    await repository.record_snapshot(snapshot, version=13, nonce="nonce-13")
    await db_session.commit()

    response = make_client(db_session).post(
        "/api/v1/platform-plugins/data-plane-state",
        json={
            "data_plane_id": "desktop-local",
            "snapshot_digest": snapshot.digest,
            "requested_version": 13,
            "applied_version": 0,
            "status": "nack",
            "error_message": "runtime artifact is unavailable",
        },
    )

    assert response.status_code == status.HTTP_200_OK
    result = await db_session.execute(
        select(PlatformPluginApplyStateModel).where(
            PlatformPluginApplyStateModel.data_plane_id == "desktop-local"
        )
    )
    apply_state = result.scalar_one()
    assert apply_state.applied_version == 0
    assert apply_state.error_message == "runtime artifact is unavailable"


@pytest.mark.unit
async def test_shadow_rollout_endpoint_returns_summary_and_recent_evidence(
    db_session: AsyncSession,
) -> None:
    repository = PlatformPluginRepository(db_session)
    occurred_at = datetime.now(UTC)
    await repository.record_shadow_rollout_events(
        [
            {
                "capability": "agent_events",
                "event_name": "agent.before_request",
                "hook_name": "before_response",
                "scope_type": "tenant",
                "scope_id": "tenant-router",
                "equal": True,
                "legacy_payload": {"model": "demo"},
                "typed_payload": {"model": "demo"},
                "occurred_at": occurred_at,
            },
            {
                "capability": "agent_tools",
                "event_name": "agent.tool_generation",
                "hook_name": "tool_generation",
                "scope_type": "project",
                "scope_id": "project-router",
                "equal": False,
                "legacy_payload": {"demo": "Demo:Demo"},
                "typed_payload": {"demo": "Demo:Changed"},
                "occurred_at": occurred_at,
            },
        ]
    )
    await db_session.commit()

    response = make_client(db_session).get(
        "/api/v1/platform-plugins/shadow-rollout",
        params={"limit": 10},
    )

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    summary = {(row["capability"], row["event_name"]): row for row in payload["summary"]}
    events = {(row["capability"], row["event_name"]): row for row in payload["events"]}
    assert summary[("agent_events", "agent.before_request")]["equal"] is True
    assert summary[("agent_tools", "agent.tool_generation")]["equal"] is False
    assert events[("agent_events", "agent.before_request")]["scope_id"] == "tenant-router"
    assert events[("agent_tools", "agent.tool_generation")]["scope_id"] == "project-router"


@pytest.mark.unit
async def test_data_plane_receipt_rejects_stale_version_or_digest(
    db_session: AsyncSession,
) -> None:
    repository = PlatformPluginRepository(db_session)
    snapshot = compose_snapshot("router-test-conflict")
    await repository.record_snapshot(snapshot, version=12, nonce="nonce-12")
    await db_session.commit()
    client = make_client(db_session)

    stale_version = client.post(
        "/api/v1/platform-plugins/data-plane-state",
        json={
            "data_plane_id": "desktop-local",
            "snapshot_digest": snapshot.digest,
            "requested_version": 11,
            "applied_version": 11,
            "status": "ack",
        },
    )
    stale_digest = client.post(
        "/api/v1/platform-plugins/data-plane-state",
        json={
            "data_plane_id": "desktop-local",
            "snapshot_digest": "a" * 64,
            "requested_version": 12,
            "applied_version": 12,
            "status": "ack",
        },
    )
    incomplete_ack = client.post(
        "/api/v1/platform-plugins/data-plane-state",
        json={
            "data_plane_id": "desktop-local",
            "snapshot_digest": snapshot.digest,
            "requested_version": 12,
            "applied_version": 11,
            "status": "ack",
        },
    )

    assert stale_version.status_code == status.HTTP_409_CONFLICT
    assert stale_digest.status_code == status.HTTP_409_CONFLICT
    assert incomplete_ack.status_code == status.HTTP_409_CONFLICT
