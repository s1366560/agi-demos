"""Unit tests for the platform plugin control-plane transport."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers import platform_plugins
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginApplyStateEventModel,
    PlatformPluginApplyStateModel,
    User,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository import (
    PlatformPluginRepository,
)
from src.infrastructure.plugins import compose_profile, parse_profile_document
from src.infrastructure.plugins.builtin_manifests import default_builtin_manifests
from src.infrastructure.plugins.cutover_readiness import (
    evaluate_platform_plugin_cutover_readiness,
    evaluate_rollback_drill_readiness,
)
from src.infrastructure.plugins.profile import ProfileSnapshot
from src.infrastructure.plugins.rollout_readiness import (
    ShadowRolloutReadiness,
    evaluate_shadow_rollout_readiness,
)


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


def make_client(db: AsyncSession, *, superuser: bool = True) -> TestClient:
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
        is_superuser=superuser,
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
async def test_shadow_rollout_readiness_requires_complete_zero_diff_scope_coverage(
    db_session: AsyncSession,
) -> None:
    repository = PlatformPluginRepository(db_session)
    occurred_at = datetime.now(UTC)
    records: list[dict[str, object]] = []
    event_names = {
        "agent_events": [
            "agent.before_step",
            "agent.before_request",
            "tools.before_execute",
            "tools.after_execute",
            "agent.after_turn",
        ],
        "agent_tools": ["agent.tool_generation"],
    }
    scope_types = {"agent_events": "tenant", "agent_tools": "project"}
    for capability, events in event_names.items():
        for scope_index in range(2):
            for event_name in events:
                records.append(
                    {
                        "capability": capability,
                        "event_name": event_name,
                        "hook_name": event_name.replace(".", "_"),
                        "scope_type": scope_types[capability],
                        "scope_id": f"{capability}-{scope_index}",
                        "equal": True,
                        "legacy_payload": {"value": "same"},
                        "typed_payload": {"value": "same"},
                        "occurred_at": occurred_at,
                    }
                )
    await repository.record_shadow_rollout_events(records)
    await db_session.commit()

    response = make_client(db_session).get(
        "/api/v1/platform-plugins/shadow-rollout/readiness",
        params={
            "minimum_samples_per_event": 2,
            "minimum_distinct_scopes": 2,
            "maximum_evidence_age_seconds": 900,
        },
    )

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["ready"] is True
    assert payload["reasons"] == []
    capability_readiness = {row["capability"]: row for row in payload["capabilities"]}
    assert capability_readiness["agent_events"]["distinct_scope_count"] == 2
    assert capability_readiness["agent_tools"]["total_count"] == 2

    records[-1]["equal"] = False
    records[-1]["typed_payload"] = {"value": "changed"}
    await repository.record_shadow_rollout_events([dict(records[-1])])
    await db_session.commit()
    diff_response = make_client(db_session).get(
        "/api/v1/platform-plugins/shadow-rollout/readiness",
        params={
            "minimum_samples_per_event": 2,
            "minimum_distinct_scopes": 2,
            "maximum_evidence_age_seconds": 900,
        },
    )
    diff_payload = diff_response.json()
    assert diff_payload["ready"] is False
    assert "agent_tools:diffs_present" in diff_payload["reasons"]


@pytest.mark.unit
async def test_shadow_rollout_readiness_fails_closed_for_missing_or_stale_evidence(
    db_session: AsyncSession,
) -> None:
    repository = PlatformPluginRepository(db_session)
    stale_at = datetime.now(UTC) - timedelta(hours=1)
    await repository.record_shadow_rollout_events(
        [
            {
                "capability": "agent_tools",
                "event_name": "agent.tool_generation",
                "hook_name": "tool_generation",
                "scope_type": "project",
                "scope_id": "project-stale",
                "equal": True,
                "legacy_payload": {"value": "same"},
                "typed_payload": {"value": "same"},
                "occurred_at": stale_at,
            }
        ]
    )
    await db_session.commit()

    response = make_client(db_session).get(
        "/api/v1/platform-plugins/shadow-rollout/readiness",
        params={
            "minimum_samples_per_event": 1,
            "minimum_distinct_scopes": 1,
            "maximum_evidence_age_seconds": 900,
        },
    )

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["ready"] is False
    reasons = set(payload["reasons"])
    assert "agent_tools:stale_evidence:agent.tool_generation" in reasons
    assert "agent_events:missing_event:agent.before_step" in reasons
    assert "agent_events:insufficient_scope_coverage" in reasons


@pytest.mark.unit
async def test_cutover_readiness_requires_shadow_parity_and_rollback_drill(
    db_session: AsyncSession,
) -> None:
    repository = PlatformPluginRepository(db_session)
    snapshot = compose_snapshot("router-test-cutover")
    await repository.record_snapshot(snapshot, version=101, nonce="cutover-101")
    await db_session.commit()
    client = make_client(db_session)

    missing_response = client.get(
        "/api/v1/platform-plugins/cutover/readiness",
        params={
            "minimum_samples_per_event": 1,
            "minimum_distinct_scopes": 1,
            "minimum_distinct_data_planes": 1,
        },
    )

    assert missing_response.status_code == status.HTTP_200_OK
    missing = missing_response.json()
    assert missing["ready"] is False
    assert missing["rollback_drill"]["ready"] is False
    assert missing["rollback_drill"]["reasons"] == ["insufficient_rollback_drills:0:1"]
    assert any(reason.startswith("shadow:") for reason in missing["reasons"])

    await repository.record_apply_state(
        data_plane_id="desktop-local",
        snapshot_digest=snapshot.digest,
        requested_version=101,
        applied_version=101,
        status="ack",
    )
    await repository.record_apply_state(
        data_plane_id="desktop-local",
        snapshot_digest="0" * 64,
        requested_version=102,
        applied_version=101,
        status="nack",
        error_message="requested layer digest does not match OCI manifest",
    )
    corrected = compose_snapshot("router-test-cutover-restored")
    await repository.record_snapshot(corrected, version=103, nonce="cutover-103")
    await repository.record_apply_state(
        data_plane_id="desktop-local",
        snapshot_digest=corrected.digest,
        requested_version=103,
        applied_version=103,
        status="ack",
    )
    await db_session.commit()

    events = await db_session.execute(select(PlatformPluginApplyStateEventModel))
    assert len(events.scalars().all()) == 3
    response = client.get(
        "/api/v1/platform-plugins/cutover/readiness",
        params={
            "minimum_samples_per_event": 1,
            "minimum_distinct_scopes": 1,
            "minimum_distinct_data_planes": 1,
        },
    )

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["rollback_drill"]["ready"] is True
    assert payload["rollback_drill"]["data_planes"][0]["data_plane_id"] == "desktop-local"
    assert payload["ready"] is False
    assert any(reason.startswith("shadow:") for reason in payload["reasons"])


@pytest.mark.unit
async def test_cutover_approval_requires_readiness_and_is_durable(
    db_session: AsyncSession,
) -> None:
    repository = PlatformPluginRepository(db_session)
    snapshot = compose_snapshot("router-test-cutover-approval")
    await repository.record_snapshot(snapshot, version=201, nonce="approval-201")
    await db_session.commit()
    client = make_client(db_session)

    rejected = client.post(
        "/api/v1/platform-plugins/cutover/approve", json={"valid_for_seconds": 3_600}
    )

    assert rejected.status_code == status.HTTP_409_CONFLICT

    now = datetime.now(UTC)
    for event_name in (
        "agent.before_step",
        "agent.before_request",
        "tools.before_execute",
        "tools.after_execute",
        "agent.after_turn",
    ):
        await repository.record_shadow_rollout_events(
            [
                {
                    "capability": "agent_events",
                    "event_name": event_name,
                    "hook_name": event_name.replace(".", "_"),
                    "scope_type": "tenant",
                    "scope_id": f"approval-tenant-{scope_index}",
                    "equal": True,
                    "legacy_payload": {"value": "same"},
                    "typed_payload": {"value": "same"},
                    "occurred_at": now,
                }
                for scope_index in range(100)
            ]
        )
    await repository.record_shadow_rollout_events(
        [
            {
                "capability": "agent_tools",
                "event_name": "agent.tool_generation",
                "hook_name": "tool_generation",
                "scope_type": "project",
                "scope_id": f"approval-project-{scope_index}",
                "equal": True,
                "legacy_payload": {"value": "same"},
                "typed_payload": {"value": "same"},
                "occurred_at": now,
            }
            for scope_index in range(100)
        ]
    )
    await repository.record_apply_state(
        data_plane_id="approval-desktop",
        snapshot_digest=snapshot.digest,
        requested_version=201,
        applied_version=201,
        status="ack",
    )
    await repository.record_apply_state(
        data_plane_id="approval-desktop",
        snapshot_digest="0" * 64,
        requested_version=202,
        applied_version=201,
        status="nack",
        error_message="invalid artifact digest",
    )
    restored = compose_snapshot("router-test-cutover-approval-restored")
    await repository.record_snapshot(restored, version=203, nonce="approval-203")
    await repository.record_apply_state(
        data_plane_id="approval-desktop",
        snapshot_digest=restored.digest,
        requested_version=203,
        applied_version=203,
        status="ack",
    )
    await db_session.commit()

    approved = client.post(
        "/api/v1/platform-plugins/cutover/approve", json={"valid_for_seconds": 3_600}
    )

    assert approved.status_code == status.HTTP_200_OK
    approval = approved.json()
    assert approval["capability"] == "agent_runtime"
    assert approval["evidence"]["ready"] is True
    assert datetime.fromisoformat(approval["expires_at"].replace("Z", "+00:00")) > now
    duplicate = client.post(
        "/api/v1/platform-plugins/cutover/approve", json={"valid_for_seconds": 3_600}
    )
    assert duplicate.status_code == status.HTTP_409_CONFLICT

    readiness = client.get(
        "/api/v1/platform-plugins/cutover/readiness",
        params={"minimum_samples_per_event": 1, "minimum_distinct_scopes": 1},
    )
    assert readiness.status_code == status.HTTP_200_OK
    assert readiness.json()["operator_approved"] is True

    revoked = client.post(
        "/api/v1/platform-plugins/cutover/revoke",
        json={"reason": "rollback drill approval was revoked"},
    )
    assert revoked.status_code == status.HTTP_200_OK
    assert revoked.json()["revoked"] is True
    missing_revoke = client.post(
        "/api/v1/platform-plugins/cutover/revoke",
        json={"reason": "already revoked"},
    )
    assert missing_revoke.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.unit
async def test_cutover_approval_and_revocation_require_platform_admin(
    db_session: AsyncSession,
) -> None:
    client = make_client(db_session, superuser=False)

    approval = client.post(
        "/api/v1/platform-plugins/cutover/approve", json={"valid_for_seconds": 3_600}
    )
    revocation = client.post(
        "/api/v1/platform-plugins/cutover/revoke",
        json={"reason": "must be forbidden before authorization"},
    )

    assert approval.status_code == status.HTTP_403_FORBIDDEN
    assert revocation.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.unit
def test_rollback_and_cutover_evaluators_fail_closed_on_incomplete_sequences() -> None:
    now = datetime.now(UTC)

    valid = evaluate_rollback_drill_readiness(events=valid_events(now), checked_at=now)
    incomplete = evaluate_rollback_drill_readiness(
        events=[
            {
                "id": "event-1",
                "data_plane_id": "desktop-local",
                "requested_version": 101,
                "applied_version": 101,
                "status": "ack",
                "error_message": None,
                "recorded_at": now,
            }
        ],
        checked_at=now,
    )

    assert valid.ready is True
    assert incomplete.ready is False
    assert incomplete.data_planes[0].reasons == (
        "missing_invalid_config_nack",
        "missing_restored_ack",
    )

    combined = evaluate_platform_plugin_cutover_readiness(
        shadow=_ready_shadow(now),
        rollback_drill=valid,
    )
    assert combined.ready is True
    assert combined.reasons == ()

    regressed = evaluate_rollback_drill_readiness(
        events=[
            *valid_events(now),
            {
                "id": "event-4",
                "data_plane_id": "desktop-local",
                "requested_version": 104,
                "applied_version": 103,
                "status": "nack",
                "error_message": "control plane restored an older generation",
                "recorded_at": now,
            },
        ],
        checked_at=now,
    )
    assert regressed.ready is False
    assert regressed.data_planes[0].reasons == ("restored_ack_not_latest",)


def _ready_shadow(checked_at: datetime) -> ShadowRolloutReadiness:
    from src.infrastructure.plugins.rollout_readiness import ShadowRolloutCapabilityReadiness

    capabilities = [
        ShadowRolloutCapabilityReadiness(
            capability=capability,
            ready=True,
            total_count=1,
            equal_count=1,
            diff_count=0,
            distinct_scope_count=1,
            observed_event_count=1,
            required_event_count=1,
            last_occurred_at=checked_at,
            reasons=(),
        )
        for capability in ("agent_events", "agent_tools")
    ]
    return ShadowRolloutReadiness(
        ready=True,
        checked_at=checked_at,
        minimum_samples_per_event=1,
        minimum_distinct_scopes=1,
        maximum_evidence_age_seconds=60,
        capabilities=tuple(capabilities),
        reasons=(),
    )


def valid_events(now: datetime) -> list[dict[str, object]]:
    return [
        {
            "id": "event-1",
            "data_plane_id": "desktop-local",
            "requested_version": 101,
            "applied_version": 101,
            "status": "ack",
            "error_message": None,
            "recorded_at": now,
        },
        {
            "id": "event-2",
            "data_plane_id": "desktop-local",
            "requested_version": 102,
            "applied_version": 101,
            "status": "nack",
            "error_message": "invalid artifact digest",
            "recorded_at": now,
        },
        {
            "id": "event-3",
            "data_plane_id": "desktop-local",
            "requested_version": 103,
            "applied_version": 103,
            "status": "ack",
            "error_message": None,
            "recorded_at": now,
        },
    ]


@pytest.mark.unit
def test_readiness_evaluator_rejects_missing_scope_counts_and_future_timestamps() -> None:
    now = datetime.now(UTC)
    readiness = evaluate_shadow_rollout_readiness(
        summary=[],
        scope_counts=[],
        checked_at=now,
        minimum_samples_per_event=1,
        minimum_distinct_scopes=1,
        maximum_evidence_age_seconds=60,
    )

    assert readiness.ready is False
    assert readiness.capabilities[0].ready is False
    assert "agent_events:missing_event:agent.before_step" in readiness.reasons

    future = evaluate_shadow_rollout_readiness(
        summary=[
            {
                "capability": "agent_events",
                "event_name": "agent.before_step",
                "total_count": 1,
                "equal_count": 1,
                "diff_count": 0,
                "last_occurred_at": now + timedelta(seconds=1),
            }
        ],
        scope_counts=[
            {"capability": "agent_events", "distinct_scope_count": 1},
        ],
        checked_at=now,
        minimum_samples_per_event=1,
        minimum_distinct_scopes=1,
        maximum_evidence_age_seconds=60,
    )

    assert future.ready is False
    assert "agent_events:stale_evidence:agent.before_step" in future.reasons


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
