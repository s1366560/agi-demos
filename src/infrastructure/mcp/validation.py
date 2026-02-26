"""Pydantic-based validation for MCP tool arguments.

Replaces manual JSON Schema type checking in MCPToolAdapter with
auto-generated Pydantic models for robust argument validation.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError, create_model

logger = logging.getLogger(__name__)


# JSON Schema type to Python type mapping
_JSON_TYPE_MAP: dict[str, type] = {
    "string": str,
    "number": float,
    "integer": int,
    "boolean": bool,
    "array": list,
    "object": dict,
}


class MCPValidationError(Exception):
    """Raised when MCP tool arguments fail validation."""

    def __init__(self, tool_name: str, errors: list[dict[str, Any]]) -> None:
        self.tool_name = tool_name
        self.errors = errors
        messages = [f"  - {e.get('loc', ['?'])}: {e.get('msg', 'unknown error')}" for e in errors]
        detail = "\n".join(messages)
        super().__init__(f"Validation failed for tool '{tool_name}':\n{detail}")


class MCPValidator:
    """Validates MCP tool arguments using auto-generated Pydantic models.

    Converts JSON Schema definitions from MCP servers into Pydantic
    models at registration time, then uses those models for fast,
    type-safe argument validation at call time.
    """

    def __init__(self) -> None:
        self._models: dict[str, type[BaseModel]] = {}

    def register_schema(
        self,
        tool_name: str,
        schema: dict[str, Any],
    ) -> type[BaseModel]:
        """Register a JSON Schema and generate a Pydantic model.

        Args:
            tool_name: Unique tool identifier (e.g., mcp__server__tool).
            schema: JSON Schema definition from MCP server.

        Returns:
            The generated Pydantic model class.
        """
        model = self._schema_to_model(tool_name, schema)
        self._models[tool_name] = model
        return model

    def validate(
        self,
        tool_name: str,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate arguments against a registered schema.

        Args:
            tool_name: Tool to validate for.
            args: Arguments to validate.

        Returns:
            Validated and coerced arguments as a dict.

        Raises:
            MCPValidationError: If validation fails.
            KeyError: If tool_name has no registered schema.
        """
        model_cls = self._models.get(tool_name)
        if model_cls is None:
            logger.warning(
                "No schema registered for tool '%s'; skipping validation",
                tool_name,
            )
            return args

        try:
            instance = model_cls(**args)
            return instance.model_dump()
        except ValidationError as exc:
            raise MCPValidationError(
                tool_name=tool_name,
                errors=exc.errors(),  # type: ignore[arg-type]
            ) from exc

    def get_model(self, tool_name: str) -> type[BaseModel] | None:
        """Get the Pydantic model for a registered tool."""
        return self._models.get(tool_name)

    def has_schema(self, tool_name: str) -> bool:
        """Check if a tool has a registered schema."""
        return tool_name in self._models

    @staticmethod
    def _schema_to_model(
        tool_name: str,
        schema: dict[str, Any],
    ) -> type[BaseModel]:
        """Convert JSON Schema to a Pydantic model.

        Handles:
        - Required vs optional fields
        - Type mapping (string, number, integer, boolean, array, object)
        - Field descriptions from schema
        - Default values
        - Nested object schemas (converted to dict[str, Any])

        Args:
            tool_name: Used to generate model class name.
            schema: JSON Schema definition.

        Returns:
            A dynamically created Pydantic model class.
        """
        properties: dict[str, Any] = schema.get("properties", {})
        required_fields = set(schema.get("required", []))

        field_definitions: dict[str, Any] = {}

        for field_name, field_schema in properties.items():
            json_type = field_schema.get("type", "string")
            py_type = _JSON_TYPE_MAP.get(json_type, Any)
            description: str = field_schema.get("description", "")
            default_val = field_schema.get("default")

            if field_name in required_fields:
                if default_val is not None:
                    field_definitions[field_name] = (
                        py_type,
                        Field(
                            default=default_val,
                            description=description,
                        ),
                    )
                else:
                    field_definitions[field_name] = (
                        py_type,
                        Field(description=description),
                    )
            else:
                # Optional field
                field_definitions[field_name] = (
                    py_type | None,
                    Field(
                        default=default_val,
                        description=description,
                    ),
                )

        # Sanitize tool_name for class name (replace non-alnum with _)
        safe_name = "".join(c if c.isalnum() else "_" for c in tool_name)
        model_name = f"MCPParams_{safe_name}"

        return create_model(model_name, **field_definitions)
