"""AgentTool abstract base class - Domain layer interface.

.. deprecated::
    This module is deprecated. Use the ``@tool_define`` decorator from
    ``src.infrastructure.agent.tools.define`` to create new tools instead.
    Existing class-based tools will be removed in a future release.

This module defines the abstract base class for agent tools.
Application-layer use cases depend on this interface rather than
infrastructure implementations.

The infrastructure AgentTool class extends this base and adds
implementation details (truncation, composition logic).
"""

import contextlib
import json
import logging
import warnings
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class AgentToolBase(ABC):
    """Abstract base class for agent tools (domain layer).

    .. deprecated::
        Subclass ``AgentToolBase`` is deprecated. Use the ``@tool_define``
        decorator to create new tools. See ``skill_tool.py`` for an example.

    All tools used by the ReAct agent must inherit from this class
    and implement the required methods.

    Tool Composition Support:
    - Tools can declare their output schema for composition
    - Tools can check compatibility with other tools
    - Tools can transform their output for input to another tool
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        warnings.warn(
            f"{cls.__qualname__} inherits from AgentToolBase which is deprecated. "
            "Use the @tool_define decorator instead. "
            "See src/infrastructure/agent/tools/define.py for details.",
            DeprecationWarning,
            stacklevel=2,
        )

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
    async def execute(self, **kwargs: Any) -> str:
        """Execute the tool with the given arguments.

        Args:
            **kwargs: Tool-specific arguments

        Returns:
            String result of the tool execution

        Raises:
            Exception: If tool execution fails
        """
        ...

    def validate_args(self, **kwargs: Any) -> bool:
        """Validate tool arguments before execution.

        Default implementation always returns True.
        Override for custom validation logic.
        """
        return True

    async def safe_execute(self, **kwargs: Any) -> str:
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

    def get_output_schema(self) -> dict[str, Any]:
        """Get the output schema of this tool for composition."""
        return {"type": "string", "description": f"Output from {self.name} tool"}

    def can_compose_with(self, other_tool: "AgentToolBase") -> bool:
        """Check if this tool's output can be used as input for another tool."""
        return True

    def compose_output(
        self,
        output: str,
        target_tool: "AgentToolBase",
        transformation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Transform this tool's output for use as input to another tool."""
        try:
            parsed = json.loads(output)
        except (json.JSONDecodeError, TypeError):
            parsed = {"raw_output": output}

        if transformation:
            parsed = self._apply_transformations(parsed, output, transformation)

        if not isinstance(parsed, dict):
            return {"data": parsed}
        return parsed

    def _apply_transformations(
        self,
        parsed: Any,
        raw_output: str,
        transformation: dict[str, Any],
    ) -> Any:
        """Apply transformation rules to parsed output."""
        if "extract_path" in transformation:
            extracted = self.extract_output_field(raw_output, transformation["extract_path"])
            parsed = extracted if extracted is not None else parsed

        if "field_mapping" in transformation and isinstance(parsed, dict):
            parsed = self._apply_field_mapping(parsed, transformation["field_mapping"])

        if "filter" in transformation and isinstance(parsed, list):
            parsed = self._apply_filter(parsed, transformation["filter"])

        if "aggregate" in transformation and isinstance(parsed, list):
            parsed = self._apply_aggregate(parsed, transformation["aggregate"])

        return parsed

    @staticmethod
    def _apply_field_mapping(parsed: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
        """Apply field mapping transformation."""
        mapped = {}
        for source_key, target_key in mapping.items():
            if source_key in parsed:
                mapped[target_key] = parsed[source_key]
        return mapped if mapped else parsed

    @staticmethod
    def _apply_filter(parsed: list[Any], filter_rules: dict[str, Any]) -> list[Any]:
        """Apply filter transformation to a list."""
        return [
            item
            for item in parsed
            if isinstance(item, dict) and all(item.get(k) == v for k, v in filter_rules.items())
        ]

    @staticmethod
    def _apply_aggregate(parsed: list[Any], agg_type: str) -> Any:
        """Apply aggregate transformation to a list."""
        if agg_type == "count":
            return {"count": len(parsed)}
        if agg_type == "first" and parsed:
            return parsed[0]
        if agg_type == "last" and parsed:
            return parsed[-1]
        if agg_type == "sum":
            with contextlib.suppress(TypeError, ValueError):
                return {"sum": sum(parsed)}
        return parsed

    def get_input_schema(self) -> dict[str, Any]:
        """Get the input schema of this tool (helper for composition)."""
        return {"type": "object", "description": f"Input for {self.name} tool"}

    def get_parameters_schema(self) -> dict[str, Any]:
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
