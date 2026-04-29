"""Workspace execution diagnostics for blackboard status surfaces."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, ClassVar, Protocol, cast

from src.domain.model.agent import ToolExecutionRecord
from src.domain.model.workspace.workspace import Workspace
from src.domain.model.workspace.workspace_member import WorkspaceMember
from src.domain.model.workspace.workspace_role import WorkspaceRole
from src.domain.model.workspace.workspace_task import WorkspaceTask, WorkspaceTaskStatus
from src.domain.model.workspace.workspace_task_session_attempt import (
    WorkspaceTaskSessionAttempt,
    WorkspaceTaskSessionAttemptStatus,
)
from src.domain.model.workspace_plan import Plan, TaskExecution, TaskIntent
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


class WorkspacePlanOutboxDiagnosticsRepository(Protocol):
    """Read-only projection of workspace plan outbox records for diagnostics."""

    async def list_by_workspace(
        self,
        workspace_id: str,
        *,
        limit: int = 50,
    ) -> list[Any]:
        """Return recent outbox items for one workspace."""
        ...


class WorkspacePlanDiagnosticsRepository(Protocol):
    """Read-only projection of the active workspace plan for diagnostics."""

    async def get_by_workspace(self, workspace_id: str) -> Plan | None:
        """Return the active plan for one workspace, if any."""


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

    _PENDING_OUTBOX_GRACE_SECONDS: ClassVar[int] = 30
    _STALE_PLAN_DISPATCH_GRACE_SECONDS: ClassVar[int] = 90
    _STALE_PLAN_RUNNING_GRACE_SECONDS: ClassVar[int] = 900
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
        workspace_plan_outbox_repo: WorkspacePlanOutboxDiagnosticsRepository | None = None,
        workspace_plan_repo: WorkspacePlanDiagnosticsRepository | None = None,
    ) -> None:
        super().__init__()
        self._workspace_repo = workspace_repo
        self._workspace_member_repo = workspace_member_repo
        self._workspace_task_repo = workspace_task_repo
        self._attempt_repo = attempt_repo
        self._tool_execution_record_repo = tool_execution_record_repo
        self._workspace_plan_outbox_repo = workspace_plan_outbox_repo
        self._workspace_plan_repo = workspace_plan_repo

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

        blockers.extend(await self._outbox_blocker_rows(workspace.id))
        blockers.extend(await self._plan_blocker_rows(workspace.id))
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

    async def _plan_blocker_rows(self, workspace_id: str) -> list[dict[str, Any]]:
        if self._workspace_plan_repo is None:
            return []
        plan = await self._workspace_plan_repo.get_by_workspace(workspace_id)
        if plan is None:
            return []

        now = datetime.now(UTC)
        rows: list[dict[str, Any]] = []
        for node in plan.nodes.values():
            row = self._plan_node_stale_row(node, now)
            if row is not None:
                rows.append({"plan_id": plan.id, "workspace_id": workspace_id, **row})
        return rows

    def _plan_node_stale_row(
        self,
        node: object,
        now: datetime,
    ) -> dict[str, Any] | None:
        intent = getattr(node, "intent", None)
        execution = getattr(node, "execution", None)
        if intent is not TaskIntent.IN_PROGRESS:
            return None
        if execution not in {TaskExecution.DISPATCHED, TaskExecution.RUNNING}:
            return None

        last_activity = self._as_aware(getattr(node, "updated_at", None)) or self._as_aware(
            getattr(node, "created_at", None)
        )
        if last_activity is None:
            return None

        age_seconds = (now - last_activity).total_seconds()
        grace_seconds = (
            self._STALE_PLAN_DISPATCH_GRACE_SECONDS
            if execution is TaskExecution.DISPATCHED
            else self._STALE_PLAN_RUNNING_GRACE_SECONDS
        )
        if age_seconds < grace_seconds:
            return None

        row_type = (
            "plan_node_stale_dispatch"
            if execution is TaskExecution.DISPATCHED
            else "plan_node_stale_running"
        )
        return {
            "type": row_type,
            "node_id": getattr(node, "id", None),
            "task_id": getattr(node, "workspace_task_id", None),
            "title": getattr(node, "title", None),
            "attempt_id": getattr(node, "current_attempt_id", None),
            "assignee_agent_id": getattr(node, "assignee_agent_id", None),
            "intent": intent.value,
            "execution": execution.value,
            "age_seconds": int(age_seconds),
            "last_activity_at": last_activity.isoformat(),
            "reason": (
                f"Plan node has been {execution.value} for {int(age_seconds)}s "
                "without reaching a terminal worker report"
            ),
        }

    async def _outbox_blocker_rows(self, workspace_id: str) -> list[dict[str, Any]]:
        if self._workspace_plan_outbox_repo is None:
            return []
        items = await self._workspace_plan_outbox_repo.list_by_workspace(
            workspace_id,
            limit=50,
        )
        now = datetime.now(UTC)
        rows: list[dict[str, Any]] = []
        for item in items:
            row = self._outbox_blocker_row(item, now)
            if row is not None:
                rows.append(row)
        return rows

    def _outbox_blocker_row(
        self,
        item: object,
        now: datetime,
    ) -> dict[str, Any] | None:
        status = getattr(item, "status", None)
        lease_expires_at = self._as_aware(getattr(item, "lease_expires_at", None))
        if status == "processing":
            if lease_expires_at is None:
                reason = "Processing outbox item has no lease expiry"
            elif lease_expires_at <= now:
                reason = (
                    "Processing outbox item lease expired at "
                    f"{lease_expires_at.isoformat()}"
                )
            else:
                return None
            row_type = "outbox_stale_processing"
        elif status == "dead_letter":
            row_type = "outbox_dead_letter"
            reason = getattr(item, "last_error", None) or "Outbox item reached dead letter"
        elif status in {"pending", "failed"}:
            next_attempt_at = self._as_aware(getattr(item, "next_attempt_at", None))
            created_at = self._as_aware(getattr(item, "created_at", None))
            if next_attempt_at is not None and next_attempt_at > now:
                return None
            if created_at is None:
                return None
            age_seconds = (now - created_at).total_seconds()
            if age_seconds < self._PENDING_OUTBOX_GRACE_SECONDS:
                return None
            row_type = "outbox_not_draining"
            reason = (
                f"Outbox item has been due for {int(age_seconds)}s "
                "without being claimed"
            )
        else:
            return None

        payload = self._mapping(getattr(item, "payload_json", None))
        metadata = self._mapping(getattr(item, "metadata_json", None))
        row: dict[str, Any] = {
            "type": row_type,
            "outbox_id": getattr(item, "id", None),
            "plan_id": getattr(item, "plan_id", None),
            "workspace_id": getattr(item, "workspace_id", None),
            "event_type": getattr(item, "event_type", None),
            "status": status,
            "attempt_count": getattr(item, "attempt_count", None),
            "max_attempts": getattr(item, "max_attempts", None),
            "lease_owner": getattr(item, "lease_owner", None),
            "lease_expires_at": lease_expires_at.isoformat() if lease_expires_at else None,
            "next_attempt_at": self._datetime_iso(getattr(item, "next_attempt_at", None)),
            "created_at": self._datetime_iso(getattr(item, "created_at", None)),
            "last_error": getattr(item, "last_error", None),
            "reason": reason,
        }
        for key in ("node_id", "task_id", "attempt_id", "root_goal_task_id"):
            value = payload.get(key) or metadata.get(key)
            if isinstance(value, str) and value:
                row[key] = value
        return row

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

    @staticmethod
    def _mapping(value: object) -> Mapping[str, Any]:
        if isinstance(value, Mapping):
            return cast(Mapping[str, Any], value)
        return {}

    @staticmethod
    def _as_aware(value: object) -> datetime | None:
        if not isinstance(value, datetime):
            return None
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    @classmethod
    def _datetime_iso(cls, value: object) -> str | None:
        aware = cls._as_aware(value)
        return aware.isoformat() if aware is not None else None

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
