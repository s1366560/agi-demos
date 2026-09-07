"""Workspace Core-owned topology HTTP contract declarations."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field

from src.application.services.workspace_layout_limits import (
    MAX_WORKSPACE_HEX_COORDINATE,
    MAX_WORKSPACE_POSITION,
)
from src.domain.model.workspace.topology_node import TopologyNodeType
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.workspace_authority import (
    workspace_core_unavailable_error,
)
from src.infrastructure.adapters.secondary.persistence.models import User

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/topology", tags=["topology"])


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


@router.post("/nodes", response_model=TopologyNodeResponse, status_code=status.HTTP_201_CREATED)
async def create_node(
    workspace_id: str,
    body: TopologyNodeCreate,
    current_user: User = Depends(get_current_user),
) -> TopologyNodeResponse:
    raise workspace_core_unavailable_error()


@router.get("/nodes", response_model=list[TopologyNodeResponse])
async def list_nodes(
    workspace_id: str,
    limit: int = 1000,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
) -> list[TopologyNodeResponse]:
    raise workspace_core_unavailable_error()


@router.get("/nodes/{node_id}", response_model=TopologyNodeResponse)
async def get_node(
    workspace_id: str,
    node_id: str,
    current_user: User = Depends(get_current_user),
) -> TopologyNodeResponse:
    raise workspace_core_unavailable_error()


@router.patch("/nodes/{node_id}", response_model=TopologyNodeResponse)
async def update_node(
    workspace_id: str,
    node_id: str,
    body: TopologyNodeUpdate,
    current_user: User = Depends(get_current_user),
) -> TopologyNodeResponse:
    raise workspace_core_unavailable_error()


@router.delete("/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_node(
    workspace_id: str,
    node_id: str,
    current_user: User = Depends(get_current_user),
) -> None:
    raise workspace_core_unavailable_error()


@router.post("/edges", response_model=TopologyEdgeResponse, status_code=status.HTTP_201_CREATED)
async def create_edge(
    workspace_id: str,
    body: TopologyEdgeCreate,
    current_user: User = Depends(get_current_user),
) -> TopologyEdgeResponse:
    raise workspace_core_unavailable_error()


@router.get("/edges", response_model=list[TopologyEdgeResponse])
async def list_edges(
    workspace_id: str,
    limit: int = 2000,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
) -> list[TopologyEdgeResponse]:
    raise workspace_core_unavailable_error()


@router.get("/edges/{edge_id}", response_model=TopologyEdgeResponse)
async def get_edge(
    workspace_id: str,
    edge_id: str,
    current_user: User = Depends(get_current_user),
) -> TopologyEdgeResponse:
    raise workspace_core_unavailable_error()


@router.patch("/edges/{edge_id}", response_model=TopologyEdgeResponse)
async def update_edge(
    workspace_id: str,
    edge_id: str,
    body: TopologyEdgeUpdate,
    current_user: User = Depends(get_current_user),
) -> TopologyEdgeResponse:
    raise workspace_core_unavailable_error()


@router.delete("/edges/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_edge(
    workspace_id: str,
    edge_id: str,
    current_user: User = Depends(get_current_user),
) -> None:
    raise workspace_core_unavailable_error()
