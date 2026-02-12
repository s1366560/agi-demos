"""
Tool conversion utilities for ReAct Agent.

Converts tool instances to ToolDefinition format used by SessionProcessor.
"""

from typing import Any, Dict, List

from .processor import ToolDefinition


def convert_tools(tools: Dict[str, Any]) -> List[ToolDefinition]:
    """
    Convert tool instances to ToolDefinition format.

    Args:
        tools: Dictionary of tool name -> tool instance

    Returns:
        List of ToolDefinition objects
    """
    definitions = []

    for name, tool in tools.items():
        # Extract tool metadata
        description = getattr(tool, "description", f"Tool: {name}")

        # Extract permission if available
        permission = getattr(tool, "permission", None)

        # Get parameters schema - prefer get_parameters_schema() method
        parameters = {"type": "object", "properties": {}, "required": []}
        if hasattr(tool, "get_parameters_schema"):
            parameters = tool.get_parameters_schema()
        elif hasattr(tool, "args_schema"):
            schema = tool.args_schema
            if hasattr(schema, "model_json_schema"):
                parameters = schema.model_json_schema()

        # Create execute wrapper with captured variables
        def make_execute_wrapper(tool_instance, tool_name):
            async def execute_wrapper(**kwargs):
                """Wrapper to execute tool."""
                try:
                    # Try different execute method names
                    if hasattr(tool_instance, "execute"):
                        result = tool_instance.execute(**kwargs)
                        # Handle both sync and async execute
                        if hasattr(result, "__await__"):
                            return await result
                        return result
                    elif hasattr(tool_instance, "ainvoke"):
                        return await tool_instance.ainvoke(kwargs)
                    elif hasattr(tool_instance, "_arun"):
                        return await tool_instance._arun(**kwargs)
                    elif hasattr(tool_instance, "_run"):
                        return tool_instance._run(**kwargs)
                    elif hasattr(tool_instance, "run"):
                        return tool_instance.run(**kwargs)
                    else:
                        raise ValueError(f"Tool {tool_name} has no execute method")
                except Exception as e:
                    return f"Error executing tool {tool_name}: {e!s}"

            return execute_wrapper

        definitions.append(
            ToolDefinition(
                name=name,
                description=description,
                parameters=parameters,
                execute=make_execute_wrapper(tool, name),
                permission=permission,
                _tool_instance=tool,
            )
        )

    return definitions
