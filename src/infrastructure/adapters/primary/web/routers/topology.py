"""Topology API routes for workspace nodes and edges."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.topology_service import TopologyService
from src.domain.events.types import AgentEventType
from src.domain.model.workspace.topology_node import TopologyNodeType
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.workspace_events import publish_workspace_event
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/topology", tags=["topology"])


def get_topology_service(request: Request, db: AsyncSession = Depends(get_db)) -> TopologyService:
    """Resolve topology service from request-scoped DI container."""
    container = request.app.state.container.with_db(db)
    return container.topology_service()


class TopologyNodeBase(BaseModel):
    node_type: TopologyNodeType
    ref_id: str | None = None
    title: str = ""
    position_x: float = 0.0
    position_y: float = 0.0
    data: dict[str, Any] = Field(default_factory=dict)


class TopologyNodeCreate(TopologyNodeBase):
    pass


class TopologyNodeUpdate(BaseModel):
    node_type: TopologyNodeType | None = None
    ref_id: str | None = None
    title: str | None = None
    position_x: float | None = None
    position_y: float | None = None
    data: dict[str, Any] | None = None


class TopologyNodeResponse(TopologyNodeBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    created_at: datetime
    updated_at: datetime | None = None


class TopologyEdgeBase(BaseModel):
    source_node_id: str
    target_node_id: str
    label: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class TopologyEdgeCreate(TopologyEdgeBase):
    pass


class TopologyEdgeUpdate(BaseModel):
    source_node_id: str | None = None
    target_node_id: str | None = None
    label: str | None = None
    data: dict[str, Any] | None = None


class TopologyEdgeResponse(TopologyEdgeBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    created_at: datetime
    updated_at: datetime | None = None


@router.post("/nodes", response_model=TopologyNodeResponse, status_code=status.HTTP_201_CREATED)
async def create_node(
    workspace_id: str,
    body: TopologyNodeCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    topology_service: TopologyService = Depends(get_topology_service),
) -> TopologyNodeResponse:
    try:
        node = await topology_service.create_node(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            node_type=body.node_type,
            ref_id=body.ref_id,
            title=body.title,
            position_x=body.position_x,
            position_y=body.position_y,
            data=body.data,
        )
        await db.commit()
        await publish_workspace_event(
            request.app.state.container.redis(),
            workspace_id=workspace_id,
            event_type=AgentEventType.TOPOLOGY_UPDATED,
            payload={"workspace_id": workspace_id, "operation": "node_created", "node_id": node.id},
        )
        return TopologyNodeResponse.model_validate(node)
    except PermissionError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/nodes", response_model=list[TopologyNodeResponse])
async def list_nodes(
    workspace_id: str,
    limit: int = 1000,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    topology_service: TopologyService = Depends(get_topology_service),
) -> list[TopologyNodeResponse]:
    try:
        nodes = await topology_service.list_nodes(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            limit=limit,
            offset=offset,
        )
        return [TopologyNodeResponse.model_validate(node) for node in nodes]
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.get("/nodes/{node_id}", response_model=TopologyNodeResponse)
async def get_node(
    workspace_id: str,
    node_id: str,
    current_user: User = Depends(get_current_user),
    topology_service: TopologyService = Depends(get_topology_service),
) -> TopologyNodeResponse:
    try:
        node = await topology_service.get_node(
            workspace_id=workspace_id,
            node_id=node_id,
            actor_user_id=current_user.id,
        )
        return TopologyNodeResponse.model_validate(node)
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except ValueError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.patch("/nodes/{node_id}", response_model=TopologyNodeResponse)
async def update_node(
    workspace_id: str,
    node_id: str,
    body: TopologyNodeUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    topology_service: TopologyService = Depends(get_topology_service),
) -> TopologyNodeResponse:
    try:
        node = await topology_service.update_node(
            workspace_id=workspace_id,
            node_id=node_id,
            actor_user_id=current_user.id,
            node_type=body.node_type,
            ref_id=body.ref_id,
            title=body.title,
            position_x=body.position_x,
            position_y=body.position_y,
            data=body.data,
        )
        await db.commit()
        await publish_workspace_event(
            request.app.state.container.redis(),
            workspace_id=workspace_id,
            event_type=AgentEventType.TOPOLOGY_UPDATED,
            payload={"workspace_id": workspace_id, "operation": "node_updated", "node_id": node.id},
        )
        return TopologyNodeResponse.model_validate(node)
    except PermissionError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except ValueError as e:
        await db.rollback()
        if "not found" in str(e).lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.delete("/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_node(
    workspace_id: str,
    node_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    topology_service: TopologyService = Depends(get_topology_service),
) -> None:
    try:
        await topology_service.delete_node(
            workspace_id=workspace_id,
            node_id=node_id,
            actor_user_id=current_user.id,
        )
        await db.commit()
        await publish_workspace_event(
            request.app.state.container.redis(),
            workspace_id=workspace_id,
            event_type=AgentEventType.TOPOLOGY_UPDATED,
            payload={"workspace_id": workspace_id, "operation": "node_deleted", "node_id": node_id},
        )
    except PermissionError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except ValueError as e:
        await db.rollback()
        if "not found" in str(e).lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/edges", response_model=TopologyEdgeResponse, status_code=status.HTTP_201_CREATED)
async def create_edge(
    workspace_id: str,
    body: TopologyEdgeCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    topology_service: TopologyService = Depends(get_topology_service),
) -> TopologyEdgeResponse:
    try:
        edge = await topology_service.create_edge(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            source_node_id=body.source_node_id,
            target_node_id=body.target_node_id,
            label=body.label,
            data=body.data,
        )
        await db.commit()
        await publish_workspace_event(
            request.app.state.container.redis(),
            workspace_id=workspace_id,
            event_type=AgentEventType.TOPOLOGY_UPDATED,
            payload={"workspace_id": workspace_id, "operation": "edge_created", "edge_id": edge.id},
        )
        return TopologyEdgeResponse.model_validate(edge)
    except PermissionError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/edges", response_model=list[TopologyEdgeResponse])
async def list_edges(
    workspace_id: str,
    limit: int = 2000,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    topology_service: TopologyService = Depends(get_topology_service),
) -> list[TopologyEdgeResponse]:
    try:
        edges = await topology_service.list_edges(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            limit=limit,
            offset=offset,
        )
        return [TopologyEdgeResponse.model_validate(edge) for edge in edges]
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.get("/edges/{edge_id}", response_model=TopologyEdgeResponse)
async def get_edge(
    workspace_id: str,
    edge_id: str,
    current_user: User = Depends(get_current_user),
    topology_service: TopologyService = Depends(get_topology_service),
) -> TopologyEdgeResponse:
    try:
        edge = await topology_service.get_edge(
            workspace_id=workspace_id,
            edge_id=edge_id,
            actor_user_id=current_user.id,
        )
        return TopologyEdgeResponse.model_validate(edge)
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except ValueError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.patch("/edges/{edge_id}", response_model=TopologyEdgeResponse)
async def update_edge(
    workspace_id: str,
    edge_id: str,
    body: TopologyEdgeUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    topology_service: TopologyService = Depends(get_topology_service),
) -> TopologyEdgeResponse:
    try:
        edge = await topology_service.update_edge(
            workspace_id=workspace_id,
            edge_id=edge_id,
            actor_user_id=current_user.id,
            source_node_id=body.source_node_id,
            target_node_id=body.target_node_id,
            label=body.label,
            data=body.data,
        )
        await db.commit()
        await publish_workspace_event(
            request.app.state.container.redis(),
            workspace_id=workspace_id,
            event_type=AgentEventType.TOPOLOGY_UPDATED,
            payload={"workspace_id": workspace_id, "operation": "edge_updated", "edge_id": edge.id},
        )
        return TopologyEdgeResponse.model_validate(edge)
    except PermissionError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except ValueError as e:
        await db.rollback()
        if "not found" in str(e).lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.delete("/edges/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_edge(
    workspace_id: str,
    edge_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    topology_service: TopologyService = Depends(get_topology_service),
) -> None:
    try:
        await topology_service.delete_edge(
            workspace_id=workspace_id,
            edge_id=edge_id,
            actor_user_id=current_user.id,
        )
        await db.commit()
        await publish_workspace_event(
            request.app.state.container.redis(),
            workspace_id=workspace_id,
            event_type=AgentEventType.TOPOLOGY_UPDATED,
            payload={"workspace_id": workspace_id, "operation": "edge_deleted", "edge_id": edge_id},
        )
    except PermissionError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except ValueError as e:
        await db.rollback()
        if "not found" in str(e).lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
