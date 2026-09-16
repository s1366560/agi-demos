from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from src.application.services.conversation_session_projection_service import (
    AgentPlanRunAuthority,
    AgentPlanVersionAuthority,
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
from src.application.services.session_stage import derive_execution_stage
from src.infrastructure.adapters.secondary.persistence.sql_conversation_session_projection_reader import (
    SqlConversationSessionProjectionReader,
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


def plan_run() -> AgentPlanRunAuthority:
    return AgentPlanRunAuthority(
        id="run-1",
        conversation_id="conversation-1",
        project_id="project-1",
        plan_version_id="plan-version-1",
        idempotency_key="approve-1",
        message_id="message-1",
        request_message="Implement the approved plan",
        status="running",
        revision=3,
        permission_profile="full_access",
        environment={
            "id": "sandbox-1",
            "kind": "worktree",
            "label": "sandbox-1",
            "workspace_path": "/workspace",
            "repository_root": None,
            "branch": None,
            "base_commit": None,
            "source_run_id": None,
            "created_at": (NOW - timedelta(minutes=5)).isoformat(),
        },
        created_at=NOW - timedelta(minutes=5),
        started_at=NOW - timedelta(minutes=4),
        updated_at=NOW,
        completed_at=None,
        error=None,
    )


def plan_version() -> AgentPlanVersionAuthority:
    return AgentPlanVersionAuthority(
        id="plan-version-1",
        conversation_id="conversation-1",
        version=2,
        status="draft",
        tasks=(
            {
                "id": "plan-task-1",
                "conversation_id": "conversation-1",
                "content": "Implement the authoritative plan projection",
                "status": "pending",
                "priority": "high",
                "order_index": 0,
                "created_at": (NOW - timedelta(minutes=2)).isoformat(),
                "updated_at": (NOW - timedelta(minutes=1)).isoformat(),
            },
        ),
        created_at=NOW - timedelta(minutes=2),
        approved_at=None,
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
                authority_revision=1,
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
        plan_versions=(plan_version(),),
    )


def test_malformed_permission_profile_fails_instead_of_promoting_an_older_run() -> None:
    with pytest.raises(ValueError, match="unsupported permission profile"):
        SqlConversationSessionProjectionReader._run_permission_profile("malformed")


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
    assert projection.current_plan == projection.plan_history[0]
    assert projection.current_plan is not None
    assert projection.current_plan.id == "plan-version-1"
    assert projection.current_plan.version == 2
    assert projection.current_plan.status == "draft"
    assert projection.current_plan.tasks[0]["id"] == "plan-task-1"
    assert projection.pending_hitl[0].request_type == "permission"
    assert projection.pending_hitl[0].question == "Allow the reviewed operation?"
    assert projection.pending_hitl[0].metadata == {"hitl_type": "permission"}
    assert projection.pending_hitl[0].authority_revision == 1
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
        "artifact_version",
        "tool_input",
        "tool_output",
        "response_metadata",
    ):
        assert f"'{forbidden}':" not in serialized
    assert payload["pending_hitl"][0]["authority_revision"] == 1
    assert "run_revision" not in serialized


async def test_projects_latest_persisted_run_and_exact_cloud_environment() -> None:
    reader = FakeConversationSessionReader(replace(snapshot(), runs=(plan_run(),)))
    service = ConversationSessionProjectionService(reader)

    projection = await service.get_projection(
        conversation_id="conversation-1",
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id="workspace-1",
        user_id="user-1",
        now=NOW,
    )

    assert projection.execution.current_run == projection.execution.run_history[0]
    assert projection.execution.current_run is not None
    assert projection.execution.current_run.id == "run-1"
    assert projection.execution.current_run.revision == 3
    assert projection.execution.current_run.permission_profile == "full_access"
    assert projection.execution.current_run.environment is not None
    assert projection.execution.current_run.environment.id == "sandbox-1"
    assert projection.execution.current_run.environment.workspace_path == "/workspace"
    assert projection.execution.current_run.authorization_snapshot == {
        "conversation_id": "conversation-1",
        "project_id": "project-1",
        "plan_version_id": "plan-version-1",
        "permission_profile": "full_access",
        "environment": projection.execution.current_run.environment.model_dump(mode="json"),
    }
    assert projection.updated_at == NOW


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


@pytest.mark.parametrize("status", ["queued", "running", "completed", "failed", "cancelled"])
@pytest.mark.parametrize("has_blocking_hitl", [False, True])
async def test_send_capability_requires_idle_run_and_no_blocking_hitl(
    status: str, has_blocking_hitl: bool
) -> None:
    source = replace(
        snapshot(),
        runs=(replace(plan_run(), status=status),),
        has_blocking_hitl=has_blocking_hitl,
        pending_hitl=snapshot().pending_hitl if has_blocking_hitl else (),
    )
    projection = await ConversationSessionProjectionService(
        FakeConversationSessionReader(source)
    ).get_projection(
        conversation_id="conversation-1",
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id="workspace-1",
        user_id="user-1",
        now=NOW,
    )
    can_send = not has_blocking_hitl and status not in {"queued", "running"}
    assert projection.capabilities.can_send_message is can_send
    assert ("send_message" in projection.capabilities.allowed_actions) is can_send
    assert projection.capabilities.can_respond_to_hitl is has_blocking_hitl
    assert projection.capabilities.can_control_execution is False


@pytest.mark.parametrize("run_status", [None, "queued", "running", "completed", "failed"])
@pytest.mark.parametrize("blocked", [False, True])
async def test_plan_approval_capability_requires_idle_versioned_draft(run_status, blocked) -> None:
    source = replace(
        snapshot(),
        conversation=replace(conversation(), current_mode="plan"),
        attempts=(),
        runs=() if run_status is None else (replace(plan_run(), status=run_status),),
        plan_versions=(plan_version(),),
        pending_hitl=(),
        has_blocking_hitl=blocked,
    )
    projection = await ConversationSessionProjectionService(
        FakeConversationSessionReader(source)
    ).get_projection(
        conversation_id="conversation-1",
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id="workspace-1",
        user_id="user-1",
        now=NOW,
    )
    expected = not blocked and run_status not in {"queued", "running"}
    assert projection.capabilities.can_approve_plan is expected
    assert ("approve_plan_and_start" in projection.capabilities.allowed_actions) is expected


@pytest.mark.unit
@pytest.mark.parametrize("status", ["queued", "running", "completed", "failed", "cancelled"])
@pytest.mark.parametrize("blocked", [False, True])
async def test_cloud_run_control_capability_requires_active_unparked_turn(status, blocked):
    source = replace(
        snapshot(),
        attempts=(),
        runs=(replace(plan_run(), status=status),),
        has_blocking_hitl=blocked,
        pending_hitl=snapshot().pending_hitl if blocked else (),
    )
    projection = await ConversationSessionProjectionService(
        FakeConversationSessionReader(source)
    ).get_projection(
        conversation_id="conversation-1",
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id="workspace-1",
        user_id="user-1",
        now=NOW,
    )
    expected = status in {"queued", "running"} and not blocked
    assert projection.capabilities.can_control_execution is expected
    assert ("cancel" in projection.capabilities.allowed_actions) is expected


# --- execution_stage derivation matrix --------------------------------------


def stage_snapshot(**overrides: object) -> ConversationSessionAuthoritySnapshot:
    base = ConversationSessionAuthoritySnapshot(
        conversation=replace(conversation(), current_mode="plan", message_count=0),
        attempts=(),
        conversation_tasks=(),
        workspace_plan_context=None,
        pending_hitl=(),
        has_blocking_hitl=False,
        artifact_records=(),
        tool_executions=ToolExecutionPageAuthority(items=(), total=0, failed_total=0),
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def pending_task() -> ConversationTaskAuthority:
    return ConversationTaskAuthority(
        id="checklist-1",
        conversation_id="conversation-1",
        content="Write focused tests",
        status="pending",
        priority="high",
        order_index=0,
        created_at=NOW - timedelta(minutes=15),
        updated_at=None,
    )


@pytest.mark.parametrize(
    ("stage_snapshot_overrides", "expected"),
    [
        # fresh session: no runs/plans/tasks and no messages -> no stage
        ({}, None),
        # plan mode with a draft plan -> understand
        ({"plan_versions": (plan_version(),)}, "understand"),
        # any conversation activity without later-stage signals -> understand
        (
            {"conversation": replace(conversation(), current_mode="plan", message_count=1)},
            "understand",
        ),
        # build mode is already implementing
        (
            {"conversation": replace(conversation(), current_mode="build", message_count=0)},
            "implement",
        ),
        # an active run -> implement
        ({"runs": (plan_run(),)}, "implement"),
        ({"runs": (replace(plan_run(), status="queued"),)}, "implement"),
        # approved plan with incomplete tasks -> implement
        (
            {
                "plan_versions": (replace(plan_version(), status="approved"),),
                "conversation_tasks": (pending_task(),),
            },
            "implement",
        ),
        # approved plan fully done without run/artifacts stays at understand
        (
            {
                "plan_versions": (replace(plan_version(), status="approved"),),
                "conversation_tasks": (replace(pending_task(), status="completed"),),
            },
            "understand",
        ),
        # active attempt with verification evidence -> verify
        ({"attempts": (attempt("attempt-1", 1, "running"),)}, "verify"),
        # verification evidence while a run is active -> verify (beats implement)
        (
            {
                "attempts": (attempt("attempt-1", 1, "cancelled"),),
                "runs": (plan_run(),),
            },
            "verify",
        ),
        # adjudicated attempts -> review
        ({"attempts": (attempt("attempt-1", 1, "accepted"),)}, "review"),
        ({"attempts": (attempt("attempt-1", 1, "rejected"),)}, "review"),
        (
            {
                "attempts": (
                    replace(
                        attempt("attempt-1", 1, "running"),
                        completed_at=NOW - timedelta(minutes=1),
                    ),
                )
            },
            "review",
        ),
        # reviewable run terminal states with artifacts -> review
        (
            {
                "runs": (replace(plan_run(), status="ready_review"),),
                "artifact_records": (ArtifactRecordAuthority(id="artifact-1", created_at=NOW),),
            },
            "review",
        ),
        (
            {
                "runs": (replace(plan_run(), status="completed"),),
                "attempts": (attempt("attempt-1", 1, "cancelled"),),
            },
            "review",
        ),
        # failed/cancelled with reviewable artifacts -> review
        (
            {
                "runs": (replace(plan_run(), status="failed"),),
                "artifact_records": (ArtifactRecordAuthority(id="artifact-1", created_at=NOW),),
            },
            "review",
        ),
        # terminal failure without reviewable artifacts -> no stepper
        ({"runs": (replace(plan_run(), status="failed"),)}, None),
        ({"runs": (replace(plan_run(), status="cancelled"),)}, None),
        # failed run with an active verified attempt still shows verify
        (
            {
                "runs": (replace(plan_run(), status="failed"),),
                "attempts": (attempt("attempt-1", 1, "running"),),
            },
            "verify",
        ),
        # precedence conflict: running run + adjudicated attempt -> later stage
        (
            {
                "runs": (plan_run(),),
                "attempts": (attempt("attempt-1", 1, "accepted"),),
            },
            "review",
        ),
    ],
)
def test_derive_execution_stage_matrix(
    stage_snapshot_overrides: dict[str, object], expected: str | None
) -> None:
    assert derive_execution_stage(stage_snapshot(**stage_snapshot_overrides)) == expected


def test_pending_hitl_never_changes_the_derived_stage() -> None:
    source = stage_snapshot(
        plan_versions=(plan_version(),),
        pending_hitl=snapshot().pending_hitl,
        has_blocking_hitl=True,
    )

    assert derive_execution_stage(source) == "understand"


async def test_projection_exposes_derived_execution_stage() -> None:
    projection = await ConversationSessionProjectionService(
        FakeConversationSessionReader(snapshot())
    ).get_projection(
        conversation_id="conversation-1",
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id="workspace-1",
        user_id="user-1",
        now=NOW,
    )

    # latest attempt is running with candidate verification refs
    assert projection.execution_stage == "verify"


async def test_execution_stage_participates_in_the_snapshot_revision_digest() -> None:
    service = ConversationSessionProjectionService(FakeConversationSessionReader(snapshot()))
    projection = await service.get_projection(
        conversation_id="conversation-1",
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id="workspace-1",
        user_id="user-1",
        now=NOW,
    )

    unsigned = projection.model_dump(mode="json", exclude={"snapshot_revision"})
    assert "execution_stage" in unsigned
    canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(canonical.encode("utf-8")).hexdigest() == projection.snapshot_revision

    fresh = await ConversationSessionProjectionService(
        FakeConversationSessionReader(stage_snapshot())
    ).get_projection(
        conversation_id="conversation-1",
        tenant_id="tenant-1",
        project_id="project-1",
        workspace_id="workspace-1",
        user_id="user-1",
        now=NOW,
    )
    assert fresh.execution_stage is None
    assert fresh.snapshot_revision != projection.snapshot_revision
