"""SQLAlchemy repository implementations for graph orchestration entities."""

import logging
from typing import Any, override

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.domain.model.agent.graph import (
    AgentEdge,
    AgentGraph,
    AgentNode,
    GraphPattern,
    GraphRun,
    GraphRunStatus,
    NodeExecution,
    NodeExecutionStatus,
)
from src.domain.ports.repositories.graph_repository import (
    AgentGraphRepository,
    GraphRunRepository,
)
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentGraphModel,
    GraphRunModel,
    NodeExecutionModel,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AgentGraph Repository
# ---------------------------------------------------------------------------


class SqlAgentGraphRepository(BaseRepository[AgentGraph, AgentGraphModel], AgentGraphRepository):
    """SQLAlchemy implementation of AgentGraphRepository."""

    _model_class = AgentGraphModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    # --- Interface implementation ---

    @override
    async def save(self, domain_entity: AgentGraph) -> AgentGraph:
        """Save an agent graph (create or update)."""
        result = await self._session.execute(
            select(AgentGraphModel).where(AgentGraphModel.id == domain_entity.id)
        )
        existing = result.scalar_one_or_none()

        if existing is not None:
            existing.tenant_id = domain_entity.tenant_id
            existing.project_id = domain_entity.project_id
            existing.name = domain_entity.name
            existing.description = domain_entity.description
            existing.pattern = domain_entity.pattern.value
            existing.nodes_json = [self._node_to_dict(n) for n in domain_entity.nodes]
            existing.edges_json = [self._edge_to_dict(e) for e in domain_entity.edges]
            existing.shared_context_keys = list(domain_entity.shared_context_keys)
            existing.max_total_steps = domain_entity.max_total_steps
            existing.metadata_json = dict(domain_entity.metadata)
            existing.is_active = domain_entity.is_active
        else:
            db_graph = self._to_db(domain_entity)
            self._session.add(db_graph)

        await self._session.flush()
        return domain_entity

    @override
    async def find_by_id(self, entity_id: str) -> AgentGraph | None:
        """Find a graph by its ID."""
        result = await self._session.execute(
            select(AgentGraphModel).where(AgentGraphModel.id == entity_id)
        )
        db_graph = result.scalar_one_or_none()
        return self._to_domain(db_graph)

    @override
    async def list_by_project(
        self,
        project_id: str,
        tenant_id: str,
        active_only: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AgentGraph]:
        """List graphs for a project."""
        query = (
            select(AgentGraphModel)
            .where(AgentGraphModel.project_id == project_id)
            .where(AgentGraphModel.tenant_id == tenant_id)
        )
        if active_only:
            query = query.where(AgentGraphModel.is_active.is_(True))
        query = query.order_by(AgentGraphModel.created_at.desc()).offset(offset).limit(limit)

        result = await self._session.execute(query)
        db_graphs = result.scalars().all()
        return [g for row in db_graphs if (g := self._to_domain(row)) is not None]

    @override
    async def delete(self, entity_id: str) -> bool:
        """Soft-delete a graph by setting is_active=False."""
        result = await self._session.execute(
            select(AgentGraphModel).where(AgentGraphModel.id == entity_id)
        )
        db_graph = result.scalar_one_or_none()
        if db_graph is None:
            return False

        db_graph.is_active = False
        await self._session.flush()
        return True

    @override
    async def count_by_project(
        self,
        project_id: str,
        tenant_id: str,
        active_only: bool = True,
    ) -> int:
        """Count graphs for a project."""
        query = (
            select(func.count())
            .select_from(AgentGraphModel)
            .where(AgentGraphModel.project_id == project_id)
            .where(AgentGraphModel.tenant_id == tenant_id)
        )
        if active_only:
            query = query.where(AgentGraphModel.is_active.is_(True))

        result = await self._session.execute(query)
        return result.scalar_one()

    # --- Node / Edge conversion helpers ---

    @staticmethod
    def _node_to_dict(node: AgentNode) -> dict[str, Any]:
        """Convert an AgentNode to a JSON-serializable dictionary."""
        return {
            "node_id": node.node_id,
            "agent_definition_id": node.agent_definition_id,
            "label": node.label,
            "instruction": node.instruction,
            "config": node.config,
            "is_entry": node.is_entry,
            "is_terminal": node.is_terminal,
        }

    @staticmethod
    def _node_from_dict(data: dict[str, Any]) -> AgentNode:
        """Convert a dictionary to an AgentNode."""
        return AgentNode(
            node_id=data["node_id"],
            agent_definition_id=data["agent_definition_id"],
            label=data["label"],
            instruction=data.get("instruction", ""),
            config=data.get("config", {}),
            is_entry=data.get("is_entry", False),
            is_terminal=data.get("is_terminal", False),
        )

    @staticmethod
    def _edge_to_dict(edge: AgentEdge) -> dict[str, Any]:
        """Convert an AgentEdge to a JSON-serializable dictionary."""
        return {
            "source_node_id": edge.source_node_id,
            "target_node_id": edge.target_node_id,
            "condition": edge.condition,
        }

    @staticmethod
    def _edge_from_dict(data: dict[str, Any]) -> AgentEdge:
        """Convert a dictionary to an AgentEdge."""
        return AgentEdge(
            source_node_id=data["source_node_id"],
            target_node_id=data["target_node_id"],
            condition=data.get("condition", ""),
        )

    # --- Domain conversion ---

    @override
    def _to_domain(self, db_model: AgentGraphModel | None) -> AgentGraph | None:
        """Convert database model to domain entity."""
        if db_model is None:
            return None

        nodes = [self._node_from_dict(n) for n in (db_model.nodes_json or [])]
        edges = [self._edge_from_dict(e) for e in (db_model.edges_json or [])]

        return AgentGraph(
            id=db_model.id,
            tenant_id=db_model.tenant_id,
            project_id=db_model.project_id,
            name=db_model.name,
            description=db_model.description,
            pattern=GraphPattern(db_model.pattern),
            nodes=nodes,
            edges=edges,
            shared_context_keys=list(db_model.shared_context_keys or []),
            max_total_steps=db_model.max_total_steps,
            metadata=dict(db_model.metadata_json or {}),
            is_active=db_model.is_active,
            created_at=db_model.created_at,
            updated_at=db_model.updated_at or db_model.created_at,
        )

    @override
    def _to_db(self, domain_entity: AgentGraph) -> AgentGraphModel:
        """Convert domain entity to database model."""
        return AgentGraphModel(
            id=domain_entity.id,
            tenant_id=domain_entity.tenant_id,
            project_id=domain_entity.project_id,
            name=domain_entity.name,
            description=domain_entity.description,
            pattern=domain_entity.pattern.value,
            nodes_json=[self._node_to_dict(n) for n in domain_entity.nodes],
            edges_json=[self._edge_to_dict(e) for e in domain_entity.edges],
            shared_context_keys=list(domain_entity.shared_context_keys),
            max_total_steps=domain_entity.max_total_steps,
            metadata_json=dict(domain_entity.metadata),
            is_active=domain_entity.is_active,
            created_at=domain_entity.created_at,
            updated_at=domain_entity.updated_at,
        )


# ---------------------------------------------------------------------------
# GraphRun Repository
# ---------------------------------------------------------------------------


class SqlGraphRunRepository(BaseRepository[GraphRun, GraphRunModel], GraphRunRepository):
    """SQLAlchemy implementation of GraphRunRepository.

    Uses selectinload for node_executions to avoid N+1 queries.
    """

    _model_class = GraphRunModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @override
    def _eager_load_options(self) -> list[Any]:
        """Include node_executions on every query."""
        return [selectinload(GraphRunModel.node_executions)]

    # --- Interface implementation ---

    @override
    async def save(self, domain_entity: GraphRun) -> GraphRun:
        """Save a graph run (create or update), including node executions."""
        result = await self._session.execute(
            select(GraphRunModel)
            .where(GraphRunModel.id == domain_entity.id)
            .options(selectinload(GraphRunModel.node_executions))
        )
        existing = result.scalar_one_or_none()

        if existing is not None:
            existing.status = domain_entity.status.value
            existing.shared_context = dict(domain_entity.shared_context)
            existing.current_node_ids = list(domain_entity.current_node_ids)
            existing.total_steps = domain_entity.total_steps
            existing.max_total_steps = domain_entity.max_total_steps
            existing.error_message = domain_entity.error_message
            existing.started_at = domain_entity.started_at
            existing.completed_at = domain_entity.completed_at

            # Sync node executions: build a lookup of existing DB records
            existing_ne_map: dict[str, NodeExecutionModel] = {
                ne.node_id: ne for ne in existing.node_executions
            }
            for node_id, ne_domain in domain_entity.node_executions.items():
                if node_id in existing_ne_map:
                    db_ne = existing_ne_map[node_id]
                    db_ne.agent_session_id = ne_domain.agent_session_id
                    db_ne.status = ne_domain.status.value
                    db_ne.input_context = dict(ne_domain.input_context)
                    db_ne.output_context = dict(ne_domain.output_context)
                    db_ne.error_message = ne_domain.error_message
                    db_ne.started_at = ne_domain.started_at
                    db_ne.completed_at = ne_domain.completed_at
                else:
                    new_ne = NodeExecutionModel(
                        id=ne_domain.id,
                        graph_run_id=domain_entity.id,
                        node_id=ne_domain.node_id,
                        agent_session_id=ne_domain.agent_session_id,
                        status=ne_domain.status.value,
                        input_context=dict(ne_domain.input_context),
                        output_context=dict(ne_domain.output_context),
                        error_message=ne_domain.error_message,
                        started_at=ne_domain.started_at,
                        completed_at=ne_domain.completed_at,
                    )
                    existing.node_executions.append(new_ne)
        else:
            db_run = self._to_db(domain_entity)
            self._session.add(db_run)

        await self._session.flush()
        return domain_entity

    @override
    async def find_by_id(self, entity_id: str) -> GraphRun | None:
        """Find a graph run by ID, including its node executions."""
        result = await self._session.execute(
            select(GraphRunModel)
            .where(GraphRunModel.id == entity_id)
            .options(selectinload(GraphRunModel.node_executions))
        )
        db_run = result.scalar_one_or_none()
        return self._to_domain(db_run)

    @override
    async def list_by_graph(
        self,
        graph_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[GraphRun]:
        """List runs for a specific graph definition."""
        result = await self._session.execute(
            select(GraphRunModel)
            .where(GraphRunModel.graph_id == graph_id)
            .options(selectinload(GraphRunModel.node_executions))
            .order_by(GraphRunModel.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        db_runs = result.scalars().all()
        return [r for row in db_runs if (r := self._to_domain(row)) is not None]

    @override
    async def list_by_conversation(
        self,
        conversation_id: str,
        limit: int = 50,
    ) -> list[GraphRun]:
        """List runs associated with a conversation."""
        result = await self._session.execute(
            select(GraphRunModel)
            .where(GraphRunModel.conversation_id == conversation_id)
            .options(selectinload(GraphRunModel.node_executions))
            .order_by(GraphRunModel.created_at.desc())
            .limit(limit)
        )
        db_runs = result.scalars().all()
        return [r for row in db_runs if (r := self._to_domain(row)) is not None]

    @override
    async def find_active_by_conversation(
        self,
        conversation_id: str,
    ) -> GraphRun | None:
        """Find the currently active (non-terminal) run for a conversation."""
        terminal_statuses = [s.value for s in GraphRunStatus if s.is_terminal]
        result = await self._session.execute(
            select(GraphRunModel)
            .where(GraphRunModel.conversation_id == conversation_id)
            .where(GraphRunModel.status.notin_(terminal_statuses))
            .options(selectinload(GraphRunModel.node_executions))
            .order_by(GraphRunModel.created_at.desc())
            .limit(1)
        )
        db_run = result.scalar_one_or_none()
        return self._to_domain(db_run)

    @override
    async def delete_by_graph(self, graph_id: str) -> None:
        """Delete all runs for a graph (cascade deletes node_executions)."""
        await self._session.execute(delete(GraphRunModel).where(GraphRunModel.graph_id == graph_id))
        await self._session.flush()

    # --- Domain conversion ---

    @override
    def _to_domain(self, db_model: GraphRunModel | None) -> GraphRun | None:
        """Convert database model to domain entity, including nested node executions."""
        if db_model is None:
            return None

        node_executions: dict[str, NodeExecution] = {}
        for db_ne in db_model.node_executions:
            node_executions[db_ne.node_id] = NodeExecution(
                id=db_ne.id,
                graph_run_id=db_ne.graph_run_id,
                node_id=db_ne.node_id,
                agent_session_id=db_ne.agent_session_id,
                status=NodeExecutionStatus(db_ne.status),
                input_context=dict(db_ne.input_context or {}),
                output_context=dict(db_ne.output_context or {}),
                error_message=db_ne.error_message,
                started_at=db_ne.started_at,
                completed_at=db_ne.completed_at,
            )

        return GraphRun(
            id=db_model.id,
            graph_id=db_model.graph_id,
            conversation_id=db_model.conversation_id,
            tenant_id=db_model.tenant_id,
            project_id=db_model.project_id,
            status=GraphRunStatus(db_model.status),
            node_executions=node_executions,
            shared_context=dict(db_model.shared_context or {}),
            current_node_ids=list(db_model.current_node_ids or []),
            total_steps=db_model.total_steps,
            max_total_steps=db_model.max_total_steps,
            error_message=db_model.error_message,
            started_at=db_model.started_at,
            completed_at=db_model.completed_at,
            created_at=db_model.created_at,
        )

    @override
    def _to_db(self, domain_entity: GraphRun) -> GraphRunModel:
        """Convert domain entity to database model, including nested node executions."""
        db_node_executions = [
            NodeExecutionModel(
                id=ne.id,
                graph_run_id=domain_entity.id,
                node_id=ne.node_id,
                agent_session_id=ne.agent_session_id,
                status=ne.status.value,
                input_context=dict(ne.input_context),
                output_context=dict(ne.output_context),
                error_message=ne.error_message,
                started_at=ne.started_at,
                completed_at=ne.completed_at,
            )
            for ne in domain_entity.node_executions.values()
        ]

        return GraphRunModel(
            id=domain_entity.id,
            graph_id=domain_entity.graph_id,
            conversation_id=domain_entity.conversation_id,
            tenant_id=domain_entity.tenant_id,
            project_id=domain_entity.project_id,
            status=domain_entity.status.value,
            shared_context=dict(domain_entity.shared_context),
            current_node_ids=list(domain_entity.current_node_ids),
            total_steps=domain_entity.total_steps,
            max_total_steps=domain_entity.max_total_steps,
            error_message=domain_entity.error_message,
            started_at=domain_entity.started_at,
            completed_at=domain_entity.completed_at,
            node_executions=db_node_executions,
        )
