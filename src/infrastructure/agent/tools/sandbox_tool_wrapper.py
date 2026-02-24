"""Sandbox MCP Tool Wrapper.

Wraps MCP tools from a sandbox instance as Agent tools with namespacing.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.domain.ports.services.sandbox_port import SandboxPort


from src.infrastructure.agent.permission.rules import classify_sandbox_tool_permission
from src.infrastructure.agent.tools.base import AgentTool
from src.infrastructure.agent.tools.mcp_errors import (
    MCPToolError,
    MCPToolErrorClassifier,
    RetryConfig,
)

logger = logging.getLogger(__name__)


class SandboxMCPToolWrapper(AgentTool):
    """
    Wrapper for Sandbox MCP tools to be used by ReActAgent.

    Tools are registered with their original names (e.g., "bash", "file_read").
    The sandbox_id is stored as an attribute for routing and context.

    The wrapper routes tool execution calls to the correct sandbox instance
    with automatic error classification and retry logic.
    """

    def __init__(
        self,
        sandbox_id: str,
        tool_name: str,
        tool_schema: dict[str, Any],
        sandbox_adapter: SandboxPort,
        retry_config: RetryConfig | None = None,
    ) -> None:
        """
        Initialize the wrapper.

        Args:
            sandbox_id: The sandbox instance ID
            tool_name: Original MCP tool name (e.g., "bash", "file_read")
            tool_schema: MCP tool schema with name, description, input_schema
            sandbox_adapter: MCPSandboxAdapter instance for routing calls
            retry_config: Optional retry configuration for transient errors
        """
        self.sandbox_id = sandbox_id
        self.tool_name = tool_name
        self._adapter = sandbox_adapter
        self._schema = tool_schema
        self._retry_config = retry_config or RetryConfig()

        # Use original tool name directly (no prefix)
        base_description = tool_schema.get("description", f"{tool_name} tool")
        description = base_description  # Remove sandbox context from description

        # Determine permission type based on tool name
        self.permission = classify_sandbox_tool_permission(tool_name)

        super().__init__(
            name=tool_name,
            description=description,
        )

        logger.debug(
            f"SandboxMCPToolWrapper: Created wrapper for sandbox={sandbox_id}, "
            f"tool={tool_name}, permission={self.permission}"
        )

    def get_parameters_schema(self) -> dict[str, Any]:
        """Get parameters schema from MCP tool schema."""
        input_schema = self._schema.get("input_schema", {})

        # Convert MCP schema format to Agent tool schema format
        properties = {}
        required = []

        if isinstance(input_schema, dict):
            # Handle JSON Schema format
            schema_props = input_schema.get("properties", {})
            for prop_name, prop_def in schema_props.items():
                properties[prop_name] = {
                    "type": prop_def.get("type", "string"),
                    "description": prop_def.get("description", ""),
                }
                if "default" in prop_def:
                    properties[prop_name]["default"] = prop_def["default"]

            required = input_schema.get("required", [])

        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }

    def validate_args(self, **kwargs: Any) -> bool:
        """Validate arguments against the MCP tool schema."""
        input_schema = self._schema.get("input_schema", {})

        if not isinstance(input_schema, dict):
            return True

        required = input_schema.get("required", [])
        return all(arg in kwargs for arg in required)

    async def execute(self, **kwargs: Any) -> Any:
        """
        Execute the tool with automatic error handling and retry.

        Args:
            **kwargs: Tool arguments as defined in input_schema

        Returns:
            String result for regular tools, or dict with artifact data for export_artifact
        """
        import time

        last_error: MCPToolError | None = None
        configured_timeout_s: float | None = None

        # Extract configured timeout from tool arguments for duration-aware classification
        tool_timeout = kwargs.get("timeout")
        if tool_timeout and isinstance(tool_timeout, (int, float)):
            configured_timeout_s = float(tool_timeout)

        for attempt in range(self._retry_config.max_retries + 1):
            start_time = time.time()
            try:
                logger.debug(
                    f"SandboxMCPToolWrapper: Executing {self.name} "
                    f"(sandbox={self.sandbox_id}, tool={self.tool_name}, "
                    f"attempt={attempt + 1}/{self._retry_config.max_retries + 1})"
                )

                # Route to sandbox adapter's call_tool method
                # Extract timeout from tool arguments (e.g., bash tool's timeout param)
                # and use it as MCP request timeout with padding for overhead
                call_kwargs: dict[str, Any] = {}
                if configured_timeout_s is not None:
                    call_kwargs["timeout"] = configured_timeout_s + 30.0

                start_time = time.time()
                result = await self._adapter.call_tool(
                    self.sandbox_id,
                    self.tool_name,
                    kwargs,
                    **call_kwargs,
                )
                elapsed_ms = int((time.time() - start_time) * 1000)

                # Parse result - check both is_error (client normalized) and isError (MCP standard)
                if result.get("is_error") or result.get("isError"):
                    content_list = result.get("content", [])

                    # Extract error message with better fallback
                    if content_list and len(content_list) > 0:
                        first_content = content_list[0]
                        if isinstance(first_content, dict):
                            error_msg = first_content.get("text", "")
                        else:
                            error_msg = str(first_content)
                    else:
                        error_msg = ""

                    # If still no error message, provide debugging info
                    if not error_msg:
                        logger.warning(
                            f"SandboxMCPToolWrapper: Tool returned is_error=True but no error "
                            f"message. Full result: {result}"
                        )
                        error_msg = (
                            f"Tool execution failed (no details provided). Raw result: {result}"
                        )

                    # Create error from tool result with duration context
                    error = Exception(error_msg)
                    mcp_error = MCPToolErrorClassifier.classify(
                        error=error,
                        tool_name=self.tool_name,
                        sandbox_id=self.sandbox_id,
                        context={
                            "kwargs": kwargs,
                            "attempt": attempt,
                            "execution_duration_ms": elapsed_ms,
                            "configured_timeout_s": configured_timeout_s,
                        },
                    )
                    mcp_error.retry_count = attempt

                    logger.debug(
                        f"SandboxMCPToolWrapper: Error classified as {mcp_error.error_type.value} "
                        f"(duration={elapsed_ms}ms, timeout={configured_timeout_s}s)"
                    )

                    # Check if retryable
                    if mcp_error.is_retryable and attempt < self._retry_config.max_retries:
                        logger.warning(
                            f"SandboxMCPToolWrapper: Retryable error (attempt {attempt + 1}): "
                            f"{mcp_error.error_type.value} - {mcp_error.message}"
                        )
                        last_error = mcp_error
                        delay = self._retry_config.get_delay(attempt)
                        await asyncio.sleep(delay)
                        continue

                    # Not retryable or max retries reached - store error and break
                    last_error = mcp_error
                    break

                # Success - check if this is an artifact result (for export_artifact tool)
                artifact = result.get("artifact")
                content_list = result.get("content", [])

                if artifact:
                    # Build a text summary for LLM context (avoid base64 in context)
                    filename = artifact.get("filename", "unknown")
                    mime_type = artifact.get("mime_type", "unknown")
                    size = artifact.get("size", 0)
                    category = artifact.get("category", "file")
                    output_summary = (
                        f"Exported artifact: {filename} "
                        f"({mime_type}, {size} bytes, category: {category})"
                    )
                    # Return full result dict for artifact processing in processor
                    # "output" key ensures processor uses the summary, not json.dumps()
                    return {
                        "output": output_summary,
                        "content": content_list,
                        "artifact": artifact,
                    }

                # Regular tool - extract text output
                if content_list and len(content_list) > 0:
                    return content_list[0].get("text", "")

                return "Success"

            except Exception as e:
                elapsed_ms = int((time.time() - start_time) * 1000)
                # Classify the exception with duration context
                mcp_error = MCPToolErrorClassifier.classify(
                    error=e,
                    tool_name=self.tool_name,
                    sandbox_id=self.sandbox_id,
                    context={
                        "kwargs": kwargs,
                        "attempt": attempt,
                        "execution_duration_ms": elapsed_ms,
                        "configured_timeout_s": configured_timeout_s,
                    },
                )
                mcp_error.retry_count = attempt
                last_error = mcp_error

                # Log the error
                logger.error(
                    f"SandboxMCPToolWrapper: Exception during execution: "
                    f"{mcp_error.error_type.value} - {mcp_error.message} "
                    f"(duration={elapsed_ms}ms, timeout={configured_timeout_s}s)"
                )

                # Check if retryable
                if mcp_error.is_retryable and attempt < self._retry_config.max_retries:
                    delay = self._retry_config.get_delay(attempt)
                    logger.info(
                        f"SandboxMCPToolWrapper: Retrying after {delay:.2f}s "
                        f"(attempt {attempt + 2}/{self._retry_config.max_retries + 1})"
                    )
                    await asyncio.sleep(delay)
                    continue

                # Not retryable or max retries reached - raise exception for processor to catch
                raise RuntimeError(f"Tool execution failed: {mcp_error.get_user_message()}") from e

        # All retries exhausted - raise exception for processor to catch
        if last_error:
            raise RuntimeError(
                f"Tool execution failed after {last_error.retry_count + 1} attempts: "
                f"{last_error.get_user_message()}"
            )

        raise RuntimeError("Tool execution failed: Unknown error")
