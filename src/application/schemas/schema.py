from datetime import datetime
from typing import Dict, Optional

from pydantic import BaseModel, Field

from src.domain.model.enums import DataStatus


class EntityTypeBase(BaseModel):
    name: str
    description: Optional[str] = None
    schema_def: Dict = Field(default_factory=dict, alias="schema")
    status: DataStatus = DataStatus.ENABLED
    source: str = "user"


class EntityTypeCreate(EntityTypeBase):
    pass


class EntityTypeUpdate(BaseModel):
    description: Optional[str] = None
    schema_def: Optional[Dict] = Field(None, alias="schema")


class EntityTypeResponse(EntityTypeBase):
    id: str
    project_id: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
        populate_by_name = True


class EdgeTypeBase(BaseModel):
    name: str
    description: Optional[str] = None
    schema_def: Dict = Field(default_factory=dict, alias="schema")
    status: DataStatus = DataStatus.ENABLED
    source: str = "user"


class EdgeTypeCreate(EdgeTypeBase):
    pass


class EdgeTypeUpdate(BaseModel):
    description: Optional[str] = None
    schema_def: Optional[Dict] = Field(None, alias="schema")


class EdgeTypeResponse(EdgeTypeBase):
    id: str
    project_id: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
        populate_by_name = True


class EdgeTypeMapBase(BaseModel):
    source_type: str
    target_type: str
    edge_type: str
    status: DataStatus = DataStatus.ENABLED
    source: str = "user"


class EdgeTypeMapCreate(EdgeTypeMapBase):
    pass


class EdgeTypeMapResponse(EdgeTypeMapBase):
    id: str
    project_id: str
    created_at: datetime

    class Config:
        from_attributes = True
