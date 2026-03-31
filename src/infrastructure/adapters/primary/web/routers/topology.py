"""Topology API routes for workspace nodes and edges."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.topology_service import TopologyService
from src.application.services.workspace_layout_limits import (
    MAX_WORKSPACE_HEX_COORDINATE,
    MAX_WORKSPACE_POSITION,
)
from src.domain.events.types import AgentEventType
from src.domain.model.workspace.topology_node import TopologyNodeType
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.workspace_events import (
    publish_workspace_event_with_retry,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/topology", tags=["topology"])
logger = logging.getLogger(__name__)


def get_topology_service(request: Request, db: AsyncSession = Depends(get_db)) -> TopologyService:
    """Resolve topology service from request-scoped DI container."""
    container = request.app.state.container.with_db(db)
    return container.topology_service()


class TopologyNodeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_type: TopologyNodeType
    ref_id: str | None = None
    title: str = ""
    position_x: float = Field(
        default=0.0,
        ge=-MAX_WORKSPACE_POSITION,
        le=MAX_WORKSPACE_POSITION,
    )
    position_y: float = Field(
        default=0.0,
        ge=-MAX_WORKSPACE_POSITION,
        le=MAX_WORKSPACE_POSITION,
    )
    hex_q: int | None = Field(
        default=None,
        ge=-MAX_WORKSPACE_HEX_COORDINATE,
        le=MAX_WORKSPACE_HEX_COORDINATE,
    )
    hex_r: int | None = Field(
        default=None,
        ge=-MAX_WORKSPACE_HEX_COORDINATE,
        le=MAX_WORKSPACE_HEX_COORDINATE,
    )
    status: str = "active"
    tags: list[str] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)


class TopologyNodeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_type: TopologyNodeType | None = None
    ref_id: str | None = None
    title: str | None = None
    position_x: float | None = Field(
        default=None,
        ge=-MAX_WORKSPACE_POSITION,
        le=MAX_WORKSPACE_POSITION,
    )
    position_y: float | None = Field(
        default=None,
        ge=-MAX_WORKSPACE_POSITION,
        le=MAX_WORKSPACE_POSITION,
    )
    hex_q: int | None = Field(
        default=None,
        ge=-MAX_WORKSPACE_HEX_COORDINATE,
        le=MAX_WORKSPACE_HEX_COORDINATE,
    )
    hex_r: int | None = Field(
        default=None,
        ge=-MAX_WORKSPACE_HEX_COORDINATE,
        le=MAX_WORKSPACE_HEX_COORDINATE,
    )
    status: str | None = None
    tags: list[str] | None = None
    data: dict[str, Any] | None = None


class TopologyNodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    node_type: TopologyNodeType
    ref_id: str | None = None
    title: str
    position_x: float
    position_y: float
    hex_q: int | None = None
    hex_r: int | None = None
    status: str
    tags: list[str] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime | None = None


class TopologyEdgeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_node_id: str
    target_node_id: str
    label: str | None = None
    direction: str | None = None
    auto_created: bool = False
    data: dict[str, Any] = Field(default_factory=dict)


class TopologyEdgeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_node_id: str | None = None
    target_node_id: str | None = None
    label: str | None = None
    direction: str | None = None
    auto_created: bool | None = None
    data: dict[str, Any] | None = None


class TopologyEdgeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    source_node_id: str
    target_node_id: str
    label: str | None = None
    source_hex_q: int | None = None
    source_hex_r: int | None = None
    target_hex_q: int | None = None
    target_hex_r: int | None = None
    direction: str | None = None
    auto_created: bool = False
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime | None = None


def _serialize_node(node: TopologyNodeResponse | object) -> dict[str, Any]:
    return TopologyNodeResponse.model_validate(node).model_dump(mode="json")


def _serialize_edge(edge: TopologyEdgeResponse | object) -> dict[str, Any]:
    return TopologyEdgeResponse.model_validate(edge).model_dump(mode="json")


async def _publish_topology_event_after_commit(
    request: Request,
    *,
    workspace_id: str,
    payload: dict[str, Any],
) -> None:
    try:
        await publish_workspace_event_with_retry(
            request.app.state.container.redis(),
            workspace_id=workspace_id,
            event_type=AgentEventType.TOPOLOGY_UPDATED,
            payload=payload,
        )
    except Exception:
        logger.exception(
            "Failed to publish topology event after commit",
            extra={"workspace_id": workspace_id, "operation": payload.get("operation")},
        )


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
            hex_q=body.hex_q,
            hex_r=body.hex_r,
            status=body.status,
            tags=body.tags,
            data=body.data,
        )
        payload = {
            "workspace_id": workspace_id,
            "operation": "node_created",
            "node_id": node.id,
            "node": _serialize_node(node),
        }
        await db.commit()
        await _publish_topology_event_after_commit(
            request,
            workspace_id=workspace_id,
            payload=payload,
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
            hex_q=body.hex_q,
            hex_r=body.hex_r,
            status=body.status,
            tags=body.tags,
            data=body.data,
        )
        updated_edges = await topology_service.list_edges_for_node(
            workspace_id=workspace_id,
            node_id=node.id,
            actor_user_id=current_user.id,
        )
        payload = {
            "workspace_id": workspace_id,
            "operation": "node_updated",
            "node_id": node.id,
            "node": _serialize_node(node),
            "updated_edges": [_serialize_edge(edge) for edge in updated_edges],
        }
        await db.commit()
        await _publish_topology_event_after_commit(
            request,
            workspace_id=workspace_id,
            payload=payload,
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
        payload = {
            "workspace_id": workspace_id,
            "operation": "node_deleted",
            "node_id": node_id,
        }
        await db.commit()
        await _publish_topology_event_after_commit(
            request,
            workspace_id=workspace_id,
            payload=payload,
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
            direction=body.direction,
            auto_created=body.auto_created,
            data=body.data,
        )
        payload = {
            "workspace_id": workspace_id,
            "operation": "edge_created",
            "edge_id": edge.id,
            "edge": _serialize_edge(edge),
        }
        await db.commit()
        await _publish_topology_event_after_commit(
            request,
            workspace_id=workspace_id,
            payload=payload,
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
            direction=body.direction,
            auto_created=body.auto_created,
            data=body.data,
        )
        payload = {
            "workspace_id": workspace_id,
            "operation": "edge_updated",
            "edge_id": edge.id,
            "edge": _serialize_edge(edge),
        }
        await db.commit()
        await _publish_topology_event_after_commit(
            request,
            workspace_id=workspace_id,
            payload=payload,
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
        payload = {
            "workspace_id": workspace_id,
            "operation": "edge_deleted",
            "edge_id": edge_id,
        }
        await db.commit()
        await _publish_topology_event_after_commit(
            request,
            workspace_id=workspace_id,
            payload=payload,
        )
    except PermissionError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except ValueError as e:
        await db.rollback()
        if "not found" in str(e).lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
