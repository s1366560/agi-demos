"""Tests for the workspace plan outbox worker."""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import src.infrastructure.agent.workspace_plan.outbox_handlers as outbox_handlers
from src.domain.model.workspace.workspace_task import WorkspaceTask
from src.domain.model.workspace_plan import (
    AcceptanceCriterion,
    Capability,
    CriterionKind,
    FeatureCheckpoint,
    Plan,
    PlanNode,
    PlanNodeId,
    PlanNodeKind,
    PlanStatus,
    TaskExecution,
    TaskIntent,
)
from src.domain.ports.services.task_allocator_port import Allocation, WorkspaceAgent
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentDefinitionModel,
    Base,
    PlanModel,
    Project as DBProject,
    Tenant as DBTenant,
    User as DBUser,
    WorkspaceAgentModel,
    WorkspaceMemberModel,
    WorkspaceModel,
    WorkspacePlanEventModel,
    WorkspacePlanOutboxModel,
    WorkspaceTaskModel,
    WorkspaceTaskSessionAttemptModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_plan_repository import SqlPlanRepository
from src.infrastructure.adapters.secondary.persistence.sql_workspace_plan_outbox import (
    SqlWorkspacePlanOutboxRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository import (
    SqlWorkspaceTaskRepository,
)
from src.infrastructure.agent.sisyphus.builtin_agent import BUILTIN_SISYPHUS_ID
from src.infrastructure.agent.workspace.workspace_goal_runtime import (
    apply_workspace_worker_report,
)
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    ACTIVE_EXECUTION_ROOT,
    ATTEMPT_WORKTREE,
    AUTONOMY_SCHEMA_VERSION_KEY,
    CURRENT_ATTEMPT_ID,
    CURRENT_ATTEMPT_WORKER_BINDING_ID,
    EXECUTION_STATE,
    LAST_WORKER_REPORT_ATTEMPT_ID,
    LAST_WORKER_REPORT_SUMMARY,
    PENDING_LEADER_ADJUDICATION,
    ROOT_GOAL_TASK_ID,
    TASK_ROLE,
    WORKSPACE_PLAN_ID,
    WORKSPACE_PLAN_NODE_ID,
    WORKTREE_SETUP,
)
from src.infrastructure.agent.workspace_plan.factory import (
    _project_verification_to_workspace_task,
    build_sql_orchestrator,
)
from src.infrastructure.agent.workspace_plan.orchestrator import OrchestratorConfig
from src.infrastructure.agent.workspace_plan.outbox_handlers import (
    HANDOFF_RESUME_EVENT,
    SUPERVISOR_TICK_EVENT,
    WORKER_LAUNCH_EVENT,
    _apply_attempt_worktree_checkpoint,
    _commit_ref_token,
    _extract_task_evidence,
    _first_prefixed_ref,
    _integration_status_from_output,
    _is_structural_sandbox_command,
    _node_allowed_sandbox_commands,
    _persisted_attempt_leader_agent_id,
    _prepare_attempt_worktree_if_available,
    _WorkspaceSandboxCommandRunner,
    _worktree_integration_command,
    _worktree_setup_command,
    make_handoff_resume_handler,
    make_supervisor_tick_handler,
    make_worker_launch_handler,
)
from src.infrastructure.agent.workspace_plan.outbox_worker import (
    WorkspacePlanOutboxWorker,
    WorkspacePlanSessionFactory,
)
from src.infrastructure.agent.workspace_plan.pipeline import (
    DRONE_PROVIDER,
    PipelineContractSpec,
    PipelineDeploySpec,
)
from src.infrastructure.agent.workspace_plan.system_actor import WORKSPACE_PLAN_SYSTEM_ACTOR_ID


async def _seed_plan(db_session: AsyncSession, workspace_id: str, plan_id: str) -> None:
    db_session.add(
        PlanModel(
            id=plan_id,
            workspace_id=workspace_id,
            goal_id=f"{plan_id}-goal",
            status="active",
        )
    )
    await db_session.flush()


async def _file_backed_outbox_session_maker(
    tmp_path: Path,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'outbox-worker.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _seed_worker_launch_outbox_item(
    session_maker: async_sessionmaker[AsyncSession],
) -> str:
    async with session_maker() as seed_session:
        await _seed_workspace_and_plan(seed_session)
        repo = SqlWorkspacePlanOutboxRepository(seed_session)
        item = await repo.enqueue(
            plan_id="worker-plan-1",
            workspace_id="workspace-1",
            event_type="worker_launch",
            max_attempts=2,
        )
        await seed_session.commit()
        return item.id


async def _seed_workspace_and_plan(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            DBUser(
                id="worker-user-1",
                email="worker-user-1@example.com",
                full_name="Worker User",
                hashed_password="hash",
                is_active=True,
            ),
            DBTenant(
                id="worker-tenant-1",
                name="Worker Tenant",
                slug="worker-tenant",
                description="",
                owner_id="worker-user-1",
                plan="free",
                max_projects=10,
                max_users=10,
                max_storage=1,
            ),
            DBProject(
                id="worker-project-1",
                tenant_id="worker-tenant-1",
                name="Worker Project",
                description="",
                owner_id="worker-user-1",
                memory_rules={},
                graph_config={},
                sandbox_type="cloud",
                sandbox_config={},
                is_public=False,
            ),
            WorkspaceModel(
                id="workspace-1",
                tenant_id="worker-tenant-1",
                project_id="worker-project-1",
                name="Worker Workspace",
                description="",
                created_by="worker-user-1",
                is_archived=False,
                metadata_json={},
            ),
            WorkspaceMemberModel(
                id="workspace-member-1",
                workspace_id="workspace-1",
                user_id="worker-user-1",
                role="owner",
                invited_by="worker-user-1",
            ),
            AgentDefinitionModel(
                id=BUILTIN_SISYPHUS_ID,
                tenant_id="worker-tenant-1",
                project_id="worker-project-1",
                name="sisyphus",
                display_name="Sisyphus",
                system_prompt="You coordinate workspace execution.",
                allowed_tools=[],
                allowed_skills=[],
                allowed_mcp_servers=[],
            ),
            AgentDefinitionModel(
                id="worker-agent",
                tenant_id="worker-tenant-1",
                project_id="worker-project-1",
                name="worker-agent",
                display_name="Worker Agent",
                system_prompt="You execute workspace tasks.",
                allowed_tools=[],
                allowed_skills=[],
                allowed_mcp_servers=[],
            ),
            WorkspaceAgentModel(
                id="worker-binding-1",
                workspace_id="workspace-1",
                agent_id="worker-agent",
                display_name="Worker Agent",
                description=None,
                config_json={"capabilities": ["codegen"]},
                is_active=True,
            ),
            WorkspaceTaskModel(
                id="root-task-1",
                workspace_id="workspace-1",
                title="Root goal",
                description="Root goal for V2 dispatch",
                created_by="worker-user-1",
                status="in_progress",
                priority=0,
                metadata_json={
                    AUTONOMY_SCHEMA_VERSION_KEY: 1,
                    TASK_ROLE: "goal_root",
                    "goal_origin": "existing_root",
                    "goal_source_refs": [],
                    "root_goal_policy": {
                        "mutable_by_agent": False,
                        "completion_requires_external_proof": True,
                    },
                    "goal_health": "healthy",
                },
            ),
        ]
    )
    await db_session.flush()
    await _seed_plan(db_session, "workspace-1", "worker-plan-1")


def _session_factory(db_session: AsyncSession) -> WorkspacePlanSessionFactory:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        try:
            yield db_session
        except BaseException:
            await db_session.rollback()
            raise

    return factory


def _with_stale_attempt_metadata(
    node: PlanNode,
    *,
    previous_attempt_id: str,
) -> PlanNode:
    return replace(
        node,
        metadata={
            **dict(node.metadata or {}),
            "last_verification_summary": "verification failed: old attempt",
            "last_verification_passed": False,
            "last_verification_attempt_id": previous_attempt_id,
            "verification_evidence_refs": ["old-evidence"],
            "terminal_attempt_status": "blocked",
            "terminal_attempt_retry_count": 1,
        },
    )


def test_extract_task_evidence_omits_worker_report_from_prior_attempt() -> None:
    task = SimpleNamespace(
        metadata={
            CURRENT_ATTEMPT_ID: "attempt-new",
            "last_attempt_id": "attempt-old",
            LAST_WORKER_REPORT_ATTEMPT_ID: "attempt-old",
            LAST_WORKER_REPORT_SUMMARY: "old completion",
            "last_worker_report_type": "completed",
            "last_worker_report_artifacts": ["commit_ref:old"],
            "last_worker_report_verifications": ["test_run:old"],
            "evidence_refs": ["commit_ref:old"],
            "execution_verifications": ["test_run:old"],
            "preflight_checks": [{"name": "read", "passed": True}],
            "code_context": {"sandbox_code_root": "/workspace/my-evo"},
        }
    )

    stdout, artifacts = _extract_task_evidence(task, current_attempt_id="attempt-new")

    assert stdout == ""
    assert "last_worker_report_type" not in artifacts
    assert "last_worker_report_artifacts" not in artifacts
    assert "evidence_refs" not in artifacts
    assert artifacts[CURRENT_ATTEMPT_ID] == "attempt-new"
    assert artifacts[LAST_WORKER_REPORT_ATTEMPT_ID] == "attempt-old"
    assert artifacts["preflight_checks"] == [{"name": "read", "passed": True}]
    assert artifacts["code_context"] == {"sandbox_code_root": "/workspace/my-evo"}


def test_extract_task_evidence_omits_unscoped_worker_report_for_current_attempt() -> None:
    task = SimpleNamespace(
        metadata={
            CURRENT_ATTEMPT_ID: "attempt-new",
            LAST_WORKER_REPORT_SUMMARY: "unscoped completion",
            "last_worker_report_type": "completed",
            "last_worker_report_artifacts": ["commit_ref:stale"],
            "last_worker_report_verifications": ["test_run:stale"],
            "evidence_refs": ["commit_ref:stale"],
            "execution_verifications": ["test_run:stale"],
            "preflight_checks": [{"name": "read", "passed": True}],
        }
    )

    stdout, artifacts = _extract_task_evidence(task, current_attempt_id="attempt-new")

    assert stdout == ""
    assert "last_worker_report_type" not in artifacts
    assert "last_worker_report_artifacts" not in artifacts
    assert "last_worker_report_verifications" not in artifacts
    assert "evidence_refs" not in artifacts
    assert "execution_verifications" not in artifacts
    assert artifacts[CURRENT_ATTEMPT_ID] == "attempt-new"
    assert artifacts["preflight_checks"] == [{"name": "read", "passed": True}]


def test_extract_task_evidence_keeps_worker_report_for_current_attempt() -> None:
    task = SimpleNamespace(
        metadata={
            CURRENT_ATTEMPT_ID: "attempt-current",
            "last_attempt_id": "attempt-current",
            LAST_WORKER_REPORT_ATTEMPT_ID: "attempt-current",
            LAST_WORKER_REPORT_SUMMARY: "current completion",
            "last_worker_report_type": "completed",
            "last_worker_report_artifacts": ["commit_ref:current"],
            "last_worker_report_verifications": ["test_run:current"],
            "evidence_refs": ["commit_ref:current"],
            "execution_verifications": ["test_run:current"],
        }
    )

    stdout, artifacts = _extract_task_evidence(task, current_attempt_id="attempt-current")

    assert stdout == "current completion"
    assert artifacts["last_worker_report_type"] == "completed"
    assert artifacts["last_worker_report_artifacts"] == ["commit_ref:current"]
    assert artifacts["evidence_refs"] == ["commit_ref:current"]


@pytest.mark.asyncio
async def test_verification_judge_retry_projection_keeps_attempt_non_terminal(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_and_plan(db_session)
    db_session.add(
        WorkspaceTaskModel(
            id="exec-task-1",
            workspace_id="workspace-1",
            title="Execution task",
            description="",
            created_by="worker-user-1",
            status="in_progress",
            priority=0,
            metadata_json={
                AUTONOMY_SCHEMA_VERSION_KEY: 1,
                TASK_ROLE: "execution_task",
                WORKSPACE_PLAN_ID: "worker-plan-1",
                WORKSPACE_PLAN_NODE_ID: "node-a",
                ROOT_GOAL_TASK_ID: "root-task-1",
                CURRENT_ATTEMPT_ID: "attempt-a",
                PENDING_LEADER_ADJUDICATION: False,
                "last_attempt_status": "awaiting_plan_verification",
            },
        )
    )
    db_session.add(
        WorkspaceTaskSessionAttemptModel(
            id="attempt-a",
            workspace_task_id="exec-task-1",
            root_goal_task_id="root-task-1",
            workspace_id="workspace-1",
            attempt_number=1,
            status="awaiting_leader_adjudication",
            conversation_id="conversation-a",
            worker_agent_id="worker-agent",
            leader_agent_id=BUILTIN_SISYPHUS_ID,
            candidate_summary="Completed docs updates.",
            candidate_verifications_json=["test_run:pytest docs 117 passed 0 failed"],
        )
    )
    await db_session.flush()
    node = PlanNode(
        id="node-a",
        plan_id="worker-plan-1",
        parent_id=PlanNodeId("goal-a"),
        kind=PlanNodeKind.TASK,
        title="Verify architecture docs",
        workspace_task_id="exec-task-1",
        current_attempt_id="attempt-a",
    )

    await _project_verification_to_workspace_task(
        db_session,
        node,
        {
            "attempt_id": "attempt-a",
            "passed": False,
            "hard_fail": False,
            "retry_verification_only": True,
            "summary": "judge verdict=retry_infrastructure; retry verification judge",
            "results": [
                {
                    "kind": "custom",
                    "name": "retryable_infrastructure_failure",
                    "judge_verdict": "retry_infrastructure",
                    "next_action_kind": "retry_same_node",
                    "required_next_action": "retry verification judge",
                    "required": True,
                    "passed": False,
                    "confidence": 0.5,
                    "message": "workspace verification judge failed",
                    "evidence": [],
                }
            ],
        },
    )
    await db_session.flush()

    attempt = await db_session.get(WorkspaceTaskSessionAttemptModel, "attempt-a")
    assert attempt is not None
    assert attempt.status == "awaiting_leader_adjudication"
    assert attempt.completed_at is None
    assert attempt.leader_feedback == "judge verdict=retry_infrastructure; retry verification judge"
    assert attempt.adjudication_reason == "verification_retry_scheduled"
    task = await db_session.get(WorkspaceTaskModel, "exec-task-1")
    assert task is not None
    assert task.status == "in_progress"
    assert task.metadata_json[PENDING_LEADER_ADJUDICATION] is False
    assert task.metadata_json["last_attempt_status"] == "awaiting_plan_verification"
    assert task.metadata_json["durable_plan_verdict"] == "verification_retry_scheduled"
    assert task.metadata_json[CURRENT_ATTEMPT_ID] == "attempt-a"


@pytest.mark.asyncio
async def test_pipeline_required_verification_waits_for_pipeline_before_accepting(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_and_plan(db_session)
    db_session.add(
        WorkspaceTaskModel(
            id="exec-task-1",
            workspace_id="workspace-1",
            title="Execution task",
            description="",
            created_by="worker-user-1",
            status="in_progress",
            priority=0,
            metadata_json={
                AUTONOMY_SCHEMA_VERSION_KEY: 1,
                TASK_ROLE: "execution_task",
                WORKSPACE_PLAN_ID: "worker-plan-1",
                WORKSPACE_PLAN_NODE_ID: "node-a",
                ROOT_GOAL_TASK_ID: "root-task-1",
                CURRENT_ATTEMPT_ID: "attempt-a",
                PENDING_LEADER_ADJUDICATION: False,
                "last_attempt_status": "awaiting_plan_verification",
            },
        )
    )
    db_session.add(
        WorkspaceTaskSessionAttemptModel(
            id="attempt-a",
            workspace_task_id="exec-task-1",
            root_goal_task_id="root-task-1",
            workspace_id="workspace-1",
            attempt_number=1,
            status="awaiting_leader_adjudication",
            conversation_id="conversation-a",
            worker_agent_id="worker-agent",
            leader_agent_id=BUILTIN_SISYPHUS_ID,
            candidate_summary="Implementation completed.",
            candidate_verifications_json=["commit_ref:abc1234", "test_run:npm run build"],
        )
    )
    await db_session.flush()
    node = PlanNode(
        id="node-a",
        plan_id="worker-plan-1",
        parent_id=PlanNodeId("goal-a"),
        kind=PlanNodeKind.TASK,
        title="Implement feature",
        workspace_task_id="exec-task-1",
        current_attempt_id="attempt-a",
        metadata={"pipeline_required": True},
    )

    await _project_verification_to_workspace_task(
        db_session,
        node,
        {
            "attempt_id": "attempt-a",
            "passed": True,
            "hard_fail": False,
            "summary": "verified before pipeline",
            "results": [
                {
                    "kind": "custom",
                    "required": True,
                    "passed": True,
                    "confidence": 1.0,
                    "message": "build passed",
                    "evidence": [
                        {"kind": "artifact", "ref": "commit_ref:abc1234"},
                        {"kind": "log", "ref": "test_run:npm run build"},
                    ],
                }
            ],
        },
    )
    await db_session.flush()

    attempt = await db_session.get(WorkspaceTaskSessionAttemptModel, "attempt-a")
    assert attempt is not None
    assert attempt.status == "awaiting_leader_adjudication"
    assert attempt.completed_at is None
    assert attempt.adjudication_reason == "pipeline_gate_pending"
    task = await db_session.get(WorkspaceTaskModel, "exec-task-1")
    assert task is not None
    assert task.status == "in_progress"
    assert task.metadata_json["durable_plan_verdict"] == "pipeline_pending"
    assert task.metadata_json["last_attempt_status"] == "awaiting_pipeline"
    assert task.metadata_json["pipeline_candidate_commit_ref"] == "abc1234"


@pytest.mark.asyncio
async def test_retryable_worker_infrastructure_projection_terminalizes_attempt(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_and_plan(db_session)
    db_session.add(
        WorkspaceTaskModel(
            id="exec-task-1",
            workspace_id="workspace-1",
            title="Execution task",
            description="",
            created_by="worker-user-1",
            status="in_progress",
            priority=0,
            metadata_json={
                AUTONOMY_SCHEMA_VERSION_KEY: 1,
                TASK_ROLE: "execution_task",
                WORKSPACE_PLAN_ID: "worker-plan-1",
                WORKSPACE_PLAN_NODE_ID: "node-a",
                ROOT_GOAL_TASK_ID: "root-task-1",
                CURRENT_ATTEMPT_ID: "attempt-a",
                PENDING_LEADER_ADJUDICATION: False,
                "last_attempt_status": "awaiting_plan_verification",
            },
        )
    )
    db_session.add(
        WorkspaceTaskSessionAttemptModel(
            id="attempt-a",
            workspace_task_id="exec-task-1",
            root_goal_task_id="root-task-1",
            workspace_id="workspace-1",
            attempt_number=1,
            status="awaiting_leader_adjudication",
            conversation_id="conversation-a",
            worker_agent_id="worker-agent",
            leader_agent_id=BUILTIN_SISYPHUS_ID,
            candidate_summary="Provider failed before producing evidence.",
            candidate_verifications_json=["provider_error:minimax 400"],
        )
    )
    await db_session.flush()
    node = PlanNode(
        id="node-a",
        plan_id="worker-plan-1",
        parent_id=PlanNodeId("goal-a"),
        kind=PlanNodeKind.TASK,
        title="Run implementation worker",
        workspace_task_id="exec-task-1",
        current_attempt_id="attempt-a",
    )

    await _project_verification_to_workspace_task(
        db_session,
        node,
        {
            "attempt_id": "attempt-a",
            "passed": False,
            "hard_fail": False,
            "summary": "provider protocol error; retry same node",
            "results": [
                {
                    "kind": "custom",
                    "name": "retryable_infrastructure_failure",
                    "judge_verdict": "retry_infrastructure",
                    "next_action_kind": "retry_same_node",
                    "failed_criteria": ["provider_protocol_error"],
                    "required": True,
                    "passed": False,
                    "confidence": 0.8,
                    "message": "worker provider failed",
                    "evidence": [],
                }
            ],
        },
    )
    await db_session.flush()

    attempt = await db_session.get(WorkspaceTaskSessionAttemptModel, "attempt-a")
    assert attempt is not None
    assert attempt.status == "rejected"
    assert attempt.completed_at is not None
    assert attempt.leader_feedback == "provider protocol error; retry same node"
    task = await db_session.get(WorkspaceTaskModel, "exec-task-1")
    assert task is not None
    assert task.status == "in_progress"
    assert task.metadata_json[PENDING_LEADER_ADJUDICATION] is False
    assert task.metadata_json["last_attempt_status"] == "rejected"
    assert task.metadata_json["durable_plan_verdict"] == "replan_requested"
    assert task.metadata_json[CURRENT_ATTEMPT_ID] == "attempt-a"


@pytest.mark.asyncio
async def test_worker_start_restarts_after_stop(db_session: AsyncSession) -> None:
    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={},
        poll_interval_seconds=10.0,
    )

    assert worker.is_running is False
    worker.start()
    assert worker.is_running is True

    await worker.stop()
    assert worker.is_running is False

    worker.start()
    assert worker.is_running is True
    await worker.stop()
    assert worker.is_running is False


@pytest.mark.asyncio
async def test_workspace_sandbox_runner_blocks_commands_outside_harness_allowlist() -> None:
    runner = _WorkspaceSandboxCommandRunner(
        project_id="project-1",
        allowed_commands={"uv run pytest src/tests/unit/example.py"},
    )

    result = await runner.run_command("rm -rf /tmp/nope")

    assert result["exit_code"] == 126
    assert result["stdout"] == ""
    assert "not allowed by workspace harness" in result["stderr"]


@pytest.mark.asyncio
async def test_workspace_sandbox_runner_allows_attempt_worktree_command_rewrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []
    runner = _WorkspaceSandboxCommandRunner(
        project_id="project-1",
        allowed_commands={"cd /workspace/my-evo && npm test"},
    )

    class FakeAdapter:
        async def call_tool(
            self,
            sandbox_id: str,
            tool_name: str,
            arguments: dict[str, object],
            *,
            timeout: float,
        ) -> dict[str, object]:
            calls.append(arguments)
            return {"content": [{"type": "text", "text": "ok"}], "is_error": False}

    async def fake_ensure_sandbox() -> tuple[str, FakeAdapter]:
        return "sandbox-1", FakeAdapter()

    monkeypatch.setattr(runner, "ensure_sandbox", fake_ensure_sandbox)

    command = "cd /workspace/my-evo/../.memstack/worktrees/attempt-1 && npm test"
    result = await runner.run_command(command)

    assert result["exit_code"] == 0
    assert result["stdout"] == "ok"
    assert calls == [{"command": command, "timeout": 60}]


@pytest.mark.asyncio
async def test_workspace_sandbox_runner_rejects_same_body_outside_attempt_worktree() -> None:
    runner = _WorkspaceSandboxCommandRunner(
        project_id="project-1",
        allowed_commands={"cd /workspace/my-evo && npm test"},
    )

    result = await runner.run_command("cd /tmp/not-a-worktree && npm test")

    assert result["exit_code"] == 126
    assert result["stdout"] == ""
    assert "not allowed by workspace harness" in result["stderr"]


@pytest.mark.asyncio
async def test_worker_launch_handler_supplies_system_leader_when_payload_omits_leader(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_workspace_and_plan(db_session)
    db_session.add(
        WorkspaceTaskModel(
            id="task-no-leader-1",
            workspace_id="workspace-1",
            title="Recover launch without leader",
            description="Retry a worker launch emitted by session recovery.",
            created_by="worker-user-1",
            status="in_progress",
            priority=0,
            assignee_agent_id="worker-agent",
            metadata_json={
                AUTONOMY_SCHEMA_VERSION_KEY: 1,
                TASK_ROLE: "execution_task",
                ROOT_GOAL_TASK_ID: "root-task-1",
                WORKSPACE_PLAN_ID: "worker-plan-1",
            },
        )
    )
    await SqlWorkspacePlanOutboxRepository(db_session).enqueue(
        plan_id="worker-plan-1",
        workspace_id="workspace-1",
        event_type=WORKER_LAUNCH_EVENT,
        payload={
            "workspace_id": "workspace-1",
            "task_id": "task-no-leader-1",
            "worker_agent_id": "worker-agent",
            "actor_user_id": "worker-user-1",
        },
        metadata={"source": "task_execution_session.recovery"},
    )
    await db_session.commit()

    launched: list[dict[str, object]] = []

    def fake_schedule_worker_session(**kwargs: object) -> None:
        launched.append(kwargs)

    async def fake_worktree_preparer(
        _session: AsyncSession,
        _workspace_id: str,
        _task: WorkspaceTask,
        _extra_instructions: str | None,
        _attempt_id: str | None,
    ) -> str:
        return "[worktree-setup]\nstatus=skipped\n[/worktree-setup]"

    monkeypatch.setattr(
        "src.infrastructure.agent.workspace.worker_launch.schedule_worker_session",
        fake_schedule_worker_session,
    )
    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={
            WORKER_LAUNCH_EVENT: make_worker_launch_handler(
                worktree_preparer=fake_worktree_preparer
            ),
        },
        worker_id="worker-a",
    )

    assert await worker.run_once() == 1

    assert launched
    assert launched[0]["leader_agent_id"] == WORKSPACE_PLAN_SYSTEM_ACTOR_ID


@pytest.mark.asyncio
async def test_worker_launch_handler_blocks_when_worktree_setup_fails(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_workspace_and_plan(db_session)
    db_session.add(
        WorkspaceTaskModel(
            id="task-worktree-fail-1",
            workspace_id="workspace-1",
            title="Do not launch on setup failure",
            description="Worker launch must not continue after worktree setup fails.",
            created_by="worker-user-1",
            status="in_progress",
            priority=0,
            assignee_agent_id="worker-agent",
            metadata_json={
                AUTONOMY_SCHEMA_VERSION_KEY: 1,
                TASK_ROLE: "execution_task",
                ROOT_GOAL_TASK_ID: "root-task-1",
                WORKSPACE_PLAN_ID: "worker-plan-1",
            },
        )
    )
    db_session.add(
        WorkspaceTaskSessionAttemptModel(
            id="attempt-worktree-fail-1",
            workspace_task_id="task-worktree-fail-1",
            root_goal_task_id="root-task-1",
            workspace_id="workspace-1",
            attempt_number=1,
            status="running",
            worker_agent_id="worker-agent",
            leader_agent_id=None,
            candidate_artifacts_json=[],
            candidate_verifications_json=[],
        )
    )
    await SqlWorkspacePlanOutboxRepository(db_session).enqueue(
        plan_id="worker-plan-1",
        workspace_id="workspace-1",
        event_type=WORKER_LAUNCH_EVENT,
        payload={
            "workspace_id": "workspace-1",
            "task_id": "task-worktree-fail-1",
            "worker_agent_id": "worker-agent",
            "actor_user_id": "worker-user-1",
            "attempt_id": "attempt-worktree-fail-1",
        },
        metadata={"source": "unit"},
    )
    await db_session.commit()

    launched: list[dict[str, object]] = []

    def fake_schedule_worker_session(**kwargs: object) -> None:
        launched.append(kwargs)

    async def fake_worktree_preparer(
        _session: AsyncSession,
        _workspace_id: str,
        _task: WorkspaceTask,
        _extra_instructions: str | None,
        _attempt_id: str | None,
    ) -> str:
        return (
            "[worktree-setup]\n"
            "status=failed\n"
            "worktree_path=/workspace/.memstack/worktrees/attempt-fail-1\n"
            "reason=git worktree add failed\n"
            "[/worktree-setup]"
        )

    monkeypatch.setattr(
        "src.infrastructure.agent.workspace.worker_launch.schedule_worker_session",
        fake_schedule_worker_session,
    )
    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={
            WORKER_LAUNCH_EVENT: make_worker_launch_handler(
                worktree_preparer=fake_worktree_preparer
            ),
        },
        worker_id="worker-a",
    )

    assert await worker.run_once() == 1

    assert not launched
    task = await db_session.get(WorkspaceTaskModel, "task-worktree-fail-1")
    assert task is not None
    assert task.status == "blocked"
    assert task.blocker_reason == "worktree_setup_failed: git worktree add failed"
    assert task.metadata_json[CURRENT_ATTEMPT_ID] == "attempt-worktree-fail-1"
    assert task.metadata_json["last_attempt_status"] == "blocked"
    assert task.metadata_json[WORKTREE_SETUP]["status"] == "failed"
    assert task.metadata_json[ATTEMPT_WORKTREE]["worktree_path"] == (
        "/workspace/.memstack/worktrees/attempt-fail-1"
    )
    assert task.metadata_json[ACTIVE_EXECUTION_ROOT] == (
        "/workspace/.memstack/worktrees/attempt-fail-1"
    )
    attempt = await db_session.get(WorkspaceTaskSessionAttemptModel, "attempt-worktree-fail-1")
    assert attempt is not None
    assert attempt.status == "blocked"
    assert attempt.leader_feedback == "worktree_setup_failed: git worktree add failed"
    assert attempt.adjudication_reason == "worktree_setup_failed"
    assert attempt.completed_at is not None


@pytest.mark.asyncio
async def test_workspace_sandbox_runner_uses_api_adapter_when_agent_worker_uninitialized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict[str, object], float]] = []
    registered: list[object] = []

    class FakeAdapter:
        async def call_tool(
            self,
            sandbox_id: str,
            tool_name: str,
            arguments: dict[str, object],
            *,
            timeout: float,
        ) -> dict[str, object]:
            calls.append((sandbox_id, tool_name, arguments, timeout))
            return {"content": [{"type": "text", "text": "pipeline ok"}], "is_error": False}

    async def fake_api_adapter() -> FakeAdapter:
        return FakeAdapter()

    async def fake_resolve(project_id: str, *, tenant_id: str | None = None) -> str:
        assert project_id == "project-1"
        assert tenant_id == "tenant-1"
        return "sandbox-1"

    monkeypatch.setattr(
        "src.infrastructure.agent.state.agent_worker_state.get_mcp_sandbox_adapter",
        lambda: None,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.state.agent_worker_state.set_mcp_sandbox_adapter",
        lambda adapter: registered.append(adapter),
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.state.agent_worker_state._resolve_project_sandbox_id",
        fake_resolve,
    )
    monkeypatch.setattr(outbox_handlers, "_api_process_sandbox_adapter", fake_api_adapter)

    runner = _WorkspaceSandboxCommandRunner(project_id="project-1", tenant_id="tenant-1")
    result = await runner.run_command("echo pipeline ok", timeout=30)

    assert result["exit_code"] == 0
    assert result["stdout"] == "pipeline ok"
    assert result["stderr"] == ""
    assert registered
    assert calls == [
        (
            "sandbox-1",
            "bash",
            {"command": "echo pipeline ok", "timeout": 30},
            35.0,
        )
    ]


def test_structural_sandbox_commands_allow_git_status_in_code_root() -> None:
    assert _is_structural_sandbox_command("git -C /workspace/my-evo status --short")
    assert not _is_structural_sandbox_command("git -C /workspace/my-evo reset --hard")
    assert not _is_structural_sandbox_command("git -C /workspace/my-evo status --short\nrm -rf .")


def test_worktree_setup_command_installs_local_push_remote_when_missing() -> None:
    command = _worktree_setup_command(
        sandbox_code_root="/workspace/my-evo",
        worktree_path="/workspace/.memstack/worktrees/attempt-1",
        branch_name="workspace/node-1-attempt-1",
        base_ref="HEAD",
    )

    assert "git remote get-url origin" in command
    assert ".memstack/git-remotes/$N.git" in command
    assert 'git init --bare "$F"' in command
    assert 'git remote add origin "$F"' in command


def test_worktree_setup_command_initializes_greenfield_code_root(tmp_path: Path) -> None:
    sandbox_code_root = tmp_path / "greenfield"
    worktree_path = tmp_path / ".memstack" / "worktrees" / "attempt-1"

    command = _worktree_setup_command(
        sandbox_code_root=str(sandbox_code_root),
        worktree_path=str(worktree_path),
        branch_name="workspace/node-1-attempt-1",
        base_ref="HEAD",
    )

    result = subprocess.run(
        ["bash", "-lc", command],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert (sandbox_code_root / ".git").is_dir()
    assert (worktree_path / ".git").exists()
    assert "git_head=" in result.stdout


def test_worktree_setup_command_updates_reused_worktree_to_latest_base(
    tmp_path: Path,
) -> None:
    sandbox_code_root = tmp_path / "repo"
    worktree_path = tmp_path / ".memstack" / "worktrees" / "attempt-1"

    command = _worktree_setup_command(
        sandbox_code_root=str(sandbox_code_root),
        worktree_path=str(worktree_path),
        branch_name="workspace/node-1-attempt-1",
        base_ref="HEAD",
    )
    result = subprocess.run(
        ["bash", "-lc", command],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr

    (sandbox_code_root / "SPRINT.md").write_text("plan\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(sandbox_code_root), "add", "SPRINT.md"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(sandbox_code_root), "commit", "-m", "docs: add sprint plan"],
        check=True,
        capture_output=True,
        text=True,
    )
    (worktree_path / "local-note.txt").write_text("keep me\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", "-lc", command],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert (worktree_path / "SPRINT.md").read_text(encoding="utf-8") == "plan\n"
    assert (worktree_path / "local-note.txt").read_text(encoding="utf-8") == "keep me\n"


def test_worktree_setup_command_stays_below_small_websocket_frame_limit() -> None:
    command = _worktree_setup_command(
        sandbox_code_root="/workspace/my-evo",
        worktree_path="/workspace/my-evo/../.memstack/worktrees/attempt-2",
        branch_name="workspace/node-1-attempt-2",
        base_ref="HEAD",
        protected_worktree_names=("attempt-2", "attempt-active"),
    )

    assert len(command) < 1000
    assert "protected_worktree_names" not in command
    assert "stop_stale_pid" not in command
    assert 'git worktree add -B "$B" "$W" "$R"' in command


def test_worktree_integration_command_blocks_dirty_main_checkout() -> None:
    command = _worktree_integration_command(
        sandbox_code_root="/workspace/my-evo",
        worktree_path="/workspace/my-evo/../.memstack/worktrees/attempt-1",
        commit_ref="abc1234",
    )

    assert "git merge-base --is-ancestor abc1234 HEAD" in command
    assert 'dirty="$(git status --porcelain)"' in command
    assert 'echo "status=blocked_dirty_main"' in command
    assert "dirty_signature=%s" in command
    assert "dirty_generated_only=%s" in command
    assert "frontend/tests/screenshots/*" in command
    assert 'echo "generated_dirty_cleaned=true"' in command
    assert "git hash-object --stdin" in command
    assert "git merge --no-edit abc1234" in command
    assert 'echo "reason=merge_failed_aborted"' in command
    assert "git merge --abort" in command


def test_worktree_integration_command_cleans_generated_artifacts_before_merge(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    worktree_path = tmp_path / "attempt"
    repo.mkdir()

    def git(cwd: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip()

    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "worker@example.com")
    git(repo, "config", "user.name", "Worker")
    (repo / "frontend/tests/screenshots").mkdir(parents=True)
    (repo / "frontend/tests/e2e-results.json").write_text('{"status":"base"}\n', encoding="utf-8")
    (repo / "frontend/tests/screenshots/01-homepage.png").write_text("base\n", encoding="utf-8")
    (repo / "src/bounty").mkdir(parents=True)
    (repo / "src/bounty/routes.ts").write_text("stub\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")

    git(repo, "worktree", "add", str(worktree_path), "HEAD")
    git(worktree_path, "config", "user.email", "worker@example.com")
    git(worktree_path, "config", "user.name", "Worker")
    (worktree_path / "src/bounty/routes.ts").write_text("implemented\n", encoding="utf-8")
    git(worktree_path, "commit", "-am", "implement bounty")
    commit_ref = git(worktree_path, "rev-parse", "HEAD")

    (repo / "frontend/tests/e2e-results.json").write_text('{"status":"dirty"}\n', encoding="utf-8")
    (repo / "frontend/tests/screenshots/01-homepage.png").write_text("dirty\n", encoding="utf-8")
    (repo / "ITERATION-REPORT-20260520.md").write_text("stale report\n", encoding="utf-8")

    command = _worktree_integration_command(
        sandbox_code_root=str(repo),
        worktree_path=str(worktree_path),
        commit_ref=commit_ref,
    )
    result = subprocess.run(
        ["bash", "-lc", command],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "generated_dirty_cleaned=true" in result.stdout
    assert "status=merged" in result.stdout
    assert (repo / "src/bounty/routes.ts").read_text(encoding="utf-8") == "implemented\n"
    assert (repo / "frontend/tests/e2e-results.json").read_text(
        encoding="utf-8"
    ) == '{"status":"base"}\n'
    assert (repo / "frontend/tests/screenshots/01-homepage.png").read_text(
        encoding="utf-8"
    ) == "base\n"
    assert not (repo / "ITERATION-REPORT-20260520.md").exists()
    assert git(repo, "status", "--short") == ""


def test_worktree_integration_command_keeps_source_dirty_blocking(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    worktree_path = tmp_path / "attempt"
    repo.mkdir()

    def git(cwd: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip()

    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "worker@example.com")
    git(repo, "config", "user.name", "Worker")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src/app.ts").write_text("base\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    git(repo, "worktree", "add", str(worktree_path), "HEAD")
    git(worktree_path, "config", "user.email", "worker@example.com")
    git(worktree_path, "config", "user.name", "Worker")
    (worktree_path / "src/app.ts").write_text("candidate\n", encoding="utf-8")
    git(worktree_path, "commit", "-am", "candidate")
    commit_ref = git(worktree_path, "rev-parse", "HEAD")

    (repo / "README.md").write_text("local user note\n", encoding="utf-8")

    command = _worktree_integration_command(
        sandbox_code_root=str(repo),
        worktree_path=str(worktree_path),
        commit_ref=commit_ref,
    )
    result = subprocess.run(
        ["bash", "-lc", command],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 66
    assert "status=blocked_dirty_main" in result.stdout
    assert "dirty_generated_only=false" in result.stdout
    assert (repo / "README.md").read_text(encoding="utf-8") == "local user note\n"
    assert (repo / "src/app.ts").read_text(encoding="utf-8") == "base\n"


def test_drone_contract_suppresses_deploy_before_deploy_phase() -> None:
    contract = PipelineContractSpec(
        provider=DRONE_PROVIDER,
        deploy=PipelineDeploySpec(enabled=True, mode="docker"),
        provider_config={"repo": "octo/hello"},
    )
    node = PlanNode(
        id="node-implement",
        plan_id="plan-1",
        kind=PlanNodeKind.TASK,
        parent_id=PlanNodeId("root-node"),
        title="Implement feature",
        metadata={"iteration_phase": "implement"},
    )

    scoped = outbox_handlers._pipeline_contract_for_node_phase(contract, node=node)

    assert scoped.deploy is None
    assert scoped.provider_config["deploy_suppressed_for_phase"] == "implement"


def test_drone_contract_keeps_deploy_for_deploy_phase() -> None:
    contract = PipelineContractSpec(
        provider=DRONE_PROVIDER,
        deploy=PipelineDeploySpec(enabled=True, mode="docker"),
        provider_config={"repo": "octo/hello"},
    )
    node = PlanNode(
        id="node-deploy",
        plan_id="plan-1",
        kind=PlanNodeKind.TASK,
        parent_id=PlanNodeId("root-node"),
        title="Deploy feature",
        metadata={"iteration_phase": "deploy"},
    )

    scoped = outbox_handlers._pipeline_contract_for_node_phase(contract, node=node)

    assert scoped.deploy is contract.deploy
    assert "deploy_suppressed_for_phase" not in scoped.provider_config


def test_pipeline_commit_ref_prefers_accepted_repair_commit_over_stale_feature() -> None:
    node = PlanNode(
        id="node-deploy",
        plan_id="plan-1",
        kind=PlanNodeKind.TASK,
        parent_id=PlanNodeId("root-node"),
        title="Deploy feature",
        feature_checkpoint=FeatureCheckpoint(
            feature_id="feature-deploy",
            sequence=1,
            title="Deploy feature",
            worktree_path="/workspace/.memstack/worktrees/original",
            commit_ref="41480536",
        ),
        metadata={
            "verification_feedback_disposition": "accepted_via_repair_alternative",
            "accepted_repair_node_id": "node-repair",
            "accepted_repair_evidence_refs": [
                "preflight:read-progress",
                "commit_ref:2e83bccd",
                "git_diff_summary:.drone.yml +22 lines",
            ],
            "evidence_refs": ["commit_ref:41480536"],
        },
    )

    assert outbox_handlers._pipeline_commit_ref(node) == "2e83bccd"


def test_pipeline_commit_ref_prefers_current_attempt_report_over_repair_history() -> None:
    node = PlanNode(
        id="node-deploy",
        plan_id="plan-1",
        kind=PlanNodeKind.TASK,
        parent_id=PlanNodeId("root-node"),
        title="Deploy feature",
        current_attempt_id="attempt-current",
        feature_checkpoint=FeatureCheckpoint(
            feature_id="feature-deploy",
            sequence=1,
            title="Deploy feature",
            worktree_path="/workspace/.memstack/worktrees/original",
            commit_ref="41480536",
        ),
        metadata={
            "last_worker_report_attempt_id": "attempt-current",
            "candidate_verifications": ["preflight:git-status", "commit_ref:1469ac15"],
            "accepted_repair_evidence_refs": ["commit_ref:2e83bccd"],
            "evidence_refs": ["commit_ref:41480536"],
        },
    )

    assert outbox_handlers._pipeline_commit_ref(node) == "1469ac15"


def test_pipeline_commit_ref_uses_latest_current_attempt_report_commit() -> None:
    node = PlanNode(
        id="node-deploy",
        plan_id="plan-1",
        kind=PlanNodeKind.TASK,
        parent_id=PlanNodeId("root-node"),
        title="Deploy feature",
        current_attempt_id="attempt-current",
        metadata={
            "last_worker_report_attempt_id": "attempt-current",
            "candidate_verifications": ["preflight:git-status", "commit_ref:bce4286b"],
            "last_worker_report_artifacts": [
                "commit_ref:41480536",
                "git_diff_summary:.drone.yml old deploy fix",
                "commit_ref:13aeda8",
                "git_diff_summary:.drone.yml removed registry pull",
            ],
            "accepted_repair_evidence_refs": ["commit_ref:2e83bccd"],
        },
    )

    assert outbox_handlers._pipeline_commit_ref(node) == "13aeda8"


def test_pipeline_commit_ref_prefers_verified_commit_over_repair_history() -> None:
    node = PlanNode(
        id="node-deploy",
        plan_id="plan-1",
        kind=PlanNodeKind.TASK,
        parent_id=PlanNodeId("root-node"),
        title="Deploy feature",
        feature_checkpoint=FeatureCheckpoint(
            feature_id="feature-deploy",
            sequence=1,
            title="Deploy feature",
            worktree_path="/workspace/.memstack/worktrees/current",
            commit_ref="d7c44ac7",
        ),
        metadata={
            "verified_commit_ref": "d7c44ac7",
            "accepted_repair_evidence_refs": ["commit_ref:2e83bccd"],
            "evidence_refs": ["commit_ref:41480536"],
        },
    )

    assert outbox_handlers._pipeline_commit_ref(node) == "d7c44ac7"


def test_pipeline_commit_ref_ignores_stale_attempt_report_commit() -> None:
    node = PlanNode(
        id="node-deploy",
        plan_id="plan-1",
        kind=PlanNodeKind.TASK,
        parent_id=PlanNodeId("root-node"),
        title="Deploy feature",
        current_attempt_id="attempt-current",
        metadata={
            "last_worker_report_attempt_id": "attempt-stale",
            "candidate_verifications": ["commit_ref:1469ac15"],
            "accepted_repair_evidence_refs": ["commit_ref:2e83bccd"],
        },
    )

    assert outbox_handlers._pipeline_commit_ref(node) == "2e83bccd"


def test_pipeline_commit_ref_accepts_reported_candidate_without_report_attempt_id() -> None:
    node = PlanNode(
        id="node-deploy",
        plan_id="plan-1",
        kind=PlanNodeKind.TASK,
        parent_id=PlanNodeId("root-node"),
        title="Deploy feature",
        current_attempt_id="attempt-current",
        execution=TaskExecution.REPORTED,
        metadata={
            "candidate_verifications": ["commit_ref:345a2e42"],
            "accepted_repair_evidence_refs": ["commit_ref:2e83bccd"],
        },
    )

    assert outbox_handlers._pipeline_commit_ref(node) == "345a2e42"


def test_pipeline_commit_ref_ignores_unscoped_candidate_after_verifier_idle() -> None:
    node = PlanNode(
        id="node-deploy",
        plan_id="plan-1",
        kind=PlanNodeKind.TASK,
        parent_id=PlanNodeId("root-node"),
        title="Deploy feature",
        current_attempt_id="attempt-current",
        execution=TaskExecution.IDLE,
        metadata={
            "verified_commit_ref": "13aeda8",
            "candidate_verifications": ["preflight:git-status", "commit_ref:c6b1e7d"],
            "last_worker_report_artifacts": [
                "commit_ref:13aeda8",
                "git_diff_summary:.drone.yml old deploy fix",
                "commit_ref:c6b1e7d",
                "git_diff_summary:.drone.yml pull built image",
            ],
            "accepted_repair_evidence_refs": ["commit_ref:2e83bccd"],
        },
    )

    assert outbox_handlers._pipeline_commit_ref(node) == "13aeda8"


def test_pipeline_commit_ref_uses_current_attempt_record_after_verifier_idle() -> None:
    node = PlanNode(
        id="node-deploy",
        plan_id="plan-1",
        kind=PlanNodeKind.TASK,
        parent_id=PlanNodeId("root-node"),
        title="Deploy feature",
        current_attempt_id="attempt-current",
        execution=TaskExecution.IDLE,
        metadata={
            "verified_commit_ref": "13aeda8",
            "candidate_verifications": ["preflight:git-status", "commit_ref:stale123"],
        },
    )
    attempt = WorkspaceTaskSessionAttemptModel(
        id="attempt-current",
        workspace_task_id="task-1",
        root_goal_task_id="root-task-1",
        workspace_id="workspace-1",
        attempt_number=4,
        status="accepted",
        conversation_id="conversation-current",
        worker_agent_id="worker-agent",
        leader_agent_id=BUILTIN_SISYPHUS_ID,
        candidate_summary="done",
        candidate_artifacts_json=[
            "commit_ref:13aeda8",
            "git_diff_summary:.drone.yml old deploy fix",
            "commit_ref:c6b1e7d",
            "git_diff_summary:.drone.yml pull built image",
        ],
        candidate_verifications_json=["preflight:git-status", "commit_ref:c6b1e7d"],
    )

    assert outbox_handlers._pipeline_commit_ref(node, current_attempt=attempt) == "c6b1e7d"


def test_pipeline_commit_ref_ignores_nonmatching_attempt_record() -> None:
    node = PlanNode(
        id="node-deploy",
        plan_id="plan-1",
        kind=PlanNodeKind.TASK,
        parent_id=PlanNodeId("root-node"),
        title="Deploy feature",
        current_attempt_id="attempt-current",
        execution=TaskExecution.IDLE,
        metadata={"verified_commit_ref": "13aeda8"},
    )
    attempt = WorkspaceTaskSessionAttemptModel(
        id="attempt-stale",
        workspace_task_id="task-1",
        root_goal_task_id="root-task-1",
        workspace_id="workspace-1",
        attempt_number=3,
        status="accepted",
        conversation_id="conversation-stale",
        worker_agent_id="worker-agent",
        leader_agent_id=BUILTIN_SISYPHUS_ID,
        candidate_artifacts_json=["commit_ref:c6b1e7d"],
        candidate_verifications_json=[],
    )

    assert outbox_handlers._pipeline_commit_ref(node, current_attempt=attempt) == "13aeda8"


def test_pipeline_commit_ref_accepts_reported_candidate_after_verifier_idle_with_attempt() -> None:
    node = PlanNode(
        id="node-deploy",
        plan_id="plan-1",
        kind=PlanNodeKind.TASK,
        parent_id=PlanNodeId("root-node"),
        title="Deploy feature",
        current_attempt_id="attempt-current",
        execution=TaskExecution.IDLE,
        metadata={
            "verified_commit_ref": "13aeda8",
            "candidate_verifications": ["preflight:git-status", "commit_ref:c6b1e7d"],
            "accepted_repair_evidence_refs": ["commit_ref:2e83bccd"],
        },
    )
    attempt = WorkspaceTaskSessionAttemptModel(
        id="attempt-current",
        workspace_task_id="task-1",
        root_goal_task_id="root-task-1",
        workspace_id="workspace-1",
        attempt_number=4,
        status="accepted",
        conversation_id="conversation-current",
        worker_agent_id="worker-agent",
        leader_agent_id=BUILTIN_SISYPHUS_ID,
        candidate_artifacts_json=[],
        candidate_verifications_json=["preflight:git-status", "commit_ref:c6b1e7d"],
    )

    assert outbox_handlers._pipeline_commit_ref(node, current_attempt=attempt) == "c6b1e7d"


def test_pipeline_commit_ref_uses_reported_metadata_when_attempt_record_unavailable() -> None:
    node = PlanNode(
        id="node-deploy",
        plan_id="plan-1",
        kind=PlanNodeKind.TASK,
        parent_id=PlanNodeId("root-node"),
        title="Deploy feature",
        current_attempt_id="attempt-current",
        execution=TaskExecution.REPORTED,
        metadata={
            "verified_commit_ref": "13aeda8",
            "candidate_verifications": ["preflight:git-status", "commit_ref:c6b1e7d"],
        },
    )

    assert outbox_handlers._pipeline_commit_ref(node) == "c6b1e7d"


@pytest.mark.asyncio
async def test_publish_git_ref_to_source_control_fast_forwards_and_pushes(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    remote = tmp_path / "remote.git"
    repo.mkdir()

    def git(cwd: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip()

    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "worker@example.com")
    git(repo, "config", "user.name", "Worker")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "base")

    git(tmp_path, "init", "--bare", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "origin", "main")

    (repo / "README.md").write_text("candidate\n", encoding="utf-8")
    git(repo, "commit", "-am", "candidate")
    candidate_commit = git(repo, "rev-parse", "HEAD")
    git(repo, "reset", "--hard", "HEAD~1")

    publish = await outbox_handlers._publish_git_ref_to_source_control(
        host_code_root=repo,
        commit_ref=candidate_commit,
        branch="main",
        remote_url=str(remote),
        token=None,
        token_env=None,
    )

    assert publish == {
        "status": "published",
        "reason": None,
        "published_commit": candidate_commit,
    }
    assert git(repo, "rev-parse", "HEAD") == candidate_commit
    assert git(remote, "rev-parse", "refs/heads/main") == candidate_commit


@pytest.mark.asyncio
async def test_publish_git_ref_to_source_control_uses_temp_worktree_when_main_dirty(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    remote = tmp_path / "remote.git"
    repo.mkdir()

    def git(cwd: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip()

    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "worker@example.com")
    git(repo, "config", "user.name", "Worker")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    (repo / "app.txt").write_text("base\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    base_commit = git(repo, "rev-parse", "HEAD")

    git(tmp_path, "init", "--bare", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "origin", "main")

    git(repo, "checkout", "-b", "candidate")
    (repo / "app.txt").write_text("candidate\n", encoding="utf-8")
    git(repo, "commit", "-am", "candidate")
    candidate_commit = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "main")
    (repo / "README.md").write_text("dirty local note\n", encoding="utf-8")

    publish = await outbox_handlers._publish_git_ref_to_source_control(
        host_code_root=repo,
        commit_ref=candidate_commit,
        branch="main",
        remote_url=str(remote),
        token=None,
        token_env=None,
    )

    assert publish == {
        "status": "published",
        "reason": "published from temporary worktree because main checkout has uncommitted changes",
        "published_commit": candidate_commit,
    }
    assert git(repo, "rev-parse", "HEAD") == base_commit
    assert git(repo, "status", "--short") == "M README.md"
    assert (repo / "README.md").read_text(encoding="utf-8") == "dirty local note\n"
    assert git(remote, "rev-parse", "refs/heads/main") == candidate_commit


@pytest.mark.asyncio
async def test_publish_git_ref_to_source_control_honors_candidate_when_dirty_head_descends(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    remote = tmp_path / "remote.git"
    repo.mkdir()

    def git(cwd: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip()

    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "worker@example.com")
    git(repo, "config", "user.name", "Worker")
    (repo / ".drone.yml").write_text("deploy: base\n", encoding="utf-8")
    git(repo, "add", ".drone.yml")
    git(repo, "commit", "-m", "base")

    (repo / ".drone.yml").write_text("deploy: docker build\n", encoding="utf-8")
    git(repo, "commit", "-am", "candidate")
    candidate_commit = git(repo, "rev-parse", "HEAD")

    (repo / ".drone.yml").write_text("deploy: docker pull stale\n", encoding="utf-8")
    git(repo, "commit", "-am", "stale published head")
    stale_head = git(repo, "rev-parse", "HEAD")

    git(tmp_path, "init", "--bare", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "origin", "main")
    (repo / "local-note.txt").write_text("dirty\n", encoding="utf-8")

    publish = await outbox_handlers._publish_git_ref_to_source_control(
        host_code_root=repo,
        commit_ref=candidate_commit,
        branch="main",
        remote_url=str(remote),
        token=None,
        token_env=None,
    )

    published_commit = git(remote, "rev-parse", "refs/heads/main")
    published_drone = git(tmp_path, "--git-dir", str(remote), "show", "refs/heads/main:.drone.yml")

    assert publish["status"] == "published"
    assert publish["published_commit"] == published_commit
    assert published_commit != stale_head
    assert published_drone == "deploy: docker build"
    assert git(repo, "rev-parse", "HEAD") == stale_head
    assert git(repo, "status", "--short") == "?? local-note.txt"


@pytest.mark.asyncio
async def test_publish_git_ref_to_source_control_merges_remote_when_branch_advanced(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    remote = tmp_path / "remote.git"
    remote_clone = tmp_path / "remote-clone"
    repo.mkdir()

    def git(cwd: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip()

    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "worker@example.com")
    git(repo, "config", "user.name", "Worker")
    (repo / ".drone.yml").write_text("pipeline: base\n", encoding="utf-8")
    git(repo, "add", ".drone.yml")
    git(repo, "commit", "-m", "base")

    git(tmp_path, "init", "--bare", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "origin", "main")

    git(repo, "checkout", "-b", "repair")
    (repo / ".drone.yml").write_text("pipeline: repair\n", encoding="utf-8")
    git(repo, "commit", "-am", "repair")
    repair_commit = git(repo, "rev-parse", "HEAD")

    git(tmp_path, "clone", str(remote), str(remote_clone))
    git(remote_clone, "config", "user.email", "remote@example.com")
    git(remote_clone, "config", "user.name", "Remote")
    (remote_clone / ".drone.yml").write_text("pipeline: stale\n", encoding="utf-8")
    git(remote_clone, "commit", "-am", "stale remote")
    stale_remote_commit = git(remote_clone, "rev-parse", "HEAD")
    git(remote_clone, "push", "origin", "main")

    publish = await outbox_handlers._publish_git_ref_to_source_control(
        host_code_root=repo,
        commit_ref=repair_commit,
        branch="main",
        remote_url=str(remote),
        token=None,
        token_env=None,
    )

    assert publish["status"] == "published"
    assert publish["reason"] == (
        "merged remote branch before publish using local conflict preference"
    )
    published_commit = str(publish["published_commit"])
    assert published_commit != repair_commit
    assert git(remote, "rev-parse", "refs/heads/main") == published_commit
    assert git(remote, "show", "refs/heads/main:.drone.yml") == "pipeline: repair"
    git(remote, "merge-base", "--is-ancestor", repair_commit, "refs/heads/main")
    git(remote, "merge-base", "--is-ancestor", stale_remote_commit, "refs/heads/main")


@pytest.mark.asyncio
async def test_publish_git_ref_to_source_control_restores_candidate_paths_after_clean_merge(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    remote = tmp_path / "remote.git"
    remote_clone = tmp_path / "remote-clone"
    repo.mkdir()

    def git(cwd: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip()

    base_drone = (
        "kind: pipeline\n"
        "type: docker\n"
        "name: default\n"
        "\n"
        "steps:\n"
        "  - name: deploy\n"
        "    image: docker:cli\n"
        "    environment:\n"
        "      DOCKER_HOST: unix:///var/run/docker.sock\n"
        "    commands:\n"
        "      - docker pull host.docker.internal:5001/my-evo:latest\n"
    )
    candidate_drone = base_drone.replace(
        "docker pull host.docker.internal:5001/my-evo:latest",
        "docker build -t my-evo:drone-docker-e2e -f Dockerfile .",
    )
    stale_remote_drone = base_drone.replace(
        "      DOCKER_HOST: unix:///var/run/docker.sock",
        "      - DOCKER_HOST=unix:///var/run/docker.sock",
    )

    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "worker@example.com")
    git(repo, "config", "user.name", "Worker")
    (repo / ".drone.yml").write_text(base_drone, encoding="utf-8")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")

    git(tmp_path, "init", "--bare", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "origin", "main")

    git(repo, "checkout", "-b", "repair")
    (repo / ".drone.yml").write_text(candidate_drone, encoding="utf-8")
    git(repo, "commit", "-am", "repair drone deploy")
    repair_commit = git(repo, "rev-parse", "HEAD")

    git(tmp_path, "clone", str(remote), str(remote_clone))
    git(remote_clone, "config", "user.email", "remote@example.com")
    git(remote_clone, "config", "user.name", "Remote")
    (remote_clone / ".drone.yml").write_text(stale_remote_drone, encoding="utf-8")
    (remote_clone / "REMOTE.md").write_text("remote-only\n", encoding="utf-8")
    git(remote_clone, "add", ".")
    git(remote_clone, "commit", "-m", "remote drift")
    stale_remote_commit = git(remote_clone, "rev-parse", "HEAD")
    git(remote_clone, "push", "origin", "main")

    publish = await outbox_handlers._publish_git_ref_to_source_control(
        host_code_root=repo,
        commit_ref=repair_commit,
        branch="main",
        remote_url=str(remote),
        token=None,
        token_env=None,
    )

    assert publish["status"] == "published"
    assert publish["reason"] == (
        "merged remote branch before publish; restored candidate tree paths after merge"
    )
    published_commit = str(publish["published_commit"])
    assert git(remote, "rev-parse", "refs/heads/main") == published_commit
    assert git(remote, "show", "refs/heads/main:.drone.yml") == candidate_drone.rstrip("\n")
    assert git(remote, "show", "refs/heads/main:REMOTE.md") == "remote-only"
    git(remote, "merge-base", "--is-ancestor", repair_commit, "refs/heads/main")
    git(remote, "merge-base", "--is-ancestor", stale_remote_commit, "refs/heads/main")


@pytest.mark.asyncio
async def test_publish_git_ref_to_source_control_restores_candidate_tree_when_remote_drifted(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    remote = tmp_path / "remote.git"
    remote_clone = tmp_path / "remote-clone"
    repo.mkdir()

    def git(cwd: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip()

    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "worker@example.com")
    git(repo, "config", "user.name", "Worker")
    (repo / ".drone.yml").write_text(
        "commands:\n  - docker network create workspace-deploy 2>/dev/null || true\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")

    git(tmp_path, "init", "--bare", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "origin", "main")

    git(repo, "checkout", "-b", "review")
    (repo / "docs").mkdir()
    (repo / "docs" / "ITERATION-REVIEW.md").write_text("review\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "review docs")
    review_commit = git(repo, "rev-parse", "HEAD")

    git(tmp_path, "clone", str(remote), str(remote_clone))
    git(remote_clone, "config", "user.email", "remote@example.com")
    git(remote_clone, "config", "user.name", "Remote")
    (remote_clone / ".drone.yml").write_text(
        "commands:\n"
        "  - docker network rm workspace-deploy 2>/dev/null || true\n"
        "  - docker network create workspace-deploy\n",
        encoding="utf-8",
    )
    (remote_clone / "REMOTE.md").write_text("remote-only\n", encoding="utf-8")
    git(remote_clone, "add", ".")
    git(remote_clone, "commit", "-m", "stale remote deploy")
    stale_remote_commit = git(remote_clone, "rev-parse", "HEAD")
    git(remote_clone, "push", "origin", "main")

    publish = await outbox_handlers._publish_git_ref_to_source_control(
        host_code_root=repo,
        commit_ref=review_commit,
        branch="main",
        remote_url=str(remote),
        token=None,
        token_env=None,
    )

    assert publish["status"] == "published"
    assert publish["reason"] == (
        "merged remote branch before publish; restored candidate tree paths after merge"
    )
    assert (
        git(remote, "show", "refs/heads/main:.drone.yml")
        == "commands:\n  - docker network create workspace-deploy 2>/dev/null || true"
    )
    assert git(remote, "show", "refs/heads/main:REMOTE.md") == "remote-only"
    assert git(remote, "show", "refs/heads/main:docs/ITERATION-REVIEW.md") == "review"
    git(remote, "merge-base", "--is-ancestor", review_commit, "refs/heads/main")
    git(remote, "merge-base", "--is-ancestor", stale_remote_commit, "refs/heads/main")


def test_source_publish_metadata_preserves_worker_commit_after_merge_publish() -> None:
    metadata = outbox_handlers._source_publish_metadata(
        status="published",
        reason="merged remote branch before publish using local conflict preference",
        commit_ref="6d2c2848",
        source_commit_ref="bce4286b",
        branch="main",
        token_env="GITHUB_TOKEN",
    )

    assert metadata["source_publish_commit_ref"] == "6d2c2848"
    assert metadata["source_publish_source_commit_ref"] == "bce4286b"


def test_reported_pipeline_result_guard_ignores_missing_pipeline_status() -> None:
    node = PlanNode(
        id="node-without-pipeline",
        plan_id="plan-1",
        kind=PlanNodeKind.TASK,
        parent_id=PlanNodeId("root-node"),
        title="Reported node",
        execution=TaskExecution.REPORTED,
        current_attempt_id="attempt-1",
        metadata={},
    )

    assert (
        outbox_handlers._reported_node_has_pipeline_result_pending_verification(
            node,
            "rejected",
        )
        is False
    )


@pytest.mark.asyncio
async def test_publish_git_ref_to_source_control_merges_unrelated_remote_history(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    remote_seed = tmp_path / "remote-seed"
    remote = tmp_path / "remote.git"
    repo.mkdir()
    remote_seed.mkdir()

    def git(cwd: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip()

    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "worker@example.com")
    git(repo, "config", "user.name", "Worker")
    (repo / ".drone.yml").write_text("pipeline: repair\n", encoding="utf-8")
    git(repo, "add", ".drone.yml")
    git(repo, "commit", "-m", "repair")
    repair_commit = git(repo, "rev-parse", "HEAD")

    git(remote_seed, "init", "-b", "main")
    git(remote_seed, "config", "user.email", "remote@example.com")
    git(remote_seed, "config", "user.name", "Remote")
    (remote_seed / ".drone.yml").write_text("pipeline: stale\n", encoding="utf-8")
    (remote_seed / "remote.txt").write_text("remote\n", encoding="utf-8")
    git(remote_seed, "add", ".")
    git(remote_seed, "commit", "-m", "unrelated remote")
    unrelated_remote_commit = git(remote_seed, "rev-parse", "HEAD")
    git(tmp_path, "init", "--bare", str(remote))
    git(remote_seed, "remote", "add", "origin", str(remote))
    git(remote_seed, "push", "origin", "main")

    publish = await outbox_handlers._publish_git_ref_to_source_control(
        host_code_root=repo,
        commit_ref=repair_commit,
        branch="main",
        remote_url=str(remote),
        token=None,
        token_env=None,
    )

    assert publish["status"] == "published"
    assert publish["reason"] == (
        "merged unrelated remote branch before publish using local conflict preference"
    )
    published_commit = str(publish["published_commit"])
    assert published_commit != repair_commit
    assert git(remote, "rev-parse", "refs/heads/main") == published_commit
    assert git(remote, "show", "refs/heads/main:.drone.yml") == "pipeline: repair"
    assert git(remote, "show", "refs/heads/main:remote.txt") == "remote"
    git(remote, "merge-base", "--is-ancestor", repair_commit, "refs/heads/main")
    git(remote, "merge-base", "--is-ancestor", unrelated_remote_commit, "refs/heads/main")


@pytest.mark.asyncio
async def test_publish_git_ref_to_source_control_uses_temp_worktree_when_candidate_is_unrelated(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    remote = tmp_path / "remote.git"
    repo.mkdir()

    def git(cwd: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip()

    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "worker@example.com")
    git(repo, "config", "user.name", "Worker")
    (repo / ".drone.yml").write_text("pipeline: stale\n", encoding="utf-8")
    git(repo, "add", ".drone.yml")
    git(repo, "commit", "-m", "base")
    base_commit = git(repo, "rev-parse", "HEAD")

    git(tmp_path, "init", "--bare", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "origin", "main")

    git(repo, "checkout", "--orphan", "candidate")
    git(repo, "rm", "-rf", ".")
    (repo / ".drone.yml").write_text("pipeline: repair\n", encoding="utf-8")
    git(repo, "add", ".drone.yml")
    git(repo, "commit", "-m", "repair")
    repair_commit = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "main")

    publish = await outbox_handlers._publish_git_ref_to_source_control(
        host_code_root=repo,
        commit_ref=repair_commit,
        branch="main",
        remote_url=str(remote),
        token=None,
        token_env=None,
    )

    assert publish["status"] == "published"
    assert publish["reason"] == (
        "merged unrelated remote branch before publish using local conflict preference"
    )
    published_commit = str(publish["published_commit"])
    assert published_commit != repair_commit
    assert git(repo, "rev-parse", "HEAD") == base_commit
    assert git(remote, "show", "refs/heads/main:.drone.yml") == "pipeline: repair"
    git(remote, "merge-base", "--is-ancestor", repair_commit, "refs/heads/main")
    git(remote, "merge-base", "--is-ancestor", base_commit, "refs/heads/main")


def test_commit_ref_token_accepts_hash_prefix_and_rejects_notes() -> None:
    assert _commit_ref_token("c459cc73 (second evidence commit)") == "c459cc73"
    assert _commit_ref_token("2055a373e2dfecf90f03c687fcecffa8be330746") == (
        "2055a373e2dfecf90f03c687fcecffa8be330746"
    )
    assert _commit_ref_token("branch-name") is None
    assert _integration_status_from_output("status=blocked_dirty_main\n M file") == (
        "blocked_dirty_main"
    )
    assert (
        outbox_handlers._integration_output_field(
            "dirty_signature",
            "status=blocked_dirty_main\ndirty_signature=abc123\n M file",
        )
        == "abc123"
    )


def test_first_prefixed_ref_accepts_artifact_wrapped_commit_ref() -> None:
    refs = [
        "artifact:commit_ref:edd6b848",
        "artifact:changed_file:docs/INDEX.md",
        "git_diff_summary:1 file changed",
    ]

    assert _first_prefixed_ref(refs, "commit_ref:") == "edd6b848"
    assert _first_prefixed_ref(refs, "git_diff_summary:") == "1 file changed"


@pytest.mark.asyncio
async def test_accepted_terminal_attempt_integrates_worktree_commit(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_workspace_and_plan(db_session)
    workspace = (
        await db_session.execute(select(WorkspaceModel).where(WorkspaceModel.id == "workspace-1"))
    ).scalar_one()
    workspace.metadata_json = {"code_context": {"sandbox_code_root": "/workspace/my-evo"}}
    task = WorkspaceTaskModel(
        id="task-integrate-1",
        workspace_id="workspace-1",
        title="Integrate accepted commit",
        description="Project accepted worktree commit to the main checkout.",
        created_by="worker-user-1",
        status="in_progress",
        priority=0,
        metadata_json={
            AUTONOMY_SCHEMA_VERSION_KEY: 1,
            ROOT_GOAL_TASK_ID: "root-task-1",
            "feature_checkpoint": {
                "feature_id": "feature-integrate",
                "worktree_path": "${sandbox_code_root}/../.memstack/worktrees/attempt-integrate",
                "branch_name": "workspace/node-integrate-attempt",
            },
        },
    )
    task_id = task.id
    attempt = WorkspaceTaskSessionAttemptModel(
        id="attempt-integrate",
        workspace_task_id=task.id,
        root_goal_task_id="root-task-1",
        workspace_id="workspace-1",
        attempt_number=1,
        status="accepted",
        conversation_id="conversation-integrate",
        worker_agent_id="worker-agent",
        leader_agent_id=BUILTIN_SISYPHUS_ID,
        candidate_summary="done",
        candidate_artifacts_json=["commit_ref:abc1234", "changed_file:src/example.py"],
        candidate_verifications_json=["commit_ref:abc1234", "test_run:pytest"],
    )
    db_session.add_all([task, attempt])
    await db_session.flush()

    commands: list[str] = []

    class FakeRunner:
        def __init__(self, *, project_id: str, tenant_id: str) -> None:
            assert project_id == "worker-project-1"
            assert tenant_id == "worker-tenant-1"

        async def run_command(self, command: str, *, timeout: int) -> dict[str, object]:
            assert timeout == 120
            commands.append(command)
            return {"exit_code": 0, "stdout": "status=merged\ngit_head=def5678\n", "stderr": ""}

    monkeypatch.setattr(outbox_handlers, "_WorkspaceSandboxCommandRunner", FakeRunner)
    node = PlanNode(
        id="node-integrate",
        plan_id="worker-plan-1",
        kind=PlanNodeKind.TASK,
        parent_id=PlanNodeId("root-node"),
        title="Integrate accepted commit",
        workspace_task_id=task.id,
        current_attempt_id=attempt.id,
        feature_checkpoint=FeatureCheckpoint(
            feature_id="feature-integrate",
            worktree_path="${sandbox_code_root}/../.memstack/worktrees/attempt-integrate",
            branch_name="workspace/node-integrate-attempt",
        ),
    )

    result = await outbox_handlers._project_accepted_terminal_attempt_to_task(
        session=db_session,
        workspace_id="workspace-1",
        node=node,
        attempt=attempt,
        summary="accepted",
        now=datetime.now(UTC),
    )

    assert result["worktree_integration_status"] == "merged"
    assert result["worktree_integration_commit_ref"] == "abc1234"
    assert commands
    assert "cd /workspace/my-evo" in commands[0]
    assert "git merge --no-edit abc1234" in commands[0]
    db_session.expire_all()
    projected_task = await db_session.get(WorkspaceTaskModel, task_id)
    assert projected_task is not None
    assert projected_task.metadata_json["worktree_integration_status"] == "merged"
    assert projected_task.metadata_json["feature_checkpoint"]["commit_ref"] == "abc1234"
    event = (
        await db_session.execute(
            select(WorkspacePlanEventModel).where(
                WorkspacePlanEventModel.event_type == "accepted_worktree_integrated"
            )
        )
    ).scalar_one()
    assert event.payload_json["commit_ref"] == "abc1234"
    assert event.payload_json["worktree_path"] == (
        "/workspace/.memstack/worktrees/attempt-integrate"
    )


@pytest.mark.asyncio
async def test_accepted_terminal_attempt_uses_feature_checkpoint_commit_ref(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_workspace_and_plan(db_session)
    workspace = (
        await db_session.execute(select(WorkspaceModel).where(WorkspaceModel.id == "workspace-1"))
    ).scalar_one()
    workspace.metadata_json = {"code_context": {"sandbox_code_root": "/workspace/my-evo"}}
    task = WorkspaceTaskModel(
        id="task-checkpoint-integrate-1",
        workspace_id="workspace-1",
        title="Integrate accepted checkpoint commit",
        description="Project accepted checkpoint commit to the main checkout.",
        created_by="worker-user-1",
        status="done",
        priority=0,
        metadata_json={
            AUTONOMY_SCHEMA_VERSION_KEY: 1,
            ROOT_GOAL_TASK_ID: "root-task-1",
        },
    )
    attempt = WorkspaceTaskSessionAttemptModel(
        id="attempt-checkpoint-integrate",
        workspace_task_id=task.id,
        root_goal_task_id="root-task-1",
        workspace_id="workspace-1",
        attempt_number=1,
        status="accepted",
        conversation_id="conversation-checkpoint-integrate",
        worker_agent_id="worker-agent",
        leader_agent_id=BUILTIN_SISYPHUS_ID,
        candidate_summary=None,
        candidate_artifacts_json=[],
        candidate_verifications_json=[],
    )
    db_session.add_all([task, attempt])
    await db_session.flush()

    commands: list[str] = []

    class FakeRunner:
        def __init__(self, *, project_id: str, tenant_id: str) -> None:
            assert project_id == "worker-project-1"
            assert tenant_id == "worker-tenant-1"

        async def run_command(self, command: str, *, timeout: int) -> dict[str, object]:
            assert timeout == 120
            commands.append(command)
            return {"exit_code": 0, "stdout": "status=merged\ngit_head=def5678\n", "stderr": ""}

    monkeypatch.setattr(outbox_handlers, "_WorkspaceSandboxCommandRunner", FakeRunner)
    node = PlanNode(
        id="node-checkpoint-integrate",
        plan_id="worker-plan-1",
        kind=PlanNodeKind.TASK,
        parent_id=PlanNodeId("root-node"),
        title="Integrate accepted checkpoint commit",
        workspace_task_id=task.id,
        current_attempt_id=attempt.id,
        feature_checkpoint=FeatureCheckpoint(
            feature_id="feature-checkpoint-integrate",
            worktree_path="${sandbox_code_root}/../.memstack/worktrees/attempt-checkpoint-integrate",
            branch_name="workspace/node-checkpoint-integrate-attempt",
            commit_ref="abc1234",
        ),
        metadata={
            "terminal_attempt_status": "accepted",
            "last_verification_attempt_id": attempt.id,
        },
    )

    assert not await outbox_handlers._accepted_attempt_projection_complete_for_node(
        session=db_session,
        workspace_id="workspace-1",
        node=node,
        attempt=attempt,
    )

    result = await outbox_handlers._project_accepted_terminal_attempt_to_task(
        session=db_session,
        workspace_id="workspace-1",
        node=node,
        attempt=attempt,
        summary="accepted from recovery",
        now=datetime.now(UTC),
    )

    assert result["worktree_integration_status"] == "merged"
    assert result["worktree_integration_commit_ref"] == "abc1234"
    assert commands
    assert "git merge --no-edit abc1234" in commands[0]


@pytest.mark.asyncio
async def test_projection_incomplete_when_attempt_commit_ref_was_not_projected(
    db_session: AsyncSession,
) -> None:
    attempt = WorkspaceTaskSessionAttemptModel(
        id="attempt-missing-node-commit-1",
        workspace_task_id="task-missing-node-commit-1",
        root_goal_task_id="root-task-1",
        workspace_id="workspace-1",
        attempt_number=1,
        status="accepted",
        conversation_id="conversation-missing-node-commit",
        worker_agent_id="worker-agent",
        leader_agent_id=BUILTIN_SISYPHUS_ID,
        candidate_summary="done",
        candidate_artifacts_json=["commit_ref:abc1234"],
        candidate_verifications_json=["preflight:git-status"],
    )
    node = PlanNode(
        id="node-missing-node-commit",
        plan_id="worker-plan-1",
        kind=PlanNodeKind.TASK,
        parent_id=PlanNodeId("root-node"),
        title="Accepted attempt with unprojected commit",
        workspace_task_id=attempt.workspace_task_id,
        current_attempt_id=attempt.id,
        metadata={
            "terminal_attempt_status": "accepted",
            "last_verification_attempt_id": attempt.id,
        },
    )

    assert not await outbox_handlers._accepted_attempt_projection_complete_for_node(
        session=db_session,
        workspace_id="workspace-1",
        node=node,
        attempt=attempt,
    )


@pytest.mark.asyncio
async def test_blocked_dirty_main_projection_waits_until_dirty_signature_changes(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_workspace_and_plan(db_session)
    workspace = (
        await db_session.execute(select(WorkspaceModel).where(WorkspaceModel.id == "workspace-1"))
    ).scalar_one()
    workspace.metadata_json = {"code_context": {"sandbox_code_root": "/workspace/my-evo"}}
    task = WorkspaceTaskModel(
        id="task-blocked-integration-1",
        workspace_id="workspace-1",
        title="Blocked accepted integration",
        description="Accepted commit blocked by dirty main checkout.",
        created_by="worker-user-1",
        status="completed",
        priority=0,
        metadata_json={AUTONOMY_SCHEMA_VERSION_KEY: 1, ROOT_GOAL_TASK_ID: "root-task-1"},
    )
    attempt = WorkspaceTaskSessionAttemptModel(
        id="attempt-blocked-integration-1",
        workspace_task_id=task.id,
        root_goal_task_id="root-task-1",
        workspace_id="workspace-1",
        attempt_number=1,
        status="accepted",
        conversation_id="conversation-blocked-integration",
        worker_agent_id="worker-agent",
        leader_agent_id=BUILTIN_SISYPHUS_ID,
        candidate_summary="done",
        candidate_artifacts_json=["commit_ref:abc1234"],
        candidate_verifications_json=["commit_ref:abc1234"],
    )
    db_session.add_all([task, attempt])
    await db_session.flush()

    commands: list[str] = []
    runner_init_args: list[tuple[str, str]] = []
    runner_result = {
        "exit_code": 0,
        "stdout": "status=dirty\ndirty_signature=sig-current\n M scratch.js\n",
        "stderr": "",
    }

    class FakeRunner:
        def __init__(self, *, project_id: str, tenant_id: str) -> None:
            runner_init_args.append((project_id, tenant_id))

        async def run_command(self, command: str, *, timeout: int) -> dict[str, object]:
            assert timeout == 30
            commands.append(command)
            return runner_result

    monkeypatch.setattr(outbox_handlers, "_WorkspaceSandboxCommandRunner", FakeRunner)
    node = PlanNode(
        id="node-blocked-integration",
        plan_id="worker-plan-1",
        kind=PlanNodeKind.TASK,
        parent_id=PlanNodeId("root-node"),
        title="Blocked accepted integration",
        workspace_task_id=task.id,
        current_attempt_id=attempt.id,
        metadata={
            "terminal_attempt_status": "accepted",
            "last_verification_attempt_id": attempt.id,
            "verified_commit_ref": "abc1234",
            "worktree_integration_status": "blocked_dirty_main",
            "worktree_integration_dirty_signature": "sig-current",
        },
    )

    assert await outbox_handlers._accepted_attempt_projection_complete_for_node(
        session=db_session,
        workspace_id="workspace-1",
        node=node,
        attempt=attempt,
    )
    assert commands
    assert runner_init_args == [("worker-project-1", "worker-tenant-1")]
    assert "git status --porcelain" in commands[0]

    runner_result["stdout"] = (
        "status=dirty\n"
        "dirty_signature=sig-current\n"
        "dirty_generated_only=true\n"
        " M frontend/tests/screenshots/01-homepage.png\n"
    )
    assert not await outbox_handlers._accepted_attempt_projection_complete_for_node(
        session=db_session,
        workspace_id="workspace-1",
        node=node,
        attempt=attempt,
    )

    runner_result["stdout"] = "status=dirty\ndirty_signature=sig-current\n M scratch.js\n"
    changed_signature_node = replace(
        node,
        metadata={
            **dict(node.metadata),
            "worktree_integration_dirty_signature": "sig-old",
        },
    )
    assert not await outbox_handlers._accepted_attempt_projection_complete_for_node(
        session=db_session,
        workspace_id="workspace-1",
        node=changed_signature_node,
        attempt=attempt,
    )

    runner_result["stdout"] = "status=clean\n"
    assert not await outbox_handlers._accepted_attempt_projection_complete_for_node(
        session=db_session,
        workspace_id="workspace-1",
        node=node,
        attempt=attempt,
    )


@pytest.mark.asyncio
async def test_prepare_attempt_worktree_defaults_to_attempt_scope_without_checkpoint(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_workspace_and_plan(db_session)
    workspace = (
        await db_session.execute(select(WorkspaceModel).where(WorkspaceModel.id == "workspace-1"))
    ).scalar_one()
    workspace.metadata_json = {"code_context": {"sandbox_code_root": "/workspace/my-evo"}}
    await db_session.flush()

    commands: list[str] = []

    class FakeRunner:
        def __init__(self, *, project_id: str, tenant_id: str) -> None:
            assert project_id == "worker-project-1"
            assert tenant_id == "worker-tenant-1"

        async def run_command(self, command: str, *, timeout: int) -> dict[str, object]:
            assert timeout == 120
            commands.append(command)
            return {"exit_code": 0, "stdout": "git_head=abc123\n", "stderr": ""}

    monkeypatch.setattr(outbox_handlers, "_WorkspaceSandboxCommandRunner", FakeRunner)
    task = WorkspaceTask(
        id="task-no-feature",
        workspace_id="workspace-1",
        title="Repair without checkpoint",
        description="Retry task created outside the plan node checkpoint path.",
        created_by="worker-user-1",
        status="in_progress",
        metadata={
            AUTONOMY_SCHEMA_VERSION_KEY: 1,
            ROOT_GOAL_TASK_ID: "root-task-1",
        },
    )

    note = await _prepare_attempt_worktree_if_available(
        db_session,
        "workspace-1",
        task,
        None,
        "attempt-direct-1",
    )

    assert note is not None
    assert "status=prepared" in note
    assert "worktree_path=/workspace/.memstack/worktrees/attempt-direct-1" in note
    assert "branch_name=workspace/task-no-feature-attempt-dire" in note
    assert commands
    assert "C=/workspace/my-evo" in commands[0]
    assert "W=/workspace/.memstack/worktrees/attempt-direct-1" in commands[0]
    assert "B=workspace/task-no-feature-attempt-dire" in commands[0]
    assert 'git worktree add -B "$B" "$W" "$R"' in commands[0]


def test_apply_attempt_worktree_checkpoint_refreshes_retry_attempt_scope() -> None:
    node = PlanNode(
        id="node-1",
        plan_id="plan-1",
        kind=PlanNodeKind.TASK,
        parent_id=PlanNodeId("goal-1"),
        title="retryable task",
        feature_checkpoint=FeatureCheckpoint(
            feature_id="feature-1",
            worktree_path="${sandbox_code_root}/../.memstack/worktrees/old-attempt",
            branch_name="workspace/node-1-old-attempt",
            base_ref="HEAD",
        ),
    )

    _apply_attempt_worktree_checkpoint(node, "new-attempt")

    assert node.feature_checkpoint is not None
    assert node.feature_checkpoint.worktree_path == (
        "${sandbox_code_root}/../.memstack/worktrees/new-attempt"
    )
    assert node.feature_checkpoint.branch_name == "workspace/node-1-new-attempt"
    assert node.feature_checkpoint.base_ref == "HEAD"


def test_apply_attempt_worktree_checkpoint_uses_previous_commit_as_retry_base() -> None:
    node = PlanNode(
        id="node-1",
        plan_id="plan-1",
        kind=PlanNodeKind.TASK,
        parent_id=PlanNodeId("goal-1"),
        title="retryable task",
        feature_checkpoint=FeatureCheckpoint(
            feature_id="feature-1",
            worktree_path="${sandbox_code_root}/../.memstack/worktrees/old-attempt",
            branch_name="workspace/node-1-old-attempt",
            commit_ref="1469ac15",
            base_ref="HEAD",
        ),
    )

    _apply_attempt_worktree_checkpoint(node, "new-attempt")

    assert node.feature_checkpoint is not None
    assert node.feature_checkpoint.base_ref == "1469ac15"


def test_apply_attempt_worktree_checkpoint_prefers_published_pipeline_ref() -> None:
    node = PlanNode(
        id="node-1",
        plan_id="plan-1",
        kind=PlanNodeKind.TASK,
        parent_id=PlanNodeId("goal-1"),
        title="retryable task",
        metadata={
            "source_publish_commit_ref": "a068cb8",
            "source_publish_source_commit_ref": "705b16a",
        },
        feature_checkpoint=FeatureCheckpoint(
            feature_id="feature-1",
            worktree_path="${sandbox_code_root}/../.memstack/worktrees/old-attempt",
            branch_name="workspace/node-1-old-attempt",
            commit_ref="9a779c1",
            base_ref="HEAD",
        ),
    )

    _apply_attempt_worktree_checkpoint(node, "new-attempt")

    assert node.feature_checkpoint is not None
    assert node.feature_checkpoint.base_ref == "a068cb8"


def test_apply_attempt_worktree_checkpoint_uses_failed_pipeline_source_without_publish_ref() -> None:
    node = PlanNode(
        id="node-1",
        plan_id="plan-1",
        kind=PlanNodeKind.TASK,
        parent_id=PlanNodeId("goal-1"),
        title="retryable task",
        metadata={"source_publish_source_commit_ref": "98bc211"},
        feature_checkpoint=FeatureCheckpoint(
            feature_id="feature-1",
            worktree_path="${sandbox_code_root}/../.memstack/worktrees/old-attempt",
            branch_name="workspace/node-1-old-attempt",
            commit_ref="9a779c1",
            base_ref="HEAD",
        ),
    )

    _apply_attempt_worktree_checkpoint(node, "new-attempt")

    assert node.feature_checkpoint is not None
    assert node.feature_checkpoint.base_ref == "98bc211"


def test_node_allowed_sandbox_commands_collects_checkpoint_and_preflight_commands() -> None:
    node = PlanNode(
        id="node-1",
        plan_id="plan-1",
        parent_id=PlanNodeId("goal-1"),
        title="Ship checkout flow",
        metadata={
            "verification_commands": ["uv run pytest src/tests/unit/example.py"],
            "preflight_checks": [
                {"check_id": "git-status", "command": "git status --short"},
                {"check_id": "read-progress"},
            ],
        },
        feature_checkpoint=FeatureCheckpoint(
            feature_id="feature-1",
            sequence=1,
            title="Checkout flow",
            init_command="make init",
            test_commands=("uv run pytest src/tests/unit/example.py", "npm test -- checkout"),
        ),
    )

    assert _node_allowed_sandbox_commands(node) == {
        "git status --short",
        "make init",
        "npm test -- checkout",
        "uv run pytest src/tests/unit/example.py",
    }


def test_persisted_attempt_leader_agent_id_skips_system_actor_marker() -> None:
    assert _persisted_attempt_leader_agent_id(WORKSPACE_PLAN_SYSTEM_ACTOR_ID) is None
    assert _persisted_attempt_leader_agent_id(BUILTIN_SISYPHUS_ID) == BUILTIN_SISYPHUS_ID
    assert _persisted_attempt_leader_agent_id(None) is None


@pytest.mark.asyncio
async def test_run_once_completes_registered_handler(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_and_plan(db_session)
    repo = SqlWorkspacePlanOutboxRepository(db_session)
    item = await repo.enqueue(
        plan_id="worker-plan-1",
        workspace_id="workspace-1",
        event_type="supervisor_tick",
        payload={"workspace_id": "workspace-1"},
    )
    handled: list[str] = []

    async def handler(outbox_item: WorkspacePlanOutboxModel, session: AsyncSession) -> None:
        handled.append(outbox_item.id)
        assert session is db_session
        assert outbox_item.payload_json == {"workspace_id": "workspace-1"}

    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={"supervisor_tick": handler},
        worker_id="worker-a",
    )

    assert await worker.run_once() == 1

    loaded = await repo.get_by_id(item.id)
    assert handled == [item.id]
    assert loaded is not None
    assert loaded.status == "completed"
    assert loaded.attempt_count == 1
    assert loaded.lease_owner is None
    assert loaded.processed_at is not None


@pytest.mark.asyncio
async def test_run_once_renews_processing_lease_during_long_handler(test_engine) -> None:
    session_maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as seed_session:
        await _seed_workspace_and_plan(seed_session)
        repo = SqlWorkspacePlanOutboxRepository(seed_session)
        item = await repo.enqueue(
            plan_id="worker-plan-1",
            workspace_id="workspace-1",
            event_type="supervisor_tick",
            payload={"workspace_id": "workspace-1"},
        )
        await seed_session.commit()

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        async with session_maker() as session:
            try:
                yield session
            except BaseException:
                await session.rollback()
                raise

    handler_can_finish = asyncio.Event()
    handler_started = asyncio.Event()

    async def long_handler(
        _outbox_item: WorkspacePlanOutboxModel,
        _session: AsyncSession,
    ) -> None:
        handler_started.set()
        await handler_can_finish.wait()

    worker = WorkspacePlanOutboxWorker(
        session_factory=factory,
        handlers={"supervisor_tick": long_handler},
        worker_id="worker-a",
        lease_seconds=2,
    )

    run_task = asyncio.create_task(worker.run_once())
    try:
        await asyncio.wait_for(handler_started.wait(), timeout=2)
        async with session_maker() as inspect_session:
            inspect_repo = SqlWorkspacePlanOutboxRepository(inspect_session)
            initial = await inspect_repo.get_by_id(item.id)
            assert initial is not None
            initial_lease_expires_at = initial.lease_expires_at

        await asyncio.sleep(1.2)

        async with session_maker() as inspect_session:
            inspect_repo = SqlWorkspacePlanOutboxRepository(inspect_session)
            renewed = await inspect_repo.get_by_id(item.id)
            assert renewed is not None
            assert renewed.status == "processing"
            assert renewed.lease_owner == "worker-a"
            assert renewed.attempt_count == 1
            assert renewed.lease_expires_at is not None
            assert initial_lease_expires_at is not None
            assert renewed.lease_expires_at > initial_lease_expires_at
    finally:
        handler_can_finish.set()
        assert await run_task == 1

    async with session_maker() as inspect_session:
        inspect_repo = SqlWorkspacePlanOutboxRepository(inspect_session)
        completed = await inspect_repo.get_by_id(item.id)
        assert completed is not None
        assert completed.status == "completed"
        assert completed.attempt_count == 1
        assert completed.lease_owner is None


@pytest.mark.asyncio
async def test_run_once_publishes_plan_update_after_handler_completion(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_and_plan(db_session)
    repo = SqlWorkspacePlanOutboxRepository(db_session)
    item = await repo.enqueue(
        plan_id="worker-plan-1",
        workspace_id="workspace-1",
        event_type="supervisor_tick",
        payload={"workspace_id": "workspace-1", "node_id": "node-1"},
    )
    published: list[dict[str, object]] = []

    async def handler(_outbox_item: WorkspacePlanOutboxModel, _session: AsyncSession) -> None:
        return None

    async def event_publisher(payload: dict[str, object]) -> None:
        published.append(payload)

    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={"supervisor_tick": handler},
        worker_id="worker-a",
        event_publisher=event_publisher,
    )

    assert await worker.run_once() == 1

    assert published == [
        {
            "workspace_id": "workspace-1",
            "plan_id": "worker-plan-1",
            "outbox_id": item.id,
            "outbox_event_type": "supervisor_tick",
            "outbox_status": "completed",
            "attempt_count": 1,
            "max_attempts": 5,
            "change": "outbox_completed",
            "node_id": "node-1",
        }
    ]


@pytest.mark.asyncio
async def test_run_once_marks_missing_handler_failed(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_and_plan(db_session)
    repo = SqlWorkspacePlanOutboxRepository(db_session)
    item = await repo.enqueue(
        plan_id="worker-plan-1",
        workspace_id="workspace-1",
        event_type="dispatch_node",
        max_attempts=2,
    )
    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={},
        worker_id="worker-a",
    )

    assert await worker.run_once() == 1

    loaded = await repo.get_by_id(item.id)
    assert loaded is not None
    assert loaded.status == "failed"
    assert loaded.attempt_count == 1
    assert loaded.lease_owner is None
    assert loaded.next_attempt_at is not None
    assert loaded.last_error == "no handler for event_type=dispatch_node"


@pytest.mark.asyncio
async def test_run_once_dead_letters_handler_exception_after_last_attempt(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_and_plan(db_session)
    repo = SqlWorkspacePlanOutboxRepository(db_session)
    item = await repo.enqueue(
        plan_id="worker-plan-1",
        workspace_id="workspace-1",
        event_type="verify_node",
        max_attempts=1,
    )

    async def failing_handler(
        outbox_item: WorkspacePlanOutboxModel,
        session: AsyncSession,
    ) -> None:
        raise RuntimeError(f"boom: {outbox_item.id} {session is db_session}")

    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={"verify_node": failing_handler},
        worker_id="worker-a",
    )

    assert await worker.run_once() == 1

    loaded = await repo.get_by_id(item.id)
    assert loaded is not None
    assert loaded.status == "dead_letter"
    assert loaded.attempt_count == 1
    assert loaded.lease_owner is None
    assert loaded.next_attempt_at is None
    assert loaded.last_error == f"boom: {item.id} True"


@pytest.mark.asyncio
async def test_run_once_releases_claimed_item_when_cancelled(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_and_plan(db_session)
    repo = SqlWorkspacePlanOutboxRepository(db_session)
    item = await repo.enqueue(
        plan_id="worker-plan-1",
        workspace_id="workspace-1",
        event_type="worker_launch",
        max_attempts=2,
    )

    async def cancelled_handler(
        _outbox_item: WorkspacePlanOutboxModel,
        _session: AsyncSession,
    ) -> None:
        raise asyncio.CancelledError

    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={"worker_launch": cancelled_handler},
        worker_id="worker-a",
    )

    with pytest.raises(asyncio.CancelledError):
        await worker.run_once()

    loaded = await repo.get_by_id(item.id)
    assert loaded is not None
    assert loaded.status == "pending"
    assert loaded.attempt_count == 0
    assert loaded.lease_owner is None
    assert loaded.next_attempt_at is None
    assert loaded.last_error == "workspace plan outbox processing cancelled"


@pytest.mark.asyncio
async def test_poll_loop_continues_after_claimed_item_cancelled(
    tmp_path: Path,
) -> None:
    engine, session_maker = await _file_backed_outbox_session_maker(tmp_path)
    try:
        item_id = await _seed_worker_launch_outbox_item(session_maker)
        calls = 0

        @asynccontextmanager
        async def factory() -> AsyncIterator[AsyncSession]:
            async with session_maker() as session:
                try:
                    yield session
                except BaseException:
                    await session.rollback()
                    raise

        async def flaky_handler(
            _outbox_item: WorkspacePlanOutboxModel,
            _session: AsyncSession,
        ) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise asyncio.CancelledError

        async def wait_for_completed() -> None:
            deadline = asyncio.get_running_loop().time() + 2
            while asyncio.get_running_loop().time() < deadline:
                async with session_maker() as inspect_session:
                    inspect_repo = SqlWorkspacePlanOutboxRepository(inspect_session)
                    loaded = await inspect_repo.get_by_id(item_id)
                if loaded is not None and loaded.status == "completed":
                    return
                await asyncio.sleep(0.01)
            raise AssertionError("outbox item was not retried after cancellation")

        worker = WorkspacePlanOutboxWorker(
            session_factory=factory,
            handlers={"worker_launch": flaky_handler},
            worker_id="worker-a",
            poll_interval_seconds=0.01,
        )

        worker.start()
        try:
            await wait_for_completed()
        finally:
            await worker.stop()

        async with session_maker() as inspect_session:
            inspect_repo = SqlWorkspacePlanOutboxRepository(inspect_session)
            loaded = await inspect_repo.get_by_id(item_id)
        assert loaded is not None
        assert loaded.status == "completed"
        assert loaded.attempt_count == 1
        assert loaded.lease_owner is None
        assert calls == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_worker_launch_handler_defers_when_active_worker_capacity_reached(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_workspace_and_plan(db_session)
    db_session.add_all(
        [
            WorkspaceTaskModel(
                id="active-worker-task",
                workspace_id="workspace-1",
                title="Already running task",
                description="",
                created_by="worker-user-1",
                status="in_progress",
                priority=0,
                metadata_json={
                    AUTONOMY_SCHEMA_VERSION_KEY: 1,
                    TASK_ROLE: "execution_task",
                    ROOT_GOAL_TASK_ID: "root-task-1",
                },
            ),
            WorkspaceTaskSessionAttemptModel(
                id="active-worker-attempt",
                workspace_task_id="active-worker-task",
                root_goal_task_id="root-task-1",
                workspace_id="workspace-1",
                attempt_number=1,
                status="running",
                conversation_id="active-worker-conversation",
                worker_agent_id="worker-agent",
                leader_agent_id=BUILTIN_SISYPHUS_ID,
            ),
            WorkspaceTaskModel(
                id="queued-worker-task",
                workspace_id="workspace-1",
                title="Queued worker task",
                description="",
                created_by="worker-user-1",
                status="in_progress",
                priority=0,
                assignee_agent_id="worker-agent",
                metadata_json={
                    AUTONOMY_SCHEMA_VERSION_KEY: 1,
                    TASK_ROLE: "execution_task",
                    ROOT_GOAL_TASK_ID: "root-task-1",
                    CURRENT_ATTEMPT_ID: "queued-worker-attempt",
                },
            ),
            WorkspaceTaskSessionAttemptModel(
                id="queued-worker-attempt",
                workspace_task_id="queued-worker-task",
                root_goal_task_id="root-task-1",
                workspace_id="workspace-1",
                attempt_number=1,
                status="running",
                conversation_id=None,
                worker_agent_id="worker-agent",
                leader_agent_id=BUILTIN_SISYPHUS_ID,
            ),
        ]
    )
    repo = SqlWorkspacePlanOutboxRepository(db_session)
    item = await repo.enqueue(
        plan_id="worker-plan-1",
        workspace_id="workspace-1",
        event_type=WORKER_LAUNCH_EVENT,
        payload={
            "workspace_id": "workspace-1",
            "task_id": "queued-worker-task",
            "worker_agent_id": "worker-agent",
            "actor_user_id": "worker-user-1",
            "leader_agent_id": BUILTIN_SISYPHUS_ID,
            "attempt_id": "queued-worker-attempt",
        },
        metadata={"source": "test"},
        max_attempts=9,
    )
    await db_session.commit()

    monkeypatch.setenv("WORKSPACE_WORKER_LAUNCH_MAX_ACTIVE", "1")
    monkeypatch.setenv("WORKSPACE_WORKER_LAUNCH_DEFER_SECONDS", "30")
    launched: list[dict[str, object]] = []
    monkeypatch.setattr(
        "src.infrastructure.agent.workspace.worker_launch.schedule_worker_session",
        lambda **kwargs: launched.append(kwargs),
    )

    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={
            WORKER_LAUNCH_EVENT: make_worker_launch_handler(worktree_preparer=_noop_worktree)
        },
        worker_id="worker-a",
    )

    assert await worker.run_once() == 1
    assert not launched
    original = await repo.get_by_id(item.id)
    assert original is not None
    assert original.status == "completed"
    deferred_jobs = list(
        (
            await db_session.execute(
                select(WorkspacePlanOutboxModel)
                .where(WorkspacePlanOutboxModel.event_type == WORKER_LAUNCH_EVENT)
                .where(WorkspacePlanOutboxModel.id != item.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(deferred_jobs) == 1
    assert deferred_jobs[0].status == "pending"
    assert deferred_jobs[0].next_attempt_at is not None
    assert deferred_jobs[0].max_attempts == 9
    assert deferred_jobs[0].payload_json["attempt_id"] == "queued-worker-attempt"
    assert (
        deferred_jobs[0].metadata_json["source"] == "workspace_plan.worker_launch.deferred_capacity"
    )
    assert deferred_jobs[0].metadata_json["active_worker_conversations"] == 1
    assert deferred_jobs[0].metadata_json["max_active_worker_conversations"] == 1


@pytest.mark.asyncio
async def test_worker_launch_handler_skips_terminal_stale_attempt_before_capacity_defer(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_workspace_and_plan(db_session)
    db_session.add_all(
        [
            WorkspaceTaskModel(
                id="active-capacity-task",
                workspace_id="workspace-1",
                title="Already running task",
                description="",
                created_by="worker-user-1",
                status="in_progress",
                priority=0,
                metadata_json={
                    AUTONOMY_SCHEMA_VERSION_KEY: 1,
                    TASK_ROLE: "execution_task",
                    ROOT_GOAL_TASK_ID: "root-task-1",
                },
            ),
            WorkspaceTaskSessionAttemptModel(
                id="active-capacity-attempt",
                workspace_task_id="active-capacity-task",
                root_goal_task_id="root-task-1",
                workspace_id="workspace-1",
                attempt_number=1,
                status="running",
                conversation_id="active-capacity-conversation",
                worker_agent_id="worker-agent",
                leader_agent_id=BUILTIN_SISYPHUS_ID,
            ),
            WorkspaceTaskModel(
                id="retry-task",
                workspace_id="workspace-1",
                title="Retry task",
                description="",
                created_by="worker-user-1",
                status="in_progress",
                priority=0,
                assignee_agent_id="worker-agent",
                metadata_json={
                    AUTONOMY_SCHEMA_VERSION_KEY: 1,
                    TASK_ROLE: "execution_task",
                    ROOT_GOAL_TASK_ID: "root-task-1",
                    CURRENT_ATTEMPT_ID: "retry-attempt-new",
                },
            ),
            WorkspaceTaskSessionAttemptModel(
                id="retry-attempt-old",
                workspace_task_id="retry-task",
                root_goal_task_id="root-task-1",
                workspace_id="workspace-1",
                attempt_number=1,
                status="blocked",
                conversation_id=None,
                worker_agent_id="worker-agent",
                leader_agent_id=BUILTIN_SISYPHUS_ID,
            ),
            WorkspaceTaskSessionAttemptModel(
                id="retry-attempt-new",
                workspace_task_id="retry-task",
                root_goal_task_id="root-task-1",
                workspace_id="workspace-1",
                attempt_number=2,
                status="running",
                conversation_id=None,
                worker_agent_id="worker-agent",
                leader_agent_id=BUILTIN_SISYPHUS_ID,
            ),
        ]
    )
    repo = SqlWorkspacePlanOutboxRepository(db_session)
    item = await repo.enqueue(
        plan_id="worker-plan-1",
        workspace_id="workspace-1",
        event_type=WORKER_LAUNCH_EVENT,
        payload={
            "workspace_id": "workspace-1",
            "task_id": "retry-task",
            "worker_agent_id": "worker-agent",
            "actor_user_id": "worker-user-1",
            "leader_agent_id": BUILTIN_SISYPHUS_ID,
            "attempt_id": "retry-attempt-old",
        },
        metadata={"source": "test"},
    )
    await db_session.commit()

    monkeypatch.setenv("WORKSPACE_WORKER_LAUNCH_MAX_ACTIVE", "1")
    launched: list[dict[str, object]] = []
    monkeypatch.setattr(
        "src.infrastructure.agent.workspace.worker_launch.schedule_worker_session",
        lambda **kwargs: launched.append(kwargs),
    )
    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={
            WORKER_LAUNCH_EVENT: make_worker_launch_handler(worktree_preparer=_noop_worktree)
        },
        worker_id="worker-a",
    )

    assert await worker.run_once() == 1

    assert not launched
    original = await repo.get_by_id(item.id)
    assert original is not None
    assert original.status == "completed"
    launch_jobs = list(
        (
            await db_session.execute(
                select(WorkspacePlanOutboxModel).where(
                    WorkspacePlanOutboxModel.event_type == WORKER_LAUNCH_EVENT
                )
            )
        )
        .scalars()
        .all()
    )
    assert [job.id for job in launch_jobs] == [item.id]


@pytest.mark.asyncio
async def test_worker_launch_handler_skips_attempt_when_task_current_attempt_changed(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_workspace_and_plan(db_session)
    db_session.add_all(
        [
            WorkspaceTaskModel(
                id="stale-running-task",
                workspace_id="workspace-1",
                title="Stale running launch",
                description="",
                created_by="worker-user-1",
                status="in_progress",
                priority=0,
                assignee_agent_id="worker-agent",
                metadata_json={
                    AUTONOMY_SCHEMA_VERSION_KEY: 1,
                    TASK_ROLE: "execution_task",
                    ROOT_GOAL_TASK_ID: "root-task-1",
                    CURRENT_ATTEMPT_ID: "current-running-attempt",
                },
            ),
            WorkspaceTaskSessionAttemptModel(
                id="stale-running-attempt",
                workspace_task_id="stale-running-task",
                root_goal_task_id="root-task-1",
                workspace_id="workspace-1",
                attempt_number=1,
                status="running",
                conversation_id=None,
                worker_agent_id="worker-agent",
                leader_agent_id=BUILTIN_SISYPHUS_ID,
            ),
            WorkspaceTaskSessionAttemptModel(
                id="current-running-attempt",
                workspace_task_id="stale-running-task",
                root_goal_task_id="root-task-1",
                workspace_id="workspace-1",
                attempt_number=2,
                status="running",
                conversation_id=None,
                worker_agent_id="worker-agent",
                leader_agent_id=BUILTIN_SISYPHUS_ID,
            ),
        ]
    )
    await SqlWorkspacePlanOutboxRepository(db_session).enqueue(
        plan_id="worker-plan-1",
        workspace_id="workspace-1",
        event_type=WORKER_LAUNCH_EVENT,
        payload={
            "workspace_id": "workspace-1",
            "task_id": "stale-running-task",
            "worker_agent_id": "worker-agent",
            "actor_user_id": "worker-user-1",
            "leader_agent_id": BUILTIN_SISYPHUS_ID,
            "attempt_id": "stale-running-attempt",
        },
        metadata={"source": "test"},
    )
    await db_session.commit()

    launched: list[dict[str, object]] = []
    monkeypatch.setattr(
        "src.infrastructure.agent.workspace.worker_launch.schedule_worker_session",
        lambda **kwargs: launched.append(kwargs),
    )
    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={
            WORKER_LAUNCH_EVENT: make_worker_launch_handler(worktree_preparer=_noop_worktree)
        },
        worker_id="worker-a",
    )

    assert await worker.run_once() == 1

    assert not launched


@pytest.mark.asyncio
async def test_run_once_returns_zero_when_no_due_items(
    db_session: AsyncSession,
) -> None:
    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={},
        worker_id="worker-a",
    )

    assert await worker.run_once() == 0


@pytest.mark.asyncio
async def test_supervisor_tick_handler_advances_sql_plan_from_outbox(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_only(db_session)
    orchestrator = build_sql_orchestrator(
        db_session,
        config=OrchestratorConfig(heartbeat_seconds=3600),
    )
    plan = await orchestrator.start_goal(
        workspace_id="workspace-1",
        title="Ship a durable plan",
        start_supervisor=False,
    )
    repo = SqlWorkspacePlanOutboxRepository(db_session)
    await repo.enqueue(
        plan_id=plan.id,
        workspace_id="workspace-1",
        event_type=SUPERVISOR_TICK_EVENT,
        payload={"workspace_id": "workspace-1"},
    )
    await db_session.commit()

    dispatched: list[tuple[str, str]] = []

    async def agent_pool(_workspace_id: str) -> list[WorkspaceAgent]:
        return [WorkspaceAgent(agent_id="agent-1", display_name="Agent One")]

    async def dispatcher(
        _workspace_id: str,
        allocation: Allocation,
        node: PlanNode,
    ) -> str:
        dispatched.append((allocation.agent_id, node.id))
        return f"attempt-{node.id}"

    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={
            SUPERVISOR_TICK_EVENT: make_supervisor_tick_handler(
                config=OrchestratorConfig(heartbeat_seconds=3600),
                agent_pool=agent_pool,
                dispatcher=dispatcher,
            )
        },
        worker_id="worker-a",
    )

    assert await worker.run_once() == 1
    loaded = await SqlPlanRepository(db_session).get(plan.id)
    assert loaded is not None
    leaf = loaded.leaf_tasks()[0]
    assert dispatched == [("agent-1", leaf.id)]
    assert leaf.intent is TaskIntent.IN_PROGRESS
    assert leaf.execution is TaskExecution.DISPATCHED
    assert leaf.assignee_agent_id == "agent-1"
    assert leaf.current_attempt_id == f"attempt-{leaf.id}"


@pytest.mark.asyncio
async def test_supervisor_tick_releases_node_when_current_attempt_is_missing(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_only(db_session)
    orchestrator = build_sql_orchestrator(
        db_session,
        config=OrchestratorConfig(heartbeat_seconds=3600),
    )
    plan = await orchestrator.start_goal(
        workspace_id="workspace-1",
        title="Ship a durable plan",
        start_supervisor=False,
    )
    leaf = plan.leaf_tasks()[0]
    plan.replace_node(
        replace(
            leaf,
            intent=TaskIntent.IN_PROGRESS,
            execution=TaskExecution.RUNNING,
            current_attempt_id="missing-attempt",
        )
    )
    await SqlPlanRepository(db_session).save(plan)
    await SqlWorkspacePlanOutboxRepository(db_session).enqueue(
        plan_id=plan.id,
        workspace_id="workspace-1",
        event_type=SUPERVISOR_TICK_EVENT,
        payload={"workspace_id": "workspace-1"},
    )
    await db_session.commit()

    dispatched: list[str] = []

    async def agent_pool(_workspace_id: str) -> list[WorkspaceAgent]:
        return [WorkspaceAgent(agent_id="agent-1", display_name="Agent One")]

    async def dispatcher(
        _workspace_id: str,
        _allocation: Allocation,
        node: PlanNode,
    ) -> str:
        dispatched.append(node.id)
        return f"retry-{node.id}"

    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={
            SUPERVISOR_TICK_EVENT: make_supervisor_tick_handler(
                config=OrchestratorConfig(heartbeat_seconds=3600),
                agent_pool=agent_pool,
                dispatcher=dispatcher,
            )
        },
        worker_id="worker-a",
    )

    assert await worker.run_once() == 1
    loaded = await SqlPlanRepository(db_session).get(plan.id)
    assert loaded is not None
    retried_leaf = loaded.leaf_tasks()[0]
    assert dispatched == [leaf.id]
    assert retried_leaf.intent is TaskIntent.IN_PROGRESS
    assert retried_leaf.execution is TaskExecution.DISPATCHED
    assert retried_leaf.current_attempt_id == f"retry-{leaf.id}"
    assert retried_leaf.metadata["terminal_attempt_retry_reason"] == "missing_attempt"
    assert retried_leaf.metadata["terminal_attempt_retry_count"] == 1


@pytest.mark.asyncio
async def test_supervisor_tick_reconciles_reported_attempt_before_verification(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_only(db_session)
    orchestrator = build_sql_orchestrator(
        db_session,
        config=OrchestratorConfig(heartbeat_seconds=3600),
    )
    plan = await orchestrator.start_goal(
        workspace_id="workspace-1",
        title="Ship a durable plan",
        start_supervisor=False,
    )
    leaf = plan.leaf_tasks()[0]
    db_session.add(
        WorkspaceTaskModel(
            id="reported-node-task",
            workspace_id="workspace-1",
            title="Reported projection",
            description="",
            created_by="worker-user-1",
            status="in_progress",
            priority=0,
            assignee_agent_id="worker-agent",
            metadata_json={
                AUTONOMY_SCHEMA_VERSION_KEY: 1,
                TASK_ROLE: "execution_task",
                ROOT_GOAL_TASK_ID: "root-task-1",
                WORKSPACE_PLAN_ID: plan.id,
                WORKSPACE_PLAN_NODE_ID: leaf.id,
                CURRENT_ATTEMPT_ID: "reported-attempt",
                LAST_WORKER_REPORT_ATTEMPT_ID: "reported-attempt",
                LAST_WORKER_REPORT_SUMMARY: "worker completed with evidence",
                "last_worker_report_type": "completed",
                "last_attempt_status": "awaiting_leader_adjudication",
            },
        )
    )
    db_session.add(
        WorkspaceTaskSessionAttemptModel(
            id="reported-attempt",
            workspace_task_id="reported-node-task",
            root_goal_task_id="root-task-1",
            workspace_id="workspace-1",
            attempt_number=1,
            status="awaiting_leader_adjudication",
            conversation_id="reported-conversation",
            worker_agent_id="worker-agent",
            leader_agent_id=BUILTIN_SISYPHUS_ID,
            candidate_summary="worker completed with evidence",
            candidate_verifications_json=[
                "preflight:read-progress",
                "preflight:git-status",
                "test_run:pytest focused",
            ],
        )
    )
    plan.replace_node(
        replace(
            leaf,
            intent=TaskIntent.IN_PROGRESS,
            execution=TaskExecution.DISPATCHED,
            current_attempt_id="reported-attempt",
            workspace_task_id="reported-node-task",
            acceptance_criteria=(
                AcceptanceCriterion(
                    kind=CriterionKind.CUSTOM,
                    spec={
                        "name": "terminal_worker_report_present",
                        "requires_terminal_worker_report": True,
                    },
                    required=False,
                ),
            ),
        )
    )
    await SqlPlanRepository(db_session).save(plan)
    await SqlWorkspacePlanOutboxRepository(db_session).enqueue(
        plan_id=plan.id,
        workspace_id="workspace-1",
        event_type=SUPERVISOR_TICK_EVENT,
        payload={"workspace_id": "workspace-1"},
    )
    await db_session.commit()

    async def agent_pool(_workspace_id: str) -> list[WorkspaceAgent]:
        return []

    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={
            SUPERVISOR_TICK_EVENT: make_supervisor_tick_handler(
                config=OrchestratorConfig(heartbeat_seconds=3600),
                agent_pool=agent_pool,
            )
        },
        worker_id="worker-a",
    )

    assert await worker.run_once() == 1
    loaded = await SqlPlanRepository(db_session).get(plan.id)
    assert loaded is not None
    reconciled_leaf = loaded.leaf_tasks()[0]
    assert reconciled_leaf.intent is TaskIntent.DONE
    assert reconciled_leaf.execution is TaskExecution.IDLE
    assert reconciled_leaf.metadata["reported_attempt_status"] == "awaiting_leader_adjudication"
    assert reconciled_leaf.metadata["last_verification_attempt_id"] == "reported-attempt"
    attempt = await db_session.get(WorkspaceTaskSessionAttemptModel, "reported-attempt")
    assert attempt is not None
    assert attempt.status == "accepted"
    task = await db_session.get(WorkspaceTaskModel, "reported-node-task")
    assert task is not None
    assert task.status == "done"
    events = (
        (
            await db_session.execute(
                select(WorkspacePlanEventModel.event_type).where(
                    WorkspacePlanEventModel.plan_id == plan.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert "auto_reported_attempt_reconciled" in events
    assert "verification_completed" in events


@pytest.mark.asyncio
async def test_supervisor_tick_releases_in_progress_idle_node_with_rejected_attempt(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_only(db_session)
    orchestrator = build_sql_orchestrator(
        db_session,
        config=OrchestratorConfig(heartbeat_seconds=3600),
    )
    plan = await orchestrator.start_goal(
        workspace_id="workspace-1",
        title="Ship a durable plan",
        start_supervisor=False,
    )
    leaf = plan.leaf_tasks()[0]
    db_session.add(
        WorkspaceTaskSessionAttemptModel(
            id="rejected-terminal-attempt",
            workspace_task_id="workspace-task-rejected",
            root_goal_task_id="root-task-1",
            workspace_id="workspace-1",
            attempt_number=1,
            status="rejected",
            conversation_id="rejected-conversation",
            worker_agent_id="worker-agent",
            leader_agent_id=BUILTIN_SISYPHUS_ID,
            leader_feedback="provider transport failure",
        )
    )
    plan.replace_node(
        replace(
            leaf,
            intent=TaskIntent.IN_PROGRESS,
            execution=TaskExecution.IDLE,
            current_attempt_id="rejected-terminal-attempt",
            workspace_task_id="workspace-task-rejected",
        )
    )
    await SqlPlanRepository(db_session).save(plan)
    await SqlWorkspacePlanOutboxRepository(db_session).enqueue(
        plan_id=plan.id,
        workspace_id="workspace-1",
        event_type=SUPERVISOR_TICK_EVENT,
        payload={"workspace_id": "workspace-1"},
    )
    await db_session.commit()

    dispatched: list[str] = []

    async def agent_pool(_workspace_id: str) -> list[WorkspaceAgent]:
        return [WorkspaceAgent(agent_id="agent-1", display_name="Agent One")]

    async def dispatcher(
        _workspace_id: str,
        _allocation: Allocation,
        node: PlanNode,
    ) -> str:
        dispatched.append(node.id)
        return f"retry-{node.id}"

    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={
            SUPERVISOR_TICK_EVENT: make_supervisor_tick_handler(
                config=OrchestratorConfig(heartbeat_seconds=3600),
                agent_pool=agent_pool,
                dispatcher=dispatcher,
            )
        },
        worker_id="worker-a",
    )

    assert await worker.run_once() == 1
    loaded = await SqlPlanRepository(db_session).get(plan.id)
    assert loaded is not None
    retried_leaf = loaded.leaf_tasks()[0]
    assert dispatched == [leaf.id]
    assert retried_leaf.intent is TaskIntent.IN_PROGRESS
    assert retried_leaf.execution is TaskExecution.DISPATCHED
    assert retried_leaf.current_attempt_id == f"retry-{leaf.id}"
    assert retried_leaf.metadata["terminal_attempt_retry_reason"] == ("terminal_attempt_rejected")
    assert retried_leaf.metadata["terminal_attempt_retry_count"] == 1


@pytest.mark.asyncio
async def test_terminal_attempt_reconcile_preserves_reported_pipeline_result_for_verifier(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_only(db_session)
    orchestrator = build_sql_orchestrator(
        db_session,
        config=OrchestratorConfig(heartbeat_seconds=3600),
    )
    plan = await orchestrator.start_goal(
        workspace_id="workspace-1",
        title="Ship a durable plan",
        start_supervisor=False,
    )
    leaf = plan.leaf_tasks()[0]
    db_session.add(
        WorkspaceTaskSessionAttemptModel(
            id="reported-pipeline-failed-attempt",
            workspace_task_id="workspace-task-pipeline",
            root_goal_task_id="root-task-1",
            workspace_id="workspace-1",
            attempt_number=1,
            status="rejected",
            conversation_id="pipeline-failed-conversation",
            worker_agent_id="worker-agent",
            leader_agent_id=BUILTIN_SISYPHUS_ID,
            leader_feedback="Drone deploy failed",
        )
    )
    plan.replace_node(
        replace(
            leaf,
            intent=TaskIntent.IN_PROGRESS,
            execution=TaskExecution.REPORTED,
            current_attempt_id="reported-pipeline-failed-attempt",
            workspace_task_id="workspace-task-pipeline",
            metadata={
                **dict(leaf.metadata or {}),
                "pipeline_status": "failed",
                "pipeline_run_id": "drone-43",
                "external_id": "drone-43",
                "pipeline_failed_stage": "workspace-ci/deploy",
                "pipeline_last_summary": "Drone deploy failed",
            },
        )
    )
    await SqlPlanRepository(db_session).save(plan)
    await db_session.commit()

    changed = await outbox_handlers._reconcile_plan_nodes_with_terminal_attempts(
        session=db_session,
        plan_id=plan.id,
        workspace_id="workspace-1",
    )

    assert changed is False
    loaded = await SqlPlanRepository(db_session).get(plan.id)
    assert loaded is not None
    preserved_leaf = loaded.leaf_tasks()[0]
    assert preserved_leaf.execution is TaskExecution.REPORTED
    assert preserved_leaf.current_attempt_id == "reported-pipeline-failed-attempt"
    assert "terminal_attempt_retry_reason" not in preserved_leaf.metadata


@pytest.mark.asyncio
async def test_supervisor_tick_releases_done_node_with_rejected_attempt(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_only(db_session)
    orchestrator = build_sql_orchestrator(
        db_session,
        config=OrchestratorConfig(heartbeat_seconds=3600),
    )
    plan = await orchestrator.start_goal(
        workspace_id="workspace-1",
        title="Ship a durable plan",
        start_supervisor=False,
    )
    leaf = plan.leaf_tasks()[0]
    db_session.add(
        WorkspaceTaskSessionAttemptModel(
            id="done-rejected-terminal-attempt",
            workspace_task_id="workspace-task-rejected",
            root_goal_task_id="root-task-1",
            workspace_id="workspace-1",
            attempt_number=1,
            status="rejected",
            conversation_id="done-rejected-conversation",
            worker_agent_id="worker-agent",
            leader_agent_id=BUILTIN_SISYPHUS_ID,
            leader_feedback="judge verdict=needs_rework",
        )
    )
    plan.replace_node(
        replace(
            leaf,
            intent=TaskIntent.DONE,
            execution=TaskExecution.IDLE,
            current_attempt_id="done-rejected-terminal-attempt",
            workspace_task_id="workspace-task-rejected",
            metadata={
                **dict(leaf.metadata or {}),
                "pipeline_status": "success",
                "last_verification_passed": True,
            },
        )
    )
    await SqlPlanRepository(db_session).save(plan)
    await SqlWorkspacePlanOutboxRepository(db_session).enqueue(
        plan_id=plan.id,
        workspace_id="workspace-1",
        event_type=SUPERVISOR_TICK_EVENT,
        payload={"workspace_id": "workspace-1"},
    )
    await db_session.commit()

    dispatched: list[str] = []

    async def agent_pool(_workspace_id: str) -> list[WorkspaceAgent]:
        return [WorkspaceAgent(agent_id="agent-1", display_name="Agent One")]

    async def dispatcher(
        _workspace_id: str,
        _allocation: Allocation,
        node: PlanNode,
    ) -> str:
        dispatched.append(node.id)
        return f"retry-{node.id}"

    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={
            SUPERVISOR_TICK_EVENT: make_supervisor_tick_handler(
                config=OrchestratorConfig(heartbeat_seconds=3600),
                agent_pool=agent_pool,
                dispatcher=dispatcher,
            )
        },
        worker_id="worker-a",
    )

    assert await worker.run_once() == 1
    loaded = await SqlPlanRepository(db_session).get(plan.id)
    assert loaded is not None
    retried_leaf = loaded.leaf_tasks()[0]
    assert dispatched == [leaf.id]
    assert retried_leaf.intent is TaskIntent.IN_PROGRESS
    assert retried_leaf.execution is TaskExecution.DISPATCHED
    assert retried_leaf.current_attempt_id == f"retry-{leaf.id}"
    assert retried_leaf.metadata["terminal_attempt_retry_reason"] == ("terminal_attempt_rejected")
    assert retried_leaf.metadata["terminal_attempt_retry_count"] == 1


@pytest.mark.asyncio
async def test_supervisor_tick_persists_terminal_reconcile_before_later_dispatch_failure(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_only(db_session)
    orchestrator = build_sql_orchestrator(
        db_session,
        config=OrchestratorConfig(heartbeat_seconds=3600),
    )
    plan = await orchestrator.start_goal(
        workspace_id="workspace-1",
        title="Ship a durable plan",
        start_supervisor=False,
    )
    accepted_leaf = plan.leaf_tasks()[0]
    db_session.add(
        WorkspaceTaskModel(
            id="accepted-node-task",
            workspace_id="workspace-1",
            title="Accepted projection",
            description="",
            created_by="worker-user-1",
            status="blocked",
            priority=0,
            assignee_agent_id="worker-agent",
            blocker_reason="stale recovery blocker",
            metadata_json={
                AUTONOMY_SCHEMA_VERSION_KEY: 1,
                TASK_ROLE: "execution_task",
                ROOT_GOAL_TASK_ID: "root-task-1",
                WORKSPACE_PLAN_ID: plan.id,
                WORKSPACE_PLAN_NODE_ID: accepted_leaf.id,
            },
        )
    )
    db_session.add(
        WorkspaceTaskSessionAttemptModel(
            id="accepted-terminal-attempt",
            workspace_task_id="accepted-node-task",
            root_goal_task_id="root-task-1",
            workspace_id="workspace-1",
            attempt_number=1,
            status="accepted",
            conversation_id="accepted-conversation",
            worker_agent_id="worker-agent",
            leader_agent_id=BUILTIN_SISYPHUS_ID,
            leader_feedback="accepted by durable verifier",
            candidate_artifacts_json=["docs/final-report.md"],
            candidate_verifications_json=["test_run:pytest final"],
        )
    )
    plan.replace_node(
        replace(
            accepted_leaf,
            intent=TaskIntent.IN_PROGRESS,
            execution=TaskExecution.RUNNING,
            current_attempt_id="accepted-terminal-attempt",
            workspace_task_id="accepted-node-task",
        )
    )
    plan.add_node(
        PlanNode(
            id="next-node",
            plan_id=plan.id,
            parent_id=plan.goal_id,
            kind=PlanNodeKind.TASK,
            title="Next ready task",
            intent=TaskIntent.TODO,
            execution=TaskExecution.IDLE,
            recommended_capabilities=(Capability(name="codegen"),),
        )
    )
    await SqlPlanRepository(db_session).save(plan)
    await SqlWorkspacePlanOutboxRepository(db_session).enqueue(
        plan_id=plan.id,
        workspace_id="workspace-1",
        event_type=SUPERVISOR_TICK_EVENT,
        payload={"workspace_id": "workspace-1"},
        max_attempts=1,
    )
    await db_session.commit()

    async def agent_pool(_workspace_id: str) -> list[WorkspaceAgent]:
        return [WorkspaceAgent(agent_id="agent-1", display_name="Agent One")]

    async def dispatcher(
        _workspace_id: str,
        _allocation: Allocation,
        _node: PlanNode,
    ) -> str:
        raise PermissionError("User must be a workspace member")

    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={
            SUPERVISOR_TICK_EVENT: make_supervisor_tick_handler(
                config=OrchestratorConfig(heartbeat_seconds=3600),
                agent_pool=agent_pool,
                dispatcher=dispatcher,
            )
        },
        worker_id="worker-a",
    )

    assert await worker.run_once() == 1
    loaded = await SqlPlanRepository(db_session).get(plan.id)
    assert loaded is not None
    reconciled_leaf = loaded.nodes[accepted_leaf.node_id]
    assert reconciled_leaf.intent is TaskIntent.DONE
    assert reconciled_leaf.execution is TaskExecution.IDLE
    assert reconciled_leaf.metadata["terminal_attempt_status"] == "accepted"
    assert reconciled_leaf.metadata["last_verification_summary"] == ("accepted by durable verifier")
    assert reconciled_leaf.metadata["last_verification_attempt_id"] == ("accepted-terminal-attempt")
    assert reconciled_leaf.metadata["candidate_artifacts"] == ["docs/final-report.md"]
    assert reconciled_leaf.metadata["candidate_verifications"] == ["test_run:pytest final"]
    task = await db_session.get(WorkspaceTaskModel, "accepted-node-task")
    assert task is not None
    assert task.status == "done"
    assert task.blocker_reason is None
    assert task.completed_at is not None
    assert task.metadata_json["current_attempt_id"] == "accepted-terminal-attempt"
    assert task.metadata_json["last_attempt_status"] == "accepted"
    assert task.metadata_json["durable_plan_verdict"] == "accepted"
    assert task.metadata_json["last_worker_report_summary"] == "accepted by durable verifier"
    assert task.metadata_json["progress_events"][-1]["evidence_refs"] == [
        "artifact:docs/final-report.md",
        "test_run:pytest final",
    ]
    outbox = await SqlWorkspacePlanOutboxRepository(db_session).list_by_workspace(
        "workspace-1",
        limit=5,
    )
    assert outbox[0].status == "dead_letter"
    assert "User must be a workspace member" in str(outbox[0].last_error)


@pytest.mark.asyncio
async def test_supervisor_tick_uses_accepted_attempt_when_current_attempt_was_parent_done(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_only(db_session)
    orchestrator = build_sql_orchestrator(
        db_session,
        config=OrchestratorConfig(heartbeat_seconds=3600),
    )
    plan = await orchestrator.start_goal(
        workspace_id="workspace-1",
        title="Ship a durable plan",
        start_supervisor=False,
    )
    leaf = plan.leaf_tasks()[0]
    db_session.add(
        WorkspaceTaskModel(
            id="parent-done-task",
            workspace_id="workspace-1",
            title="Accepted projection",
            description="",
            created_by="worker-user-1",
            status="done",
            priority=0,
            assignee_agent_id="worker-agent",
            metadata_json={
                AUTONOMY_SCHEMA_VERSION_KEY: 1,
                TASK_ROLE: "execution_task",
                ROOT_GOAL_TASK_ID: "root-task-1",
                WORKSPACE_PLAN_ID: plan.id,
                WORKSPACE_PLAN_NODE_ID: leaf.id,
                CURRENT_ATTEMPT_ID: "accepted-before-parent-done",
            },
        )
    )
    db_session.add_all(
        [
            WorkspaceTaskSessionAttemptModel(
                id="accepted-before-parent-done",
                workspace_task_id="parent-done-task",
                root_goal_task_id="root-task-1",
                workspace_id="workspace-1",
                attempt_number=2,
                status="accepted",
                conversation_id="accepted-conversation",
                worker_agent_id="worker-agent",
                leader_agent_id=BUILTIN_SISYPHUS_ID,
                leader_feedback="accepted before recovery sweep",
                candidate_artifacts_json=["docs/GOAL-COMPLETION.md"],
                candidate_verifications_json=["test_run:pytest final"],
            ),
            WorkspaceTaskSessionAttemptModel(
                id="cancelled-after-parent-done",
                workspace_task_id="parent-done-task",
                root_goal_task_id="root-task-1",
                workspace_id="workspace-1",
                attempt_number=3,
                status="cancelled",
                conversation_id="cancelled-conversation",
                worker_agent_id="worker-agent",
                leader_agent_id=BUILTIN_SISYPHUS_ID,
                leader_feedback="recovery:parent_done",
                adjudication_reason="recovery:parent_done",
            ),
        ]
    )
    plan.replace_node(
        replace(
            leaf,
            intent=TaskIntent.IN_PROGRESS,
            execution=TaskExecution.RUNNING,
            current_attempt_id="cancelled-after-parent-done",
            workspace_task_id="parent-done-task",
        )
    )
    await SqlPlanRepository(db_session).save(plan)
    await SqlWorkspacePlanOutboxRepository(db_session).enqueue(
        plan_id=plan.id,
        workspace_id="workspace-1",
        event_type=SUPERVISOR_TICK_EVENT,
        payload={"workspace_id": "workspace-1"},
    )
    await db_session.commit()

    dispatched: list[str] = []

    async def agent_pool(_workspace_id: str) -> list[WorkspaceAgent]:
        return [WorkspaceAgent(agent_id="agent-1", display_name="Agent One")]

    async def dispatcher(
        _workspace_id: str,
        _allocation: Allocation,
        node: PlanNode,
    ) -> str:
        dispatched.append(node.id)
        return f"retry-{node.id}"

    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={
            SUPERVISOR_TICK_EVENT: make_supervisor_tick_handler(
                config=OrchestratorConfig(heartbeat_seconds=3600),
                agent_pool=agent_pool,
                dispatcher=dispatcher,
            )
        },
        worker_id="worker-a",
    )

    assert await worker.run_once() == 1
    loaded = await SqlPlanRepository(db_session).get(plan.id)
    assert loaded is not None
    reconciled_leaf = loaded.leaf_tasks()[0]
    assert dispatched == []
    assert reconciled_leaf.intent is TaskIntent.DONE
    assert reconciled_leaf.execution is TaskExecution.IDLE
    assert reconciled_leaf.current_attempt_id == "accepted-before-parent-done"
    assert reconciled_leaf.metadata["terminal_attempt_status"] == "accepted"
    assert reconciled_leaf.metadata["terminal_attempt_superseded_attempt_id"] == (
        "cancelled-after-parent-done"
    )
    assert reconciled_leaf.metadata["terminal_attempt_superseded_status"] == "cancelled"
    assert reconciled_leaf.metadata["last_verification_attempt_id"] == (
        "accepted-before-parent-done"
    )
    assert reconciled_leaf.metadata["candidate_artifacts"] == ["docs/GOAL-COMPLETION.md"]
    assert reconciled_leaf.metadata["candidate_verifications"] == ["test_run:pytest final"]
    task = await db_session.get(WorkspaceTaskModel, "parent-done-task")
    assert task is not None
    assert task.status == "done"
    assert task.metadata_json[CURRENT_ATTEMPT_ID] == "accepted-before-parent-done"
    assert task.metadata_json["last_attempt_status"] == "accepted"
    assert task.metadata_json["durable_plan_verdict"] == "accepted"


@pytest.mark.asyncio
async def test_supervisor_tick_rejects_stale_parent_done_accepted_attempt(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_only(db_session)
    orchestrator = build_sql_orchestrator(
        db_session,
        config=OrchestratorConfig(heartbeat_seconds=3600),
    )
    plan = await orchestrator.start_goal(
        workspace_id="workspace-1",
        title="Ship a durable plan",
        start_supervisor=False,
    )
    leaf = plan.leaf_tasks()[0]
    db_session.add(
        WorkspaceTaskModel(
            id="stale-parent-done-task",
            workspace_id="workspace-1",
            title="Accepted projection",
            description="",
            created_by="worker-user-1",
            status="in_progress",
            priority=0,
            assignee_agent_id="worker-agent",
            metadata_json={
                AUTONOMY_SCHEMA_VERSION_KEY: 1,
                TASK_ROLE: "execution_task",
                ROOT_GOAL_TASK_ID: "root-task-1",
                WORKSPACE_PLAN_ID: plan.id,
                WORKSPACE_PLAN_NODE_ID: leaf.id,
                CURRENT_ATTEMPT_ID: "cancelled-after-parent-done",
            },
        )
    )
    db_session.add_all(
        [
            WorkspaceTaskSessionAttemptModel(
                id="accepted-before-parent-done",
                workspace_task_id="stale-parent-done-task",
                root_goal_task_id="root-task-1",
                workspace_id="workspace-1",
                attempt_number=2,
                status="accepted",
                conversation_id="accepted-conversation",
                worker_agent_id="worker-agent",
                leader_agent_id=BUILTIN_SISYPHUS_ID,
                leader_feedback="accepted before recovery sweep",
                candidate_artifacts_json=["docs/OLD.md", "commit_ref:4171b352"],
                candidate_verifications_json=["test_run:pytest old", "commit_ref:4171b352"],
            ),
            WorkspaceTaskSessionAttemptModel(
                id="cancelled-after-parent-done",
                workspace_task_id="stale-parent-done-task",
                root_goal_task_id="root-task-1",
                workspace_id="workspace-1",
                attempt_number=3,
                status="cancelled",
                conversation_id="cancelled-conversation",
                worker_agent_id="worker-agent",
                leader_agent_id=BUILTIN_SISYPHUS_ID,
                leader_feedback="recovery:parent_done",
                adjudication_reason="recovery:parent_done",
            ),
        ]
    )
    plan.replace_node(
        replace(
            leaf,
            intent=TaskIntent.IN_PROGRESS,
            execution=TaskExecution.RUNNING,
            current_attempt_id="cancelled-after-parent-done",
            workspace_task_id="stale-parent-done-task",
            feature_checkpoint=FeatureCheckpoint(
                feature_id="feature-1",
                sequence=1,
                title="Review",
                base_ref="HEAD",
                commit_ref="8d65d60",
            ),
        )
    )
    await SqlPlanRepository(db_session).save(plan)
    await SqlWorkspacePlanOutboxRepository(db_session).enqueue(
        plan_id=plan.id,
        workspace_id="workspace-1",
        event_type=SUPERVISOR_TICK_EVENT,
        payload={"workspace_id": "workspace-1"},
    )
    await db_session.commit()

    dispatched: list[str] = []

    async def agent_pool(_workspace_id: str) -> list[WorkspaceAgent]:
        return [WorkspaceAgent(agent_id="agent-1", display_name="Agent One")]

    async def dispatcher(
        _workspace_id: str,
        _allocation: Allocation,
        node: PlanNode,
    ) -> str:
        dispatched.append(node.id)
        return f"retry-{node.id}"

    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={
            SUPERVISOR_TICK_EVENT: make_supervisor_tick_handler(
                config=OrchestratorConfig(heartbeat_seconds=3600),
                agent_pool=agent_pool,
                dispatcher=dispatcher,
            )
        },
        worker_id="worker-a",
    )

    assert await worker.run_once() == 1
    loaded = await SqlPlanRepository(db_session).get(plan.id)
    assert loaded is not None
    retried_leaf = loaded.leaf_tasks()[0]
    assert dispatched == [retried_leaf.id]
    assert retried_leaf.intent is TaskIntent.IN_PROGRESS
    assert retried_leaf.execution is TaskExecution.DISPATCHED
    assert retried_leaf.current_attempt_id == f"retry-{retried_leaf.id}"
    assert retried_leaf.metadata["terminal_attempt_retry_reason"] == "terminal_attempt_cancelled"
    assert "terminal_attempt_status" not in retried_leaf.metadata


@pytest.mark.asyncio
async def test_supervisor_tick_releases_blocked_node_with_terminal_attempt(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_only(db_session)
    orchestrator = build_sql_orchestrator(
        db_session,
        config=OrchestratorConfig(heartbeat_seconds=3600),
    )
    plan = await orchestrator.start_goal(
        workspace_id="workspace-1",
        title="Ship a durable plan",
        start_supervisor=False,
    )
    leaf = plan.leaf_tasks()[0]
    db_session.add(
        WorkspaceTaskModel(
            id="blocked-node-task",
            workspace_id="workspace-1",
            title="Blocked projection",
            description="",
            created_by="worker-user-1",
            status="blocked",
            priority=0,
            assignee_agent_id="worker-agent",
            metadata_json={
                AUTONOMY_SCHEMA_VERSION_KEY: 1,
                TASK_ROLE: "execution_task",
                ROOT_GOAL_TASK_ID: "root-task-1",
                WORKSPACE_PLAN_ID: plan.id,
                WORKSPACE_PLAN_NODE_ID: leaf.id,
            },
        )
    )
    db_session.add(
        WorkspaceTaskSessionAttemptModel(
            id="blocked-terminal-attempt",
            workspace_task_id="blocked-node-task",
            root_goal_task_id="root-task-1",
            workspace_id="workspace-1",
            attempt_number=1,
            status="blocked",
            conversation_id="blocked-conversation",
            worker_agent_id="worker-agent",
            leader_agent_id=BUILTIN_SISYPHUS_ID,
        )
    )
    plan.replace_node(
        replace(
            leaf,
            intent=TaskIntent.BLOCKED,
            execution=TaskExecution.IDLE,
            current_attempt_id="blocked-terminal-attempt",
            workspace_task_id="blocked-node-task",
        )
    )
    await SqlPlanRepository(db_session).save(plan)
    await SqlWorkspacePlanOutboxRepository(db_session).enqueue(
        plan_id=plan.id,
        workspace_id="workspace-1",
        event_type=SUPERVISOR_TICK_EVENT,
        payload={"workspace_id": "workspace-1"},
    )
    await db_session.commit()

    dispatched: list[str] = []

    async def agent_pool(_workspace_id: str) -> list[WorkspaceAgent]:
        return [WorkspaceAgent(agent_id="agent-1", display_name="Agent One")]

    async def dispatcher(
        _workspace_id: str,
        _allocation: Allocation,
        node: PlanNode,
    ) -> str:
        dispatched.append(node.id)
        return f"retry-{node.id}"

    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={
            SUPERVISOR_TICK_EVENT: make_supervisor_tick_handler(
                config=OrchestratorConfig(heartbeat_seconds=3600),
                agent_pool=agent_pool,
                dispatcher=dispatcher,
            )
        },
        worker_id="worker-a",
    )

    assert await worker.run_once() == 1
    loaded = await SqlPlanRepository(db_session).get(plan.id)
    assert loaded is not None
    retried_leaf = loaded.leaf_tasks()[0]
    assert dispatched == [leaf.id]
    assert retried_leaf.intent is TaskIntent.IN_PROGRESS
    assert retried_leaf.execution is TaskExecution.DISPATCHED
    assert retried_leaf.current_attempt_id == f"retry-{leaf.id}"
    assert retried_leaf.metadata["terminal_attempt_retry_reason"] == ("terminal_attempt_blocked")
    assert retried_leaf.metadata["terminal_attempt_retry_count"] == 1


@pytest.mark.asyncio
async def test_supervisor_tick_handler_leader_builds_team_when_only_leader_is_bound(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_only(db_session, include_worker=False)
    db_session.add(
        WorkspaceAgentModel(
            id="leader-binding-1",
            workspace_id="workspace-1",
            agent_id=BUILTIN_SISYPHUS_ID,
            display_name="Sisyphus",
            description=None,
            config_json={"workspace_role": "leader"},
            is_active=True,
        )
    )
    orchestrator = build_sql_orchestrator(
        db_session,
        config=OrchestratorConfig(heartbeat_seconds=3600),
    )
    plan = await orchestrator.start_goal(
        workspace_id="workspace-1",
        title="Ship a durable plan",
        start_supervisor=False,
    )
    await SqlWorkspacePlanOutboxRepository(db_session).enqueue(
        plan_id=plan.id,
        workspace_id="workspace-1",
        event_type=SUPERVISOR_TICK_EVENT,
        payload={
            "workspace_id": "workspace-1",
            "root_task_id": "root-task-1",
            "actor_user_id": "worker-user-1",
            "leader_agent_id": BUILTIN_SISYPHUS_ID,
        },
    )
    await db_session.commit()

    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={
            SUPERVISOR_TICK_EVENT: make_supervisor_tick_handler(
                config=OrchestratorConfig(heartbeat_seconds=3600),
            ),
        },
        worker_id="worker-a",
    )

    assert await worker.run_once() == 1

    bindings = list(
        (
            await db_session.execute(
                select(WorkspaceAgentModel)
                .where(WorkspaceAgentModel.workspace_id == "workspace-1")
                .order_by(WorkspaceAgentModel.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    execution_bindings = [
        binding
        for binding in bindings
        if binding.agent_id != BUILTIN_SISYPHUS_ID
        and binding.config_json["workspace_role"] == "execution_worker"
    ]
    assert len(execution_bindings) == 3
    assert {binding.label for binding in execution_bindings} == {
        "Architect",
        "Builder",
        "Verifier",
    }
    assert all(
        binding.config_json["auto_bound_by_leader"] is True for binding in execution_bindings
    )

    loaded = await SqlPlanRepository(db_session).get(plan.id)
    assert loaded is not None
    leaf = loaded.leaf_tasks()[0]
    assert leaf.intent is TaskIntent.IN_PROGRESS
    assert leaf.execution is TaskExecution.DISPATCHED
    assert leaf.assignee_agent_id in {binding.agent_id for binding in execution_bindings}
    assert leaf.assignee_agent_id != BUILTIN_SISYPHUS_ID
    assert leaf.workspace_task_id is not None

    launch_jobs = list(
        (
            await db_session.execute(
                select(WorkspacePlanOutboxModel).where(
                    WorkspacePlanOutboxModel.event_type == WORKER_LAUNCH_EVENT
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(launch_jobs) == 1
    assert launch_jobs[0].status == "pending"

    created_agents = list(
        (
            await db_session.execute(
                select(AgentDefinitionModel).where(
                    AgentDefinitionModel.name.like("workspace-workspace1-%")
                )
            )
        )
        .scalars()
        .all()
    )
    assert {agent.name for agent in created_agents} == {
        "workspace-workspace1-architect",
        "workspace-workspace1-builder",
        "workspace-workspace1-verifier",
    }


@pytest.mark.asyncio
async def test_supervisor_tick_handler_uses_system_actor_without_attempt_leader_fk(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_only(db_session)
    orchestrator = build_sql_orchestrator(
        db_session,
        config=OrchestratorConfig(heartbeat_seconds=3600),
    )
    plan = await orchestrator.start_goal(
        workspace_id="workspace-1",
        title="Ship a durable plan with system actor",
        start_supervisor=False,
    )
    repo = SqlWorkspacePlanOutboxRepository(db_session)
    item = await repo.enqueue(
        plan_id=plan.id,
        workspace_id="workspace-1",
        event_type=SUPERVISOR_TICK_EVENT,
        payload={
            "workspace_id": "workspace-1",
            "root_task_id": "root-task-1",
            "actor_user_id": "worker-user-1",
        },
    )
    await db_session.commit()

    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={
            SUPERVISOR_TICK_EVENT: make_supervisor_tick_handler(
                config=OrchestratorConfig(heartbeat_seconds=3600),
            ),
        },
        worker_id="worker-a",
    )

    assert await worker.run_once() == 1
    loaded_item = await repo.get_by_id(item.id)
    assert loaded_item is not None
    assert loaded_item.status == "completed", loaded_item.last_error

    loaded = await SqlPlanRepository(db_session).get(plan.id)
    assert loaded is not None
    leaf = loaded.leaf_tasks()[0]
    assert leaf.intent is TaskIntent.IN_PROGRESS
    assert leaf.execution is TaskExecution.DISPATCHED
    assert leaf.workspace_task_id is not None
    assert leaf.current_attempt_id is not None

    attempt = await db_session.get(WorkspaceTaskSessionAttemptModel, leaf.current_attempt_id)
    assert attempt is not None
    assert attempt.leader_agent_id is None

    task_row = await db_session.get(WorkspaceTaskModel, leaf.workspace_task_id)
    assert task_row is not None
    assert task_row.metadata_json[EXECUTION_STATE]["updated_by_actor_id"] == (
        WORKSPACE_PLAN_SYSTEM_ACTOR_ID
    )

    launch_jobs = list(
        (
            await db_session.execute(
                select(WorkspacePlanOutboxModel).where(
                    WorkspacePlanOutboxModel.event_type == WORKER_LAUNCH_EVENT
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(launch_jobs) == 1
    assert launch_jobs[0].payload_json["leader_agent_id"] == WORKSPACE_PLAN_SYSTEM_ACTOR_ID


@pytest.mark.asyncio
async def test_supervisor_tick_handler_launches_real_worker_and_verifies_report(  # noqa: PLR0915
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_workspace_only(db_session)
    orchestrator = build_sql_orchestrator(
        db_session,
        config=OrchestratorConfig(heartbeat_seconds=3600),
    )
    plan = await orchestrator.start_goal(
        workspace_id="workspace-1",
        title="Ship a durable plan",
        start_supervisor=False,
    )
    planned_leaf = plan.leaf_tasks()[0]
    assert planned_leaf.feature_checkpoint is not None
    plan.replace_node(
        replace(
            planned_leaf,
            feature_checkpoint=replace(
                planned_leaf.feature_checkpoint,
                expected_artifacts=("src/example.py",),
                test_commands=("uv run pytest src/tests/unit/example.py",),
            ),
            metadata={
                **planned_leaf.metadata,
                "write_set": ["src/example.py"],
                "verification_commands": ["uv run pytest src/tests/unit/example.py"],
            },
        )
    )
    await SqlPlanRepository(db_session).save(plan)
    await SqlWorkspacePlanOutboxRepository(db_session).enqueue(
        plan_id=plan.id,
        workspace_id="workspace-1",
        event_type=SUPERVISOR_TICK_EVENT,
        payload={
            "workspace_id": "workspace-1",
            "root_task_id": "root-task-1",
            "actor_user_id": "worker-user-1",
            "leader_agent_id": BUILTIN_SISYPHUS_ID,
        },
    )
    await db_session.commit()

    launched: list[dict[str, object]] = []

    def fake_schedule_worker_session(**kwargs: object) -> None:
        launched.append(kwargs)

    prepared_worktrees: list[tuple[str, str]] = []

    async def fake_worktree_preparer(
        _session: AsyncSession,
        workspace_id: str,
        task: WorkspaceTask,
        extra_instructions: str | None,
        attempt_id: str | None,
    ) -> str:
        assert extra_instructions is not None
        assert "[feature-checkpoint]" in extra_instructions
        assert attempt_id is not None
        prepared_worktrees.append((workspace_id, task.id))
        return "[worktree-setup]\nstatus=prepared\n[/worktree-setup]"

    monkeypatch.setattr(
        "src.infrastructure.agent.workspace.worker_launch.schedule_worker_session",
        fake_schedule_worker_session,
    )

    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={
            SUPERVISOR_TICK_EVENT: make_supervisor_tick_handler(
                config=OrchestratorConfig(heartbeat_seconds=3600),
            ),
            WORKER_LAUNCH_EVENT: make_worker_launch_handler(
                worktree_preparer=fake_worktree_preparer
            ),
        },
        worker_id="worker-a",
    )

    assert await worker.run_once() == 1
    outbox_after_dispatch = list(
        (
            await db_session.execute(
                select(WorkspacePlanOutboxModel).where(
                    WorkspacePlanOutboxModel.event_type == SUPERVISOR_TICK_EVENT
                )
            )
        )
        .scalars()
        .all()
    )
    assert outbox_after_dispatch[0].status == "completed", outbox_after_dispatch[0].last_error
    worker_launch_jobs = list(
        (
            await db_session.execute(
                select(WorkspacePlanOutboxModel).where(
                    WorkspacePlanOutboxModel.event_type == WORKER_LAUNCH_EVENT
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(worker_launch_jobs) == 1
    worker_launch_job_id = worker_launch_jobs[0].id
    assert worker_launch_jobs[0].status == "pending"
    assert not launched
    assert await worker.run_once() == 1
    db_session.expire_all()
    worker_launch_job = await db_session.get(WorkspacePlanOutboxModel, worker_launch_job_id)
    assert worker_launch_job is not None
    assert worker_launch_job.status == "completed", worker_launch_job.last_error
    assert launched
    db_session.expire_all()

    loaded = await SqlPlanRepository(db_session).get(plan.id)
    assert loaded is not None
    leaf = loaded.leaf_tasks()[0]
    assert leaf.intent is TaskIntent.IN_PROGRESS
    assert leaf.execution is TaskExecution.RUNNING
    assert leaf.assignee_agent_id == "worker-agent"
    assert leaf.workspace_task_id is not None
    assert leaf.current_attempt_id is not None
    assert leaf.updated_at is not None

    task = await SqlWorkspaceTaskRepository(db_session).find_by_id(leaf.workspace_task_id)
    assert task is not None
    assert task.assignee_agent_id == "worker-agent"
    assert task.status.value == "in_progress"
    assert prepared_worktrees == [("workspace-1", task.id)]
    root_task = await SqlWorkspaceTaskRepository(db_session).find_by_id("root-task-1")
    assert root_task is not None
    assert root_task.status.value == "in_progress"
    assert task.metadata[ROOT_GOAL_TASK_ID] == "root-task-1"
    assert task.metadata[WORKSPACE_PLAN_ID] == plan.id
    assert task.metadata[WORKSPACE_PLAN_NODE_ID] == leaf.id
    assert leaf.feature_checkpoint is not None
    assert task.metadata["harness_feature_id"] == leaf.feature_checkpoint.feature_id
    assert task.metadata["preflight_checks"][0]["check_id"] == "read-progress"
    assert task.metadata["feature_checkpoint"]["feature_id"] == leaf.feature_checkpoint.feature_id
    assert task.metadata["feature_checkpoint"]["worktree_path"] == (
        f"${{sandbox_code_root}}/../.memstack/worktrees/{leaf.current_attempt_id}"
    )
    assert task.metadata["feature_checkpoint"]["branch_name"].startswith(f"workspace/{leaf.id}-")
    assert task.metadata[CURRENT_ATTEMPT_ID] == leaf.current_attempt_id
    assert task.metadata["current_attempt_number"] == 1
    assert task.metadata["current_attempt_worker_agent_id"] == "worker-agent"
    assert task.metadata[CURRENT_ATTEMPT_WORKER_BINDING_ID] == "worker-binding-1"
    assert task.metadata["last_attempt_status"] == "running"
    assert task.metadata[EXECUTION_STATE]["phase"] == "in_progress"
    assert task.metadata[EXECUTION_STATE]["last_agent_reason"] == (
        "workspace_plan.dispatch.project_attempt"
    )
    assert task.metadata[EXECUTION_STATE]["last_agent_action"] == "start"
    assert launched and launched[0]["attempt_id"] == leaf.current_attempt_id
    assert "[feature-checkpoint]" in str(launched[0]["extra_instructions"])
    assert "[preflight-checks]" in str(launched[0]["extra_instructions"])
    assert leaf.feature_checkpoint.feature_id in str(launched[0]["extra_instructions"])
    assert "worktree_path=${sandbox_code_root}/../.memstack/worktrees/" in str(
        launched[0]["extra_instructions"]
    )
    assert "branch_name=workspace/" in str(launched[0]["extra_instructions"])
    assert "[worktree-setup]" in str(launched[0]["extra_instructions"])
    assert "status=prepared" in str(launched[0]["extra_instructions"])

    async def report_session_factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(
        "src.infrastructure.agent.workspace.workspace_goal_runtime.async_session_factory",
        asynccontextmanager(report_session_factory),
    )
    updated = await apply_workspace_worker_report(
        workspace_id="workspace-1",
        root_goal_task_id="root-task-1",
        task_id=task.id,
        attempt_id=leaf.current_attempt_id,
        actor_user_id="worker-user-1",
        worker_agent_id="worker-agent",
        leader_agent_id=BUILTIN_SISYPHUS_ID,
        report_type="completed",
        summary=(
            '{"summary":"Implemented the durable task and verified it.",'
            '"verifications":["preflight:read-progress","preflight:git-status"],'
            '"commit_ref":"abc123",'
            '"git_diff_summary":"1 file changed",'
            '"changed_files":["src/example.py"],'
            '"test_commands":["uv run pytest src/tests/unit/example.py"]}'
        ),
    )
    assert updated is not None
    assert updated.metadata["pending_leader_adjudication"] is False
    assert updated.metadata["last_attempt_status"] == "awaiting_plan_verification"

    assert await worker.run_once() == 1
    db_session.expire_all()
    verified = await SqlPlanRepository(db_session).get(plan.id)
    assert verified is not None
    verified_leaf = verified.leaf_tasks()[0]
    assert verified_leaf.intent is TaskIntent.DONE
    assert verified_leaf.execution is TaskExecution.IDLE
    assert verified_leaf.metadata["verified_commit_ref"] == "abc123"
    assert verified_leaf.metadata["verified_git_diff_summary"] == "1 file changed"
    assert verified_leaf.metadata["verified_test_commands"] == [
        "uv run pytest src/tests/unit/example.py"
    ]
    assert verified_leaf.feature_checkpoint is not None
    assert verified_leaf.feature_checkpoint.commit_ref == "abc123"
    events = list(
        (
            await db_session.execute(
                select(WorkspacePlanEventModel)
                .where(WorkspacePlanEventModel.plan_id == plan.id)
                .order_by(WorkspacePlanEventModel.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    assert [event.event_type for event in events] == [
        "worker_report_terminal",
        "verification_completed",
    ]
    assert events[0].actor_id == "worker-agent"
    assert events[1].payload_json["passed"] is True

    projected_task = await SqlWorkspaceTaskRepository(db_session).find_by_id(task.id)
    assert projected_task is not None
    assert projected_task.status.value == "done"
    assert projected_task.metadata["pending_leader_adjudication"] is False
    assert projected_task.metadata["durable_plan_verdict"] == "accepted"
    assert projected_task.metadata["last_worker_report_type"] == "completed"
    assert projected_task.metadata["last_attempt_status"] == "accepted"
    assert projected_task.metadata["last_attempt_id"] == leaf.current_attempt_id
    assert projected_task.metadata["last_leader_adjudication_status"] == "accepted"
    assert projected_task.metadata["feature_checkpoint"]["commit_ref"] == "abc123"
    assert projected_task.metadata["handoff_package"]["git_head"] == "abc123"
    assert projected_task.metadata["handoff_package"]["git_diff_summary"] == "1 file changed"
    assert projected_task.metadata["handoff_package"]["test_commands"] == [
        "uv run pytest src/tests/unit/example.py"
    ]
    assert projected_task.metadata["progress_events"][-1]["event_type"] == ("verification_accepted")
    assert "Commit: abc123" in projected_task.metadata["next_session_briefing"]
    reconciled_root = await SqlWorkspaceTaskRepository(db_session).find_by_id("root-task-1")
    assert reconciled_root is not None
    assert reconciled_root.metadata["goal_health"] == "achieved"
    assert reconciled_root.metadata["goal_progress_summary"] == (
        "1/1 child tasks done; 0 in progress; 0 blocked; 1/1 assigned"
    )
    assert reconciled_root.metadata["active_child_task_ids"] == []
    assert reconciled_root.metadata["blocked_child_task_ids"] == []
    attempt = await db_session.get(WorkspaceTaskSessionAttemptModel, leaf.current_attempt_id)
    assert attempt is not None
    assert attempt.status == "accepted"


@pytest.mark.asyncio
async def test_dispatch_after_operator_replan_cancels_stale_active_attempt(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_workspace_only(db_session)
    orchestrator = build_sql_orchestrator(
        db_session,
        config=OrchestratorConfig(heartbeat_seconds=3600),
    )
    plan = await orchestrator.start_goal(
        workspace_id="workspace-1",
        title="Ship a redispatched durable plan",
        start_supervisor=False,
    )
    await SqlWorkspacePlanOutboxRepository(db_session).enqueue(
        plan_id=plan.id,
        workspace_id="workspace-1",
        event_type=SUPERVISOR_TICK_EVENT,
        payload={
            "workspace_id": "workspace-1",
            "root_task_id": "root-task-1",
            "actor_user_id": "worker-user-1",
            "leader_agent_id": BUILTIN_SISYPHUS_ID,
        },
    )
    await db_session.commit()

    monkeypatch.setattr(
        "src.infrastructure.agent.workspace.worker_launch.schedule_worker_session",
        lambda **_kwargs: None,
    )
    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={
            SUPERVISOR_TICK_EVENT: make_supervisor_tick_handler(
                config=OrchestratorConfig(heartbeat_seconds=3600),
            ),
            WORKER_LAUNCH_EVENT: make_worker_launch_handler(worktree_preparer=_noop_worktree),
        },
        worker_id="worker-a",
    )

    assert await worker.run_once() == 1
    assert await worker.run_once() == 1
    db_session.expire_all()
    dispatched = await SqlPlanRepository(db_session).get(plan.id)
    assert dispatched is not None
    leaf = dispatched.leaf_tasks()[0]
    assert leaf.current_attempt_id is not None
    previous_attempt_id = leaf.current_attempt_id
    assert leaf.workspace_task_id is not None
    previous_attempt = await db_session.get(
        WorkspaceTaskSessionAttemptModel,
        previous_attempt_id,
    )
    assert previous_attempt is not None
    assert previous_attempt.status == "running"

    dispatched.replace_node(
        replace(
            leaf,
            intent=TaskIntent.TODO,
            execution=TaskExecution.IDLE,
            assignee_agent_id=None,
            current_attempt_id=None,
            metadata={
                **dict(leaf.metadata or {}),
                "operator_action": {
                    "action": "operator_replan_requested",
                    "actor_id": "operator",
                    "reason": "retry after platform fix",
                    "created_at": datetime.now(UTC).isoformat(),
                },
            },
        )
    )
    await SqlPlanRepository(db_session).save(dispatched)
    await SqlWorkspacePlanOutboxRepository(db_session).enqueue(
        plan_id=plan.id,
        workspace_id="workspace-1",
        event_type=SUPERVISOR_TICK_EVENT,
        payload={
            "workspace_id": "workspace-1",
            "root_task_id": "root-task-1",
            "actor_user_id": "worker-user-1",
            "leader_agent_id": BUILTIN_SISYPHUS_ID,
        },
    )
    await db_session.commit()

    assert await worker.run_once() == 1
    db_session.expire_all()
    redispatched = await SqlPlanRepository(db_session).get(plan.id)
    assert redispatched is not None
    redispatched_leaf = redispatched.leaf_tasks()[0]
    assert redispatched_leaf.current_attempt_id is not None
    assert redispatched_leaf.current_attempt_id != previous_attempt_id
    assert redispatched_leaf.execution is TaskExecution.DISPATCHED

    old_attempt = await db_session.get(WorkspaceTaskSessionAttemptModel, previous_attempt_id)
    assert old_attempt is not None
    assert old_attempt.status == "cancelled"
    assert old_attempt.adjudication_reason == "plan_node_reset_superseded"

    new_attempt = await db_session.get(
        WorkspaceTaskSessionAttemptModel,
        redispatched_leaf.current_attempt_id,
    )
    assert new_attempt is not None
    assert new_attempt.status == "running"
    assert new_attempt.attempt_number == 2

    projected_task = await SqlWorkspaceTaskRepository(db_session).find_by_id(
        redispatched_leaf.workspace_task_id or ""
    )
    assert projected_task is not None
    assert projected_task.metadata[CURRENT_ATTEMPT_ID] == redispatched_leaf.current_attempt_id
    assert projected_task.metadata["launch_state"] == "scheduled"

    launch_jobs = list(
        (
            await db_session.execute(
                select(WorkspacePlanOutboxModel)
                .where(WorkspacePlanOutboxModel.event_type == WORKER_LAUNCH_EVENT)
                .order_by(WorkspacePlanOutboxModel.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    assert [job.status for job in launch_jobs] == ["completed", "pending"]
    assert launch_jobs[-1].payload_json["attempt_id"] == redispatched_leaf.current_attempt_id


@pytest.mark.asyncio
async def test_retry_same_node_dispatches_same_conversation_repair_turn(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_workspace_only(db_session)
    plan = Plan(
        id="plan-repair-turn",
        workspace_id="workspace-1",
        goal_id=PlanNodeId("goal-repair-turn"),
        status=PlanStatus.ACTIVE,
    )
    plan.add_node(
        PlanNode(
            id="goal-repair-turn",
            plan_id=plan.id,
            parent_id=None,
            kind=PlanNodeKind.GOAL,
            title="Ship repair turn",
        )
    )
    old_worktree = "${sandbox_code_root}/../.memstack/worktrees/attempt-old"
    plan.add_node(
        PlanNode(
            id="node-repair-turn",
            plan_id=plan.id,
            parent_id=plan.goal_id,
            kind=PlanNodeKind.TASK,
            title="Repair missing evidence",
            description="Provide the fresh commit evidence.",
            recommended_capabilities=(Capability(name="codegen"),),
            workspace_task_id="repair-task-1",
            feature_checkpoint=FeatureCheckpoint(
                feature_id="feature-repair-turn",
                sequence=1,
                title="Repair missing evidence",
                test_commands=("npm test",),
                expected_artifacts=("src/example.ts",),
                worktree_path=old_worktree,
                branch_name="workspace/node-repair-turn-attempt-old",
                base_ref="HEAD",
            ),
            metadata={
                "write_set": ["src/example.ts"],
                "verification_commands": ["npm test"],
                "last_verification_attempt_id": "attempt-old",
                "last_verification_judge_verdict": "needs_rework",
                "last_verification_judge_next_action_kind": "retry_same_node",
                "last_verification_judge_required_next_action": "report fresh commit_ref",
                "last_verification_judge_failed_criteria": ["missing_commit_ref"],
                "last_verification_judge_repair_brief": {
                    "failed_items": ["missing commit_ref"],
                    "minimum_verifications": ["npm test"],
                    "feedback_items": [
                        {
                            "target_layer": "planner",
                            "feedback_kind": "plan_scope_mismatch",
                            "severity": "warning",
                            "recommended_action": "revise_plan_node",
                            "summary": "planner-only feedback must not reach worker",
                        }
                    ],
                },
                "last_verification_feedback_items": [
                    {
                        "target_layer": "worker",
                        "feedback_kind": "missing_evidence",
                        "severity": "blocking",
                        "recommended_action": "retry_worker",
                        "summary": "worker should report a fresh commit_ref",
                        "failure_signature": "missing-commit-ref",
                    },
                    {
                        "target_layer": "planner",
                        "feedback_kind": "plan_scope_mismatch",
                        "severity": "warning",
                        "recommended_action": "revise_plan_node",
                        "summary": "planner-only feedback must not reach worker",
                    },
                ],
            },
        )
    )
    await SqlPlanRepository(db_session).save(plan)
    db_session.add(
        WorkspaceTaskModel(
            id="repair-task-1",
            workspace_id="workspace-1",
            title="Repair missing evidence",
            description="Provide the fresh commit evidence.",
            created_by="worker-user-1",
            status="in_progress",
            priority=0,
            assignee_agent_id="worker-agent",
            metadata_json={
                AUTONOMY_SCHEMA_VERSION_KEY: 1,
                TASK_ROLE: "execution_task",
                ROOT_GOAL_TASK_ID: "root-task-1",
                "lineage_source": "agent",
                WORKSPACE_PLAN_ID: plan.id,
                WORKSPACE_PLAN_NODE_ID: "node-repair-turn",
                "feature_checkpoint": {
                    "feature_id": "feature-repair-turn",
                    "worktree_path": old_worktree,
                    "branch_name": "workspace/node-repair-turn-attempt-old",
                    "base_ref": "HEAD",
                },
            },
        )
    )
    db_session.add(
        WorkspaceTaskSessionAttemptModel(
            id="attempt-old",
            workspace_task_id="repair-task-1",
            root_goal_task_id="root-task-1",
            workspace_id="workspace-1",
            attempt_number=1,
            status="rejected",
            conversation_id="conversation-reuse",
            worker_agent_id="worker-agent",
            leader_agent_id=BUILTIN_SISYPHUS_ID,
            leader_feedback="judge verdict=needs_rework; missing commit_ref",
        )
    )
    await SqlWorkspacePlanOutboxRepository(db_session).enqueue(
        plan_id=plan.id,
        workspace_id="workspace-1",
        event_type=SUPERVISOR_TICK_EVENT,
        payload={
            "workspace_id": "workspace-1",
            "root_task_id": "root-task-1",
            "actor_user_id": "worker-user-1",
            "leader_agent_id": BUILTIN_SISYPHUS_ID,
        },
    )
    await db_session.commit()

    launched: list[dict[str, object]] = []

    def fake_schedule_worker_session(**kwargs: object) -> None:
        launched.append(kwargs)

    monkeypatch.setattr(
        "src.infrastructure.agent.workspace.worker_launch.schedule_worker_session",
        fake_schedule_worker_session,
    )
    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={
            SUPERVISOR_TICK_EVENT: make_supervisor_tick_handler(
                config=OrchestratorConfig(heartbeat_seconds=3600),
            ),
            WORKER_LAUNCH_EVENT: make_worker_launch_handler(worktree_preparer=_noop_worktree),
        },
        worker_id="worker-a",
    )

    assert await worker.run_once() == 1
    outbox_items = list(
        (await db_session.execute(select(WorkspacePlanOutboxModel))).scalars().all()
    )
    launch_items = list(
        (
            await db_session.execute(
                select(WorkspacePlanOutboxModel).where(
                    WorkspacePlanOutboxModel.event_type == WORKER_LAUNCH_EVENT
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(launch_items) == 1, [
        (item.event_type, item.status, item.last_error) for item in outbox_items
    ]
    assert await worker.run_once() == 1
    assert launched
    assert launched[0]["reuse_conversation_id"] == "conversation-reuse"
    assert "[repair-turn]" in str(launched[0]["repair_brief_prompt"])
    assert "missing commit_ref" in str(launched[0]["repair_brief_prompt"])
    assert "worker should report a fresh commit_ref" in str(launched[0]["repair_brief_prompt"])
    assert "planner-only feedback" not in str(launched[0]["repair_brief_prompt"])

    db_session.expire_all()
    attempts = list(
        (
            await db_session.execute(
                select(WorkspaceTaskSessionAttemptModel)
                .where(WorkspaceTaskSessionAttemptModel.workspace_task_id == "repair-task-1")
                .order_by(WorkspaceTaskSessionAttemptModel.attempt_number.asc())
            )
        )
        .scalars()
        .all()
    )
    assert len(attempts) == 2
    old_attempt, new_attempt = attempts
    assert old_attempt.id == "attempt-old"
    assert new_attempt.status == "running"
    assert new_attempt.conversation_id == "conversation-reuse"
    assert new_attempt.candidate_artifacts_json == []
    assert new_attempt.candidate_verifications_json == []

    repaired_plan = await SqlPlanRepository(db_session).get(plan.id)
    assert repaired_plan is not None
    repaired_node = repaired_plan.nodes[PlanNodeId("node-repair-turn")]
    assert repaired_node.current_attempt_id == new_attempt.id
    assert repaired_node.feature_checkpoint is not None
    assert repaired_node.feature_checkpoint.worktree_path == old_worktree
    assert repaired_node.metadata["current_repair_turn"]["previous_attempt_id"] == "attempt-old"
    assert repaired_node.metadata["same_conversation_repair_turn_count"] == 1

    events = list(
        (
            await db_session.execute(
                select(WorkspacePlanEventModel)
                .where(WorkspacePlanEventModel.plan_id == plan.id)
                .order_by(WorkspacePlanEventModel.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    assert [event.event_type for event in events] == ["worker_repair_turn_dispatched"]
    assert events[0].attempt_id == new_attempt.id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("force_schedule", "expected_launch_jobs", "expected_pending_launch_jobs"),
    [
        (False, 1, 0),
        (True, 2, 1),
    ],
)
async def test_handoff_resume_handler_running_current_attempt_respects_force_schedule(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    force_schedule: bool,
    expected_launch_jobs: int,
    expected_pending_launch_jobs: int,
) -> None:
    await _seed_workspace_only(db_session)
    orchestrator = build_sql_orchestrator(
        db_session,
        config=OrchestratorConfig(heartbeat_seconds=3600),
    )
    plan = await orchestrator.start_goal(
        workspace_id="workspace-1",
        title="Ship a resumable durable plan",
        start_supervisor=False,
    )
    await SqlWorkspacePlanOutboxRepository(db_session).enqueue(
        plan_id=plan.id,
        workspace_id="workspace-1",
        event_type=SUPERVISOR_TICK_EVENT,
        payload={
            "workspace_id": "workspace-1",
            "root_task_id": "root-task-1",
            "actor_user_id": "worker-user-1",
            "leader_agent_id": BUILTIN_SISYPHUS_ID,
        },
    )
    await db_session.commit()

    monkeypatch.setattr(
        "src.infrastructure.agent.workspace.worker_launch.schedule_worker_session",
        lambda **_kwargs: None,
    )
    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={
            SUPERVISOR_TICK_EVENT: make_supervisor_tick_handler(
                config=OrchestratorConfig(heartbeat_seconds=3600),
            ),
            WORKER_LAUNCH_EVENT: make_worker_launch_handler(worktree_preparer=_noop_worktree),
        },
        worker_id="worker-a",
    )
    assert await worker.run_once() == 1
    assert await worker.run_once() == 1

    db_session.expire_all()
    dispatched = await SqlPlanRepository(db_session).get(plan.id)
    assert dispatched is not None
    leaf = dispatched.leaf_tasks()[0]
    assert leaf.workspace_task_id is not None
    assert leaf.current_attempt_id is not None
    attempt_row = await db_session.get(WorkspaceTaskSessionAttemptModel, leaf.current_attempt_id)
    assert attempt_row is not None
    assert attempt_row.status == "running"
    attempt_row.conversation_id = "conversation-running"
    await db_session.flush()
    assert attempt_row.conversation_id

    await SqlWorkspacePlanOutboxRepository(db_session).enqueue(
        plan_id=plan.id,
        workspace_id="workspace-1",
        event_type=HANDOFF_RESUME_EVENT,
        payload={
            "workspace_id": "workspace-1",
            "task_id": leaf.workspace_task_id,
            "node_id": leaf.id,
            "worker_agent_id": "worker-agent",
            "actor_user_id": "worker-user-1",
            "leader_agent_id": BUILTIN_SISYPHUS_ID,
            "previous_attempt_id": leaf.current_attempt_id,
            "root_goal_task_id": "root-task-1",
            "summary": "snapshot thought this was stale",
            "force_schedule": force_schedule,
        },
    )
    await db_session.commit()

    resume_worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={HANDOFF_RESUME_EVENT: make_handoff_resume_handler()},
        worker_id="worker-b",
    )
    assert await resume_worker.run_once() == 1

    db_session.expire_all()
    launch_jobs = list(
        (
            await db_session.execute(
                select(WorkspacePlanOutboxModel).where(
                    WorkspacePlanOutboxModel.event_type == WORKER_LAUNCH_EVENT
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(launch_jobs) == expected_launch_jobs
    pending_launch_jobs = [job for job in launch_jobs if job.status == "pending"]
    assert len(pending_launch_jobs) == expected_pending_launch_jobs
    if force_schedule:
        assert pending_launch_jobs[0].payload_json["attempt_id"] == leaf.current_attempt_id
    refreshed_plan = await SqlPlanRepository(db_session).get(plan.id)
    assert refreshed_plan is not None
    assert refreshed_plan.leaf_tasks()[0].current_attempt_id == leaf.current_attempt_id


@pytest.mark.asyncio
async def test_handoff_resume_handler_creates_fresh_attempt_and_worker_launch(  # noqa: PLR0915
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_workspace_only(db_session)
    orchestrator = build_sql_orchestrator(
        db_session,
        config=OrchestratorConfig(heartbeat_seconds=3600),
    )
    plan = await orchestrator.start_goal(
        workspace_id="workspace-1",
        title="Ship a resumable durable plan",
        start_supervisor=False,
    )
    await SqlWorkspacePlanOutboxRepository(db_session).enqueue(
        plan_id=plan.id,
        workspace_id="workspace-1",
        event_type=SUPERVISOR_TICK_EVENT,
        payload={
            "workspace_id": "workspace-1",
            "root_task_id": "root-task-1",
            "actor_user_id": "worker-user-1",
            "leader_agent_id": BUILTIN_SISYPHUS_ID,
        },
    )
    await db_session.commit()

    monkeypatch.setattr(
        "src.infrastructure.agent.workspace.worker_launch.schedule_worker_session",
        lambda **_kwargs: None,
    )
    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={
            SUPERVISOR_TICK_EVENT: make_supervisor_tick_handler(
                config=OrchestratorConfig(heartbeat_seconds=3600),
            ),
            WORKER_LAUNCH_EVENT: make_worker_launch_handler(worktree_preparer=_noop_worktree),
        },
        worker_id="worker-a",
    )
    assert await worker.run_once() == 1
    assert await worker.run_once() == 1

    db_session.expire_all()
    dispatched = await SqlPlanRepository(db_session).get(plan.id)
    assert dispatched is not None
    leaf = dispatched.leaf_tasks()[0]
    assert leaf.workspace_task_id is not None
    assert leaf.current_attempt_id is not None
    previous_attempt_id = leaf.current_attempt_id
    dispatched.replace_node(
        _with_stale_attempt_metadata(leaf, previous_attempt_id=previous_attempt_id)
    )
    await SqlPlanRepository(db_session).save(dispatched)

    task_row = await db_session.get(WorkspaceTaskModel, leaf.workspace_task_id)
    assert task_row is not None
    task_row.status = "blocked"
    task_row.metadata_json = {
        **dict(task_row.metadata_json or {}),
        "evidence_refs": ["commit_ref:abc123", "changed_file:src/example.py"],
        "execution_verifications": ["test_run:uv run pytest src/tests/unit/example.py"],
        "last_worker_report_type": "blocked",
        "last_worker_report_summary": "lost process",
    }
    attempt_row = await db_session.get(WorkspaceTaskSessionAttemptModel, previous_attempt_id)
    assert attempt_row is not None
    attempt_row.status = "blocked"
    await SqlWorkspacePlanOutboxRepository(db_session).enqueue(
        plan_id=plan.id,
        workspace_id="workspace-1",
        event_type=HANDOFF_RESUME_EVENT,
        payload={
            "workspace_id": "workspace-1",
            "task_id": leaf.workspace_task_id,
            "node_id": leaf.id,
            "worker_agent_id": "worker-agent",
            "actor_user_id": "worker-user-1",
            "leader_agent_id": BUILTIN_SISYPHUS_ID,
            "previous_attempt_id": previous_attempt_id,
            "root_goal_task_id": "root-task-1",
            "summary": "resume after restart",
            "force_schedule": True,
        },
    )
    await db_session.commit()

    resume_worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={HANDOFF_RESUME_EVENT: make_handoff_resume_handler()},
        worker_id="worker-b",
    )
    assert await resume_worker.run_once() == 1

    db_session.expire_all()
    resume_items = list(
        (
            await db_session.execute(
                select(WorkspacePlanOutboxModel).where(
                    WorkspacePlanOutboxModel.event_type == HANDOFF_RESUME_EVENT
                )
            )
        )
        .scalars()
        .all()
    )
    assert resume_items[-1].status == "completed", resume_items[-1].last_error
    resumed = await SqlPlanRepository(db_session).get(plan.id)
    assert resumed is not None
    resumed_leaf = resumed.leaf_tasks()[0]
    assert resumed_leaf.current_attempt_id != previous_attempt_id
    assert "last_verification_summary" not in resumed_leaf.metadata
    assert "last_verification_passed" not in resumed_leaf.metadata
    assert "last_verification_attempt_id" not in resumed_leaf.metadata
    assert "verification_evidence_refs" not in resumed_leaf.metadata
    assert "terminal_attempt_status" not in resumed_leaf.metadata
    assert resumed_leaf.metadata["terminal_attempt_retry_count"] == 1
    assert resumed_leaf.handoff_package is not None
    assert resumed_leaf.handoff_package.git_head == "abc123"
    assert resumed_leaf.handoff_package.changed_files == ("src/example.py",)
    assert resumed_leaf.handoff_package.test_commands == (
        "uv run pytest src/tests/unit/example.py",
    )

    projected_task = await SqlWorkspaceTaskRepository(db_session).find_by_id(leaf.workspace_task_id)
    assert projected_task is not None
    assert projected_task.status.value == "in_progress"
    assert projected_task.metadata["handoff_package"]["summary"] == "resume after restart"
    assert projected_task.metadata[CURRENT_ATTEMPT_ID] == resumed_leaf.current_attempt_id

    launch_jobs = list(
        (
            await db_session.execute(
                select(WorkspacePlanOutboxModel)
                .where(WorkspacePlanOutboxModel.event_type == WORKER_LAUNCH_EVENT)
                .where(WorkspacePlanOutboxModel.status == "pending")
            )
        )
        .scalars()
        .all()
    )
    assert len(launch_jobs) == 1
    assert "[handoff-package]" in str(launch_jobs[0].payload_json["extra_instructions"])
    assert "previous_attempt_id" in str(launch_jobs[0].payload_json["extra_instructions"])


@pytest.mark.asyncio
async def test_handoff_resume_handler_defers_downstream_node_with_unmet_dependencies(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_only(db_session)
    plan = Plan(
        id="dependency-plan-1",
        workspace_id="workspace-1",
        goal_id=PlanNodeId("goal-node-1"),
        status=PlanStatus.ACTIVE,
    )
    plan.add_node(
        PlanNode(
            id="goal-node-1",
            plan_id=plan.id,
            parent_id=None,
            kind=PlanNodeKind.GOAL,
            title="Root goal",
        )
    )
    plan.add_node(
        PlanNode(
            id="implement-node",
            plan_id=plan.id,
            parent_id=PlanNodeId("goal-node-1"),
            kind=PlanNodeKind.TASK,
            title="Implement feature",
        )
    )
    plan.add_node(
        PlanNode(
            id="test-node",
            plan_id=plan.id,
            parent_id=PlanNodeId("goal-node-1"),
            kind=PlanNodeKind.TASK,
            title="Run E2E",
            depends_on=frozenset({PlanNodeId("implement-node")}),
            intent=TaskIntent.IN_PROGRESS,
            execution=TaskExecution.RUNNING,
            current_attempt_id="previous-test-attempt",
            workspace_task_id="test-task-1",
        )
    )
    await SqlPlanRepository(db_session).save(plan)
    db_session.add(
        WorkspaceTaskModel(
            id="test-task-1",
            workspace_id="workspace-1",
            title="Run E2E",
            description="Downstream verification task",
            created_by="worker-user-1",
            status="blocked",
            priority=0,
            assignee_agent_id="worker-agent",
            metadata_json={
                AUTONOMY_SCHEMA_VERSION_KEY: 1,
                TASK_ROLE: "execution_task",
                ROOT_GOAL_TASK_ID: "root-task-1",
                WORKSPACE_PLAN_ID: plan.id,
                WORKSPACE_PLAN_NODE_ID: "test-node",
            },
        )
    )
    db_session.add(
        WorkspaceTaskSessionAttemptModel(
            id="previous-test-attempt",
            workspace_task_id="test-task-1",
            root_goal_task_id="root-task-1",
            workspace_id="workspace-1",
            attempt_number=1,
            status="blocked",
            conversation_id="previous-test-conversation",
            worker_agent_id="worker-agent",
            leader_agent_id=BUILTIN_SISYPHUS_ID,
        )
    )
    await SqlWorkspacePlanOutboxRepository(db_session).enqueue(
        plan_id=plan.id,
        workspace_id="workspace-1",
        event_type=HANDOFF_RESUME_EVENT,
        payload={
            "workspace_id": "workspace-1",
            "task_id": "test-task-1",
            "node_id": "test-node",
            "worker_agent_id": "worker-agent",
            "actor_user_id": "worker-user-1",
            "leader_agent_id": BUILTIN_SISYPHUS_ID,
            "previous_attempt_id": "previous-test-attempt",
            "root_goal_task_id": "root-task-1",
            "summary": "resume downstream after restart",
            "force_schedule": True,
        },
    )
    await db_session.commit()

    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={HANDOFF_RESUME_EVENT: make_handoff_resume_handler()},
        worker_id="worker-dependency",
    )

    assert await worker.run_once() == 1

    loaded = await SqlPlanRepository(db_session).get(plan.id)
    assert loaded is not None
    test_node = loaded.nodes[PlanNodeId("test-node")]
    assert test_node.intent is TaskIntent.TODO
    assert test_node.execution is TaskExecution.IDLE
    assert test_node.current_attempt_id is None
    assert test_node.metadata["handoff_resume_deferred_missing_dependency_ids"] == [
        "implement-node"
    ]
    attempts = list(
        (
            await db_session.execute(
                select(WorkspaceTaskSessionAttemptModel).where(
                    WorkspaceTaskSessionAttemptModel.workspace_task_id == "test-task-1"
                )
            )
        )
        .scalars()
        .all()
    )
    assert [attempt.id for attempt in attempts] == ["previous-test-attempt"]
    launch_jobs = list(
        (
            await db_session.execute(
                select(WorkspacePlanOutboxModel).where(
                    WorkspacePlanOutboxModel.event_type == WORKER_LAUNCH_EVENT
                )
            )
        )
        .scalars()
        .all()
    )
    assert launch_jobs == []


async def _noop_worktree(
    _session: AsyncSession,
    _workspace_id: str,
    _task: WorkspaceTask,
    _extra_instructions: str | None,
    _attempt_id: str | None,
) -> str | None:
    return None


async def _seed_workspace_only(db_session: AsyncSession, *, include_worker: bool = True) -> None:
    rows = [
        DBUser(
            id="worker-user-1",
            email="worker-user-1@example.com",
            full_name="Worker User",
            hashed_password="hash",
            is_active=True,
        ),
        DBTenant(
            id="worker-tenant-1",
            name="Worker Tenant",
            slug="worker-tenant",
            description="",
            owner_id="worker-user-1",
            plan="free",
            max_projects=10,
            max_users=10,
            max_storage=1,
        ),
        DBProject(
            id="worker-project-1",
            tenant_id="worker-tenant-1",
            name="Worker Project",
            description="",
            owner_id="worker-user-1",
            memory_rules={},
            graph_config={},
            sandbox_type="cloud",
            sandbox_config={},
            is_public=False,
        ),
        WorkspaceModel(
            id="workspace-1",
            tenant_id="worker-tenant-1",
            project_id="worker-project-1",
            name="Worker Workspace",
            description="",
            created_by="worker-user-1",
            is_archived=False,
            metadata_json={},
        ),
        WorkspaceMemberModel(
            id="workspace-member-1",
            workspace_id="workspace-1",
            user_id="worker-user-1",
            role="owner",
            invited_by="worker-user-1",
        ),
        AgentDefinitionModel(
            id=BUILTIN_SISYPHUS_ID,
            tenant_id="worker-tenant-1",
            project_id="worker-project-1",
            name="sisyphus",
            display_name="Sisyphus",
            system_prompt="You coordinate workspace execution.",
            allowed_tools=[],
            allowed_skills=[],
            allowed_mcp_servers=[],
        ),
        WorkspaceTaskModel(
            id="root-task-1",
            workspace_id="workspace-1",
            title="Root goal",
            description="Root goal for V2 dispatch",
            created_by="worker-user-1",
            status="todo",
            priority=0,
            metadata_json={
                AUTONOMY_SCHEMA_VERSION_KEY: 1,
                TASK_ROLE: "goal_root",
                "goal_origin": "existing_root",
                "goal_source_refs": [],
                "root_goal_policy": {
                    "mutable_by_agent": False,
                    "completion_requires_external_proof": True,
                },
                "goal_health": "healthy",
            },
        ),
    ]
    if include_worker:
        rows.extend(
            [
                AgentDefinitionModel(
                    id="worker-agent",
                    tenant_id="worker-tenant-1",
                    project_id="worker-project-1",
                    name="worker-agent",
                    display_name="Worker Agent",
                    system_prompt="You execute workspace tasks.",
                    allowed_tools=[],
                    allowed_skills=[],
                    allowed_mcp_servers=[],
                ),
                WorkspaceAgentModel(
                    id="worker-binding-1",
                    workspace_id="workspace-1",
                    agent_id="worker-agent",
                    display_name="Worker Agent",
                    description=None,
                    config_json={"capabilities": ["codegen"]},
                    is_active=True,
                ),
            ]
        )
    db_session.add_all(rows)
    await db_session.flush()
