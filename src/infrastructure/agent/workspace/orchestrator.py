"""Workspace Autonomy Orchestrator — unified entry points (P2d M5).

Collects the six public coroutines exposed by
:mod:`workspace_goal_runtime` behind a single facade. Callers that want a
single injection point (e.g. subagent/react loops) can depend on
:class:`WorkspaceAutonomyOrchestrator` instead of importing module-level
functions scattered across the runtime module.

This module is **pure-additive**: the underlying coroutines remain available
at their module import paths. The facade holds no mutable state; it simply
forwards to the underlying functions so composition / mocking is easier and
future migrations can swap implementations without touching callers.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.model.workspace.workspace_task import (
    WorkspaceTask,
    WorkspaceTaskPriority,
    WorkspaceTaskStatus,
)

from . import workspace_goal_runtime as _runtime


@dataclass(frozen=True)
class WorkspaceAutonomyOrchestrator:
    """Unified entry point for workspace autonomy.

    Instances are cheap and stateless — construct one per caller or share
    a singleton. The class is deliberately thin: each method forwards to an
    existing coroutine so runtime regression tests cover it by proxy.
    """

    def should_activate(
        self,
        user_query: str,
        *,
        has_workspace_binding: bool = False,
        has_open_root: bool = False,
    ) -> bool:
        """Forward to :func:`workspace_goal_runtime.should_activate_workspace_authority`."""
        return _runtime.should_activate_workspace_authority(
            user_query,
            has_workspace_binding=has_workspace_binding,
            has_open_root=has_open_root,
        )

    async def materialize_goal_candidate(
        self,
        project_id: str,
        tenant_id: str,
        user_id: str,
        *,
        leader_agent_id: str | None = None,
        task_decomposer: _runtime.TaskDecomposerProtocol | None = None,
        user_query: str = "",
    ) -> WorkspaceTask | None:
        """Forward to :func:`workspace_goal_runtime.maybe_materialize_workspace_goal_candidate`."""
        return await _runtime.maybe_materialize_workspace_goal_candidate(
            project_id,
            tenant_id,
            user_id,
            leader_agent_id=leader_agent_id,
            task_decomposer=task_decomposer,
            user_query=user_query,
        )

    async def apply_worker_report(
        self,
        *,
        workspace_id: str,
        root_goal_task_id: str,
        task_id: str,
        attempt_id: str | None = None,
        conversation_id: str | None = None,
        actor_user_id: str,
        worker_agent_id: str | None,
        report_type: str,
        summary: str,
        artifacts: list[str] | None = None,
        leader_agent_id: str | None = None,
        report_id: str | None = None,
    ) -> WorkspaceTask | None:
        """Forward to :func:`workspace_goal_runtime.apply_workspace_worker_report`."""
        return await _runtime.apply_workspace_worker_report(
            workspace_id=workspace_id,
            root_goal_task_id=root_goal_task_id,
            task_id=task_id,
            attempt_id=attempt_id,
            conversation_id=conversation_id,
            actor_user_id=actor_user_id,
            worker_agent_id=worker_agent_id,
            report_type=report_type,
            summary=summary,
            artifacts=artifacts,
            leader_agent_id=leader_agent_id,
            report_id=report_id,
        )

    async def adjudicate_worker_report(
        self,
        *,
        workspace_id: str,
        task_id: str,
        attempt_id: str | None = None,
        actor_user_id: str,
        status: WorkspaceTaskStatus,
        leader_agent_id: str | None = None,
        title: str | None = None,
        priority: WorkspaceTaskPriority | None = None,
    ) -> WorkspaceTask | None:
        """Forward to :func:`workspace_goal_runtime.adjudicate_workspace_worker_report`."""
        return await _runtime.adjudicate_workspace_worker_report(
            workspace_id=workspace_id,
            task_id=task_id,
            attempt_id=attempt_id,
            actor_user_id=actor_user_id,
            status=status,
            leader_agent_id=leader_agent_id,
            title=title,
            priority=priority,
        )

    async def auto_complete_ready_root(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        root_task: WorkspaceTask,
        task_repo: _runtime.SqlWorkspaceTaskRepository,
        command_service: _runtime.WorkspaceTaskCommandService,
        leader_agent_id: str | None,
    ) -> WorkspaceTask | None:
        """Forward to :func:`workspace_goal_runtime.auto_complete_ready_root`."""
        return await _runtime.auto_complete_ready_root(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            root_task=root_task,
            task_repo=task_repo,
            command_service=command_service,
            leader_agent_id=leader_agent_id,
        )

    async def prepare_subagent_delegation(
        self,
        *,
        workspace_id: str,
        root_goal_task_id: str,
        actor_user_id: str,
        delegated_task_text: str,
        subagent_name: str,
        subagent_id: str | None,
        leader_agent_id: str | None,
        workspace_task_id: str | None = None,
    ) -> dict[str, str] | None:
        """Forward to :func:`workspace_goal_runtime.prepare_workspace_subagent_delegation`."""
        return await _runtime.prepare_workspace_subagent_delegation(
            workspace_id=workspace_id,
            root_goal_task_id=root_goal_task_id,
            actor_user_id=actor_user_id,
            delegated_task_text=delegated_task_text,
            subagent_name=subagent_name,
            subagent_id=subagent_id,
            leader_agent_id=leader_agent_id,
            workspace_task_id=workspace_task_id,
        )


__all__ = ["WorkspaceAutonomyOrchestrator"]
