"""
Type-safe JSON field models for SQLAlchemy models.

These Pydantic models provide runtime validation and serialization
for JSON columns in the database, ensuring data integrity.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

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
    pattern: Optional[str] = None
    field: Optional[str] = None
    action: Optional[str] = None
    priority: int = 0
    enabled: bool = True


class MemoryRulesConfig(BaseModel):
    """Configuration for project memory rules."""

    rules: List[MemoryRule] = Field(default_factory=list)
    default_action: str = "include"
    max_memory_size: Optional[int] = None
    retention_days: Optional[int] = None

    class Config:
        extra = "allow"


class GraphNodeConfig(BaseModel):
    """Configuration for graph node types."""

    label: str
    properties: List[str] = Field(default_factory=list)
    indexed: bool = False


class GraphRelationshipConfig(BaseModel):
    """Configuration for graph relationship types."""

    type: str
    from_node: str
    to_node: str
    properties: List[str] = Field(default_factory=list)


class GraphConfig(BaseModel):
    """Configuration for project knowledge graph."""

    enabled: bool = True
    node_types: List[GraphNodeConfig] = Field(default_factory=list)
    relationship_types: List[GraphRelationshipConfig] = Field(default_factory=list)
    embedding_model: Optional[str] = None
    similarity_threshold: float = 0.7

    class Config:
        extra = "allow"


class SandboxConfig(BaseModel):
    """Configuration for project sandbox environment."""

    provider: str = "docker"
    image: Optional[str] = None
    memory_limit: str = "2g"
    cpu_limit: float = 1.0
    timeout_seconds: int = 300
    mount_paths: List[str] = Field(default_factory=list)
    environment: Dict[str, str] = Field(default_factory=dict)

    class Config:
        extra = "allow"


# === Agent Configuration Models ===


class AgentModelConfig(BaseModel):
    """LLM model configuration for agent."""

    provider: str = "gemini"
    model: str = "gemini-2.0-flash"
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None


class AgentConfig(BaseModel):
    """Agent configuration for conversations."""

    model_config_data: Optional[AgentModelConfig] = Field(default=None, alias="model_config")
    system_prompt: Optional[str] = None
    enabled_tools: List[str] = Field(default_factory=list)
    disabled_tools: List[str] = Field(default_factory=list)
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
    properties: Dict[str, Any] = Field(default_factory=dict)
    required: List[str] = Field(default_factory=list)

    class Config:
        extra = "allow"


class ToolCall(BaseModel):
    """A tool call in a message."""

    tool_name: str
    tool_input: Dict[str, Any] = Field(default_factory=dict)
    call_id: Optional[str] = None


class ToolResult(BaseModel):
    """Result of a tool execution."""

    call_id: Optional[str] = None
    tool_name: str
    success: bool = True
    result: Any = None
    error: Optional[str] = None
    execution_time_ms: Optional[int] = None


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
    tool_name: Optional[str] = None
    tool_input: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

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
    description: Optional[str] = None
    input_mapping: Dict[str, str] = Field(default_factory=dict)
    output_key: Optional[str] = None
    condition: Optional[str] = None

    class Config:
        extra = "allow"


# === Event Data Models ===


class AgentEventData(BaseModel):
    """Data for agent execution events."""

    event_type: str
    message: Optional[str] = None
    tool_name: Optional[str] = None
    tool_input: Optional[Dict[str, Any]] = None
    tool_result: Optional[Any] = None
    error: Optional[str] = None
    tokens_used: Optional[int] = None
    cost: Optional[float] = None
    duration_ms: Optional[int] = None

    class Config:
        extra = "allow"


# === MCP Server Models ===


class MCPTransportConfig(BaseModel):
    """Transport configuration for MCP server."""

    type: str = "stdio"  # stdio, sse, websocket
    command: Optional[str] = None
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    url: Optional[str] = None
    headers: Dict[str, str] = Field(default_factory=dict)

    class Config:
        extra = "allow"


class MCPToolInfo(BaseModel):
    """Information about a discovered MCP tool."""

    name: str
    description: Optional[str] = None
    input_schema: Optional[Dict[str, Any]] = None


# === Generic Metadata Model ===


class GenericMetadata(BaseModel):
    """Generic metadata container for flexible JSON fields."""

    class Config:
        extra = "allow"

    def __init__(self, **data):
        super().__init__(**data)


# === Type Aliases for Convenience ===

JsonDict = Dict[str, Any]
JsonList = List[Any]
ToolCallList = List[ToolCall]
ToolResultList = List[ToolResult]
PlanStepList = List[PlanStep]
WorkflowStepList = List[WorkflowStep]
