"""Canonical Cloud run-input, summary and Activity authority contracts."""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

from fastapi import status
from sqlalchemy import select

from src.infrastructure.adapters.secondary.persistence.agent_run_settlement import (
    apply_run_input_applied_projection,
)
from src.infrastructure.adapters.secondary.persistence.attachment_model import AttachmentModel
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent,
    AgentPlanRunModel,
    AgentPlanVersionModel,
    AgentRunAuthorityModel,
    AgentRunInputModel,
    Conversation,
    WorkspaceMemberModel,
    WorkspaceModel,
)


async def _add_run(test_db, test_project_db, test_user) -> AgentPlanRunModel:
    now = datetime.now(UTC)
    workspace = WorkspaceModel(
        id="run-authority-workspace",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        name="Run authority workspace",
        created_by=test_user.id,
        metadata_json={"capability_mode": "code"},
    )
    membership = WorkspaceMemberModel(
        id="run-authority-workspace-member",
        workspace_id=workspace.id,
        user_id=test_user.id,
        role="owner",
        invited_by=test_user.id,
    )
    conversation = Conversation(
        id="run-authority-conversation",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
        title="Run authority",
        status="active",
        agent_config={},
        message_count=0,
        workspace_id=workspace.id,
    )
    version = AgentPlanVersionModel(
        id="run-authority-plan",
        conversation_id=conversation.id,
        version=1,
        status="approved",
        tasks_json=[],
        approved_at=now,
    )
    run = AgentPlanRunModel(
        id="run-authority-run",
        conversation_id=conversation.id,
        project_id=test_project_db.id,
        plan_version_id=version.id,
        idempotency_key="run-authority-start",
        message_id="run-authority-message",
        request_message="Implement the authority",
        status="running",
        revision=3,
        permission_profile="workspace_write",
        authorization_snapshot={},
        created_at=now - timedelta(minutes=1),
        updated_at=now,
    )
    authority = AgentRunAuthorityModel(
        id=run.id,
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        conversation_id=conversation.id,
        run_kind="plan",
        plan_run_id=run.id,
        plan_version_id=version.id,
        idempotency_key=run.idempotency_key,
        message_id=run.message_id,
        request_message=run.request_message,
        status=run.status,
        revision=run.revision,
        permission_profile=run.permission_profile,
        authorization_snapshot=run.authorization_snapshot,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )
    test_db.add_all([workspace, membership, conversation, version, run, authority])
    await test_db.commit()
    return run


async def test_root_chat_run_authority_is_active_and_accepts_queue_input(
    authenticated_async_client,
    test_db,
    test_project_db,
    test_user,
) -> None:
    now = datetime.now(UTC)
    conversation = Conversation(
        id="root-run-authority-conversation",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
        title="Root run authority",
        status="active",
        agent_config={},
        message_count=0,
    )
    run = AgentRunAuthorityModel(
        id="root-execution-message",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        conversation_id=conversation.id,
        run_kind="chat",
        plan_run_id=None,
        plan_version_id=None,
        idempotency_key="client-message:root-message",
        message_id="root-execution-message",
        request_message="Inspect the current workspace.",
        status="running",
        revision=1,
        permission_profile="read_only",
        authorization_snapshot={"source": "chat_admission"},
        created_at=now,
        updated_at=now,
    )
    test_db.add_all([conversation, run])
    await test_db.commit()

    active = await authenticated_async_client.get(
        f"/api/v1/agent/conversations/{conversation.id}/active-run"
    )
    assert active.status_code == status.HTTP_200_OK
    active_run = active.json()["active_run"]
    assert active_run["id"] == run.id
    assert active_run["turn_id"] == run.message_id
    assert active_run["status"] == "running"
    assert active_run["revision"] == 1
    assert active_run["allowed_actions"] == ["steer_now", "queue_next", "kill_run"]

    queued = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{run.id}/inputs",
        json={
            "expected_run_revision": 1,
            "message": "Queue this until the current run completes.",
            "message_id": "root-queue-message",
            "idempotency_key": "root-queue-key",
            "delivery": "queue_next",
            "references": [],
            "context_items": [],
        },
    )
    assert queued.status_code == status.HTTP_200_OK
    assert queued.json()["run_id"] == run.id
    assert queued.json()["input"]["status"] == "queued"


async def test_run_input_is_revision_checked_idempotent_and_reloadable(
    authenticated_async_client,
    test_db,
    test_project_db,
    test_user,
) -> None:
    run = await _add_run(test_db, test_project_db, test_user)
    payload = {
        "expected_run_revision": 3,
        "message": "Continue after this tool boundary.",
        "message_id": "queued-message-1",
        "idempotency_key": "queue-key-1",
        "delivery": "queue_next",
        "references": [],
        "context_items": [],
    }

    response = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{run.id}/inputs",
        json=payload,
    )
    assert response.status_code == status.HTTP_200_OK
    ack = response.json()
    receipt = ack["input"]
    assert ack["created"] is True
    assert ack["delivery_mode"] == "queue_next"
    assert ack["run_revision"] == 3
    assert ack["queue_position"] == 1
    assert receipt["status"] == "queued"
    assert receipt["sequence"] == 1
    assert receipt["content"] == payload["message"]

    replay = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{run.id}/inputs",
        json=payload,
    )
    assert replay.status_code == status.HTTP_200_OK
    assert replay.json()["created"] is False
    assert replay.json()["input"]["id"] == receipt["id"]

    conflict = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{run.id}/inputs",
        json={**payload, "message": "Different payload"},
    )
    assert conflict.status_code == status.HTTP_409_CONFLICT

    listing = await authenticated_async_client.get(f"/api/v1/agent/runs/{run.id}/inputs")
    assert listing.status_code == status.HTTP_200_OK
    assert listing.json()["inputs"] == [receipt]
    assert listing.json()["total_count"] == 1

    wrong_revision = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{run.id}/inputs",
        json={
            **payload,
            "expected_run_revision": 2,
            "message_id": "wrong-revision-message",
            "idempotency_key": "wrong-revision-key",
        },
    )
    assert wrong_revision.status_code == status.HTTP_409_CONFLICT

    second = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{run.id}/inputs",
        json={
            **payload,
            "message": "Second queued input.",
            "message_id": "queued-message-2",
            "idempotency_key": "queue-key-2",
        },
    )
    assert second.status_code == status.HTTP_200_OK
    assert second.json()["queue_position"] == 2

    context_conflict = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{run.id}/inputs",
        json={
            **payload,
            "message_id": "context-conflict-message",
            "idempotency_key": "context-conflict-key",
            "context_items": [
                {
                    "kind": "agent",
                    "resource_id": "agent-outside-roster",
                    "label": "Outside roster",
                }
            ],
        },
    )
    assert context_conflict.status_code == status.HTTP_409_CONFLICT

    uploaded_attachment = AttachmentModel(
        id="attachment-uploaded",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        conversation_id=run.conversation_id,
        filename="constraints.txt",
        mime_type="text/plain",
        size_bytes=24,
        object_key="tests/constraints.txt",
        purpose="both",
        status="uploaded",
    )
    test_db.add(uploaded_attachment)
    await test_db.commit()
    attachment_context = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{run.id}/inputs",
        json={
            **payload,
            "message": "Use the uploaded constraints.",
            "message_id": "attachment-context-message",
            "idempotency_key": "attachment-context-key",
            "context_items": [
                {
                    "kind": "attachment",
                    "resource_id": uploaded_attachment.id,
                    "label": uploaded_attachment.filename,
                }
            ],
        },
    )
    assert attachment_context.status_code == status.HTTP_200_OK

    other_conversation = Conversation(
        id="run-authority-other-conversation",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
        title="Other conversation",
        status="active",
        agent_config={},
        message_count=0,
        workspace_id="run-authority-workspace",
    )
    test_db.add(other_conversation)
    await test_db.flush()
    uploaded_attachment.conversation_id = other_conversation.id
    await test_db.commit()
    attachment_scope_conflict = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{run.id}/inputs",
        json={
            **payload,
            "message": "Use an attachment from another conversation.",
            "message_id": "attachment-scope-conflict-message",
            "idempotency_key": "attachment-scope-conflict-key",
            "context_items": [
                {
                    "kind": "attachment",
                    "resource_id": uploaded_attachment.id,
                    "label": uploaded_attachment.filename,
                }
            ],
        },
    )
    assert attachment_scope_conflict.status_code == status.HTTP_409_CONFLICT


async def test_run_input_applied_projection_is_structured_and_revision_scoped(
    test_db,
    test_project_db,
    test_user,
) -> None:
    run = await _add_run(test_db, test_project_db, test_user)
    row = AgentRunInputModel(
        id="steer-input",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        conversation_id=run.conversation_id,
        run_id=run.id,
        actor_user_id=test_user.id,
        expected_run_revision=run.revision,
        message="Apply at the next Observe boundary.",
        message_id="steer-message",
        idempotency_key="steer-key",
        payload_hash="a" * 64,
        delivery="steer_now",
        references_json=[],
        context_items_json=[],
        status="pending_boundary",
        sequence=1,
    )
    test_db.add(row)
    await test_db.commit()

    receipt_event = {
        "run_input_id": row.id,
        "run_id": run.id,
        "run_revision": run.revision,
        "message_id": row.message_id,
        "idempotency_key": row.idempotency_key,
        "delivery_mode": "steer_now",
        "applied_round": 5,
        "applied_at": "2026-08-04T01:00:00+00:00",
        "injected_via": "control_channel_observe_boundary",
    }
    invalid_receipts = [
        {**receipt_event, "delivery_mode": "queue_next"},
        {**receipt_event, "run_revision": True},
        {**receipt_event, "applied_round": -1},
        {**receipt_event, "applied_at": "not-a-date"},
        {**receipt_event, "applied_at": "2026-08-04T01:00:00"},
        {**receipt_event, "injected_via": "message_text"},
    ]
    for invalid_receipt in invalid_receipts:
        assert (
            await apply_run_input_applied_projection(test_db, event_data=invalid_receipt) is False
        )

    applied = await apply_run_input_applied_projection(
        test_db,
        event_data=receipt_event,
    )
    await test_db.commit()
    await test_db.refresh(row)

    assert applied is True
    assert row.status == "applied"
    assert row.applied_round == 5
    assert row.applied_at is not None
    assert row.applied_at.replace(tzinfo=UTC) == datetime(2026, 8, 4, 1, 0, tzinfo=UTC)
    assert row.injected_via == "control_channel_observe_boundary"

    stale = await apply_run_input_applied_projection(
        test_db,
        event_data={
            "run_input_id": row.id,
            "run_id": run.id,
            "run_revision": run.revision + 1,
            "message_id": row.message_id,
            "idempotency_key": row.idempotency_key,
            "delivery_mode": "steer_now",
            "applied_round": 9,
            "applied_at": "2026-08-04T02:00:00+00:00",
            "injected_via": "control_channel_observe_boundary",
        },
    )
    assert stale is False
    assert row.applied_round == 5


async def test_steer_dispatch_commits_before_control_and_failed_dispatch_retries(
    authenticated_async_client,
    test_app,
    test_db,
    test_project_db,
    test_user,
    monkeypatch,
) -> None:
    from src.infrastructure.adapters.primary.web.routers.agent import run_authority

    run = await _add_run(test_db, test_project_db, test_user)
    run_id = run.id
    monkeypatch.setattr(test_app.state.container, "_redis_client", object())
    dispatch_attempts: list[str] = []

    async def _send_control(_channel, message) -> bool:
        assert test_db.in_transaction() is False
        persisted = await test_db.get(AgentRunInputModel, message.run_input_id)
        assert persisted is not None
        assert persisted.dispatch_status == "dispatching"
        dispatch_attempts.append(message.run_input_id)
        return len(dispatch_attempts) > 1

    monkeypatch.setattr(run_authority.RedisControlChannel, "send_control", _send_control)
    payload = {
        "expected_run_revision": run.revision,
        "message": "Apply after this Observe boundary.",
        "message_id": "steer-dispatch-message",
        "idempotency_key": "steer-dispatch-key",
        "delivery": "steer_now",
        "references": [],
        "context_items": [],
    }

    failed = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{run.id}/inputs",
        json=payload,
    )
    assert failed.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert failed.json()["accepted"] is False
    assert failed.json()["reason_code"] == "run_input_dispatch_failed"
    row_result = await test_db.execute(
        select(AgentRunInputModel).where(
            AgentRunInputModel.run_id == run.id,
            AgentRunInputModel.idempotency_key == payload["idempotency_key"],
        )
    )
    row = row_result.scalar_one()
    row_id = row.id
    assert row.dispatch_status == "failed"
    assert row.dispatch_attempts == 1
    await test_db.rollback()

    conflict = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{run_id}/inputs",
        json={**payload, "message": "Different steering payload."},
    )
    assert conflict.status_code == status.HTTP_409_CONFLICT

    replay = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{run_id}/inputs",
        json=payload,
    )
    assert replay.status_code == status.HTTP_200_OK
    assert replay.json()["created"] is False
    assert replay.json()["input"]["dispatch_status"] == "dispatched"
    assert replay.json()["input"]["dispatch_attempts"] == 2
    assert dispatch_attempts == [row_id, row_id]


async def test_steer_dispatch_rejects_live_lease_and_takes_over_expired_lease(
    authenticated_async_client,
    test_app,
    test_db,
    test_project_db,
    test_user,
    monkeypatch,
) -> None:
    from src.application.schemas.agent_run_authority import CreateRunInputRequest
    from src.infrastructure.adapters.primary.web.routers.agent import run_authority

    run = await _add_run(test_db, test_project_db, test_user)
    monkeypatch.setattr(test_app.state.container, "_redis_client", object())
    payload = {
        "expected_run_revision": run.revision,
        "message": "Lease-protected steering input.",
        "message_id": "lease-steer-message",
        "idempotency_key": "lease-steer-key",
        "delivery": "steer_now",
        "references": [],
        "context_items": [],
    }
    command = CreateRunInputRequest.model_validate(payload)
    row = AgentRunInputModel(
        id="lease-steer-input",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        conversation_id=run.conversation_id,
        run_id=run.id,
        actor_user_id=test_user.id,
        expected_run_revision=run.revision,
        message=payload["message"],
        message_id=payload["message_id"],
        idempotency_key=payload["idempotency_key"],
        payload_hash=run_authority._canonical_hash(command.model_dump(mode="json")),
        delivery="steer_now",
        references_json=[],
        context_items_json=[],
        status="pending_boundary",
        sequence=1,
        dispatch_status="dispatching",
        dispatch_attempts=1,
        dispatch_lease_expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    test_db.add(row)
    await test_db.commit()
    send_control = AsyncMock(return_value=True)
    monkeypatch.setattr(run_authority.RedisControlChannel, "send_control", send_control)

    in_progress = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{run.id}/inputs",
        json=payload,
    )
    assert in_progress.status_code == status.HTTP_409_CONFLICT
    assert in_progress.json()["accepted"] is False
    assert in_progress.json()["reason_code"] == "run_input_dispatch_in_progress"
    send_control.assert_not_awaited()

    row.dispatch_lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await test_db.commit()
    takeover = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{run.id}/inputs",
        json=payload,
    )

    assert takeover.status_code == status.HTTP_200_OK
    assert takeover.json()["created"] is False
    assert takeover.json()["input"]["dispatch_status"] == "dispatched"
    assert takeover.json()["input"]["dispatch_attempts"] == 2
    send_control.assert_awaited_once()


async def test_active_latest_and_legacy_summary_are_explicit(
    authenticated_async_client,
    test_db,
    test_project_db,
    test_user,
) -> None:
    run = await _add_run(test_db, test_project_db, test_user)

    active = await authenticated_async_client.get(
        "/api/v1/agent/conversations/run-authority-conversation/active-run"
    )
    assert active.status_code == status.HTTP_200_OK
    assert active.json()["active_run"]["id"] == run.id
    assert active.json()["active_run"]["turn_id"] == run.message_id
    assert active.json()["active_run"]["allowed_actions"] == [
        "steer_now",
        "queue_next",
        "kill_run",
    ]

    run.status = "ready_review"
    run.revision = 4
    authority = await test_db.get(AgentRunAuthorityModel, run.id)
    assert authority is not None
    authority.status = run.status
    authority.revision = run.revision
    await test_db.commit()
    active = await authenticated_async_client.get(
        "/api/v1/agent/conversations/run-authority-conversation/active-run"
    )
    assert active.json()["reason_code"] == "no_active_run"

    latest = await authenticated_async_client.get(
        "/api/v1/agent/conversations/run-authority-conversation/latest-run"
    )
    assert latest.status_code == status.HTTP_200_OK
    assert latest.json()["latest_run"]["id"] == run.id
    assert latest.json()["latest_run"]["turn_id"] == run.message_id
    assert latest.json()["latest_run"]["revision"] == 4
    assert latest.json()["latest_run"]["allowed_actions"] == []

    summary = await authenticated_async_client.get(f"/api/v1/agent/runs/{run.id}/summary")
    assert summary.status_code == status.HTTP_200_OK
    assert summary.json()["summary_state"] == "partial"
    assert summary.json()["reason_code"] == "summary_not_recorded"

    changes = await authenticated_async_client.get(
        f"/api/v1/agent/runs/{run.id}/changes",
        params={"scope": "run", "expected_revision": 4},
    )
    assert changes.status_code == status.HTTP_200_OK
    assert changes.json()["status"] == "unattributed"
    assert changes.json()["reason"] == "change_attribution_not_recorded"
    assert changes.json()["files"] == []


async def test_changes_scope_uses_structural_turn_attribution(
    authenticated_async_client,
    test_db,
    test_project_db,
    test_user,
) -> None:
    run = await _add_run(test_db, test_project_db, test_user)
    test_db.add_all(
        [
            AgentExecutionEvent(
                id="run-change-event",
                conversation_id=run.conversation_id,
                message_id=run.message_id,
                event_type="tool_result",
                event_data={"file_path": "src/run.py", "hunk_id": "run-hunk"},
                event_time_us=1,
                event_counter=0,
            ),
            AgentExecutionEvent(
                id="other-turn-change-event",
                conversation_id=run.conversation_id,
                message_id="other-turn",
                event_type="tool_result",
                event_data={"file_path": "src/other.py", "hunk_id": "other-hunk"},
                event_time_us=2,
                event_counter=0,
            ),
            AgentExecutionEvent(
                id="run-routing-event",
                conversation_id=run.conversation_id,
                message_id=run.message_id,
                event_type="routing_decision",
                event_data={"path": "plan_mode", "route_id": "route-1"},
                event_time_us=3,
                event_counter=0,
            ),
            AgentExecutionEvent(
                id="run-read-event",
                conversation_id=run.conversation_id,
                message_id=run.message_id,
                event_type="tool_result",
                event_data={"file_path": "/etc/hosts"},
                event_time_us=4,
                event_counter=0,
            ),
        ]
    )
    await test_db.commit()

    run_scope = await authenticated_async_client.get(
        f"/api/v1/agent/runs/{run.id}/changes",
        params={"scope": "run", "expected_revision": run.revision},
    )
    turn_scope = await authenticated_async_client.get(
        f"/api/v1/agent/runs/{run.id}/changes",
        params={
            "scope": "turn",
            "turn_id": "other-turn",
            "expected_revision": run.revision,
        },
    )
    session_scope = await authenticated_async_client.get(
        f"/api/v1/agent/runs/{run.id}/changes",
        params={"scope": "session", "expected_revision": run.revision},
    )

    assert [item["event_id"] for item in run_scope.json()["attribution"]] == ["run-change-event"]
    assert [item["event_id"] for item in turn_scope.json()["attribution"]] == [
        "other-turn-change-event"
    ]
    assert [item["event_id"] for item in session_scope.json()["attribution"]] == [
        "run-change-event",
        "other-turn-change-event",
    ]


async def test_ready_input_promotes_once_with_same_receipt(
    authenticated_async_client,
    test_db,
    test_project_db,
    test_user,
    monkeypatch,
) -> None:
    async def _noop_execute(**_kwargs: Any) -> None:
        return None

    from src.infrastructure.adapters.primary.web.routers.agent import run_input_authority

    monkeypatch.setattr(run_input_authority, "_execute_approved_plan", _noop_execute)
    run = await _add_run(test_db, test_project_db, test_user)
    input_row = AgentRunInputModel(
        id="ready-input",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        conversation_id=run.conversation_id,
        run_id=run.id,
        actor_user_id=test_user.id,
        expected_run_revision=run.revision,
        message="Promote me",
        message_id="ready-input-message",
        idempotency_key="ready-input-create",
        payload_hash="b" * 64,
        delivery="queue_next",
        references_json=[],
        context_items_json=[],
        status="ready",
        sequence=1,
        queue_position=1,
    )
    run.status = "ready_review"
    run.revision = 4
    authority = await test_db.get(AgentRunAuthorityModel, run.id)
    assert authority is not None
    authority.status = run.status
    authority.revision = run.revision
    test_db.add(input_row)
    await test_db.commit()
    payload = {
        "expected_source_run_revision": 4,
        "idempotency_key": "promote-ready-input",
    }

    first = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{run.id}/inputs/{input_row.id}/promote",
        json=payload,
    )
    replay = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{run.id}/inputs/{input_row.id}/promote",
        json=payload,
    )

    assert first.status_code == status.HTTP_200_OK
    assert first.json()["created"] is True
    assert first.json()["input"]["status"] == "promoted_to_plan"
    assert replay.status_code == status.HTTP_200_OK
    assert replay.json()["created"] is False
    assert replay.json()["input"]["id"] == first.json()["input"]["id"]


async def test_ready_chat_input_creates_plan_version_before_promotion(
    authenticated_async_client,
    test_db,
    test_project_db,
    test_user,
    monkeypatch,
) -> None:
    async def _noop_execute(**_kwargs: Any) -> None:
        return None

    from src.infrastructure.adapters.primary.web.routers.agent import run_input_authority

    monkeypatch.setattr(run_input_authority, "_execute_approved_plan", _noop_execute)
    now = datetime.now(UTC)
    conversation = Conversation(
        id="chat-promotion-conversation",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
        title="Chat promotion",
        status="active",
        agent_config={},
        message_count=0,
    )
    source_run = AgentRunAuthorityModel(
        id="chat-promotion-source-run",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        conversation_id=conversation.id,
        run_kind="chat",
        plan_run_id=None,
        plan_version_id=None,
        idempotency_key="client-message:chat-promotion-source",
        message_id="chat-promotion-source-run",
        request_message="Complete the current turn.",
        status="ready_review",
        revision=2,
        permission_profile="workspace_write",
        authorization_snapshot={"source": "chat_admission"},
        created_at=now - timedelta(minutes=1),
        updated_at=now,
        completed_at=now,
    )
    input_row = AgentRunInputModel(
        id="ready-chat-input",
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        conversation_id=conversation.id,
        run_id=source_run.id,
        actor_user_id=test_user.id,
        expected_run_revision=1,
        message="Start the explicit planning turn.",
        message_id="ready-chat-input-message",
        idempotency_key="ready-chat-input-create",
        payload_hash="c" * 64,
        delivery="queue_next",
        references_json=[],
        context_items_json=[],
        status="ready",
        sequence=1,
        queue_position=1,
    )
    test_db.add_all([conversation, source_run, input_row])
    await test_db.commit()

    response = await authenticated_async_client.post(
        f"/api/v1/agent/runs/{source_run.id}/inputs/{input_row.id}/promote",
        json={
            "expected_source_run_revision": 2,
            "idempotency_key": "promote-ready-chat-input",
        },
    )

    assert response.status_code == status.HTTP_200_OK
    await test_db.refresh(input_row)
    assert input_row.promoted_run_id is not None
    promoted_run = await test_db.get(AgentPlanRunModel, input_row.promoted_run_id)
    assert promoted_run is not None
    assert promoted_run.plan_version_id is not None
    assert promoted_run.permission_profile == "read_only"
    promoted_version = await test_db.get(AgentPlanVersionModel, promoted_run.plan_version_id)
    assert promoted_version is not None
    assert promoted_version.conversation_id == conversation.id
    assert promoted_version.status == "draft"
    active = await authenticated_async_client.get(
        f"/api/v1/agent/conversations/{conversation.id}/active-run"
    )
    assert active.status_code == status.HTTP_200_OK
    assert active.json()["active_run"]["id"] == promoted_run.id
    assert active.json()["active_run"]["status"] == "running"
    assert active.json()["active_run"]["allowed_actions"] == [
        "steer_now",
        "queue_next",
        "kill_run",
    ]


async def test_activity_read_state_merges_newer_revision_and_read_time(
    authenticated_async_client,
    test_db,
    test_project_db,
    test_user,
) -> None:
    await _add_run(test_db, test_project_db, test_user)
    first_read = datetime.now(UTC) - timedelta(minutes=1)
    first = await authenticated_async_client.put(
        f"/api/v1/projects/{test_project_db.id}/activity/read-state",
        json={
            "entries": [
                {
                    "entry_id": "agent_run:run-authority-run",
                    "entry_revision": 2,
                    "read_at": first_read.isoformat(),
                }
            ]
        },
    )
    assert first.status_code == status.HTTP_200_OK
    assert first.json()["authority_revision"] == 1

    second_read = datetime.now(UTC)
    second = await authenticated_async_client.put(
        f"/api/v1/projects/{test_project_db.id}/activity/read-state",
        json={
            "entries": [
                {
                    "entry_id": "agent_run:run-authority-run",
                    "entry_revision": 1,
                    "read_at": second_read.isoformat(),
                }
            ]
        },
    )
    assert second.status_code == status.HTTP_200_OK
    assert second.json()["authority_revision"] == 2
    assert second.json()["entries"][0]["entry_revision"] == 2
    assert second.json()["entries"][0]["read_at"] == second_read.isoformat().replace(
        "+00:00",
        "Z",
    )


async def test_activity_read_state_rejects_stale_expected_authority_revision(
    authenticated_async_client,
    test_db,
    test_project_db,
    test_user,
) -> None:
    await _add_run(test_db, test_project_db, test_user)
    endpoint = f"/api/v1/projects/{test_project_db.id}/activity/read-state"
    first = await authenticated_async_client.put(
        endpoint,
        json={
            "expected_authority_revision": 0,
            "entries": [
                {
                    "entry_id": "agent_run:run-authority-run",
                    "entry_revision": 2,
                    "read_at": datetime.now(UTC).isoformat(),
                }
            ],
        },
    )
    assert first.status_code == status.HTTP_200_OK

    stale = await authenticated_async_client.put(
        endpoint,
        json={
            "expected_authority_revision": 0,
            "entries": [
                {
                    "entry_id": "agent_run:run-authority-run",
                    "entry_revision": 3,
                    "read_at": datetime.now(UTC).isoformat(),
                }
            ],
        },
    )

    assert stale.status_code == status.HTTP_409_CONFLICT
    assert stale.json()["detail"] == "Activity read-state revision conflict"
