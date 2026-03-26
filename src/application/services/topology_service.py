"""Application service for workspace topology nodes and edges."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from src.domain.model.workspace.topology_edge import TopologyEdge
from src.domain.model.workspace.topology_node import TopologyNode, TopologyNodeType
from src.domain.model.workspace.workspace import Workspace
from src.domain.model.workspace.workspace_member import WorkspaceMember
from src.domain.model.workspace.workspace_role import WorkspaceRole
from src.domain.ports.repositories.workspace.topology_repository import TopologyRepository
from src.domain.ports.repositories.workspace.workspace_member_repository import (
    WorkspaceMemberRepository,
)
from src.domain.ports.repositories.workspace.workspace_repository import WorkspaceRepository


class TopologyService:
    """Orchestrates topology CRUD with workspace permission and consistency checks."""

    def __init__(
        self,
        workspace_repo: WorkspaceRepository,
        workspace_member_repo: WorkspaceMemberRepository,
        topology_repo: TopologyRepository,
    ) -> None:
        self._workspace_repo = workspace_repo
        self._workspace_member_repo = workspace_member_repo
        self._topology_repo = topology_repo

    async def create_node(
        self,
        workspace_id: str,
        actor_user_id: str,
        node_type: TopologyNodeType,
        title: str = "",
        ref_id: str | None = None,
        position_x: float = 0.0,
        position_y: float = 0.0,
        data: Mapping[str, Any] | None = None,
    ) -> TopologyNode:
        workspace = await self._require_workspace(workspace_id)
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.EDITOR,
            error_message="Insufficient permission to create topology node",
        )

        now = datetime.now(UTC)
        node = TopologyNode(
            id=TopologyNode.generate_id(),
            workspace_id=workspace.id,
            node_type=node_type,
            ref_id=ref_id,
            title=title,
            position_x=position_x,
            position_y=position_y,
            data=dict(data or {}),
            created_at=now,
            updated_at=now,
        )
        return await self._topology_repo.save_node(node)

    async def list_nodes(
        self,
        workspace_id: str,
        actor_user_id: str,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[TopologyNode]:
        workspace = await self._require_workspace(workspace_id)
        await self._require_membership(workspace.id, actor_user_id)
        return await self._topology_repo.list_nodes_by_workspace(
            workspace_id=workspace.id,
            limit=limit,
            offset=offset,
        )

    async def get_node(
        self,
        workspace_id: str,
        node_id: str,
        actor_user_id: str,
    ) -> TopologyNode:
        workspace = await self._require_workspace(workspace_id)
        await self._require_membership(workspace.id, actor_user_id)
        return await self._require_node_in_workspace(workspace.id, node_id)

    async def update_node(
        self,
        workspace_id: str,
        node_id: str,
        actor_user_id: str,
        node_type: TopologyNodeType | None = None,
        title: str | None = None,
        ref_id: str | None = None,
        position_x: float | None = None,
        position_y: float | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> TopologyNode:
        workspace = await self._require_workspace(workspace_id)
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.EDITOR,
            error_message="Insufficient permission to update topology node",
        )
        node = await self._require_node_in_workspace(workspace.id, node_id)

        if node_type is not None:
            node.node_type = node_type
        if title is not None:
            node.title = title
        if ref_id is not None:
            node.ref_id = ref_id
        if position_x is not None:
            node.position_x = position_x
        if position_y is not None:
            node.position_y = position_y
        if data is not None:
            node.data = dict(data)
        node.updated_at = datetime.now(UTC)
        return await self._topology_repo.save_node(node)

    async def delete_node(
        self,
        workspace_id: str,
        node_id: str,
        actor_user_id: str,
    ) -> bool:
        workspace = await self._require_workspace(workspace_id)
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.EDITOR,
            error_message="Insufficient permission to delete topology node",
        )
        await self._require_node_in_workspace(workspace.id, node_id)
        return await self._topology_repo.delete_node(node_id)

    async def create_edge(
        self,
        workspace_id: str,
        actor_user_id: str,
        source_node_id: str,
        target_node_id: str,
        label: str | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> TopologyEdge:
        workspace = await self._require_workspace(workspace_id)
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.EDITOR,
            error_message="Insufficient permission to create topology edge",
        )
        await self._validate_edge_endpoints(workspace.id, source_node_id, target_node_id)

        now = datetime.now(UTC)
        edge = TopologyEdge(
            id=TopologyEdge.generate_id(),
            workspace_id=workspace.id,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            label=label,
            data=dict(data or {}),
            created_at=now,
            updated_at=now,
        )
        return await self._topology_repo.save_edge(edge)

    async def list_edges(
        self,
        workspace_id: str,
        actor_user_id: str,
        limit: int = 2000,
        offset: int = 0,
    ) -> list[TopologyEdge]:
        workspace = await self._require_workspace(workspace_id)
        await self._require_membership(workspace.id, actor_user_id)
        return await self._topology_repo.list_edges_by_workspace(
            workspace_id=workspace.id,
            limit=limit,
            offset=offset,
        )

    async def get_edge(
        self,
        workspace_id: str,
        edge_id: str,
        actor_user_id: str,
    ) -> TopologyEdge:
        workspace = await self._require_workspace(workspace_id)
        await self._require_membership(workspace.id, actor_user_id)
        return await self._require_edge_in_workspace(workspace.id, edge_id)

    async def update_edge(
        self,
        workspace_id: str,
        edge_id: str,
        actor_user_id: str,
        source_node_id: str | None = None,
        target_node_id: str | None = None,
        label: str | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> TopologyEdge:
        workspace = await self._require_workspace(workspace_id)
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.EDITOR,
            error_message="Insufficient permission to update topology edge",
        )
        edge = await self._require_edge_in_workspace(workspace.id, edge_id)

        next_source_id = source_node_id if source_node_id is not None else edge.source_node_id
        next_target_id = target_node_id if target_node_id is not None else edge.target_node_id
        await self._validate_edge_endpoints(workspace.id, next_source_id, next_target_id)

        edge.source_node_id = next_source_id
        edge.target_node_id = next_target_id
        edge.label = label
        if data is not None:
            edge.data = dict(data)
        edge.updated_at = datetime.now(UTC)
        return await self._topology_repo.save_edge(edge)

    async def delete_edge(
        self,
        workspace_id: str,
        edge_id: str,
        actor_user_id: str,
    ) -> bool:
        workspace = await self._require_workspace(workspace_id)
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.EDITOR,
            error_message="Insufficient permission to delete topology edge",
        )
        await self._require_edge_in_workspace(workspace.id, edge_id)
        return await self._topology_repo.delete_edge(edge_id)

    async def _validate_edge_endpoints(
        self,
        workspace_id: str,
        source_node_id: str,
        target_node_id: str,
    ) -> None:
        source = await self._topology_repo.find_node_by_id(source_node_id)
        if source is None:
            raise ValueError(f"Source node {source_node_id} not found")
        target = await self._topology_repo.find_node_by_id(target_node_id)
        if target is None:
            raise ValueError(f"Target node {target_node_id} not found")
        if source.workspace_id != workspace_id or target.workspace_id != workspace_id:
            raise ValueError("Edge endpoints must exist in same workspace")

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

    async def _require_node_in_workspace(self, workspace_id: str, node_id: str) -> TopologyNode:
        node = await self._topology_repo.find_node_by_id(node_id)
        if node is None:
            raise ValueError(f"Node {node_id} not found")
        if node.workspace_id != workspace_id:
            raise ValueError("Node does not belong to workspace")
        return node

    async def _require_edge_in_workspace(self, workspace_id: str, edge_id: str) -> TopologyEdge:
        edge = await self._topology_repo.find_edge_by_id(edge_id)
        if edge is None:
            raise ValueError(f"Edge {edge_id} not found")
        if edge.workspace_id != workspace_id:
            raise ValueError("Edge does not belong to workspace")
        return edge

    @staticmethod
    def _role_weight(role: WorkspaceRole) -> int:
        if role == WorkspaceRole.OWNER:
            return 300
        if role == WorkspaceRole.EDITOR:
            return 200
        return 100
