"""Terminal canonical runs do not restore retired session runtimes on subscribe."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.infrastructure.adapters.primary.web.websocket import scoped_session_admission_v2
from src.infrastructure.adapters.primary.web.websocket.handlers import subscription_handler
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent,
    AgentRunAuthorityModel,
    Conversation,
)

pytestmark = pytest.mark.unit


async def _case(db, project, user, statuses):
    conversation = Conversation(
        id=str(uuid4()),
        tenant_id=project.tenant_id,
        project_id=project.id,
        user_id=user.id,
        title="Subscription preflight",
    )
    db.add(conversation)
    run_ids = []
    for status in statuses:
        run_id = str(uuid4())
        run_ids.append(run_id)
        db.add(
            AgentRunAuthorityModel(
                id=run_id,
                tenant_id=conversation.tenant_id,
                project_id=conversation.project_id,
                conversation_id=conversation.id,
                run_kind="chat",
                idempotency_key=run_id,
                message_id=run_id,
                request_message="Preflight",
                status=status,
                permission_profile="read_only",
                authorization_snapshot={},
            )
        )
    await db.commit()
    return SimpleNamespace(db=db, tenant_id=project.tenant_id, run_ids=run_ids), conversation


@pytest.mark.parametrize(
    ("statuses", "terminal"),
    [
        ([], False),
        (["cancelled"], True),
        (["completed"], True),
        (["failed"], True),
        (["ready_review"], True),
        (["completed", "cancelled"], True),
        (["cancelled", "queued"], False),
        (["running", "cancelled"], False),
        (["paused"], False),
        (["unrecognized"], False),
    ],
)
async def test_terminal_preflight_uses_all_canonical_run_states(
    test_db, test_project_db, test_user, statuses, terminal
):
    context, conversation = await _case(test_db, test_project_db, test_user, statuses)
    result = await scoped_session_admission_v2.scoped_session_has_only_terminal_runs_v2(
        context, conversation_id=conversation.id, project_id=conversation.project_id
    )
    assert result is terminal


@pytest.mark.parametrize("field", ["tenant_id", "project_id", "conversation_id"])
async def test_terminal_preflight_never_reads_another_scope(
    test_db, test_project_db, test_user, field
):
    context, conversation = await _case(test_db, test_project_db, test_user, ["cancelled"])
    arguments = {"conversation_id": conversation.id, "project_id": conversation.project_id}
    if field == "tenant_id":
        context.tenant_id = "another-tenant"
    else:
        arguments[field] = "another-scope"
    assert not await scoped_session_admission_v2.scoped_session_has_only_terminal_runs_v2(
        context, **arguments
    )


async def test_cancelled_subscription_skips_exact_bundle_restoration(
    test_db, test_project_db, test_user, monkeypatch, caplog
):
    context, conversation = await _case(test_db, test_project_db, test_user, ["cancelled"])
    acquire = AsyncMock(side_effect=RuntimeError("Bundle differs from its exact reference"))
    monkeypatch.setattr(subscription_handler, "acquire_existing_scoped_session_v2", acquire)
    await subscription_handler._maybe_start_recovery_bridge(
        context, conversation.id, conversation.project_id, {}
    )
    acquire.assert_not_awaited()
    assert "Failed to start recovery bridge" not in caplog.text


@pytest.mark.parametrize("latest_message", ["canonical", "legacy", None])
async def test_new_legacy_activity_keeps_pinned_recovery_after_terminal_canonical_run(
    test_db, test_project_db, test_user, latest_message
):
    context, conversation = await _case(test_db, test_project_db, test_user, ["completed"])
    message_id = context.run_ids[0] if latest_message == "canonical" else latest_message
    test_db.add(
        AgentExecutionEvent(
            id=str(uuid4()),
            conversation_id=conversation.id,
            message_id=message_id,
            event_type="text_delta",
            event_data={"delta": "Latest activity"},
            event_time_us=1000,
            event_counter=0,
        )
    )
    await test_db.commit()
    result = await scoped_session_admission_v2.scoped_session_has_only_terminal_runs_v2(
        context, conversation_id=conversation.id, project_id=conversation.project_id
    )
    assert result is (latest_message == "canonical")
