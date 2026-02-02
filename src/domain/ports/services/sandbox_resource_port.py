"""Sandbox Resource Port - Abstract interface for sandbox access.

This port defines the contract that sandbox services must implement to be
used by the agent workflow. It provides a clean abstraction that decouples
agent logic from sandbox lifecycle management.

Key Design Principles:
1. Agent only needs to know "I can execute tools"
2. Agent doesn't participate in sandbox creation decisions
3. Can be mocked for testing agent logic
4. Supports lazy initialization (sandbox created on first use)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class SandboxInfo:
    """Information about a project's sandbox.

    This is a domain model that represents the current state of a sandbox.
    It is moved from the application layer to the domain layer to be
    shared across different ports.
    """

    sandbox_id: str
    project_id: str
    tenant_id: str
    status: str
    endpoint: Optional[str] = None
    websocket_url: Optional[str] = None
    mcp_port: Optional[int] = None
    desktop_port: Optional[int] = None
    terminal_port: Optional[int] = None
    desktop_url: Optional[str] = None
    terminal_url: Optional[str] = None
    created_at: Optional[datetime] = None
    last_accessed_at: Optional[datetime] = None
    is_healthy: bool = False
    error_message: Optional[str] = None
    available_tools: List[str] = None

    def __post_init__(self) -> None:
        if self.available_tools is None:
            self.available_tools = []

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "sandbox_id": self.sandbox_id,
            "project_id": self.project_id,
            "tenant_id": self.tenant_id,
            "status": self.status,
            "endpoint": self.endpoint,
            "websocket_url": self.websocket_url,
            "mcp_port": self.mcp_port,
            "desktop_port": self.desktop_port,
            "terminal_port": self.terminal_port,
            "desktop_url": self.desktop_url,
            "terminal_url": self.terminal_url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_accessed_at": self.last_accessed_at.isoformat()
            if self.last_accessed_at
            else None,
            "is_healthy": self.is_healthy,
            "error_message": self.error_message,
            "available_tools": self.available_tools,
        }


class SandboxResourcePort(ABC):
    """Abstract port for sandbox resource access.

    This port defines the contract that sandbox services must implement.
    It provides a clean interface for agents to access sandbox functionality
    without coupling to specific implementation details.

    Agents should only depend on this port, not on concrete implementations.
    This allows:
    - Mocking for testing
    - Swapping implementations (local vs cloud sandboxes)
    - Evolving the implementation without changing agent code
    """

    @abstractmethod
    async def get_sandbox_id(
        self,
        project_id: str,
        tenant_id: str,
    ) -> Optional[str]:
        """Get the sandbox ID for a project without creating one.

        This is a read-only operation that will not trigger sandbox creation.

        Args:
            project_id: The project ID
            tenant_id: The tenant ID

        Returns:
            The sandbox ID if one exists, None otherwise
        """

    @abstractmethod
    async def ensure_sandbox_ready(
        self,
        project_id: str,
        tenant_id: str,
    ) -> str:
        """Ensure a sandbox is ready for the project, creating if necessary.

        This is the only method that may trigger sandbox creation.
        If a sandbox already exists and is healthy, it returns the existing ID.
        If no sandbox exists or the existing one is unhealthy, it creates a new one.

        Args:
            project_id: The project ID
            tenant_id: The tenant ID

        Returns:
            The sandbox ID that is ready for use

        Raises:
            SandboxError: If sandbox creation fails
        """

    @abstractmethod
    async def execute_tool(
        self,
        project_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        """Execute a tool in the project's sandbox.

        Args:
            project_id: The project ID
            tool_name: The name of the tool to execute
            arguments: Tool arguments
            timeout: Execution timeout in seconds

        Returns:
            Tool execution result

        Raises:
            SandboxNotFoundError: If no sandbox exists for the project
            SandboxTimeoutError: If tool execution times out
        """

    @abstractmethod
    async def sync_file(
        self,
        project_id: str,
        filename: str,
        content_base64: str,
        destination: str = "/workspace",
    ) -> bool:
        """Sync a file to the project's sandbox.

        This method handles base64 decoding and file transfer to the sandbox.

        Args:
            project_id: The project ID
            filename: The name of the file
            content_base64: Base64-encoded file content
            destination: Target directory in sandbox (default: /workspace)

        Returns:
            True if sync succeeded, False otherwise
        """

    @abstractmethod
    async def get_sandbox_info(
        self,
        project_id: str,
    ) -> Optional[SandboxInfo]:
        """Get information about the project's sandbox.

        Args:
            project_id: The project ID

        Returns:
            SandboxInfo if sandbox exists, None otherwise
        """
