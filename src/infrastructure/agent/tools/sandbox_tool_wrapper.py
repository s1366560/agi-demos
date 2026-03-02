"""Sandbox MCP Tool Wrapper.

Wraps MCP tools from a sandbox instance as Agent tools with namespacing.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.domain.ports.services.sandbox_port import SandboxPort
    from src.infrastructure.agent.tools.define import ToolInfo


from src.infrastructure.agent.permission.rules import classify_sandbox_tool_permission
from src.infrastructure.agent.tools.mcp_errors import (
    MCPToolError,
    MCPToolErrorClassifier,
    RetryConfig,
)

logger = logging.getLogger(__name__)



def _convert_mcp_schema(input_schema: dict[str, Any]) -> dict[str, Any]:
    """Convert MCP input_schema to agent tool JSON Schema format.

    Preserves the full JSON Schema structure including nested
    ``items`` for arrays and ``properties`` for objects so the LLM
    can generate correctly-shaped arguments (e.g. ``batch_edit``'s
    ``edits`` array of objects).

    Args:
        input_schema: Raw MCP tool input schema.

    Returns:
        Normalised JSON Schema dict with type/properties/required.
    """
    # The MCP input_schema is already valid JSON Schema.  We only
    # normalise top-level keys so the caller always sees a consistent
    # shape.  Critically, we preserve nested "items", "enum",
    # "properties", "required", "anyOf", etc. that previous code
    # was dropping.
    return {
        "type": input_schema.get("type", "object"),
        "properties": input_schema.get("properties", {}),
        "required": input_schema.get("required", []),
    }


def _extract_error_msg(result: dict[str, Any]) -> str:
    """Extract error message from an MCP error result.

    Args:
        result: The MCP result dict with is_error/isError flag set.

    Returns:
        The extracted error message string.
    """
    content_list = result.get("content", [])

    if content_list and len(content_list) > 0:
        first_content = content_list[0]
        if isinstance(first_content, dict):
            error_msg = first_content.get("text", "")
        else:
            error_msg = str(first_content)
    else:
        error_msg = ""

    if not error_msg:
        error_msg = (
            f"Tool execution failed (no details provided). Raw result: {result}"
        )

    return str(error_msg)


def _extract_ok_output(result: dict[str, Any]) -> str:
    """Extract output string from a successful MCP result.

    Args:
        result: The MCP result dict (no error flag set).

    Returns:
        String representation of the result.
    """
    artifact = result.get("artifact")
    content_list = result.get("content", [])

    if artifact:
        filename = artifact.get("filename", "unknown")
        mime_type = artifact.get("mime_type", "unknown")
        size = artifact.get("size", 0)
        category = artifact.get("category", "file")
        return (
            f"Exported artifact: {filename} "
            f"({mime_type}, {size} bytes, category: {category})"
        )

    if content_list and len(content_list) > 0:
        return str(content_list[0].get("text", ""))

    return "Success"


async def _execute_with_retry(
    sandbox_id: str,
    tool_name: str,
    sandbox_port: SandboxPort,
    retry_config: RetryConfig,
    kwargs: dict[str, Any],
) -> str:
    """Execute a sandbox MCP tool call with error classification and retry.

    Args:
        sandbox_id: The sandbox instance ID.
        tool_name: Original MCP tool name.
        sandbox_port: SandboxPort for routing calls.
        retry_config: Retry configuration.
        kwargs: Tool arguments.

    Returns:
        String result from the tool execution.

    Raises:
        RuntimeError: When execution fails after all retries.
    """
    import time as _time

    last_error: MCPToolError | None = None
    tool_timeout = kwargs.get("timeout")
    configured_timeout_s: float | None = (
        float(tool_timeout)
        if tool_timeout and isinstance(tool_timeout, (int, float))
        else None
    )

    for attempt in range(retry_config.max_retries + 1):
        start_time = _time.time()
        try:
            call_kwargs: dict[str, Any] = {}
            if configured_timeout_s is not None:
                call_kwargs["timeout"] = configured_timeout_s + 30.0

            result = await sandbox_port.call_tool(
                sandbox_id, tool_name, kwargs, **call_kwargs,
            )
            elapsed_ms = int((_time.time() - start_time) * 1000)

            if result.get("is_error") or result.get("isError"):
                error_msg = _extract_error_msg(result)
                mcp_err = MCPToolErrorClassifier.classify(
                    error=Exception(error_msg),
                    tool_name=tool_name,
                    sandbox_id=sandbox_id,
                    context={
                        "kwargs": kwargs,
                        "attempt": attempt,
                        "execution_duration_ms": elapsed_ms,
                        "configured_timeout_s": configured_timeout_s,
                    },
                )
                mcp_err.retry_count = attempt
                last_error = mcp_err

                if (
                    mcp_err.is_retryable
                    and attempt < retry_config.max_retries
                ):
                    await asyncio.sleep(retry_config.get_delay(attempt))
                    continue
                break

            return _extract_ok_output(result)

        except Exception as exc:
            elapsed_ms = int((_time.time() - start_time) * 1000)
            mcp_err = MCPToolErrorClassifier.classify(
                error=exc,
                tool_name=tool_name,
                sandbox_id=sandbox_id,
                context={
                    "kwargs": kwargs,
                    "attempt": attempt,
                    "execution_duration_ms": elapsed_ms,
                    "configured_timeout_s": configured_timeout_s,
                },
            )
            mcp_err.retry_count = attempt

            if (
                mcp_err.is_retryable
                and attempt < retry_config.max_retries
            ):
                await asyncio.sleep(retry_config.get_delay(attempt))
                last_error = mcp_err
                continue

            raise RuntimeError(
                f"Tool execution failed: {mcp_err.get_user_message()}"
            ) from exc

    if last_error:
        raise RuntimeError(
            f"Tool execution failed after {last_error.retry_count + 1} "
            f"attempts: {last_error.get_user_message()}"
        )
    raise RuntimeError("Tool execution failed: Unknown error")


def create_sandbox_mcp_tool(
    sandbox_id: str,
    tool_name: str,
    tool_schema: dict[str, Any],
    sandbox_port: SandboxPort,
    retry_config: RetryConfig | None = None,
) -> ToolInfo:
    """Create a ToolInfo for a sandbox MCP tool.

    This is the ``@tool_define`` migration equivalent of
    :class:`SandboxMCPToolWrapper`. Each sandbox tool has a unique
    name/description/parameters so we build :class:`ToolInfo` directly
    rather than using the ``@tool_define`` decorator.

    Args:
        sandbox_id: The sandbox instance ID.
        tool_name: Original MCP tool name (e.g. ``bash``, ``file_read``).
        tool_schema: MCP tool schema dict (name, description, input_schema).
        sandbox_port: SandboxPort instance for routing calls.
        retry_config: Optional retry configuration for transient errors.

    Returns:
        A :class:`ToolInfo` instance representing this sandbox tool.
    """
    from src.infrastructure.agent.tools.context import ToolContext
    from src.infrastructure.agent.tools.define import ToolInfo
    from src.infrastructure.agent.tools.result import ToolResult

    cfg = retry_config or RetryConfig()
    description = tool_schema.get("description", f"{tool_name} tool")
    parameters = _convert_mcp_schema(tool_schema.get("input_schema", {}))
    permission = classify_sandbox_tool_permission(tool_name)

    async def execute(ctx: ToolContext, **kwargs: Any) -> ToolResult:
        """Execute the sandbox MCP tool with retry logic."""
        _ = ctx  # Context available but not used by MCP tool calls
        try:
            output = await _execute_with_retry(
                sandbox_id=sandbox_id,
                tool_name=tool_name,
                sandbox_port=sandbox_port,
                retry_config=cfg,
                kwargs=kwargs,
            )
            return ToolResult(output=output)
        except RuntimeError as exc:
            return ToolResult(output=str(exc), is_error=True)

    return ToolInfo(
        name=tool_name,
        description=description,
        parameters=parameters,
        execute=execute,
        permission=permission,
        category="mcp",
        tags=frozenset({"mcp", "sandbox"}),
    )
