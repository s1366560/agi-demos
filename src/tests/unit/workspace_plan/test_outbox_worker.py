"""Tests for the workspace plan outbox worker."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import src.infrastructure.agent.workspace_plan.outbox_handlers as outbox_handlers
from src.domain.model.workspace.workspace_task import WorkspaceTask
from src.domain.model.workspace_plan import (
    Capability,
    FeatureCheckpoint,
    PlanNode,
    PlanNodeId,
    PlanNodeKind,
    TaskExecution,
    TaskIntent,
)
from src.domain.ports.services.task_allocator_port import Allocation, WorkspaceAgent
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentDefinitionModel,
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
    AUTONOMY_SCHEMA_VERSION_KEY,
    CURRENT_ATTEMPT_ID,
    CURRENT_ATTEMPT_WORKER_BINDING_ID,
    EXECUTION_STATE,
    ROOT_GOAL_TASK_ID,
    TASK_ROLE,
    WORKSPACE_PLAN_ID,
    WORKSPACE_PLAN_NODE_ID,
)
from src.infrastructure.agent.workspace_plan.factory import build_sql_orchestrator
from src.infrastructure.agent.workspace_plan.orchestrator import OrchestratorConfig
from src.infrastructure.agent.workspace_plan.outbox_handlers import (
    HANDOFF_RESUME_EVENT,
    SUPERVISOR_TICK_EVENT,
    WORKER_LAUNCH_EVENT,
    _is_structural_sandbox_command,
    _node_allowed_sandbox_commands,
    _persisted_attempt_leader_agent_id,
    _WorkspaceSandboxCommandRunner,
    _worktree_setup_command,
    make_handoff_resume_handler,
    make_supervisor_tick_handler,
    make_worker_launch_handler,
)
from src.infrastructure.agent.workspace_plan.outbox_worker import (
    WorkspacePlanOutboxWorker,
    WorkspacePlanSessionFactory,
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
        yield db_session

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
    assert ".memstack/git-remotes/${repo_name}.git" in command
    assert 'git init --bare "$fallback_remote"' in command
    assert 'git remote add origin "$fallback_remote"' in command
    assert "git config push.default current" in command


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
    calls = 0

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
            loaded = await repo.get_by_id(item.id)
            if loaded is not None and loaded.status == "completed":
                return
            await asyncio.sleep(0.01)
        raise AssertionError("outbox item was not retried after cancellation")

    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={"worker_launch": flaky_handler},
        worker_id="worker-a",
        poll_interval_seconds=0.01,
    )

    worker.start()
    try:
        await wait_for_completed()
    finally:
        await worker.stop()

    loaded = await repo.get_by_id(item.id)
    assert loaded is not None
    assert loaded.status == "completed"
    assert loaded.attempt_count == 1
    assert loaded.lease_owner is None
    assert calls == 2


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
            status="done",
            priority=0,
            assignee_agent_id="worker-agent",
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
    outbox = await SqlWorkspacePlanOutboxRepository(db_session).list_by_workspace(
        "workspace-1",
        limit=5,
    )
    assert outbox[0].status == "dead_letter"
    assert "User must be a workspace member" in str(outbox[0].last_error)


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
    ) -> str:
        assert extra_instructions is not None
        assert "[feature-checkpoint]" in extra_instructions
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


async def _noop_worktree(
    _session: AsyncSession,
    _workspace_id: str,
    _task: WorkspaceTask,
    _extra_instructions: str | None,
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
