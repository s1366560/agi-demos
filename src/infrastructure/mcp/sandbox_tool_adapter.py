"""Sandbox-hosted MCP Tool Adapter.

Adapts user MCP tools running inside sandbox containers to the AgentTool
interface. Tool calls are proxied through the sandbox's mcp_server_call_tool.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, cast, override

from src.infrastructure.agent.tools.base import AgentTool
from src.infrastructure.mcp.resource_cache import MCPResourceCache

logger = logging.getLogger(__name__)

# Background tasks are tracked per-instance (see SandboxMCPServerToolAdapter.__init__)

if TYPE_CHECKING:
    from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter
    from src.infrastructure.agent.tools.define import ToolInfo


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
        tool_info: dict[str, Any],
        cache_ttl_seconds: float = 60.0,
        resource_cache: MCPResourceCache | None = None,
    ) -> None:
        """Initialize the adapter.

        Args:
            sandbox_adapter: MCPSandboxAdapter instance.
            sandbox_id: Sandbox container ID.
            server_name: User MCP server name.
            tool_info: Tool definition dict (name, description, input_schema, _meta).
            cache_ttl_seconds: Cache TTL for resource HTML (default: 60s, 0 to disable).
            resource_cache: Optional MCPResourceCache service for shared caching.
        """
        # Extract and compute tool name/description first (needed for super().__init__)
        self._server_name = server_name
        self._original_tool_name = tool_info.get("name", "")
        description = tool_info.get("description", "")
        tool_name = self._generate_tool_name_static(server_name, self._original_tool_name)

        # Call parent constructor with computed name and description
        super().__init__(name=tool_name, description=description)

        # Now set the remaining attributes
        self._sandbox_adapter = sandbox_adapter
        self._sandbox_id = sandbox_id
        self._input_schema = tool_info.get("input_schema", tool_info.get("inputSchema", {}))
        # Override the _description with our own (parent set it, but we keep it consistent)
        self._description = description

        # Preserve _meta.ui for MCP Apps support
        meta = tool_info.get("_meta")
        self._ui_metadata = meta.get("ui") if meta and isinstance(meta, dict) else None
        if self._ui_metadata:
            logger.info(
                "SandboxMCPServerToolAdapter %s: _ui_metadata=%s",
                self._name,
                self._ui_metadata,
            )
        else:
            logger.debug(
                "SandboxMCPServerToolAdapter %s: no _meta.ui in tool_info (keys=%s)",
                self._name,
                list(tool_info.keys()),
            )

        # MCP App ID (set externally after auto-detection)
        self._app_id: str = ""

        # Resource HTML caching
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cached_html: str | None = None
        self._cache_fetched_at: float | None = None
        self._cache_stats: dict[str, Any] = {
            "hits": 0,
            "misses": 0,
            "last_fetch_at": None,
        }

        # Background tasks for this adapter instance
        self._bg_tasks: set[asyncio.Task[Any]] = set()

        # Injected cache service (preferred when available)
        self._resource_cache = resource_cache

    @staticmethod
    def _generate_tool_name_static(server_name: str, tool_name: str) -> str:
        """Generate MCP tool name (static version for use before __init__)."""
        clean_server = server_name.replace("-", "_")
        return f"mcp__{clean_server}__{tool_name}"

    def _generate_tool_name(self) -> str:
        """Generate MCP tool name (instance version)."""
        return self._generate_tool_name_static(self._server_name, self._original_tool_name)

    @property
    @override
    def name(self) -> str:
        return self._name

    @property
    @override
    def description(self) -> str:
        return self._description or (
            f"MCP tool {self._original_tool_name} from {self._server_name}"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return cast(dict[str, Any], self._input_schema)

    @property
    def ui_metadata(self) -> dict[str, Any] | None:
        """Get MCP App UI metadata if this tool declares an interactive UI."""
        return self._ui_metadata

    @property
    def has_ui(self) -> bool:
        """Check if this tool declares an MCP App UI.

        SEP-1865 mandates the ``ui://`` scheme.  Legacy schemes are
        accepted with a deprecation warning so existing servers keep
        working while they migrate.
        """
        if self._ui_metadata is None:
            return False
        uri = self._ui_metadata.get("resourceUri", "")
        if not uri:
            return False
        if not str(uri).startswith("ui://"):
            logger.warning(
                "Tool %s declares non-standard resourceUri scheme: %r; SEP-1865 requires ui:// scheme",
                self.name,
                uri,
            )
        return True

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
        uri = self.resource_uri
        if not uri:
            return ""

        # Use injected cache service if available
        if self._resource_cache is not None:
            cached = await self._resource_cache.get(uri)
            if cached is not None:
                return cached

            try:
                html = await self._sandbox_adapter.read_resource(self._sandbox_id, uri)
                html = html or ""
                if html:
                    await self._resource_cache.put(uri, html, ttl=self._cache_ttl_seconds)
                return html
            except Exception as e:
                logger.warning("fetch_resource_html failed for %s: %s", uri, e)
                return ""

        # Fallback: inline caching (legacy path)
        return await self._fetch_resource_html_inline(uri)

    async def _fetch_resource_html_inline(self, uri: str) -> str:
        """Legacy inline caching path for fetch_resource_html."""
        import time

        if self._cache_ttl_seconds > 0 and self._cached_html is not None:
            cache_age = time.time() - (self._cache_fetched_at or 0)
            if cache_age < self._cache_ttl_seconds:
                self._cache_stats["hits"] += 1
                logger.debug("Resource HTML cache hit for %s (age=%.1fs)", uri, cache_age)
                return self._cached_html

        # Cache miss or expired - fetch fresh
        self._cache_stats["misses"] += 1
        try:
            html = await self._sandbox_adapter.read_resource(self._sandbox_id, uri)
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
        if self._resource_cache is not None:
            uri = self.resource_uri
            if uri:
                with contextlib.suppress(RuntimeError):
                    loop = asyncio.get_running_loop()
                    _task = loop.create_task(self._resource_cache.invalidate(uri))
                    self._bg_tasks.add(_task)
                    _task.add_done_callback(self._bg_tasks.discard)
        self._cached_html = None
        self._cache_fetched_at = None
        logger.debug("Resource HTML cache invalidated for %s", self.resource_uri)

    def prefetch_resource_html(self) -> None:
        """Prefetch resource HTML in the background without blocking.

        Starts an async task to fetch and cache the HTML.
        Useful for warming the cache before the first request.
        """
        if self._resource_cache is not None:

            async def _fetch(uri: str) -> str:
                html = await self._sandbox_adapter.read_resource(self._sandbox_id, uri)
                return html or ""

            uri = self.resource_uri
            if uri:
                self._resource_cache.prefetch(uri, _fetch)
            return

        # Fallback: legacy prefetch
        import asyncio as _asyncio

        async def _prefetch() -> None:
            try:
                await self.fetch_resource_html()
                logger.debug("Prefetched resource HTML for %s", self.resource_uri)
            except Exception as e:
                logger.warning("Prefetch failed for %s: %s", self.resource_uri, e)

        # Create background task (fire and forget)
        with contextlib.suppress(RuntimeError):
            _mcp_bg_tasks = self._bg_tasks
            _prefetch_task = _asyncio.create_task(_prefetch())
            _mcp_bg_tasks.add(_prefetch_task)
            _prefetch_task.add_done_callback(_mcp_bg_tasks.discard)

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dict with hits, misses, and size or last_fetch_at.
        """
        if self._resource_cache is not None:
            return dict(self._resource_cache.get_stats())
        return dict(self._cache_stats)

    @override
    def get_parameters_schema(self) -> dict[str, Any]:
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

    @override
    async def execute(self, **kwargs: Any) -> str:
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
    def _extract_text(content: list[Any]) -> str:
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

    def _capture_html_from_content(self, content: list[Any]) -> None:
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
                # Also store in injected cache service if available
                if self._resource_cache is not None:
                    uri = self.resource_uri
                    if uri:
                        with contextlib.suppress(RuntimeError):
                            loop = asyncio.get_running_loop()
                            _task = loop.create_task(self._resource_cache.put(uri, text))
                            self._bg_tasks.add(_task)
                            _task.add_done_callback(self._bg_tasks.discard)
                logger.debug(
                    "Captured HTML from tool result for %s (%d bytes)",
                    self._name,
                    len(text),
                )
                return


# ---------------------------------------------------------------------------
# @tool_define migration: factory function for dynamic sandbox MCP server tools
# ---------------------------------------------------------------------------


def _generate_sandbox_tool_name(server_name: str, tool_name: str) -> str:
    """Generate MCP tool name from server and tool names.

    Args:
        server_name: MCP server name (dashes replaced with underscores).
        tool_name: Original tool name.

    Returns:
        Name in ``mcp__{server}__{tool}`` format.
    """
    clean_server = server_name.replace("-", "_")
    return f"mcp__{clean_server}__{tool_name}"


def _extract_text_from_content(content: list[Any]) -> str:
    """Extract text from MCP content items.

    Args:
        content: List of MCP content dicts.

    Returns:
        Newline-joined text from all items.
    """
    texts: list[str] = []
    for item in content:
        if isinstance(item, dict):
            if item.get("type") == "text":
                texts.append(item.get("text", ""))
            else:
                texts.append(str(item))
        else:
            texts.append(str(item))
    return "\n".join(texts)


def _normalize_parameters_schema(input_schema: dict[str, Any]) -> dict[str, Any]:
    """Normalise MCP input_schema into a complete JSON Schema dict.

    Args:
        input_schema: Raw schema from tool definition.

    Returns:
        Schema dict guaranteed to have type, properties, required.
    """
    if not input_schema:
        return {"type": "object", "properties": {}, "required": []}
    schema = dict(input_schema)
    if "type" not in schema:
        schema["type"] = "object"
    if "properties" not in schema:
        schema["properties"] = {}
    if "required" not in schema:
        schema["required"] = []
    return schema


def _build_fetch_resource_html(
    sandbox_adapter: MCPSandboxAdapter,
    sandbox_id: str,
    cache_ttl_seconds: float,
    resource_cache: MCPResourceCache | None,
    get_uri: Callable[[], str],
    state: dict[str, Any],
) -> Callable[[], Awaitable[str]]:
    """Build the fetch_resource_html closure."""

    async def _fetch_html_inline(uri: str) -> str:
        import time

        if cache_ttl_seconds > 0 and state["cached_html"] is not None:
            age = time.time() - (state["cache_fetched_at"] or 0)
            if age < cache_ttl_seconds:
                state["cache_stats"]["hits"] += 1
                return str(state["cached_html"])

        state["cache_stats"]["misses"] += 1
        try:
            html = await sandbox_adapter.read_resource(sandbox_id, uri)
            html = html or ""
            if cache_ttl_seconds > 0 and html:
                state["cached_html"] = html
                state["cache_fetched_at"] = time.time()
            state["cache_stats"]["last_fetch_at"] = time.time()
            return html
        except Exception as exc:
            logger.warning("fetch_resource_html failed for %s: %s", uri, exc)
            return ""

    async def fetch_resource_html() -> str:
        uri = get_uri()
        if not uri:
            return ""
        if resource_cache is not None:
            cached = await resource_cache.get(uri)
            if cached is not None:
                return cached
            try:
                html = await sandbox_adapter.read_resource(sandbox_id, uri)
                html = html or ""
                if html:
                    await resource_cache.put(uri, html, ttl=cache_ttl_seconds)
                return html
            except Exception as exc:
                logger.warning("fetch_resource_html failed for %s: %s", uri, exc)
                return ""
        return await _fetch_html_inline(uri)

    return fetch_resource_html


def _build_invalidate_cache(
    resource_cache: MCPResourceCache | None,
    get_uri: Callable[[], str],
    state: dict[str, Any],
    bg_tasks: set[asyncio.Task[Any]],
) -> Callable[[], None]:
    """Build the invalidate_resource_cache closure."""

    def invalidate_resource_cache() -> None:
        if resource_cache is not None:
            uri = get_uri()
            if uri:
                with contextlib.suppress(RuntimeError):
                    loop = asyncio.get_running_loop()
                    _task = loop.create_task(resource_cache.invalidate(uri))
                    bg_tasks.add(_task)
                    _task.add_done_callback(bg_tasks.discard)
        state["cached_html"] = None
        state["cache_fetched_at"] = None

    return invalidate_resource_cache


def _build_prefetch(
    sandbox_adapter: MCPSandboxAdapter,
    sandbox_id: str,
    resource_cache: MCPResourceCache | None,
    get_uri: Callable[[], str],
    fetch_fn: Callable[[], Awaitable[str]],
    bg_tasks: set[asyncio.Task[Any]],
) -> Callable[[], None]:
    """Build the prefetch_resource_html closure."""

    def prefetch_resource_html() -> None:
        if resource_cache is not None:
            async def _fetch(uri: str) -> str:
                html = await sandbox_adapter.read_resource(sandbox_id, uri)
                return html or ""

            uri = get_uri()
            if uri:
                resource_cache.prefetch(uri, _fetch)
            return

        import asyncio as _asyncio

        async def _prefetch() -> None:
            try:
                await fetch_fn()
            except Exception as exc:
                logger.warning(
                    "Prefetch failed for %s: %s", get_uri(), exc,
                )

        with contextlib.suppress(RuntimeError):
            _task = _asyncio.create_task(_prefetch())
            bg_tasks.add(_task)
            _task.add_done_callback(bg_tasks.discard)

    return prefetch_resource_html


def _build_capture_html(
    resource_cache: MCPResourceCache | None,
    get_uri: Callable[[], str],
    state: dict[str, Any],
    bg_tasks: set[asyncio.Task[Any]],
) -> Callable[[list[Any]], None]:
    """Build the capture_html_from_content closure."""

    def capture_html_from_content(content: list[Any]) -> None:
        import time

        for item in content:
            if not isinstance(item, dict) or item.get("type") != "text":
                continue
            text = item.get("text", "")
            prefix = text.lstrip()[:80].lower()
            if "<!doctype html" not in prefix and "<html" not in prefix:
                continue
            state["last_html"] = text
            state["cached_html"] = text
            state["cache_fetched_at"] = time.time()
            if resource_cache is not None:
                uri = get_uri()
                if uri:
                    with contextlib.suppress(RuntimeError):
                        loop = asyncio.get_running_loop()
                        _t = loop.create_task(resource_cache.put(uri, text))
                        bg_tasks.add(_t)
                        _t.add_done_callback(bg_tasks.discard)
            return

    return capture_html_from_content


def _attach_processor_attrs(
    info: Any,
    *,
    ui_metadata: dict[str, Any] | None,
    server_name: str,
    original_tool_name: str,
    name: str,
    resource_uri: str,
    fetch_resource_html: Callable[[], Awaitable[str]],
    invalidate_fn: Callable[[], None],
    prefetch_fn: Callable[[], None],
    cache_stats_fn: Callable[[], dict[str, Any]],
) -> None:
    """Set extra attributes on ToolInfo for processor.py compatibility.

    processor.py accesses these via ``getattr(tool_instance, ...)`` where
    ``tool_instance`` is the ToolInfo stored as ``_tool_instance`` on
    ``ToolDefinition``.
    """
    has_ui = ui_metadata is not None and bool(ui_metadata.get("resourceUri", ""))
    info.has_ui = has_ui
    info.ui_metadata = ui_metadata
    info._ui_metadata = ui_metadata
    info._app_id = ""
    info._last_app_id = ""
    info._server_name = server_name
    info._original_tool_name = original_tool_name
    info._last_html = ""
    info._name = name
    info.resource_uri = resource_uri
    info.fetch_resource_html = fetch_resource_html
    info.invalidate_resource_cache = invalidate_fn
    info.prefetch_resource_html = prefetch_fn
    info.get_cache_stats = cache_stats_fn


def create_sandbox_mcp_server_tool(
    sandbox_adapter: MCPSandboxAdapter,
    sandbox_id: str,
    server_name: str,
    tool_info: dict[str, Any],
    cache_ttl_seconds: float = 60.0,
    resource_cache: MCPResourceCache | None = None,
) -> ToolInfo:
    """Create a ToolInfo for a sandbox-hosted MCP server tool.

    This is the ``@tool_define`` migration equivalent of
    :class:`SandboxMCPServerToolAdapter`. Each sandbox MCP server tool has a
    unique name/description/parameters so we build :class:`ToolInfo` directly.

    The returned ``ToolInfo`` has extra attributes set on it so that
    ``processor.py`` can access ``has_ui``, ``ui_metadata``, ``_app_id``,
    ``_server_name``, ``_last_html``, ``fetch_resource_html``, etc. via
    ``getattr(tool_instance, ...)``.

    Args:
        sandbox_adapter: MCPSandboxAdapter instance.
        sandbox_id: Sandbox container ID.
        server_name: User MCP server name.
        tool_info: Tool definition dict (name, description, input_schema, _meta).
        cache_ttl_seconds: Cache TTL for resource HTML (default 60s, 0 to disable).
        resource_cache: Optional MCPResourceCache for shared caching.

    Returns:
        A :class:`ToolInfo` instance representing this sandbox MCP server tool.
    """
    from src.infrastructure.agent.tools.context import ToolContext
    from src.infrastructure.agent.tools.define import ToolInfo
    from src.infrastructure.agent.tools.result import ToolResult

    original_tool_name: str = tool_info.get("name", "")
    description: str = tool_info.get("description", "")
    raw_schema = tool_info.get("input_schema", tool_info.get("inputSchema", {}))
    parameters = _normalize_parameters_schema(raw_schema)
    name = _generate_sandbox_tool_name(server_name, original_tool_name)

    # -- UI metadata extraction --
    meta = tool_info.get("_meta")
    ui_metadata: dict[str, Any] | None = (
        meta.get("ui") if meta and isinstance(meta, dict) else None
    )

    def _resource_uri() -> str:
        if ui_metadata:
            return str(ui_metadata.get("resourceUri", ""))
        return ""

    # -- Mutable state shared between closures --
    state: dict[str, Any] = {
        "cached_html": None,
        "cache_fetched_at": None,
        "last_html": "",
        "cache_stats": {"hits": 0, "misses": 0, "last_fetch_at": None},
    }
    bg_tasks: set[asyncio.Task[Any]] = set()

    # -- Build caching helpers --
    fetch_resource_html = _build_fetch_resource_html(
        sandbox_adapter=sandbox_adapter,
        sandbox_id=sandbox_id,
        cache_ttl_seconds=cache_ttl_seconds,
        resource_cache=resource_cache,
        get_uri=_resource_uri,
        state=state,
    )
    invalidate_fn = _build_invalidate_cache(
        resource_cache=resource_cache,
        get_uri=_resource_uri,
        state=state,
        bg_tasks=bg_tasks,
    )
    prefetch_fn = _build_prefetch(
        sandbox_adapter=sandbox_adapter,
        sandbox_id=sandbox_id,
        resource_cache=resource_cache,
        get_uri=_resource_uri,
        fetch_fn=fetch_resource_html,
        bg_tasks=bg_tasks,
    )
    capture_fn = _build_capture_html(
        resource_cache=resource_cache,
        get_uri=_resource_uri,
        state=state,
        bg_tasks=bg_tasks,
    )

    # -- Execute function --
    async def execute(ctx: ToolContext, **kwargs: Any) -> ToolResult:
        """Execute the tool by proxying through sandbox mcp_server_call_tool."""
        _ = ctx
        logger.info("Executing sandbox MCP tool: %s", name)
        try:
            result = await sandbox_adapter.call_tool(
                sandbox_id=sandbox_id,
                tool_name="mcp_server_call_tool",
                arguments={
                    "server_name": server_name,
                    "tool_name": original_tool_name,
                    "arguments": json.dumps(kwargs),
                },
            )
            is_error = result.get("is_error", result.get("isError", False))
            content = result.get("content", [])

            if is_error:
                texts = _extract_text_from_content(content)
                error_msg = texts or "Tool execution failed"
                logger.error("Sandbox MCP tool error: %s", error_msg)
                return ToolResult(
                    output=f"Error: {error_msg}", is_error=True,
                )

            texts = _extract_text_from_content(content)
            capture_fn(content)
            # Sync _last_html attribute on ToolInfo for processor.py
            info._last_html = state["last_html"]  # type: ignore[attr-defined]
            return ToolResult(
                output=texts or "Tool executed successfully (no output)",
            )
        except Exception as exc:
            logger.exception(
                "Error executing sandbox MCP tool %s: %s", name, exc,
            )
            return ToolResult(
                output=f"Error executing tool: {exc}", is_error=True,
            )

    # -- Build ToolInfo --
    info = ToolInfo(
        name=name,
        description=description or f"MCP tool {original_tool_name} from {server_name}",
        parameters=parameters,
        execute=execute,
        permission=None,
        category="mcp",
        tags=frozenset({"mcp", "sandbox", server_name}),
    )

    # -- Attach extra attributes for processor.py compatibility --
    _attach_processor_attrs(
        info,
        ui_metadata=ui_metadata,
        server_name=server_name,
        original_tool_name=original_tool_name,
        name=name,
        resource_uri=_resource_uri(),
        fetch_resource_html=fetch_resource_html,
        invalidate_fn=invalidate_fn,
        prefetch_fn=prefetch_fn,
        cache_stats_fn=lambda: (
            dict(resource_cache.get_stats()) if resource_cache is not None
            else dict(state["cache_stats"])
        ),
    )

    return info
