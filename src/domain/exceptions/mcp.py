"""
MCP domain exceptions.

Exception hierarchy for MCP-related operations including server management,
tool execution, transport, and connection handling.

Exception Hierarchy:
    MCPError (base)
    ├── MCPServerError
    │   ├── MCPServerNotFoundError      - Server not found by ID/name
    │   ├── MCPServerAlreadyExistsError - Server name conflict
    │   └── MCPServerNotConnectedError  - Server not in connected state
    ├── MCPToolError
    │   ├── MCPToolNotFoundError        - Tool not found on server
    │   └── MCPToolExecutionError       - Tool execution failed
    └── MCPConnectionError              - Connection/transport failure
"""

from typing import Any


class MCPError(Exception):
    """Base exception for all MCP-related errors."""

    def __init__(
        self,
        message: str,
        original_error: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.original_error = original_error
        self.details = details or {}

    def __str__(self) -> str:
        if self.original_error:
            return f"{self.message} (caused by: {self.original_error})"
        return self.message


class MCPServerError(MCPError):
    """Base exception for MCP server errors."""


class MCPServerNotFoundError(MCPServerError):
    """Raised when an MCP server cannot be found."""

    def __init__(
        self,
        server_id: str | None = None,
        server_name: str | None = None,
        message: str | None = None,
    ) -> None:
        self.server_id = server_id
        self.server_name = server_name
        identifier = server_name or server_id or "unknown"
        msg = message or f"MCP server '{identifier}' not found"
        super().__init__(msg, details={"server_id": server_id, "server_name": server_name})


class MCPServerAlreadyExistsError(MCPServerError):
    """Raised when creating a server with a name that already exists."""

    def __init__(self, server_name: str, message: str | None = None) -> None:
        self.server_name = server_name
        msg = message or f"MCP server '{server_name}' already exists"
        super().__init__(msg, details={"server_name": server_name})


class MCPServerNotConnectedError(MCPServerError):
    """Raised when attempting operations on a disconnected server."""

    def __init__(self, server_name: str, message: str | None = None) -> None:
        self.server_name = server_name
        msg = message or f"MCP server '{server_name}' is not connected"
        super().__init__(msg, details={"server_name": server_name})


class MCPToolError(MCPError):
    """Base exception for MCP tool errors."""


class MCPToolNotFoundError(MCPToolError):
    """Raised when a tool cannot be found on any MCP server."""

    def __init__(
        self,
        tool_name: str,
        server_name: str | None = None,
        message: str | None = None,
    ) -> None:
        self.tool_name = tool_name
        self.server_name = server_name
        if server_name:
            msg = message or f"Tool '{tool_name}' not found on server '{server_name}'"
        else:
            msg = message or f"Tool '{tool_name}' not found"
        super().__init__(msg, details={"tool_name": tool_name, "server_name": server_name})


class MCPToolExecutionError(MCPToolError):
    """Raised when a tool execution fails."""

    def __init__(
        self,
        tool_name: str,
        message: str | None = None,
        original_error: Exception | None = None,
    ) -> None:
        self.tool_name = tool_name
        msg = message or f"Tool '{tool_name}' execution failed"
        super().__init__(msg, original_error=original_error, details={"tool_name": tool_name})


class MCPConnectionError(MCPError):
    """Raised when MCP connection or transport fails."""

    def __init__(
        self,
        endpoint: str | None = None,
        message: str | None = None,
        original_error: Exception | None = None,
    ) -> None:
        self.endpoint = endpoint
        msg = message or "MCP connection failed"
        if endpoint:
            msg += f" (endpoint: {endpoint})"
        super().__init__(msg, original_error=original_error, details={"endpoint": endpoint})
