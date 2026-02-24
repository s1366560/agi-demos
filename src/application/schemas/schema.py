from datetime import datetime

from pydantic import BaseModel, Field

from src.domain.model.enums import DataStatus


class EntityTypeBase(BaseModel):
    name: str
    description: str | None = None
    schema_def: dict = Field(default_factory=dict, alias="schema")
    status: DataStatus = DataStatus.ENABLED
    source: str = "user"


class EntityTypeCreate(EntityTypeBase):
    pass


class EntityTypeUpdate(BaseModel):
    description: str | None = None
    schema_def: dict | None = Field(None, alias="schema")


class EntityTypeResponse(EntityTypeBase):
    id: str
    project_id: str
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True
        populate_by_name = True


class EdgeTypeBase(BaseModel):
    name: str
    description: str | None = None
    schema_def: dict = Field(default_factory=dict, alias="schema")
    status: DataStatus = DataStatus.ENABLED
    source: str = "user"


class EdgeTypeCreate(EdgeTypeBase):
    pass


class EdgeTypeUpdate(BaseModel):
    description: str | None = None
    schema_def: dict | None = Field(None, alias="schema")


class EdgeTypeResponse(EdgeTypeBase):
    id: str
    project_id: str
    created_at: datetime
    updated_at: datetime | None = None

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
