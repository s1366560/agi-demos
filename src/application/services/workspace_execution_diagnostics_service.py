"""Workspace execution diagnostics for blackboard status surfaces."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, ClassVar, cast

from src.domain.model.agent import ToolExecutionRecord
from src.domain.model.workspace.workspace import Workspace
from src.domain.model.workspace.workspace_member import WorkspaceMember
from src.domain.model.workspace.workspace_role import WorkspaceRole
from src.domain.model.workspace.workspace_task import WorkspaceTask, WorkspaceTaskStatus
from src.domain.model.workspace.workspace_task_session_attempt import (
    WorkspaceTaskSessionAttempt,
    WorkspaceTaskSessionAttemptStatus,
)
from src.domain.ports.repositories.agent_repository import ToolExecutionRecordRepository
from src.domain.ports.repositories.workspace.workspace_member_repository import (
    WorkspaceMemberRepository,
)
from src.domain.ports.repositories.workspace.workspace_repository import WorkspaceRepository
from src.domain.ports.repositories.workspace.workspace_task_repository import (
    WorkspaceTaskRepository,
)
from src.domain.ports.repositories.workspace.workspace_task_session_attempt_repository import (
    WorkspaceTaskSessionAttemptRepository,
)


def _empty_rows() -> list[dict[str, Any]]:
    return []


@dataclass(frozen=True)
class WorkspaceExecutionDiagnostics:
    """Read-only execution signals for workspace status and blackboard views."""

    workspace_id: str
    generated_at: datetime
    task_status_counts: dict[str, int]
    attempt_status_counts: dict[str, int]
    tool_status_counts: dict[str, int]
    tasks: list[dict[str, Any]] = field(default_factory=_empty_rows)
    blockers: list[dict[str, Any]] = field(default_factory=_empty_rows)
    pending_adjudications: list[dict[str, Any]] = field(default_factory=_empty_rows)
    evidence_gaps: list[dict[str, Any]] = field(default_factory=_empty_rows)
    recent_tool_failures: list[dict[str, Any]] = field(default_factory=_empty_rows)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "generated_at": self.generated_at.isoformat(),
            "task_status_counts": self.task_status_counts,
            "attempt_status_counts": self.attempt_status_counts,
            "tool_status_counts": self.tool_status_counts,
            "tasks": self.tasks,
            "blockers": self.blockers,
            "pending_adjudications": self.pending_adjudications,
            "evidence_gaps": self.evidence_gaps,
            "recent_tool_failures": self.recent_tool_failures,
        }


class WorkspaceExecutionDiagnosticsService:
    """Build structural diagnostics from durable workspace execution records."""

    _BLOCKING_ATTEMPT_STATUSES: ClassVar[set[WorkspaceTaskSessionAttemptStatus]] = {
        WorkspaceTaskSessionAttemptStatus.BLOCKED,
        WorkspaceTaskSessionAttemptStatus.REJECTED,
        WorkspaceTaskSessionAttemptStatus.CANCELLED,
    }
    _EVIDENCE_EXPECTED_STATUSES: ClassVar[set[WorkspaceTaskStatus]] = {
        WorkspaceTaskStatus.REPORTED,
        WorkspaceTaskStatus.ADJUDICATING,
        WorkspaceTaskStatus.DONE,
    }

    def __init__(
        self,
        *,
        workspace_repo: WorkspaceRepository,
        workspace_member_repo: WorkspaceMemberRepository,
        workspace_task_repo: WorkspaceTaskRepository,
        attempt_repo: WorkspaceTaskSessionAttemptRepository,
        tool_execution_record_repo: ToolExecutionRecordRepository,
    ) -> None:
        super().__init__()
        self._workspace_repo = workspace_repo
        self._workspace_member_repo = workspace_member_repo
        self._workspace_task_repo = workspace_task_repo
        self._attempt_repo = attempt_repo
        self._tool_execution_record_repo = tool_execution_record_repo

    async def get_diagnostics(
        self,
        *,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
        actor_user_id: str,
        task_limit: int = 100,
        tool_limit_per_conversation: int = 100,
    ) -> WorkspaceExecutionDiagnostics:
        workspace = await self._require_workspace_scope(
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        _ = await self._require_membership(workspace_id=workspace.id, user_id=actor_user_id)

        tasks = await self._workspace_task_repo.find_by_workspace(
            workspace_id=workspace.id,
            limit=task_limit,
            offset=0,
        )

        task_status_counts = Counter(task.status.value for task in tasks)
        attempt_status_counts: Counter[str] = Counter()
        tool_status_counts: Counter[str] = Counter()
        task_rows: list[dict[str, Any]] = []
        blockers: list[dict[str, Any]] = []
        pending_adjudications: list[dict[str, Any]] = []
        evidence_gaps: list[dict[str, Any]] = []
        recent_tool_failures: list[dict[str, Any]] = []

        for task in tasks:
            attempts = await self._attempt_repo.find_by_workspace_task_id(
                task.id,
                limit=3,
                offset=0,
            )
            attempt_status_counts.update(attempt.status.value for attempt in attempts)

            latest_attempt = attempts[0] if attempts else None
            tool_records = await self._load_tool_records(
                latest_attempt=latest_attempt,
                limit=tool_limit_per_conversation,
            )
            tool_status_counts.update(record.status.value for record in tool_records)
            recent_tool_failures.extend(self._failed_tool_rows(task, latest_attempt, tool_records))

            task_row = self._task_row(task, latest_attempt, tool_records)
            task_rows.append(task_row)
            blockers.extend(self._blocking_rows(task, latest_attempt, tool_records))
            pending_adjudications.extend(self._pending_adjudication_rows(task, latest_attempt))
            gap = self._evidence_gap_row(task, latest_attempt, tool_records)
            if gap is not None:
                evidence_gaps.append(gap)

        recent_tool_failures.sort(
            key=lambda item: str(item.get("completed_at") or ""), reverse=True
        )

        return WorkspaceExecutionDiagnostics(
            workspace_id=workspace.id,
            generated_at=datetime.now(UTC),
            task_status_counts=dict(task_status_counts),
            attempt_status_counts=dict(attempt_status_counts),
            tool_status_counts=dict(tool_status_counts),
            tasks=task_rows,
            blockers=blockers,
            pending_adjudications=pending_adjudications,
            evidence_gaps=evidence_gaps,
            recent_tool_failures=recent_tool_failures[:10],
        )

    async def _load_tool_records(
        self,
        *,
        latest_attempt: WorkspaceTaskSessionAttempt | None,
        limit: int,
    ) -> list[ToolExecutionRecord]:
        if latest_attempt is None or not latest_attempt.conversation_id:
            return []
        return await self._tool_execution_record_repo.list_by_conversation(
            latest_attempt.conversation_id,
            limit=limit,
        )

    def _task_row(
        self,
        task: WorkspaceTask,
        latest_attempt: WorkspaceTaskSessionAttempt | None,
        tool_records: list[ToolExecutionRecord],
    ) -> dict[str, Any]:
        latest_tool = max(tool_records, key=lambda item: item.started_at, default=None)
        return {
            "task_id": task.id,
            "title": task.title,
            "status": task.status.value,
            "priority": task.priority.value,
            "blocker_reason": task.blocker_reason,
            "current_attempt_id": self._metadata_str(task, "current_attempt_id"),
            "latest_attempt_id": latest_attempt.id if latest_attempt else None,
            "latest_attempt_status": latest_attempt.status.value if latest_attempt else None,
            "latest_attempt_conversation_id": (
                latest_attempt.conversation_id if latest_attempt else None
            ),
            "pending_leader_adjudication": self._is_pending_adjudication(
                task,
                latest_attempt,
            ),
            "last_worker_report_summary": self._metadata_str(
                task,
                "last_worker_report_summary",
            ),
            "verification_count": self._verification_count(task, latest_attempt),
            "tool_execution_count": len(tool_records),
            "failed_tool_count": sum(
                1 for record in tool_records if record.status.value == "failed"
            ),
            "latest_tool": self._tool_row(latest_tool) if latest_tool else None,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        }

    def _blocking_rows(
        self,
        task: WorkspaceTask,
        latest_attempt: WorkspaceTaskSessionAttempt | None,
        tool_records: list[ToolExecutionRecord],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if task.status is WorkspaceTaskStatus.BLOCKED:
            rows.append(
                {
                    "type": "task_blocked",
                    "task_id": task.id,
                    "title": task.title,
                    "reason": task.blocker_reason or self._metadata_str(task, "blocker_reason"),
                }
            )
        if (
            task.status is not WorkspaceTaskStatus.DONE
            and latest_attempt is not None
            and latest_attempt.status in self._BLOCKING_ATTEMPT_STATUSES
        ):
            rows.append(
                {
                    "type": "attempt_blocked",
                    "task_id": task.id,
                    "title": task.title,
                    "attempt_id": latest_attempt.id,
                    "attempt_status": latest_attempt.status.value,
                    "reason": latest_attempt.leader_feedback
                    or latest_attempt.adjudication_reason
                    or latest_attempt.candidate_summary,
                }
            )
        for record in tool_records:
            if record.status.value == "failed":
                rows.append(
                    {
                        "type": "tool_failed",
                        "task_id": task.id,
                        "title": task.title,
                        "attempt_id": latest_attempt.id if latest_attempt else None,
                        "tool_execution_id": record.id,
                        "tool_name": record.tool_name,
                        "reason": record.error,
                    }
                )
        return rows

    def _pending_adjudication_rows(
        self,
        task: WorkspaceTask,
        latest_attempt: WorkspaceTaskSessionAttempt | None,
    ) -> list[dict[str, Any]]:
        if not self._is_pending_adjudication(task, latest_attempt):
            return []
        return [
            {
                "task_id": task.id,
                "title": task.title,
                "attempt_id": latest_attempt.id if latest_attempt else None,
                "attempt_status": latest_attempt.status.value if latest_attempt else None,
                "summary": latest_attempt.candidate_summary if latest_attempt else None,
            }
        ]

    def _evidence_gap_row(
        self,
        task: WorkspaceTask,
        latest_attempt: WorkspaceTaskSessionAttempt | None,
        tool_records: list[ToolExecutionRecord],
    ) -> dict[str, Any] | None:
        if task.status not in self._EVIDENCE_EXPECTED_STATUSES:
            return None
        if self._verification_count(task, latest_attempt) > 0:
            return None
        if any(record.status.value == "success" for record in tool_records):
            return None
        return {
            "task_id": task.id,
            "title": task.title,
            "status": task.status.value,
            "attempt_id": latest_attempt.id if latest_attempt else None,
            "reason": "No verification evidence or successful tool execution recorded",
        }

    def _failed_tool_rows(
        self,
        task: WorkspaceTask,
        latest_attempt: WorkspaceTaskSessionAttempt | None,
        tool_records: list[ToolExecutionRecord],
    ) -> list[dict[str, Any]]:
        return [
            {
                "task_id": task.id,
                "title": task.title,
                "attempt_id": latest_attempt.id if latest_attempt else None,
                **self._tool_row(record),
            }
            for record in tool_records
            if record.status.value == "failed"
        ]

    @staticmethod
    def _tool_row(record: ToolExecutionRecord) -> dict[str, Any]:
        return {
            "id": record.id,
            "call_id": record.call_id,
            "tool_name": record.tool_name,
            "status": record.status.value,
            "error": record.error,
            "duration_ms": record.duration_ms,
            "started_at": record.started_at.isoformat() if record.started_at else None,
            "completed_at": record.completed_at.isoformat() if record.completed_at else None,
        }

    def _is_pending_adjudication(
        self,
        task: WorkspaceTask,
        latest_attempt: WorkspaceTaskSessionAttempt | None,
    ) -> bool:
        if task.metadata.get("pending_leader_adjudication") is True:
            return True
        return (
            latest_attempt is not None
            and latest_attempt.status
            is WorkspaceTaskSessionAttemptStatus.AWAITING_LEADER_ADJUDICATION
        )

    @staticmethod
    def _verification_count(
        task: WorkspaceTask,
        latest_attempt: WorkspaceTaskSessionAttempt | None,
    ) -> int:
        report_verifications = task.metadata.get("last_worker_report_verifications")
        report_items: list[object] = (
            cast(list[object], report_verifications)
            if isinstance(report_verifications, list)
            else []
        )
        task_count = sum(1 for item in report_items if isinstance(item, str) and item)
        attempt_count = (
            len(latest_attempt.candidate_verifications) if latest_attempt is not None else 0
        )
        return task_count + attempt_count

    @staticmethod
    def _metadata_str(task: WorkspaceTask, key: str) -> str | None:
        value = task.metadata.get(key)
        return value if isinstance(value, str) and value else None

    async def _require_workspace_scope(
        self,
        *,
        tenant_id: str,
        project_id: str,
        workspace_id: str,
    ) -> Workspace:
        workspace = await self._workspace_repo.find_by_id(workspace_id)
        if workspace is None:
            raise ValueError(f"Workspace {workspace_id} not found")
        if workspace.tenant_id != tenant_id or workspace.project_id != project_id:
            raise ValueError("Workspace does not belong to tenant/project scope")
        return workspace

    async def _require_membership(self, *, workspace_id: str, user_id: str) -> WorkspaceMember:
        member = await self._workspace_member_repo.find_by_workspace_and_user(
            workspace_id=workspace_id,
            user_id=user_id,
        )
        if member is None or self._role_weight(member.role) < self._role_weight(
            WorkspaceRole.VIEWER
        ):
            raise PermissionError("User must be a workspace member")
        return member

    @staticmethod
    def _role_weight(role: WorkspaceRole) -> int:
        if role == WorkspaceRole.OWNER:
            return 300
        if role == WorkspaceRole.EDITOR:
            return 200
        return 100
