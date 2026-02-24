"""
MCP Tool Adapter for converting MCP tools to AgentTool interface.

Provides a bridge between MCP server tools and the MemStack agent system,
allowing MCP tools to be used seamlessly alongside native agent tools.
"""

import json
import logging
from typing import Any, cast

from src.infrastructure.agent.mcp.registry import MCPServerRegistry
from src.infrastructure.agent.tools.base import AgentTool

logger = logging.getLogger(__name__)


class MCPToolAdapter(AgentTool):
    """
    Adapter that wraps an MCP tool as an AgentTool.

    Converts MCP tool definitions into the AgentTool interface,
    enabling MCP tools to be used by the ReAct agent system.
    """

    def __init__(
        self,
        server_id: str,
        tool_definition: dict[str, Any],
        registry: MCPServerRegistry,
    ) -> None:
        """
        Initialize MCP tool adapter.

        Args:
            server_id: ID of the MCP server providing this tool
            tool_definition: MCP tool definition (name, description, inputSchema)
            registry: Registry for accessing the MCP server
        """
        self.server_id = server_id
        self.tool_definition = tool_definition
        self.registry = registry

        # Extract tool metadata
        tool_name = tool_definition.get("name", "unknown")
        tool_description = tool_definition.get("description", "No description")
        self.input_schema = tool_definition.get("inputSchema", {})

        # Initialize base class with MCP-prefixed name
        super().__init__(
            name=f"mcp_{server_id}_{tool_name}",
            description=f"[MCP] {tool_description}",
        )

        self.original_name = tool_name

    async def execute(self, **kwargs: Any) -> str:
        """
        Execute the MCP tool via the registry.

        Args:
            **kwargs: Tool arguments

        Returns:
            Tool execution result as string
        """
        try:
            # Call MCP tool through registry
            result = await self.registry.call_tool(
                server_id=self.server_id,
                tool_name=self.original_name,
                arguments=kwargs,
            )

            # Convert result to string
            if isinstance(result, str):
                return result
            elif isinstance(result, dict):
                return json.dumps(result, indent=2, ensure_ascii=False)
            else:
                return str(result)

        except Exception as e:
            error_msg = f"MCP tool execution failed: {e!s}"
            logger.error(f"{error_msg} (server={self.server_id}, tool={self.original_name})")
            return error_msg

    def validate_args(self, **kwargs: Any) -> bool:
        """
        Validate arguments against the MCP input schema.

        Args:
            **kwargs: Arguments to validate

        Returns:
            True if arguments are valid, False otherwise
        """
        if not self.input_schema:
            return True

        # Extract required properties from JSON Schema
        schema_properties = self.input_schema.get("properties", {})
        required_fields = self.input_schema.get("required", [])

        # Check required fields
        for field in required_fields:
            if field not in kwargs:
                logger.warning(f"Missing required field: {field}")
                return False

        # Check field types (basic validation)
        for field_name, field_value in kwargs.items():
            if field_name in schema_properties:
                field_schema = schema_properties[field_name]
                expected_type = field_schema.get("type")

                if expected_type:
                    if not self._validate_type(field_value, expected_type):
                        logger.warning(
                            f"Field {field_name} has invalid type "
                            f"(expected {expected_type}, got {type(field_value).__name__})"
                        )
                        return False

        return True

    def _validate_type(self, value: Any, expected_type: str) -> bool:
        """
        Validate value against JSON Schema type.

        Args:
            value: Value to validate
            expected_type: Expected JSON Schema type

        Returns:
            True if value matches expected type
        """
        type_mapping = {
            "string": str,
            "number": (int, float),
            "integer": int,
            "boolean": bool,
            "array": list,
            "object": dict,
        }

        python_type = type_mapping.get(expected_type)
        if not python_type:
            return True  # Unknown type, allow

        return isinstance(value, python_type)  # type: ignore[arg-type]

    def get_input_schema(self) -> dict[str, Any]:
        """Get the MCP tool input schema."""
        return cast(dict[str, Any], self.input_schema)

    def get_server_id(self) -> str:
        """Get the MCP server ID."""
        return self.server_id

    def get_original_name(self) -> str:
        """Get the original MCP tool name."""
        return cast(str, self.original_name)


class MCPToolFactory:
    """
    Factory for creating MCP tool adapters.

    Discovers tools from registered MCP servers and creates
    AgentTool adapters for each discovered tool.
    """

    def __init__(self, registry: MCPServerRegistry) -> None:
        """
        Initialize MCP tool factory.

        Args:
            registry: MCP server registry
        """
        self.registry = registry

    async def create_tools_for_server(self, server_id: str) -> list[MCPToolAdapter]:
        """
        Create tool adapters for all tools from a specific server.

        Args:
            server_id: MCP server identifier

        Returns:
            List of MCPToolAdapter instances
        """
        try:
            tools = await self.registry.get_tools(server_id)
            adapters = []

            for tool_def in tools:
                adapter = MCPToolAdapter(
                    server_id=server_id,
                    tool_definition=tool_def,
                    registry=self.registry,
                )
                adapters.append(adapter)
                logger.info(f"Created adapter for tool: {adapter.name}")

            return adapters

        except Exception as e:
            logger.error(f"Failed to create tools for server {server_id}: {e}")
            return []

    async def create_all_tools(self) -> list[MCPToolAdapter]:
        """
        Create tool adapters for all tools from all registered servers.

        Returns:
            List of MCPToolAdapter instances
        """
        all_adapters = []

        for server_id in self.registry.get_registered_servers():
            adapters = await self.create_tools_for_server(server_id)
            all_adapters.extend(adapters)

        logger.info(f"Created {len(all_adapters)} MCP tool adapters")
        return all_adapters

    async def create_tool_by_name(self, server_id: str, tool_name: str) -> MCPToolAdapter | None:
        """
        Create a tool adapter for a specific tool by name.

        Args:
            server_id: MCP server identifier
            tool_name: Original MCP tool name

        Returns:
            MCPToolAdapter instance or None if not found
        """
        try:
            tools = await self.registry.get_tools(server_id)

            for tool_def in tools:
                if tool_def.get("name") == tool_name:
                    adapter = MCPToolAdapter(
                        server_id=server_id,
                        tool_definition=tool_def,
                        registry=self.registry,
                    )
                    logger.info(f"Created adapter for tool: {adapter.name}")
                    return adapter

            logger.warning(f"Tool {tool_name} not found on server {server_id}")
            return None

        except Exception as e:
            logger.error(f"Failed to create tool {tool_name} for server {server_id}: {e}")
            return None
