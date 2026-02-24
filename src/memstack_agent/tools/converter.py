"""Tool conversion utilities for memstack-agent.

Provides functions to convert Python callables to Tool definitions:
- function_to_tool: Convert any callable to a ToolDefinition
- infer_type_schema: Infer JSON Schema from Python type hints

Supports:
- Regular functions (sync/async)
- Lambda functions
- Methods with type hints
- Dataclass/Pydantic models as parameters

Reference: OpenAI's function_to_schema in src/infrastructure/agent/tools
"""

import inspect
from dataclasses import is_dataclass
from functools import partial
from typing import Any, Callable, Dict, List, Optional, Union, get_args, get_origin

from memstack_agent.tools.protocol import ToolDefinition, ToolMetadata

# Type mapping for JSON Schema
_TYPE_MAPPING: Dict[type, Dict[str, Any]] = {
    str: {"type": "string"},
    int: {"type": "integer"},
    float: {"type": "number"},
    bool: {"type": "boolean"},
}


def infer_type_schema(type_hint: Any) -> Dict[str, Any]:
    """Infer JSON Schema from a Python type hint.

    Supports:
    - Primitives: str, int, float, bool
    - Optional[T]: {"type": T, "nullable": true}
    - List[T]: {"type": "array", "items": T}
    - Dict[str, T]: {"type": "object", "additionalProperties": T}
    - Union types: {"anyOf": [...]}
    - Dataclass fields: Extract each field

    Args:
        type_hint: Python type hint from typing module

    Returns:
        JSON Schema dictionary for type
    """
    # Handle dataclass types
    if is_dataclass(type_hint):
        return _infer_dataclass_schema(type_hint)

    origin = get_origin(type_hint)

    # Handle Optional[T] (Union[T, None])
    if origin is Union:
        args = get_args(type_hint)

        non_none_args = [a for a in args if a is not type(None)]
        if len(non_none_args) == 1:
            # Optional[T] -> Union[T, None]
            schema = infer_type_schema(non_none_args[0])
            schema["nullable"] = True
            return schema
        # Multi-type Union -> anyOf
        return {"anyOf": [infer_type_schema(a) for a in args]}

    # Handle List[T]
    if origin is list or origin is List:
        if hasattr(type_hint, "__args__"):
            # Get generic type from List[T]
            args = get_args(type_hint)
            return {
                "type": "array",
                "items": infer_type_schema(args[0]) if args else str,
            }
        # Fallback for list-like types
        return {"type": "array"}

    # Handle Dict[str, T]
    if origin is dict or origin is Dict:
        if hasattr(type_hint, "__args__"):
            # Get generic type from Dict[str, T]
            args = get_args(type_hint)
            if args and len(args) >= 2:
                key_type, value_type = args
                return {
                    "type": "object",
                    "additionalProperties": infer_type_schema(value_type),
                }
        # Fallback
        return {"type": "object"}

    # Check for direct type mapping
    if type_hint in _TYPE_MAPPING:
        return _TYPE_MAPPING[type_hint].copy()

    # Fallback: treat as string
    return {"type": "string"}


def _parse_param_docstring(docstring: str) -> Dict[str, str]:
    """Parse parameter descriptions from docstring.

    Supports Google and Sphinx style docstrings:

    Args:
        docstring: The function's docstring

    Returns:
        Dict mapping param names to descriptions
    """
    result = {}
    if not docstring:
        return result

    lines = docstring.strip().split("\n")
    in_args = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("Args:") or stripped.startswith("Parameters:"):
            in_args = True
        elif stripped.startswith("Returns:"):
            break

        if in_args:
            # Look for pattern: "param_name: description"
            if ":" in stripped:
                parts = stripped.split(":", 1)
                if len(parts) == 2:
                    name = parts[0].strip()
                    desc = parts[1].strip()
                    if name and not name.startswith('"'):
                        result[name] = desc

            # Stop at new section
            elif stripped and not stripped[0].islower():
                break

    return result


def _infer_dataclass_schema(dataclass_type: Any) -> Dict[str, Any]:
    """Infer JSON Schema from a dataclass type.

    Args:
        dataclass_type: A dataclass type

    Returns:
        JSON Schema dictionary for the dataclass
    """
    from dataclasses import MISSING, fields

    properties = {}
    required = []

    for field in fields(dataclass_type):
        # Infer schema for field type
        field_schema = infer_type_schema(field.type)
        properties[field.name] = field_schema

        # Check if required (no default value)
        if field.default is MISSING and field.default_factory is MISSING:
            required.append(field.name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


def _build_function_schema(func: Callable) -> Dict[str, Any]:
    """Build JSON Schema from function signature.

    Args:
        func: Function to analyze

    Returns:
        JSON Schema for function parameters
    """
    sig = inspect.signature(func)
    properties = {}
    required = []

    # Parse docstring for parameter descriptions
    param_descriptions = _parse_param_docstring(func.__doc__ or "")

    for param_name, param in sig.parameters.items():
        # Skip self parameter
        if param_name == "self":
            continue

        # Infer type schema
        param_schema = infer_type_schema(param.annotation)
        properties[param_name] = param_schema

        # Add description from docstring if available
        if param_name in param_descriptions:
            properties[param_name]["description"] = param_descriptions[param_name]
        else:
            properties[param_name]["description"] = f"Parameter {param_name}"

        # Check if required (no default value)
        if param.default is param.empty:
            required.append(param_name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


async def _execute_wrapped(func: Callable, /, **kwargs: Any) -> Any:  # noqa: ANN401
    """Wrapper to execute sync/async functions uniformly.

    Args:
        func: The function to execute
        **kwargs: Arguments to pass

    Returns:
        Function result

    Raises:
        Exception: If function execution fails
    """
    result = func(**kwargs)
    if inspect.iscoroutine(result):
        return await result
    return result


def function_to_tool(
    func: Callable,
    name: Optional[str] = None,
    description: Optional[str] = None,
    metadata: Optional[ToolMetadata] = None,
) -> ToolDefinition:
    """Convert a Python callable to a ToolDefinition.

    This enables quick tool creation from regular functions:

        @function_to_tool
        async def search_web(query: str) -> str:
            '''Search the web for information.

            Args:
                query: The search query
            '''
            return f"Results for: {query}"

    Or explicit:

        tool = function_to_tool(
            my_search,
            name="web_search",
            description="Search web",
        )

    Args:
        func: The function to convert
        name: Optional tool name (defaults to function name)
        description: Optional tool description (defaults to docstring)
        metadata: Optional tool metadata

    Returns:
        ToolDefinition wrapping function
    """
    # Build parameters schema from function signature
    parameters = _build_function_schema(func)

    # Get name and description
    tool_name = name or func.__name__
    tool_desc = description or func.__doc__

    # Create execute wrapper
    execute_wrapper = partial(_execute_wrapped, func)

    # Create definition
    return ToolDefinition(
        name=tool_name,
        description=tool_desc,
        parameters=parameters,
        execute=execute_wrapper,
        metadata=metadata or ToolMetadata(),
        _tool_instance=func,
    )


__all__ = [
    "infer_type_schema",
    "function_to_tool",
]
