"""Sandbox-hosted MCP Tool Adapter.

Adapts user MCP tools running inside sandbox containers to the AgentTool
interface. Tool calls are proxied through the sandbox's mcp_server_call_tool.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from src.infrastructure.agent.tools.base import AgentTool

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter


class SandboxMCPServerToolAdapter(AgentTool):
    """Adapter for MCP tools running inside a sandbox container.

    User-configured MCP servers run as subprocesses inside the sandbox.
    Tool calls are proxied through the sandbox's mcp_server_call_tool
    management tool via the existing MCPSandboxAdapter.

    Tool naming convention: mcp__{server_name}__{tool_name}
    """

    MCP_PREFIX = "mcp"
    MCP_NAME_SEPARATOR = "__"

    def __init__(
        self,
        sandbox_adapter: MCPSandboxAdapter,
        sandbox_id: str,
        server_name: str,
        tool_info: Dict[str, Any],
        cache_ttl_seconds: float = 60.0,
    ):
        """Initialize the adapter.

        Args:
            sandbox_adapter: MCPSandboxAdapter instance.
            sandbox_id: Sandbox container ID.
            server_name: User MCP server name.
            tool_info: Tool definition dict (name, description, input_schema, _meta).
            cache_ttl_seconds: Cache TTL for resource HTML (default: 60s, 0 to disable).
        """
        self._sandbox_adapter = sandbox_adapter
        self._sandbox_id = sandbox_id
        self._server_name = server_name

        self._original_tool_name = tool_info.get("name", "")
        self._description = tool_info.get("description", "")
        self._input_schema = tool_info.get("input_schema", tool_info.get("inputSchema", {}))
        self._name = self._generate_tool_name()

        # Preserve _meta.ui for MCP Apps support
        meta = tool_info.get("_meta")
        self._ui_metadata = meta.get("ui") if meta and isinstance(meta, dict) else None
        if self._ui_metadata:
            logger.info(
                "SandboxMCPServerToolAdapter %s: _ui_metadata=%s",
                self._name, self._ui_metadata,
            )
        else:
            logger.debug(
                "SandboxMCPServerToolAdapter %s: no _meta.ui in tool_info (keys=%s)",
                self._name, list(tool_info.keys()),
            )

        # MCP App ID (set externally after auto-detection)
        self._app_id: str = ""

        # Resource HTML caching
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cached_html: Optional[str] = None
        self._cache_fetched_at: Optional[float] = None
        self._cache_stats = {
            "hits": 0,
            "misses": 0,
            "last_fetch_at": None,
        }

    def _generate_tool_name(self) -> str:
        clean_server = self._server_name.replace("-", "_")
        return (
            f"{self.MCP_PREFIX}{self.MCP_NAME_SEPARATOR}"
            f"{clean_server}{self.MCP_NAME_SEPARATOR}"
            f"{self._original_tool_name}"
        )

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description or (
            f"MCP tool {self._original_tool_name} from {self._server_name}"
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return self._input_schema

    @property
    def ui_metadata(self) -> Optional[Dict[str, Any]]:
        """Get MCP App UI metadata if this tool declares an interactive UI."""
        return self._ui_metadata

    @property
    def has_ui(self) -> bool:
        """Check if this tool declares an MCP App UI.

        Accepts any non-empty resourceUri scheme (ui://, mcp-resource://, etc.)
        as long as _meta.ui is present with a resourceUri field.
        """
        return (
            self._ui_metadata is not None
            and bool(self._ui_metadata.get("resourceUri"))
        )

    @property
    def resource_uri(self) -> str:
        """Get the ui:// resource URI, if declared."""
        if self._ui_metadata:
            return str(self._ui_metadata.get("resourceUri", ""))
        return ""

    async def fetch_resource_html(self) -> str:
        """Fetch HTML from the MCP server via resources/read.

        Returns the live HTML content from the running MCP server,
        using cache if available and not expired.

        Returns:
            HTML content string, or empty string on failure.
        """
        import time

        uri = self.resource_uri
        if not uri:
            return ""

        # Check cache
        if self._cache_ttl_seconds > 0 and self._cached_html is not None:
            cache_age = time.time() - (self._cache_fetched_at or 0)
            if cache_age < self._cache_ttl_seconds:
                self._cache_stats["hits"] += 1
                logger.debug("Resource HTML cache hit for %s (age=%.1fs)", uri, cache_age)
                return self._cached_html

        # Cache miss or expired - fetch fresh
        self._cache_stats["misses"] += 1
        try:
            html = await self._sandbox_adapter.read_resource(
                self._sandbox_id, uri
            )
            html = html or ""

            # Cache successful result
            if self._cache_ttl_seconds > 0 and html:
                self._cached_html = html
                self._cache_fetched_at = time.time()

            self._cache_stats["last_fetch_at"] = time.time()
            return html
        except Exception as e:
            logger.warning("fetch_resource_html failed for %s: %s", uri, e)
            # Don't cache errors - allow retry
            return ""

    def invalidate_resource_cache(self) -> None:
        """Invalidate the cached resource HTML."""
        self._cached_html = None
        self._cache_fetched_at = None
        logger.debug("Resource HTML cache invalidated for %s", self.resource_uri)

    def prefetch_resource_html(self) -> None:
        """Prefetch resource HTML in the background without blocking.

        Starts an async task to fetch and cache the HTML.
        Useful for warming the cache before the first request.
        """
        import asyncio

        async def _prefetch():
            try:
                await self.fetch_resource_html()
                logger.debug("Prefetched resource HTML for %s", self.resource_uri)
            except Exception as e:
                logger.warning("Prefetch failed for %s: %s", self.resource_uri, e)

        # Create background task (fire and forget)
        try:
            asyncio.create_task(_prefetch())
        except RuntimeError:
            # No event loop available, skip prefetch
            pass

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dict with hits, misses, last_fetch_at
        """
        return dict(self._cache_stats)

    def get_parameters_schema(self) -> Dict[str, Any]:
        if not self._input_schema:
            return {"type": "object", "properties": {}, "required": []}

        schema = dict(self._input_schema)
        if "type" not in schema:
            schema["type"] = "object"
        if "properties" not in schema:
            schema["properties"] = {}
        if "required" not in schema:
            schema["required"] = []
        return schema

    async def execute(self, **kwargs: Any) -> str:  # noqa: ANN401
        """Execute the tool by proxying through sandbox's mcp_server_call_tool."""
        logger.info("Executing sandbox MCP tool: %s", self._name)

        try:
            # Call the sandbox management tool to proxy the tool call
            result = await self._sandbox_adapter.call_tool(
                sandbox_id=self._sandbox_id,
                tool_name="mcp_server_call_tool",
                arguments={
                    "server_name": self._server_name,
                    "tool_name": self._original_tool_name,
                    "arguments": json.dumps(kwargs),
                },
            )

            # Parse result
            is_error = result.get("is_error", result.get("isError", False))
            content = result.get("content", [])

            if is_error:
                texts = self._extract_text(content)
                error_msg = texts or "Tool execution failed"
                logger.error("Sandbox MCP tool error: %s", error_msg)
                return f"Error: {error_msg}"

            texts = self._extract_text(content)
            # Detect HTML content in the result and cache it so processor.py
            # can emit it in mcp_app_result without an extra resources/read call.
            self._capture_html_from_content(content)
            return texts or "Tool executed successfully (no output)"

        except Exception as e:
            logger.exception("Error executing sandbox MCP tool %s: %s", self._name, e)
            return f"Error executing tool: {e}"

    @staticmethod
    def _extract_text(content: list) -> str:
        """Extract text from MCP content items."""
        texts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    texts.append(item.get("text", ""))
                else:
                    texts.append(str(item))
            else:
                texts.append(str(item))
        return "\n".join(texts)

    def _capture_html_from_content(self, content: list) -> None:
        """Detect HTML in tool result and cache it for mcp_app_result emission.

        If the tool execution returns HTML directly (e.g., a game renderer that
        generates the page inline), store it in _last_html and _cached_html so
        processor.py can include it in mcp_app_result without a round-trip
        resources/read call.
        """
        import time

        for item in content:
            if not isinstance(item, dict) or item.get("type") != "text":
                continue
            text = item.get("text", "")
            prefix = text.lstrip()[:80].lower()
            if "<!doctype html" in prefix or "<html" in prefix:
                self._last_html: str = text
                self._cached_html = text
                self._cache_fetched_at = time.time()
                logger.debug("Captured HTML from tool result for %s (%d bytes)", self._name, len(text))
                return
