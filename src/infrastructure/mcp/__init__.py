"""
MCP (Model Context Protocol) Infrastructure Layer.

This module provides MCP tool integration for the MemStack Agent system.
All MCP servers are managed via Temporal Workflows for horizontal scaling.

Architecture:
- MCPConfig: Configuration models for local/remote MCP servers
- MCPTemporalToolAdapter: Adapts Temporal MCP tools to AgentTool interface
- MCPTemporalToolLoader: Loads tools from Temporal MCP servers

Server configurations are stored in database (tenant-scoped).
Tools are loaded dynamically from running Temporal Workflows.
"""

from src.infrastructure.mcp.config import (
    McpConfig,
    McpLocalConfig,
    McpOAuthConfig,
    McpRemoteConfig,
    MCPStatus,
)
from src.infrastructure.mcp.temporal_tool_adapter import MCPTemporalToolAdapter
from src.infrastructure.mcp.temporal_tool_loader import MCPTemporalToolLoader

__all__ = [
    "McpConfig",
    "McpLocalConfig",
    "McpOAuthConfig",
    "McpRemoteConfig",
    "MCPStatus",
    "MCPTemporalToolAdapter",
    "MCPTemporalToolLoader",
]
