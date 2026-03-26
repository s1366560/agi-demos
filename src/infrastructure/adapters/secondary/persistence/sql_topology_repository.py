"""SQLAlchemy repository for workspace topology persistence."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace.topology_edge import TopologyEdge
from src.domain.model.workspace.topology_node import TopologyNode, TopologyNodeType
from src.domain.ports.repositories.workspace.topology_repository import TopologyRepository
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import (
    TopologyEdgeModel,
    TopologyNodeModel,
)


class SqlTopologyRepository(BaseRepository[TopologyNode, TopologyNodeModel], TopologyRepository):
    """SQLAlchemy implementation of TopologyRepository."""

    _model_class = TopologyNodeModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def save_node(self, node: TopologyNode) -> TopologyNode:
        await self.save(node)
        return node

    async def find_node_by_id(self, node_id: str) -> TopologyNode | None:
        return await self.find_by_id(node_id)

    async def list_nodes_by_workspace(
        self,
        workspace_id: str,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[TopologyNode]:
        query = (
            select(TopologyNodeModel)
            .where(TopologyNodeModel.workspace_id == workspace_id)
            .order_by(TopologyNodeModel.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(query)
        rows = result.scalars().all()
        return [n for row in rows if (n := self._to_domain(row)) is not None]

    async def save_edge(self, edge: TopologyEdge) -> TopologyEdge:
        existing = await self._session.get(TopologyEdgeModel, edge.id)
        if existing:
            existing.source_node_id = edge.source_node_id
            existing.target_node_id = edge.target_node_id
            existing.label = edge.label
            existing.source_hex_q = edge.source_hex_q
            existing.source_hex_r = edge.source_hex_r
            existing.target_hex_q = edge.target_hex_q
            existing.target_hex_r = edge.target_hex_r
            existing.direction = edge.direction
            existing.auto_created = edge.auto_created
            existing.data_json = edge.data
            existing.updated_at = edge.updated_at
        else:
            self._session.add(
                TopologyEdgeModel(
                    id=edge.id,
                    workspace_id=edge.workspace_id,
                    source_node_id=edge.source_node_id,
                    target_node_id=edge.target_node_id,
                    label=edge.label,
                    source_hex_q=edge.source_hex_q,
                    source_hex_r=edge.source_hex_r,
                    target_hex_q=edge.target_hex_q,
                    target_hex_r=edge.target_hex_r,
                    direction=edge.direction,
                    auto_created=edge.auto_created,
                    data_json=edge.data,
                    created_at=edge.created_at,
                    updated_at=edge.updated_at,
                )
            )
        await self._session.flush()
        return edge

    async def find_edge_by_id(self, edge_id: str) -> TopologyEdge | None:
        row = await self._session.get(TopologyEdgeModel, edge_id)
        return self._edge_to_domain(row) if row else None

    async def list_edges_by_workspace(
        self,
        workspace_id: str,
        limit: int = 2000,
        offset: int = 0,
    ) -> list[TopologyEdge]:
        query = (
            select(TopologyEdgeModel)
            .where(TopologyEdgeModel.workspace_id == workspace_id)
            .order_by(TopologyEdgeModel.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(query)
        rows = result.scalars().all()
        return [self._edge_to_domain(row) for row in rows]

    async def delete_node(self, node_id: str) -> bool:
        return await self.delete(node_id)

    async def delete_edge(self, edge_id: str) -> bool:
        existing = await self._session.get(TopologyEdgeModel, edge_id)
        if existing is None:
            return False
        await self._session.delete(existing)
        await self._session.flush()
        return True

    def _to_domain(self, db_node: TopologyNodeModel | None) -> TopologyNode | None:
        if db_node is None:
            return None

        return TopologyNode(
            id=db_node.id,
            workspace_id=db_node.workspace_id,
            node_type=TopologyNodeType(db_node.node_type),
            ref_id=db_node.ref_id,
            title=db_node.title,
            position_x=db_node.position_x,
            position_y=db_node.position_y,
            hex_q=db_node.hex_q,
            hex_r=db_node.hex_r,
            status=db_node.status,
            tags=db_node.tags_json or [],
            data=db_node.data_json or {},
            created_at=db_node.created_at,
            updated_at=db_node.updated_at,
        )

    def _to_db(self, domain_entity: TopologyNode) -> TopologyNodeModel:
        return TopologyNodeModel(
            id=domain_entity.id,
            workspace_id=domain_entity.workspace_id,
            node_type=domain_entity.node_type.value,
            ref_id=domain_entity.ref_id,
            title=domain_entity.title,
            position_x=domain_entity.position_x,
            position_y=domain_entity.position_y,
            hex_q=domain_entity.hex_q,
            hex_r=domain_entity.hex_r,
            status=domain_entity.status,
            tags_json=domain_entity.tags,
            data_json=domain_entity.data,
            created_at=domain_entity.created_at,
            updated_at=domain_entity.updated_at,
        )

    def _update_fields(self, db_model: TopologyNodeModel, domain_entity: TopologyNode) -> None:
        db_model.node_type = domain_entity.node_type.value
        db_model.ref_id = domain_entity.ref_id
        db_model.title = domain_entity.title
        db_model.position_x = domain_entity.position_x
        db_model.position_y = domain_entity.position_y
        db_model.hex_q = domain_entity.hex_q
        db_model.hex_r = domain_entity.hex_r
        db_model.status = domain_entity.status
        db_model.tags_json = domain_entity.tags
        db_model.data_json = domain_entity.data
        db_model.updated_at = domain_entity.updated_at

    @staticmethod
    def _edge_to_domain(db_edge: TopologyEdgeModel) -> TopologyEdge:
        return TopologyEdge(
            id=db_edge.id,
            workspace_id=db_edge.workspace_id,
            source_node_id=db_edge.source_node_id,
            target_node_id=db_edge.target_node_id,
            label=db_edge.label,
            source_hex_q=db_edge.source_hex_q,
            source_hex_r=db_edge.source_hex_r,
            target_hex_q=db_edge.target_hex_q,
            target_hex_r=db_edge.target_hex_r,
            direction=db_edge.direction,
            auto_created=db_edge.auto_created,
            data=db_edge.data_json or {},
            created_at=db_edge.created_at,
            updated_at=db_edge.updated_at,
        )
