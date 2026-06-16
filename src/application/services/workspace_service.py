"""Application service for workspace lifecycle, members, and agent bindings."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from src.application.services.workspace_layout_limits import validate_hex_target
from src.domain.model.workspace.workspace import Workspace
from src.domain.model.workspace.workspace_agent import WorkspaceAgent
from src.domain.model.workspace.workspace_member import WorkspaceMember
from src.domain.model.workspace.workspace_role import WorkspaceRole
from src.domain.ports.agent.agent_registry import AgentRegistryPort
from src.domain.ports.repositories.workspace.topology_repository import TopologyRepository
from src.domain.ports.repositories.workspace.workspace_agent_repository import (
    WorkspaceAgentRepository,
)
from src.domain.ports.repositories.workspace.workspace_member_repository import (
    WorkspaceMemberRepository,
)
from src.domain.ports.repositories.workspace.workspace_repository import WorkspaceRepository

RESERVED_BLACKBOARD_HEX = (0, 0)


def _serialize_workspace_agent_event(agent: WorkspaceAgent) -> dict[str, Any]:
    return {
        "id": agent.id,
        "workspace_id": agent.workspace_id,
        "agent_id": agent.agent_id,
        "display_name": agent.display_name,
        "description": agent.description,
        "config": dict(agent.config or {}),
        "is_active": agent.is_active,
        "hex_q": agent.hex_q,
        "hex_r": agent.hex_r,
        "theme_color": agent.theme_color,
        "label": agent.label,
        "status": agent.status,
        "created_at": agent.created_at.isoformat(),
        "updated_at": agent.updated_at.isoformat() if agent.updated_at else None,
    }


def _serialize_workspace_event(workspace: Workspace) -> dict[str, Any]:
    return {
        "id": workspace.id,
        "tenant_id": workspace.tenant_id,
        "project_id": workspace.project_id,
        "name": workspace.name,
        "created_by": workspace.created_by,
        "description": workspace.description,
        "is_archived": workspace.is_archived,
        "metadata": workspace.metadata,
        "office_status": workspace.office_status,
        "hex_layout_config": workspace.hex_layout_config,
        "created_at": workspace.created_at.isoformat(),
        "updated_at": workspace.updated_at.isoformat() if workspace.updated_at else None,
    }


def _serialize_workspace_member_event(member: WorkspaceMember) -> dict[str, Any]:
    return {
        "id": member.id,
        "workspace_id": member.workspace_id,
        "user_id": member.user_id,
        "role": member.role.value,
        "invited_by": member.invited_by,
        "created_at": member.created_at.isoformat(),
        "updated_at": member.updated_at.isoformat() if member.updated_at else None,
    }


def _resolve_hex_target(hex_q: int | None, hex_r: int | None) -> tuple[int, int] | None:
    if hex_q is None and hex_r is None:
        return None
    if hex_q is None or hex_r is None:
        raise ValueError("Both hex_q and hex_r must be provided together")
    validate_hex_target(hex_q, hex_r)
    if (hex_q, hex_r) == RESERVED_BLACKBOARD_HEX:
        raise ValueError("Center hex is reserved for the blackboard")
    return hex_q, hex_r


def _apply_agent_binding_updates(
    relation: WorkspaceAgent,
    *,
    display_name: str | None = None,
    description: str | None = None,
    config: Mapping[str, object] | None = None,
    is_active: bool | None = None,
    hex_q: int | None = None,
    hex_r: int | None = None,
    theme_color: str | None = None,
    label: str | None = None,
    status: str | None = None,
    clear_nullable_text: bool = False,
) -> None:
    if config is not None:
        relation.config = dict(config)
    if is_active is not None:
        relation.is_active = is_active

    if clear_nullable_text or display_name is not None:
        relation.display_name = display_name
    if clear_nullable_text or description is not None:
        relation.description = description

    updates = (
        ("hex_q", hex_q),
        ("hex_r", hex_r),
        ("theme_color", theme_color),
        ("label", label),
        ("status", status),
    )
    for field_name, value in updates:
        if value is not None:
            setattr(relation, field_name, value)


class WorkspaceService:
    """Core orchestration service for workspace collaboration entities."""

    def __init__(
        self,
        workspace_repo: WorkspaceRepository,
        workspace_member_repo: WorkspaceMemberRepository,
        workspace_agent_repo: WorkspaceAgentRepository,
        topology_repo: TopologyRepository,
        workspace_event_publisher: Callable[[str, str, dict[str, Any]], Awaitable[None]]
        | None = None,
        agent_registry: AgentRegistryPort | None = None,
    ) -> None:
        self._workspace_repo = workspace_repo
        self._workspace_member_repo = workspace_member_repo
        self._workspace_agent_repo = workspace_agent_repo
        self._topology_repo = topology_repo
        self._workspace_event_publisher = workspace_event_publisher
        self._agent_registry = agent_registry
        self._pending_events: list[tuple[str, str, dict[str, Any]]] = []

    def consume_pending_events(self) -> list[tuple[str, str, dict[str, Any]]]:
        """Return and clear queued workspace events."""
        pending_events = list(self._pending_events)
        self._pending_events.clear()
        return pending_events

    async def publish_pending_events(self) -> None:
        """Publish queued workspace events after the request transaction commits."""
        if self._workspace_event_publisher is None:
            self._pending_events.clear()
            return
        for workspace_id, event_name, payload in self._pending_events:
            await self._workspace_event_publisher(workspace_id, event_name, payload)
        self._pending_events.clear()

    def _queue_workspace_event(
        self,
        workspace_id: str,
        event_name: str,
        payload: dict[str, Any],
    ) -> None:
        self._pending_events.append((workspace_id, event_name, payload))

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

        self._queue_workspace_event(
            saved_workspace.id,
            "workspace_member_joined",
            self._member_event_payload(owner_member),
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
        return await self._workspace_repo.find_visible_by_project_for_user(
            tenant_id=tenant_id,
            project_id=project_id,
            user_id=actor_user_id,
            limit=limit,
            offset=offset,
        )

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
        self._queue_workspace_event(
            updated.id,
            "workspace_updated",
            {
                "workspace_id": updated.id,
                "workspace": _serialize_workspace_event(updated),
                "name": updated.name,
                "is_archived": updated.is_archived,
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
        if deleted:
            self._queue_workspace_event(
                workspace.id,
                "workspace_deleted",
                {
                    "workspace_id": workspace.id,
                    "workspace": _serialize_workspace_event(workspace),
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
        self._queue_workspace_event(
            workspace.id,
            "workspace_member_joined",
            self._member_event_payload(saved_member),
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
        if target_member.role == WorkspaceRole.OWNER and new_role != WorkspaceRole.OWNER:
            await self._ensure_owner_can_be_removed_or_demoted(workspace.id)

        target_member.role = new_role
        target_member.updated_at = datetime.now(UTC)
        saved_member = await self._workspace_member_repo.save(target_member)
        self._queue_workspace_event(
            workspace.id,
            "workspace_member_updated",
            {
                **self._member_event_payload(saved_member),
                "updated_by": actor_user_id,
            },
        )
        return saved_member

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
        if member.role == WorkspaceRole.OWNER:
            await self._ensure_owner_can_be_removed_or_demoted(workspace.id)
        deleted = await self._workspace_member_repo.delete(member.id)
        if deleted:
            self._queue_workspace_event(
                workspace.id,
                "workspace_member_left",
                {
                    **self._member_event_payload(member),
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
        hex_q: int | None = None,
        hex_r: int | None = None,
        theme_color: str | None = None,
        label: str | None = None,
    ) -> WorkspaceAgent:
        workspace = await self._require_workspace(workspace_id)
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.EDITOR,
            error_message="Insufficient permission to bind workspace agent",
        )
        await self._ensure_agent_available_for_workspace(workspace, agent_id)

        existing = await self._find_agent_binding_by_agent_id(
            workspace_id=workspace.id,
            agent_id=agent_id,
        )
        if hex_q is not None or hex_r is not None:
            target = _resolve_hex_target(
                hex_q if hex_q is not None else existing.hex_q if existing is not None else None,
                hex_r if hex_r is not None else existing.hex_r if existing is not None else None,
            )
            if target is not None:
                await self._topology_repo.acquire_hex_lock(workspace.id, target[0], target[1])
                await self._ensure_hex_available(
                    workspace.id,
                    target[0],
                    target[1],
                    exclude_agent_id=existing.id if existing is not None else None,
                )
        now = datetime.now(UTC)

        if existing is not None:
            _apply_agent_binding_updates(
                existing,
                display_name=display_name,
                description=description,
                config=config,
                is_active=is_active,
                hex_q=hex_q,
                hex_r=hex_r,
                theme_color=theme_color,
                label=label,
                clear_nullable_text=True,
            )
            existing.updated_at = now
            saved = await self._workspace_agent_repo.save(existing)
            self._queue_workspace_event(
                workspace.id,
                "workspace_agent_bound",
                {
                    "workspace_id": workspace.id,
                    "workspace_agent_id": saved.id,
                    "agent_id": saved.agent_id,
                    "agent": _serialize_workspace_agent_event(saved),
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
            hex_q=hex_q,
            hex_r=hex_r,
            theme_color=theme_color,
            label=label,
            created_at=now,
            updated_at=now,
        )
        saved = await self._workspace_agent_repo.save(relation)
        self._queue_workspace_event(
            workspace.id,
            "workspace_agent_bound",
            {
                "workspace_id": workspace.id,
                "workspace_agent_id": saved.id,
                "agent_id": saved.agent_id,
                "agent": _serialize_workspace_agent_event(saved),
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
        hex_q: int | None = None,
        hex_r: int | None = None,
        theme_color: str | None = None,
        label: str | None = None,
        status: str | None = None,
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

        if hex_q is not None or hex_r is not None:
            target = _resolve_hex_target(
                hex_q if hex_q is not None else relation.hex_q,
                hex_r if hex_r is not None else relation.hex_r,
            )
            if target is not None:
                await self._topology_repo.acquire_hex_lock(workspace.id, target[0], target[1])
                await self._ensure_hex_available(
                    workspace.id,
                    target[0],
                    target[1],
                    exclude_agent_id=relation.id,
                )

        _apply_agent_binding_updates(
            relation,
            display_name=display_name,
            description=description,
            config=config,
            is_active=is_active,
            hex_q=hex_q,
            hex_r=hex_r,
            theme_color=theme_color,
            label=label,
            status=status,
        )
        relation.updated_at = datetime.now(UTC)
        saved = await self._workspace_agent_repo.save(relation)
        self._queue_workspace_event(
            workspace.id,
            "workspace_agent_bound",
            {
                "workspace_id": workspace.id,
                "workspace_agent_id": saved.id,
                "agent_id": saved.agent_id,
                "agent": _serialize_workspace_agent_event(saved),
                "is_update": True,
                "bound_by": actor_user_id,
            },
        )
        return saved

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
        if deleted:
            self._queue_workspace_event(
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

    async def _ensure_agent_available_for_workspace(
        self,
        workspace: Workspace,
        agent_id: str,
    ) -> None:
        if self._agent_registry is None:
            return
        agent = await self._agent_registry.get_by_id(
            agent_id,
            tenant_id=workspace.tenant_id,
            project_id=workspace.project_id,
        )
        if agent is None:
            raise ValueError("Agent definition is not available for this workspace")

    def _member_event_payload(self, member: WorkspaceMember) -> dict[str, Any]:
        serialized_member = _serialize_workspace_member_event(member)
        return {
            "workspace_id": member.workspace_id,
            "member_id": member.id,
            "user_id": member.user_id,
            "role": member.role.value,
            "invited_by": member.invited_by,
            "member": serialized_member,
        }

    async def _ensure_owner_can_be_removed_or_demoted(self, workspace_id: str) -> None:
        owner_count = await self._workspace_member_repo.count_by_workspace_and_role(
            workspace_id=workspace_id,
            role=WorkspaceRole.OWNER,
        )
        if owner_count <= 1:
            raise ValueError("Cannot remove or demote the last workspace owner")

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
        return await self._workspace_agent_repo.find_by_workspace_and_agent_id(
            workspace_id=workspace_id,
            agent_id=agent_id,
        )

    async def _ensure_hex_available(
        self,
        workspace_id: str,
        hex_q: int,
        hex_r: int,
        *,
        exclude_agent_id: str | None = None,
    ) -> None:
        occupying_agents = await self._workspace_agent_repo.find_by_workspace_and_hex(
            workspace_id=workspace_id,
            hex_q=hex_q,
            hex_r=hex_r,
        )
        if any(agent.id != exclude_agent_id for agent in occupying_agents):
            raise ValueError("Hex is already occupied")

        occupying_nodes = await self._topology_repo.list_nodes_by_hex(
            workspace_id=workspace_id,
            hex_q=hex_q,
            hex_r=hex_r,
        )
        if occupying_nodes:
            raise ValueError("Hex is already occupied")
