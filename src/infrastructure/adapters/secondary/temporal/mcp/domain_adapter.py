"""
Temporal MCP Domain Adapter.

Provides conversion between Temporal MCP data classes and domain models.
"""

from typing import Any, Dict, List

from src.domain.model.mcp.tool import MCPToolResult, MCPToolSchema


class TemporalMCPDomainAdapter:
    """
    Adapter for converting between Temporal MCP types and domain models.

    This class provides a bridge layer that allows Temporal workflows and
    activities to work with domain models while maintaining backward
    compatibility with existing Temporal dataclass serialization.
    """

    @staticmethod
    def to_domain_tool_result(data: Dict[str, Any]) -> MCPToolResult:
        """
        Convert Temporal MCPToolResult dict to domain MCPToolResult.

        Handles both 'isError' (MCP protocol) and 'is_error' (internal) formats.

        Args:
            data: Dictionary containing tool result data

        Returns:
            MCPToolResult domain model
        """
        # Handle None values by using False as default for is_error
        is_error_value = data.get("is_error", data.get("isError", False))
        return MCPToolResult(
            content=data.get("content") or [],
            is_error=bool(is_error_value) if is_error_value is not None else False,
            error_message=data.get("error_message"),
            metadata=data.get("metadata"),
            artifact=data.get("artifact"),
            execution_time_ms=data.get("execution_time_ms"),
        )

    @staticmethod
    def from_domain_tool_result(result: MCPToolResult) -> Dict[str, Any]:
        """
        Convert domain MCPToolResult to Temporal-serializable dict.

        Uses 'isError' format for MCP protocol compatibility.

        Args:
            result: Domain MCPToolResult

        Returns:
            Dictionary for Temporal serialization
        """
        return {
            "content": result.content,
            "isError": result.is_error,
            "error_message": result.error_message,
            "metadata": result.metadata,
            "artifact": result.artifact,
            "execution_time_ms": result.execution_time_ms,
        }

    @staticmethod
    def to_domain_tool_schema(data: Dict[str, Any]) -> MCPToolSchema:
        """
        Convert Temporal tool schema dict to domain MCPToolSchema.

        Args:
            data: Dictionary containing tool schema

        Returns:
            MCPToolSchema domain model
        """
        return MCPToolSchema.from_dict(data)

    @staticmethod
    def from_domain_tool_schema(schema: MCPToolSchema) -> Dict[str, Any]:
        """
        Convert domain MCPToolSchema to Temporal-serializable dict.

        Args:
            schema: Domain MCPToolSchema

        Returns:
            Dictionary for Temporal serialization
        """
        return schema.to_dict()

    @staticmethod
    def convert_tools_list(tools: List[Dict[str, Any]]) -> List[MCPToolSchema]:
        """
        Convert list of tool dictionaries to domain MCPToolSchema list.

        Args:
            tools: List of tool definition dictionaries

        Returns:
            List of MCPToolSchema domain models
        """
        return [MCPToolSchema.from_dict(t) for t in tools]


# Convenience functions for direct import
to_domain_tool_result = TemporalMCPDomainAdapter.to_domain_tool_result
from_domain_tool_result = TemporalMCPDomainAdapter.from_domain_tool_result
to_domain_tool_schema = TemporalMCPDomainAdapter.to_domain_tool_schema
from_domain_tool_schema = TemporalMCPDomainAdapter.from_domain_tool_schema
