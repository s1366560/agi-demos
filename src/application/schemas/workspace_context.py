"""Public API schemas for authoritative desktop workspace context."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WorkspaceContextSnapshotResponse(BaseModel):
    tenant_id: str
    project_id: str
    revision: int
    updated_at: datetime


class WorkspaceContextResponse(BaseModel):
    context: WorkspaceContextSnapshotResponse
    membership_role: str


class WorkspaceContextSwitchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    project_id: str
    expected_revision: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1, max_length=255)

    @field_validator("tenant_id", "project_id", "idempotency_key")
    @classmethod
    def reject_blank_values(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value


class WorkspaceContextSwitchResponse(BaseModel):
    context: WorkspaceContextSnapshotResponse
    changed: bool
