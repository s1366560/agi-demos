"""Workspace activity audit log service."""

from __future__ import annotations

import logging
from typing import Any

from src.infrastructure.audit.audit_log_service import AuditLogService

logger = logging.getLogger(__name__)


class WorkspaceAuditService:
    """Records all workspace mutations for compliance.

    Wraps AuditLogService with workspace-specific convenience methods.
    resource_type is always "workspace" with a scoped action.
    """

    def __init__(self, audit_service: AuditLogService) -> None:
        self._audit = audit_service

    async def log_agent_added(
        self,
        workspace_id: str,
        agent_id: str,
        actor_user_id: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        details: dict[str, Any] = {"agent_id": agent_id}
        if extra:
            details.update(extra)
        _ = await self._audit.log_event(
            action="workspace.agent.added",
            resource_type="workspace",
            resource_id=workspace_id,
            actor=actor_user_id,
            details=details,
        )

    async def log_agent_removed(
        self,
        workspace_id: str,
        agent_id: str,
        actor_user_id: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        details: dict[str, Any] = {"agent_id": agent_id}
        if extra:
            details.update(extra)
        _ = await self._audit.log_event(
            action="workspace.agent.removed",
            resource_type="workspace",
            resource_id=workspace_id,
            actor=actor_user_id,
            details=details,
        )

    async def log_task_created(
        self,
        workspace_id: str,
        task_id: str,
        actor_user_id: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        details: dict[str, Any] = {"task_id": task_id}
        if extra:
            details.update(extra)
        _ = await self._audit.log_event(
            action="workspace.task.created",
            resource_type="workspace",
            resource_id=workspace_id,
            actor=actor_user_id,
            details=details,
        )

    async def log_task_updated(
        self,
        workspace_id: str,
        task_id: str,
        actor_user_id: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        details: dict[str, Any] = {"task_id": task_id}
        if extra:
            details.update(extra)
        _ = await self._audit.log_event(
            action="workspace.task.updated",
            resource_type="workspace",
            resource_id=workspace_id,
            actor=actor_user_id,
            details=details,
        )

    async def log_objective_created(
        self,
        workspace_id: str,
        objective_id: str,
        actor_user_id: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        details: dict[str, Any] = {"objective_id": objective_id}
        if extra:
            details.update(extra)
        _ = await self._audit.log_event(
            action="workspace.objective.created",
            resource_type="workspace",
            resource_id=workspace_id,
            actor=actor_user_id,
            details=details,
        )

    async def log_gene_created(
        self,
        workspace_id: str,
        gene_id: str,
        actor_user_id: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        details: dict[str, Any] = {"gene_id": gene_id}
        if extra:
            details.update(extra)
        _ = await self._audit.log_event(
            action="workspace.gene.created",
            resource_type="workspace",
            resource_id=workspace_id,
            actor=actor_user_id,
            details=details,
        )

    async def log_member_added(
        self,
        workspace_id: str,
        user_id: str,
        role: str,
        actor_user_id: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        details: dict[str, Any] = {
            "user_id": user_id,
            "role": role,
        }
        if extra:
            details.update(extra)
        _ = await self._audit.log_event(
            action="workspace.member.added",
            resource_type="workspace",
            resource_id=workspace_id,
            actor=actor_user_id,
            details=details,
        )

    async def log_member_removed(
        self,
        workspace_id: str,
        user_id: str,
        actor_user_id: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        details: dict[str, Any] = {"user_id": user_id}
        if extra:
            details.update(extra)
        _ = await self._audit.log_event(
            action="workspace.member.removed",
            resource_type="workspace",
            resource_id=workspace_id,
            actor=actor_user_id,
            details=details,
        )

    async def log_topology_changed(
        self,
        workspace_id: str,
        change_type: str,
        actor_user_id: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        _ = await self._audit.log_event(
            action=f"workspace.topology.{change_type}",
            resource_type="workspace",
            resource_id=workspace_id,
            actor=actor_user_id,
            details=extra or {},
        )

    async def log_blackboard_post(
        self,
        workspace_id: str,
        post_id: str,
        actor_user_id: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        details: dict[str, Any] = {"post_id": post_id}
        if extra:
            details.update(extra)
        _ = await self._audit.log_event(
            action="workspace.blackboard.posted",
            resource_type="workspace",
            resource_id=workspace_id,
            actor=actor_user_id,
            details=details,
        )

    async def log_settings_changed(
        self,
        workspace_id: str,
        actor_user_id: str,
        changes: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        details: dict[str, Any] = {}
        if extra:
            details.update(extra)
        if changes is not None:
            details["changes"] = changes
        _ = await self._audit.log_event(
            action="workspace.settings.changed",
            resource_type="workspace",
            resource_id=workspace_id,
            actor=actor_user_id,
            details=details,
        )
