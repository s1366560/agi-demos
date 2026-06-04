"""Tests for the workspace plan outbox worker."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import src.infrastructure.agent.workspace_plan.outbox_handlers as outbox_handlers
from src.domain.model.workspace.workspace import Workspace
from src.domain.model.workspace.workspace_task import WorkspaceTask
from src.domain.model.workspace.workspace_task_session_attempt import (
    WorkspaceTaskSessionAttemptStatus,
)
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
from src.domain.ports.services.workspace_supervisor_port import TickReport
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentDefinitionModel,
    Base,
    PlanModel,
    Project as DBProject,
    Tenant as DBTenant,
    User as DBUser,
    WorkspaceAgentModel,
    WorkspaceDeploymentModel,
    WorkspaceMemberModel,
    WorkspaceModel,
    WorkspacePipelineRunModel,
    WorkspacePlanEventModel,
    WorkspacePlanOutboxModel,
    WorkspaceTaskModel,
    WorkspaceTaskSessionAttemptModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_plan_repository import SqlPlanRepository
from src.infrastructure.adapters.secondary.persistence.sql_workspace_pipeline import (
    SqlWorkspacePipelineRepository,
)
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
    _project_supervisor_decision_to_workspace_task,
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
    _ensure_leader_execution_team,
    _extract_task_evidence,
    _first_prefixed_ref,
    _integration_status_from_output,
    _is_structural_sandbox_command,
    _node_allowed_sandbox_commands,
    _node_worker_brief,
    _persisted_attempt_leader_agent_id,
    _prepare_attempt_worktree_if_available,
    _resolve_actor_user_id,
    _WorkspaceSandboxCommandRunner,
    _worktree_integration_command,
    _worktree_setup_command,
    make_handoff_resume_handler,
    make_pipeline_run_requested_handler,
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
from src.infrastructure.agent.workspace_plan.worktree_manager import AttemptWorktreeContext


def test_node_worker_brief_surfaces_latest_verification_feedback() -> None:
    node = PlanNode(
        id="node-feedback",
        plan_id="plan-feedback",
        parent_id=PlanNodeId("goal-feedback"),
        kind=PlanNodeKind.TASK,
        title="Deploy through Drone",
        description="Trigger docker deploy and verify health.",
        metadata={
            "last_verification_attempt_id": "attempt-132",
            "pipeline_status": "failed",
            "pipeline_failed_stage": "workspace-ci/deploy",
            "pipeline_last_summary": (
                "Drone build #120 failed in deploy; wget cannot connect to health endpoint; "
                "container logs report missing field `enableTracing`."
            ),
            "last_verification_judge_required_next_action": (
                "Reproduce container startup in the attempt worktree, inspect container logs, "
                "and fix runtime config before rerunning Drone."
            ),
            "last_verification_feedback_items": [
                {
                    "target_layer": "worker",
                    "feedback_kind": "product_code_failure",
                    "severity": "blocking",
                    "recommended_action": "retry_worker",
                    "failure_signature": "drone-docker-deploy-missing-runtime-env",
                    "summary": "Container starts without required runtime environment.",
                    "evidence_refs": ["drone_error:deploy_runtime_env_missing"],
                }
            ],
        },
    )

    brief = _node_worker_brief(node)

    assert "[verification-feedback]" in brief
    assert "pipeline_failed_stage=workspace-ci/deploy" in brief
    assert "missing field `enableTracing`" in brief
    assert "last_verification_judge_required_next_action=Reproduce container startup" in brief
    assert "failure_signature=drone-docker-deploy-missing-runtime-env" in brief
    assert "[/verification-feedback]" in brief


def test_node_worker_brief_surfaces_retry_reason_and_runtime_feedback() -> None:
    node = PlanNode(
        id="node-feedback",
        plan_id="plan-feedback",
        parent_id=PlanNodeId("goal-feedback"),
        kind=PlanNodeKind.TASK,
        title="Deploy through Drone",
        description="Trigger docker deploy and verify health.",
        metadata={
            "retry_last_reason": (
                "harness-native CI pipeline failed: Drone build #127 deploy stage exited 1; "
                "wget: can't connect to remote host (192.168.65.254): Connection refused"
            ),
            "last_verification_feedback_items": [
                {
                    "target_layer": "runtime",
                    "feedback_kind": "runtime_infra_failure",
                    "severity": "blocking",
                    "recommended_action": "retry_infra",
                    "failure_signature": "drone-health-host-network-refused",
                    "summary": "host.docker.internal health probe failed after container start.",
                }
            ],
        },
    )

    brief = _node_worker_brief(node)

    assert "[verification-feedback]" in brief
    assert "retry_last_reason=harness-native CI pipeline failed" in brief
    assert "Drone build #127 deploy stage exited 1" in brief
    assert "target_layer=runtime" in brief
    assert "failure_signature=drone-health-host-network-refused" in brief


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


@pytest.mark.asyncio
async def test_pipeline_handler_commits_running_state_before_drone_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, session_maker = await _file_backed_outbox_session_maker(tmp_path)
    entered = asyncio.Event()
    release = asyncio.Event()

    class BlockingDroneProvider:
        async def run(self, contract: PipelineContractSpec) -> outbox_handlers.PipelineRunResult:
            _ = contract
            entered.set()
            await release.wait()
            return outbox_handlers.PipelineRunResult(
                status="success",
                reason="Drone build octo/my-evo#1 finished with status success",
                stage_results=(
                    outbox_handlers.PipelineStageResult(
                        stage="workspace-ci/build",
                        status="success",
                        command="drone:workspace-ci/build",
                        exit_code=0,
                        stdout_preview="build passed",
                    ),
                ),
                evidence_refs=("ci_pipeline:passed",),
                external_id="octo/my-evo#1",
                metadata={"external_provider": DRONE_PROVIDER, "drone_build_number": "1"},
            )

    async def _require_provider(_provider: str) -> BlockingDroneProvider:
        return BlockingDroneProvider()

    monkeypatch.setattr(outbox_handlers, "require_pipeline_provider", _require_provider)

    async with session_maker() as seed_session:
        await _seed_workspace_only(seed_session)
        workspace = await seed_session.get(WorkspaceModel, "workspace-1")
        assert workspace is not None
        workspace.metadata_json = {
            "workspace_type": "software_development",
            "code_context": {"sandbox_code_root": "/workspace/my-evo"},
            "delivery_cicd": {
                "provider": DRONE_PROVIDER,
                "auto_deploy": False,
                "agent_managed": False,
                "timeout_seconds": 60,
            },
        }
        plan = Plan(
            id="pipeline-plan-1",
            workspace_id="workspace-1",
            goal_id=PlanNodeId("pipeline-goal-1"),
            status=PlanStatus.ACTIVE,
        )
        plan.add_node(
            PlanNode(
                id="pipeline-goal-1",
                plan_id=plan.id,
                parent_id=None,
                kind=PlanNodeKind.GOAL,
                title="Ship pipeline",
            )
        )
        plan.add_node(
            PlanNode(
                id="pipeline-node-1",
                plan_id=plan.id,
                parent_id=plan.goal_id,
                kind=PlanNodeKind.TASK,
                title="Run Drone",
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-pipeline-1",
                metadata={"iteration_phase": "deploy"},
            )
        )
        await SqlPlanRepository(seed_session).save(plan)
        item = await SqlWorkspacePlanOutboxRepository(seed_session).enqueue(
            plan_id=plan.id,
            workspace_id="workspace-1",
            event_type="pipeline_run_requested",
            payload={
                "workspace_id": "workspace-1",
                "plan_id": plan.id,
                "node_id": "pipeline-node-1",
                "attempt_id": "attempt-pipeline-1",
                ROOT_GOAL_TASK_ID: "root-task-1",
            },
        )
        item_id = item.id
        await seed_session.commit()

    handler = make_pipeline_run_requested_handler()
    async with session_maker() as handler_session:
        item = await handler_session.get(WorkspacePlanOutboxModel, item_id)
        assert item is not None
        task = asyncio.create_task(handler(item, handler_session))
        await asyncio.wait_for(entered.wait(), timeout=2)

        async with session_maker() as inspect_session:
            run = (
                await inspect_session.execute(
                    select(WorkspacePipelineRunModel).where(
                        WorkspacePipelineRunModel.attempt_id == "attempt-pipeline-1"
                    )
                )
            ).scalar_one()
            assert run.status == "running"
            assert run.provider == DRONE_PROVIDER
            visible_plan = await SqlPlanRepository(inspect_session).get("pipeline-plan-1")
            assert visible_plan is not None
            visible_node = visible_plan.nodes[PlanNodeId("pipeline-node-1")]
            assert visible_node.metadata["pipeline_status"] == "running"
            assert visible_node.metadata["pipeline_run_id"] == run.id

        release.set()
        await task
        await handler_session.commit()

    await engine.dispose()


@pytest.mark.asyncio
async def test_pipeline_handler_persists_drone_deployment_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, session_maker = await _file_backed_outbox_session_maker(tmp_path)

    class SuccessfulDroneProvider:
        async def run(self, contract: PipelineContractSpec) -> outbox_handlers.PipelineRunResult:
            _ = contract
            return outbox_handlers.PipelineRunResult(
                status="success",
                reason="Drone build octo/my-evo#2 finished with status success",
                stage_results=(
                    outbox_handlers.PipelineStageResult(
                        stage="workspace-ci/deploy",
                        status="success",
                        command="drone:workspace-ci/deploy",
                        exit_code=0,
                        stdout_preview="docker compose up -d web",
                        metadata={"drone_step_kind": "deploy"},
                    ),
                ),
                evidence_refs=("ci_pipeline:passed", "deployment:passed:docker"),
                external_id="octo/my-evo#2",
                external_url="http://localhost:8080/octo/my-evo/2",
                deployment_status="deployed",
                metadata={
                    "external_provider": DRONE_PROVIDER,
                    "deployment_status": "deployed",
                    "deploy_validation": outbox_handlers.DRONE_DOCKER_DEPLOY_VALIDATION,
                },
            )

    async def _require_provider(_provider: str) -> SuccessfulDroneProvider:
        return SuccessfulDroneProvider()

    monkeypatch.setattr(outbox_handlers, "require_pipeline_provider", _require_provider)

    async with session_maker() as seed_session:
        await _seed_workspace_only(seed_session)
        workspace = await seed_session.get(WorkspaceModel, "workspace-1")
        assert workspace is not None
        workspace.metadata_json = {
            "workspace_type": "software_development",
            "code_context": {"sandbox_code_root": "/workspace/my-evo"},
            "delivery_cicd": {
                "provider": DRONE_PROVIDER,
                "code_root": "/workspace/my-evo",
                "auto_deploy": False,
                "agent_managed": False,
                "services": [
                    {
                        "service_id": "web",
                        "name": "Web",
                        "start_command": "npm run start",
                        "internal_port": 8080,
                        "path_prefix": "/",
                        "health_path": "/health",
                        "required": True,
                    }
                ],
                "drone": {
                    "repo": "octo/my-evo",
                    "deploy": {
                        "enabled": False,
                        "mode": "cli",
                        "stage": "deploy",
                        "docker": {
                            "deploy_host_port": 18080,
                            "reserved_host_ports": [3000, 3001, 5001],
                        },
                    },
                },
            },
        }
        plan = Plan(
            id="pipeline-plan-1",
            workspace_id="workspace-1",
            goal_id=PlanNodeId("pipeline-goal-1"),
            status=PlanStatus.ACTIVE,
        )
        plan.add_node(
            PlanNode(
                id="pipeline-goal-1",
                plan_id=plan.id,
                parent_id=None,
                kind=PlanNodeKind.GOAL,
                title="Ship pipeline",
            )
        )
        plan.add_node(
            PlanNode(
                id="pipeline-node-1",
                plan_id=plan.id,
                parent_id=plan.goal_id,
                kind=PlanNodeKind.TASK,
                title="Run Drone",
                intent=TaskIntent.IN_PROGRESS,
                execution=TaskExecution.REPORTED,
                current_attempt_id="attempt-pipeline-1",
                metadata={"iteration_phase": "deploy"},
            )
        )
        await SqlPlanRepository(seed_session).save(plan)
        item = await SqlWorkspacePlanOutboxRepository(seed_session).enqueue(
            plan_id=plan.id,
            workspace_id="workspace-1",
            event_type="pipeline_run_requested",
            payload={
                "workspace_id": "workspace-1",
                "plan_id": plan.id,
                "node_id": "pipeline-node-1",
                "attempt_id": "attempt-pipeline-1",
                ROOT_GOAL_TASK_ID: "root-task-1",
            },
        )
        item_id = item.id
        await seed_session.commit()

    handler = make_pipeline_run_requested_handler()
    async with session_maker() as handler_session:
        item = await handler_session.get(WorkspacePlanOutboxModel, item_id)
        assert item is not None
        await handler(item, handler_session)
        await handler_session.commit()

    async with session_maker() as inspect_session:
        deployment = (await inspect_session.execute(select(WorkspaceDeploymentModel))).scalar_one()
        assert deployment.provider == DRONE_PROVIDER
        assert deployment.status == "running"
        assert deployment.service_id is not None
        assert deployment.service_id.startswith("ws-workspac-web-")
        assert deployment.service_name == "Web"
        assert deployment.port == 18080
        assert deployment.preview_url == "http://localhost:18080/"
        assert deployment.health_url == "http://localhost:18080/health"
        assert deployment.metadata_json["deployment_status"] == "deployed"

        visible_plan = await SqlPlanRepository(inspect_session).get("pipeline-plan-1")
        assert visible_plan is not None
        visible_node = visible_plan.nodes[PlanNodeId("pipeline-node-1")]
        evidence_refs = visible_node.metadata["pipeline_evidence_refs"]
        assert f"deployment:{deployment.service_id}:running" in evidence_refs
        assert f"preview_url:{deployment.service_id}:http://localhost:18080/" in evidence_refs

    await engine.dispose()


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
    assert task.metadata_json["retry_verification_only"] is True
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
    assert (
        attempt.leader_feedback
        == "durable plan verifier passed code checks; awaiting harness-native pipeline evidence"
    )
    task = await db_session.get(WorkspaceTaskModel, "exec-task-1")
    assert task is not None
    assert task.status == "in_progress"
    assert task.metadata_json["durable_plan_verdict"] == "pipeline_pending"
    assert (
        task.metadata_json["durable_plan_verification_summary"]
        == "durable plan verifier passed code checks; awaiting harness-native pipeline evidence"
    )
    assert task.metadata_json["durable_plan_raw_verification_summary"] == "verified before pipeline"
    assert task.metadata_json["last_attempt_status"] == "awaiting_pipeline"
    assert task.metadata_json["pipeline_candidate_commit_ref"] == "abc1234"


@pytest.mark.asyncio
async def test_supervisor_accept_decision_overrides_pipeline_pending_projection(
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
                "durable_plan_verdict": "pipeline_pending",
                "last_attempt_status": "awaiting_pipeline",
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
            candidate_artifacts_json=[
                "src/swarm/service.ts",
                "commit_ref:abc1234",
                "git_diff_summary:implemented swarm service",
            ],
            candidate_verifications_json=[
                "test_run:swarm 36/36 tests passed",
                "tsc:swarm-zero-errors",
            ],
            leader_feedback=(
                "durable plan verifier passed code checks; awaiting harness-native pipeline evidence"
            ),
            adjudication_reason="pipeline_gate_pending",
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

    await _project_supervisor_decision_to_workspace_task(
        db_session,
        node,
        {
            "action": "accept_node",
            "rationale": "agent supervisor accepted current attempt",
            "confidence": 0.95,
        },
    )
    await db_session.flush()

    attempt = await db_session.get(WorkspaceTaskSessionAttemptModel, "attempt-a")
    assert attempt is not None
    assert attempt.status == "accepted"
    assert attempt.completed_at is not None
    assert attempt.leader_feedback == "agent supervisor accepted current attempt"
    assert attempt.adjudication_reason == "supervisor_decision_accept_node"
    task = await db_session.get(WorkspaceTaskModel, "exec-task-1")
    assert task is not None
    assert task.status == "done"
    assert task.metadata_json["durable_plan_verdict"] == "accepted"
    assert task.metadata_json["last_attempt_status"] == "accepted"
    assert task.metadata_json["handoff_package"]["git_head"] == "abc1234"
    assert task.metadata_json["handoff_package"]["test_commands"] == ["swarm 36/36 tests passed"]
    assert task.metadata_json[PENDING_LEADER_ADJUDICATION] is False


@pytest.mark.asyncio
async def test_supervisor_dispose_decision_projects_task_without_accepting_attempt(
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
            blocker_reason="Maximum steps (80) exceeded",
            metadata_json={
                AUTONOMY_SCHEMA_VERSION_KEY: 1,
                TASK_ROLE: "execution_task",
                WORKSPACE_PLAN_ID: "worker-plan-1",
                WORKSPACE_PLAN_NODE_ID: "node-a",
                ROOT_GOAL_TASK_ID: "root-task-1",
                CURRENT_ATTEMPT_ID: "attempt-a",
                PENDING_LEADER_ADJUDICATION: False,
                "durable_plan_verdict": "replan_requested",
                "last_attempt_status": "rejected",
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
            status="rejected",
            conversation_id="conversation-a",
            worker_agent_id="worker-agent",
            leader_agent_id=BUILTIN_SISYPHUS_ID,
            candidate_summary="Maximum steps (80) exceeded",
            leader_feedback="verification failed",
            adjudication_reason="verification_failed",
        )
    )
    await db_session.flush()
    node = PlanNode(
        id="node-a",
        plan_id="worker-plan-1",
        parent_id=PlanNodeId("goal-a"),
        kind=PlanNodeKind.TASK,
        title="Stale verification",
        workspace_task_id="exec-task-1",
        current_attempt_id="attempt-a",
    )

    changed = await _project_supervisor_decision_to_workspace_task(
        db_session,
        node,
        {
            "action": "dispose_node",
            "rationale": "stale node structurally superseded by completed sibling",
            "confidence": 0.95,
            "event_payload": {
                "disposed_node_id": "node-a",
                "superseded_by_task_id": "sibling-task",
            },
        },
    )
    await db_session.flush()

    assert changed is True
    attempt = await db_session.get(WorkspaceTaskSessionAttemptModel, "attempt-a")
    assert attempt is not None
    assert attempt.status == "rejected"
    assert attempt.adjudication_reason == "verification_failed"
    task = await db_session.get(WorkspaceTaskModel, "exec-task-1")
    assert task is not None
    assert task.status == "done"
    assert task.blocker_reason is None
    assert task.metadata_json["durable_plan_verdict"] == "disposed"
    assert task.metadata_json["durable_plan_disposition"] == "supervisor_agent_disposed_node"
    assert task.metadata_json["superseded_by_task_id"] == "sibling-task"
    assert task.metadata_json["last_attempt_status"] == "disposed"
    assert task.metadata_json[PENDING_LEADER_ADJUDICATION] is False


@pytest.mark.asyncio
async def test_pipeline_missing_evidence_judge_keeps_attempt_pending_pipeline(
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
            candidate_summary="Committed deploy changes.",
            candidate_verifications_json=["commit_ref:def5678", "test_run:npm test"],
        )
    )
    await db_session.flush()
    node = PlanNode(
        id="node-a",
        plan_id="worker-plan-1",
        parent_id=PlanNodeId("goal-a"),
        kind=PlanNodeKind.TASK,
        title="Deploy feature",
        workspace_task_id="exec-task-1",
        current_attempt_id="attempt-a",
        metadata={"pipeline_required": True},
    )

    await _project_verification_to_workspace_task(
        db_session,
        node,
        {
            "attempt_id": "attempt-a",
            "passed": False,
            "hard_fail": False,
            "summary": (
                "verification failed: missing harness-native CI pipeline evidence; "
                "judge verdict=needs_rework; next_action_kind=retry_same_node"
            ),
            "results": [
                {
                    "kind": "ci_pipeline",
                    "name": None,
                    "required": True,
                    "passed": False,
                    "confidence": 0.7,
                    "message": "missing harness-native CI pipeline evidence",
                    "evidence": [{"kind": "artifact", "ref": "commit_ref:def5678"}],
                },
                {
                    "kind": "custom",
                    "name": "workspace_verification_judge",
                    "judge_verdict": "needs_rework",
                    "next_action_kind": "retry_same_node",
                    "required_next_action": "request pipeline and wait",
                    "required": True,
                    "passed": False,
                    "confidence": 0.7,
                    "message": (
                        "judge verdict=needs_rework; missing harness-native CI pipeline "
                        "evidence; next_action_kind=retry_same_node"
                    ),
                    "evidence": [],
                },
            ],
        },
    )
    await db_session.flush()

    attempt = await db_session.get(WorkspaceTaskSessionAttemptModel, "attempt-a")
    assert attempt is not None
    assert attempt.status == "awaiting_leader_adjudication"
    assert attempt.completed_at is None
    assert attempt.adjudication_reason == "pipeline_gate_pending"
    assert (
        attempt.leader_feedback
        == "durable plan verifier passed code checks; awaiting harness-native pipeline evidence"
    )
    task = await db_session.get(WorkspaceTaskModel, "exec-task-1")
    assert task is not None
    assert task.status == "in_progress"
    assert task.metadata_json["durable_plan_verdict"] == "pipeline_pending"
    assert (
        task.metadata_json["durable_plan_verification_summary"]
        == "durable plan verifier passed code checks; awaiting harness-native pipeline evidence"
    )
    assert "verification failed" in task.metadata_json["durable_plan_raw_verification_summary"]
    assert task.metadata_json["last_attempt_status"] == "awaiting_pipeline"
    assert task.metadata_json["pipeline_candidate_commit_ref"] == "def5678"


@pytest.mark.asyncio
async def test_pipeline_missing_evidence_retry_infra_keeps_attempt_pending_pipeline(
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
            candidate_summary="Committed deploy changes.",
            candidate_verifications_json=["commit_ref:ghi9012", "test_run:npm test"],
        )
    )
    await db_session.flush()
    node = PlanNode(
        id="node-a",
        plan_id="worker-plan-1",
        parent_id=PlanNodeId("goal-a"),
        kind=PlanNodeKind.TASK,
        title="Deploy feature",
        workspace_task_id="exec-task-1",
        current_attempt_id="attempt-a",
        metadata={"pipeline_required": True},
    )

    await _project_verification_to_workspace_task(
        db_session,
        node,
        {
            "attempt_id": "attempt-a",
            "passed": False,
            "hard_fail": False,
            "summary": (
                "verification failed: missing harness-native CI pipeline evidence; "
                "judge verdict=retry_infrastructure; next_action_kind=retry_same_node"
            ),
            "results": [
                {
                    "kind": "ci_pipeline",
                    "name": None,
                    "required": True,
                    "passed": False,
                    "confidence": 0.7,
                    "message": "missing harness-native CI pipeline evidence",
                    "evidence": [{"kind": "artifact", "ref": "commit_ref:ghi9012"}],
                },
                {
                    "kind": "custom",
                    "name": "retryable_infrastructure_failure",
                    "judge_verdict": "retry_infrastructure",
                    "next_action_kind": "retry_same_node",
                    "required_next_action": "request pipeline and wait",
                    "required": True,
                    "passed": False,
                    "confidence": 0.7,
                    "message": (
                        "judge verdict=retry_infrastructure; missing harness-native CI "
                        "pipeline evidence; next_action_kind=retry_same_node"
                    ),
                    "evidence": [],
                },
            ],
        },
    )
    await db_session.flush()

    attempt = await db_session.get(WorkspaceTaskSessionAttemptModel, "attempt-a")
    assert attempt is not None
    assert attempt.status == "awaiting_leader_adjudication"
    assert attempt.completed_at is None
    assert attempt.adjudication_reason == "pipeline_gate_pending"
    assert (
        attempt.leader_feedback
        == "durable plan verifier passed code checks; awaiting harness-native pipeline evidence"
    )
    task = await db_session.get(WorkspaceTaskModel, "exec-task-1")
    assert task is not None
    assert task.status == "in_progress"
    assert task.metadata_json["durable_plan_verdict"] == "pipeline_pending"
    assert (
        task.metadata_json["durable_plan_verification_summary"]
        == "durable plan verifier passed code checks; awaiting harness-native pipeline evidence"
    )
    assert "verification failed" in task.metadata_json["durable_plan_raw_verification_summary"]
    assert task.metadata_json["last_attempt_status"] == "awaiting_pipeline"
    assert task.metadata_json["pipeline_candidate_commit_ref"] == "ghi9012"


@pytest.mark.asyncio
async def test_pipeline_missing_evidence_judge_timeout_stays_pending_pipeline(
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
            candidate_summary="Committed deploy changes.",
            candidate_verifications_json=["commit_ref:jkl3456", "test_run:npm test"],
        )
    )
    await db_session.flush()
    node = PlanNode(
        id="node-a",
        plan_id="worker-plan-1",
        parent_id=PlanNodeId("goal-a"),
        kind=PlanNodeKind.TASK,
        title="Deploy feature",
        workspace_task_id="exec-task-1",
        current_attempt_id="attempt-a",
        metadata={"pipeline_required": True},
    )

    await _project_verification_to_workspace_task(
        db_session,
        node,
        {
            "attempt_id": "attempt-a",
            "passed": False,
            "hard_fail": False,
            "summary": (
                "verification failed: missing harness-native CI pipeline evidence; "
                "workspace verification judge timed out after 180s"
            ),
            "results": [
                {
                    "kind": "ci_pipeline",
                    "name": None,
                    "required": True,
                    "passed": False,
                    "confidence": 0.7,
                    "message": "missing harness-native CI pipeline evidence",
                    "evidence": [{"kind": "artifact", "ref": "commit_ref:jkl3456"}],
                },
                {
                    "kind": "custom",
                    "name": "retryable_infrastructure_failure",
                    "judge_verdict": "retry_infrastructure",
                    "next_action_kind": "retry_same_node",
                    "failed_criteria": ["workspace_verification_judge"],
                    "required_next_action": "retry verification judge",
                    "required": True,
                    "passed": False,
                    "confidence": 0.5,
                    "message": (
                        "judge verdict=retry_infrastructure; workspace verification judge "
                        "timed out after 180s; next_action=retry verification judge; "
                        "next_action_kind=retry_same_node; failed=workspace_verification_judge; "
                        "feedback_targets=runtime"
                    ),
                    "evidence": [],
                },
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
    assert task.metadata_json["pipeline_candidate_commit_ref"] == "jkl3456"


@pytest.mark.asyncio
async def test_pending_pipeline_hard_fail_projection_stays_pipeline_pending(
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
                "last_attempt_status": "awaiting_pipeline",
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
            candidate_summary="Committed deploy changes.",
            candidate_verifications_json=["commit_ref:293a833", "test_run:npm test"],
        )
    )
    await db_session.flush()
    node = PlanNode(
        id="node-a",
        plan_id="worker-plan-1",
        parent_id=PlanNodeId("goal-a"),
        kind=PlanNodeKind.TASK,
        title="Deploy feature",
        workspace_task_id="exec-task-1",
        current_attempt_id="attempt-a",
        metadata={
            "pipeline_required": True,
            "pipeline_gate_status": "requested",
            "pipeline_status": "requested",
        },
    )

    await _project_verification_to_workspace_task(
        db_session,
        node,
        {
            "attempt_id": "attempt-a",
            "passed": False,
            "hard_fail": True,
            "summary": (
                "verification failed: missing harness-native CI pipeline evidence "
                "for current commit 293a833"
            ),
            "results": [
                {
                    "kind": "ci_pipeline",
                    "required": True,
                    "passed": False,
                    "confidence": 1.0,
                    "message": (
                        "missing harness-native CI pipeline evidence for current commit 293a833"
                    ),
                    "evidence": [{"kind": "artifact", "ref": "commit_ref:293a833"}],
                },
                {
                    "kind": "custom",
                    "name": "workspace_verification_judge",
                    "judge_verdict": "blocked_human_required",
                    "next_action_kind": "human_required",
                    "required_next_action": "platform harness must trigger Drone",
                    "feedback_items": [
                        {
                            "target_layer": "runtime",
                            "feedback_kind": "runtime_infra_failure",
                            "recommended_action": "escalate_human",
                            "summary": (
                                "Pipeline trigger blocked until Drone evidence exists for "
                                "commit 293a833."
                            ),
                            "failure_signature": "missing_drone_pipeline_evidence_current_commit",
                            "evidence_refs": ["commit_ref:293a833", "ci_pipeline:missing"],
                        }
                    ],
                    "required": True,
                    "passed": False,
                    "confidence": 0.9,
                    "message": "judge verdict=blocked_human_required; missing pipeline evidence",
                    "evidence": [],
                },
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
    assert task.metadata_json["durable_plan_verdict"] == "pipeline_pending"
    assert task.metadata_json["last_attempt_status"] == "awaiting_pipeline"


@pytest.mark.asyncio
async def test_worker_product_code_feedback_projection_is_not_pipeline_pending(
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
                "last_attempt_status": "awaiting_pipeline",
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
            candidate_summary="Committed deploy changes.",
            candidate_verifications_json=["commit_ref:0896747", "test_run:npm test"],
        )
    )
    await db_session.flush()
    node = PlanNode(
        id="node-a",
        plan_id="worker-plan-1",
        parent_id=PlanNodeId("goal-a"),
        kind=PlanNodeKind.TASK,
        title="Deploy feature",
        workspace_task_id="exec-task-1",
        current_attempt_id="attempt-a",
        metadata={
            "pipeline_required": True,
            "pipeline_gate_status": "running",
            "pipeline_status": "running",
        },
    )

    await _project_verification_to_workspace_task(
        db_session,
        node,
        {
            "attempt_id": "attempt-a",
            "passed": False,
            "hard_fail": True,
            "summary": "verification failed: Drone deploy port conflict requires worker retry",
            "results": [
                {
                    "kind": "ci_pipeline",
                    "required": True,
                    "passed": False,
                    "confidence": 1.0,
                    "message": "Drone deploy failed: bind for 0.0.0.0:3001 failed",
                    "evidence": [{"kind": "artifact", "ref": "commit_ref:0896747"}],
                },
                {
                    "kind": "custom",
                    "name": "workspace_verification_judge",
                    "judge_verdict": "needs_rework",
                    "next_action_kind": "retry_same_node",
                    "required_next_action": "worker must fix compose publishing",
                    "feedback_items": [
                        {
                            "target_layer": "worker",
                            "feedback_kind": "product_code_failure",
                            "recommended_action": "retry_worker",
                            "summary": (
                                "Drone CI/CD evidence was captured after publish, but the "
                                "worker must fix the deploy port binding."
                            ),
                            "failure_signature": "ci_pipeline_deploy_port_conflict",
                            "evidence_refs": ["commit_ref:0896747", "ci_pipeline:failed"],
                        }
                    ],
                    "required": True,
                    "passed": False,
                    "confidence": 0.9,
                    "message": "judge verdict=needs_rework; worker retry required",
                    "evidence": [],
                },
            ],
        },
    )
    await db_session.flush()

    attempt = await db_session.get(WorkspaceTaskSessionAttemptModel, "attempt-a")
    assert attempt is not None
    assert attempt.status == WorkspaceTaskSessionAttemptStatus.BLOCKED.value
    assert attempt.adjudication_reason != "pipeline_gate_pending"
    task = await db_session.get(WorkspaceTaskModel, "exec-task-1")
    assert task is not None
    assert task.status == "blocked"
    assert task.metadata_json["durable_plan_verdict"] == "blocked"
    assert task.metadata_json["last_attempt_status"] == "blocked"


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
        batch_size=1,
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
        batch_size=1,
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
        ["sh", "-lc", command],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert (sandbox_code_root / ".git").is_dir()
    assert (worktree_path / ".git").exists()
    assert "git_head=" in result.stdout


def test_worktree_setup_command_falls_back_when_base_ref_unusable(tmp_path: Path) -> None:
    sandbox_code_root = tmp_path / "repo"
    worktree_path = tmp_path / ".memstack" / "worktrees" / "attempt-1"

    command = _worktree_setup_command(
        sandbox_code_root=str(sandbox_code_root),
        worktree_path=str(worktree_path),
        branch_name="workspace/node-1-attempt-1",
        base_ref="missing-ref",
    )

    result = subprocess.run(
        ["bash", "-lc", command],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "base_ref_unusable=missing-ref" in result.stdout
    assert (worktree_path / ".git").exists()
    assert "git_head=" in result.stdout


def test_worktree_setup_command_falls_back_from_sparse_base_ref(tmp_path: Path) -> None:
    sandbox_code_root = tmp_path / "repo"
    worktree_path = tmp_path / ".memstack" / "worktrees" / "attempt-1"

    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=sandbox_code_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip()

    sandbox_code_root.mkdir()
    git("init", "-b", "master")
    git("config", "user.email", "worker@example.com")
    git("config", "user.name", "Worker")
    (sandbox_code_root / "OAS-INS-OAUTH.md").write_text("audit\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "audit")
    sparse_ref = git("rev-parse", "HEAD")

    git("checkout", "--orphan", "github/main")
    git("rm", "-rf", ".")
    (sandbox_code_root / "backend").mkdir()
    (sandbox_code_root / "frontend").mkdir()
    (sandbox_code_root / "backend" / "package.json").write_text("{}\n", encoding="utf-8")
    (sandbox_code_root / "frontend" / "package.json").write_text("{}\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "project baseline")

    command = _worktree_setup_command(
        sandbox_code_root=str(sandbox_code_root),
        worktree_path=str(worktree_path),
        branch_name="workspace/node-1-attempt-1",
        base_ref=sparse_ref,
    )

    result = subprocess.run(
        ["bash", "-lc", command],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert f"base_ref_sparse={sparse_ref}" in result.stdout
    assert "fallback_base_ref=github/main" in result.stdout
    assert (worktree_path / "backend" / "package.json").exists()
    assert (worktree_path / "frontend" / "package.json").exists()


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

    assert len(command) < 1500
    assert "protected_worktree_names" not in command
    assert "stop_stale_pid" not in command
    assert 'git worktree add -B "$B" "$W" "$R"' in command


def test_worktree_integration_command_blocks_dirty_main_checkout() -> None:
    command = _worktree_integration_command(
        sandbox_code_root="/workspace/my-evo",
        worktree_path="/workspace/my-evo/../.memstack/worktrees/attempt-1",
        commit_ref="abc1234",
    )

    assert 'git merge-base --is-ancestor "$RESOLVED_COMMIT" HEAD' in command
    assert 'dirty="$(git status --porcelain)"' in command
    assert 'echo "status=blocked_dirty_main"' in command
    assert "dirty_signature=%s" in command
    assert "dirty_generated_only=%s" in command
    assert "frontend/tests/screenshots/*" in command
    assert 'echo "generated_dirty_cleaned=true"' in command
    assert "git hash-object --stdin" in command
    assert 'git merge --no-edit "$RESOLVED_COMMIT"' in command
    assert "refusing to merge unrelated histories" in command
    assert 'git merge --no-edit --allow-unrelated-histories -X theirs "$RESOLVED_COMMIT"' in command
    assert 'echo "reason=merge_failed_aborted"' in command
    assert "git merge --abort" in command


def test_worktree_integration_command_merges_unrelated_history_with_attempt_preference(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    attempt = tmp_path / "attempt-worktree"
    repo.mkdir()

    def git(cwd: Path, *args: str, check: bool = True) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=check,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip()

    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "worker@example.com")
    git(repo, "config", "user.name", "Worker")
    (repo / "shared.txt").write_text("main\n", encoding="utf-8")
    (repo / "main-only.txt").write_text("main only\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "main")

    git(repo, "checkout", "--orphan", "attempt")
    for path in repo.iterdir():
        if path.name == ".git":
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    (repo / "shared.txt").write_text("attempt\n", encoding="utf-8")
    (repo / "attempt-only.txt").write_text("attempt only\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "attempt")
    commit_ref = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "main")
    git(repo, "worktree", "add", str(attempt), "attempt")

    command = _worktree_integration_command(
        sandbox_code_root=str(repo),
        worktree_path=str(attempt),
        commit_ref=commit_ref,
    )
    result = subprocess.run(
        ["bash", "-lc", command],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "unrelated_history_retry=true" in result.stdout
    assert "status=merged" in result.stdout
    assert (repo / "shared.txt").read_text(encoding="utf-8") == "attempt\n"
    assert (repo / "attempt-only.txt").read_text(encoding="utf-8") == "attempt only\n"
    assert (repo / "main-only.txt").read_text(encoding="utf-8") == "main only\n"
    assert git(repo, "status", "--short") == ""


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


def test_worktree_integration_command_commits_staged_bootstrap_before_merge(
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

    git(repo, "init", "-b", "master")
    git(repo, "config", "user.email", "worker@example.com")
    git(repo, "config", "user.name", "Worker")
    (repo / "frontend").mkdir()
    (repo / "frontend/.gitkeep").write_text("", encoding="utf-8")
    git(repo, "add", "frontend/.gitkeep")
    git(repo, "commit", "-m", "init")

    git(repo, "checkout", "--orphan", "attempt")
    (repo / "src").mkdir()
    (repo / "src/app.ts").write_text("candidate\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "candidate")
    commit_ref = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "master")
    git(repo, "worktree", "add", str(worktree_path), "attempt")

    (repo / "README.md").write_text("bootstrap baseline\n", encoding="utf-8")
    git(repo, "add", "README.md")
    (repo / "frontend/e2e-test-output.txt").write_text("transient output\n", encoding="utf-8")

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
    assert "baseline_dirty_committed=true" in result.stdout
    assert "unrelated_history_retry=true" in result.stdout
    assert "status=merged" in result.stdout
    assert (repo / "README.md").read_text(encoding="utf-8") == "bootstrap baseline\n"
    assert (repo / "src/app.ts").read_text(encoding="utf-8") == "candidate\n"
    assert not (repo / "frontend/e2e-test-output.txt").exists()
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


def test_drone_contract_keeps_required_auto_deploy_before_deploy_phase() -> None:
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

    assert scoped.deploy is contract.deploy
    assert "deploy_suppressed_for_phase" not in scoped.provider_config


def test_drone_contract_suppresses_optional_deploy_before_deploy_phase() -> None:
    contract = PipelineContractSpec(
        provider=DRONE_PROVIDER,
        deploy=PipelineDeploySpec(enabled=True, mode="docker", required=False),
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


def test_drone_contract_enables_deploy_awareness_for_deploy_phase() -> None:
    contract = PipelineContractSpec(
        provider=DRONE_PROVIDER,
        auto_deploy=False,
        deploy=PipelineDeploySpec(enabled=False, mode="docker", required=True),
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

    assert scoped.deploy is not None
    assert scoped.deploy.enabled is True
    assert scoped.deploy.mode == "docker"
    assert "deploy_suppressed_for_phase" not in scoped.provider_config


def test_running_pipeline_run_is_not_reflected_as_terminal_completion() -> None:
    contract = PipelineContractSpec(provider=DRONE_PROVIDER)
    node = PlanNode(
        id="node-deploy",
        plan_id="plan-1",
        kind=PlanNodeKind.TASK,
        parent_id=PlanNodeId("root-node"),
        title="Deploy feature",
        metadata={"pipeline_status": "running"},
    )
    run = WorkspacePipelineRunModel(
        id="run-1",
        contract_id="contract-1",
        workspace_id="workspace-1",
        plan_id="plan-1",
        node_id="node-deploy",
        attempt_id="attempt-1",
        commit_ref="9b3e7cc",
        provider=DRONE_PROVIDER,
        status="running",
        metadata_json={"source_publish_source_commit_ref": "9b3e7cc"},
    )

    assert not outbox_handlers._can_reflect_existing_pipeline_run(
        run=run,
        contract=contract,
        node=node,
    )


def test_pipeline_run_commit_match_uses_source_commit_metadata() -> None:
    run = WorkspacePipelineRunModel(
        id="run-1",
        contract_id="contract-1",
        workspace_id="workspace-1",
        plan_id="plan-1",
        node_id="node-deploy",
        attempt_id="attempt-1",
        commit_ref="published123",
        provider=DRONE_PROVIDER,
        status="running",
        metadata_json={"source_publish_source_commit_ref": "be55379"},
    )

    assert outbox_handlers._pipeline_run_matches_requested_commit(
        run,
        requested_source_commit_ref="be55379",
    )
    assert not outbox_handlers._pipeline_run_matches_requested_commit(
        run,
        requested_source_commit_ref="9b3e7cc",
    )


@pytest.mark.asyncio
async def test_supervisor_tick_recovers_orphaned_running_pipeline_request(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_only(db_session)
    plan = Plan(
        id="pipeline-plan-1",
        workspace_id="workspace-1",
        goal_id=PlanNodeId("pipeline-goal-1"),
        status=PlanStatus.ACTIVE,
    )
    plan.add_node(
        PlanNode(
            id="pipeline-goal-1",
            plan_id=plan.id,
            parent_id=None,
            kind=PlanNodeKind.GOAL,
            title="Ship pipeline",
        )
    )
    plan.add_node(
        PlanNode(
            id="pipeline-node-1",
            plan_id=plan.id,
            parent_id=plan.goal_id,
            kind=PlanNodeKind.TASK,
            title="Run Drone",
            intent=TaskIntent.IN_PROGRESS,
            execution=TaskExecution.IDLE,
            current_attempt_id="attempt-pipeline-1",
            metadata={"pipeline_status": "running", "pipeline_gate_status": "running"},
        )
    )
    await SqlPlanRepository(db_session).save(plan)
    pipeline_repo = SqlWorkspacePipelineRepository(db_session)
    contract = await pipeline_repo.ensure_contract(
        workspace_id="workspace-1",
        plan_id=plan.id,
        provider=DRONE_PROVIDER,
        code_root="/workspace/my-evo",
        commands=[],
    )
    run = await pipeline_repo.create_run(
        contract_id=contract.id,
        workspace_id="workspace-1",
        plan_id=plan.id,
        node_id="pipeline-node-1",
        attempt_id="attempt-pipeline-1",
        commit_ref="9b3e7cc",
        provider=DRONE_PROVIDER,
        metadata={"source_publish_source_commit_ref": "9b3e7cc"},
    )

    changed = await outbox_handlers._recover_orphaned_running_pipeline_requests_after_tick(
        session=db_session,
        plan_id=plan.id,
        workspace_id="workspace-1",
    )

    assert changed
    outbox_items = (
        (
            await db_session.execute(
                select(WorkspacePlanOutboxModel).where(
                    WorkspacePlanOutboxModel.event_type == "pipeline_run_requested"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(outbox_items) == 1
    assert outbox_items[0].payload_json["attempt_id"] == "attempt-pipeline-1"
    assert outbox_items[0].payload_json["pipeline_run_id"] == run.id

    changed_again = await outbox_handlers._recover_orphaned_running_pipeline_requests_after_tick(
        session=db_session,
        plan_id=plan.id,
        workspace_id="workspace-1",
    )

    assert not changed_again


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


def test_pipeline_commit_ref_prefers_summary_commit_when_artifacts_include_prior_commits() -> None:
    node = PlanNode(
        id="node-deploy",
        plan_id="plan-1",
        kind=PlanNodeKind.TASK,
        parent_id=PlanNodeId("root-node"),
        title="Deploy feature",
        current_attempt_id="attempt-current",
        execution=TaskExecution.REPORTED,
    )
    attempt = WorkspaceTaskSessionAttemptModel(
        id="attempt-current",
        workspace_task_id="task-1",
        root_goal_task_id="root-task-1",
        workspace_id="workspace-1",
        attempt_number=25,
        status="awaiting_leader_adjudication",
        conversation_id="conversation-current",
        worker_agent_id="worker-agent",
        leader_agent_id=BUILTIN_SISYPHUS_ID,
        candidate_summary=(
            "Fixed Drone deploy stage port conflict. Platform harness must trigger "
            "Drone pipeline on s1366560/my-evo at commit be55379."
        ),
        candidate_artifacts_json=[
            "docker-compose.ci.yml",
            ".drone.yml",
            "commit_ref:be55379",
            "commit_ref:9b3e7cc",
        ],
        candidate_verifications_json=["worker_report:completed"],
    )

    assert outbox_handlers._pipeline_commit_ref(node, current_attempt=attempt) == "be55379"


def test_pipeline_commit_ref_prefers_clean_worktree_commit_over_later_fallback_ref() -> None:
    node = PlanNode(
        id="node-deploy",
        plan_id="plan-1",
        kind=PlanNodeKind.TASK,
        parent_id=PlanNodeId("root-node"),
        title="Deploy feature",
        current_attempt_id="attempt-current",
        execution=TaskExecution.REPORTED,
    )
    attempt = WorkspaceTaskSessionAttemptModel(
        id="attempt-current",
        workspace_task_id="task-1",
        root_goal_task_id="root-task-1",
        workspace_id="workspace-1",
        attempt_number=35,
        status="awaiting_leader_adjudication",
        conversation_id="conversation-current",
        worker_agent_id="worker-agent",
        leader_agent_id=BUILTIN_SISYPHUS_ID,
        candidate_summary=(
            "The worktree is clean at commit 42f842d. The platform harness must publish "
            "42f842d (or 60599e4 if only the fix commit is needed) and re-trigger Drone."
        ),
        candidate_artifacts_json=[
            "commit_ref:42f842d539abe7a6fb453a2241a897db4912d407",
            "commit_ref:60599e43701142335ec8b5aba90fc95ddaddf5d2",
        ],
        candidate_verifications_json=[
            "preflight:git-status",
            "commit_ref:42f842d539abe7a6fb453a2241a897db4912d407",
        ],
    )

    assert (
        outbox_handlers._pipeline_commit_ref(node, current_attempt=attempt)
        == "42f842d539abe7a6fb453a2241a897db4912d407"
    )


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


def test_pipeline_commit_ref_prefers_newer_verification_commit_over_stale_artifact() -> None:
    node = PlanNode(
        id="node-deploy",
        plan_id="plan-1",
        kind=PlanNodeKind.TASK,
        parent_id=PlanNodeId("root-node"),
        title="Deploy feature",
        current_attempt_id="attempt-current",
        execution=TaskExecution.REPORTED,
        metadata={"verified_commit_ref": "stale000"},
    )
    attempt = WorkspaceTaskSessionAttemptModel(
        id="attempt-current",
        workspace_task_id="task-1",
        root_goal_task_id="root-task-1",
        workspace_id="workspace-1",
        attempt_number=5,
        status="awaiting_leader_adjudication",
        conversation_id="conversation-current",
        worker_agent_id="worker-agent",
        leader_agent_id=BUILTIN_SISYPHUS_ID,
        candidate_summary="done",
        candidate_artifacts_json=[
            "docker-compose.override.yml",
            "commit_ref:63285ad",
        ],
        candidate_verifications_json=[
            "preflight:git-status",
            "commit_ref:63285ad",
            "commit_ref:293a833",
            "worker_report:completed",
        ],
    )

    assert outbox_handlers._pipeline_commit_ref(node, current_attempt=attempt) == "293a833"


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


def test_pipeline_run_commit_ref_does_not_reuse_stale_node_ref_without_attempt() -> None:
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
            commit_ref="stale123",
        ),
        metadata={"evidence_refs": ["commit_ref:stale123"]},
    )
    contract = PipelineContractSpec(
        provider=DRONE_PROVIDER, provider_config={"repo": "octo/my-evo"}
    )

    assert (
        outbox_handlers._pipeline_run_commit_ref(
            contract,
            node=node,
            current_attempt=None,
            attempt_id=None,
        )
        is None
    )
    assert (
        outbox_handlers._pipeline_run_commit_ref(
            replace(contract, provider_config={"repo": "octo/my-evo", "commit": "remote456"}),
            node=node,
            current_attempt=None,
            attempt_id=None,
        )
        == "remote456"
    )


@pytest.mark.asyncio
async def test_prepare_drone_source_ref_skips_publish_without_attempt_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_publish(**_: object) -> dict[str, object]:
        pytest.fail("source publish should not run without an attempt_id")

    monkeypatch.setattr(outbox_handlers, "_publish_git_ref_to_source_control", fail_publish)
    workspace = Workspace(
        id="workspace-1",
        tenant_id="tenant-1",
        project_id="project-1",
        name="workspace",
        created_by="user-1",
        metadata={
            "source_control": {
                "repo": "octo/my-evo",
                "default_branch": "main",
                "auth_token_env": "GITHUB_TOKEN",
            }
        },
    )
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
            commit_ref="stale123",
        ),
    )
    contract = PipelineContractSpec(
        provider=DRONE_PROVIDER, provider_config={"repo": "octo/my-evo"}
    )

    scoped_contract, metadata, result = await outbox_handlers._prepare_drone_source_ref(
        workspace=workspace,
        workspace_metadata=workspace.metadata,
        root_metadata={},
        node=node,
        attempt_id=None,
        current_attempt=None,
        contract=contract,
    )

    assert result is None
    assert scoped_contract.provider_config["branch"] == "main"
    assert "commit" not in scoped_contract.provider_config
    assert metadata["source_publish_status"] == "skipped"
    assert metadata["source_publish_reason"] == "missing attempt_id; using remote branch head"
    assert metadata["source_publish_branch"] == "main"


@pytest.mark.asyncio
async def test_pipeline_repair_source_commit_ref_uses_source_verification_attempt(
    db_session: AsyncSession,
) -> None:
    db_session.add(
        WorkspaceTaskSessionAttemptModel(
            id="attempt-source",
            workspace_task_id="task-source",
            root_goal_task_id="root-task",
            workspace_id="workspace-1",
            attempt_number=1,
            status=WorkspaceTaskSessionAttemptStatus.REJECTED.value,
            candidate_artifacts_json=["commit_ref:fa6a7d1b635fc14f6115da32f131a29bdb70f7df"],
            candidate_verifications_json=["commit_ref:fa6a7d1", "worker_report:completed"],
        )
    )
    await db_session.flush()
    plan = Plan(
        id="plan-1",
        workspace_id="workspace-1",
        goal_id=PlanNodeId("root-node"),
        status=PlanStatus.ACTIVE,
    )
    plan.add_node(
        PlanNode(
            id="root-node",
            plan_id=plan.id,
            kind=PlanNodeKind.GOAL,
            title="Root",
        )
    )
    plan.add_node(
        PlanNode(
            id="node-original",
            plan_id=plan.id,
            kind=PlanNodeKind.TASK,
            parent_id=plan.goal_id,
            title="Original deploy",
            metadata={"source_verification_attempt_id": "attempt-source"},
        )
    )
    plan.add_node(
        PlanNode(
            id="node-repair",
            plan_id=plan.id,
            kind=PlanNodeKind.TASK,
            parent_id=plan.goal_id,
            title="Repair deploy",
            current_attempt_id="attempt-repair",
            metadata={"repair_for_node_id": "node-original"},
        )
    )

    commit_ref = await outbox_handlers._pipeline_repair_source_commit_ref(
        session=db_session,
        plan=plan,
        node=plan.nodes[PlanNodeId("node-repair")],
    )

    assert commit_ref == "fa6a7d1"


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
async def test_publish_git_ref_to_source_control_retries_temp_push_when_remote_advances(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    (repo / "local-note.txt").write_text("keep dirty\n", encoding="utf-8")
    git(repo, "add", ".drone.yml")
    git(repo, "commit", "-m", "base")
    git(tmp_path, "init", "--bare", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "origin", "main")

    git(repo, "checkout", "-b", "repair")
    (repo / ".drone.yml").write_text("pipeline: repair\n", encoding="utf-8")
    git(repo, "commit", "-am", "repair")
    repair_commit = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "main")
    (repo / "local-note.txt").write_text("dirty local note\n", encoding="utf-8")

    git(tmp_path, "clone", str(remote), str(remote_clone))
    git(remote_clone, "config", "user.email", "remote@example.com")
    git(remote_clone, "config", "user.name", "Remote")

    original_run_git_command = outbox_handlers._run_git_command
    remote_advanced = False

    async def run_git_command_with_remote_race(
        cwd: Path,
        args: tuple[str, ...],
        *,
        env: Mapping[str, str],
        timeout: int = 60,
    ) -> dict[str, str]:
        nonlocal remote_advanced
        if args == ("push", str(remote), "HEAD:refs/heads/main") and not remote_advanced:
            remote_advanced = True
            (remote_clone / "remote.txt").write_text("remote advance\n", encoding="utf-8")
            git(remote_clone, "add", "remote.txt")
            git(remote_clone, "commit", "-m", "remote advance during publish")
            git(remote_clone, "push", "origin", "main")
        return await original_run_git_command(cwd, args, env=env, timeout=timeout)

    monkeypatch.setattr(
        outbox_handlers,
        "_run_git_command",
        run_git_command_with_remote_race,
    )

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
        "merged remote branch before publish; retried after non-fast-forward push"
    )
    published_commit = str(publish["published_commit"])
    assert git(remote, "rev-parse", "refs/heads/main") == published_commit
    assert git(remote, "show", "refs/heads/main:.drone.yml") == "pipeline: repair"
    assert git(remote, "show", "refs/heads/main:remote.txt") == "remote advance"
    git(remote, "merge-base", "--is-ancestor", repair_commit, "refs/heads/main")
    assert git(repo, "status", "--short") == "?? local-note.txt"


@pytest.mark.asyncio
async def test_merge_remote_branch_force_refreshes_publish_tracking_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    async def fake_run_git_command(
        cwd: Path,
        args: tuple[str, ...],
        *,
        env: Mapping[str, str],
        timeout: int = 60,
    ) -> dict[str, str]:
        assert cwd == tmp_path
        assert env == {}
        calls.append(args)
        if args[0] == "fetch":
            return {"exit_code": "0", "stdout": "", "stderr": ""}
        if args == (
            "merge-base",
            "--is-ancestor",
            "refs/remotes/memstack-source-publish/main",
            "HEAD",
        ):
            return {"exit_code": "0", "stdout": "", "stderr": ""}
        return {"exit_code": "1", "stdout": "", "stderr": "unexpected command"}

    monkeypatch.setattr(outbox_handlers, "_run_git_command", fake_run_git_command)

    result = await outbox_handlers._merge_remote_branch_for_publish(
        worktree_path=tmp_path,
        candidate_ref="candidate",
        remote="https://github.com/example/repo.git",
        branch="main",
        env={},
    )

    assert result == {"status": "skipped", "reason": None}
    assert calls[0] == (
        "fetch",
        "--no-tags",
        "https://github.com/example/repo.git",
        "+refs/heads/main:refs/remotes/memstack-source-publish/main",
    )


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
async def test_publish_git_ref_to_source_control_keeps_remote_drift_outside_candidate_paths(
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
    assert publish["reason"] == "merged remote branch before publish"
    assert (
        git(remote, "show", "refs/heads/main:.drone.yml") == "commands:\n"
        "  - docker network rm workspace-deploy 2>/dev/null || true\n"
        "  - docker network create workspace-deploy"
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


def test_unrelated_history_rejection_detector_accepts_localized_git_output() -> None:
    assert outbox_handlers._is_unrelated_history_merge_rejection(
        {"stderr": "致命错误：拒绝合并无关的历史"}
    )


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
    assert _commit_ref_token("abc123") == "abc123"
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
async def test_done_repair_disposition_projects_workspace_task(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_and_plan(db_session)
    original_task_id = "task-repair-disposition-original"
    repair_task_id = "task-repair-disposition-repair"
    repair_attempt_id = "attempt-repair-disposition"
    db_session.add_all(
        [
            WorkspaceTaskModel(
                id=original_task_id,
                workspace_id="workspace-1",
                title="Original task accepted through repair",
                description="Original task whose plan node was accepted by repair evidence.",
                created_by="worker-user-1",
                status="in_progress",
                priority=0,
                metadata_json={
                    AUTONOMY_SCHEMA_VERSION_KEY: 1,
                    ROOT_GOAL_TASK_ID: "root-task-1",
                },
            ),
            WorkspaceTaskModel(
                id=repair_task_id,
                workspace_id="workspace-1",
                title="Repair task",
                description="Repair alternative accepted by the verifier.",
                created_by="worker-user-1",
                status="done",
                priority=0,
                metadata_json={
                    AUTONOMY_SCHEMA_VERSION_KEY: 1,
                    ROOT_GOAL_TASK_ID: "root-task-1",
                },
            ),
            WorkspaceTaskSessionAttemptModel(
                id=repair_attempt_id,
                workspace_task_id=repair_task_id,
                root_goal_task_id="root-task-1",
                workspace_id="workspace-1",
                attempt_number=1,
                status="accepted",
                conversation_id="conversation-repair-disposition",
                worker_agent_id="worker-agent",
                leader_agent_id=BUILTIN_SISYPHUS_ID,
                candidate_summary="Repair alternative completed the original criteria.",
                candidate_artifacts_json=["commit_ref:abc1234", "changed_file:src/example.py"],
                candidate_verifications_json=["test_run:uv run pytest src/tests/unit -q"],
            ),
        ]
    )
    await db_session.flush()

    plan = Plan(
        id="repair-disposition-plan-1",
        workspace_id="workspace-1",
        goal_id=PlanNodeId("repair-disposition-root"),
        status=PlanStatus.ACTIVE,
    )
    plan.add_node(
        PlanNode(
            id="repair-disposition-root",
            plan_id=plan.id,
            parent_id=None,
            kind=PlanNodeKind.GOAL,
            title="Root",
        )
    )
    plan.add_node(
        PlanNode(
            id="original-node",
            plan_id=plan.id,
            parent_id=plan.goal_id,
            kind=PlanNodeKind.TASK,
            title="Original accepted by repair",
            workspace_task_id=original_task_id,
            intent=TaskIntent.DONE,
            execution=TaskExecution.IDLE,
            metadata={
                "last_verification_passed": True,
                "last_verification_summary": "Repair alternative satisfies original task.",
                "verification_feedback_disposition": "accepted_via_repair_alternative",
                "accepted_repair_node_id": "repair-node",
                "accepted_repair_evidence_refs": [
                    "commit_ref:abc1234",
                    "git_diff_summary:1 file changed",
                    "test_run:uv run pytest src/tests/unit -q",
                    "worker_report:completed",
                ],
            },
        )
    )
    plan.add_node(
        PlanNode(
            id="repair-node",
            plan_id=plan.id,
            parent_id=plan.goal_id,
            kind=PlanNodeKind.TASK,
            title="Repair accepted",
            workspace_task_id=repair_task_id,
            intent=TaskIntent.DONE,
            execution=TaskExecution.IDLE,
            current_attempt_id=repair_attempt_id,
            feature_checkpoint=FeatureCheckpoint(
                feature_id="feature-repair-disposition",
                sequence=1,
                title="Repair accepted",
                commit_ref="abc1234",
            ),
            metadata={
                "last_verification_passed": True,
                "last_verification_attempt_id": repair_attempt_id,
                "verification_evidence_refs": [
                    "commit_ref:abc1234",
                    "test_run:uv run pytest src/tests/unit -q",
                    "worker_report:completed",
                ],
            },
        )
    )
    await SqlPlanRepository(db_session).save(plan)

    changed = await outbox_handlers._project_done_idle_disposition_nodes_after_tick(
        session=db_session,
        plan_id=plan.id,
        workspace_id="workspace-1",
    )

    assert changed is True
    db_session.expire_all()
    projected_task = await db_session.get(WorkspaceTaskModel, original_task_id)
    assert projected_task is not None
    assert projected_task.status == "done"
    assert projected_task.completed_at is not None
    assert projected_task.blocker_reason is None
    assert projected_task.metadata_json["durable_plan_verdict"] == "accepted"
    assert projected_task.metadata_json["last_attempt_status"] == "accepted"
    assert projected_task.metadata_json["last_attempt_id"] == repair_attempt_id
    handoff = projected_task.metadata_json["handoff_package"]
    assert handoff["git_head"] == "abc1234"
    assert "uv run pytest src/tests/unit -q" in handoff["test_commands"]

    loaded = await SqlPlanRepository(db_session).get(plan.id)
    assert loaded is not None
    original = loaded.nodes[PlanNodeId("original-node")]
    assert original.metadata["workspace_task_projection_status"] == "done"
    assert original.metadata["workspace_task_projected_at"]


@pytest.mark.asyncio
async def test_done_supervisor_dispose_disposition_projects_workspace_task(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_and_plan(db_session)
    db_session.add(
        WorkspaceTaskModel(
            id="disposed-task",
            workspace_id="workspace-1",
            title="Stale verification",
            description="",
            created_by="worker-user-1",
            status="in_progress",
            priority=0,
            blocker_reason="Maximum steps (80) exceeded",
            metadata_json={
                AUTONOMY_SCHEMA_VERSION_KEY: 1,
                ROOT_GOAL_TASK_ID: "root-task-1",
                WORKSPACE_PLAN_ID: "disposed-plan-1",
                WORKSPACE_PLAN_NODE_ID: "disposed-node",
            },
        )
    )
    db_session.add(
        WorkspaceTaskSessionAttemptModel(
            id="disposed-attempt",
            workspace_task_id="disposed-task",
            root_goal_task_id="root-task-1",
            workspace_id="workspace-1",
            attempt_number=1,
            status=WorkspaceTaskSessionAttemptStatus.REJECTED.value,
            conversation_id="disposed-conversation",
            worker_agent_id="worker-agent",
            leader_agent_id=BUILTIN_SISYPHUS_ID,
            candidate_summary="Maximum steps (80) exceeded",
            adjudication_reason="verification_failed",
        )
    )
    await db_session.flush()

    plan = Plan(
        id="disposed-plan-1",
        workspace_id="workspace-1",
        goal_id=PlanNodeId("disposed-root"),
        status=PlanStatus.ACTIVE,
    )
    plan.add_node(
        PlanNode(
            id="disposed-root",
            plan_id=plan.id,
            parent_id=None,
            kind=PlanNodeKind.GOAL,
            title="Root",
        )
    )
    plan.add_node(
        PlanNode(
            id="disposed-node",
            plan_id=plan.id,
            parent_id=plan.goal_id,
            kind=PlanNodeKind.TASK,
            title="Stale verification",
            workspace_task_id="disposed-task",
            current_attempt_id="disposed-attempt",
            intent=TaskIntent.DONE,
            execution=TaskExecution.IDLE,
            metadata={
                "verified_commit_ref": "stale-commit",
                "verification_feedback_disposition": "supervisor_agent_disposed_node",
                "last_supervisor_decision_rationale": (
                    "stale node structurally superseded by completed sibling"
                ),
                "last_supervisor_decision_event_payload": {
                    "disposed_node_id": "disposed-node",
                    "superseded_by_task_id": "sibling-task",
                },
            },
        )
    )
    await SqlPlanRepository(db_session).save(plan)

    changed = await outbox_handlers._project_done_idle_disposition_nodes_after_tick(
        session=db_session,
        plan_id=plan.id,
        workspace_id="workspace-1",
    )

    assert changed is True
    db_session.expire_all()
    task = await db_session.get(WorkspaceTaskModel, "disposed-task")
    assert task is not None
    assert task.status == "done"
    assert task.blocker_reason is None
    assert task.metadata_json["durable_plan_verdict"] == "disposed"
    assert task.metadata_json["durable_plan_disposition"] == "supervisor_agent_disposed_node"
    assert task.metadata_json["superseded_by_task_id"] == "sibling-task"
    attempt = await db_session.get(WorkspaceTaskSessionAttemptModel, "disposed-attempt")
    assert attempt is not None
    assert attempt.status == WorkspaceTaskSessionAttemptStatus.REJECTED.value
    loaded = await SqlPlanRepository(db_session).get(plan.id)
    assert loaded is not None
    disposed = loaded.nodes[PlanNodeId("disposed-node")]
    assert disposed.metadata["workspace_task_projection_status"] == "done"
    assert disposed.metadata["last_supervisor_decision_action"] == "dispose_node"


@pytest.mark.asyncio
async def test_supervisor_dispose_event_reconciles_node_before_tick(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_and_plan(db_session)
    db_session.add_all(
        [
            WorkspaceTaskModel(
                id="disposed-task",
                workspace_id="workspace-1",
                title="Disposed task",
                description="",
                created_by="worker-user-1",
                status="in_progress",
                priority=0,
                assignee_agent_id="worker-agent",
                blocker_reason="Maximum steps (80) exceeded",
                metadata_json={
                    AUTONOMY_SCHEMA_VERSION_KEY: 1,
                    TASK_ROLE: "execution_task",
                    ROOT_GOAL_TASK_ID: "root-task-1",
                    WORKSPACE_PLAN_ID: "disposed-plan-2",
                    WORKSPACE_PLAN_NODE_ID: "disposed-node",
                },
            ),
            WorkspaceTaskSessionAttemptModel(
                id="disposed-attempt",
                workspace_task_id="disposed-task",
                root_goal_task_id="root-task-1",
                workspace_id="workspace-1",
                attempt_number=1,
                status="rejected",
                conversation_id="disposed-conversation",
                worker_agent_id="worker-agent",
                leader_agent_id=BUILTIN_SISYPHUS_ID,
            ),
            WorkspacePlanEventModel(
                id="dispose-event-reconcile",
                plan_id="disposed-plan-2",
                workspace_id="workspace-1",
                node_id="disposed-node",
                attempt_id="disposed-attempt",
                event_type="supervisor_decision_completed",
                source="workspace_plan_verifier",
                payload_json={
                    "action": "dispose_node",
                    "rationale": "Node is stale and structurally superseded.",
                    "confidence": 0.91,
                },
                created_at=datetime.now(UTC),
            ),
        ]
    )
    plan = Plan(
        id="disposed-plan-2",
        workspace_id="workspace-1",
        goal_id=PlanNodeId("disposed-root"),
        status=PlanStatus.ACTIVE,
    )
    plan.add_node(
        PlanNode(
            id="disposed-root",
            plan_id=plan.id,
            parent_id=None,
            kind=PlanNodeKind.GOAL,
            title="Root",
            intent=TaskIntent.IN_PROGRESS,
            execution=TaskExecution.IDLE,
            workspace_task_id="root-task-1",
        )
    )
    plan.add_node(
        PlanNode(
            id="disposed-node",
            plan_id=plan.id,
            parent_id=PlanNodeId("disposed-root"),
            kind=PlanNodeKind.TASK,
            title="Disposed task",
            intent=TaskIntent.IN_PROGRESS,
            execution=TaskExecution.RUNNING,
            workspace_task_id="disposed-task",
            current_attempt_id="new-running-attempt",
            metadata={
                TASK_ROLE: "execution_task",
                WORKSPACE_PLAN_ID: "disposed-plan-2",
                WORKSPACE_PLAN_NODE_ID: "disposed-node",
            },
        )
    )
    await SqlPlanRepository(db_session).save(plan)
    await db_session.commit()

    changed = await outbox_handlers._reconcile_supervisor_disposed_nodes_before_tick(
        session=db_session,
        plan_id="disposed-plan-2",
        workspace_id="workspace-1",
    )
    assert changed is True

    loaded = await SqlPlanRepository(db_session).get("disposed-plan-2")
    assert loaded is not None
    disposed = loaded.nodes[PlanNodeId("disposed-node")]
    assert disposed.intent is TaskIntent.DONE
    assert disposed.execution is TaskExecution.IDLE
    assert disposed.current_attempt_id == "disposed-attempt"
    assert disposed.metadata["verification_feedback_disposition"] == (
        "supervisor_agent_disposed_node"
    )
    assert disposed.metadata["last_supervisor_decision_action"] == "dispose_node"


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
    assert 'git merge --no-edit "$RESOLVED_COMMIT"' in commands[0]
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
async def test_accepted_terminal_attempt_skips_invalid_commit_ref_for_integration(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_workspace_and_plan(db_session)
    workspace = (
        await db_session.execute(select(WorkspaceModel).where(WorkspaceModel.id == "workspace-1"))
    ).scalar_one()
    workspace.metadata_json = {"code_context": {"sandbox_code_root": "/workspace/my-evo"}}
    task = WorkspaceTaskModel(
        id="task-integrate-valid-ref",
        workspace_id="workspace-1",
        title="Integrate accepted commit with noisy evidence",
        description="Project accepted worktree commit when early evidence contains a bad SHA.",
        created_by="worker-user-1",
        status="in_progress",
        priority=0,
        metadata_json={
            AUTONOMY_SCHEMA_VERSION_KEY: 1,
            ROOT_GOAL_TASK_ID: "root-task-1",
            "feature_checkpoint": {
                "feature_id": "feature-integrate-valid-ref",
                "worktree_path": "${sandbox_code_root}/../.memstack/worktrees/attempt-integrate",
                "branch_name": "workspace/node-integrate-attempt",
            },
        },
    )
    task_id = task.id
    invalid_commit_ref = "68413fe68413fe68413fe68413fe68413fe68413fe"
    valid_commit_ref = "68413fe"
    attempt = WorkspaceTaskSessionAttemptModel(
        id="attempt-integrate-valid-ref",
        workspace_task_id=task.id,
        root_goal_task_id="root-task-1",
        workspace_id="workspace-1",
        attempt_number=1,
        status="accepted",
        conversation_id="conversation-integrate-valid-ref",
        worker_agent_id="worker-agent",
        leader_agent_id=BUILTIN_SISYPHUS_ID,
        candidate_summary="done",
        candidate_artifacts_json=[
            f"commit_ref:{invalid_commit_ref}",
            "changed_file:src/example.py",
        ],
        candidate_verifications_json=[
            f"commit_ref:{valid_commit_ref}",
            "test_run:pytest",
        ],
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
        id="node-integrate-valid-ref",
        plan_id="worker-plan-1",
        kind=PlanNodeKind.TASK,
        parent_id=PlanNodeId("root-node"),
        title="Integrate accepted commit with noisy evidence",
        workspace_task_id=task.id,
        current_attempt_id=attempt.id,
        feature_checkpoint=FeatureCheckpoint(
            feature_id="feature-integrate-valid-ref",
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
    assert result["worktree_integration_commit_ref"] == valid_commit_ref
    assert commands
    assert f"CMT={valid_commit_ref}" in commands[0]
    assert invalid_commit_ref not in commands[0]
    db_session.expire_all()
    projected_task = await db_session.get(WorkspaceTaskModel, task_id)
    assert projected_task is not None
    assert projected_task.metadata_json["feature_checkpoint"]["commit_ref"] == valid_commit_ref
    event = (
        await db_session.execute(
            select(WorkspacePlanEventModel).where(
                WorkspacePlanEventModel.event_type == "accepted_worktree_integrated"
            )
        )
    ).scalar_one()
    assert event.payload_json["commit_ref"] == valid_commit_ref


@pytest.mark.asyncio
async def test_accepted_terminal_attempt_records_resolved_worktree_commit(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_workspace_and_plan(db_session)
    workspace = (
        await db_session.execute(select(WorkspaceModel).where(WorkspaceModel.id == "workspace-1"))
    ).scalar_one()
    workspace.metadata_json = {"code_context": {"sandbox_code_root": "/workspace/my-evo"}}
    task = WorkspaceTaskModel(
        id="task-integrate-resolved",
        workspace_id="workspace-1",
        title="Integrate accepted repaired commit",
        description="Project accepted worktree commit with repaired SHA.",
        created_by="worker-user-1",
        status="in_progress",
        priority=0,
        metadata_json={
            AUTONOMY_SCHEMA_VERSION_KEY: 1,
            ROOT_GOAL_TASK_ID: "root-task-1",
            "feature_checkpoint": {
                "feature_id": "feature-integrate-resolved",
                "worktree_path": "${sandbox_code_root}/../.memstack/worktrees/attempt-integrate",
                "branch_name": "workspace/node-integrate-attempt",
            },
        },
    )
    task_id = task.id
    bad_commit_ref = "8f7d695a0b46e24fe07bdc28c40b7b0cb1ce3d37"
    actual_commit_ref = "8f7d695b3438acc8dc469f9f527e143731e00802"
    attempt = WorkspaceTaskSessionAttemptModel(
        id="attempt-integrate-resolved",
        workspace_task_id=task.id,
        root_goal_task_id="root-task-1",
        workspace_id="workspace-1",
        attempt_number=1,
        status="accepted",
        conversation_id="conversation-integrate-resolved",
        worker_agent_id="worker-agent",
        leader_agent_id=BUILTIN_SISYPHUS_ID,
        candidate_summary="done",
        candidate_artifacts_json=[f"commit_ref:{bad_commit_ref}", "changed_file:src/example.py"],
        candidate_verifications_json=[f"commit_ref:{bad_commit_ref}", "test_run:pytest"],
    )
    db_session.add_all([task, attempt])
    await db_session.flush()

    class FakeRunner:
        def __init__(self, *, project_id: str, tenant_id: str) -> None:
            assert project_id == "worker-project-1"
            assert tenant_id == "worker-tenant-1"

        async def run_command(self, command: str, *, timeout: int) -> dict[str, object]:
            assert timeout == 120
            assert "cut -c1-12" in command
            return {
                "exit_code": 0,
                "stdout": (
                    f"commit_ref_repaired_from={bad_commit_ref}\n"
                    f"resolved_commit_ref={actual_commit_ref}\n"
                    "status=merged\n"
                    "git_head=def5678\n"
                ),
                "stderr": "",
            }

    monkeypatch.setattr(outbox_handlers, "_WorkspaceSandboxCommandRunner", FakeRunner)
    node = PlanNode(
        id="node-integrate-resolved",
        plan_id="worker-plan-1",
        kind=PlanNodeKind.TASK,
        parent_id=PlanNodeId("root-node"),
        title="Integrate accepted repaired commit",
        workspace_task_id=task.id,
        current_attempt_id=attempt.id,
        feature_checkpoint=FeatureCheckpoint(
            feature_id="feature-integrate-resolved",
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
    assert result["worktree_integration_commit_ref"] == actual_commit_ref
    db_session.expire_all()
    projected_task = await db_session.get(WorkspaceTaskModel, task_id)
    assert projected_task is not None
    assert projected_task.metadata_json["feature_checkpoint"]["commit_ref"] == actual_commit_ref
    event = (
        await db_session.execute(
            select(WorkspacePlanEventModel).where(
                WorkspacePlanEventModel.event_type == "accepted_worktree_integrated"
            )
        )
    ).scalar_one()
    assert event.payload_json["commit_ref"] == actual_commit_ref


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
    assert 'git merge --no-edit "$RESOLVED_COMMIT"' in commands[0]


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
    monkeypatch.setenv(outbox_handlers._BLOCKED_DIRTY_MAIN_SIGNATURE_TTL_ENV, "0")
    outbox_handlers._blocked_dirty_main_projection_cache.clear()
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
        "dirty_has_generated=true\n"
        " M frontend/tests/screenshots/01-homepage.png\n"
    )
    assert not await outbox_handlers._accepted_attempt_projection_complete_for_node(
        session=db_session,
        workspace_id="workspace-1",
        node=node,
        attempt=attempt,
    )

    runner_result["stdout"] = (
        "status=dirty\n"
        "dirty_signature=sig-current\n"
        "dirty_generated_only=false\n"
        "dirty_has_generated=true\n"
        "A  README.md\n"
        "?? frontend/e2e-test-output.txt\n"
    )
    assert not await outbox_handlers._accepted_attempt_projection_complete_for_node(
        session=db_session,
        workspace_id="workspace-1",
        node=node,
        attempt=attempt,
    )

    runner_result["stdout"] = (
        "status=dirty\n"
        "dirty_signature=sig-current\n"
        "dirty_generated_only=false\n"
        "dirty_has_generated=false\n"
        "staged_bootstrap_only=true\n"
        "A  README.md\n"
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
async def test_blocked_dirty_main_projection_reuses_recent_dirty_signature_check(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(outbox_handlers._BLOCKED_DIRTY_MAIN_SIGNATURE_TTL_ENV, "30")
    outbox_handlers._blocked_dirty_main_projection_cache.clear()
    await _seed_workspace_and_plan(db_session)
    workspace = (
        await db_session.execute(select(WorkspaceModel).where(WorkspaceModel.id == "workspace-1"))
    ).scalar_one()
    workspace.metadata_json = {"code_context": {"sandbox_code_root": "/workspace/my-evo"}}
    task = WorkspaceTaskModel(
        id="task-blocked-integration-cache",
        workspace_id="workspace-1",
        title="Blocked accepted integration",
        description="Accepted commit blocked by dirty main checkout.",
        created_by="worker-user-1",
        status="completed",
        priority=0,
        metadata_json={AUTONOMY_SCHEMA_VERSION_KEY: 1, ROOT_GOAL_TASK_ID: "root-task-1"},
    )
    attempt = WorkspaceTaskSessionAttemptModel(
        id="attempt-blocked-integration-cache",
        workspace_task_id=task.id,
        root_goal_task_id="root-task-1",
        workspace_id="workspace-1",
        attempt_number=1,
        status="accepted",
        conversation_id="conversation-blocked-integration-cache",
        worker_agent_id="worker-agent",
        leader_agent_id=BUILTIN_SISYPHUS_ID,
        candidate_summary="done",
        candidate_artifacts_json=["commit_ref:abc1234"],
        candidate_verifications_json=["commit_ref:abc1234"],
    )
    second_task = WorkspaceTaskModel(
        id="task-blocked-integration-cache-2",
        workspace_id="workspace-1",
        title="Second blocked accepted integration",
        description="Another accepted commit blocked by the same dirty main checkout.",
        created_by="worker-user-1",
        status="completed",
        priority=0,
        metadata_json={AUTONOMY_SCHEMA_VERSION_KEY: 1, ROOT_GOAL_TASK_ID: "root-task-1"},
    )
    second_attempt = WorkspaceTaskSessionAttemptModel(
        id="attempt-blocked-integration-cache-2",
        workspace_task_id=second_task.id,
        root_goal_task_id="root-task-1",
        workspace_id="workspace-1",
        attempt_number=1,
        status="accepted",
        conversation_id="conversation-blocked-integration-cache-2",
        worker_agent_id="worker-agent",
        leader_agent_id=BUILTIN_SISYPHUS_ID,
        candidate_summary="done",
        candidate_artifacts_json=["commit_ref:def5678"],
        candidate_verifications_json=["commit_ref:def5678"],
    )
    db_session.add_all([task, attempt, second_task, second_attempt])
    await db_session.flush()

    commands: list[str] = []

    class FakeRunner:
        def __init__(self, *, project_id: str, tenant_id: str) -> None:
            assert project_id == "worker-project-1"
            assert tenant_id == "worker-tenant-1"

        async def run_command(self, command: str, *, timeout: int) -> dict[str, object]:
            commands.append(command)
            return {
                "exit_code": 0,
                "stdout": "status=dirty\ndirty_signature=sig-current\n M scratch.js\n",
                "stderr": "",
            }

    monkeypatch.setattr(outbox_handlers, "_WorkspaceSandboxCommandRunner", FakeRunner)
    node = PlanNode(
        id="node-blocked-integration-cache",
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
    second_node = PlanNode(
        id="node-blocked-integration-cache-2",
        plan_id="worker-plan-1",
        kind=PlanNodeKind.TASK,
        parent_id=PlanNodeId("root-node"),
        title="Second blocked accepted integration",
        workspace_task_id=second_task.id,
        current_attempt_id=second_attempt.id,
        metadata={
            "terminal_attempt_status": "accepted",
            "last_verification_attempt_id": second_attempt.id,
            "verified_commit_ref": "def5678",
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
    assert await outbox_handlers._accepted_attempt_projection_complete_for_node(
        session=db_session,
        workspace_id="workspace-1",
        node=second_node,
        attempt=second_attempt,
    )
    assert len(commands) == 1
    outbox_handlers._blocked_dirty_main_projection_cache.clear()


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

    class FakeWorktreeAgentPreparer:
        def __init__(self, *, tenant_id: str, project_id: str) -> None:
            assert tenant_id == "worker-tenant-1"
            assert project_id == "worker-project-1"

        async def prepare_worktree(self, request: Any) -> AttemptWorktreeContext:
            commands.append(request.setup_command)
            return AttemptWorktreeContext(
                workspace_root=request.workspace_root,
                sandbox_code_root=request.sandbox_code_root,
                active_root=request.worktree_path,
                worktree_path=request.worktree_path,
                branch_name=request.branch_name,
                base_ref=request.base_ref,
                attempt_id=request.attempt_id,
                is_isolated=True,
                setup_status="prepared",
                setup_output="git_head=abc123",
                original_base_ref=request.base_ref,
                resolved_base_ref=request.base_ref,
            )

    monkeypatch.setattr(
        outbox_handlers, "WorkspaceWorktreeAgentPreparer", FakeWorktreeAgentPreparer
    )
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


@pytest.mark.asyncio
async def test_prepare_attempt_worktree_surfaces_structured_fallback_diagnostics(
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

    class FakeWorktreeAgentPreparer:
        def __init__(self, *, tenant_id: str, project_id: str) -> None:
            assert tenant_id == "worker-tenant-1"
            assert project_id == "worker-project-1"

        async def prepare_worktree(self, request: Any) -> AttemptWorktreeContext:
            commands.append(request.setup_command)
            commands.append(request.diagnostics_command)
            return AttemptWorktreeContext(
                workspace_root=request.workspace_root,
                sandbox_code_root=request.sandbox_code_root,
                active_root=request.worktree_path,
                worktree_path=request.worktree_path,
                branch_name=request.branch_name,
                base_ref=request.base_ref,
                attempt_id=request.attempt_id,
                is_isolated=True,
                setup_status="fallback_used",
                setup_output="base_ref_unusable=bad-ref\\ngit_head=abc123",
                original_base_ref="bad-ref",
                resolved_base_ref="HEAD",
                fallback_reason="base_ref_unusable",
                git_fsck_summary="broken link from commit abc",
                pruned_worktrees_count=3,
            )

    monkeypatch.setattr(
        outbox_handlers, "WorkspaceWorktreeAgentPreparer", FakeWorktreeAgentPreparer
    )
    task = WorkspaceTask(
        id="task-fallback",
        workspace_id="workspace-1",
        title="Retry with bad base",
        description="Exercise structured worktree fallback diagnostics.",
        created_by="worker-user-1",
        status="in_progress",
        metadata={
            AUTONOMY_SCHEMA_VERSION_KEY: 1,
            ROOT_GOAL_TASK_ID: "root-task-1",
            "feature_checkpoint": {
                "worktree_path": "${sandbox_code_root}/../.memstack/worktrees/attempt-fallback",
                "branch_name": "workspace/node-1-attempt-fallback",
                "base_ref": "bad-ref",
            },
        },
    )

    note = await _prepare_attempt_worktree_if_available(
        db_session,
        "workspace-1",
        task,
        None,
        "attempt-fallback",
    )

    assert note is not None
    assert "status=fallback_used" in note
    assert "original_base_ref=bad-ref" in note
    assert "resolved_base_ref=HEAD" in note
    assert "fallback_reason=base_ref_unusable" in note
    assert "pruned_worktrees_count=3" in note
    assert "git_fsck_summary=broken link from commit abc" in note
    assert len(commands) == 2


@pytest.mark.asyncio
async def test_prepare_attempt_worktree_uses_runner_when_agent_contract_fails(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_workspace_and_plan(db_session)
    workspace = (
        await db_session.execute(select(WorkspaceModel).where(WorkspaceModel.id == "workspace-1"))
    ).scalar_one()
    workspace.metadata_json = {"code_context": {"sandbox_code_root": "/workspace/my-evo"}}
    await db_session.flush()

    agent_commands: list[str] = []
    runner_commands: list[str] = []

    class FakeWorktreeAgentPreparer:
        def __init__(self, *, tenant_id: str, project_id: str) -> None:
            assert tenant_id == "worker-tenant-1"
            assert project_id == "worker-project-1"

        async def prepare_worktree(self, request: Any) -> AttemptWorktreeContext:
            agent_commands.append(request.setup_command)
            return AttemptWorktreeContext(
                workspace_root=request.workspace_root,
                sandbox_code_root=request.sandbox_code_root,
                active_root=request.worktree_path,
                worktree_path=request.worktree_path,
                branch_name=request.branch_name,
                base_ref=request.base_ref,
                attempt_id=request.attempt_id,
                is_isolated=True,
                setup_status="failed",
                setup_reason="builtin workspace worktree manager did not submit preparation: {}",
            )

    class FakeRunner:
        def __init__(self, *, project_id: str, tenant_id: str) -> None:
            assert project_id == "worker-project-1"
            assert tenant_id == "worker-tenant-1"

        async def run_command(self, command: str, *, timeout: int) -> dict[str, object]:
            runner_commands.append(command)
            if timeout == 120:
                return {"exit_code": 0, "stdout": "git_head=abc123\n", "stderr": ""}
            assert timeout == 60
            return {
                "exit_code": 0,
                "stdout": "resolved_base_ref=abc123\npruned_worktrees_count=0\n",
                "stderr": "",
            }

    monkeypatch.setattr(
        outbox_handlers, "WorkspaceWorktreeAgentPreparer", FakeWorktreeAgentPreparer
    )
    monkeypatch.setattr(outbox_handlers, "_WorkspaceSandboxCommandRunner", FakeRunner)
    task = WorkspaceTask(
        id="task-agent-contract-fallback",
        workspace_id="workspace-1",
        title="Prepare after missing worktree contract",
        description="Exercise deterministic setup after agent contract failure.",
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
        "attempt-contract-fallback",
    )

    assert note is not None
    assert "status=prepared" in note
    assert "worktree_path=/workspace/.memstack/worktrees/attempt-contract-fallback" in note
    assert agent_commands
    assert len(runner_commands) == 2
    assert "git worktree add -B" in runner_commands[0]
    assert "git fsck --no-progress --connectivity-only" in runner_commands[1]


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


def test_apply_attempt_worktree_checkpoint_uses_failed_pipeline_source_without_publish_ref() -> (
    None
):
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
        batch_size=1,
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
async def test_worker_launch_handler_ignores_stale_active_worker_capacity(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_workspace_and_plan(db_session)
    stale_at = datetime(2025, 1, 1, tzinfo=UTC)
    db_session.add_all(
        [
            WorkspaceTaskModel(
                id="stale-active-worker-task",
                workspace_id="workspace-1",
                title="Stale running task",
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
                id="stale-active-worker-attempt",
                workspace_task_id="stale-active-worker-task",
                root_goal_task_id="root-task-1",
                workspace_id="workspace-1",
                attempt_number=1,
                status="running",
                conversation_id="stale-active-worker-conversation",
                worker_agent_id="worker-agent",
                leader_agent_id=BUILTIN_SISYPHUS_ID,
                created_at=stale_at,
                updated_at=stale_at,
            ),
            WorkspaceTaskModel(
                id="fresh-queued-worker-task",
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
                    CURRENT_ATTEMPT_ID: "fresh-queued-worker-attempt",
                },
            ),
            WorkspaceTaskSessionAttemptModel(
                id="fresh-queued-worker-attempt",
                workspace_task_id="fresh-queued-worker-task",
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
            "task_id": "fresh-queued-worker-task",
            "worker_agent_id": "worker-agent",
            "actor_user_id": "worker-user-1",
            "leader_agent_id": BUILTIN_SISYPHUS_ID,
            "attempt_id": "fresh-queued-worker-attempt",
        },
        metadata={"source": "test"},
        max_attempts=9,
    )
    await db_session.commit()

    monkeypatch.setenv("WORKSPACE_WORKER_LAUNCH_MAX_ACTIVE", "1")
    monkeypatch.setenv("WORKSPACE_WORKER_LAUNCH_ACTIVE_EVENT_GRACE_SECONDS", "60")
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
        batch_size=1,
    )

    assert await worker.run_once() == 1
    assert len(launched) == 1
    assert launched[0]["attempt_id"] == "fresh-queued-worker-attempt"
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
    assert deferred_jobs == []


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
        batch_size=1,
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
async def test_worker_launch_handler_skips_supervisor_disposed_node(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_workspace_and_plan(db_session)
    db_session.add_all(
        [
            WorkspaceTaskModel(
                id="disposed-task",
                workspace_id="workspace-1",
                title="Disposed task",
                description="",
                created_by="worker-user-1",
                status="in_progress",
                priority=0,
                assignee_agent_id="worker-agent",
                metadata_json={
                    AUTONOMY_SCHEMA_VERSION_KEY: 1,
                    TASK_ROLE: "execution_task",
                    ROOT_GOAL_TASK_ID: "root-task-1",
                    CURRENT_ATTEMPT_ID: "disposed-attempt",
                },
            ),
            WorkspaceTaskSessionAttemptModel(
                id="disposed-attempt",
                workspace_task_id="disposed-task",
                root_goal_task_id="root-task-1",
                workspace_id="workspace-1",
                attempt_number=1,
                status="running",
                conversation_id=None,
                worker_agent_id="worker-agent",
                leader_agent_id=BUILTIN_SISYPHUS_ID,
            ),
            WorkspacePlanEventModel(
                id="dispose-event-1",
                plan_id="worker-plan-1",
                workspace_id="workspace-1",
                node_id="disposed-node",
                attempt_id="disposed-attempt",
                event_type="supervisor_decision_completed",
                source="workspace_plan_verifier",
                payload_json={"action": "dispose_node"},
                created_at=datetime.now(UTC),
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
            "task_id": "disposed-task",
            "node_id": "disposed-node",
            "worker_agent_id": "worker-agent",
            "actor_user_id": "worker-user-1",
            "leader_agent_id": BUILTIN_SISYPHUS_ID,
            "attempt_id": "disposed-attempt",
        },
        metadata={"source": "test"},
    )
    await db_session.commit()
    launched: list[str] = []
    monkeypatch.setattr(
        "src.infrastructure.agent.workspace.worker_launch.schedule_worker_session",
        lambda **kwargs: launched.append(kwargs["attempt"].id),
    )

    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={
            WORKER_LAUNCH_EVENT: make_worker_launch_handler(worktree_preparer=_noop_worktree)
        },
        worker_id="worker-a",
        batch_size=1,
    )

    assert await worker.run_once() == 1
    assert launched == []
    completed = await repo.get_by_id(item.id)
    assert completed is not None
    assert completed.status == "completed"


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
        batch_size=1,
    )

    assert await worker.run_once() == 1

    assert not launched


@pytest.mark.asyncio
async def test_worker_launch_handler_skips_no_attempt_payload_when_node_not_launchable(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_workspace_only(db_session)
    plan = Plan(
        id="worker-plan-1",
        workspace_id="workspace-1",
        goal_id=PlanNodeId("worker-plan-1-goal"),
        status=PlanStatus.ACTIVE,
    )
    plan.add_node(
        PlanNode(
            id="worker-plan-1-goal",
            plan_id=plan.id,
            parent_id=None,
            kind=PlanNodeKind.GOAL,
            title="Root goal",
            intent=TaskIntent.IN_PROGRESS,
            execution=TaskExecution.IDLE,
            workspace_task_id="root-task-1",
        )
    )
    plan.add_node(
        PlanNode(
            id="idle-node",
            plan_id=plan.id,
            parent_id=plan.goal_id,
            kind=PlanNodeKind.TASK,
            title="Old idle task",
            intent=TaskIntent.TODO,
            execution=TaskExecution.IDLE,
            workspace_task_id="idle-node-task",
        )
    )
    await SqlPlanRepository(db_session).save(plan)
    db_session.add(
        WorkspaceTaskModel(
            id="idle-node-task",
            workspace_id="workspace-1",
            title="Old idle task",
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
                WORKSPACE_PLAN_NODE_ID: "idle-node",
            },
        )
    )
    repo = SqlWorkspacePlanOutboxRepository(db_session)
    item = await repo.enqueue(
        plan_id=plan.id,
        workspace_id="workspace-1",
        event_type=WORKER_LAUNCH_EVENT,
        payload={
            "workspace_id": "workspace-1",
            "task_id": "idle-node-task",
            "node_id": "idle-node",
            "worker_agent_id": "worker-agent",
            "actor_user_id": "worker-user-1",
            "leader_agent_id": BUILTIN_SISYPHUS_ID,
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
        batch_size=1,
    )

    assert await worker.run_once() == 1

    assert not launched
    completed = await repo.get_by_id(item.id)
    assert completed is not None
    assert completed.status == "completed"


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
        batch_size=1,
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
async def test_supervisor_tick_handler_skips_retry_superseded_by_newer_completed_tick(
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
    stale = await repo.enqueue(
        plan_id=plan.id,
        workspace_id="workspace-1",
        event_type=SUPERVISOR_TICK_EVENT,
        payload={"workspace_id": "workspace-1"},
    )
    newer = await repo.enqueue(
        plan_id=plan.id,
        workspace_id="workspace-1",
        event_type=SUPERVISOR_TICK_EVENT,
        payload={"workspace_id": "workspace-1"},
    )
    stale.status = "failed"
    stale.attempt_count = 1
    stale.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    stale.next_attempt_at = datetime(2026, 1, 1, tzinfo=UTC)
    stale.last_error = "deadlock detected"
    newer.status = "completed"
    newer.attempt_count = 1
    newer.created_at = datetime(2026, 1, 1, 0, 1, tzinfo=UTC)
    newer.processed_at = datetime(2026, 1, 1, 0, 2, tzinfo=UTC)
    await db_session.commit()

    async def dispatcher(
        _workspace_id: str,
        _allocation: Allocation,
        _node: PlanNode,
    ) -> str:
        raise AssertionError("superseded supervisor tick should not run")

    async def agent_pool(_workspace_id: str) -> list[WorkspaceAgent]:
        raise AssertionError("superseded supervisor tick should not load agents")

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
        batch_size=1,
    )

    assert await worker.run_once() == 1
    loaded = await repo.get_by_id(stale.id)
    assert loaded is not None
    assert loaded.status == "completed"
    assert loaded.last_error is None


@pytest.mark.asyncio
async def test_supervisor_tick_handler_skips_tick_superseded_by_newer_pipeline_request(
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
    stale = await repo.enqueue(
        plan_id=plan.id,
        workspace_id="workspace-1",
        event_type=SUPERVISOR_TICK_EVENT,
        payload={"workspace_id": "workspace-1"},
    )
    pipeline_request = await repo.enqueue(
        plan_id=plan.id,
        workspace_id="workspace-1",
        event_type=outbox_handlers.PIPELINE_RUN_REQUESTED_EVENT,
        payload={
            "workspace_id": "workspace-1",
            "plan_id": plan.id,
            "node_id": "node-1",
            "attempt_id": "attempt-1",
        },
    )
    stale.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    pipeline_request.created_at = datetime(2026, 1, 1, 0, 1, tzinfo=UTC)
    await db_session.commit()

    async def dispatcher(
        _workspace_id: str,
        _allocation: Allocation,
        _node: PlanNode,
    ) -> str:
        raise AssertionError("superseded supervisor tick should not dispatch work")

    async def agent_pool(_workspace_id: str) -> list[WorkspaceAgent]:
        raise AssertionError("superseded supervisor tick should not load agents")

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
        batch_size=1,
    )

    assert await worker.run_once() == 1
    loaded_stale = await repo.get_by_id(stale.id)
    loaded_pipeline_request = await repo.get_by_id(pipeline_request.id)
    assert loaded_stale is not None
    assert loaded_stale.status == "completed"
    assert loaded_stale.last_error is None
    assert loaded_pipeline_request is not None
    assert loaded_pipeline_request.status == "pending"
    assert loaded_pipeline_request.attempt_count == 0


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
        batch_size=1,
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
        batch_size=1,
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
async def test_supervisor_tick_reconciles_verifying_reported_attempt(
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
            id="verifying-reported-node-task",
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
                CURRENT_ATTEMPT_ID: "verifying-reported-attempt",
                LAST_WORKER_REPORT_ATTEMPT_ID: "verifying-reported-attempt",
                LAST_WORKER_REPORT_SUMMARY: "worker completed with evidence",
                "last_worker_report_type": "completed",
                "last_attempt_status": "awaiting_leader_adjudication",
            },
        )
    )
    db_session.add(
        WorkspaceTaskSessionAttemptModel(
            id="verifying-reported-attempt",
            workspace_task_id="verifying-reported-node-task",
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
            execution=TaskExecution.VERIFYING,
            current_attempt_id="verifying-reported-attempt",
            workspace_task_id="verifying-reported-node-task",
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
        batch_size=1,
    )

    assert await worker.run_once() == 1
    loaded = await SqlPlanRepository(db_session).get(plan.id)
    assert loaded is not None
    reconciled_leaf = loaded.leaf_tasks()[0]
    assert reconciled_leaf.intent is TaskIntent.DONE
    assert reconciled_leaf.execution is TaskExecution.IDLE
    assert reconciled_leaf.metadata["reported_attempt_status"] == "awaiting_leader_adjudication"
    assert reconciled_leaf.metadata["last_verification_attempt_id"] == "verifying-reported-attempt"


@pytest.mark.asyncio
async def test_supervisor_tick_enqueues_followup_after_post_terminal_reconcile(
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
    leaf = plan.leaf_tasks()[0]
    plan.add_node(
        PlanNode(
            id="dependent-node",
            plan_id=plan.id,
            parent_id=plan.goal_id,
            title="Dependent task",
            depends_on=frozenset({leaf.node_id}),
            recommended_capabilities=(Capability(name="codegen"),),
        )
    )
    db_session.add(
        WorkspaceTaskModel(
            id="fresh-node-task",
            workspace_id="workspace-1",
            title="Fresh verified node",
            description="",
            created_by="worker-user-1",
            status="in_progress",
            priority=0,
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
            id="fresh-accepted-attempt",
            workspace_task_id="fresh-node-task",
            root_goal_task_id="root-task-1",
            workspace_id="workspace-1",
            attempt_number=1,
            status="accepted",
            conversation_id="fresh-conversation",
            worker_agent_id="worker-agent",
            leader_agent_id=BUILTIN_SISYPHUS_ID,
            leader_feedback="freshly verified by durable verifier",
            candidate_verifications_json=[
                "preflight:read-progress",
                "preflight:git-status",
                "commit_ref:abc1234",
            ],
        )
    )
    await SqlPlanRepository(db_session).save(plan)
    await SqlWorkspacePlanOutboxRepository(db_session).enqueue(
        plan_id=plan.id,
        workspace_id="workspace-1",
        event_type=SUPERVISOR_TICK_EVENT,
        payload={"workspace_id": "workspace-1", "root_task_id": "root-task-1"},
    )
    await db_session.commit()

    class FreshVerificationOrchestrator:
        async def tick_once(self, workspace_id: str) -> TickReport:
            loaded = await SqlPlanRepository(db_session).get(plan.id)
            assert loaded is not None
            node = loaded.nodes[leaf.node_id]
            loaded.replace_node(
                replace(
                    node,
                    intent=TaskIntent.DONE,
                    execution=TaskExecution.IDLE,
                    current_attempt_id="fresh-accepted-attempt",
                    workspace_task_id="fresh-node-task",
                    metadata={
                        **node.metadata,
                        "last_verification_passed": True,
                        "last_verification_summary": "verified (fresh)",
                        "verified_commit_ref": "abc1234",
                        ACTIVE_EXECUTION_ROOT: (
                            "/workspace/.memstack/worktrees/fresh-accepted-attempt"
                        ),
                    },
                )
            )
            await SqlPlanRepository(db_session).save(loaded)
            return TickReport(workspace_id=workspace_id, nodes_completed=1)

    monkeypatch.setattr(
        outbox_handlers,
        "build_sql_orchestrator",
        lambda *_args, **_kwargs: FreshVerificationOrchestrator(),
    )

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
        batch_size=1,
    )

    assert await worker.run_once() == 1
    loaded = await SqlPlanRepository(db_session).get(plan.id)
    assert loaded is not None
    reconciled_leaf = loaded.nodes[leaf.node_id]
    assert reconciled_leaf.metadata["terminal_attempt_status"] == "accepted"
    assert reconciled_leaf.metadata["worktree_integration_status"] == "skipped"

    outbox = await SqlWorkspacePlanOutboxRepository(db_session).list_by_workspace(
        "workspace-1",
        limit=5,
    )
    followups = [
        item
        for item in outbox
        if item.event_type == SUPERVISOR_TICK_EVENT
        and item.status == "pending"
        and item.metadata_json.get("reason") == "post_terminal_attempt_reconcile"
    ]
    assert len(followups) == 1
    assert followups[0].payload_json["root_task_id"] == "root-task-1"


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
        batch_size=1,
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
async def test_terminal_attempt_reconcile_preserves_verification_retry_node(
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
            id="verifier-retry-attempt",
            workspace_task_id="workspace-task-retry",
            root_goal_task_id="root-task-1",
            workspace_id="workspace-1",
            attempt_number=1,
            status="cancelled",
            conversation_id="verifier-retry-conversation",
            worker_agent_id="worker-agent",
            leader_agent_id=BUILTIN_SISYPHUS_ID,
            leader_feedback="verification judge retry scheduled",
            adjudication_reason="verification_retry_scheduled",
        )
    )
    plan.replace_node(
        replace(
            leaf,
            intent=TaskIntent.IN_PROGRESS,
            execution=TaskExecution.REPORTED,
            current_attempt_id="verifier-retry-attempt",
            workspace_task_id="workspace-task-retry",
            metadata={
                **dict(leaf.metadata or {}),
                "retry_verification_only": True,
                "retry_not_before": "2026-05-22T06:32:43Z",
                "last_verification_judge_next_action_kind": "retry_same_node",
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
    assert preserved_leaf.current_attempt_id == "verifier-retry-attempt"
    assert preserved_leaf.metadata["retry_verification_only"] is True
    assert "terminal_attempt_retry_reason" not in preserved_leaf.metadata


@pytest.mark.asyncio
async def test_terminal_attempt_reconcile_preserves_inflight_pipeline_attempt(
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
            id="pipeline-running-terminal-attempt",
            workspace_task_id="workspace-task-pipeline",
            root_goal_task_id="root-task-1",
            workspace_id="workspace-1",
            attempt_number=1,
            status="rejected",
            conversation_id="pipeline-running-conversation",
            worker_agent_id="worker-agent",
            leader_agent_id=BUILTIN_SISYPHUS_ID,
            leader_feedback="waiting for current pipeline result",
        )
    )
    plan.replace_node(
        replace(
            leaf,
            intent=TaskIntent.IN_PROGRESS,
            execution=TaskExecution.IDLE,
            current_attempt_id="pipeline-running-terminal-attempt",
            workspace_task_id="workspace-task-pipeline",
            metadata={
                **dict(leaf.metadata or {}),
                "pipeline_status": "running",
                "pipeline_gate_status": "running",
                "pipeline_run_id": "drone-running-43",
                "pipeline_started_at": "2026-05-21T15:40:07Z",
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
    assert preserved_leaf.execution is TaskExecution.IDLE
    assert preserved_leaf.current_attempt_id == "pipeline-running-terminal-attempt"
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
        batch_size=1,
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
        batch_size=1,
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
async def test_supervisor_tick_reconciles_done_idle_accepted_judge_attempt(
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
            id="accepted-node-task",
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
                CURRENT_ATTEMPT_ID: "accepted-judge-attempt",
                PENDING_LEADER_ADJUDICATION: False,
                "durable_plan_verdict": "pipeline_pending",
                "last_attempt_status": "awaiting_pipeline",
            },
        )
    )
    db_session.add(
        WorkspaceTaskSessionAttemptModel(
            id="accepted-judge-attempt",
            workspace_task_id="accepted-node-task",
            root_goal_task_id="root-task-1",
            workspace_id="workspace-1",
            attempt_number=1,
            status="awaiting_leader_adjudication",
            conversation_id="accepted-conversation",
            worker_agent_id="worker-agent",
            leader_agent_id=BUILTIN_SISYPHUS_ID,
            leader_feedback=(
                "durable plan verifier passed code checks; awaiting harness-native pipeline evidence"
            ),
            adjudication_reason="pipeline_gate_pending",
            candidate_artifacts_json=["src/swarm/service.ts", "commit_ref:abc1234"],
            candidate_verifications_json=["test_run:swarm 36/36 tests passed"],
        )
    )
    plan.replace_node(
        replace(
            leaf,
            intent=TaskIntent.DONE,
            execution=TaskExecution.IDLE,
            current_attempt_id="accepted-judge-attempt",
            workspace_task_id="accepted-node-task",
            metadata={
                **dict(leaf.metadata or {}),
                "last_verification_judge_verdict": "accepted",
                "last_verification_summary": "agent supervisor accepted current attempt",
                "verified_commit_ref": "abc1234",
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
        batch_size=1,
    )

    assert await worker.run_once() == 1
    attempt = await db_session.get(WorkspaceTaskSessionAttemptModel, "accepted-judge-attempt")
    assert attempt is not None
    assert attempt.status == "accepted"
    assert attempt.adjudication_reason == "supervisor_decision_accept_node_reconciled"
    task = await db_session.get(WorkspaceTaskModel, "accepted-node-task")
    assert task is not None
    assert task.status == "done"
    assert task.metadata_json["durable_plan_verdict"] == "accepted"
    assert task.metadata_json["last_attempt_status"] == "accepted"
    loaded = await SqlPlanRepository(db_session).get(plan.id)
    assert loaded is not None
    reconciled_leaf = loaded.nodes[leaf.node_id]
    assert reconciled_leaf.metadata["terminal_attempt_status"] == "accepted"
    assert reconciled_leaf.metadata["last_verification_attempt_id"] == "accepted-judge-attempt"


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
        batch_size=1,
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
async def test_supervisor_tick_retries_parent_done_attempt_that_already_has_output(
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
            id="parent-done-output-task",
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
                CURRENT_ATTEMPT_ID: "cancelled-after-parent-done",
            },
        )
    )
    db_session.add_all(
        [
            WorkspaceTaskSessionAttemptModel(
                id="accepted-before-parent-done",
                workspace_task_id="parent-done-output-task",
                root_goal_task_id="root-task-1",
                workspace_id="workspace-1",
                attempt_number=1,
                status="accepted",
                conversation_id="accepted-conversation",
                worker_agent_id="worker-agent",
                leader_agent_id=BUILTIN_SISYPHUS_ID,
                leader_feedback="accepted before recovery sweep",
                candidate_artifacts_json=["docs/OLD.md", "commit_ref:20a9cefe"],
                candidate_verifications_json=["test_run:pytest old", "commit_ref:20a9cefe"],
            ),
            WorkspaceTaskSessionAttemptModel(
                id="cancelled-after-parent-done",
                workspace_task_id="parent-done-output-task",
                root_goal_task_id="root-task-1",
                workspace_id="workspace-1",
                attempt_number=2,
                status="cancelled",
                conversation_id="cancelled-conversation",
                worker_agent_id="worker-agent",
                leader_agent_id=BUILTIN_SISYPHUS_ID,
                leader_feedback="recovery:parent_done",
                adjudication_reason="recovery:parent_done",
                candidate_artifacts_json=["docs/NEW.md", "commit_ref:766ebce"],
                candidate_verifications_json=["test_run:pytest new", "commit_ref:766ebce"],
            ),
        ]
    )
    plan.replace_node(
        replace(
            leaf,
            intent=TaskIntent.DONE,
            execution=TaskExecution.IDLE,
            current_attempt_id="accepted-before-parent-done",
            workspace_task_id="parent-done-output-task",
            metadata={
                "terminal_attempt_status": "accepted",
                "terminal_attempt_superseded_attempt_id": "cancelled-after-parent-done",
                "terminal_attempt_superseded_status": "cancelled",
                "terminal_attempt_superseded_reason": "recovery:parent_done",
                "last_verification_attempt_id": "accepted-before-parent-done",
                "last_verification_passed": True,
                "verified_commit_ref": "20a9cefe",
                "worktree_integration_status": "failed",
                "worktree_integration_summary": "fatal: refusing to merge unrelated histories",
                "worktree_integration_worktree_path": (
                    "/workspace/.memstack/worktrees/accepted-before-parent-done"
                ),
                "worktree_integration_dirty_signature": None,
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
        batch_size=1,
    )

    assert await worker.run_once() == 1
    loaded = await SqlPlanRepository(db_session).get(plan.id)
    assert loaded is not None
    retried_leaf = loaded.leaf_tasks()[0]
    assert dispatched == [retried_leaf.id]
    assert retried_leaf.intent is TaskIntent.IN_PROGRESS
    assert retried_leaf.execution is TaskExecution.DISPATCHED
    assert retried_leaf.current_attempt_id == f"retry-{retried_leaf.id}"
    assert retried_leaf.metadata["terminal_attempt_retry_reason"] == (
        "superseded_parent_done_attempt_has_output"
    )
    assert "terminal_attempt_status" not in retried_leaf.metadata


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
        batch_size=1,
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
async def test_terminal_reconcile_accepts_attempt_when_expected_commit_is_later_ref(
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
            id="multi-ref-task",
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
                CURRENT_ATTEMPT_ID: "accepted-multi-ref",
            },
        )
    )
    db_session.add(
        WorkspaceTaskSessionAttemptModel(
            id="accepted-multi-ref",
            workspace_task_id="multi-ref-task",
            root_goal_task_id="root-task-1",
            workspace_id="workspace-1",
            attempt_number=1,
            status="accepted",
            conversation_id="multi-ref-conversation",
            worker_agent_id="worker-agent",
            leader_agent_id=BUILTIN_SISYPHUS_ID,
            leader_feedback="accepted after verifier repair",
            candidate_artifacts_json=[
                "commit_ref:1111111",
                "changed_file:frontend/src/app/(app)/swarm/page.tsx",
                "commit_ref:2222222",
            ],
            candidate_verifications_json=["test_run:tsc --noEmit"],
        )
    )
    plan.replace_node(
        replace(
            leaf,
            intent=TaskIntent.BLOCKED,
            execution=TaskExecution.IDLE,
            current_attempt_id=None,
            workspace_task_id="multi-ref-task",
            feature_checkpoint=FeatureCheckpoint(
                feature_id="feature-multi-ref",
                sequence=1,
                title="Implement routes",
                base_ref="HEAD",
                commit_ref="2222222",
            ),
            metadata={
                **dict(leaf.metadata or {}),
                "last_verification_attempt_id": "accepted-multi-ref",
                "last_verification_passed": True,
                "terminal_attempt_retry_reason": "accepted_attempt_commit_mismatch",
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

    assert changed is True
    loaded = await SqlPlanRepository(db_session).get(plan.id)
    assert loaded is not None
    reconciled_leaf = loaded.leaf_tasks()[0]
    assert reconciled_leaf.intent is TaskIntent.DONE
    assert reconciled_leaf.execution is TaskExecution.IDLE
    assert reconciled_leaf.current_attempt_id == "accepted-multi-ref"
    assert reconciled_leaf.metadata["terminal_attempt_status"] == "accepted"
    assert reconciled_leaf.metadata["last_verification_attempt_id"] == "accepted-multi-ref"
    assert reconciled_leaf.metadata["candidate_artifacts"] == [
        "commit_ref:1111111",
        "changed_file:frontend/src/app/(app)/swarm/page.tsx",
        "commit_ref:2222222",
    ]
    assert "terminal_attempt_retry_reason" not in reconciled_leaf.metadata


@pytest.mark.asyncio
async def test_terminal_reconcile_uses_last_verified_attempt_when_checkpoint_is_stale(
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
            id="stale-checkpoint-task",
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
                CURRENT_ATTEMPT_ID: "accepted-stale-checkpoint",
            },
        )
    )
    db_session.add(
        WorkspaceTaskSessionAttemptModel(
            id="accepted-stale-checkpoint",
            workspace_task_id="stale-checkpoint-task",
            root_goal_task_id="root-task-1",
            workspace_id="workspace-1",
            attempt_number=1,
            status="accepted",
            conversation_id="stale-checkpoint-conversation",
            worker_agent_id="worker-agent",
            leader_agent_id=BUILTIN_SISYPHUS_ID,
            leader_feedback="accepted after verifier repair",
            candidate_artifacts_json=[
                "commit_ref:187edd7",
                "changed_file:frontend/src/app/(app)/swarm/page.tsx",
            ],
            candidate_verifications_json=["worker_report:completed"],
        )
    )
    plan.replace_node(
        replace(
            leaf,
            intent=TaskIntent.BLOCKED,
            execution=TaskExecution.IDLE,
            current_attempt_id=None,
            workspace_task_id="stale-checkpoint-task",
            feature_checkpoint=FeatureCheckpoint(
                feature_id="feature-stale-checkpoint",
                sequence=1,
                title="Implement routes",
                base_ref="HEAD",
                commit_ref="203a9e1",
            ),
            metadata={
                **dict(leaf.metadata or {}),
                "last_verification_attempt_id": "accepted-stale-checkpoint",
                "last_verification_passed": True,
                "verification_evidence_refs": [
                    "commit_ref:187edd7",
                    "commit_ref:203a9e1",
                ],
                "verified_commit_ref": "203a9e1",
                "terminal_attempt_retry_reason": "accepted_attempt_commit_mismatch",
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

    assert changed is True
    loaded = await SqlPlanRepository(db_session).get(plan.id)
    assert loaded is not None
    reconciled_leaf = loaded.leaf_tasks()[0]
    assert reconciled_leaf.intent is TaskIntent.DONE
    assert reconciled_leaf.current_attempt_id == "accepted-stale-checkpoint"
    assert reconciled_leaf.metadata["terminal_attempt_status"] == "accepted"
    assert reconciled_leaf.metadata["candidate_artifacts"] == [
        "commit_ref:187edd7",
        "changed_file:frontend/src/app/(app)/swarm/page.tsx",
    ]
    assert "terminal_attempt_retry_reason" not in reconciled_leaf.metadata


@pytest.mark.asyncio
async def test_terminal_reconcile_accepts_no_output_attempt_verified_with_expected_commit(
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
            id="no-output-accepted-task",
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
                CURRENT_ATTEMPT_ID: "accepted-no-output",
            },
        )
    )
    db_session.add(
        WorkspaceTaskSessionAttemptModel(
            id="accepted-no-output",
            workspace_task_id="no-output-accepted-task",
            root_goal_task_id="root-task-1",
            workspace_id="workspace-1",
            attempt_number=1,
            status="accepted",
            conversation_id="no-output-conversation",
            worker_agent_id="worker-agent",
            leader_agent_id=BUILTIN_SISYPHUS_ID,
            leader_feedback="accepted after runtime-infra verification",
            candidate_artifacts_json=[],
            candidate_verifications_json=[],
        )
    )
    plan.replace_node(
        replace(
            leaf,
            intent=TaskIntent.DONE,
            execution=TaskExecution.IDLE,
            current_attempt_id="accepted-no-output",
            workspace_task_id="no-output-accepted-task",
            feature_checkpoint=FeatureCheckpoint(
                feature_id="feature-no-output",
                sequence=1,
                title="Verify deploy",
                worktree_path="/workspace/.memstack/worktrees/accepted-no-output",
                branch_name="workspace/no-output",
                base_ref="old-base",
                commit_ref="2d146b0",
            ),
            metadata={
                **dict(leaf.metadata or {}),
                "last_verification_attempt_id": "accepted-no-output",
                "last_verification_passed": True,
                "verified_commit_ref": "2d146b0",
                "worktree_integration_status": "failed",
                "worktree_integration_worktree_path": (
                    "/workspace/.memstack/worktrees/accepted-no-output"
                ),
                "terminal_attempt_retry_reason": "accepted_attempt_commit_mismatch",
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

    assert changed is True
    loaded = await SqlPlanRepository(db_session).get(plan.id)
    assert loaded is not None
    reconciled_leaf = loaded.leaf_tasks()[0]
    assert reconciled_leaf.intent is TaskIntent.DONE
    assert reconciled_leaf.execution is TaskExecution.IDLE
    assert reconciled_leaf.current_attempt_id == "accepted-no-output"
    assert reconciled_leaf.feature_checkpoint is not None
    assert reconciled_leaf.feature_checkpoint.worktree_path is None
    assert reconciled_leaf.feature_checkpoint.branch_name is None
    assert reconciled_leaf.feature_checkpoint.base_ref == "HEAD"
    assert reconciled_leaf.feature_checkpoint.commit_ref is None
    assert reconciled_leaf.metadata["terminal_attempt_status"] == "accepted"
    assert reconciled_leaf.metadata["last_verification_attempt_id"] == "accepted-no-output"
    assert "terminal_attempt_retry_reason" not in reconciled_leaf.metadata
    assert "verified_commit_ref" not in reconciled_leaf.metadata
    assert "worktree_integration_status" not in reconciled_leaf.metadata


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
        batch_size=1,
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
        batch_size=1,
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
                    AgentDefinitionModel.name.like("workspace-plan-workerproject1-%")
                )
            )
        )
        .scalars()
        .all()
    )
    assert {agent.name for agent in created_agents} == {
        "workspace-plan-workerproject1-architect",
        "workspace-plan-workerproject1-builder",
        "workspace-plan-workerproject1-verifier",
    }
    assert all(agent.metadata_json.get("workspace_id") is None for agent in created_agents)
    assert all(
        agent.metadata_json.get("team_definition_scope") == "project"
        for agent in created_agents
    )


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
        batch_size=1,
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
        batch_size=1,
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
        batch_size=1,
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
    await _merge_task_metadata(
        db_session,
        leaf.workspace_task_id,
        {
            "durable_plan_raw_verification_summary": (
                "verification failed while awaiting pipeline recovery"
            ),
        },
    )

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
    redispatched_task = await SqlWorkspaceTaskRepository(db_session).find_by_id(
        redispatched_leaf.workspace_task_id or ""
    )
    assert redispatched_task is not None
    assert (
        redispatched_task.metadata["durable_plan_raw_verification_summary"]
        == "verification failed while awaiting pipeline recovery"
    )

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
                "terminal_attempt_retry_reason": "worktree_integration_failed",
                "worktree_integration_failed_previous_attempt_id": "attempt-old",
                "worktree_integration_failed_previous_commit_ref": "abc1234",
                "worktree_integration_failed_previous_summary": (
                    "status=failed\nreason=merge_failed_aborted\n"
                    "CONFLICT (add/add): Merge conflict in src/example.ts"
                ),
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
        batch_size=1,
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
    assert "worktree_integration_failure" in str(launched[0]["repair_brief_prompt"])
    assert "inspect the current main checkout" in str(launched[0]["repair_brief_prompt"])
    assert "avoid reintroducing stale conflicting content" in str(
        launched[0]["repair_brief_prompt"]
    )
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
        batch_size=1,
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
        batch_size=1,
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
async def test_handoff_resume_handler_skips_supervisor_disposed_node(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_and_plan(db_session)
    db_session.add_all(
        [
            WorkspaceTaskModel(
                id="disposed-task",
                workspace_id="workspace-1",
                title="Disposed task",
                description="",
                created_by="worker-user-1",
                status="in_progress",
                priority=0,
                assignee_agent_id="worker-agent",
                metadata_json={
                    AUTONOMY_SCHEMA_VERSION_KEY: 1,
                    TASK_ROLE: "execution_task",
                    ROOT_GOAL_TASK_ID: "root-task-1",
                    WORKSPACE_PLAN_ID: "worker-plan-1",
                    WORKSPACE_PLAN_NODE_ID: "disposed-node",
                },
            ),
            WorkspacePlanEventModel(
                id="dispose-event-handoff",
                plan_id="worker-plan-1",
                workspace_id="workspace-1",
                node_id="disposed-node",
                attempt_id="previous-attempt",
                event_type="supervisor_decision_completed",
                source="workspace_plan_verifier",
                payload_json={"action": "dispose_node"},
                created_at=datetime.now(UTC),
            ),
        ]
    )
    repo = SqlWorkspacePlanOutboxRepository(db_session)
    item = await repo.enqueue(
        plan_id="worker-plan-1",
        workspace_id="workspace-1",
        event_type=HANDOFF_RESUME_EVENT,
        payload={
            "workspace_id": "workspace-1",
            "task_id": "disposed-task",
            "node_id": "disposed-node",
            "worker_agent_id": "worker-agent",
            "actor_user_id": "worker-user-1",
            "leader_agent_id": BUILTIN_SISYPHUS_ID,
            "previous_attempt_id": "previous-attempt",
            "root_goal_task_id": "root-task-1",
            "summary": "snapshot thought this was stale",
            "force_schedule": True,
        },
    )
    await db_session.commit()

    worker = WorkspacePlanOutboxWorker(
        session_factory=_session_factory(db_session),
        handlers={HANDOFF_RESUME_EVENT: make_handoff_resume_handler()},
        worker_id="worker-b",
        batch_size=1,
    )

    assert await worker.run_once() == 1
    completed = await repo.get_by_id(item.id)
    assert completed is not None
    assert completed.status == "completed"
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
        batch_size=1,
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
        batch_size=1,
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


async def _merge_task_metadata(
    db_session: AsyncSession,
    task_id: str | None,
    metadata: Mapping[str, object],
) -> None:
    assert task_id is not None
    task = await db_session.get(WorkspaceTaskModel, task_id)
    assert task is not None
    task.metadata_json = {**dict(task.metadata_json or {}), **dict(metadata)}
    await db_session.flush()


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


async def _seed_ready_plan(
    db_session: AsyncSession,
    *,
    workspace_id: str,
    plan_id: str,
    root_task_id: str,
) -> None:
    plan = Plan(
        id=plan_id,
        workspace_id=workspace_id,
        goal_id=PlanNodeId(f"{plan_id}-goal"),
        status=PlanStatus.ACTIVE,
    )
    plan.add_node(
        PlanNode(
            id=f"{plan_id}-goal",
            plan_id=plan.id,
            parent_id=None,
            kind=PlanNodeKind.GOAL,
            title="Root goal",
            intent=TaskIntent.IN_PROGRESS,
            execution=TaskExecution.IDLE,
            workspace_task_id=root_task_id,
        )
    )
    plan.add_node(
        PlanNode(
            id=f"{plan_id}-task",
            plan_id=plan.id,
            parent_id=plan.goal_id,
            kind=PlanNodeKind.TASK,
            title="Implement root goal",
            intent=TaskIntent.TODO,
            execution=TaskExecution.IDLE,
            workspace_task_id=f"{plan_id}-task-model",
        )
    )
    await SqlPlanRepository(db_session).save(plan)


@pytest.mark.unit
async def test_leader_execution_team_reuses_project_scoped_agent_definitions(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_only(db_session, include_worker=False)
    await _seed_ready_plan(
        db_session,
        workspace_id="workspace-1",
        plan_id="team-plan-1",
        root_task_id="root-task-1",
    )
    db_session.add_all(
        [
            WorkspaceModel(
                id="workspace-2",
                tenant_id="worker-tenant-1",
                project_id="worker-project-1",
                name="Second Worker Workspace",
                description="",
                created_by="worker-user-1",
                is_archived=False,
                metadata_json={},
            ),
            WorkspaceMemberModel(
                id="workspace-member-2",
                workspace_id="workspace-2",
                user_id="worker-user-1",
                role="owner",
                invited_by="worker-user-1",
            ),
            WorkspaceTaskModel(
                id="root-task-2",
                workspace_id="workspace-2",
                title="Root goal",
                description="Root goal for reused worker definitions",
                created_by="worker-user-1",
                status="todo",
                priority=0,
                metadata_json={
                    AUTONOMY_SCHEMA_VERSION_KEY: 1,
                    TASK_ROLE: "goal_root",
                },
            ),
        ]
    )
    await db_session.flush()
    await _seed_ready_plan(
        db_session,
        workspace_id="workspace-2",
        plan_id="team-plan-2",
        root_task_id="root-task-2",
    )

    await _ensure_leader_execution_team(
        session=db_session,
        workspace_id="workspace-1",
        leader_agent_id=BUILTIN_SISYPHUS_ID,
    )
    await _ensure_leader_execution_team(
        session=db_session,
        workspace_id="workspace-2",
        leader_agent_id=BUILTIN_SISYPHUS_ID,
    )

    created_agents = (
        (
            await db_session.execute(
                select(AgentDefinitionModel).where(
                    AgentDefinitionModel.metadata_json["created_by"].as_string()
                    == "workspace_plan_team_setup"
                )
            )
        )
        .scalars()
        .all()
    )
    assert {agent.name for agent in created_agents} == {
        "workspace-plan-workerproject1-architect",
        "workspace-plan-workerproject1-builder",
        "workspace-plan-workerproject1-verifier",
    }
    assert all(agent.metadata_json.get("workspace_id") is None for agent in created_agents)
    assert all(
        agent.metadata_json.get("team_definition_scope") == "project" for agent in created_agents
    )

    bindings = (
        (
            await db_session.execute(
                select(WorkspaceAgentModel).where(WorkspaceAgentModel.is_active.is_(True))
            )
        )
        .scalars()
        .all()
    )
    assert len(bindings) == 6
    assert len({binding.agent_id for binding in bindings}) == 3


@pytest.mark.unit
async def test_leader_execution_team_supersedes_legacy_workspace_scoped_agent_definition(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_only(db_session, include_worker=False)
    await _seed_ready_plan(
        db_session,
        workspace_id="workspace-1",
        plan_id="legacy-team-plan",
        root_task_id="root-task-1",
    )
    db_session.add_all(
        [
            AgentDefinitionModel(
                id="legacy-workspace-architect",
                tenant_id="worker-tenant-1",
                project_id="worker-project-1",
                name="workspace-workspace1-architect",
                display_name="Workspace Architect",
                system_prompt="You are a legacy workspace-scoped worker.",
                trigger_description="Legacy workspace worker",
                allowed_tools=[],
                allowed_skills=[],
                allowed_mcp_servers=[],
                source="database",
                agent_to_agent_enabled=True,
                agent_to_agent_allowlist=[BUILTIN_SISYPHUS_ID],
                discoverable=True,
                metadata_json={
                    "created_by": "leader_team_setup",
                    "workspace_id": "workspace-1",
                    "workspace_role": "execution_worker",
                    "max_iterations_explicit": False,
                },
            ),
            WorkspaceAgentModel(
                id="legacy-architect-binding",
                workspace_id="workspace-1",
                agent_id="legacy-workspace-architect",
                display_name="Workspace Architect",
                description=None,
                config_json={
                    "workspace_role": "execution_worker",
                    "capabilities": ["architecture"],
                },
                is_active=True,
                label="Architect",
                status="idle",
            ),
        ]
    )
    await db_session.flush()

    await _ensure_leader_execution_team(
        session=db_session,
        workspace_id="workspace-1",
        leader_agent_id=BUILTIN_SISYPHUS_ID,
    )

    legacy_agent = await db_session.get(AgentDefinitionModel, "legacy-workspace-architect")
    assert legacy_agent is not None
    assert legacy_agent.discoverable is False
    assert legacy_agent.enabled is True
    assert legacy_agent.metadata_json["superseded_by"] == "project_scoped_workspace_plan_team"

    shared_agents = (
        (
            await db_session.execute(
                select(AgentDefinitionModel).where(
                    AgentDefinitionModel.metadata_json["team_definition_scope"].as_string()
                    == "project"
                )
            )
        )
        .scalars()
        .all()
    )
    assert {agent.name for agent in shared_agents} == {
        "workspace-plan-workerproject1-architect",
        "workspace-plan-workerproject1-builder",
        "workspace-plan-workerproject1-verifier",
    }

    legacy_binding = await db_session.get(WorkspaceAgentModel, "legacy-architect-binding")
    assert legacy_binding is not None
    assert legacy_binding.agent_id == "legacy-workspace-architect"
    assert legacy_binding.is_active is True


@pytest.mark.unit
async def test_resolve_actor_user_id_falls_back_when_payload_user_is_not_member(
    db_session: AsyncSession,
) -> None:
    await _seed_workspace_only(db_session)

    assert (
        await _resolve_actor_user_id(
            db_session,
            "workspace-1",
            {"actor_user_id": "worker-user-1"},
        )
        == "worker-user-1"
    )
    assert (
        await _resolve_actor_user_id(
            db_session,
            "workspace-1",
            {"actor_user_id": "workspace-plan:system"},
        )
        == "worker-user-1"
    )
