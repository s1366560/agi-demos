"""Application service for workspace topology nodes and edges."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from src.application.services.workspace_layout_limits import (
    validate_hex_target,
    validate_position_value,
)
from src.domain.model.workspace.topology_edge import TopologyEdge
from src.domain.model.workspace.topology_node import TopologyNode, TopologyNodeType
from src.domain.model.workspace.workspace import Workspace
from src.domain.model.workspace.workspace_member import WorkspaceMember
from src.domain.model.workspace.workspace_role import WorkspaceRole
from src.domain.ports.repositories.workspace.topology_repository import TopologyRepository
from src.domain.ports.repositories.workspace.workspace_agent_repository import (
    WorkspaceAgentRepository,
)
from src.domain.ports.repositories.workspace.workspace_member_repository import (
    WorkspaceMemberRepository,
)
from src.domain.ports.repositories.workspace.workspace_repository import WorkspaceRepository

RESERVED_BLACKBOARD_HEX = (0, 0)
MAX_TOPOLOGY_REF_ID_LENGTH = 255
MAX_TOPOLOGY_TITLE_LENGTH = 64
MAX_TOPOLOGY_STATUS_LENGTH = 32
MAX_TOPOLOGY_LABEL_LENGTH = 64
MAX_TOPOLOGY_DIRECTION_LENGTH = 32
MAX_TOPOLOGY_TAG_COUNT = 12
MAX_TOPOLOGY_TAG_LENGTH = 32
MAX_TOPOLOGY_DATA_KEYS = 16
MAX_TOPOLOGY_DATA_LIST_ITEMS = 16
MAX_TOPOLOGY_DATA_KEY_LENGTH = 32
MAX_TOPOLOGY_DATA_STRING_LENGTH = 256
MAX_TOPOLOGY_DATA_DEPTH = 3
MAX_TOPOLOGY_DATA_BYTES = 2048


def _validate_optional_text_length(
    value: str | None,
    *,
    field_name: str,
    max_length: int,
) -> None:
    if value is not None and len(value) > max_length:
        raise ValueError(f"{field_name} must be {max_length} characters or fewer")


def _validate_tags(tags: list[str] | None) -> list[str]:
    normalized = list(tags or [])
    if len(normalized) > MAX_TOPOLOGY_TAG_COUNT:
        raise ValueError(f"tags must contain {MAX_TOPOLOGY_TAG_COUNT} items or fewer")
    for tag in normalized:
        if len(tag) > MAX_TOPOLOGY_TAG_LENGTH:
            raise ValueError(f"tag values must be {MAX_TOPOLOGY_TAG_LENGTH} characters or fewer")
    return normalized


def _validate_topology_list(values: list[object], *, depth: int) -> None:
    if len(values) > MAX_TOPOLOGY_DATA_LIST_ITEMS:
        raise ValueError(
            f"Topology data arrays must contain {MAX_TOPOLOGY_DATA_LIST_ITEMS} items or fewer"
        )
    for item in values:
        _validate_topology_json_value(item, depth=depth + 1)


def _validate_topology_dict(values: dict[str, object], *, depth: int) -> None:
    if len(values) > MAX_TOPOLOGY_DATA_KEYS:
        raise ValueError(
            f"Topology data objects must contain {MAX_TOPOLOGY_DATA_KEYS} keys or fewer"
        )
    for key, item in values.items():
        if len(key) > MAX_TOPOLOGY_DATA_KEY_LENGTH:
            raise ValueError(
                f"Topology data keys must be {MAX_TOPOLOGY_DATA_KEY_LENGTH} characters or fewer"
            )
        _validate_topology_json_value(item, depth=depth + 1)


def _validate_topology_json_value(value: object, *, depth: int = 0) -> None:
    if depth > MAX_TOPOLOGY_DATA_DEPTH:
        raise ValueError("Topology data is nested too deeply")

    if value is None or isinstance(value, (bool, int)):
        return

    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Topology data numbers must be finite")
        return

    if isinstance(value, str):
        if len(value) > MAX_TOPOLOGY_DATA_STRING_LENGTH:
            raise ValueError(
                f"Topology data string values must be {MAX_TOPOLOGY_DATA_STRING_LENGTH} characters or fewer"
        )
        return

    if isinstance(value, list):
        _validate_topology_list(value, depth=depth)
        return

    if isinstance(value, dict):
        for key, _item in value.items():
            if not isinstance(key, str):
                raise ValueError("Topology data keys must be strings")
        _validate_topology_dict(value, depth=depth)
        return

    raise ValueError("Topology data must be JSON-compatible")


def _normalize_topology_data(data: Mapping[str, Any] | None) -> dict[str, Any]:
    normalized = dict(data or {})
    _validate_topology_json_value(normalized)
    encoded = json.dumps(normalized, separators=(",", ":"), sort_keys=True, allow_nan=False)
    if len(encoded) > MAX_TOPOLOGY_DATA_BYTES:
        raise ValueError(f"Topology data must be {MAX_TOPOLOGY_DATA_BYTES} bytes or fewer")
    return normalized


def _resolve_hex_target(hex_q: int | None, hex_r: int | None) -> tuple[int, int] | None:
    if hex_q is None and hex_r is None:
        return None
    if hex_q is None or hex_r is None:
        raise ValueError("Both hex_q and hex_r must be provided together")
    validate_hex_target(hex_q, hex_r)
    if (hex_q, hex_r) == RESERVED_BLACKBOARD_HEX:
        raise ValueError("Center hex is reserved for the blackboard")
    return hex_q, hex_r


class TopologyService:
    """Orchestrates topology CRUD with workspace permission and consistency checks."""

    def __init__(
        self,
        workspace_repo: WorkspaceRepository,
        workspace_member_repo: WorkspaceMemberRepository,
        topology_repo: TopologyRepository,
        workspace_agent_repo: WorkspaceAgentRepository,
    ) -> None:
        self._workspace_repo = workspace_repo
        self._workspace_member_repo = workspace_member_repo
        self._topology_repo = topology_repo
        self._workspace_agent_repo = workspace_agent_repo

    async def create_node(
        self,
        workspace_id: str,
        actor_user_id: str,
        node_type: TopologyNodeType,
        title: str = "",
        ref_id: str | None = None,
        position_x: float = 0.0,
        position_y: float = 0.0,
        hex_q: int | None = None,
        hex_r: int | None = None,
        status: str = "active",
        tags: list[str] | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> TopologyNode:
        workspace = await self._require_workspace(workspace_id)
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.EDITOR,
            error_message="Insufficient permission to create topology node",
        )
        _validate_optional_text_length(
            ref_id,
            field_name="ref_id",
            max_length=MAX_TOPOLOGY_REF_ID_LENGTH,
        )
        _validate_optional_text_length(
            title,
            field_name="title",
            max_length=MAX_TOPOLOGY_TITLE_LENGTH,
        )
        _validate_optional_text_length(
            status,
            field_name="status",
            max_length=MAX_TOPOLOGY_STATUS_LENGTH,
        )
        validate_position_value(position_x, field_name="position_x")
        validate_position_value(position_y, field_name="position_y")
        normalized_tags = _validate_tags(tags)
        normalized_data = _normalize_topology_data(data)
        target = _resolve_hex_target(hex_q, hex_r)
        if target is not None:
            await self._topology_repo.acquire_hex_lock(workspace.id, target[0], target[1])
            await self._ensure_hex_available(workspace.id, target[0], target[1])

        now = datetime.now(UTC)
        node = TopologyNode(
            id=TopologyNode.generate_id(),
            workspace_id=workspace.id,
            node_type=node_type,
            ref_id=ref_id,
            title=title,
            position_x=position_x,
            position_y=position_y,
            hex_q=hex_q,
            hex_r=hex_r,
            status=status,
            tags=normalized_tags,
            data=normalized_data,
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

    async def list_all_nodes(
        self,
        workspace_id: str,
        actor_user_id: str,
    ) -> list[TopologyNode]:
        workspace = await self._require_workspace(workspace_id)
        await self._require_membership(workspace.id, actor_user_id)
        return await self._topology_repo.list_all_nodes_by_workspace(workspace.id)

    async def get_node(
        self,
        workspace_id: str,
        node_id: str,
        actor_user_id: str,
    ) -> TopologyNode:
        workspace = await self._require_workspace(workspace_id)
        await self._require_membership(workspace.id, actor_user_id)
        return await self._require_node_in_workspace(workspace.id, node_id)

    async def update_node(  # noqa: PLR0913, C901, PLR0912
        self,
        workspace_id: str,
        node_id: str,
        actor_user_id: str,
        node_type: TopologyNodeType | None = None,
        title: str | None = None,
        ref_id: str | None = None,
        position_x: float | None = None,
        position_y: float | None = None,
        hex_q: int | None = None,
        hex_r: int | None = None,
        status: str | None = None,
        tags: list[str] | None = None,
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
        if ref_id is not None:
            _validate_optional_text_length(
                ref_id,
                field_name="ref_id",
                max_length=MAX_TOPOLOGY_REF_ID_LENGTH,
            )
        if title is not None:
            _validate_optional_text_length(
                title,
                field_name="title",
                max_length=MAX_TOPOLOGY_TITLE_LENGTH,
            )
        if status is not None:
            _validate_optional_text_length(
                status,
                field_name="status",
                max_length=MAX_TOPOLOGY_STATUS_LENGTH,
            )
        if position_x is not None:
            validate_position_value(position_x, field_name="position_x")
        if position_y is not None:
            validate_position_value(position_y, field_name="position_y")

        next_tags = _validate_tags(tags) if tags is not None else None
        next_data = _normalize_topology_data(data) if data is not None else None

        hex_changed = False
        if hex_q is not None or hex_r is not None:
            target = _resolve_hex_target(
                hex_q if hex_q is not None else node.hex_q,
                hex_r if hex_r is not None else node.hex_r,
            )
            if target is not None:
                await self._topology_repo.acquire_hex_lock(workspace.id, target[0], target[1])
                await self._ensure_hex_available(
                    workspace.id,
                    target[0],
                    target[1],
                    exclude_node_id=node.id,
                )
            hex_changed = target is not None and (node.hex_q, node.hex_r) != target

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
        if hex_q is not None:
            node.hex_q = hex_q
        if hex_r is not None:
            node.hex_r = hex_r
        if status is not None:
            node.status = status
        if tags is not None and next_tags is not None:
            node.tags = next_tags
        if data is not None and next_data is not None:
            node.data = next_data
        node.updated_at = datetime.now(UTC)
        saved_node = await self._topology_repo.save_node(node)
        if hex_changed:
            await self._sync_edge_coordinates_for_node(workspace.id, saved_node)
        return saved_node

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
        source_hex_q: int | None = None,
        source_hex_r: int | None = None,
        target_hex_q: int | None = None,
        target_hex_r: int | None = None,
        direction: str | None = None,
        auto_created: bool = False,
        data: Mapping[str, Any] | None = None,
    ) -> TopologyEdge:
        workspace = await self._require_workspace(workspace_id)
        await self._require_minimum_role(
            workspace_id=workspace.id,
            user_id=actor_user_id,
            minimum=WorkspaceRole.EDITOR,
            error_message="Insufficient permission to create topology edge",
        )
        _validate_optional_text_length(
            label,
            field_name="label",
            max_length=MAX_TOPOLOGY_LABEL_LENGTH,
        )
        _validate_optional_text_length(
            direction,
            field_name="direction",
            max_length=MAX_TOPOLOGY_DIRECTION_LENGTH,
        )
        normalized_data = _normalize_topology_data(data)
        source_node, target_node = await self._validate_edge_endpoints(
            workspace.id, source_node_id, target_node_id
        )

        now = datetime.now(UTC)
        edge = TopologyEdge(
            id=TopologyEdge.generate_id(),
            workspace_id=workspace.id,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            label=label,
            source_hex_q=source_node.hex_q,
            source_hex_r=source_node.hex_r,
            target_hex_q=target_node.hex_q,
            target_hex_r=target_node.hex_r,
            direction=direction,
            auto_created=auto_created,
            data=normalized_data,
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

    async def list_all_edges(
        self,
        workspace_id: str,
        actor_user_id: str,
    ) -> list[TopologyEdge]:
        workspace = await self._require_workspace(workspace_id)
        await self._require_membership(workspace.id, actor_user_id)
        return await self._topology_repo.list_all_edges_by_workspace(workspace.id)

    async def get_edge(
        self,
        workspace_id: str,
        edge_id: str,
        actor_user_id: str,
    ) -> TopologyEdge:
        workspace = await self._require_workspace(workspace_id)
        await self._require_membership(workspace.id, actor_user_id)
        return await self._require_edge_in_workspace(workspace.id, edge_id)

    async def list_edges_for_node(
        self,
        workspace_id: str,
        node_id: str,
        actor_user_id: str,
    ) -> list[TopologyEdge]:
        workspace = await self._require_workspace(workspace_id)
        await self._require_membership(workspace.id, actor_user_id)
        return await self._topology_repo.list_edges_for_node(workspace.id, node_id)

    async def update_edge(  # noqa: PLR0913
        self,
        workspace_id: str,
        edge_id: str,
        actor_user_id: str,
        source_node_id: str | None = None,
        target_node_id: str | None = None,
        label: str | None = None,
        source_hex_q: int | None = None,
        source_hex_r: int | None = None,
        target_hex_q: int | None = None,
        target_hex_r: int | None = None,
        direction: str | None = None,
        auto_created: bool | None = None,
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
        if label is not None:
            _validate_optional_text_length(
                label,
                field_name="label",
                max_length=MAX_TOPOLOGY_LABEL_LENGTH,
            )
        if direction is not None:
            _validate_optional_text_length(
                direction,
                field_name="direction",
                max_length=MAX_TOPOLOGY_DIRECTION_LENGTH,
            )
        next_data = _normalize_topology_data(data) if data is not None else None

        next_source_id = source_node_id if source_node_id is not None else edge.source_node_id
        next_target_id = target_node_id if target_node_id is not None else edge.target_node_id
        source_node, target_node = await self._validate_edge_endpoints(
            workspace.id, next_source_id, next_target_id
        )

        edge.source_node_id = next_source_id
        edge.target_node_id = next_target_id
        if label is not None:
            edge.label = label
        edge.source_hex_q = source_node.hex_q
        edge.source_hex_r = source_node.hex_r
        edge.target_hex_q = target_node.hex_q
        edge.target_hex_r = target_node.hex_r
        if direction is not None:
            edge.direction = direction
        if auto_created is not None:
            edge.auto_created = auto_created
        if data is not None and next_data is not None:
            edge.data = next_data
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
    ) -> tuple[TopologyNode, TopologyNode]:
        source = await self._topology_repo.find_node_by_id(source_node_id)
        if source is None:
            raise ValueError(f"Source node {source_node_id} not found")
        target = await self._topology_repo.find_node_by_id(target_node_id)
        if target is None:
            raise ValueError(f"Target node {target_node_id} not found")
        if source.workspace_id != workspace_id or target.workspace_id != workspace_id:
            raise ValueError("Edge endpoints must exist in same workspace")
        return source, target

    async def _ensure_hex_available(
        self,
        workspace_id: str,
        hex_q: int,
        hex_r: int,
        *,
        exclude_node_id: str | None = None,
    ) -> None:
        occupying_nodes = await self._topology_repo.list_nodes_by_hex(
            workspace_id=workspace_id,
            hex_q=hex_q,
            hex_r=hex_r,
        )
        if any(node.id != exclude_node_id for node in occupying_nodes):
            raise ValueError("Hex is already occupied")

        occupying_agents = await self._workspace_agent_repo.find_by_workspace_and_hex(
            workspace_id=workspace_id,
            hex_q=hex_q,
            hex_r=hex_r,
        )
        if occupying_agents:
            raise ValueError("Hex is already occupied")

    async def _sync_edge_coordinates_for_node(
        self,
        workspace_id: str,
        node: TopologyNode,
    ) -> None:
        await self._topology_repo.sync_edge_coordinates_for_node(
            workspace_id=workspace_id,
            node_id=node.id,
            hex_q=node.hex_q,
            hex_r=node.hex_r,
        )

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
