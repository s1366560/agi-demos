"""Project data models."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MemoryRulesConfig(BaseModel):
    """Memory rules configuration."""

    max_episodes: int = Field(
        default=1000, ge=100, le=10000, description="Maximum number of episodes"
    )
    retention_days: int = Field(default=30, ge=1, le=365, description="Retention days")
    auto_refresh: bool = Field(default=True, description="Enable auto refresh")
    refresh_interval: int = Field(default=24, ge=1, le=168, description="Refresh interval in hours")


class GraphConfig(BaseModel):
    """Graph visualization configuration."""

    layout_algorithm: str = Field(default="force-directed", description="Layout algorithm")
    node_size: int = Field(default=20, ge=10, le=100, description="Default node size")
    edge_width: int = Field(default=2, ge=1, le=10, description="Default edge width")
    colors: dict = Field(default_factory=dict, description="Color scheme")
    animations: bool = Field(default=True, description="Enable animations")
    max_nodes: int = Field(default=1000, ge=100, le=50000, description="Maximum nodes to display")
    max_edges: int = Field(default=10000, ge=100, le=100000, description="Maximum edges to display")
    similarity_threshold: float = Field(
        default=0.7, ge=0.1, le=1.0, description="Similarity threshold"
    )
    community_detection: bool = Field(default=True, description="Enable community detection")


class LocalSandboxConfigSchema(BaseModel):
    """Configuration for local sandbox connection."""

    workspace_path: str = Field(
        default="/workspace",
        description="Path to workspace directory on user's local machine",
    )
    tunnel_url: str | None = Field(
        default=None,
        description="WebSocket tunnel URL for NAT traversal (e.g., wss://xxx.ngrok.io)",
    )
    host: str = Field(default="localhost", description="Local host address")
    port: int = Field(default=8765, ge=1024, le=65535, description="Local port number")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "workspace_path": "/home/user/projects/my-project",
                "tunnel_url": "wss://abc123.ngrok.io",
                "host": "localhost",
                "port": 8765,
            }
        }
    )


class SandboxConfigSchema(BaseModel):
    """Sandbox configuration for project."""

    sandbox_type: Literal["cloud", "local"] = Field(
        default="cloud",
        description="Type of sandbox: 'cloud' for server-managed Docker, 'local' for user's machine",
    )
    local_config: LocalSandboxConfigSchema | None = Field(
        default=None,
        description="Configuration for local sandbox (required when sandbox_type is 'local')",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "sandbox_type": "local",
                "local_config": {
                    "workspace_path": "/home/user/workspace",
                    "tunnel_url": "wss://abc123.ngrok.io",
                },
            }
        }
    )


class ProjectCreate(BaseModel):
    """Request model for creating a project."""

    name: str = Field(..., description="Project name", min_length=1, max_length=255)
    description: str | None = Field(
        default=None, description="Project description", max_length=1000
    )
    tenant_id: str = Field(..., description="Tenant ID")
    memory_rules: MemoryRulesConfig = Field(
        default_factory=MemoryRulesConfig, description="Memory rules"
    )
    graph_config: GraphConfig = Field(
        default_factory=GraphConfig, description="Graph configuration"
    )
    sandbox_config: SandboxConfigSchema = Field(
        default_factory=SandboxConfigSchema, description="Sandbox configuration"
    )
    is_public: bool = Field(default=False, description="Whether the project is public")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "AI Research Project",
                "description": "Knowledge management for AI research",
                "tenant_id": "tenant_123",
                "memory_rules": {
                    "max_episodes": 1000,
                    "retention_days": 30,
                    "auto_refresh": True,
                    "refresh_interval": 24,
                },
                "graph_config": {
                    "max_nodes": 5000,
                    "max_edges": 10000,
                    "similarity_threshold": 0.7,
                    "community_detection": True,
                },
                "sandbox_config": {
                    "sandbox_type": "cloud",
                },
                "is_public": False,
            }
        }
    )


class ProjectUpdate(BaseModel):
    """Request model for updating a project."""

    name: str | None = Field(
        default=None, description="Project name", min_length=1, max_length=255
    )
    description: str | None = Field(
        default=None, description="Project description", max_length=1000
    )
    memory_rules: MemoryRulesConfig | None = Field(default=None, description="Memory rules")
    graph_config: GraphConfig | None = Field(default=None, description="Graph configuration")
    sandbox_config: SandboxConfigSchema | None = Field(
        default=None, description="Sandbox configuration"
    )
    is_public: bool | None = Field(default=None, description="Whether the project is public")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Updated AI Research Project",
                "description": "Updated knowledge management system",
                "memory_rules": {
                    "max_episodes": 2000,
                    "retention_days": 60,
                    "auto_refresh": True,
                    "refresh_interval": 12,
                },
                "graph_config": {
                    "max_nodes": 5000,
                    "max_edges": 10000,
                    "similarity_threshold": 0.8,
                    "community_detection": True,
                },
                "is_public": True,
            }
        }
    )


class ProjectMemberCreate(BaseModel):
    """Request model for adding a project member."""

    user_id: str = Field(..., description="User ID to add")
    role: str = Field(default="member", description="Member role (admin, member, viewer)")


class ProjectMemberUpdate(BaseModel):
    """Request model for updating a project member."""

    role: str = Field(..., description="New role (admin, member, viewer)")


class SystemStatus(BaseModel):
    """System status information."""

    status: str = Field(default="operational", description="System status")
    indexing_active: bool = Field(default=True, description="Whether indexing is active")
    indexing_progress: int = Field(default=0, description="Indexing progress percentage")


class ProjectStats(BaseModel):
    """Project statistics."""

    memory_count: int = Field(default=0, description="Number of memories")
    conversation_count: int = Field(default=0, description="Number of conversations")
    storage_used: int = Field(default=0, description="Storage used in bytes")
    storage_limit: int = Field(
        default=1073741824, description="Storage limit in bytes (default 1GB)"
    )
    node_count: int = Field(default=0, description="Number of knowledge graph nodes")
    member_count: int = Field(default=0, description="Number of members")
    collaborators: int = Field(
        default=0, description="Number of collaborators (alias for member_count)"
    )
    active_nodes: int = Field(default=0, description="Number of active nodes in last 7 days")
    last_active: datetime | None = Field(default=None, description="Last activity timestamp")
    system_status: SystemStatus | None = Field(
        default=None, description="System status information"
    )
    recent_activity: list[dict] | None = Field(
        default_factory=list, description="Recent activity feed"
    )


class ProjectResponse(BaseModel):
    """Response model for project operations."""

    id: str = Field(..., description="Project unique identifier")
    tenant_id: str = Field(..., description="Tenant ID")
    name: str = Field(..., description="Project name")
    description: str | None = Field(default=None, description="Project description")
    owner_id: str = Field(..., description="Owner user ID")
    member_ids: list[str] = Field(default_factory=list, description="Member user IDs")
    memory_rules: MemoryRulesConfig = Field(
        default_factory=MemoryRulesConfig, description="Memory rules"
    )
    graph_config: GraphConfig = Field(
        default_factory=GraphConfig, description="Graph configuration"
    )
    sandbox_config: SandboxConfigSchema = Field(
        default_factory=SandboxConfigSchema, description="Sandbox configuration"
    )
    is_public: bool = Field(default=False, description="Whether the project is public")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime | None = Field(default=None, description="Last update timestamp")
    stats: ProjectStats | None = Field(default=None, description="Project statistics")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "project_123",
                "tenant_id": "tenant_123",
                "name": "AI Research Project",
                "description": "Knowledge management for AI research",
                "owner_id": "user_123",
                "member_ids": ["user_456", "user_789"],
                "memory_rules": {
                    "max_episodes": 1000,
                    "retention_days": 30,
                    "auto_refresh": True,
                    "refresh_interval": 24,
                },
                "graph_config": {
                    "max_nodes": 5000,
                    "max_edges": 10000,
                    "similarity_threshold": 0.7,
                    "community_detection": True,
                },
                "is_public": False,
                "created_at": "2024-01-15T10:30:00Z",
                "updated_at": "2024-01-15T12:45:00Z",
            }
        },
    )


class ProjectListResponse(BaseModel):
    """Response model for project list operations."""

    projects: list[ProjectResponse] = Field(..., description="List of projects")
    total: int = Field(..., description="Total number of projects")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Page size")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "projects": [
                    {
                        "id": "project_123",
                        "tenant_id": "tenant_123",
                        "name": "AI Research Project",
                        "description": "Knowledge management for AI research",
                        "owner_id": "user_123",
                        "member_ids": ["user_456", "user_789"],
                        "is_public": False,
                        "created_at": "2024-01-15T10:30:00Z",
                        "updated_at": "2024-01-15T12:45:00Z",
                    }
                ],
                "total": 1,
                "page": 1,
                "page_size": 20,
            }
        }
    )
