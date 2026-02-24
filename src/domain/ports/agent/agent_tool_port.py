"""AgentTool abstract base class - Domain layer interface.

This module defines the abstract base class for agent tools.
Application-layer use cases depend on this interface rather than
infrastructure implementations.

The infrastructure AgentTool class extends this base and adds
implementation details (truncation, composition logic).
"""

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class AgentToolBase(ABC):
    """Abstract base class for agent tools (domain layer).

    All tools used by the ReAct agent must inherit from this class
    and implement the required methods.

    Tool Composition Support:
    - Tools can declare their output schema for composition
    - Tools can check compatibility with other tools
    - Tools can transform their output for input to another tool
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Get the tool name."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Get the tool description."""
        ...

    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:  # noqa: ANN401
        """Execute the tool with the given arguments.

        Args:
            **kwargs: Tool-specific arguments

        Returns:
            String result of the tool execution

        Raises:
            Exception: If tool execution fails
        """
        ...

    def validate_args(self, **kwargs: Any) -> bool:  # noqa: ANN401
        """Validate tool arguments before execution.

        Default implementation always returns True.
        Override for custom validation logic.
        """
        return True

    async def safe_execute(self, **kwargs: Any) -> str:  # noqa: ANN401
        """Safely execute the tool with error handling."""
        try:
            if not self.validate_args(**kwargs):
                return f"Error: Invalid arguments for tool {self.name}"

            logger.info(f"Executing tool: {self.name} with args: {kwargs}")
            result = await self.execute(**kwargs)
            logger.info(f"Tool {self.name} completed successfully")
            return result

        except Exception as e:
            error_msg = f"Error executing tool {self.name}: {e}"
            logger.error(error_msg)
            return error_msg

    def get_output_schema(self) -> Dict[str, Any]:
        """Get the output schema of this tool for composition."""
        return {"type": "string", "description": f"Output from {self.name} tool"}

    def can_compose_with(self, other_tool: "AgentToolBase") -> bool:
        """Check if this tool's output can be used as input for another tool."""
        return True

    def compose_output(
        self,
        output: str,
        target_tool: "AgentToolBase",
        transformation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Transform this tool's output for use as input to another tool."""
        try:
            parsed = json.loads(output)
        except (json.JSONDecodeError, TypeError):
            parsed = {"raw_output": output}

        if transformation:
            if "extract_path" in transformation:
                path = transformation["extract_path"]
                extracted = self.extract_output_field(output, path)
                parsed = extracted if extracted is not None else parsed

            if "field_mapping" in transformation and isinstance(parsed, dict):
                mapping = transformation["field_mapping"]
                mapped = {}
                for source_key, target_key in mapping.items():
                    if source_key in parsed:
                        mapped[target_key] = parsed[source_key]
                parsed = mapped if mapped else parsed

            if "filter" in transformation and isinstance(parsed, list):
                filter_rules = transformation["filter"]
                filtered = []
                for item in parsed:
                    if isinstance(item, dict):
                        matches = all(item.get(k) == v for k, v in filter_rules.items())
                        if matches:
                            filtered.append(item)
                parsed = filtered

            if "aggregate" in transformation and isinstance(parsed, list):
                agg_type = transformation["aggregate"]
                if agg_type == "count":
                    parsed = {"count": len(parsed)}
                elif agg_type == "first" and parsed:
                    parsed = parsed[0]
                elif agg_type == "last" and parsed:
                    parsed = parsed[-1]
                elif agg_type == "sum":
                    try:
                        parsed = {"sum": sum(parsed)}
                    except (TypeError, ValueError):
                        pass

        if not isinstance(parsed, dict):
            return {"data": parsed}

        return parsed

    def get_input_schema(self) -> Dict[str, Any]:
        """Get the input schema of this tool (helper for composition)."""
        return {"type": "object", "description": f"Input for {self.name} tool"}

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Get the parameters schema for LLM function calling."""
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    def extract_output_field(self, output: str, field_path: str) -> Any:
        """Extract a specific field from tool output using a dot-separated path."""
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
