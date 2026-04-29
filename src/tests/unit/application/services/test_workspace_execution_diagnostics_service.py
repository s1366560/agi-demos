from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from src.application.services.workspace_execution_diagnostics_service import (
    WorkspaceExecutionDiagnosticsService,
)
from src.domain.model.agent import ToolExecutionRecord
from src.domain.model.workspace.workspace import Workspace
from src.domain.model.workspace.workspace_member import WorkspaceMember
from src.domain.model.workspace.workspace_role import WorkspaceRole
from src.domain.model.workspace.workspace_task import WorkspaceTask, WorkspaceTaskStatus
from src.domain.model.workspace.workspace_task_session_attempt import (
    WorkspaceTaskSessionAttempt,
    WorkspaceTaskSessionAttemptStatus,
)
from src.domain.model.workspace_plan import (
    Plan,
    PlanNode,
    PlanNodeId,
    PlanNodeKind,
    PlanStatus,
    TaskExecution,
    TaskIntent,
)
from src.domain.ports.agent.tool_executor_port import ToolExecutionStatus


class _WorkspaceRepo:
    def __init__(self, workspace: Workspace | None) -> None:
        self.workspace = workspace

    async def find_by_id(self, _workspace_id: str) -> Workspace | None:
        return self.workspace


class _MemberRepo:
    def __init__(self, member: WorkspaceMember | None) -> None:
        self.member = member

    async def find_by_workspace_and_user(
        self,
        *,
        workspace_id: str,
        user_id: str,
    ) -> WorkspaceMember | None:
        if (
            self.member
            and self.member.workspace_id == workspace_id
            and self.member.user_id == user_id
        ):
            return self.member
        return None


class _TaskRepo:
    def __init__(self, tasks: list[WorkspaceTask]) -> None:
        self.tasks = tasks

    async def find_by_workspace(
        self,
        workspace_id: str,
        status=None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[WorkspaceTask]:
        del status
        return [task for task in self.tasks if task.workspace_id == workspace_id][offset:limit]


class _AttemptRepo:
    def __init__(self, attempts_by_task: dict[str, list[WorkspaceTaskSessionAttempt]]) -> None:
        self.attempts_by_task = attempts_by_task

    async def find_by_workspace_task_id(
        self,
        workspace_task_id: str,
        *,
        statuses=None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[WorkspaceTaskSessionAttempt]:
        del statuses
        return self.attempts_by_task.get(workspace_task_id, [])[offset:limit]


class _ToolExecutionRepo:
    def __init__(self, records_by_conversation: dict[str, list[ToolExecutionRecord]]) -> None:
        self.records_by_conversation = records_by_conversation

    async def list_by_conversation(
        self,
        conversation_id: str,
        limit: int = 100,
    ) -> list[ToolExecutionRecord]:
        return self.records_by_conversation.get(conversation_id, [])[:limit]


@dataclass
class _OutboxItem:
    id: str
    workspace_id: str
    event_type: str
    status: str
    plan_id: str | None = None
    payload_json: dict[str, object] = field(default_factory=dict)
    metadata_json: dict[str, object] = field(default_factory=dict)
    attempt_count: int = 0
    max_attempts: int = 5
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    next_attempt_at: datetime | None = None
    processed_at: datetime | None = None
    created_at: datetime | None = None
    last_error: str | None = None


class _OutboxRepo:
    def __init__(self, items: list[_OutboxItem]) -> None:
        self.items = items

    async def list_by_workspace(
        self,
        workspace_id: str,
        *,
        limit: int = 50,
    ) -> list[_OutboxItem]:
        return [item for item in self.items if item.workspace_id == workspace_id][:limit]


class _PlanRepo:
    def __init__(self, plan: Plan | None) -> None:
        self.plan = plan

    async def get_by_workspace(self, workspace_id: str) -> Plan | None:
        if self.plan is not None and self.plan.workspace_id == workspace_id:
            return self.plan
        return None


def _service(
    *,
    workspace: Workspace | None,
    member: WorkspaceMember | None,
    tasks: list[WorkspaceTask],
    attempts_by_task: dict[str, list[WorkspaceTaskSessionAttempt]] | None = None,
    records_by_conversation: dict[str, list[ToolExecutionRecord]] | None = None,
    outbox_items: list[_OutboxItem] | None = None,
    plan: Plan | None = None,
) -> WorkspaceExecutionDiagnosticsService:
    return WorkspaceExecutionDiagnosticsService(
        workspace_repo=_WorkspaceRepo(workspace),
        workspace_member_repo=_MemberRepo(member),
        workspace_task_repo=_TaskRepo(tasks),
        attempt_repo=_AttemptRepo(attempts_by_task or {}),
        tool_execution_record_repo=_ToolExecutionRepo(records_by_conversation or {}),
        workspace_plan_outbox_repo=(
            _OutboxRepo(outbox_items) if outbox_items is not None else None
        ),
        workspace_plan_repo=_PlanRepo(plan) if plan is not None else None,
    )


def _workspace() -> Workspace:
    return Workspace(
        id="workspace-1",
        tenant_id="tenant-1",
        project_id="project-1",
        name="Workspace",
        created_by="user-1",
    )


def _member() -> WorkspaceMember:
    return WorkspaceMember(
        id="member-1",
        workspace_id="workspace-1",
        user_id="user-1",
        role=WorkspaceRole.VIEWER,
    )


def _task(
    task_id: str,
    title: str,
    status: WorkspaceTaskStatus,
    *,
    metadata: dict | None = None,
    blocker_reason: str | None = None,
) -> WorkspaceTask:
    now = datetime.now(UTC)
    return WorkspaceTask(
        id=task_id,
        workspace_id="workspace-1",
        title=title,
        created_by="user-1",
        status=status,
        metadata=metadata or {},
        blocker_reason=blocker_reason,
        created_at=now,
        updated_at=now,
    )


def _attempt(
    attempt_id: str,
    task_id: str,
    status: WorkspaceTaskSessionAttemptStatus,
    *,
    conversation_id: str | None = None,
    verifications: list[str] | None = None,
    summary: str | None = None,
) -> WorkspaceTaskSessionAttempt:
    return WorkspaceTaskSessionAttempt(
        id=attempt_id,
        workspace_task_id=task_id,
        root_goal_task_id="root-1",
        workspace_id="workspace-1",
        attempt_number=1,
        status=status,
        conversation_id=conversation_id,
        candidate_summary=summary,
        candidate_verifications=verifications or [],
    )


def _tool_record(
    record_id: str,
    status: ToolExecutionStatus,
    *,
    error: str | None = None,
    started_offset_seconds: int = 0,
) -> ToolExecutionRecord:
    started_at = datetime.now(UTC) + timedelta(seconds=started_offset_seconds)
    completed_at = started_at + timedelta(milliseconds=20)
    return ToolExecutionRecord(
        id=record_id,
        conversation_id="conversation-1",
        message_id="message-1",
        call_id=f"call-{record_id}",
        tool_name="bash",
        status=status,
        error=error,
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=20,
    )


def _plan_with_stale_dispatch(*, age_seconds: int = 180) -> Plan:
    plan = Plan(
        id="plan-1",
        workspace_id="workspace-1",
        goal_id=PlanNodeId("goal-1"),
        status=PlanStatus.ACTIVE,
    )
    goal = PlanNode(
        id="goal-1",
        plan_id="plan-1",
        parent_id=None,
        kind=PlanNodeKind.GOAL,
        title="Root goal",
        intent=TaskIntent.IN_PROGRESS,
    )
    plan.add_node(goal)
    plan.add_node(
        PlanNode(
            id="node-stale",
            plan_id="plan-1",
            parent_id=goal.node_id,
            kind=PlanNodeKind.TASK,
            title="Stale dispatched node",
            intent=TaskIntent.IN_PROGRESS,
            execution=TaskExecution.DISPATCHED,
            assignee_agent_id="agent-1",
            current_attempt_id="attempt-1",
            workspace_task_id="task-stale",
            updated_at=datetime.now(UTC) - timedelta(seconds=age_seconds),
        )
    )
    return plan


def _plan_with_current_task(task_id: str) -> Plan:
    plan = Plan(
        id="plan-1",
        workspace_id="workspace-1",
        goal_id=PlanNodeId("goal-1"),
        status=PlanStatus.ACTIVE,
    )
    goal = PlanNode(
        id="goal-1",
        plan_id="plan-1",
        parent_id=None,
        kind=PlanNodeKind.GOAL,
        title="Root goal",
        intent=TaskIntent.IN_PROGRESS,
    )
    plan.add_node(goal)
    plan.add_node(
        PlanNode(
            id="node-current",
            plan_id="plan-1",
            parent_id=goal.node_id,
            kind=PlanNodeKind.TASK,
            title="Current task",
            intent=TaskIntent.IN_PROGRESS,
            execution=TaskExecution.RUNNING,
            workspace_task_id=task_id,
        )
    )
    return plan


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_diagnostics_collects_structural_execution_signals() -> None:
    blocked_task = _task(
        "task-blocked",
        "Blocked task",
        WorkspaceTaskStatus.BLOCKED,
        blocker_reason="missing credentials",
    )
    adjudicating_task = _task(
        "task-adjudicating",
        "Needs review",
        WorkspaceTaskStatus.ADJUDICATING,
        metadata={"pending_leader_adjudication": True},
    )
    done_without_evidence = _task(
        "task-no-evidence",
        "No evidence",
        WorkspaceTaskStatus.DONE,
    )
    attempts = {
        "task-blocked": [
            _attempt(
                "attempt-blocked",
                "task-blocked",
                WorkspaceTaskSessionAttemptStatus.BLOCKED,
                conversation_id="conversation-1",
                summary="blocked by missing credentials",
            )
        ],
        "task-adjudicating": [
            _attempt(
                "attempt-review",
                "task-adjudicating",
                WorkspaceTaskSessionAttemptStatus.AWAITING_LEADER_ADJUDICATION,
                conversation_id="conversation-2",
                summary="ready for review",
            )
        ],
    }
    records = {
        "conversation-1": [
            _tool_record(
                "tool-failed",
                ToolExecutionStatus.FAILED,
                error="exit 1",
            )
        ]
    }

    diagnostics = await _service(
        workspace=_workspace(),
        member=_member(),
        tasks=[blocked_task, adjudicating_task, done_without_evidence],
        attempts_by_task=attempts,
        records_by_conversation=records,
    ).get_diagnostics(
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id="workspace-1",
        actor_user_id="user-1",
    )

    assert diagnostics.task_status_counts == {
        "blocked": 1,
        "adjudicating": 1,
        "done": 1,
    }
    assert diagnostics.attempt_status_counts == {
        "blocked": 1,
        "awaiting_leader_adjudication": 1,
    }
    assert diagnostics.tool_status_counts == {"failed": 1}
    assert {item["type"] for item in diagnostics.blockers} == {
        "task_blocked",
        "attempt_blocked",
        "tool_failed",
    }
    assert diagnostics.pending_adjudications == [
        {
            "task_id": "task-adjudicating",
            "title": "Needs review",
            "attempt_id": "attempt-review",
            "attempt_status": "awaiting_leader_adjudication",
            "summary": "ready for review",
        }
    ]
    assert diagnostics.evidence_gaps == [
        {
            "task_id": "task-adjudicating",
            "title": "Needs review",
            "status": "adjudicating",
            "attempt_id": "attempt-review",
            "reason": "No verification evidence or successful tool execution recorded",
        },
        {
            "task_id": "task-no-evidence",
            "title": "No evidence",
            "status": "done",
            "attempt_id": None,
            "reason": "No verification evidence or successful tool execution recorded",
        },
    ]
    assert diagnostics.recent_tool_failures[0]["id"] == "tool-failed"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_diagnostics_requires_workspace_membership() -> None:
    service = _service(
        workspace=_workspace(),
        member=None,
        tasks=[],
    )

    with pytest.raises(PermissionError, match="workspace member"):
        await service.get_diagnostics(
            tenant_id="tenant-1",
            project_id="project-1",
            workspace_id="workspace-1",
            actor_user_id="user-1",
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_done_task_latest_blocked_attempt_is_not_reported_as_blocker() -> None:
    done_task = _task(
        "task-done",
        "Done task",
        WorkspaceTaskStatus.DONE,
    )
    attempts = {
        "task-done": [
            _attempt(
                "attempt-blocked-after-done",
                "task-done",
                WorkspaceTaskSessionAttemptStatus.BLOCKED,
                summary="recovery:parent_done",
            )
        ]
    }

    diagnostics = await _service(
        workspace=_workspace(),
        member=_member(),
        tasks=[done_task],
        attempts_by_task=attempts,
    ).get_diagnostics(
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id="workspace-1",
        actor_user_id="user-1",
    )

    assert diagnostics.blockers == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_accepted_task_tool_failure_stays_recent_failure_not_blocker() -> None:
    done_task = _task(
        "task-done",
        "Recovered task",
        WorkspaceTaskStatus.DONE,
    )
    attempts = {
        "task-done": [
            _attempt(
                "attempt-accepted",
                "task-done",
                WorkspaceTaskSessionAttemptStatus.ACCEPTED,
                conversation_id="conversation-1",
                verifications=["pytest"],
            )
        ]
    }
    records = {
        "conversation-1": [
            _tool_record(
                "tool-failed",
                ToolExecutionStatus.FAILED,
                error="transient write failure",
                started_offset_seconds=1,
            ),
            _tool_record(
                "tool-success",
                ToolExecutionStatus.SUCCESS,
                started_offset_seconds=2,
            ),
        ]
    }

    diagnostics = await _service(
        workspace=_workspace(),
        member=_member(),
        tasks=[done_task],
        attempts_by_task=attempts,
        records_by_conversation=records,
    ).get_diagnostics(
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id="workspace-1",
        actor_user_id="user-1",
    )

    assert diagnostics.blockers == []
    assert diagnostics.recent_tool_failures[0]["id"] == "tool-failed"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_running_task_tool_failure_stays_recent_failure_not_blocker() -> None:
    running_task = _task(
        "task-running",
        "Running task",
        WorkspaceTaskStatus.IN_PROGRESS,
    )
    attempts = {
        "task-running": [
            _attempt(
                "attempt-running",
                "task-running",
                WorkspaceTaskSessionAttemptStatus.RUNNING,
                conversation_id="conversation-1",
            )
        ]
    }
    records = {
        "conversation-1": [
            _tool_record(
                "tool-failed",
                ToolExecutionStatus.FAILED,
                error="worker recovered on retry",
            )
        ]
    }

    diagnostics = await _service(
        workspace=_workspace(),
        member=_member(),
        tasks=[running_task],
        attempts_by_task=attempts,
        records_by_conversation=records,
    ).get_diagnostics(
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id="workspace-1",
        actor_user_id="user-1",
    )

    assert diagnostics.blockers == []
    assert diagnostics.recent_tool_failures[0]["id"] == "tool-failed"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_active_plan_filters_historical_task_blockers() -> None:
    historical_task = _task(
        "task-old",
        "Historical blocker",
        WorkspaceTaskStatus.BLOCKED,
        metadata={"task_role": "execution_task"},
        blocker_reason="stale_no_heartbeat",
    )
    current_task = _task(
        "task-current",
        "Current task",
        WorkspaceTaskStatus.IN_PROGRESS,
        metadata={"task_role": "execution_task"},
    )
    attempts = {
        "task-old": [
            _attempt(
                "attempt-old",
                "task-old",
                WorkspaceTaskSessionAttemptStatus.BLOCKED,
                summary="stale_no_heartbeat",
            )
        ],
        "task-current": [
            _attempt(
                "attempt-current",
                "task-current",
                WorkspaceTaskSessionAttemptStatus.RUNNING,
                conversation_id="conversation-1",
            )
        ],
    }

    diagnostics = await _service(
        workspace=_workspace(),
        member=_member(),
        tasks=[historical_task, current_task],
        attempts_by_task=attempts,
        plan=_plan_with_current_task("task-current"),
    ).get_diagnostics(
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id="workspace-1",
        actor_user_id="user-1",
    )

    assert diagnostics.task_status_counts == {"blocked": 1, "in_progress": 1}
    assert diagnostics.blockers == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_diagnostics_reports_outbox_blockers() -> None:
    expired_at = datetime.now(UTC) - timedelta(seconds=5)
    retry_at = datetime.now(UTC) + timedelta(minutes=2)

    diagnostics = await _service(
        workspace=_workspace(),
        member=_member(),
        tasks=[],
        outbox_items=[
            _OutboxItem(
                id="outbox-stale",
                workspace_id="workspace-1",
                plan_id="plan-1",
                event_type="worker_launch",
                status="processing",
                payload_json={"node_id": "node-1", "attempt_id": "attempt-1"},
                attempt_count=2,
                max_attempts=5,
                lease_owner="worker-a",
                lease_expires_at=expired_at,
            ),
            _OutboxItem(
                id="outbox-dead",
                workspace_id="workspace-1",
                plan_id="plan-1",
                event_type="supervisor_tick",
                status="dead_letter",
                payload_json={"node_id": "node-2"},
                attempt_count=5,
                max_attempts=5,
                next_attempt_at=retry_at,
                last_error="handler failed",
            ),
            _OutboxItem(
                id="outbox-active",
                workspace_id="workspace-1",
                event_type="worker_launch",
                status="processing",
                lease_expires_at=datetime.now(UTC) + timedelta(seconds=30),
            ),
            _OutboxItem(
                id="outbox-pending",
                workspace_id="workspace-1",
                event_type="supervisor_tick",
                status="pending",
                created_at=datetime.now(UTC) - timedelta(seconds=45),
            ),
        ],
    ).get_diagnostics(
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id="workspace-1",
        actor_user_id="user-1",
    )

    outbox_blockers = [
        blocker
        for blocker in diagnostics.blockers
        if str(blocker.get("type")).startswith("outbox_")
    ]
    assert [blocker["type"] for blocker in outbox_blockers] == [
        "outbox_stale_processing",
        "outbox_dead_letter",
        "outbox_not_draining",
    ]
    assert outbox_blockers[0]["outbox_id"] == "outbox-stale"
    assert outbox_blockers[0]["node_id"] == "node-1"
    assert outbox_blockers[0]["attempt_id"] == "attempt-1"
    assert outbox_blockers[0]["lease_expires_at"] == expired_at.isoformat()
    assert outbox_blockers[1]["outbox_id"] == "outbox-dead"
    assert outbox_blockers[1]["last_error"] == "handler failed"
    assert outbox_blockers[2]["outbox_id"] == "outbox-pending"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_diagnostics_suppresses_outbox_blocker_after_later_success() -> None:
    now = datetime.now(UTC)

    diagnostics = await _service(
        workspace=_workspace(),
        member=_member(),
        tasks=[],
        outbox_items=[
            _OutboxItem(
                id="outbox-old-dead",
                workspace_id="workspace-1",
                plan_id="plan-1",
                event_type="supervisor_tick",
                status="dead_letter",
                payload_json={"node_id": "node-1"},
                created_at=now - timedelta(minutes=3),
                processed_at=now - timedelta(minutes=3),
                last_error="old failure",
            ),
            _OutboxItem(
                id="outbox-new-success",
                workspace_id="workspace-1",
                plan_id="plan-1",
                event_type="supervisor_tick",
                status="completed",
                payload_json={"node_id": "node-1"},
                created_at=now - timedelta(minutes=1),
                processed_at=now - timedelta(minutes=1),
            ),
            _OutboxItem(
                id="outbox-current-dead",
                workspace_id="workspace-1",
                plan_id="plan-1",
                event_type="supervisor_tick",
                status="dead_letter",
                payload_json={"node_id": "node-2"},
                created_at=now - timedelta(minutes=2),
                processed_at=now - timedelta(minutes=2),
                last_error="current failure",
            ),
        ],
    ).get_diagnostics(
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id="workspace-1",
        actor_user_id="user-1",
    )

    outbox_blockers = [
        blocker
        for blocker in diagnostics.blockers
        if str(blocker.get("type")).startswith("outbox_")
    ]
    assert [blocker["outbox_id"] for blocker in outbox_blockers] == ["outbox-current-dead"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_diagnostics_reports_stale_dispatched_plan_node() -> None:
    diagnostics = await _service(
        workspace=_workspace(),
        member=_member(),
        tasks=[],
        plan=_plan_with_stale_dispatch(age_seconds=180),
    ).get_diagnostics(
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id="workspace-1",
        actor_user_id="user-1",
    )

    plan_blockers = [
        blocker
        for blocker in diagnostics.blockers
        if blocker.get("type") == "plan_node_stale_dispatch"
    ]
    assert plan_blockers == [
        {
            "plan_id": "plan-1",
            "workspace_id": "workspace-1",
            "type": "plan_node_stale_dispatch",
            "node_id": "node-stale",
            "task_id": "task-stale",
            "title": "Stale dispatched node",
            "attempt_id": "attempt-1",
            "assignee_agent_id": "agent-1",
            "intent": "in_progress",
            "execution": "dispatched",
            "age_seconds": plan_blockers[0]["age_seconds"],
            "last_activity_at": plan_blockers[0]["last_activity_at"],
            "reason": plan_blockers[0]["reason"],
        }
    ]
    assert plan_blockers[0]["age_seconds"] >= 170
