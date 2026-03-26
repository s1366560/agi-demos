"""Application service for workspace lifecycle, members, and agent bindings."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from src.domain.model.workspace.workspace import Workspace
from src.domain.model.workspace.workspace_agent import WorkspaceAgent
from src.domain.model.workspace.workspace_member import WorkspaceMember
from src.domain.model.workspace.workspace_role import WorkspaceRole
from src.domain.ports.repositories.workspace.workspace_agent_repository import (
    WorkspaceAgentRepository,
)
from src.domain.ports.repositories.workspace.workspace_member_repository import (
    WorkspaceMemberRepository,
)
from src.domain.ports.repositories.workspace.workspace_repository import WorkspaceRepository


class WorkspaceService:
    """Core orchestration service for workspace collaboration entities."""

    def __init__(
        self,
        workspace_repo: WorkspaceRepository,
        workspace_member_repo: WorkspaceMemberRepository,
        workspace_agent_repo: WorkspaceAgentRepository,
        workspace_event_publisher: Callable[[str, str, dict[str, Any]], Awaitable[None]]
        | None = None,
    ) -> None:
        self._workspace_repo = workspace_repo
        self._workspace_member_repo = workspace_member_repo
        self._workspace_agent_repo = workspace_agent_repo
        self._workspace_event_publisher = workspace_event_publisher

    async def create_workspace(
        self,
        tenant_id: str,
        project_id: str,
        name: str,
        created_by: str,
        description: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Workspace:
        workspace = Workspace(
            id=Workspace.generate_id(),
            tenant_id=tenant_id,
            project_id=project_id,
            name=name,
            created_by=created_by,
            description=description,
            metadata=dict(metadata or {}),
            is_archived=False,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        saved_workspace = await self._workspace_repo.save(workspace)

        owner_member = WorkspaceMember(
            id=WorkspaceMember.generate_id(),
            workspace_id=saved_workspace.id,
            user_id=created_by,
            role=WorkspaceRole.OWNER,
            invited_by=created_by,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await self._workspace_member_repo.save(owner_member)

        if self._workspace_event_publisher is not None:
            await self._workspace_event_publisher(
                saved_workspace.id,
                "workspace_member_joined",
                {
                    "workspace_id": saved_workspace.id,
                    "member_id": owner_member.id,
                    "user_id": owner_member.user_id,
                    "role": owner_member.role.value,
                    "invited_by": owner_member.invited_by,
                },
            )
        return saved_workspace

    async def get_workspace(self, workspace_id: str, actor_user_id: str) -> Workspace:
        workspace = await self._require_workspace(workspace_id)
        await self._require_membership(workspace_id=workspace.id, user_id=actor_user_id)
        return workspace

    async def list_workspaces(
        self,
        tenant_id: str,
        project_id: str,
        actor_user_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Workspace]:
        workspaces = await self._workspace_repo.find_by_project(
            tenant_id=tenant_id,
            project_id=project_id,
            limit=limit,
            offset=offset,
        )

        visible: list[Workspace] = []
        for workspace in workspaces:
            member = await self._workspace_member_repo.find_by_workspace_and_user(
                workspace_id=workspace.id,
                user_id=actor_user_id,
            )
            if member is not None:
                visible.append(workspace)
        return visible

    async def update_workspace(
        self,
        workspace_id: str,
        actor_user_id: str,
        name: str | None = None,
        description: str | None = None,
        is_archived: bool | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Workspace:
        workspace = await self._require_workspace(workspace_id)
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.EDITOR,
            error_message="Insufficient permission to update workspace",
        )

        if name is not None:
            workspace.name = name
        if description is not None:
            workspace.description = description
        if is_archived is not None:
            workspace.is_archived = is_archived
        if metadata is not None:
            workspace.metadata = dict(metadata)
        workspace.updated_at = datetime.now(UTC)
        updated = await self._workspace_repo.save(workspace)
        if self._workspace_event_publisher is not None:
            await self._workspace_event_publisher(
                workspace.id,
                "workspace_updated",
                {
                    "workspace_id": workspace.id,
                    "name": workspace.name,
                    "is_archived": workspace.is_archived,
                    "updated_by": actor_user_id,
                },
            )
        return updated

    async def delete_workspace(self, workspace_id: str, actor_user_id: str) -> bool:
        workspace = await self._require_workspace(workspace_id)
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.OWNER,
            error_message="Only workspace owner can delete workspace",
        )
        deleted = await self._workspace_repo.delete(workspace.id)
        if deleted and self._workspace_event_publisher is not None:
            await self._workspace_event_publisher(
                workspace.id,
                "workspace_deleted",
                {
                    "workspace_id": workspace.id,
                    "deleted_by": actor_user_id,
                },
            )
        return deleted

    async def add_member(
        self,
        workspace_id: str,
        actor_user_id: str,
        target_user_id: str,
        role: WorkspaceRole = WorkspaceRole.VIEWER,
    ) -> WorkspaceMember:
        workspace = await self._require_workspace(workspace_id)
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.OWNER,
            error_message="Only workspace owner can add members",
        )

        existing = await self._workspace_member_repo.find_by_workspace_and_user(
            workspace_id=workspace.id,
            user_id=target_user_id,
        )
        if existing is not None:
            raise ValueError(f"User {target_user_id} is already a member")

        member = WorkspaceMember(
            id=WorkspaceMember.generate_id(),
            workspace_id=workspace.id,
            user_id=target_user_id,
            role=role,
            invited_by=actor_user_id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        saved_member = await self._workspace_member_repo.save(member)
        if self._workspace_event_publisher is not None:
            await self._workspace_event_publisher(
                workspace.id,
                "workspace_member_joined",
                {
                    "workspace_id": workspace.id,
                    "member_id": saved_member.id,
                    "user_id": saved_member.user_id,
                    "role": saved_member.role.value,
                    "invited_by": saved_member.invited_by,
                },
            )
        return saved_member

    async def list_members(
        self,
        workspace_id: str,
        actor_user_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[WorkspaceMember]:
        workspace = await self._require_workspace(workspace_id)
        await self._require_membership(workspace_id=workspace.id, user_id=actor_user_id)
        return await self._workspace_member_repo.find_by_workspace(
            workspace_id=workspace.id,
            limit=limit,
            offset=offset,
        )

    async def update_member_role(
        self,
        workspace_id: str,
        actor_user_id: str,
        target_user_id: str,
        new_role: WorkspaceRole,
    ) -> WorkspaceMember:
        workspace = await self._require_workspace(workspace_id)
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.OWNER,
            error_message="Only workspace owner can update member roles",
        )

        target_member = await self._require_membership(
            workspace_id=workspace.id,
            user_id=target_user_id,
        )
        if (
            actor_user_id == target_user_id
            and target_member.role == WorkspaceRole.OWNER
            and new_role != WorkspaceRole.OWNER
        ):
            raise ValueError("Cannot change your own owner role")

        target_member.role = new_role
        target_member.updated_at = datetime.now(UTC)
        return await self._workspace_member_repo.save(target_member)

    async def remove_member(
        self,
        workspace_id: str,
        actor_user_id: str,
        target_user_id: str,
    ) -> bool:
        workspace = await self._require_workspace(workspace_id)
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.OWNER,
            error_message="Only workspace owner can remove members",
        )
        member = await self._require_membership(workspace_id=workspace.id, user_id=target_user_id)
        if member.role == WorkspaceRole.OWNER and actor_user_id != target_user_id:
            raise ValueError("Only an owner can remove themselves from owner role")
        deleted = await self._workspace_member_repo.delete(member.id)
        if deleted and self._workspace_event_publisher is not None:
            await self._workspace_event_publisher(
                workspace.id,
                "workspace_member_left",
                {
                    "workspace_id": workspace.id,
                    "member_id": member.id,
                    "user_id": target_user_id,
                    "removed_by": actor_user_id,
                },
            )
        return deleted

    async def bind_agent(
        self,
        workspace_id: str,
        actor_user_id: str,
        agent_id: str,
        display_name: str | None = None,
        description: str | None = None,
        config: Mapping[str, object] | None = None,
        is_active: bool = True,
    ) -> WorkspaceAgent:
        workspace = await self._require_workspace(workspace_id)
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.EDITOR,
            error_message="Insufficient permission to bind workspace agent",
        )

        existing = await self._find_agent_binding_by_agent_id(
            workspace_id=workspace.id,
            agent_id=agent_id,
        )
        now = datetime.now(UTC)

        if existing is not None:
            existing.display_name = display_name
            existing.description = description
            existing.config = dict(config or existing.config)
            existing.is_active = is_active
            existing.updated_at = now
            saved = await self._workspace_agent_repo.save(existing)
            if self._workspace_event_publisher is not None:
                await self._workspace_event_publisher(
                    workspace.id,
                    "workspace_agent_bound",
                    {
                        "workspace_id": workspace.id,
                        "workspace_agent_id": saved.id,
                        "agent_id": saved.agent_id,
                        "is_update": True,
                        "bound_by": actor_user_id,
                    },
                )
            return saved

        relation = WorkspaceAgent(
            id=WorkspaceAgent.generate_id(),
            workspace_id=workspace.id,
            agent_id=agent_id,
            display_name=display_name,
            description=description,
            config=dict(config or {}),
            is_active=is_active,
            created_at=now,
            updated_at=now,
        )
        saved = await self._workspace_agent_repo.save(relation)
        if self._workspace_event_publisher is not None:
            await self._workspace_event_publisher(
                workspace.id,
                "workspace_agent_bound",
                {
                    "workspace_id": workspace.id,
                    "workspace_agent_id": saved.id,
                    "agent_id": saved.agent_id,
                    "is_update": False,
                    "bound_by": actor_user_id,
                },
            )
        return saved

    async def list_workspace_agents(
        self,
        workspace_id: str,
        actor_user_id: str,
        active_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[WorkspaceAgent]:
        workspace = await self._require_workspace(workspace_id)
        await self._require_membership(workspace_id=workspace.id, user_id=actor_user_id)
        return await self._workspace_agent_repo.find_by_workspace(
            workspace_id=workspace.id,
            active_only=active_only,
            limit=limit,
            offset=offset,
        )

    async def update_agent_binding(
        self,
        workspace_id: str,
        actor_user_id: str,
        workspace_agent_id: str,
        display_name: str | None = None,
        description: str | None = None,
        config: Mapping[str, object] | None = None,
        is_active: bool | None = None,
    ) -> WorkspaceAgent:
        workspace = await self._require_workspace(workspace_id)
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.EDITOR,
            error_message="Insufficient permission to update workspace agent binding",
        )

        relation = await self._workspace_agent_repo.find_by_id(workspace_agent_id)
        if relation is None:
            raise ValueError(f"Workspace agent binding {workspace_agent_id} not found")
        if relation.workspace_id != workspace.id:
            raise ValueError("Workspace agent binding does not belong to workspace")

        if display_name is not None:
            relation.display_name = display_name
        if description is not None:
            relation.description = description
        if config is not None:
            relation.config = dict(config)
        if is_active is not None:
            relation.is_active = is_active
        relation.updated_at = datetime.now(UTC)
        return await self._workspace_agent_repo.save(relation)

    async def unbind_agent(
        self,
        workspace_id: str,
        actor_user_id: str,
        workspace_agent_id: str,
    ) -> bool:
        workspace = await self._require_workspace(workspace_id)
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.EDITOR,
            error_message="Insufficient permission to unbind workspace agent",
        )

        relation = await self._workspace_agent_repo.find_by_id(workspace_agent_id)
        if relation is None:
            raise ValueError(f"Workspace agent binding {workspace_agent_id} not found")
        if relation.workspace_id != workspace.id:
            raise ValueError("Workspace agent binding does not belong to workspace")
        deleted = await self._workspace_agent_repo.delete(workspace_agent_id)
        if deleted and self._workspace_event_publisher is not None:
            await self._workspace_event_publisher(
                workspace.id,
                "workspace_agent_unbound",
                {
                    "workspace_id": workspace.id,
                    "workspace_agent_id": workspace_agent_id,
                    "agent_id": relation.agent_id,
                    "unbound_by": actor_user_id,
                },
            )
        return deleted

    async def _require_workspace(self, workspace_id: str) -> Workspace:
        workspace = await self._workspace_repo.find_by_id(workspace_id)
        if workspace is None:
            raise ValueError(f"Workspace {workspace_id} not found")
        return workspace

    async def _require_membership(self, workspace_id: str, user_id: str) -> WorkspaceMember:
        member = await self._workspace_member_repo.find_by_workspace_and_user(
            workspace_id=workspace_id,
            user_id=user_id,
        )
        if member is None:
            raise PermissionError("User must be a workspace member")
        return member

    async def _require_minimum_role(
        self,
        workspace_id: str,
        user_id: str,
        minimum: WorkspaceRole,
        error_message: str,
    ) -> WorkspaceMember:
        member = await self._require_membership(workspace_id=workspace_id, user_id=user_id)
        if self._role_weight(member.role) < self._role_weight(minimum):
            raise PermissionError(error_message)
        return member

    @staticmethod
    def _role_weight(role: WorkspaceRole) -> int:
        if role == WorkspaceRole.OWNER:
            return 300
        if role == WorkspaceRole.EDITOR:
            return 200
        return 100

    async def _find_agent_binding_by_agent_id(
        self,
        workspace_id: str,
        agent_id: str,
    ) -> WorkspaceAgent | None:
        candidates = await self._workspace_agent_repo.find_by_workspace(
            workspace_id=workspace_id,
            active_only=False,
            limit=500,
            offset=0,
        )
        for candidate in candidates:
            if candidate.agent_id == agent_id:
                return candidate
        return None
