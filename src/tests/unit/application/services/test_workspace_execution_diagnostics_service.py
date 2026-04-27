from __future__ import annotations

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


def _service(
    *,
    workspace: Workspace | None,
    member: WorkspaceMember | None,
    tasks: list[WorkspaceTask],
    attempts_by_task: dict[str, list[WorkspaceTaskSessionAttempt]] | None = None,
    records_by_conversation: dict[str, list[ToolExecutionRecord]] | None = None,
) -> WorkspaceExecutionDiagnosticsService:
    return WorkspaceExecutionDiagnosticsService(
        workspace_repo=_WorkspaceRepo(workspace),
        workspace_member_repo=_MemberRepo(member),
        workspace_task_repo=_TaskRepo(tasks),
        attempt_repo=_AttemptRepo(attempts_by_task or {}),
        tool_execution_record_repo=_ToolExecutionRepo(records_by_conversation or {}),
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
