"""
Pydantic models for MemStack SDK.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class EpisodeCreate(BaseModel):
    """Request model for creating an episode."""

    name: str = Field(..., description="Episode name")
    content: str = Field(..., description="Episode content (text or JSON)")
    source_type: str = Field(default="text", description="Type of source: 'text' or 'json'")
    source_description: Optional[str] = Field(None, description="Description of the source")
    group_id: Optional[str] = Field(None, description="Group ID for organizing episodes")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "User Conversation",
                "content": "User said: I love hiking in the mountains",
                "source_type": "text",
                "source_description": "Chat message",
                "group_id": "user_123",
            }
        }


class Episode(BaseModel):
    """Episode model."""

    id: str
    name: str
    content: str
    source_type: str
    source_description: Optional[str] = None
    group_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: datetime
    status: str = "processing"


class EpisodeResponse(BaseModel):
    """Response model for episode creation."""

    id: str
    status: str
    message: str
    created_at: datetime


class MemoryQuery(BaseModel):
    """Request model for memory search."""

    query: str = Field(..., description="Search query text")
    limit: int = Field(default=10, ge=1, le=100, description="Maximum number of results")
    tenant_id: Optional[str] = Field(None, description="Tenant ID for multi-tenancy")
    filters: Optional[Dict[str, Any]] = Field(None, description="Additional filters")

    class Config:
        json_schema_extra = {
            "example": {
                "query": "What are the user's preferences for outdoor activities?",
                "limit": 10,
            }
        }


class MemoryResult(BaseModel):
    """Individual memory search result."""

    id: str
    content: str
    score: float
    type: str  # 'episode', 'entity', 'relation'
    metadata: Optional[Dict[str, Any]] = None


class MemoryResponse(BaseModel):
    """Response model for memory search."""

    results: List[MemoryResult]
    total: int
    query: str


class APIKey(BaseModel):
    """API Key model."""

    key_id: str
    key: str
    name: str
    created_at: datetime
    expires_at: Optional[datetime] = None
    permissions: List[str]


class APIKeyCreate(BaseModel):
    """Request model for creating an API key."""

    name: str
    permissions: List[str]
    expires_in_days: Optional[int] = None


class Memo(BaseModel):
    """Memo model."""

    id: str
    content: str
    visibility: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    tags: List[str]
    user_id: str


class MemoCreate(BaseModel):
    """Request model for creating a memo."""

    content: str
    visibility: str = "PRIVATE"
    tags: List[str] = Field(default_factory=list)


class MemoUpdate(BaseModel):
    """Request model for updating a memo."""

    content: Optional[str] = None
    visibility: Optional[str] = None
    tags: Optional[List[str]] = None
