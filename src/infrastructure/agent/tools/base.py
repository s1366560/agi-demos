"""Base tool class for ReAct agent.

This module defines the abstract base class that all agent tools must implement.

Enhanced with tool composition support (T109-T111) for intelligent tool chaining
and output truncation to prevent excessive token usage.
"""

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from src.infrastructure.agent.tools.truncation import (
    MAX_OUTPUT_BYTES,
    OutputTruncator,
)

logger = logging.getLogger(__name__)


class AgentTool(ABC):
    """
    Abstract base class for agent tools.

    All tools used by the ReAct agent must inherit from this class
    and implement the required methods.

    Tool Composition Support:
    - Tools can declare their output schema for composition
    - Tools can check compatibility with other tools
    - Tools can transform their output for input to another tool
    """

    def __init__(
        self,
        name: str,
        description: str,
        max_output_bytes: int = MAX_OUTPUT_BYTES,
    ):
        """
        Initialize the tool.

        Args:
            name: Unique name for the tool
            description: Human-readable description of what the tool does
            max_output_bytes: Maximum output size in bytes (default: 50KB)
        """
        self._name = name
        self._description = description
        self._max_output_bytes = max_output_bytes
        self._truncator = OutputTruncator(max_bytes=max_output_bytes)

    @property
    def name(self) -> str:
        """Get the tool name."""
        return self._name

    @property
    def description(self) -> str:
        """Get the tool description."""
        return self._description

    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        """
        Execute the tool with the given arguments.

        Args:
            **kwargs: Tool-specific arguments

        Returns:
            String result of the tool execution

        Raises:
            Exception: If tool execution fails
        """
        pass

    def validate_args(self, **kwargs: Any) -> bool:
        """
        Validate tool arguments before execution.

        Args:
            **kwargs: Arguments to validate

        Returns:
            True if arguments are valid, False otherwise

        Note:
            Default implementation always returns True.
            Override for custom validation logic.
        """
        return True

    async def safe_execute(self, **kwargs: Any) -> str:
        """
        Safely execute the tool with error handling.

        Args:
            **kwargs: Tool-specific arguments

        Returns:
            String result of the tool execution, or error message if failed
        """
        try:
            if not self.validate_args(**kwargs):
                return f"Error: Invalid arguments for tool {self._name}"

            logger.info(f"Executing tool: {self._name} with args: {kwargs}")
            result = await self.execute(**kwargs)
            logger.info(f"Tool {self._name} completed successfully")
            return result

        except Exception as e:
            error_msg = f"Error executing tool {self._name}: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def truncate_output(self, output: str) -> str:
        """
        Truncate tool output to maximum byte size.

        Args:
            output: Raw output from tool execution

        Returns:
            Truncated output if exceeds limit, otherwise original output
        """
        result = self._truncator.truncate(output)
        if result.truncated:
            logger.warning(
                f"Tool {self._name} output truncated: {result.truncated_bytes} bytes removed"
            )
        return result.output

    # === Tool Composition Methods (T109-T111) ===

    def get_output_schema(self) -> Dict[str, Any]:
        """
        Get the output schema of this tool (T109).

        Returns a JSON schema describing the structure of this tool's output.
        This is used for tool composition to validate compatibility.

        Default implementation returns a generic string output schema.

        Returns:
            JSON schema dictionary describing the output format

        Example:
            {
                "type": "object",
                "properties": {
                    "results": {"type": "array"},
                    "count": {"type": "integer"}
                }
            }
        """
        return {"type": "string", "description": f"Output from {self._name} tool"}

    def can_compose_with(self, other_tool: "AgentTool") -> bool:
        """
        Check if this tool's output can be used as input for another tool (T110).

        This method checks compatibility between this tool's output
        and another tool's expected input format.

        Args:
            other_tool: The tool to check compatibility with

        Returns:
            True if the tools can be composed, False otherwise

        Note:
            Default implementation returns True (assumes compatibility).
            Override for specific compatibility checks.
        """
        # Default: assume tools are compatible
        # Specific tools should override this for precise checking
        return True

    def compose_output(
        self, output: str, target_tool: "AgentTool", transformation: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Transform this tool's output for use as input to another tool (T111).

        This method applies data transformations to make the output
        from this tool suitable as input for the target tool.

        Args:
            output: The raw output string from this tool
            target_tool: The tool that will receive the transformed output
            transformation: Optional transformation rules with keys:
                - field_mapping: {"source_field": "target_field"}
                - extract_path: "path.to.field" to extract specific data
                - filter: {"key": "value"} to filter results
                - aggregate: "sum"|"count"|"first"|"last" to aggregate arrays

        Returns:
            Transformed output as a dictionary suitable for the target tool's input

        Example transformations:
            - Extract specific fields from output
            - Parse structured data (JSON, CSV)
            - Aggregate or filter results
            - Map field names between tools
        """
        # Parse output as JSON if possible
        try:
            parsed = json.loads(output)
        except (json.JSONDecodeError, TypeError):
            parsed = {"raw_output": output}

        # Apply transformations if specified
        if transformation:
            # Extract specific path
            if "extract_path" in transformation:
                path = transformation["extract_path"]
                extracted = self.extract_output_field(output, path)
                parsed = extracted if extracted is not None else parsed

            # Field mapping
            if "field_mapping" in transformation and isinstance(parsed, dict):
                mapping = transformation["field_mapping"]
                mapped = {}
                for source_key, target_key in mapping.items():
                    if source_key in parsed:
                        mapped[target_key] = parsed[source_key]
                parsed = mapped if mapped else parsed

            # Filter results (for arrays)
            if "filter" in transformation and isinstance(parsed, list):
                filter_rules = transformation["filter"]
                filtered = []
                for item in parsed:
                    if isinstance(item, dict):
                        matches = all(item.get(k) == v for k, v in filter_rules.items())
                        if matches:
                            filtered.append(item)
                parsed = filtered

            # Aggregate results (for arrays)
            if "aggregate" in transformation and isinstance(parsed, list):
                agg_type = transformation["aggregate"]
                if agg_type == "count":
                    parsed = {"count": len(parsed)}
                elif agg_type == "first" and parsed:
                    parsed = parsed[0]
                elif agg_type == "last" and parsed:
                    parsed = parsed[-1]
                elif agg_type == "sum":
                    # Try to sum numeric values
                    try:
                        parsed = {"sum": sum(parsed)}
                    except (TypeError, ValueError):
                        pass

        # Ensure result is a dictionary
        if not isinstance(parsed, dict):
            return {"data": parsed}

        return parsed

    def get_input_schema(self) -> Dict[str, Any]:
        """
        Get the input schema of this tool (helper for composition).

        Returns a JSON schema describing the expected input format.
        Used by compose_output to validate transformations.

        Returns:
            JSON schema dictionary describing the input format
        """
        return {"type": "object", "description": f"Input for {self._name} tool"}

    def get_parameters_schema(self) -> Dict[str, Any]:
        """
        Get the parameters schema for LLM function calling.

        Returns a JSON schema describing the parameters this tool accepts.
        This is used by the agent to tell the LLM what arguments the tool expects.

        Override this method in subclasses to define specific parameters.

        Returns:
            JSON schema dictionary describing the tool parameters
        """
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    def extract_output_field(self, output: str, field_path: str) -> Any:
        """
        Extract a specific field from tool output using a path.

        Helper method for compose_output to extract specific data.

        Args:
            output: The raw output string from this tool
            field_path: Dot-separated path to the field (e.g., "results.0.id")

        Returns:
            The extracted field value, or None if not found

        Example:
            extract_output_field('{"results": [{"id": 123}]}', "results.0.id")
            # Returns: 123
        """
        try:
            data = json.loads(output)
            path_parts = field_path.split(".")

            current = data
            for part in path_parts:
                if isinstance(current, dict):
                    current = current.get(part)
                elif isinstance(current, list) and part.isdigit():
                    index = int(part)
                    if 0 <= index < len(current):
                        current = current[index]
                    else:
                        return None
                else:
                    return None

                if current is None:
                    return None

            return current
        except (json.JSONDecodeError, TypeError, AttributeError):
            return None
