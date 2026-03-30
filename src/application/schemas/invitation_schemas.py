from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class CreateInvitationRequest(BaseModel):
    email: EmailStr
    role: str = "member"
    message: str | None = None


class BulkCreateInvitationRequest(BaseModel):
    invitations: list[CreateInvitationRequest] = Field(min_length=1, max_length=50)


class InvitationResponse(BaseModel):
    id: str
    tenant_id: str
    email: str
    role: str
    status: str
    invited_by: str
    expires_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class InvitationListResponse(BaseModel):
    items: list[InvitationResponse]
    total: int
    limit: int
    offset: int


class InvitationVerifyResponse(BaseModel):
    valid: bool
    email: str | None = None
    tenant_id: str | None = None
    role: str | None = None
    expires_at: datetime | None = None


class AcceptInvitationRequest(BaseModel):
    display_name: str | None = None
