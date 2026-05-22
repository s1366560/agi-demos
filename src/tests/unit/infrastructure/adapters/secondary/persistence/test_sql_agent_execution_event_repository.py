"""Tests for SqlAgentExecutionEventRepository."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import AgentExecutionEvent
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation as DBConversation,
    PlanModel,
    PlanNodeModel,
    WorkspacePlanEventModel,
    WorkspaceTaskModel,
    WorkspaceTaskSessionAttemptModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_event_repository import (
    SqlAgentExecutionEventRepository,
    _workspace_progress_summary,
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_events_by_message_ids_filters_by_conversation_and_message_ids() -> None:
    """Batch lookups must scope by conversation_id to avoid cross-conversation leaks."""
    session = MagicMock(spec=AsyncSession)
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = []
    result.scalars.return_value = scalars
    session.execute = AsyncMock(return_value=result)

    repo = SqlAgentExecutionEventRepository(session)

    await repo.get_events_by_message_ids("conv-a", {"shared-msg"})

    statement = session.execute.await_args.args[0]
    compiled = statement.compile()

    assert "agent_execution_events.conversation_id = :conversation_id_1" in str(compiled)
    assert "agent_execution_events.message_id IN" in str(compiled)
    assert compiled.params["conversation_id_1"] == "conv-a"
    assert compiled.params["message_id_1"] == ["shared-msg"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_events_by_message_filters_by_conversation_and_message_id() -> None:
    """Single-message lookups must scope by conversation_id to avoid leaks."""
    session = MagicMock(spec=AsyncSession)
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = []
    result.scalars.return_value = scalars
    session.execute = AsyncMock(return_value=result)

    repo = SqlAgentExecutionEventRepository(session)

    await repo.get_events_by_message("conv-a", "shared-msg")

    statement = session.execute.await_args.args[0]
    compiled = statement.compile()

    assert "agent_execution_events.conversation_id = :conversation_id_1" in str(compiled)
    assert "agent_execution_events.message_id = :message_id_1" in str(compiled)
    assert compiled.params["conversation_id_1"] == "conv-a"
    assert compiled.params["message_id_1"] == "shared-msg"


@pytest.mark.unit
def test_to_db_sanitizes_nested_nul_bytes() -> None:
    """PostgreSQL JSON path extraction cannot convert JSON strings containing NUL bytes."""
    session = MagicMock(spec=AsyncSession)
    repo = SqlAgentExecutionEventRepository(session)
    event = AgentExecutionEvent(
        conversation_id="conv-a",
        message_id="msg-a",
        event_type="observe",
        event_data={
            "observation": "binary\x00output",
            "nested": ["ok\x00value", {"detail": "fine"}],
        },
    )

    model = repo._to_db(event)

    assert model.event_data["observation"] == "binary[NUL]output"
    assert model.event_data["nested"][0] == "ok[NUL]value"


@pytest.mark.unit
def test_to_db_redacts_tokens_from_nested_payloads() -> None:
    """Persisted agent event payloads must not store credentials from tool output."""
    session = MagicMock(spec=AsyncSession)
    repo = SqlAgentExecutionEventRepository(session)
    jwt = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJ1c2VySWQiOiJ1c2VyLTEiLCJlbWFpbCI6InVzZXJAZXhhbXBsZS5jb20ifQ."
        "abc123abc123abc123abc123abc123abc123"
    )
    api_key = "ms_sk_" + "a" * 64
    event = AgentExecutionEvent(
        conversation_id="conv-a",
        message_id="msg-a",
        event_type="observe",
        event_data={
            "observation": f'{{"token":"{jwt}","apiKey":"{api_key}"}}',
            "nested": [{"authorization": f"Bearer {jwt}"}],
        },
    )

    model = repo._to_db(event)

    serialized = str(model.event_data)
    assert jwt not in serialized
    assert api_key not in serialized
    assert "[REDACTED_JWT]" in model.event_data["observation"]
    assert "[REDACTED_API_KEY]" in model.event_data["observation"]
    assert model.event_data["nested"][0]["authorization"] == "Bearer [REDACTED_JWT]"


def test_workspace_progress_summary_keeps_error_context_from_long_tool_output() -> None:
    """Long build logs should retain the actionable failure, not only the preamble."""
    output = (
        "> next build "
        + "compiled successfully " * 30
        + 'useSearchParams() should be wrapped in a suspense boundary at page "/arena". '
        + "stack frame " * 80
    )

    summary = _workspace_progress_summary(
        "observe",
        {
            "tool_name": "bash",
            "status": "completed",
            "observation": output,
        },
    )

    assert len(summary) <= 320
    assert summary.startswith("bash completed: > next build")
    assert 'useSearchParams() should be wrapped in a suspense boundary at page "/arena"' in summary


def test_workspace_progress_summary_skips_read_observations() -> None:
    """File operation receipts should not replace blocker summaries."""
    for tool_name in ("edit", "glob", "grep", "read", "workspace_report_progress", "write"):
        summary = _workspace_progress_summary(
            "observe",
            {
                "tool_name": tool_name,
                "status": "completed",
                "observation": "Successfully updated /workspace/app/page.tsx",
            },
        )

        assert summary == ""


def test_workspace_progress_summary_skips_plain_bash_listing() -> None:
    """Plain directory listings should stay out of the blackboard progress headline."""
    summary = _workspace_progress_summary(
        "observe",
        {
            "tool_name": "bash",
            "status": "completed",
            "observation": "async_api\ndriver\n_impl\n__init__.py\n__main__.py",
        },
    )

    assert summary == ""


def test_workspace_progress_summary_keeps_dependency_status_markers() -> None:
    """Dependency install status should remain visible even when the output is listing-shaped."""
    summary = _workspace_progress_summary(
        "observe",
        {
            "tool_name": "bash",
            "status": "completed",
            "observation": "chrome-linux\nDEPENDENCIES_VALIDATED\nINSTALLATION_COMPLETE",
        },
    )

    assert "DEPENDENCIES_VALIDATED" in summary
    assert "INSTALLATION_COMPLETE" in summary


def test_workspace_progress_summary_skips_npm_audit_tail_notice() -> None:
    """npm install audit hints should not replace actionable build or route status."""
    summary = _workspace_progress_summary(
        "observe",
        {
            "tool_name": "bash",
            "status": "completed",
            "observation": "\nTo address all issues, run:\n  npm audit fix\n\nRun `npm audit` for details.",
        },
    )

    assert summary == ""


def test_workspace_progress_summary_compresses_harness_heartbeat() -> None:
    """Long package-manager warnings should not hide the active command heartbeat."""
    summary = _workspace_progress_summary(
        "observe",
        {
            "tool_name": "bash",
            "status": "completed",
            "observation": (
                "npm warn deprecated inflight@1.0.6: This module is not supported\n"
                "npm warn deprecated glob@7.2.3: Old versions of glob are not supported\n"
                "--- stderr ---\n"
                "[workspace_harness_heartbeat] bash command still running"
            ),
        },
    )

    assert summary == "bash running: command still running (workspace harness heartbeat)"


def test_workspace_progress_summary_skips_pure_harness_heartbeat() -> None:
    """A bare heartbeat has no new task evidence."""
    summary = _workspace_progress_summary(
        "observe",
        {
            "tool_name": "bash",
            "status": "completed",
            "observation": (
                "[workspace_harness_heartbeat] bash command still running\n"
                "[workspace_harness_heartbeat] bash command still running"
            ),
        },
    )

    assert summary == ""


def test_workspace_progress_summary_keeps_build_error_with_harness_heartbeat() -> None:
    """Command heartbeats must not hide actionable compile failures in the same output."""
    summary = _workspace_progress_summary(
        "observe",
        {
            "tool_name": "bash",
            "status": "completed",
            "observation": (
                "Checking validity of types ...\n"
                "Failed to compile.\n\n"
                "./src/app/swarm/page.tsx:25:42\n"
                "Type error: Property 'style' does not exist on type "
                "'IntrinsicAttributes & { className?: string | undefined; }'.\n"
                "--- stderr ---\n"
                "[workspace_harness_heartbeat] bash command still running"
            ),
        },
    )

    assert summary.startswith("bash completed:")
    assert "Failed to compile" in summary
    assert "./src/app/swarm/page.tsx:25:42" in summary
    assert "Property 'style' does not exist" in summary
    assert "workspace harness heartbeat" not in summary


def test_workspace_progress_summary_keeps_build_manifest_with_harness_heartbeat() -> None:
    """Successful Next build output is high-signal deployment feedback."""
    summary = _workspace_progress_summary(
        "observe",
        {
            "tool_name": "bash",
            "status": "completed",
            "observation": (
                "/swarm                               2.75 kB         123 kB\n"
                "/workspace                           4.79 kB         125 kB\n"
                "+ First Load JS shared by all             103 kB\n"
                "--- stderr ---\n"
                "[workspace_harness_heartbeat] bash command still running"
            ),
        },
    )

    assert summary.startswith("bash completed:")
    assert "/swarm" in summary
    assert "First Load JS shared by all" in summary
    assert "workspace harness heartbeat" not in summary


def test_workspace_progress_summary_keeps_e2e_summary_with_harness_heartbeat() -> None:
    """E2E route summaries should stay visible even when the command emitted heartbeats."""
    summary = _workspace_progress_summary(
        "observe",
        {
            "tool_name": "bash",
            "status": "completed",
            "observation": (
                "[OK] 01-homepage -> 200\n"
                "[HTTP404] 04-dashboard -> 404\n"
                "=== SUMMARY ===\n"
                "Total: 18 | 200: 17 | 404: 1\n"
                "404 routes: ['04-dashboard']\n"
                "--- stderr ---\n"
                "[workspace_harness_heartbeat] bash command still running"
            ),
        },
    )

    assert summary.startswith("bash completed:")
    assert "[HTTP404] 04-dashboard -> 404" in summary
    assert "Total: 18 | 200: 17 | 404: 1" in summary
    assert "workspace harness heartbeat" not in summary


def test_workspace_progress_summary_skips_bash_search_result_listings() -> None:
    """Shell grep results are investigation noise, not the current deployment result."""
    summary = _workspace_progress_summary(
        "observe",
        {
            "tool_name": "bash",
            "status": "completed",
            "observation": (
                "417:  // Dashboard API\n"
                "420:   * Get full dashboard data in one request.\n"
                "422:  getDashboard() {\n"
                "423:    return this.get<DashboardData>('/api/v2/dashboard');"
            ),
        },
    )

    assert summary == ""


def test_workspace_progress_summary_skips_background_pid_receipts() -> None:
    """Background process IDs are execution receipts, not meaningful task progress."""
    for observation in (
        "PID=8596",
        "Build PID=21792",
        "0",
        "finished",
        "killed",
        "killed old servers\n000port free",
        "stopped old processes",
        "Tool execution failed after 1 attempts: Exit code: 1\n(no output)",
        "-rw-r--r-- 1 root root 21 /workspace/app/frontend/.next/BUILD_ID\nabc123",
    ):
        summary = _workspace_progress_summary(
            "observe",
            {
                "tool_name": "bash",
                "status": "completed",
                "observation": observation,
            },
        )

        assert summary == ""


def test_workspace_progress_summary_keeps_route_status() -> None:
    """Route reports are high-signal deployment feedback, even when all routes pass."""
    summary = _workspace_progress_summary(
        "observe",
        {
            "tool_name": "bash",
            "status": "completed",
            "observation": (
                "Route Status Report\n"
                "[OK] 200 / Homepage\n"
                "[OK] 200 /dashboard DASHBOARD (formerly 404)\n"
                "Routes returning 200: 18/18"
            ),
        },
    )

    assert "[OK] 200 /dashboard" in summary
    assert "Routes returning 200: 18/18" in summary


@pytest.mark.unit
@pytest.mark.asyncio
async def test_save_projects_workspace_agent_event_to_plan_progress(
    db_session: AsyncSession,
    workspace_test_seed: dict[str, str],
) -> None:
    """Workspace workers should show live progress even without explicit WTP progress calls."""
    _ = workspace_test_seed
    db_session.add_all(
        [
            WorkspaceTaskModel(
                id="workspace-task-progress",
                workspace_id="workspace-1",
                title="Run E2E",
                description="",
                created_by="user-1",
                status="in_progress",
                metadata_json={},
            ),
            DBConversation(
                id="conversation-progress",
                project_id="project-1",
                tenant_id="tenant-1",
                user_id="user-1",
                title="Worker",
                status="active",
                agent_config={"selected_agent_id": "agent-1"},
                meta={
                    "workspace_id": "workspace-1",
                    "linked_workspace_task_id": "workspace-task-progress",
                    "attempt_id": "attempt-progress",
                    "workspace_llm_stage": "worker_launch",
                },
                workspace_id="workspace-1",
                linked_workspace_task_id="workspace-task-progress",
            ),
            WorkspaceTaskSessionAttemptModel(
                id="attempt-progress",
                workspace_task_id="workspace-task-progress",
                root_goal_task_id="workspace-task-progress",
                workspace_id="workspace-1",
                attempt_number=1,
                status="running",
                conversation_id="conversation-progress",
            ),
            PlanModel(
                id="plan-progress",
                workspace_id="workspace-1",
                goal_id="node-progress",
                status="active",
            ),
            PlanNodeModel(
                id="node-progress",
                plan_id="plan-progress",
                kind="task",
                title="Run E2E",
                description="",
                progress={"percent": 25.0, "confidence": 0.8, "note": "starting"},
                workspace_task_id="workspace-task-progress",
                current_attempt_id="attempt-progress",
                metadata_json={},
            ),
        ]
    )
    await db_session.flush()

    event = AgentExecutionEvent(
        id="event-progress",
        conversation_id="conversation-progress",
        message_id="message-progress",
        event_type="assistant_message",
        event_data={
            "content": "I found 20/20 existing E2E results and am adding TC21/TC22.",
            "role": "assistant",
        },
        event_time_us=123,
        event_counter=0,
        created_at=datetime.now(UTC),
    )

    await SqlAgentExecutionEventRepository(db_session).save(event)

    node = (
        await db_session.execute(
            select(PlanNodeModel).where(PlanNodeModel.id == "node-progress")
        )
    ).scalar_one()
    assert node.progress == {
        "percent": 25.0,
        "confidence": 0.8,
        "note": "I found 20/20 existing E2E results and am adding TC21/TC22.",
    }
    assert node.metadata_json["latest_agent_event_progress_id"] == "event-progress"
    assert node.metadata_json["latest_worker_progress"]["source_event_type"] == (
        "assistant_message"
    )

    progress_event = (
        await db_session.execute(
            select(WorkspacePlanEventModel).where(
                WorkspacePlanEventModel.plan_id == "plan-progress",
                WorkspacePlanEventModel.event_type == "worker_progress",
            )
        )
    ).scalar_one()
    assert progress_event.source == "agent_execution_event_projection"
    assert progress_event.node_id == "node-progress"
    assert progress_event.attempt_id == "attempt-progress"
    assert progress_event.actor_id == "agent-1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_save_batch_skips_context_status_for_workspace_progress(
    db_session: AsyncSession,
    workspace_test_seed: dict[str, str],
) -> None:
    """Low-signal heartbeat events should not flood the workspace plan event ledger."""
    _ = workspace_test_seed
    db_session.add_all(
        [
            WorkspaceTaskModel(
                id="workspace-task-context",
                workspace_id="workspace-1",
                title="Run E2E",
                description="",
                created_by="user-1",
                status="in_progress",
                metadata_json={},
            ),
            DBConversation(
                id="conversation-context",
                project_id="project-1",
                tenant_id="tenant-1",
                user_id="user-1",
                title="Worker",
                status="active",
                meta={
                    "workspace_id": "workspace-1",
                    "linked_workspace_task_id": "workspace-task-context",
                    "attempt_id": "attempt-context",
                },
                workspace_id="workspace-1",
                linked_workspace_task_id="workspace-task-context",
            ),
            PlanModel(
                id="plan-context",
                workspace_id="workspace-1",
                goal_id="node-context",
                status="active",
            ),
            PlanNodeModel(
                id="node-context",
                plan_id="plan-context",
                kind="task",
                title="Run E2E",
                description="",
                progress={"percent": 0.0, "confidence": 1.0, "note": ""},
                workspace_task_id="workspace-task-context",
                current_attempt_id="attempt-context",
                metadata_json={},
            ),
        ]
    )
    await db_session.flush()

    await SqlAgentExecutionEventRepository(db_session).save_batch(
        [
            AgentExecutionEvent(
                id="event-context",
                conversation_id="conversation-context",
                message_id="message-context",
                event_type="context_status",
                event_data={"current_tokens": 1000},
                event_time_us=456,
                event_counter=0,
                created_at=datetime.now(UTC),
            )
        ]
    )

    node = (
        await db_session.execute(
            select(PlanNodeModel).where(PlanNodeModel.id == "node-context")
        )
    ).scalar_one()
    assert node.progress["note"] == ""
    event_count = (
        await db_session.execute(
            select(WorkspacePlanEventModel).where(
                WorkspacePlanEventModel.plan_id == "plan-context"
            )
        )
    ).scalars().all()
    assert event_count == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_save_skips_no_output_observe_for_workspace_progress(
    db_session: AsyncSession,
    workspace_test_seed: dict[str, str],
) -> None:
    """No-output tool observations should not overwrite useful workspace feedback."""
    _ = workspace_test_seed
    db_session.add_all(
        [
            WorkspaceTaskModel(
                id="workspace-task-no-output",
                workspace_id="workspace-1",
                title="Run E2E",
                description="",
                created_by="user-1",
                status="in_progress",
                metadata_json={},
            ),
            DBConversation(
                id="conversation-no-output",
                project_id="project-1",
                tenant_id="tenant-1",
                user_id="user-1",
                title="Worker",
                status="active",
                agent_config={"selected_agent_id": "agent-1"},
                meta={
                    "workspace_id": "workspace-1",
                    "linked_workspace_task_id": "workspace-task-no-output",
                    "attempt_id": "attempt-no-output",
                },
                workspace_id="workspace-1",
                linked_workspace_task_id="workspace-task-no-output",
            ),
            PlanModel(
                id="plan-no-output",
                workspace_id="workspace-1",
                goal_id="node-no-output",
                status="active",
            ),
            PlanNodeModel(
                id="node-no-output",
                plan_id="plan-no-output",
                kind="task",
                title="Run E2E",
                description="",
                progress={"percent": 0.0, "confidence": 1.0, "note": "useful blocker"},
                workspace_task_id="workspace-task-no-output",
                current_attempt_id="attempt-no-output",
                metadata_json={},
            ),
        ]
    )
    await db_session.flush()

    await SqlAgentExecutionEventRepository(db_session).save(
        AgentExecutionEvent(
            id="event-no-output",
            conversation_id="conversation-no-output",
            message_id="message-no-output",
            event_type="observe",
            event_data={
                "tool_name": "bash",
                "status": "completed",
                "observation": "(no output)",
            },
            event_time_us=789,
            event_counter=0,
            created_at=datetime.now(UTC),
        )
    )

    node = (
        await db_session.execute(
            select(PlanNodeModel).where(PlanNodeModel.id == "node-no-output")
        )
    ).scalar_one()
    assert node.progress["note"] == "useful blocker"
    progress_events = (
        await db_session.execute(
            select(WorkspacePlanEventModel).where(
                WorkspacePlanEventModel.plan_id == "plan-no-output"
            )
        )
    ).scalars().all()
    assert progress_events == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_save_keeps_useful_workspace_progress_when_act_arrives_after_observe(
    db_session: AsyncSession,
    workspace_test_seed: dict[str, str],
) -> None:
    """Generic running-tool events should not hide the latest useful worker observation."""
    _ = workspace_test_seed
    db_session.add_all(
        [
            WorkspaceTaskModel(
                id="workspace-task-act",
                workspace_id="workspace-1",
                title="Run E2E",
                description="",
                created_by="user-1",
                status="in_progress",
                metadata_json={},
            ),
            DBConversation(
                id="conversation-act",
                project_id="project-1",
                tenant_id="tenant-1",
                user_id="user-1",
                title="Worker",
                status="active",
                agent_config={"selected_agent_id": "agent-1"},
                meta={
                    "workspace_id": "workspace-1",
                    "linked_workspace_task_id": "workspace-task-act",
                    "attempt_id": "attempt-act",
                },
                workspace_id="workspace-1",
                linked_workspace_task_id="workspace-task-act",
            ),
            PlanModel(
                id="plan-act",
                workspace_id="workspace-1",
                goal_id="node-act",
                status="active",
            ),
            PlanNodeModel(
                id="node-act",
                plan_id="plan-act",
                kind="task",
                title="Run E2E",
                description="",
                progress={
                    "percent": 0.0,
                    "confidence": 1.0,
                    "note": "bash completed: native binding missing",
                },
                workspace_task_id="workspace-task-act",
                current_attempt_id="attempt-act",
                metadata_json={
                    "latest_agent_event_progress_id": "event-observe",
                    "latest_worker_progress": {
                        "source_event_id": "event-observe",
                        "source_event_type": "observe",
                        "summary": "bash completed: native binding missing",
                    },
                },
            ),
        ]
    )
    await db_session.flush()

    await SqlAgentExecutionEventRepository(db_session).save(
        AgentExecutionEvent(
            id="event-act",
            conversation_id="conversation-act",
            message_id="message-act",
            event_type="act",
            event_data={
                "tool_name": "bash",
                "tool_input": {"command": "find node_modules -name '*.node'"},
            },
            event_time_us=890,
            event_counter=0,
            created_at=datetime.now(UTC),
        )
    )

    node = (
        await db_session.execute(select(PlanNodeModel).where(PlanNodeModel.id == "node-act"))
    ).scalar_one()
    assert node.progress["note"] == "bash completed: native binding missing"
    assert node.metadata_json["latest_agent_event_progress_id"] == "event-act"
    assert node.metadata_json["latest_worker_progress"]["source_event_id"] == "event-observe"

    progress_event = (
        await db_session.execute(
            select(WorkspacePlanEventModel).where(
                WorkspacePlanEventModel.plan_id == "plan-act",
                WorkspacePlanEventModel.event_type == "worker_progress",
            )
        )
    ).scalar_one()
    assert progress_event.payload_json["source_event_id"] == "event-act"
    assert progress_event.payload_json["summary"] == "Running tool: bash"
