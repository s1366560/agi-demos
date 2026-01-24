"""
MCP Temporal Tool Adapter.

Adapts Temporal MCP tools to AgentTool interface for use with ReAct Agent.
This adapter calls tools through MCPTemporalAdapter (Temporal Workflows).
"""

import logging
from typing import Any, Dict, Optional

from src.infrastructure.agent.tools.base import AgentTool

logger = logging.getLogger(__name__)


class MCPTemporalToolAdapter(AgentTool):
    """
    Adapter that wraps a Temporal MCP tool as an AgentTool.

    This adapter:
    1. Converts MCP tool schema to AgentTool format
    2. Routes tool calls through MCPTemporalAdapter
    3. Handles permission checks if configured

    Tool naming convention: mcp__{server_name}__{tool_name}
    """

    MCP_PREFIX = "mcp"
    MCP_NAME_SEPARATOR = "__"

    def __init__(
        self,
        mcp_temporal_adapter: Any,  # MCPTemporalAdapter
        server_name: str,
        tool_info: Any,  # MCPToolInfo dataclass or dict
        tenant_id: str = "",
        permission_manager: Optional[Any] = None,
    ):
        """
        Initialize MCP Temporal Tool Adapter.

        Args:
            mcp_temporal_adapter: MCPTemporalAdapter instance for tool execution
            server_name: Name of the MCP server
            tool_info: Tool info from MCPTemporalAdapter.list_tools() (MCPToolInfo dataclass)
            tenant_id: Tenant ID for the MCP server
            permission_manager: Optional permission manager for access control
        """
        self.mcp_temporal_adapter = mcp_temporal_adapter
        self.server_name = server_name
        self.tool_info = tool_info
        self.tenant_id = tenant_id
        self.permission_manager = permission_manager

        # Extract tool properties - handle both dataclass and dict
        if hasattr(tool_info, "name"):
            # MCPToolInfo dataclass
            full_name = tool_info.name
            self._description = tool_info.description or ""
            self._input_schema = tool_info.input_schema or {}
        else:
            # Dictionary fallback
            full_name = tool_info.get("name", "")
            self._description = tool_info.get("description", "")
            self._input_schema = tool_info.get("input_schema", {})

        # Tool info comes from adapter.list_tools() with name like "mcp__{server}__{tool}"
        if full_name.startswith(f"{self.MCP_PREFIX}{self.MCP_NAME_SEPARATOR}"):
            # Already has mcp__ prefix, extract original name
            parts = full_name.split(self.MCP_NAME_SEPARATOR)
            self.original_tool_name = parts[-1] if len(parts) >= 3 else full_name
        else:
            self.original_tool_name = full_name

        # Generate full tool name
        self._name = self._generate_tool_name()

        logger.debug(
            f"Created MCPTemporalToolAdapter: {self._name} "
            f"(server: {server_name}, original: {self.original_tool_name})"
        )

    def _generate_tool_name(self) -> str:
        """Generate the full tool name with MCP prefix."""
        # Clean server name (replace - with _)
        clean_server = self.server_name.replace("-", "_")
        return f"{self.MCP_PREFIX}{self.MCP_NAME_SEPARATOR}{clean_server}{self.MCP_NAME_SEPARATOR}{self.original_tool_name}"

    @property
    def name(self) -> str:
        """Get the tool name."""
        return self._name

    @property
    def description(self) -> str:
        """Get the tool description."""
        return self._description or f"MCP tool {self.original_tool_name} from {self.server_name}"

    @property
    def parameters(self) -> Dict[str, Any]:
        """Get the tool parameters schema."""
        return self._input_schema

    def get_parameters_schema(self) -> Dict[str, Any]:
        """
        Get the parameters schema for LLM function calling.

        Returns the MCP tool's input schema in a format suitable for LLM function calling.

        Returns:
            JSON schema dictionary describing the tool parameters
        """
        if not self._input_schema:
            return {
                "type": "object",
                "properties": {},
                "required": [],
            }

        # Return the input schema, ensuring it has the expected structure
        schema = dict(self._input_schema)
        if "type" not in schema:
            schema["type"] = "object"
        if "properties" not in schema:
            schema["properties"] = {}
        if "required" not in schema:
            schema["required"] = []

        return schema

    async def execute(self, **kwargs: Any) -> str:
        """
        Execute the MCP tool through Temporal Workflow.

        Args:
            **kwargs: Tool arguments

        Returns:
            Tool execution result as string
        """
        logger.info(f"Executing Temporal MCP tool: {self._name}")
        logger.debug(f"Tool arguments: {kwargs}")

        try:
            # Check permission if manager is available
            if self.permission_manager:
                # TODO: Implement permission check
                pass

            # Call tool through Temporal adapter
            result = await self.mcp_temporal_adapter.call_mcp_tool(
                tenant_id=self.tenant_id,
                server_name=self.server_name,
                tool_name=self.original_tool_name,
                arguments=kwargs,
            )

            # Format result
            if result.is_error:
                error_msg = result.error_message or "Tool execution failed"
                logger.error(f"Temporal MCP tool error: {error_msg}")
                return f"Error: {error_msg}"

            # Extract text content from result
            if result.content:
                texts = []
                for item in result.content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            texts.append(item.get("text", ""))
                        else:
                            texts.append(str(item))
                    else:
                        texts.append(str(item))
                return "\n".join(texts)

            return "Tool executed successfully (no output)"

        except Exception as e:
            logger.exception(f"Error executing Temporal MCP tool {self._name}: {e}")
            return f"Error executing tool: {str(e)}"
