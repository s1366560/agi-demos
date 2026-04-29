from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.application.schemas.workspace_agent_autonomy import GoalCandidateRecordModel
from src.application.services.workspace_mention_router import WorkspaceMentionRouter
from src.domain.model.workspace.workspace_task import WorkspaceTaskStatus
from src.infrastructure.agent.workspace.workspace_goal_runtime import (
    _ensure_execution_attempt,
    _launch_workspace_retry_attempt,
    adjudicate_workspace_worker_report,
    apply_workspace_worker_report,
    auto_complete_ready_root,
    maybe_materialize_workspace_goal_candidate,
    prepare_workspace_subagent_delegation,
    resolve_workspace_execution_task_for_delegate,
)
from src.infrastructure.agent.workspace_plan.system_actor import WORKSPACE_PLAN_SYSTEM_ACTOR_ID


def _candidate(decision: str = "adopt_existing_goal") -> GoalCandidateRecordModel:
    return GoalCandidateRecordModel(
        candidate_id="cand-1",
        candidate_text="Prepare rollback checklist",
        candidate_kind="existing" if decision == "adopt_existing_goal" else "inferred",
        source_refs=["task:root-1"] if decision == "adopt_existing_goal" else ["message:msg-1"],
        evidence_strength=0.85,
        source_breakdown=[
            {
                "source_type": "existing_root_task"
                if decision == "adopt_existing_goal"
                else "message_signal",
                "score": 0.85,
                "ref": "root-1" if decision == "adopt_existing_goal" else "message:msg-1",
            },
        ],
        freshness=1.0,
        urgency=0.8,
        user_intent_confidence=0.85,
        formalizable=decision == "formalize_new_goal",
        decision=decision,
    )


def _attempt(
    *,
    attempt_id: str = "attempt-1",
    attempt_number: int = 1,
    status: str = "running",
):
    attempt = MagicMock()
    attempt.id = attempt_id
    attempt.attempt_number = attempt_number
    attempt.status = MagicMock(value=status)
    return attempt


@pytest.mark.unit
class TestWorkspaceGoalRuntime:
    async def test_ensure_execution_attempt_does_not_persist_system_actor_marker(
        self,
    ) -> None:
        task = MagicMock()
        task.id = "task-1"
        task.workspace_id = "ws-1"
        task.assignee_agent_id = "worker-agent"
        task.metadata = {"root_goal_task_id": "root-1"}
        pending_attempt = _attempt(attempt_id="attempt-1", status="pending")
        running_attempt = _attempt(attempt_id="attempt-1", status="running")
        attempt_service = MagicMock()
        attempt_service.get_active_attempt = AsyncMock(return_value=None)
        attempt_service.create_attempt = AsyncMock(return_value=pending_attempt)
        attempt_service.mark_running = AsyncMock(return_value=running_attempt)

        result = await _ensure_execution_attempt(
            attempt_service=attempt_service,
            task=task,
            leader_agent_id=WORKSPACE_PLAN_SYSTEM_ACTOR_ID,
        )

        assert result is running_attempt
        attempt_service.create_attempt.assert_awaited_once()
        assert attempt_service.create_attempt.await_args.kwargs["leader_agent_id"] is None

    async def test_no_workspace_noop(self) -> None:
        session = AsyncMock()

        @asynccontextmanager
        async def fake_session_factory():
            yield session

        with (
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.async_session_factory",
                fake_session_factory,
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceRepository"
            ) as repo_cls,
        ):
            repo_cls.return_value.find_by_project = AsyncMock(return_value=[])
            await maybe_materialize_workspace_goal_candidate("p-1", "t-1", "u-1")

            repo_cls.return_value.find_by_project.assert_awaited_once()

    async def test_materializes_top_candidate_and_publishes(self) -> None:
        workspace = MagicMock()
        workspace.id = "ws-1"
        materialized_task = MagicMock()
        materialized_task.id = "root-1"
        materialized_task.title = "Prepare rollback checklist"
        materialized_task.description = None
        materialized_task.metadata = {"task_role": "goal_root"}

        session = AsyncMock()

        @asynccontextmanager
        async def fake_session_factory():
            yield session

        with (
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.async_session_factory",
                fake_session_factory,
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.get_redis_client",
                AsyncMock(return_value=object()),
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceRepository"
            ) as workspace_repo_cls,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskService"
            ) as task_service_cls,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlCyberObjectiveRepository"
            ) as objective_repo_cls,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceTaskRepository"
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlBlackboardRepository"
            ) as blackboard_repo_cls,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceMessageRepository"
            ) as message_repo_cls,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceGoalSensingService"
            ) as sensing_cls,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceGoalMaterializationService"
            ) as materializer_cls,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskEventPublisher"
            ) as publisher_cls,
            patch(
                "src.infrastructure.agent.workspace.goal_runtime.kickoff_v2_plan",
                new=AsyncMock(return_value=True),
            ) as kickoff,
        ):
            workspace_repo_cls.return_value.find_by_project = AsyncMock(return_value=[workspace])
            task_service = task_service_cls.return_value
            task_service.list_tasks = AsyncMock(return_value=[])
            objective_repo_cls.return_value.find_by_workspace = AsyncMock(return_value=[])
            blackboard_repo_cls.return_value.list_posts_by_workspace = AsyncMock(return_value=[])
            message_repo_cls.return_value.find_by_workspace = AsyncMock(return_value=[])
            sensing_cls.return_value.sense_candidates.return_value = [_candidate()]
            materializer = materializer_cls.return_value
            materializer.materialize_candidate = AsyncMock(return_value=materialized_task)
            publisher = publisher_cls.return_value
            publisher.publish_pending_events = AsyncMock(return_value=None)

            await maybe_materialize_workspace_goal_candidate("p-1", "t-1", "u-1")

            materializer.materialize_candidate.assert_awaited_once()
            session.commit.assert_awaited_once()
            publisher.publish_pending_events.assert_awaited_once()
            kickoff.assert_awaited_once()

    async def test_skips_materialization_when_no_existing_root_candidate_exists(self) -> None:
        workspace = MagicMock()
        workspace.id = "ws-1"
        session = AsyncMock()

        @asynccontextmanager
        async def fake_session_factory():
            yield session

        with (
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.async_session_factory",
                fake_session_factory,
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.get_redis_client",
                AsyncMock(return_value=object()),
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceRepository"
            ) as workspace_repo_cls,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskService"
            ) as task_service_cls,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlCyberObjectiveRepository"
            ) as objective_repo_cls,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceTaskRepository"
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlBlackboardRepository"
            ) as blackboard_repo_cls,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceMessageRepository"
            ) as message_repo_cls,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceGoalSensingService"
            ) as sensing_cls,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceGoalMaterializationService"
            ) as materializer_cls,
        ):
            workspace_repo_cls.return_value.find_by_project = AsyncMock(return_value=[workspace])
            task_service = task_service_cls.return_value
            task_service.list_tasks = AsyncMock(return_value=[])
            objective_repo_cls.return_value.find_by_workspace = AsyncMock(return_value=[])
            blackboard_repo_cls.return_value.list_posts_by_workspace = AsyncMock(return_value=[])
            message_repo_cls.return_value.find_by_workspace = AsyncMock(return_value=[])
            sensing_cls.return_value.sense_candidates.return_value = [
                _candidate("formalize_new_goal")
            ]

            result = await maybe_materialize_workspace_goal_candidate("p-1", "t-1", "u-1")

            assert result is None
            materializer_cls.return_value.materialize_candidate.assert_not_called()

    async def test_materialization_kicks_off_v2_plan_without_v1_task_creation(self) -> None:
        workspace = MagicMock()
        workspace.id = "ws-1"
        root_task = MagicMock()
        root_task.id = "root-1"
        root_task.title = "Prepare rollback checklist"
        root_task.description = "desc"
        root_task.metadata = {"task_role": "goal_root"}

        session = AsyncMock()

        @asynccontextmanager
        async def fake_session_factory():
            yield session

        with (
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.async_session_factory",
                fake_session_factory,
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.get_redis_client",
                AsyncMock(return_value=object()),
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceRepository"
            ) as workspace_repo_cls,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskService"
            ) as task_service_cls,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlCyberObjectiveRepository"
            ) as objective_repo_cls,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceTaskRepository"
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlBlackboardRepository"
            ) as blackboard_repo_cls,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceMessageRepository"
            ) as message_repo_cls,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceGoalSensingService"
            ) as sensing_cls,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceGoalMaterializationService"
            ) as materializer_cls,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskEventPublisher"
            ) as publisher_cls,
            patch(
                "src.infrastructure.agent.workspace.goal_runtime.kickoff_v2_plan",
                new=AsyncMock(return_value=True),
            ) as kickoff,
        ):
            workspace_repo_cls.return_value.find_by_project = AsyncMock(return_value=[workspace])
            task_service = task_service_cls.return_value
            task_service.list_tasks = AsyncMock(return_value=[])
            objective_repo_cls.return_value.find_by_workspace = AsyncMock(return_value=[])
            blackboard_repo_cls.return_value.list_posts_by_workspace = AsyncMock(return_value=[])
            message_repo_cls.return_value.find_by_workspace = AsyncMock(return_value=[])
            sensing_cls.return_value.sense_candidates.return_value = [_candidate()]
            materializer = materializer_cls.return_value
            materializer.materialize_candidate = AsyncMock(return_value=root_task)
            publisher = publisher_cls.return_value
            publisher.publish_pending_events = AsyncMock(return_value=None)

            create_task = AsyncMock()
            assign_task = AsyncMock()
            start_task = AsyncMock()
            with (
                patch(
                    "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskCommandService.create_task",
                    new=create_task,
                ),
                patch(
                    "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskCommandService.assign_task_to_agent",
                    new=assign_task,
                ),
                patch(
                    "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskCommandService.start_task",
                    new=start_task,
                ),
            ):
                await maybe_materialize_workspace_goal_candidate(
                    "p-1",
                    "t-1",
                    "u-1",
                    user_query="Prepare rollback checklist",
                )

            create_task.assert_not_awaited()
            assign_task.assert_not_awaited()
            start_task.assert_not_awaited()
            kickoff.assert_awaited_once_with(
                workspace_id="ws-1",
                title="Prepare rollback checklist",
                description="desc",
                created_by="u-1",
                root_task_id="root-1",
                leader_agent_id=WORKSPACE_PLAN_SYSTEM_ACTOR_ID,
            )

    async def test_apply_worker_report_uses_leader_side_task_mutations(self) -> None:
        task = MagicMock()
        task.id = "child-1"
        task.workspace_id = "ws-1"
        task.assignee_agent_id = "worker-a"
        task.status = MagicMock(value="todo")
        task.metadata = {
            "autonomy_schema_version": 1,
            "task_role": "execution_task",
            "root_goal_task_id": "root-1",
            "lineage_source": "agent",
            "derived_from_internal_plan_step": "t1",
            "execution_state": {
                "phase": "todo",
                "last_agent_reason": "workspace_plan.dispatch_execution_task",
                "last_agent_action": "created",
                "updated_by_actor_type": "agent",
                "updated_by_actor_id": "leader-agent",
                "updated_at": "2026-04-16T03:00:00Z",
            },
            "evidence_refs": [],
        }

        session = AsyncMock()

        @asynccontextmanager
        async def fake_session_factory():
            yield session

        with (
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.async_session_factory",
                fake_session_factory,
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.get_redis_client",
                AsyncMock(return_value=object()),
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceRepository"
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceMemberRepository"
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceAgentRepository"
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceTaskRepository"
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskService"
            ) as task_service_cls,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime._build_attempt_service"
            ) as attempt_service_builder,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskEventPublisher"
            ) as publisher_cls,
        ):
            task_service = task_service_cls.return_value
            task_service.get_task = AsyncMock(return_value=task)
            attempt_service = MagicMock()
            pending_attempt = _attempt(status="pending")
            pending_attempt.worker_agent_id = "worker-a"
            running_attempt = _attempt(status="running")
            running_attempt.worker_agent_id = "worker-a"
            attempt_service.get_active_attempt = AsyncMock(return_value=None)
            attempt_service.create_attempt = AsyncMock(return_value=pending_attempt)
            attempt_service.mark_running = AsyncMock(return_value=running_attempt)
            attempt_service.record_candidate_output = AsyncMock(
                return_value=_attempt(status="awaiting_leader_adjudication")
            )
            attempt_service_builder.return_value = attempt_service
            publisher = publisher_cls.return_value
            publisher.publish_pending_events = AsyncMock(return_value=None)

            updated_task = MagicMock()
            updated_task.id = "child-1"
            updated_task.status = MagicMock(value="todo")
            updated_task.metadata = dict(task.metadata)

            started_task = MagicMock()
            started_task.id = "child-1"
            started_task.status = MagicMock(value="in_progress")

            with (
                patch(
                    "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskCommandService.update_task",
                    new=AsyncMock(return_value=updated_task),
                ) as update_mock,
                patch(
                    "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskCommandService.start_task",
                    new=AsyncMock(return_value=started_task),
                ) as start_mock,
            ):
                result = await apply_workspace_worker_report(
                    workspace_id="ws-1",
                    root_goal_task_id="root-1",
                    task_id="child-1",
                    actor_user_id="u-1",
                    worker_agent_id="worker-a",
                    report_type="progress",
                    summary="正在执行回滚步骤",
                    artifacts=["artifact:file-1"],
                    leader_agent_id="leader-agent",
                )

            assert result is started_task
            metadata = update_mock.await_args.kwargs["metadata"]
            assert metadata["evidence_refs"] == ["artifact:file-1"]
            assert metadata["execution_state"]["updated_by_actor_id"] == "worker-a"
            assert metadata["current_attempt_id"] == "attempt-1"
            assert (
                update_mock.await_args.kwargs["reason"]
                == "workspace_goal_runtime.worker_report.progress.metadata"
            )
            assert (
                start_mock.await_args.kwargs["reason"]
                == "workspace_goal_runtime.worker_report.progress.start"
            )
            attempt_service.record_candidate_output.assert_not_awaited()

    async def test_apply_worker_report_parses_structured_browser_verdict_as_candidate_evidence(
        self,
    ) -> None:
        task = MagicMock()
        task.id = "child-browser-1"
        task.workspace_id = "ws-1"
        task.assignee_agent_id = "worker-a"
        task.status = MagicMock(value="in_progress")
        task.metadata = {
            "autonomy_schema_version": 1,
            "task_role": "execution_task",
            "root_goal_task_id": "root-1",
            "lineage_source": "agent",
            "derived_from_internal_plan_step": "browser-check",
            "execution_state": {
                "phase": "in_progress",
                "last_agent_reason": "workspace_goal_runtime.prepare_subagent_delegation.start",
                "last_agent_action": "start",
                "updated_by_actor_type": "agent",
                "updated_by_actor_id": "leader-agent",
                "updated_at": "2026-04-16T03:00:00Z",
            },
            "evidence_refs": ["artifact:existing"],
            "execution_verifications": ["worker_report:started"],
        }

        session = AsyncMock()

        @asynccontextmanager
        async def fake_session_factory():
            yield session

        with (
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.async_session_factory",
                fake_session_factory,
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.get_redis_client",
                AsyncMock(return_value=object()),
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceRepository"
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceMemberRepository"
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceAgentRepository"
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceTaskRepository"
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskService"
            ) as task_service_cls,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime._build_attempt_service"
            ) as attempt_service_builder,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskEventPublisher"
            ) as publisher_cls,
        ):
            task_service = task_service_cls.return_value
            task_service.get_task = AsyncMock(return_value=task)
            attempt_service = MagicMock()
            running_attempt = _attempt(status="running")
            running_attempt.worker_agent_id = "worker-a"
            attempt_service.get_active_attempt = AsyncMock(return_value=running_attempt)
            attempt_service.record_candidate_output = AsyncMock(
                return_value=_attempt(status="awaiting_leader_adjudication")
            )
            attempt_service_builder.return_value = attempt_service
            publisher = publisher_cls.return_value
            publisher.publish_pending_events = AsyncMock(return_value=None)

            with (
                patch(
                    "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskCommandService.update_task",
                    new=AsyncMock(return_value=task),
                ) as update_mock,
                patch(
                    "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskCommandService.complete_task",
                    new=AsyncMock(return_value=task),
                ) as complete_mock,
            ):
                result = await apply_workspace_worker_report(
                    workspace_id="ws-1",
                    root_goal_task_id="root-1",
                    task_id="child-browser-1",
                    conversation_id="conv-attempt-1",
                    actor_user_id="u-1",
                    worker_agent_id="worker-a",
                    report_type="completed",
                    summary=(
                        '{"summary":"Browser checks passed","verdict":"pass",'
                        '"verifications":["browser_assert:landing_page","screenshot_captured"],'
                        '"artifacts":["artifact:screenshot-1"],"verification_grade":"pass",'
                        '"commit_ref":"abc123","git_diff_summary":"1 file changed",'
                        '"changed_files":["src/ui.tsx"],"test_commands":["npm test"]}'
                    ),
                    artifacts=["artifact:trace-1"],
                    verifications=["preflight:read-progress", "preflight:git-status"],
                    leader_agent_id="leader-agent",
                )

            assert result is task
            metadata = update_mock.await_args.kwargs["metadata"]
            assert metadata["evidence_refs"] == [
                "artifact:existing",
                "artifact:trace-1",
                "artifact:screenshot-1",
                "commit_ref:abc123",
                "git_diff_summary:1 file changed",
                "changed_file:src/ui.tsx",
            ]
            assert metadata["execution_verifications"] == [
                "worker_report:started",
                "preflight:read-progress",
                "preflight:git-status",
                "browser_assert:landing_page",
                "screenshot_captured",
                "test_run:npm test",
                "worker_verdict:pass",
                "verification_grade:pass",
            ]
            assert metadata["pending_leader_adjudication"] is True
            assert metadata["last_worker_report_type"] == "completed"
            assert metadata["execution_state"]["phase"] == "in_progress"
            complete_mock.assert_not_awaited()
            attempt_service.record_candidate_output.assert_awaited_once()
            assert (
                attempt_service.record_candidate_output.await_args.kwargs["conversation_id"]
                == "conv-attempt-1"
            )

    async def test_apply_worker_report_is_idempotent_for_duplicate_terminal_reports(self) -> None:
        task = MagicMock()
        task.id = "child-dup-1"
        task.workspace_id = "ws-1"
        task.assignee_agent_id = "worker-a"
        task.status = MagicMock(value="in_progress")
        task.metadata = {
            "autonomy_schema_version": 1,
            "task_role": "execution_task",
            "root_goal_task_id": "root-1",
            "lineage_source": "agent",
            "derived_from_internal_plan_step": "dup-step",
            "execution_state": {
                "phase": "in_progress",
                "last_agent_reason": "workspace_goal_runtime.prepare_subagent_delegation.start",
                "last_agent_action": "start",
                "updated_by_actor_type": "agent",
                "updated_by_actor_id": "leader-agent",
                "updated_at": "2026-04-16T03:00:00Z",
            },
            "evidence_refs": [],
        }

        session = AsyncMock()

        @asynccontextmanager
        async def fake_session_factory():
            yield session

        with (
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.async_session_factory",
                fake_session_factory,
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.get_redis_client",
                AsyncMock(return_value=object()),
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceRepository"
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceMemberRepository"
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceAgentRepository"
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceTaskRepository"
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskService"
            ) as task_service_cls,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime._build_attempt_service"
            ) as attempt_service_builder,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskEventPublisher"
            ) as publisher_cls,
        ):
            task_service = task_service_cls.return_value
            task_service.get_task = AsyncMock(return_value=task)
            attempt_service = MagicMock()
            running_attempt = _attempt(status="running")
            running_attempt.worker_agent_id = "worker-a"
            attempt_service.get_active_attempt = AsyncMock(return_value=running_attempt)
            attempt_service.record_candidate_output = AsyncMock(
                return_value=_attempt(status="awaiting_leader_adjudication")
            )
            attempt_service_builder.return_value = attempt_service
            publisher = publisher_cls.return_value
            publisher.publish_pending_events = AsyncMock(return_value=None)

            async def update_task_side_effect(**kwargs: object) -> object:
                task.metadata = {**dict(task.metadata), **dict(kwargs["metadata"])}
                return task

            with (
                patch(
                    "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskCommandService.update_task",
                    new=AsyncMock(side_effect=update_task_side_effect),
                ) as update_mock,
                patch(
                    "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskCommandService.complete_task",
                    new=AsyncMock(return_value=task),
                ),
            ):
                first = await apply_workspace_worker_report(
                    workspace_id="ws-1",
                    root_goal_task_id="root-1",
                    task_id="child-dup-1",
                    actor_user_id="u-1",
                    worker_agent_id="worker-a",
                    report_type="completed",
                    summary='{"summary":"Done","artifacts":["artifact:one"]}',
                    artifacts=[],
                    leader_agent_id="leader-agent",
                    report_id="run-1",
                )
                second = await apply_workspace_worker_report(
                    workspace_id="ws-1",
                    root_goal_task_id="root-1",
                    task_id="child-dup-1",
                    actor_user_id="u-1",
                    worker_agent_id="worker-a",
                    report_type="completed",
                    summary='{"summary":"Done","artifacts":["artifact:one"]}',
                    artifacts=[],
                    leader_agent_id="leader-agent",
                    report_id="run-1",
                )

            assert first is task
            assert second is task
            assert update_mock.await_count == 1
            attempt_service.record_candidate_output.assert_awaited_once()

    async def test_apply_worker_report_ignores_late_terminal_report_for_terminal_attempt(
        self,
    ) -> None:
        task = MagicMock()
        task.id = "child-terminal-1"
        task.workspace_id = "ws-1"
        task.assignee_agent_id = "worker-a"
        task.status = MagicMock(value="done")
        task.metadata = {
            "autonomy_schema_version": 1,
            "task_role": "execution_task",
            "root_goal_task_id": "root-1",
            "lineage_source": "agent",
            "derived_from_internal_plan_step": "late-terminal",
            "last_worker_report_type": "completed",
        }

        session = AsyncMock()

        @asynccontextmanager
        async def fake_session_factory():
            yield session

        with (
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.async_session_factory",
                fake_session_factory,
            ),
            patch("src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceRepository"),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceMemberRepository"
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceAgentRepository"
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceTaskRepository"
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskService"
            ) as task_service_cls,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime._build_attempt_service"
            ) as attempt_service_builder,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskCommandService.update_task",
                new=AsyncMock(return_value=task),
            ) as update_mock,
        ):
            task_service = task_service_cls.return_value
            task_service.get_task = AsyncMock(return_value=task)
            attempt_service = MagicMock()
            accepted_attempt = _attempt(status="accepted")
            accepted_attempt.workspace_task_id = "child-terminal-1"
            accepted_attempt.worker_agent_id = "worker-a"
            attempt_service.get_attempt = AsyncMock(return_value=accepted_attempt)
            attempt_service.record_candidate_output = AsyncMock()
            attempt_service_builder.return_value = attempt_service

            result = await apply_workspace_worker_report(
                workspace_id="ws-1",
                root_goal_task_id="root-1",
                task_id="child-terminal-1",
                attempt_id="attempt-1",
                actor_user_id="u-1",
                worker_agent_id="worker-a",
                report_type="blocked",
                summary="Goal not achieved after 3 no-progress turns",
                artifacts=["artifact:late"],
                leader_agent_id="leader-agent",
                report_id="late-blocked",
            )

        assert result is task
        update_mock.assert_not_awaited()
        attempt_service.record_candidate_output.assert_not_awaited()
        session.commit.assert_not_awaited()

    @pytest.mark.parametrize(
        ("status", "updated_status_value", "expected_method", "expected_reason"),
        [
            (
                WorkspaceTaskStatus.IN_PROGRESS,
                "todo",
                "start_task",
                "workspace_goal_runtime.leader_adjudication.in_progress.start",
            ),
            (
                WorkspaceTaskStatus.DONE,
                "in_progress",
                "complete_task",
                "workspace_goal_runtime.leader_adjudication.completed.complete",
            ),
            (
                WorkspaceTaskStatus.BLOCKED,
                "in_progress",
                "block_task",
                "workspace_goal_runtime.leader_adjudication.blocked.block",
            ),
        ],
    )
    async def test_adjudicate_worker_report_applies_direct_leader_decision(  # noqa: PLR0915
        self,
        status: WorkspaceTaskStatus,
        updated_status_value: str,
        expected_method: str,
        expected_reason: str,
    ) -> None:
        task = MagicMock()
        task.id = "child-adjudicate-1"
        task.workspace_id = "ws-1"
        task.title = "Draft checklist"
        task.status = MagicMock(value="in_progress")
        task.metadata = {
            "autonomy_schema_version": 1,
            "task_role": "execution_task",
            "root_goal_task_id": "root-1",
            "current_attempt_id": "attempt-3",
            "lineage_source": "agent",
            "derived_from_internal_plan_step": "adj-step",
            "pending_leader_adjudication": True,
            "last_worker_report_summary": "Checklist drafted",
            "execution_state": {
                "phase": "pending_adjudication",
                "last_agent_reason": "workspace_goal_runtime.worker_report.completed:Checklist drafted",
                "last_agent_action": "await_leader_adjudication",
                "updated_by_actor_type": "agent",
                "updated_by_actor_id": "leader-agent",
                "updated_at": "2026-04-16T03:00:00Z",
            },
        }

        session = AsyncMock()

        @asynccontextmanager
        async def fake_session_factory():
            yield session

        with (
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.async_session_factory",
                fake_session_factory,
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.get_redis_client",
                AsyncMock(return_value=object()),
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceRepository"
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceMemberRepository"
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceAgentRepository"
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceTaskRepository"
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskService"
            ) as task_service_cls,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime._build_attempt_service"
            ) as attempt_service_builder,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskEventPublisher"
            ) as publisher_cls,
        ):
            task_service = task_service_cls.return_value
            task_service.get_task = AsyncMock(return_value=task)
            attempt_service = MagicMock()
            attempt_service.get_attempt = AsyncMock(
                return_value=_attempt(attempt_id="attempt-3", status="awaiting_leader_adjudication")
            )
            attempt_service.accept = AsyncMock(
                return_value=_attempt(attempt_id="attempt-3", status="accepted")
            )
            attempt_service.block = AsyncMock(
                return_value=_attempt(attempt_id="attempt-3", status="blocked")
            )
            attempt_service.reject = AsyncMock(
                return_value=_attempt(attempt_id="attempt-3", status="rejected")
            )
            attempt_service.create_attempt = AsyncMock(
                return_value=_attempt(attempt_id="attempt-4", attempt_number=2, status="pending")
            )
            attempt_service_builder.return_value = attempt_service
            publisher = publisher_cls.return_value
            publisher.publish_pending_events = AsyncMock(return_value=None)

            updated_task = MagicMock()
            updated_task.id = "child-adjudicate-1"
            updated_task.status = MagicMock(value=updated_status_value)
            updated_task.metadata = dict(task.metadata)

            final_task = MagicMock()
            final_task.id = "child-adjudicate-1"
            final_task.status = status

            with (
                patch(
                    "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskCommandService.update_task",
                    new=AsyncMock(return_value=updated_task),
                ) as update_mock,
                patch(
                    f"src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskCommandService.{expected_method}",
                    new=AsyncMock(return_value=final_task),
                ) as terminal_mock,
                patch(
                    "src.infrastructure.agent.workspace.workspace_goal_runtime._schedule_workspace_retry_attempt"
                ) as retry_schedule_mock,
            ):
                result = await adjudicate_workspace_worker_report(
                    workspace_id="ws-1",
                    task_id="child-adjudicate-1",
                    actor_user_id="u-1",
                    status=status,
                    leader_agent_id="leader-agent",
                )

            assert result is final_task
            first_update_call = update_mock.await_args_list[0]
            metadata = first_update_call.kwargs["metadata"]
            assert metadata["pending_leader_adjudication"] is False
            assert metadata["last_leader_adjudication_status"] == status.value
            assert metadata["execution_state"]["updated_by_actor_id"] == "leader-agent"
            assert (
                first_update_call.kwargs["reason"]
                == f"workspace_goal_runtime.leader_adjudication.{status.value}.metadata"
            )
            assert terminal_mock.await_args.kwargs["reason"] == expected_reason
            if status == WorkspaceTaskStatus.DONE:
                attempt_service.accept.assert_awaited_once()
                second_update_call = update_mock.await_args_list[-1]
                assert second_update_call.kwargs["metadata"]["last_attempt_status"] == "accepted"
                assert (
                    second_update_call.kwargs["metadata"]["last_worker_report_type"] == "completed"
                )
            elif status == WorkspaceTaskStatus.BLOCKED:
                attempt_service.block.assert_awaited_once()
                second_update_call = update_mock.await_args_list[-1]
                assert second_update_call.kwargs["metadata"]["last_attempt_status"] == "blocked"
            elif status == WorkspaceTaskStatus.IN_PROGRESS:
                attempt_service.reject.assert_awaited_once()
                attempt_service.create_attempt.assert_awaited_once()
                second_update_call = update_mock.await_args_list[-1]
                assert second_update_call.kwargs["metadata"]["last_attempt_status"] == "rejected"
                assert second_update_call.kwargs["metadata"]["current_attempt_id"] == "attempt-4"
                assert second_update_call.kwargs["metadata"]["current_attempt_number"] == 2
                retry_schedule_mock.assert_called_once_with(
                    workspace_id="ws-1",
                    root_goal_task_id="root-1",
                    workspace_task_id="child-adjudicate-1",
                    attempt_id="attempt-4",
                    actor_user_id="u-1",
                    leader_agent_id="leader-agent",
                    retry_feedback="Checklist drafted",
                )
            else:
                retry_schedule_mock.assert_not_called()

    async def test_launch_workspace_retry_attempt_creates_scoped_conversation_and_streams(
        self,
    ) -> None:
        workspace = MagicMock()
        workspace.id = "ws-1"
        workspace.project_id = "project-1"
        workspace.tenant_id = "tenant-1"

        session = AsyncMock()

        @asynccontextmanager
        async def fake_session_factory():
            yield session

        conversation_repo = MagicMock()
        conversation_repo.find_by_id = AsyncMock(return_value=None)
        conversation_repo.save = AsyncMock()

        captured: dict[str, object] = {}

        async def _stream_chat_v2(**kwargs: object):
            captured.update(kwargs)
            yield {"type": "complete", "data": {"content": "retry launched"}}

        agent_service = MagicMock()
        agent_service.stream_chat_v2 = _stream_chat_v2

        container = MagicMock()
        container.conversation_repository.return_value = conversation_repo
        container.agent_service.return_value = agent_service

        with (
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.async_session_factory",
                fake_session_factory,
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.get_redis_client",
                AsyncMock(return_value=object()),
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceRepository"
            ) as workspace_repo_cls,
            patch(
                "src.configuration.factories.create_llm_client",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "src.configuration.di_container.DIContainer",
                return_value=container,
            ),
        ):
            workspace_repo_cls.return_value.find_by_id = AsyncMock(return_value=workspace)

            await _launch_workspace_retry_attempt(
                workspace_id="ws-1",
                root_goal_task_id="root-1",
                workspace_task_id="child-1",
                attempt_id="attempt-9",
                actor_user_id="u-1",
                leader_agent_id="leader-agent",
                retry_feedback="Please tighten verification",
            )

        expected_conversation_id = WorkspaceMentionRouter.workspace_conversation_id(
            "ws-1",
            "leader-agent",
            conversation_scope="task:child-1:attempt:attempt-9",
        )
        conversation_repo.find_by_id.assert_awaited_once_with(expected_conversation_id)
        conversation_repo.save.assert_awaited_once()
        saved_conversation = conversation_repo.save.await_args.args[0]
        assert saved_conversation.metadata["attempt_id"] == "attempt-9"
        assert saved_conversation.metadata["workspace_task_id"] == "child-1"
        assert saved_conversation.metadata["retry_launch"] is True
        assert captured["conversation_id"] == expected_conversation_id
        assert captured["project_id"] == "project-1"
        assert captured["tenant_id"] == "tenant-1"
        assert captured["agent_id"] == "leader-agent"
        assert "attempt_id=attempt-9" in str(captured["user_message"])
        assert "Leader retry feedback: Please tighten verification" in str(captured["user_message"])

    async def test_prepare_workspace_subagent_delegation_marks_matching_task_in_progress(  # noqa: PLR0915
        self,
    ) -> None:
        task = MagicMock()
        task.id = "child-1"
        task.workspace_id = "ws-1"
        task.title = "Draft checklist"
        task.status = WorkspaceTaskStatus.TODO
        task.get_workspace_agent_binding_id.return_value = "binding-worker-a"
        task.metadata = {
            "autonomy_schema_version": 1,
            "task_role": "execution_task",
            "root_goal_task_id": "root-1",
            "lineage_source": "agent",
            "workspace_agent_binding_id": "binding-worker-a",
        }

        session = AsyncMock()

        @asynccontextmanager
        async def fake_session_factory():
            yield session

        with (
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.async_session_factory",
                fake_session_factory,
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.get_redis_client",
                AsyncMock(return_value=object()),
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceTaskRepository"
            ) as task_repo_cls,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceRepository"
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceMemberRepository"
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceAgentRepository"
            ),
            patch("src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskService"),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime._build_attempt_service"
            ) as attempt_service_builder,
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskEventPublisher"
            ) as publisher_cls,
        ):
            task_repo_cls.return_value.find_by_root_goal_task_id = AsyncMock(return_value=[task])
            task_repo_cls.return_value.find_by_id = AsyncMock(return_value=task)
            attempt_service = MagicMock()
            pending_attempt = _attempt(status="pending")
            pending_attempt.worker_agent_id = "worker-a"
            running_attempt = _attempt(status="running")
            running_attempt.worker_agent_id = "worker-a"
            attempt_service.get_active_attempt = AsyncMock(return_value=None)
            attempt_service.create_attempt = AsyncMock(return_value=pending_attempt)
            attempt_service.mark_running = AsyncMock(return_value=running_attempt)
            attempt_service_builder.return_value = attempt_service
            publisher = publisher_cls.return_value
            publisher.publish_pending_events = AsyncMock(return_value=None)

            updated_task = MagicMock()
            updated_task.id = "child-1"
            updated_task.status = WorkspaceTaskStatus.TODO
            updated_task.get_workspace_agent_binding_id.return_value = "binding-worker-a"

            started_task = MagicMock()
            started_task.id = "child-1"
            started_task.status = WorkspaceTaskStatus.IN_PROGRESS
            started_task.get_workspace_agent_binding_id.return_value = "binding-worker-a"

            root_task = MagicMock()
            root_task.id = "root-1"
            root_task.status = MagicMock(value="todo")

            workspace_task_service = MagicMock()
            workspace_task_service.get_task = AsyncMock(return_value=root_task)

            with (
                patch(
                    "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskService",
                    return_value=workspace_task_service,
                ),
                patch(
                    "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskCommandService.update_task",
                    new=AsyncMock(return_value=updated_task),
                ) as update_mock,
                patch(
                    "src.infrastructure.agent.workspace.workspace_goal_runtime.WorkspaceTaskCommandService.start_task",
                    new=AsyncMock(
                        side_effect=[
                            MagicMock(id="root-1", status=MagicMock(value="in_progress")),
                            started_task,
                        ]
                    ),
                ) as start_mock,
            ):
                binding = await prepare_workspace_subagent_delegation(
                    workspace_id="ws-1",
                    root_goal_task_id="root-1",
                    actor_user_id="u-1",
                    delegated_task_text="Draft checklist",
                    subagent_name="worker-subagent",
                    subagent_id="sa-1",
                    leader_agent_id="leader-agent",
                )

            assert binding == {
                "workspace_task_id": "child-1",
                "attempt_id": "attempt-1",
                "worker_agent_id": "worker-a",
                "workspace_agent_binding_id": "binding-worker-a",
                "workspace_id": "ws-1",
                "root_goal_task_id": "root-1",
                "actor_user_id": "u-1",
                "leader_agent_id": "leader-agent",
            }
            metadata = update_mock.await_args.kwargs["metadata"]
            assert metadata["delegated_subagent_name"] == "worker-subagent"
            assert metadata["delegated_subagent_id"] == "sa-1"
            assert metadata["current_attempt_id"] == "attempt-1"
            assert metadata["current_attempt_worker_agent_id"] == "worker-a"
            assert metadata["current_attempt_worker_binding_id"] == "binding-worker-a"
            assert metadata["workspace_agent_binding_id"] == "binding-worker-a"
            root_start_call, child_start_call = start_mock.await_args_list
            assert root_start_call.kwargs["task_id"] == "root-1"
            assert root_start_call.kwargs["reason"] == (
                "workspace_goal_runtime.prepare_subagent_delegation.start_root"
            )
            assert child_start_call.kwargs["reason"] == (
                "workspace_goal_runtime.prepare_subagent_delegation.start"
            )

    async def test_resolve_workspace_execution_task_prefers_explicit_task_id_marker(self) -> None:
        task = MagicMock()
        task.id = "child-42"
        task.workspace_id = "ws-1"
        task.status = WorkspaceTaskStatus.TODO
        task.title = "Different visible title"
        task.metadata = {"root_goal_task_id": "root-1"}

        session = AsyncMock()

        @asynccontextmanager
        async def fake_session_factory():
            yield session

        with (
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.async_session_factory",
                fake_session_factory,
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceTaskRepository"
            ) as task_repo_cls,
        ):
            task_repo_cls.return_value.find_by_id = AsyncMock(return_value=task)

            resolved = await resolve_workspace_execution_task_for_delegate(
                workspace_id="ws-1",
                root_goal_task_id="root-1",
                delegated_task_text=(
                    "[workspace-task-binding]\nworkspace_task_id=child-42\n"
                    "root_goal_task_id=root-1\nworkspace_id=ws-1\n[/workspace-task-binding]\n\n"
                    "Do the work"
                ),
                subagent_name="worker-subagent",
            )

        assert resolved is task

    async def test_resolve_workspace_execution_task_prefers_explicit_argument_over_title(
        self,
    ) -> None:
        task = MagicMock()
        task.id = "child-99"
        task.workspace_id = "ws-1"
        task.status = WorkspaceTaskStatus.TODO
        task.title = "Completely different"
        task.metadata = {"root_goal_task_id": "root-1"}

        session = AsyncMock()

        @asynccontextmanager
        async def fake_session_factory():
            yield session

        with (
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.async_session_factory",
                fake_session_factory,
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceTaskRepository"
            ) as task_repo_cls,
        ):
            task_repo_cls.return_value.find_by_id = AsyncMock(return_value=task)

            resolved = await resolve_workspace_execution_task_for_delegate(
                workspace_id="ws-1",
                root_goal_task_id="root-1",
                delegated_task_text="Some transformed task description",
                subagent_name="worker-subagent",
                workspace_task_id="child-99",
            )

        assert resolved is task

    async def test_resolve_workspace_execution_task_uses_singleton_open_child_fallback(
        self,
    ) -> None:
        only_child = MagicMock()
        only_child.id = "child-single"
        only_child.workspace_id = "ws-1"
        only_child.status = WorkspaceTaskStatus.TODO
        only_child.metadata = {"root_goal_task_id": "root-1"}

        session = AsyncMock()

        @asynccontextmanager
        async def fake_session_factory():
            yield session

        with (
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.async_session_factory",
                fake_session_factory,
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceTaskRepository"
            ) as task_repo_cls,
        ):
            repo = task_repo_cls.return_value
            repo.find_by_id = AsyncMock(return_value=None)
            repo.find_by_root_goal_task_id = AsyncMock(return_value=[only_child])

            resolved = await resolve_workspace_execution_task_for_delegate(
                workspace_id="ws-1",
                root_goal_task_id="root-1",
                delegated_task_text="Do the work without a structured binding block",
                subagent_name="worker-subagent",
            )

        assert resolved is only_child

    async def test_resolve_workspace_execution_task_returns_none_when_multiple_open_children_exist(
        self,
    ) -> None:
        child_a = MagicMock()
        child_a.id = "child-a"
        child_a.workspace_id = "ws-1"
        child_a.status = WorkspaceTaskStatus.TODO
        child_a.metadata = {"root_goal_task_id": "root-1"}

        child_b = MagicMock()
        child_b.id = "child-b"
        child_b.workspace_id = "ws-1"
        child_b.status = WorkspaceTaskStatus.IN_PROGRESS
        child_b.metadata = {"root_goal_task_id": "root-1"}

        session = AsyncMock()

        @asynccontextmanager
        async def fake_session_factory():
            yield session

        with (
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.async_session_factory",
                fake_session_factory,
            ),
            patch(
                "src.infrastructure.agent.workspace.workspace_goal_runtime.SqlWorkspaceTaskRepository"
            ) as task_repo_cls,
        ):
            repo = task_repo_cls.return_value
            repo.find_by_id = AsyncMock(return_value=None)
            repo.find_by_root_goal_task_id = AsyncMock(return_value=[child_a, child_b])

            resolved = await resolve_workspace_execution_task_for_delegate(
                workspace_id="ws-1",
                root_goal_task_id="root-1",
                delegated_task_text="Do the work without a structured binding block",
                subagent_name="worker-subagent",
            )

        assert resolved is None

    async def test_auto_complete_resynthesizes_failed_evidence_for_accepted_children(self) -> None:
        root_task = MagicMock()
        root_task.id = "root-accepted"
        root_task.workspace_id = "ws-1"
        root_task.title = "Ship accepted work"
        root_task.status = MagicMock(value="in_progress")
        root_task.metadata = {
            "autonomy_schema_version": 1,
            "task_role": "goal_root",
            "goal_origin": "human_defined",
            "goal_source_refs": ["api:test"],
            "root_goal_policy": {
                "mutable_by_agent": True,
                "completion_requires_external_proof": True,
            },
            "remediation_status": "ready_for_completion",
            "goal_evidence": {
                "goal_task_id": "root-accepted",
                "goal_text_snapshot": "Ship accepted work",
                "outcome_status": "achieved",
                "summary": "stale failure",
                "artifacts": ["artifact:file-1"],
                "verifications": ["child_report_not_completed:child-accepted:blocked"],
                "generated_by_agent_id": "leader-1",
                "recorded_at": "2026-04-16T03:00:00Z",
                "verification_grade": "fail",
            },
        }

        child = MagicMock()
        child.id = "child-accepted"
        child.title = "Implement accepted work"
        child.status = WorkspaceTaskStatus.DONE
        child.completed_at = datetime.fromisoformat("2026-04-16T03:40:00+00:00")
        child.updated_at = child.completed_at
        child.created_at = child.completed_at
        child.metadata = {
            "task_role": "execution_task",
            "evidence_refs": ["artifact:file-1"],
            "execution_verifications": ["browser_assert:done"],
            "durable_plan_verdict": "accepted",
            "last_worker_report_type": "blocked",
            "last_attempt_status": "awaiting_plan_verification",
        }

        task_repo = MagicMock()
        task_repo.find_by_root_goal_task_id = AsyncMock(return_value=[child])
        task_repo.find_by_id = AsyncMock(return_value=root_task)
        task_repo.save = AsyncMock(side_effect=lambda task: task)
        command_service = MagicMock()
        command_service.complete_task = AsyncMock(return_value=MagicMock(id="root-accepted"))

        result = await auto_complete_ready_root(
            workspace_id="ws-1",
            actor_user_id="user-1",
            root_task=root_task,
            task_repo=task_repo,
            command_service=command_service,
            leader_agent_id="leader-1",
        )

        assert result is not None
        saved_root = task_repo.save.await_args.args[0]
        assert saved_root.metadata["goal_evidence"]["verification_grade"] == "pass"
        assert (
            "child_report_not_completed:child-accepted:blocked"
            not in saved_root.metadata["goal_evidence"]["verifications"]
        )
        command_service.complete_task.assert_awaited_once()

    async def test_auto_complete_ignores_legacy_blocked_children_when_plan_children_done(
        self,
    ) -> None:
        root_task = MagicMock()
        root_task.id = "root-plan"
        root_task.workspace_id = "ws-1"
        root_task.title = "Ship plan work"
        root_task.status = MagicMock(value="in_progress")
        root_task.metadata = {
            "autonomy_schema_version": 1,
            "task_role": "goal_root",
            "goal_origin": "human_defined",
            "goal_source_refs": ["api:test"],
            "root_goal_policy": {
                "mutable_by_agent": True,
                "completion_requires_external_proof": True,
            },
        }

        plan_child = MagicMock()
        plan_child.id = "plan-child"
        plan_child.title = "Plan child"
        plan_child.status = WorkspaceTaskStatus.DONE
        plan_child.completed_at = datetime.fromisoformat("2026-04-16T03:40:00+00:00")
        plan_child.updated_at = plan_child.completed_at
        plan_child.created_at = plan_child.completed_at
        plan_child.metadata = {
            "task_role": "execution_task",
            "workspace_plan_id": "plan-1",
            "workspace_plan_node_id": "node-1",
            "evidence_refs": ["artifact:file-1"],
            "execution_verifications": ["pytest:passed"],
        }

        legacy_child = MagicMock()
        legacy_child.id = "legacy-child"
        legacy_child.title = "Legacy blocked child"
        legacy_child.status = WorkspaceTaskStatus.BLOCKED
        legacy_child.completed_at = None
        legacy_child.updated_at = datetime.fromisoformat("2026-04-16T03:40:00+00:00")
        legacy_child.created_at = legacy_child.updated_at
        legacy_child.metadata = {"task_role": "execution_task"}

        task_repo = MagicMock()
        task_repo.find_by_root_goal_task_id = AsyncMock(return_value=[plan_child, legacy_child])
        task_repo.find_by_id = AsyncMock(return_value=root_task)
        task_repo.save = AsyncMock(side_effect=lambda task: task)
        command_service = MagicMock()
        command_service.complete_task = AsyncMock(return_value=MagicMock(id="root-plan"))

        result = await auto_complete_ready_root(
            workspace_id="ws-1",
            actor_user_id="user-1",
            root_task=root_task,
            task_repo=task_repo,
            command_service=command_service,
            leader_agent_id="leader-1",
        )

        assert result is not None
        saved_root = task_repo.save.await_args.args[0]
        assert "child_report_not_completed:legacy-child" not in (
            saved_root.metadata["goal_evidence"]["verifications"]
        )
        command_service.complete_task.assert_awaited_once()
