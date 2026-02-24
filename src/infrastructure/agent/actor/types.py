"""Actor type definitions for project-level agent runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProjectAgentActorConfig:
    tenant_id: str
    project_id: str
    agent_mode: str = "default"
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
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
    conversation_context: list[dict[str, Any]] = field(default_factory=list)
    attachment_ids: list[str] | None = None
    file_metadata: list[dict[str, Any]] | None = None
    correlation_id: str | None = None
    forced_skill_name: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    max_steps: int | None = None
    # Cached context summary from previous turns (serialized dict)
    context_summary_data: dict[str, Any] | None = None
    # Whether conversation is in Plan Mode (read-only analysis)
    plan_mode: bool = False
    # Context injected by MCP Apps via ui/update-model-context (SEP-1865)
    app_model_context: dict[str, Any] | None = None


@dataclass(frozen=True)
class ProjectChatResult:
    conversation_id: str
    message_id: str
    content: str = ""
    last_event_time_us: int = 0
    last_event_counter: int = 0
    is_error: bool = False
    error_message: str | None = None
    execution_time_ms: float = 0.0
    event_count: int = 0
    hitl_pending: bool = False
    hitl_request_id: str | None = None


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
    created_at: str | None = None
    last_activity_at: str | None = None
    uptime_seconds: float = 0.0
    current_conversation_id: str | None = None
    current_message_id: str | None = None
