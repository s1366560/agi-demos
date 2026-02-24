"""
Type-safe JSON field models for SQLAlchemy models.

These Pydantic models provide runtime validation and serialization
for JSON columns in the database, ensuring data integrity.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# === Project Configuration Models ===


class MemoryRuleType(str, Enum):
    """Types of memory rules."""

    INCLUDE = "include"
    EXCLUDE = "exclude"
    TRANSFORM = "transform"
    FILTER = "filter"


class MemoryRule(BaseModel):
    """A single memory processing rule."""

    rule_type: MemoryRuleType = MemoryRuleType.INCLUDE
    pattern: str | None = None
    field: str | None = None
    action: str | None = None
    priority: int = 0
    enabled: bool = True


class MemoryRulesConfig(BaseModel):
    """Configuration for project memory rules."""

    rules: list[MemoryRule] = Field(default_factory=list)
    default_action: str = "include"
    max_memory_size: int | None = None
    retention_days: int | None = None

    class Config:
        extra = "allow"


class GraphNodeConfig(BaseModel):
    """Configuration for graph node types."""

    label: str
    properties: list[str] = Field(default_factory=list)
    indexed: bool = False


class GraphRelationshipConfig(BaseModel):
    """Configuration for graph relationship types."""

    type: str
    from_node: str
    to_node: str
    properties: list[str] = Field(default_factory=list)


class GraphConfig(BaseModel):
    """Configuration for project knowledge graph."""

    enabled: bool = True
    node_types: list[GraphNodeConfig] = Field(default_factory=list)
    relationship_types: list[GraphRelationshipConfig] = Field(default_factory=list)
    embedding_model: str | None = None
    similarity_threshold: float = 0.7

    class Config:
        extra = "allow"


class SandboxConfig(BaseModel):
    """Configuration for project sandbox environment."""

    provider: str = "docker"
    image: str | None = None
    memory_limit: str = "2g"
    cpu_limit: float = 1.0
    timeout_seconds: int = 300
    mount_paths: list[str] = Field(default_factory=list)
    environment: dict[str, str] = Field(default_factory=dict)

    class Config:
        extra = "allow"


# === Agent Configuration Models ===


class AgentModelConfig(BaseModel):
    """LLM model configuration for agent."""

    provider: str = "gemini"
    model: str = "gemini-2.0-flash"
    temperature: float = 0.7
    max_tokens: int | None = None
    top_p: float | None = None


class AgentConfig(BaseModel):
    """Agent configuration for conversations."""

    model_config_data: AgentModelConfig | None = Field(default=None, alias="model_config")
    system_prompt: str | None = None
    enabled_tools: list[str] = Field(default_factory=list)
    disabled_tools: list[str] = Field(default_factory=list)
    max_iterations: int = 10
    doom_loop_threshold: int = 3
    auto_approve_tools: bool = False

    class Config:
        extra = "allow"
        populate_by_name = True


# === Tool Configuration Models ===


class ToolInputSchema(BaseModel):
    """Schema for tool input parameters."""

    type: str = "object"
    properties: dict[str, Any] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)

    class Config:
        extra = "allow"


class ToolCall(BaseModel):
    """A tool call in a message."""

    tool_name: str
    tool_input: dict[str, Any] = Field(default_factory=dict)
    call_id: str | None = None


class ToolResult(BaseModel):
    """Result of a tool execution."""

    call_id: str | None = None
    tool_name: str
    success: bool = True
    result: Any = None
    error: str | None = None
    execution_time_ms: int | None = None


# === Plan Step Models ===


class PlanStepStatus(str, Enum):
    """Status of a plan step."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PlanStep(BaseModel):
    """A step in a work plan."""

    index: int
    description: str
    status: PlanStepStatus = PlanStepStatus.PENDING
    tool_name: str | None = None
    tool_input: dict[str, Any] = Field(default_factory=dict)
    result: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    class Config:
        extra = "allow"


# === Workflow Pattern Models ===


class TriggerPattern(BaseModel):
    """Pattern that triggers a workflow."""

    pattern_type: str = "keyword"  # keyword, regex, semantic
    value: str
    confidence_threshold: float = 0.8


class WorkflowStep(BaseModel):
    """A step in a workflow pattern."""

    order: int
    tool_name: str
    description: str | None = None
    input_mapping: dict[str, str] = Field(default_factory=dict)
    output_key: str | None = None
    condition: str | None = None

    class Config:
        extra = "allow"


# === Event Data Models ===


class AgentEventData(BaseModel):
    """Data for agent execution events."""

    event_type: str
    message: str | None = None
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    tool_result: Any | None = None
    error: str | None = None
    tokens_used: int | None = None
    cost: float | None = None
    duration_ms: int | None = None

    class Config:
        extra = "allow"


# === MCP Server Models ===


class MCPTransportConfig(BaseModel):
    """Transport configuration for MCP server."""

    type: str = "stdio"  # stdio, sse, websocket
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)

    class Config:
        extra = "allow"


class MCPToolInfo(BaseModel):
    """Information about a discovered MCP tool."""

    name: str
    description: str | None = None
    input_schema: dict[str, Any] | None = None


# === Generic Metadata Model ===


class GenericMetadata(BaseModel):
    """Generic metadata container for flexible JSON fields."""

    class Config:
        extra = "allow"

    def __init__(self, **data) -> None:
        super().__init__(**data)


# === Type Aliases for Convenience ===

JsonDict = dict[str, Any]
JsonList = list[Any]
ToolCallList = list[ToolCall]
ToolResultList = list[ToolResult]
PlanStepList = list[PlanStep]
WorkflowStepList = list[WorkflowStep]
