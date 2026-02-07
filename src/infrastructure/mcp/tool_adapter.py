"""MCP Tool Adapter.

Adapts MCP tools to AgentTool interface for use with ReAct Agent.
Replaces MCPTemporalToolAdapter -- works with any MCP adapter backend.
"""

import logging
from typing import Any, Dict, Optional

from src.infrastructure.agent.tools.base import AgentTool

logger = logging.getLogger(__name__)


class MCPToolAdapter(AgentTool):
    """Adapter that wraps an MCP tool as an AgentTool.

    Works with both MCPRayAdapter and MCPLocalFallback.
    Tool naming convention: mcp__{server_name}__{tool_name}
    """

    MCP_PREFIX = "mcp"
    MCP_NAME_SEPARATOR = "__"

    def __init__(
        self,
        mcp_adapter: Any,
        server_name: str,
        tool_info: Any,
        tenant_id: str = "",
        permission_manager: Optional[Any] = None,
    ):
        self.mcp_adapter = mcp_adapter
        self.server_name = server_name
        self.tool_info = tool_info
        self.tenant_id = tenant_id
        self.permission_manager = permission_manager

        # Extract tool properties - handle both dataclass and dict
        if hasattr(tool_info, "name"):
            full_name = tool_info.name
            self._description = tool_info.description or ""
            self._input_schema = tool_info.input_schema or {}
        else:
            full_name = tool_info.get("name", "")
            self._description = tool_info.get("description", "")
            self._input_schema = tool_info.get("input_schema", {})

        # Extract original tool name from prefixed name
        if full_name.startswith(f"{self.MCP_PREFIX}{self.MCP_NAME_SEPARATOR}"):
            parts = full_name.split(self.MCP_NAME_SEPARATOR)
            self.original_tool_name = parts[-1] if len(parts) >= 3 else full_name
        else:
            self.original_tool_name = full_name

        self._name = self._generate_tool_name()

    def _generate_tool_name(self) -> str:
        clean_server = self.server_name.replace("-", "_")
        return (
            f"{self.MCP_PREFIX}{self.MCP_NAME_SEPARATOR}"
            f"{clean_server}{self.MCP_NAME_SEPARATOR}"
            f"{self.original_tool_name}"
        )

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description or f"MCP tool {self.original_tool_name} from {self.server_name}"

    @property
    def parameters(self) -> Dict[str, Any]:
        return self._input_schema

    def get_parameters_schema(self) -> Dict[str, Any]:
        if not self._input_schema:
            return {"type": "object", "properties": {}, "required": []}

        schema = dict(self._input_schema)
        if "type" not in schema:
            schema["type"] = "object"
        if "properties" not in schema:
            schema["properties"] = {}
        if "required" not in schema:
            schema["required"] = []
        return schema

    async def execute(self, **kwargs: Any) -> str:
        """Execute the MCP tool through the adapter."""
        logger.info("Executing MCP tool: %s", self._name)

        try:
            if self.permission_manager:
                pass  # TODO: Implement permission check

            result = await self.mcp_adapter.call_mcp_tool(
                tenant_id=self.tenant_id,
                server_name=self.server_name,
                tool_name=self.original_tool_name,
                arguments=kwargs,
            )

            if result.is_error:
                error_msg = result.error_message or "Tool execution failed"
                logger.error("MCP tool error: %s", error_msg)
                return f"Error: {error_msg}"

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
            logger.exception("Error executing MCP tool %s: %s", self._name, e)
            return f"Error executing tool: {e}"
