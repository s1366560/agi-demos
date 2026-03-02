"""Structured output tool for ReAct agent.

Wraps the StructuredOutputValidator to generate LLM responses
that conform to a user-provided JSON schema. The tool dynamically
creates a Pydantic model from the schema and validates the output.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, create_model

from src.domain.llm_providers.llm_types import LLMClient, Message
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.llm.validation import (
    StructuredOutputValidator,
    ValidationConfig,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_so_llm_client: LLMClient | None = None


def configure_structured_output(llm_client: LLMClient) -> None:
    """Configure the structured output tool with an LLM client.

    Called at agent startup to inject the LLM client dependency.
    """
    global _so_llm_client
    _so_llm_client = llm_client


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

_JSON_TYPE_MAP: dict[str, type[Any]] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _json_type_to_python(json_type: str) -> type[Any]:
    """Map a JSON Schema type string to a Python type.

    Args:
        json_type: JSON Schema type (e.g. "string", "integer").

    Returns:
        Corresponding Python type. Defaults to ``Any`` for unknown types.
    """
    return _JSON_TYPE_MAP.get(json_type, Any)  # type: ignore[return-value]


def _schema_to_pydantic(
    schema: dict[str, Any],
    model_name: str = "DynamicModel",
) -> type[BaseModel]:
    """Build a Pydantic model from a JSON Schema dict.

    Only top-level ``properties`` are converted. Required fields are
    marked with ``...`` (no default); optional fields default to
    ``None``.

    Args:
        schema: JSON Schema with ``properties`` and optional
            ``required`` list.
        model_name: Name for the generated model class.

    Returns:
        A dynamically created Pydantic ``BaseModel`` subclass.
    """
    properties: dict[str, Any] = schema.get("properties", {})
    required: set[str] = set(schema.get("required", []))

    field_definitions: dict[str, Any] = {}
    for name, prop in properties.items():
        python_type = _json_type_to_python(prop.get("type", "string"))
        if name in required:
            field_definitions[name] = (python_type, ...)
        else:
            field_definitions[name] = (python_type | None, None)

    return create_model(model_name, **field_definitions)


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------


@tool_define(
    name="structured_output",
    description=(
        "Generate structured data from the LLM that conforms to a "
        "given JSON schema. Use this when you need the model to "
        "return data in a specific format (e.g. extracting entities, "
        "filling a form, producing structured analysis). "
        "Input: prompt (string), schema (JSON Schema object). "
        "Optional: data (string context), max_retries (int, default 3)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Instruction for the LLM.",
            },
            "schema": {
                "type": "object",
                "description": (
                    "JSON Schema describing the expected output (must contain 'properties')."
                ),
            },
            "data": {
                "type": "string",
                "description": ("Optional context data to include in the prompt."),
            },
            "max_retries": {
                "type": "integer",
                "description": ("Maximum validation retries (default 3, max 5)."),
                "default": 3,
            },
        },
        "required": ["prompt", "schema"],
    },
    permission=None,
    category="llm",
    tags=frozenset({"llm", "structured", "validation"}),
)
async def structured_output_tool(
    ctx: ToolContext,
    *,
    prompt: str,
    schema: dict[str, Any],
    data: str = "",
    max_retries: int = 3,
) -> ToolResult:
    """Generate validated structured output from the LLM."""
    if _so_llm_client is None:
        return ToolResult(
            output=(
                "Error: structured_output tool is not configured. "
                "Call configure_structured_output() first."
            ),
            is_error=True,
        )

    max_retries = min(max(max_retries, 0), 5)

    try:
        response_model = _schema_to_pydantic(schema)
    except Exception as exc:
        return ToolResult(
            output=f"Error: failed to build model from schema: {exc}",
            is_error=True,
        )

    user_content = prompt
    if data:
        user_content = f"{prompt}\n\nData:\n{data}"

    messages: list[Message] = [
        Message.system(
            "You are a structured data extraction assistant. "
            + "Always respond with valid JSON matching the schema."
        ),
        Message.user(user_content),
    ]

    config = ValidationConfig(max_retries=max_retries)
    validator = StructuredOutputValidator(config=config)

    try:
        result = await validator.generate_validated(
            llm_client=_so_llm_client,
            messages=messages,
            response_model=response_model,
        )
    except Exception as exc:
        logger.exception(
            "Unexpected error in structured_output: %s",
            exc,
        )
        return ToolResult(
            output=f"Error: unexpected failure: {exc}",
            is_error=True,
        )

    if result.success and result.data is not None:
        return ToolResult(
            output=json.dumps(result.data, indent=2, ensure_ascii=False),
            title="Structured output",
            metadata={
                "attempts": result.attempts,
                "schema_keys": list(schema.get("properties", {}).keys()),
            },
        )

    return ToolResult(
        output=f"Error: validation failed after {result.attempts} attempt(s): {result.error}",
        is_error=True,
        metadata={"attempts": result.attempts},
    )
