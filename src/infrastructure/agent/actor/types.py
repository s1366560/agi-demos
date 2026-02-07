"""Actor type definitions for project-level agent runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ProjectAgentActorConfig:
    tenant_id: str
    project_id: str
    agent_mode: str = "default"
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 4096
    max_steps: int = 20
    persistent: bool = True
    idle_timeout_seconds: int = 3600
    max_concurrent_chats: int = 10
    mcp_tools_ttl_seconds: int = 300
    enable_skills: bool = True
    enable_subagents: bool = True


@dataclass(frozen=True)
class ProjectChatRequest:
    conversation_id: str
    message_id: str
    user_message: str
    user_id: str
    conversation_context: List[Dict[str, Any]] = field(default_factory=list)
    attachment_ids: Optional[List[str]] = None
    correlation_id: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    max_steps: Optional[int] = None


@dataclass(frozen=True)
class ProjectChatResult:
    conversation_id: str
    message_id: str
    content: str = ""
    sequence_number: int = 0
    is_error: bool = False
    error_message: Optional[str] = None
    execution_time_ms: float = 0.0
    event_count: int = 0
    hitl_pending: bool = False
    hitl_request_id: Optional[str] = None


@dataclass(frozen=True)
class MCPServerActorConfig:
    """Configuration for MCPServerActor. Replaces MCPServerConfig (Temporal)."""

    server_name: str
    tenant_id: str
    transport_type: str = "local"  # "local"/"stdio", "http", "sse", "websocket"

    # Local transport
    command: Optional[List[str]] = None
    environment: Optional[Dict[str, str]] = None

    # Remote transport
    url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None

    # WebSocket specific
    heartbeat_interval: int = 30
    reconnect_attempts: int = 3

    # Common
    timeout: int = 30000  # milliseconds
    enabled: bool = True


@dataclass(frozen=True)
class ProjectAgentStatus:
    tenant_id: str
    project_id: str
    agent_mode: str
    actor_id: str
    is_initialized: bool = False
    is_active: bool = True
    is_executing: bool = False
    total_chats: int = 0
    active_chats: int = 0
    failed_chats: int = 0
    tool_count: int = 0
    skill_count: int = 0
    subagent_count: int = 0
    created_at: Optional[str] = None
    last_activity_at: Optional[str] = None
    uptime_seconds: float = 0.0
    current_conversation_id: Optional[str] = None
    current_message_id: Optional[str] = None
