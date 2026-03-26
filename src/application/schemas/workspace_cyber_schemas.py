from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.domain.model.workspace.cyber_gene import CyberGeneCategory
from src.domain.model.workspace.cyber_objective import CyberObjectiveType


class CyberObjectiveCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    obj_type: CyberObjectiveType = CyberObjectiveType.OBJECTIVE
    parent_id: str | None = None
    progress: float = Field(default=0.0, ge=0.0, le=1.0)


class CyberObjectiveUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    obj_type: CyberObjectiveType | None = None
    parent_id: str | None = None
    progress: float | None = Field(None, ge=0.0, le=1.0)


class CyberObjectiveResponse(BaseModel):
    id: str
    workspace_id: str
    title: str
    description: str | None
    obj_type: CyberObjectiveType
    parent_id: str | None
    progress: float
    created_by: str
    created_at: datetime
    updated_at: datetime | None


class CyberObjectiveListResponse(BaseModel):
    items: list[CyberObjectiveResponse]
    total: int


class CyberGeneCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    category: CyberGeneCategory = CyberGeneCategory.SKILL
    description: str | None = None
    config_json: str | None = None
    version: str = "1.0.0"
    is_active: bool = True


class CyberGeneUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    category: CyberGeneCategory | None = None
    description: str | None = None
    config_json: str | None = None
    version: str | None = None
    is_active: bool | None = None


class CyberGeneResponse(BaseModel):
    id: str
    workspace_id: str
    name: str
    category: CyberGeneCategory
    description: str | None
    config_json: str | None
    version: str
    is_active: bool
    created_by: str
    created_at: datetime
    updated_at: datetime | None


class CyberGeneListResponse(BaseModel):
    items: list[CyberGeneResponse]
    total: int
