"""API endpoints for agent graph orchestration."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.graph.agent_graph import AgentGraph
from src.domain.model.agent.graph.graph_pattern import GraphPattern
from src.domain.model.agent.graph.graph_run import GraphRun
from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db

from .utils import get_container_with_db

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class AgentNodeSchema(BaseModel):
    node_id: str
    agent_definition_id: str
    label: str
    instruction: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    is_entry: bool = False
    is_terminal: bool = False


class AgentEdgeSchema(BaseModel):
    source_node_id: str
    target_node_id: str
    condition: str = ""


class CreateGraphRequest(BaseModel):
    name: str
    description: str = ""
    pattern: str
    nodes: list[AgentNodeSchema]
    edges: list[AgentEdgeSchema]
    shared_context_keys: list[str] = Field(default_factory=list)
    max_total_steps: int = 50
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateGraphRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    nodes: list[AgentNodeSchema] | None = None
    edges: list[AgentEdgeSchema] | None = None
    shared_context_keys: list[str] | None = None
    max_total_steps: int | None = None
    metadata: dict[str, Any] | None = None
    is_active: bool | None = None


class GraphResponse(BaseModel):
    id: str
    tenant_id: str
    project_id: str
    name: str
    description: str
    pattern: str
    nodes: list[AgentNodeSchema]
    edges: list[AgentEdgeSchema]
    shared_context_keys: list[str]
    max_total_steps: int
    metadata: dict[str, Any]
    is_active: bool
    created_at: str
    updated_at: str | None = None


class GraphListResponse(BaseModel):
    graphs: list[GraphResponse]
    total: int


class NodeExecutionResponse(BaseModel):
    id: str
    node_id: str
    agent_session_id: str | None = None
    status: str
    input_context: dict[str, Any]
    output_context: dict[str, Any]
    error_message: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    created_at: str


class GraphRunResponse(BaseModel):
    id: str
    graph_id: str
    conversation_id: str
    tenant_id: str
    project_id: str
    status: str
    shared_context: dict[str, Any]
    current_node_ids: list[str]
    total_steps: int
    max_total_steps: int
    error_message: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    created_at: str
    node_executions: list[NodeExecutionResponse] = Field(default_factory=list)


class GraphRunListResponse(BaseModel):
    runs: list[GraphRunResponse]
    total: int


class StartRunRequest(BaseModel):
    conversation_id: str
    initial_context: dict[str, Any] = Field(default_factory=dict)
    parent_session_id: str | None = None
    parent_agent_id: str | None = None


class CancelRunRequest(BaseModel):
    reason: str = "User requested cancellation"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _graph_to_response(graph: AgentGraph) -> GraphResponse:
    return GraphResponse(
        id=graph.id,
        tenant_id=graph.tenant_id,
        project_id=graph.project_id,
        name=graph.name,
        description=graph.description,
        pattern=graph.pattern.value,
        nodes=[
            AgentNodeSchema(
                node_id=n.node_id,
                agent_definition_id=n.agent_definition_id,
                label=n.label,
                instruction=n.instruction,
                config=n.config,
                is_entry=n.is_entry,
                is_terminal=n.is_terminal,
            )
            for n in graph.nodes
        ],
        edges=[
            AgentEdgeSchema(
                source_node_id=e.source_node_id,
                target_node_id=e.target_node_id,
                condition=e.condition,
            )
            for e in graph.edges
        ],
        shared_context_keys=list(graph.shared_context_keys),
        max_total_steps=graph.max_total_steps,
        metadata=graph.metadata,
        is_active=graph.is_active,
        created_at=graph.created_at.isoformat() if graph.created_at else "",
        updated_at=graph.updated_at.isoformat() if graph.updated_at else None,
    )


def _run_to_response(run: GraphRun, *, include_executions: bool = False) -> GraphRunResponse:
    node_executions: list[NodeExecutionResponse] = []
    if include_executions:
        for ne in run.node_executions.values():
            node_executions.append(
                NodeExecutionResponse(
                    id=ne.id,
                    node_id=ne.node_id,
                    agent_session_id=ne.agent_session_id,
                    status=ne.status.value,
                    input_context=ne.input_context,
                    output_context=ne.output_context,
                    error_message=ne.error_message,
                    started_at=ne.started_at.isoformat() if ne.started_at else None,
                    completed_at=ne.completed_at.isoformat() if ne.completed_at else None,
                    created_at=ne.created_at.isoformat() if ne.created_at else "",
                )
            )

    return GraphRunResponse(
        id=run.id,
        graph_id=run.graph_id,
        conversation_id=run.conversation_id,
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        status=run.status.value,
        shared_context=run.shared_context,
        current_node_ids=list(run.current_node_ids),
        total_steps=run.total_steps,
        max_total_steps=run.max_total_steps,
        error_message=run.error_message,
        started_at=run.started_at.isoformat() if run.started_at else None,
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        created_at=run.created_at.isoformat() if run.created_at else "",
        node_executions=node_executions,
    )


# ---------------------------------------------------------------------------
# Graph CRUD endpoints
# ---------------------------------------------------------------------------


def _apply_graph_updates(graph: AgentGraph, body: UpdateGraphRequest) -> None:
    """Apply update request fields to graph entity."""
    from src.domain.model.agent.graph.agent_edge import AgentEdge
    from src.domain.model.agent.graph.agent_node import AgentNode

    if body.name is not None:
        graph.name = body.name
    if body.description is not None:
        graph.description = body.description
    if body.shared_context_keys is not None:
        graph.shared_context_keys = body.shared_context_keys
    if body.max_total_steps is not None:
        graph.max_total_steps = body.max_total_steps
    if body.metadata is not None:
        graph.metadata = body.metadata
    if body.is_active is not None:
        graph.is_active = body.is_active
    if body.nodes is not None:
        graph.nodes = [
            AgentNode(
                node_id=n.node_id,
                agent_definition_id=n.agent_definition_id,
                label=n.label,
                instruction=n.instruction,
                config=n.config,
                is_entry=n.is_entry,
                is_terminal=n.is_terminal,
            )
            for n in body.nodes
        ]
    if body.edges is not None:
        graph.edges = [
            AgentEdge(
                source_node_id=e.source_node_id,
                target_node_id=e.target_node_id,
                condition=e.condition,
            )
            for e in body.edges
        ]


@router.get("/graphs", response_model=GraphListResponse)
async def list_graphs(
    request: Request,
    project_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    user_tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> GraphListResponse:
    container = get_container_with_db(request, db)
    repo = container.graph_repository()
    try:
        graphs = await repo.list_by_project(tenant_id=user_tenant_id, project_id=project_id)
        return GraphListResponse(
            graphs=[_graph_to_response(g) for g in graphs],
            total=len(graphs),
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to list graphs")
        raise HTTPException(status_code=500, detail="Failed to list graphs") from None


@router.post("/graphs", response_model=GraphResponse, status_code=201)
async def create_graph(
    request: Request,
    body: CreateGraphRequest,
    project_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    user_tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> GraphResponse:
    from src.domain.model.agent.graph.agent_edge import AgentEdge
    from src.domain.model.agent.graph.agent_node import AgentNode

    try:
        pattern = GraphPattern(body.pattern)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid pattern: {body.pattern}. Valid: {[p.value for p in GraphPattern]}",
        ) from exc

    nodes = [
        AgentNode(
            node_id=n.node_id,
            agent_definition_id=n.agent_definition_id,
            label=n.label,
            instruction=n.instruction,
            config=n.config,
            is_entry=n.is_entry,
            is_terminal=n.is_terminal,
        )
        for n in body.nodes
    ]
    edges = [
        AgentEdge(
            source_node_id=e.source_node_id,
            target_node_id=e.target_node_id,
            condition=e.condition,
        )
        for e in body.edges
    ]

    graph = AgentGraph(
        tenant_id=user_tenant_id,
        project_id=project_id,
        name=body.name,
        description=body.description,
        pattern=pattern,
        nodes=nodes,
        edges=edges,
        shared_context_keys=body.shared_context_keys,
        max_total_steps=body.max_total_steps,
        metadata=body.metadata,
    )

    validation_errors = graph.validate_graph()
    if validation_errors:
        raise HTTPException(status_code=400, detail="; ".join(validation_errors))

    container = get_container_with_db(request, db)
    repo = container.graph_repository()
    try:
        await repo.save(graph)
        await db.commit()
        return _graph_to_response(graph)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to create graph")
        raise HTTPException(status_code=500, detail="Failed to create graph") from None


@router.get("/graphs/{graph_id}", response_model=GraphResponse)
async def get_graph(
    request: Request,
    graph_id: str,
    current_user: User = Depends(get_current_user),
    user_tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> GraphResponse:
    container = get_container_with_db(request, db)
    repo = container.graph_repository()
    try:
        graph = await repo.find_by_id(graph_id)
    except Exception:
        logger.exception("Failed to get graph %s", graph_id)
        raise HTTPException(status_code=500, detail="Failed to get graph") from None
    if graph is None or graph.tenant_id != user_tenant_id:
        raise HTTPException(status_code=404, detail="Graph not found")
    return _graph_to_response(graph)


@router.put("/graphs/{graph_id}", response_model=GraphResponse)
async def update_graph(
    request: Request,
    graph_id: str,
    body: UpdateGraphRequest,
    current_user: User = Depends(get_current_user),
    user_tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> GraphResponse:
    container = get_container_with_db(request, db)
    repo = container.graph_repository()
    try:
        graph = await repo.find_by_id(graph_id)
    except Exception:
        logger.exception("Failed to find graph %s for update", graph_id)
        raise HTTPException(status_code=500, detail="Failed to update graph") from None

    if graph is None or graph.tenant_id != user_tenant_id:
        raise HTTPException(status_code=404, detail="Graph not found")

    _apply_graph_updates(graph, body)

    validation_errors = graph.validate_graph()
    if validation_errors:
        raise HTTPException(status_code=400, detail="; ".join(validation_errors))

    try:
        await repo.save(graph)
        await db.commit()
        return _graph_to_response(graph)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to update graph %s", graph_id)
        raise HTTPException(status_code=500, detail="Failed to update graph") from None


@router.delete("/graphs/{graph_id}", status_code=204)
async def delete_graph(
    request: Request,
    graph_id: str,
    current_user: User = Depends(get_current_user),
    user_tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> None:
    container = get_container_with_db(request, db)
    repo = container.graph_repository()
    try:
        graph = await repo.find_by_id(graph_id)
    except Exception:
        logger.exception("Failed to find graph %s for deletion", graph_id)
        raise HTTPException(status_code=500, detail="Failed to delete graph") from None

    if graph is None or graph.tenant_id != user_tenant_id:
        raise HTTPException(status_code=404, detail="Graph not found")

    try:
        await repo.delete(graph_id)
        await db.commit()
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to delete graph %s", graph_id)
        raise HTTPException(status_code=500, detail="Failed to delete graph") from None


# ---------------------------------------------------------------------------
# Graph Run endpoints
# ---------------------------------------------------------------------------


@router.post("/graphs/{graph_id}/runs", response_model=GraphRunResponse, status_code=201)
async def start_graph_run(
    request: Request,
    graph_id: str,
    body: StartRunRequest,
    project_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    user_tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> GraphRunResponse:
    container = get_container_with_db(request, db)
    orchestrator = container.graph_orchestrator()
    try:
        run, _events = await orchestrator.start_run(
            graph_id=graph_id,
            conversation_id=body.conversation_id,
            tenant_id=user_tenant_id,
            project_id=project_id,
            initial_context=body.initial_context,
            parent_session_id=body.parent_session_id,
            parent_agent_id=body.parent_agent_id,
        )
        await db.commit()
        return _run_to_response(run, include_executions=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to start graph run for graph %s", graph_id)
        raise HTTPException(status_code=500, detail="Failed to start graph run") from None


@router.get("/graphs/{graph_id}/runs", response_model=GraphRunListResponse)
async def list_graph_runs(
    request: Request,
    graph_id: str,
    current_user: User = Depends(get_current_user),
    user_tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> GraphRunListResponse:
    container = get_container_with_db(request, db)
    orchestrator = container.graph_orchestrator()
    try:
        runs = await orchestrator.list_runs_for_graph(graph_id)
        return GraphRunListResponse(
            runs=[_run_to_response(r) for r in runs],
            total=len(runs),
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to list runs for graph %s", graph_id)
        raise HTTPException(status_code=500, detail="Failed to list graph runs") from None


@router.get("/graphs/runs/{run_id}", response_model=GraphRunResponse)
async def get_graph_run(
    request: Request,
    run_id: str,
    current_user: User = Depends(get_current_user),
    user_tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> GraphRunResponse:
    container = get_container_with_db(request, db)
    orchestrator = container.graph_orchestrator()
    try:
        run = await orchestrator.get_run_status(run_id)
    except Exception:
        logger.exception("Failed to get run %s", run_id)
        raise HTTPException(status_code=500, detail="Failed to get graph run") from None
    if run is None or run.tenant_id != user_tenant_id:
        raise HTTPException(status_code=404, detail="Graph run not found")
    return _run_to_response(run, include_executions=True)


@router.post("/graphs/runs/{run_id}/cancel", response_model=GraphRunResponse)
async def cancel_graph_run(
    request: Request,
    run_id: str,
    body: CancelRunRequest | None = None,
    current_user: User = Depends(get_current_user),
    user_tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> GraphRunResponse:
    container = get_container_with_db(request, db)
    orchestrator = container.graph_orchestrator()
    reason = body.reason if body else "User requested cancellation"
    try:
        run, _events = await orchestrator.cancel_run(run_id, reason=reason)
        await db.commit()
        if run.tenant_id != user_tenant_id:
            raise HTTPException(status_code=404, detail="Graph run not found")
        return _run_to_response(run, include_executions=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to cancel run %s", run_id)
        raise HTTPException(status_code=500, detail="Failed to cancel graph run") from None
