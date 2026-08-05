"""Terminal settlement contracts for canonical Cloud agent runs."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from src.infrastructure.adapters.secondary.persistence.agent_run_settlement import (
    settle_agent_plan_run,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent,
    AgentPlanRunModel,
    AgentPlanVersionModel,
    AgentRunInputModel,
    AgentRunSummaryModel,
    Conversation,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_run_authority import (
    ensure_plan_run_authority,
    mark_agent_run_running,
)


async def test_plan_run_authority_transitions_to_running_in_canonical_scope(
    test_db,
    test_project_db,
    test_user,
) -> None:
    now = datetime.now(UTC)
    conversation = Conversation(
        id="running-authority-conversation",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
        title="Running authority",
    )
    plan = AgentPlanVersionModel(
        id="running-authority-plan",
        conversation_id=conversation.id,
        version=1,
        status="approved",
        tasks_json=[],
        approved_at=now,
    )
    run = AgentPlanRunModel(
        id="running-authority-run",
        conversation_id=conversation.id,
        project_id=test_project_db.id,
        plan_version_id=plan.id,
        idempotency_key="running-authority-start",
        message_id="running-authority-message",
        request_message="Run",
        status="queued",
        revision=1,
        permission_profile="workspace_write",
        authorization_snapshot={},
        created_at=now,
        updated_at=now,
    )
    test_db.add_all([conversation, plan, run])
    await test_db.commit()
    authority = await ensure_plan_run_authority(
        test_db,
        run=run,
        tenant_id=test_project_db.tenant_id,
    )
    await test_db.commit()

    marked = await mark_agent_run_running(
        test_db,
        run_id=authority.id,
        tenant_id=test_project_db.tenant_id,
        project_id=test_project_db.id,
        conversation_id=conversation.id,
    )

    assert marked is not None
    assert marked.run_kind == "plan"
    assert marked.status == "running"
    assert marked.started_at is not None


async def test_settlement_readies_queue_blocks_unapplied_steer_and_aggregates_models(
    test_db,
    test_project_db,
    test_user,
) -> None:
    now = datetime.now(UTC)
    conversation = Conversation(
        id="settlement-conversation",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
        title="Settlement",
        status="active",
        agent_config={},
        message_count=0,
    )
    plan = AgentPlanVersionModel(
        id="settlement-plan",
        conversation_id=conversation.id,
        version=1,
        status="approved",
        tasks_json=[],
        approved_at=now,
    )
    run = AgentPlanRunModel(
        id="settlement-run",
        conversation_id=conversation.id,
        project_id=test_project_db.id,
        plan_version_id=plan.id,
        idempotency_key="settlement-start",
        message_id="settlement-message",
        request_message="Settle the run",
        status="ready_review",
        revision=4,
        permission_profile="workspace_write",
        authorization_snapshot={},
        created_at=now - timedelta(seconds=2),
        updated_at=now,
        completed_at=now,
    )
    common = {
        "tenant_id": test_project_db.tenant_id,
        "project_id": test_project_db.id,
        "conversation_id": conversation.id,
        "run_id": run.id,
        "actor_user_id": test_user.id,
        "expected_run_revision": 3,
        "payload_hash": "a" * 64,
        "references_json": [],
        "context_items_json": [],
        "sequence": 1,
        "created_at": now,
        "updated_at": now,
    }
    queued = AgentRunInputModel(
        id="settlement-queued",
        message="Next",
        message_id="settlement-queued-message",
        idempotency_key="settlement-queued-key",
        delivery="queue_next",
        status="queued",
        queue_position=1,
        **common,
    )
    pending = AgentRunInputModel(
        id="settlement-pending",
        message="Steer",
        message_id="settlement-steer-message",
        idempotency_key="settlement-steer-key",
        delivery="steer_now",
        status="pending_boundary",
        queue_position=None,
        **{**common, "sequence": 2},
    )
    events = [
        AgentExecutionEvent(
            id="settlement-cost-1",
            conversation_id=conversation.id,
            message_id=run.message_id,
            event_type="cost_update",
            event_data={
                "model": "model-a",
                "cost": 0.1,
                "tokens": {"input": 10, "output": 5},
            },
            event_time_us=1,
            event_counter=0,
        ),
        AgentExecutionEvent(
            id="settlement-cost-2",
            conversation_id=conversation.id,
            message_id=run.message_id,
            event_type="cost_update",
            event_data={
                "model": "model-a",
                "cost": 0.2,
                "tokens": {"input": 20, "output": 7},
            },
            event_time_us=2,
            event_counter=0,
        ),
        AgentExecutionEvent(
            id="settlement-complete",
            conversation_id=conversation.id,
            message_id=run.message_id,
            event_type="complete",
            event_data={
                "execution_summary": {
                    "total_cost": 0.3,
                    "total_tokens": {"input": 30, "output": 12},
                }
            },
            event_time_us=3,
            event_counter=0,
        ),
    ]
    test_db.add_all([conversation, plan, run, queued, pending, *events])
    await test_db.commit()

    await settle_agent_plan_run(
        test_db,
        run=run,
        tenant_id=test_project_db.tenant_id,
        started_at=now - timedelta(seconds=2),
        succeeded=True,
        completed_at=now,
    )
    await test_db.commit()

    assert queued.status == "ready"
    assert pending.status == "blocked"
    summary = (
        await test_db.execute(
            select(AgentRunSummaryModel).where(AgentRunSummaryModel.run_id == run.id)
        )
    ).scalar_one()
    assert summary.input_tokens == 30
    assert summary.output_tokens == 12
    assert summary.model_breakdown_json[0] == {
        "model": "model-a",
        "input_tokens": 30,
        "output_tokens": 12,
        "cost_usd": pytest.approx(0.3),
        "call_count": 2,
    }
