"""
Session API schemas.

Pydantic models for session-related API requests and responses.
"""

from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, ConfigDict


class SessionCreate(BaseModel):
    """Request model for creating a session."""

    agent_id: str = Field(..., description="Which agent handles this session")
    kind: Optional[str] = Field(
        default="main",
        description="Session type: main, sub_agent, background, one_shot",
    )
    model: Optional[str] = Field(None, description="Optional model override")
    metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Optional metadata (channel, user, etc.)",
    )


class SessionResponse(BaseModel):
    """Response model for a session."""

    id: str
    session_key: str
    agent_id: str
    kind: str
    model: Optional[str]
    status: str
    metadata: Dict[str, Any]
    created_at: datetime
    last_active_at: datetime
    message_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class SessionListResponse(BaseModel):
    """Response model for listing sessions."""

    sessions: List[SessionResponse]
    total: int
    limit: int
    offset: int


class SessionMessageCreate(BaseModel):
    """Request model for adding a message to a session."""

    role: str = Field(..., description="Message role: user, assistant, system, tool")
    content: str = Field(..., description="Message content")
    metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Optional metadata",
    )


class SessionMessageResponse(BaseModel):
    """Response model for a session message."""

    id: str
    session_id: str
    role: str
    content: str
    metadata: Dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SessionHistoryResponse(BaseModel):
    """Response model for session message history."""

    session_id: str
    session_key: str
    messages: List[SessionMessageResponse]
    total: int
    limit: int


class SendMessageRequest(BaseModel):
    """Request model for sending a message to another session."""

    session_id: Optional[str] = Field(None, description="Target session ID")
    session_key: Optional[str] = Field(None, description="Target session key")
    message: str = Field(..., description="Message to send")
    role: Optional[str] = Field(default="assistant", description="Message role")
    metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Optional metadata",
    )


class SessionStatsResponse(BaseModel):
    """Response model for session statistics."""

    total: int
    by_status: Dict[str, int]
    by_kind: Dict[str, int]
