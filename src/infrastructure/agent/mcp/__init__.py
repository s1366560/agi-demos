"""MCP (Model Context Protocol) integration package."""

from src.infrastructure.agent.mcp.adapter import (
    create_all_mcp_tools,
    create_mcp_tool,
    create_mcp_tool_by_name,
    create_mcp_tools_from_server,
    mcp_tool_name,
)
from src.infrastructure.agent.mcp.client import MCPClient, MCPTransport
from src.infrastructure.agent.mcp.oauth import (
    MCPAuthEntry,
    MCPAuthStorage,
    MCPOAuthProvider,
    OAuthClientInfo,
    OAuthTokens,
    base64_url_encode,
)
from src.infrastructure.agent.mcp.oauth_callback import (
    MCPOAuthCallbackServer,
    get_oauth_callback_server,
    stop_oauth_callback_server,
)
from src.infrastructure.agent.mcp.registry import MCPServerRegistry

__all__ = [
    "MCPAuthEntry",
    "MCPAuthStorage",
    "MCPClient",
    "MCPOAuthCallbackServer",
    "MCPOAuthProvider",
    "MCPServerRegistry",
    "MCPTransport",
    "OAuthClientInfo",
    "OAuthTokens",
    "base64_url_encode",
    "create_all_mcp_tools",
    "create_mcp_tool",
    "create_mcp_tool_by_name",
    "create_mcp_tools_from_server",
    "get_oauth_callback_server",
    "mcp_tool_name",
    "stop_oauth_callback_server",
]
