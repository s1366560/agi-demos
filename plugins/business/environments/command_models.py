"""Environments command models. This module does not open the relational store."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.application.schemas.acp_runner_schemas import ACPRunnerPoolCreate, ACPRunnerTokenRequest

type Identifier = Annotated[str, Field(min_length=1, max_length=128)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _Key(_Input):
    id: str = Field(min_length=1, max_length=128)


class _Settings(_Input):
    name: str = Field(min_length=1, max_length=255)
    compute_provider: str | None = Field(None, max_length=50)
    proxy_endpoint: str | None = Field(None, max_length=2048)
    provider_config: dict[str, Any] | None = None


class ClusterCreateCommand(_Input):
    action: Literal["create"]
    data: _Settings


class ClusterEditCommand(_Key):
    action: Literal["edit"]


class ClusterUpdateCommand(_Key):
    action: Literal["update"]
    data: _Settings


class _Cluster(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Identifier


class _CreatePool(_Cluster):
    data: ACPRunnerPoolCreate


class _IssueToken(_Cluster):
    pool_key: Annotated[str, Field(min_length=1, max_length=120)]
    data: ACPRunnerTokenRequest


class DeployRead(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    view: Literal["list", "detail", "latest"]
    id: Identifier
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


class DeployChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["create", "success", "failed", "cancel"]
    id: Identifier
    message: str = Field("", max_length=2000)


class TemplateRead(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    view: Literal["list", "detail", "items", "names"]
    id: Identifier | None = None
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)
    is_published: bool | None = None


class TemplateChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["create", "publish", "clone", "delete"]
    id: Identifier | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class InventoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["instances", "clusters"]
    id: Identifier | None = None
    health: bool = False
    page_size: int = Field(20, ge=1, le=100)
    page: int = Field(1, ge=1, le=1000000)
