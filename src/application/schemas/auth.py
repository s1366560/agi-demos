"""
Authentication models for API Key management.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class APIKey(BaseModel):
    """API Key model."""

    key_id: str = Field(default_factory=lambda: str(uuid4()))
    key: str  # This will be the actual API key (hashed in storage)
    name: str
    user_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None
    is_active: bool = True
    permissions: list[str] = Field(default_factory=list)
    last_used_at: Optional[datetime] = None

    class Config:
        json_schema_extra = {
            "example": {
                "key_id": "key_123abc",
                "key": "vpm_sk_1234567890abcdef",
                "name": "Production API Key",
                "user_id": "user_123",
                "is_active": True,
                "permissions": ["read", "write"],
            }
        }


class User(BaseModel):
    """User model."""

    user_id: str = Field(default_factory=lambda: str(uuid4()))
    email: str
    name: str
    roles: list[str] = Field(default_factory=list)
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    profile: Optional[dict] = Field(default_factory=dict)

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "user_123",
                "email": "user@example.com",
                "name": "John Doe",
                "roles": ["user"],
                "is_active": True,
                "permissions": ["read", "write"],
            }
        }


class APIKeyCreate(BaseModel):
    """Request model for creating an API key."""

    name: str
    permissions: list[str] = Field(default_factory=lambda: ["read", "write"])
    expires_in_days: Optional[int] = None


class APIKeyResponse(BaseModel):
    """Response model for API key creation."""

    key_id: str
    key: str  # Only returned once during creation
    name: str
    created_at: datetime
    expires_at: Optional[datetime] = None
    permissions: list[str]


class UserCreate(BaseModel):
    email: str
    name: str
    password: str
    roles: list[str] = Field(default_factory=lambda: ["user"])


class UserProfile(BaseModel):
    job_title: Optional[str] = None
    department: Optional[str] = None
    bio: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    language: Optional[str] = None
    timezone: Optional[str] = None
    avatar_url: Optional[str] = None


class UserUpdate(BaseModel):
    name: Optional[str] = None
    profile: Optional[UserProfile] = None


class UserResponse(BaseModel):
    user_id: str = Field(alias="id")
    email: str
    name: str
    roles: list[str]
    is_active: bool
    created_at: datetime
    profile: Optional[dict] = Field(default_factory=dict)

    class Config:
        from_attributes = True
        populate_by_name = True


class Token(BaseModel):
    access_token: str
    token_type: str
