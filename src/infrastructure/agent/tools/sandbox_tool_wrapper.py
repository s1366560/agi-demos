"""Sandbox MCP Tool Wrapper.

Wraps MCP tools from a sandbox instance as Agent tools with namespacing.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from src.infrastructure.agent.tools.base import AgentTool

logger = logging.getLogger(__name__)


class SandboxMCPToolWrapper(AgentTool):
    """
    Wrapper for Sandbox MCP tools to be used by ReActAgent.

    Tools are namespaced to avoid conflicts between multiple sandboxes:
    - Format: sandbox_{sandbox_id}_{tool_name}
    - Example: sandbox_abc123def_bash, sandbox_abc123def_file_read

    The wrapper routes tool execution calls to the correct sandbox instance.
    """

    def __init__(
        self,
        sandbox_id: str,
        tool_name: str,
        tool_schema: Dict[str, Any],
        sandbox_adapter: Any,
    ):
        """
        Initialize the wrapper.

        Args:
            sandbox_id: The sandbox instance ID
            tool_name: Original MCP tool name (e.g., "bash", "file_read")
            tool_schema: MCP tool schema with name, description, input_schema
            sandbox_adapter: MCPSandboxAdapter instance for routing calls
        """
        self.sandbox_id = sandbox_id
        self.tool_name = tool_name
        self._adapter = sandbox_adapter
        self._schema = tool_schema

        # Create namespaced name to avoid conflicts
        namespaced_name = f"sandbox_{sandbox_id}_{tool_name}"

        # Create description with sandbox context
        base_description = tool_schema.get("description", f"{tool_name} tool")
        description = f"[Sandbox:{sandbox_id[:8]}...] {base_description}"

        super().__init__(
            name=namespaced_name,
            description=description,
        )

        logger.debug(
            f"SandboxMCPToolWrapper: Created wrapper for sandbox={sandbox_id}, "
            f"tool={tool_name}, namespaced_name={namespaced_name}"
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Get parameters schema from MCP tool schema."""
        input_schema = self._schema.get("input_schema", {})

        # Convert MCP schema format to Agent tool schema format
        properties = {}
        required = []

        if isinstance(input_schema, dict):
            # Handle JSON Schema format
            schema_props = input_schema.get("properties", {})
            for prop_name, prop_def in schema_props.items():
                properties[prop_name] = {
                    "type": prop_def.get("type", "string"),
                    "description": prop_def.get("description", ""),
                }
                if "default" in prop_def:
                    properties[prop_name]["default"] = prop_def["default"]

            required = input_schema.get("required", [])

        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }

    def validate_args(self, **kwargs: Any) -> bool:
        """Validate arguments against the MCP tool schema."""
        input_schema = self._schema.get("input_schema", {})

        if not isinstance(input_schema, dict):
            return True

        required = input_schema.get("required", [])
        return all(arg in kwargs for arg in required)

    async def execute(self, **kwargs: Any) -> str:
        """
        Execute the tool by routing to the sandbox's MCP tool.

        Args:
            **kwargs: Tool arguments as defined in input_schema

        Returns:
            String result from tool execution
        """
        try:
            logger.debug(
                f"SandboxMCPToolWrapper: Executing {self.name} "
                f"(sandbox={self.sandbox_id}, tool={self.tool_name})"
            )

            # Route to sandbox adapter's call_tool method
            result = await self._adapter.call_tool(
                self.sandbox_id,
                self.tool_name,
                kwargs,
            )

            # Parse result
            if result.get("is_error"):
                content_list = result.get("content", [])
                error_msg = content_list[0].get("text", "Unknown error") if content_list else "Unknown error"
                return f"Error: {error_msg}"

            # Extract output
            content_list = result.get("content", [])
            if content_list and len(content_list) > 0:
                return content_list[0].get("text", "")

            return "Success"

        except Exception as e:
            logger.error(
                f"SandboxMCPToolWrapper: Error executing {self.name}: {e}"
            )
            return f"Error: {str(e)}"
