"""Pydantic schemas for Sandbox API.

Contains all request/response models for sandbox operations.
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# --- Core Sandbox Schemas ---


class CreateSandboxRequest(BaseModel):
    """Request to create a new sandbox."""

    project_path: str = Field(
        default="/tmp/sandbox_workspace", description="Path to mount as workspace"
    )
    profile: Optional[str] = Field(
        default="standard", description="Sandbox profile: lite, standard, or full"
    )
    image: Optional[str] = Field(
        default=None, description="Docker image (default: sandbox-mcp-server)"
    )
    memory_limit: Optional[str] = Field(
        default=None, description="Memory limit (overrides profile if set)"
    )
    cpu_limit: Optional[str] = Field(
        default=None, description="CPU limit (overrides profile if set)"
    )
    timeout_seconds: Optional[int] = Field(
        default=None, description="Max sandbox lifetime (overrides profile if set)"
    )
    network_isolated: bool = Field(default=False, description="Network isolation")
    environment: Dict[str, str] = Field(default_factory=dict, description="Environment variables")


class SandboxResponse(BaseModel):
    """Sandbox instance response."""

    id: str
    status: str
    project_path: str
    endpoint: Optional[str] = None
    websocket_url: Optional[str] = None
    created_at: str
    tools: List[str] = Field(default_factory=list)
    # Service ports and URLs
    mcp_port: Optional[int] = None
    desktop_port: Optional[int] = None
    terminal_port: Optional[int] = None
    desktop_url: Optional[str] = None
    terminal_url: Optional[str] = None


class ListSandboxesResponse(BaseModel):
    """List sandboxes response."""

    sandboxes: List[SandboxResponse]
    total: int


# --- Tool Schemas ---


class ToolCallRequest(BaseModel):
    """Request to call an MCP tool."""

    tool_name: str = Field(..., description="Tool name (read, write, edit, glob, grep, bash)")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments")
    timeout: float = Field(default=30.0, description="Timeout in seconds")


class ToolCallResponse(BaseModel):
    """Tool call response."""

    content: List[Dict[str, Any]]
    is_error: bool


class ToolInfo(BaseModel):
    """Tool information."""

    name: str
    description: Optional[str] = None
    input_schema: Dict[str, Any] = Field(default_factory=dict)


class ListToolsResponse(BaseModel):
    """List tools response."""

    tools: List[ToolInfo]


# --- Desktop Schemas ---


class DesktopStartRequest(BaseModel):
    """Request to start desktop service."""

    resolution: str = Field(default="1280x720", description="Screen resolution (e.g., '1280x720')")
    display: str = Field(default=":1", description="X11 display number (e.g., ':1')")


class DesktopStatusResponse(BaseModel):
    """Desktop service status response."""

    running: bool = Field(..., description="Whether desktop service is running")
    url: Optional[str] = Field(None, description="KasmVNC web client URL (if running)")
    display: str = Field(default="", description="X11 display number (e.g., ':1')")
    resolution: str = Field(default="", description="Screen resolution (e.g., '1920x1080')")
    port: int = Field(default=0, description="KasmVNC web server port number")
    audio_enabled: bool = Field(default=False, description="Whether audio streaming is enabled")
    dynamic_resize: bool = Field(default=True, description="Whether dynamic resize is supported")
    encoding: str = Field(default="webp", description="Image encoding format (webp/jpeg/qoi)")


class DesktopStopResponse(BaseModel):
    """Response from stopping desktop."""

    success: bool = Field(..., description="Whether the operation was successful")
    message: str = Field(default="", description="Status message")


# --- Terminal Schemas ---


class TerminalStartRequest(BaseModel):
    """Request to start terminal service."""

    port: int = Field(default=7681, description="Port for the ttyd WebSocket server")


class TerminalStatusResponse(BaseModel):
    """Terminal service status response."""

    running: bool = Field(..., description="Whether terminal service is running")
    url: Optional[str] = Field(None, description="WebSocket URL (if running)")
    port: int = Field(default=0, description="Ttyd port number")
    pid: Optional[int] = Field(None, description="Process ID")
    session_id: Optional[str] = Field(None, description="Terminal session ID")


class TerminalStopResponse(BaseModel):
    """Response from stopping terminal."""

    success: bool = Field(..., description="Whether the operation was successful")
    message: str = Field(default="", description="Status message")


# --- Token Schemas ---


class SandboxTokenRequest(BaseModel):
    """Request to generate a sandbox access token."""

    sandbox_type: Literal["cloud", "local"] = Field(
        default="cloud",
        description="Type of sandbox: 'cloud' for server-managed, 'local' for user's machine",
    )
    ttl_seconds: int = Field(
        default=300,
        ge=60,
        le=3600,
        description="Token time-to-live in seconds (1-60 minutes)",
    )


class SandboxTokenResponse(BaseModel):
    """Response containing sandbox access token."""

    token: str = Field(..., description="Access token for sandbox WebSocket connection")
    project_id: str = Field(..., description="Project ID the token is scoped to")
    sandbox_type: str = Field(..., description="Type of sandbox (cloud/local)")
    expires_at: str = Field(..., description="ISO format expiration timestamp")
    expires_in: int = Field(..., description="Seconds until token expires")
    websocket_url_hint: str = Field(
        default="",
        description="Hint for constructing WebSocket URL with token",
    )


class ValidateTokenRequest(BaseModel):
    """Request to validate a sandbox token."""

    token: str = Field(..., description="Token to validate")
    project_id: Optional[str] = Field(
        default=None, description="Optional project ID to verify against"
    )


class ValidateTokenResponse(BaseModel):
    """Response from token validation."""

    valid: bool = Field(..., description="Whether the token is valid")
    project_id: Optional[str] = Field(None, description="Project ID from token")
    user_id: Optional[str] = Field(None, description="User ID from token")
    sandbox_type: Optional[str] = Field(None, description="Sandbox type from token")
    error: Optional[str] = Field(None, description="Error message if invalid")


# --- Profile Schemas ---


class ProfileInfo(BaseModel):
    """Information about a sandbox profile."""

    name: str = Field(..., description="Profile name (e.g., 'Lite', 'Standard', 'Full')")
    profile_type: str = Field(..., description="Profile type identifier (lite, standard, full)")
    description: str = Field(..., description="Profile description")
    desktop_enabled: bool = Field(..., description="Whether desktop environment is enabled")
    memory_limit: str = Field(..., description="Memory limit (e.g., '512m', '2g', '4g')")
    cpu_limit: str = Field(..., description="CPU limit (e.g., '0.5', '2', '4')")
    timeout_seconds: int = Field(..., description="Maximum sandbox lifetime in seconds")
    preinstalled_tools: List[str] = Field(..., description="List of preinstalled tools")
    max_instances: int = Field(..., description="Maximum concurrent instances")


class ListProfilesResponse(BaseModel):
    """Response listing all available sandbox profiles."""

    profiles: List[ProfileInfo]


# --- Health Check Schemas ---


class HealthCheckResponse(BaseModel):
    """Health check response."""

    level: str = Field(..., description="Health check level performed")
    status: str = Field(..., description="Overall health status")
    healthy: bool = Field(..., description="Whether the sandbox is healthy")
    details: Dict[str, Any] = Field(default_factory=dict, description="Detailed health information")
    timestamp: str = Field(..., description="ISO format timestamp")
    sandbox_id: str = Field(..., description="Sandbox ID")
    errors: List[str] = Field(default_factory=list, description="List of errors found")
