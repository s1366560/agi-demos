from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.application.services.conversation_session_projection_service import (
    ArtifactRecordAuthority,
    ConversationAuthority,
    ConversationSessionAuthoritySnapshot,
    ConversationSessionNotFoundError,
    ConversationSessionProjectionService,
    ConversationTaskAuthority,
    PendingHITLAuthority,
    ToolExecutionAuthority,
    ToolExecutionPageAuthority,
    WorkspaceAttemptAuthority,
    WorkspacePlanContextAuthority,
    WorkspacePlanNodeAuthority,
)

NOW = datetime(2026, 7, 15, 9, 0, tzinfo=UTC)


class FakeConversationSessionReader:
    def __init__(self, snapshot: ConversationSessionAuthoritySnapshot | None) -> None:
        self.snapshot = snapshot
        self.last_scope: tuple[str, str, str, str | None, str] | None = None

    async def load(
        self,
        *,
        conversation_id: str,
        tenant_id: str,
        project_id: str,
        workspace_id: str | None,
        user_id: str,
        now: datetime,
        tool_limit: int,
    ) -> ConversationSessionAuthoritySnapshot | None:
        self.last_scope = (
            conversation_id,
            tenant_id,
            project_id,
            workspace_id,
            user_id,
        )
        return self.snapshot


def conversation(*, workspace_id: str | None = "workspace-1") -> ConversationAuthority:
    return ConversationAuthority(
        id="conversation-1",
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id=workspace_id,
        linked_workspace_task_id="task-1" if workspace_id else None,
        workspace_name="Workspace One" if workspace_id else None,
        user_id="user-1",
        title="Implement the scoped session projection",
        summary=None,
        status="active",
        current_mode="build",
        conversation_mode="autonomous" if workspace_id else "single_agent",
        capability_mode="code" if workspace_id else None,
        message_count=4,
        participant_agents=("agent-1",),
        coordinator_agent_id="agent-1",
        focused_agent_id="agent-1",
        created_at=NOW - timedelta(minutes=30),
        updated_at=NOW - timedelta(minutes=1),
    )


def attempt(attempt_id: str, number: int, status: str) -> WorkspaceAttemptAuthority:
    return WorkspaceAttemptAuthority(
        id=attempt_id,
        workspace_task_id="task-1",
        root_goal_task_id="task-root",
        workspace_id="workspace-1",
        conversation_id="conversation-1",
        attempt_number=number,
        status=status,
        worker_agent_id="agent-worker",
        leader_agent_id="agent-leader",
        candidate_summary="Candidate summary",
        candidate_artifact_refs=("artifact://report",),
        candidate_verification_refs=("check://tests", "check://lint"),
        leader_feedback=None,
        adjudication_reason=None,
        created_at=NOW - timedelta(minutes=10 - number),
        updated_at=NOW - timedelta(minutes=2),
        completed_at=None,
    )


def snapshot() -> ConversationSessionAuthoritySnapshot:
    plan_node = WorkspacePlanNodeAuthority(
        id="node-1",
        plan_id="plan-1",
        workspace_task_id="task-1",
        kind="task",
        title="Implement projection",
        description="Expose only persisted authority",
        intent="in_progress",
        execution="running",
        progress={"percent": 50},
        assignee_agent_id="agent-worker",
        current_attempt_id="attempt-2",
        created_at=NOW - timedelta(minutes=20),
        updated_at=NOW - timedelta(minutes=2),
        completed_at=None,
    )
    return ConversationSessionAuthoritySnapshot(
        conversation=conversation(),
        attempts=(attempt("attempt-2", 2, "running"), attempt("attempt-1", 1, "rejected")),
        conversation_tasks=(
            ConversationTaskAuthority(
                id="checklist-1",
                conversation_id="conversation-1",
                content="Write focused tests",
                status="in_progress",
                priority="high",
                order_index=0,
                created_at=NOW - timedelta(minutes=15),
                updated_at=NOW - timedelta(minutes=3),
            ),
        ),
        workspace_plan_context=WorkspacePlanContextAuthority(
            id="plan-1",
            workspace_id="workspace-1",
            goal_id="goal-1",
            status="active",
            created_at=NOW - timedelta(minutes=25),
            updated_at=NOW - timedelta(minutes=2),
            linked_nodes=(plan_node,),
        ),
        pending_hitl=(
            PendingHITLAuthority(
                id="hitl-1",
                conversation_id="conversation-1",
                message_id="message-1",
                request_type="permission",
                question="Allow the reviewed operation?",
                options=(),
                context={},
                metadata={"hitl_type": "permission"},
                created_at=NOW - timedelta(minutes=1),
                expires_at=NOW + timedelta(minutes=4),
            ),
        ),
        has_blocking_hitl=True,
        artifact_records=(
            ArtifactRecordAuthority(
                id="artifact-record-1",
                created_at=NOW - timedelta(seconds=30),
            ),
        ),
        tool_executions=ToolExecutionPageAuthority(
            items=(
                ToolExecutionAuthority(
                    id="tool-1",
                    message_id="message-1",
                    call_id="call-1",
                    tool_name="read_file",
                    status="success",
                    error=None,
                    step_number=1,
                    sequence_number=1,
                    started_at=NOW - timedelta(minutes=4),
                    completed_at=NOW - timedelta(minutes=3),
                    duration_ms=100,
                ),
            ),
            total=3,
            failed_total=1,
        ),
    )


async def test_builds_discriminated_workspace_session_without_desktop_authority() -> None:
    reader = FakeConversationSessionReader(snapshot())
    service = ConversationSessionProjectionService(reader)

    projection = await service.get_projection(
        conversation_id="conversation-1",
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id="workspace-1",
        user_id="user-1",
        now=NOW,
    )

    assert projection.schema_version == 2
    assert projection.projection_kind == "workspace_session"
    assert (projection.authority_kind, projection.authority_id) == (
        "workspace_attempt",
        "attempt-2",
    )
    assert projection.execution.current_attempt == projection.execution.attempt_history[0]
    assert [item.id for item in projection.execution.attempt_history] == [
        "attempt-2",
        "attempt-1",
    ]
    assert projection.workspace_plan_context is not None
    linked_node = projection.workspace_plan_context.linked_nodes[0]
    assert linked_node.id == "node-1"
    assert linked_node.plan_id == "plan-1"
    assert linked_node.progress == {"percent": 50}
    assert projection.pending_hitl[0].request_type == "permission"
    assert projection.pending_hitl[0].question == "Allow the reviewed operation?"
    assert projection.pending_hitl[0].metadata == {"hitl_type": "permission"}
    assert [item.id for item in projection.artifact_records] == ["artifact-record-1"]
    assert projection.tool_execution_records.total == 3
    assert projection.tool_execution_records.truncated is True
    assert projection.evidence_summary.candidate_artifact_ref_count == 2
    assert projection.evidence_summary.candidate_verification_ref_count == 4
    assert projection.evidence_summary.artifact_record_count == 1
    assert projection.evidence_summary.failed_tool_execution_count == 1
    assert projection.capabilities.can_send_message is False
    assert projection.capabilities.allowed_actions == ["respond_to_hitl"]
    assert len(projection.snapshot_revision) == 64
    assert reader.last_scope == (
        "conversation-1",
        "tenant-1",
        "project-1",
        "workspace-1",
        "user-1",
    )

    payload = projection.model_dump(mode="json")
    serialized = str(payload)
    for forbidden in (
        "run_id",
        "permission_profile",
        "environment",
        "plan_version",
        "artifact_version",
        "tool_input",
        "tool_output",
        "response_metadata",
    ):
        assert forbidden not in serialized
    assert "revision" not in payload


async def test_standalone_session_uses_conversation_record_authority() -> None:
    standalone = ConversationSessionAuthoritySnapshot(
        conversation=conversation(workspace_id=None),
        attempts=(),
        conversation_tasks=(),
        workspace_plan_context=None,
        pending_hitl=(),
        has_blocking_hitl=False,
        artifact_records=(),
        tool_executions=ToolExecutionPageAuthority(items=(), total=0, failed_total=0),
    )

    projection = await ConversationSessionProjectionService(
        FakeConversationSessionReader(standalone)
    ).get_projection(
        conversation_id="conversation-1",
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id=None,
        user_id="user-1",
        now=NOW,
    )

    assert (projection.authority_kind, projection.authority_id) == (
        "conversation_record",
        "conversation-1",
    )
    assert projection.execution.current_attempt is None
    assert projection.capabilities.allowed_actions == ["send_message"]


async def test_hidden_blocking_hitl_revokes_send_without_claiming_response_capability() -> None:
    blocked = ConversationSessionAuthoritySnapshot(
        conversation=conversation(workspace_id=None),
        attempts=(),
        conversation_tasks=(),
        workspace_plan_context=None,
        pending_hitl=(),
        has_blocking_hitl=True,
        artifact_records=(),
        tool_executions=ToolExecutionPageAuthority(items=(), total=0, failed_total=0),
    )

    projection = await ConversationSessionProjectionService(
        FakeConversationSessionReader(blocked)
    ).get_projection(
        conversation_id="conversation-1",
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id=None,
        user_id="user-1",
        now=NOW,
    )

    assert projection.pending_hitl == []
    assert projection.capabilities.can_send_message is False
    assert projection.capabilities.can_respond_to_hitl is False
    assert projection.capabilities.allowed_actions == []


async def test_missing_complete_scope_raises_not_found() -> None:
    service = ConversationSessionProjectionService(FakeConversationSessionReader(None))

    with pytest.raises(ConversationSessionNotFoundError):
        await service.get_projection(
            conversation_id="conversation-1",
            tenant_id="tenant-1",
            project_id="project-1",
            workspace_id="workspace-1",
            user_id="user-1",
            now=NOW,
        )
