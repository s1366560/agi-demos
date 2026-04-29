"""Tests for workspace plan snapshot routes."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace_plan import (
    FeatureCheckpoint,
    Plan,
    PlanNode,
    PlanNodeId,
    PlanNodeKind,
    PlanStatus,
    TaskExecution,
    TaskIntent,
)
from src.domain.ports.services.blackboard_port import BlackboardEntry
from src.infrastructure.adapters.primary.web.routers import workspace_plans
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    Project as DBProject,
    Tenant as DBTenant,
    User,
    WorkspaceModel,
    WorkspaceTaskModel,
    WorkspaceTaskSessionAttemptModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_plan_repository import SqlPlanRepository
from src.infrastructure.adapters.secondary.persistence.sql_workspace_plan_blackboard import (
    SqlWorkspacePlanBlackboard,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_plan_events import (
    SqlWorkspacePlanEventRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_plan_outbox import (
    SqlWorkspacePlanOutboxRepository,
)


class _WorkspaceServiceStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def get_workspace(self, *, workspace_id: str, actor_user_id: str) -> object:
        self.calls.append((workspace_id, actor_user_id))
        return object()


async def _seed_workspace(db_session: AsyncSession, workspace_id: str) -> None:
    db_session.add_all(
        [
            User(
                id="plan-api-user",
                email="plan-api-user@example.com",
                full_name="Plan API User",
                hashed_password="hash",
                is_active=True,
            ),
            DBTenant(
                id="plan-api-tenant",
                name="Plan API Tenant",
                slug="plan-api-tenant",
                description="",
                owner_id="plan-api-user",
                plan="free",
                max_projects=10,
                max_users=10,
                max_storage=1,
            ),
            DBProject(
                id="plan-api-project",
                tenant_id="plan-api-tenant",
                name="Plan API Project",
                description="",
                owner_id="plan-api-user",
                memory_rules={},
                graph_config={},
                sandbox_type="cloud",
                sandbox_config={},
                is_public=False,
            ),
            WorkspaceModel(
                id=workspace_id,
                tenant_id="plan-api-tenant",
                project_id="plan-api-project",
                name="Plan API Workspace",
                description="",
                created_by="plan-api-user",
                is_archived=False,
                metadata_json={},
            ),
        ]
    )
    await db_session.flush()


def _make_plan(workspace_id: str) -> Plan:
    goal_id = PlanNodeId(value="goal-api")
    task_id = PlanNodeId(value="task-api")
    plan = Plan(
        id="plan-api",
        workspace_id=workspace_id,
        goal_id=goal_id,
        status=PlanStatus.ACTIVE,
    )
    plan.nodes[goal_id] = PlanNode(
        id=goal_id.value,
        plan_id=plan.id,
        kind=PlanNodeKind.GOAL,
        title="Complete autonomous objective",
        intent=TaskIntent.IN_PROGRESS,
        execution=TaskExecution.IDLE,
    )
    plan.nodes[task_id] = PlanNode(
        id=task_id.value,
        plan_id=plan.id,
        parent_id=goal_id,
        kind=PlanNodeKind.TASK,
        title="Implement durable supervisor",
        intent=TaskIntent.IN_PROGRESS,
        execution=TaskExecution.DISPATCHED,
        assignee_agent_id="agent-api",
        priority=4,
        feature_checkpoint=FeatureCheckpoint(
            feature_id="feature-api",
            sequence=1,
            title="Implement durable supervisor",
            expected_artifacts=("docs/sprint.md",),
        ),
        metadata={
            "iteration_index": 1,
            "iteration_phase": "implement",
            "iteration_loop": "scrum_feedback_loop_v1",
            "write_set": ["src/runtime/supervisor.py"],
        },
    )
    return plan


@pytest.mark.asyncio
async def test_get_workspace_plan_snapshot_returns_plan_blackboard_and_outbox(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = "workspace-plan-api"
    await _seed_workspace(db_session, workspace_id)
    plan = _make_plan(workspace_id)
    await SqlPlanRepository(db_session).save(plan)
    await SqlWorkspacePlanBlackboard(db_session).put(
        BlackboardEntry(
            plan_id=plan.id,
            key="artifact.spec",
            value={"path": "docs/spec.md"},
            published_by="planner",
            schema_ref="schema://artifact/v1",
        )
    )
    await SqlWorkspacePlanOutboxRepository(db_session).enqueue(
        plan_id=plan.id,
        workspace_id=workspace_id,
        event_type="supervisor_tick",
        payload={"workspace_id": workspace_id},
    )
    await SqlWorkspacePlanEventRepository(db_session).append(
        plan_id=plan.id,
        workspace_id=workspace_id,
        node_id="task-api",
        attempt_id="attempt-api",
        event_type="verification_completed",
        source="workspace_plan_verifier",
        payload={"passed": True, "summary": "verified"},
    )
    await db_session.commit()

    workspace_service = _WorkspaceServiceStub()
    monkeypatch.setattr(
        workspace_plans,
        "_get_workspace_service",
        lambda _request, _db: workspace_service,
    )

    response = await workspace_plans.get_workspace_plan_snapshot(
        workspace_id=workspace_id,
        request=cast(Request, SimpleNamespace()),
        outbox_limit=5,
        event_limit=5,
        current_user=cast(User, SimpleNamespace(id="plan-api-user")),
        db=db_session,
    )

    assert workspace_service.calls == [(workspace_id, "plan-api-user")]
    assert response.plan is not None
    assert response.plan.id == plan.id
    assert response.plan.status == "active"
    assert [node.title for node in response.plan.nodes] == [
        "Complete autonomous objective",
        "Implement durable supervisor",
    ]
    assert response.blackboard[0].key == "artifact.spec"
    assert response.blackboard[0].value == {"path": "docs/spec.md"}
    assert response.blackboard[0].version == 1
    assert response.outbox[0].event_type == "supervisor_tick"
    assert response.outbox[0].status == "pending"
    assert response.outbox[0].actions["retry_outbox"].enabled is False
    assert response.events[0].event_type == "verification_completed"
    assert response.events[0].payload["summary"] == "verified"
    assert response.iteration is not None
    assert response.iteration.current_iteration == 1
    assert response.iteration.active_phase == "implement"
    assert response.iteration.task_count == 1
    assert "docs/sprint.md" in response.iteration.deliverables
    assert "src/runtime/supervisor.py" in response.iteration.deliverables
    task_node = next(node for node in response.plan.nodes if node.id == "task-api")
    assert task_node.feature_checkpoint is not None
    assert task_node.feature_checkpoint["feature_id"] == "feature-api"
    assert task_node.actions["request_replan"].enabled is True
    assert task_node.actions["reopen_blocked"].enabled is False


@pytest.mark.asyncio
async def test_stale_plan_node_recovery_enqueues_handoff_resume(
    db_session: AsyncSession,
) -> None:
    workspace_id = "workspace-plan-api-stale"
    await _seed_workspace(db_session, workspace_id)
    plan = _make_plan(workspace_id)
    task_node_id = PlanNodeId(value="task-api")
    stale_node = replace(
        plan.nodes[task_node_id],
        execution=TaskExecution.RUNNING,
        workspace_task_id="workspace-task-api",
        assignee_agent_id="agent-api",
        current_attempt_id="attempt-stale",
    )
    plan.nodes[task_node_id] = stale_node
    await SqlPlanRepository(db_session).save(plan)
    await db_session.commit()

    enqueued = await workspace_plans._enqueue_stale_plan_node_recovery(
        session=db_session,
        workspace_id=workspace_id,
        plan=plan,
        nodes=[stale_node],
        actor_id="plan-api-user",
    )

    assert enqueued == 1
    outbox = await SqlWorkspacePlanOutboxRepository(db_session).list_by_workspace(
        workspace_id, limit=5
    )
    assert outbox[0].event_type == "handoff_resume"
    assert outbox[0].payload_json["node_id"] == "task-api"
    assert outbox[0].payload_json["force_schedule"] is True
    events = await SqlWorkspacePlanEventRepository(db_session).list_recent(
        plan.id,
        limit=5,
    )
    assert events[0].event_type == "auto_stale_node_recovery_queued"


def test_stale_plan_node_snapshot_recovery_uses_longer_running_grace() -> None:
    plan = _make_plan("workspace-plan-api-stale-grace")
    task_node_id = PlanNodeId(value="task-api")
    updated_at = datetime.now(UTC) - timedelta(seconds=300)

    plan.nodes[task_node_id] = replace(
        plan.nodes[task_node_id],
        execution=TaskExecution.RUNNING,
        updated_at=updated_at,
    )

    assert workspace_plans._stale_running_nodes(plan) == []

    plan.nodes[task_node_id] = replace(
        plan.nodes[task_node_id],
        execution=TaskExecution.DISPATCHED,
        updated_at=updated_at,
    )

    assert [node.id for node in workspace_plans._stale_running_nodes(plan)] == ["task-api"]


@pytest.mark.asyncio
async def test_snapshot_recovery_skips_stale_node_with_live_worker(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = "workspace-plan-api-live-worker"
    await _seed_workspace(db_session, workspace_id)
    db_session.add_all(
        [
            WorkspaceTaskModel(
                id="root-api",
                workspace_id=workspace_id,
                title="Root",
                description="",
                created_by="plan-api-user",
                status="in_progress",
                metadata_json={},
            ),
            WorkspaceTaskModel(
                id="workspace-task-api",
                workspace_id=workspace_id,
                title="Task",
                description="",
                created_by="plan-api-user",
                status="in_progress",
                metadata_json={},
            ),
            Conversation(
                id="conversation-live",
                project_id="plan-api-project",
                tenant_id="plan-api-tenant",
                user_id="plan-api-user",
                title="Worker",
                status="active",
            ),
            WorkspaceTaskSessionAttemptModel(
                id="attempt-live",
                workspace_task_id="workspace-task-api",
                root_goal_task_id="root-api",
                workspace_id=workspace_id,
                attempt_number=1,
                status="running",
                conversation_id="conversation-live",
            ),
        ]
    )
    plan = _make_plan(workspace_id)
    task_node_id = PlanNodeId(value="task-api")
    plan.nodes[task_node_id] = replace(
        plan.nodes[task_node_id],
        execution=TaskExecution.RUNNING,
        updated_at=datetime.now(UTC)
        - timedelta(seconds=workspace_plans._SNAPSHOT_RECOVERY_RUNNING_STALE_SECONDS + 1),
        workspace_task_id="workspace-task-api",
        current_attempt_id="attempt-live",
    )
    await db_session.flush()

    class _Redis:
        async def exists(self, key: str) -> int:
            return 1 if key == "agent:running:conversation-live" else 0

    monkeypatch.setattr(
        "src.infrastructure.agent.state.agent_worker_state.get_redis_client",
        AsyncMock(return_value=_Redis()),
    )

    stale_nodes = workspace_plans._stale_running_nodes(plan)

    assert [node.id for node in stale_nodes] == ["task-api"]
    assert (
        await workspace_plans._nodes_without_live_worker(
            session=db_session,
            nodes=stale_nodes,
        )
        == []
    )


@pytest.mark.asyncio
async def test_get_workspace_plan_snapshot_includes_root_closure_state(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = "workspace-plan-api-root"
    await _seed_workspace(db_session, workspace_id)
    plan = _make_plan(workspace_id)
    task_node_id = PlanNodeId(value="task-api")
    plan.nodes[task_node_id] = replace(plan.nodes[task_node_id], workspace_task_id="child-api")
    await SqlPlanRepository(db_session).save(plan)
    db_session.add_all(
        [
            WorkspaceTaskModel(
                id="root-api",
                workspace_id=workspace_id,
                title="Complete root",
                description="",
                created_by="plan-api-user",
                status="in_progress",
                priority=0,
                metadata_json={
                    "autonomy_schema_version": 1,
                    "task_role": "goal_root",
                    "goal_origin": "human_defined",
                    "goal_source_refs": ["api:test"],
                    "remediation_status": "ready_for_completion",
                    "remediation_summary": "goal_evidence.verification_grade must be pass",
                    "goal_evidence": {
                        "goal_task_id": "root-api",
                        "goal_text_snapshot": "Complete root",
                        "outcome_status": "achieved",
                        "summary": "stale failure",
                        "artifacts": ["artifact:file-1"],
                        "verifications": ["child_report_not_completed:child-api:blocked"],
                        "generated_by_agent_id": "leader-api",
                        "recorded_at": "2026-04-16T03:00:00Z",
                        "verification_grade": "fail",
                    },
                },
            ),
            WorkspaceTaskModel(
                id="child-api",
                workspace_id=workspace_id,
                title="Child task",
                description="",
                created_by="plan-api-user",
                status="done",
                priority=0,
                metadata_json={
                    "autonomy_schema_version": 1,
                    "task_role": "execution_task",
                    "root_goal_task_id": "root-api",
                    "lineage_source": "agent",
                },
            ),
        ]
    )
    await db_session.commit()

    workspace_service = _WorkspaceServiceStub()
    monkeypatch.setattr(
        workspace_plans,
        "_get_workspace_service",
        lambda _request, _db: workspace_service,
    )

    response = await workspace_plans.get_workspace_plan_snapshot(
        workspace_id=workspace_id,
        request=cast(Request, SimpleNamespace()),
        outbox_limit=5,
        event_limit=5,
        current_user=cast(User, SimpleNamespace(id="plan-api-user")),
        db=db_session,
    )

    assert response.root_goal is not None
    assert response.root_goal.id == "root-api"
    assert response.root_goal.status == "in_progress"
    assert response.root_goal.remediation_status == "ready_for_completion"
    assert response.root_goal.evidence_grade == "fail"
    assert response.root_goal.completion_blocker_reason == (
        "goal_evidence.verification_grade must be pass"
    )


@pytest.mark.asyncio
async def test_get_workspace_plan_snapshot_returns_empty_state_without_plan(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = "workspace-plan-api-empty"
    await _seed_workspace(db_session, workspace_id)
    await db_session.commit()

    workspace_service = _WorkspaceServiceStub()
    monkeypatch.setattr(
        workspace_plans,
        "_get_workspace_service",
        lambda _request, _db: workspace_service,
    )

    response = await workspace_plans.get_workspace_plan_snapshot(
        workspace_id=workspace_id,
        request=cast(Request, SimpleNamespace()),
        outbox_limit=5,
        event_limit=5,
        current_user=cast(User, SimpleNamespace(id="plan-api-user")),
        db=db_session,
    )

    assert workspace_service.calls == [(workspace_id, "plan-api-user")]
    assert response.workspace_id == workspace_id
    assert response.plan is None
    assert response.blackboard == []
    assert response.outbox == []
    assert response.events == []


@pytest.mark.asyncio
async def test_retry_workspace_plan_outbox_item_queues_failed_job(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = "workspace-plan-api-retry"
    await _seed_workspace(db_session, workspace_id)
    plan = _make_plan(workspace_id)
    await SqlPlanRepository(db_session).save(plan)
    outbox_repo = SqlWorkspacePlanOutboxRepository(db_session)
    item = await outbox_repo.enqueue(
        plan_id=plan.id,
        workspace_id=workspace_id,
        event_type="supervisor_tick",
        payload={"workspace_id": workspace_id},
        max_attempts=1,
    )
    claimed = await outbox_repo.claim_due(limit=1, lease_owner="worker-a")
    assert [claimed_item.id for claimed_item in claimed] == [item.id]
    assert await outbox_repo.mark_failed(item.id, "worker failed") is True
    await db_session.commit()

    workspace_service = _WorkspaceServiceStub()
    monkeypatch.setattr(
        workspace_plans,
        "_get_workspace_service",
        lambda _request, _db: workspace_service,
    )

    result = await workspace_plans.retry_workspace_plan_outbox_item(
        workspace_id=workspace_id,
        outbox_id=item.id,
        body=workspace_plans.WorkspacePlanActionRequest(reason="fixed input"),
        request=cast(Request, SimpleNamespace()),
        current_user=cast(User, SimpleNamespace(id="plan-api-user")),
        db=db_session,
    )

    assert result.ok is True
    assert result.outbox_id == item.id
    loaded = await outbox_repo.get_by_id(item.id)
    assert loaded is not None
    assert loaded.status == "pending"
    assert loaded.attempt_count == 0
    assert loaded.metadata_json["operator_retry"]["reason"] == "fixed input"
    events = await SqlWorkspacePlanEventRepository(db_session).list_recent(plan.id, limit=5)
    assert events[0].event_type == "operator_retry_outbox"
    assert events[0].payload["outbox_id"] == item.id


@pytest.mark.asyncio
async def test_request_workspace_plan_node_replan_resets_node_and_schedules_tick(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = "workspace-plan-api-replan"
    await _seed_workspace(db_session, workspace_id)
    plan = _make_plan(workspace_id)
    await SqlPlanRepository(db_session).save(plan)
    await db_session.commit()

    workspace_service = _WorkspaceServiceStub()
    monkeypatch.setattr(
        workspace_plans,
        "_get_workspace_service",
        lambda _request, _db: workspace_service,
    )
    published: list[dict[str, object]] = []

    async def fake_publish_workspace_event(
        _redis_client: object,
        *,
        workspace_id: str,
        event_type: object,
        payload: dict[str, object],
        metadata: dict[str, object] | None = None,
        correlation_id: str | None = None,
    ) -> None:
        published.append(
            {
                "workspace_id": workspace_id,
                "event_type": event_type,
                "payload": payload,
                "metadata": metadata or {},
                "correlation_id": correlation_id or "",
            }
        )

    monkeypatch.setattr(
        workspace_plans,
        "publish_workspace_event",
        fake_publish_workspace_event,
    )
    request = cast(
        Request,
        SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(container=SimpleNamespace(redis_client=object()))
            )
        ),
    )

    result = await workspace_plans.request_workspace_plan_node_replan(
        workspace_id=workspace_id,
        node_id="task-api",
        body=workspace_plans.WorkspacePlanActionRequest(reason="scope changed"),
        request=request,
        current_user=cast(User, SimpleNamespace(id="plan-api-user")),
        db=db_session,
    )

    assert result.ok is True
    assert result.node_id == "task-api"
    loaded_plan = await SqlPlanRepository(db_session).get(plan.id)
    assert loaded_plan is not None
    node = loaded_plan.nodes[PlanNodeId(value="task-api")]
    assert node.intent is TaskIntent.TODO
    assert node.execution is TaskExecution.IDLE
    assert node.metadata["operator_action"]["reason"] == "scope changed"
    events = await SqlWorkspacePlanEventRepository(db_session).list_recent(plan.id, limit=5)
    assert events[0].event_type == "operator_replan_requested"
    assert published == [
        {
            "workspace_id": workspace_id,
            "event_type": workspace_plans.AgentEventType.WORKSPACE_PLAN_UPDATED,
            "payload": {
                "workspace_id": workspace_id,
                "plan_id": plan.id,
                "action": "operator_replan_requested",
                "node_id": "task-api",
                "reason": "scope changed",
            },
            "metadata": {
                "source": "workspace_plan_api",
                "action": "operator_replan_requested",
            },
            "correlation_id": plan.id,
        }
    ]
    outbox_snapshot = await workspace_plans.get_workspace_plan_snapshot(
        workspace_id=workspace_id,
        request=cast(Request, SimpleNamespace()),
        outbox_limit=5,
        event_limit=5,
        current_user=cast(User, SimpleNamespace(id="plan-api-user")),
        db=db_session,
    )
    assert outbox_snapshot.outbox[0].event_type == "supervisor_tick"
    assert outbox_snapshot.outbox[0].metadata["source"] == "operator_action"


__all__: list[str] = []
