"""Tool provider factory for hot-plug support.

This module provides factory functions to create tool_provider callables
for ReActAgent, enabling dynamic tool loading at runtime.
"""

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

SelectionContextProvider = Callable[[], dict[str, Any]]
SelectionPipeline = Callable[[dict[str, Any], dict[str, Any] | None], dict[str, Any]]


def create_cached_tool_provider(
    project_id: str,
    fallback_tools: dict[str, Any] | None = None,
) -> Callable[[], dict[str, Any]]:
    """Create a tool provider that reads from the tools cache.

    This is the recommended way to enable hot-plug for tools. The provider
    reads from the global tools cache (populated by get_or_create_tools)
    and returns the current tools.

    Args:
        project_id: Project ID to get tools for
        fallback_tools: Optional fallback tools if cache is empty

    Returns:
        A callable that returns current tools dict
    """
    from src.infrastructure.agent.state.agent_worker_state import (
        get_cached_tools_for_project,
        rescan_custom_tools_for_project,
    )

    def provider() -> dict[str, Any]:
        # Rescan custom tools before returning — picks up
        # .memstack/tools/*.py files created mid-conversation.
        rescan_custom_tools_for_project(project_id)
        cached = get_cached_tools_for_project(project_id)
        if cached is not None:
            return cached
        elif fallback_tools is not None:
            logger.warning(f"Tools cache miss for project {project_id}, using fallback")
            return fallback_tools
        else:
            logger.warning(f"Tools cache miss for project {project_id}, returning empty")
            return {}

    return provider


def create_composite_tool_provider(
    providers: list[Callable[[], dict[str, Any]]],
) -> Callable[[], dict[str, Any]]:
    """Create a tool provider that aggregates multiple providers.

    Useful for combining builtin tools, MCP tools, and skill tools.

    Args:
        providers: List of tool provider callables

    Returns:
        A callable that returns merged tools dict from all providers
    """

    def provider() -> dict[str, Any]:
        tools = {}
        for p in providers:
            try:
                tools.update(p())
            except Exception as e:
                logger.warning(f"Tool provider failed: {e}")
        return tools

    return provider


def create_pipeline_tool_provider(
    base_provider: Callable[[], dict[str, Any]],
    selection_pipeline: SelectionPipeline,
    context_provider: SelectionContextProvider | None = None,
) -> Callable[[], dict[str, Any]]:
    """Wrap a provider with a selection pipeline.

    Args:
        base_provider: Upstream provider returning a full tool set.
        selection_pipeline: Pipeline that filters/reorders tools.
        context_provider: Optional callback to provide pipeline context.

    Returns:
        Provider callable that applies selection pipeline.
    """

    def provider() -> dict[str, Any]:
        tools = base_provider()
        context = context_provider() if context_provider else None
        selected = selection_pipeline(tools, context)

        if isinstance(selected, dict):
            return selected

        raise TypeError("Tool selection pipeline must return Dict[str, Any]")

    return provider


def create_mcp_tool_provider(
    tenant_id: str,
) -> Callable[[], dict[str, Any]]:
    """Create a tool provider that reads MCP tools from cache.

    This provider returns MCP tools from the TTL cache without making
    Temporal workflow calls.

    Args:
        tenant_id: Tenant ID for MCP tools

    Returns:
        A callable that returns MCP tools dict
    """

    # Access the MCP tools cache directly (synchronous)
    def provider() -> dict[str, Any]:
        # Note: This accesses the internal cache structure
        # A more robust solution would expose a sync API in agent_session_pool
        try:
            from src.infrastructure.agent.state.agent_session_pool import (
                get_mcp_tools_from_cache_sync,
            )

            cache_key = f"mcp_tools:{tenant_id}"
            tools = get_mcp_tools_from_cache_sync(cache_key)
            if tools is not None:
                return tools
            return {}
        except ImportError:
            logger.debug("MCP tools cache not available")
            return {}

    return provider


def create_static_tool_provider(
    tools: dict[str, Any],
) -> Callable[[], dict[str, Any]]:
    """Create a tool provider that always returns the same tools.

    Useful for testing or when tools don't need to change.

    Args:
        tools: Static tools dict

    Returns:
        A callable that returns the static tools
    """

    def provider() -> dict[str, Any]:
        return tools.copy()

    return provider


def create_custom_tool_provider(
    base_path: str | None = None,
    tools_dirs: list[str] | None = None,
) -> Callable[[], dict[str, Any]]:
    """Create a tool provider that loads custom tools from the filesystem.

    Scans ``.memstack/tools/`` for Python files using the ``@tool_define``
    decorator and returns them as a tool provider callable.

    Args:
        base_path: Project root directory. Defaults to ``cwd()``.
        tools_dirs: Override tool directories to scan.

    Returns:
        A callable that returns custom tools dict
    """
    from pathlib import Path

    from src.infrastructure.agent.tools.custom_tool_loader import get_custom_tool_infos

    resolved_path = Path(base_path) if base_path else None

    # Cache loaded tools so we don't re-scan on every call.
    _cache: dict[str, Any] = {}
    _loaded: list[bool] = [False]

    def provider() -> dict[str, Any]:
        if not _loaded[0]:
            _cache.update(get_custom_tool_infos(base_path=resolved_path))
            _loaded[0] = True
        return _cache.copy()

    return provider
