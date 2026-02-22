"""Agent Worker state management for Temporal Activities.

This module provides global state management for the Agent Temporal Worker,
allowing Agent Activities to access shared services independently from
the main data processing worker.

Enhanced with:
- LLM client caching for connection reuse
- Tool set caching for faster Agent initialization
- Agent Session Pool for component reuse (95%+ latency reduction)
- MCP tools caching with TTL
- SubAgentRouter caching
- SystemPromptManager singleton

Performance Impact (with Agent Session Pool):
- First request: ~300-800ms (builds cache)
- Subsequent requests: <20ms (95%+ reduction)
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import redis.asyncio as redis

from src.infrastructure.agent.plugins.manager import get_plugin_runtime_manager
from src.infrastructure.agent.plugins.registry import (
    PluginDiagnostic,
    PluginToolBuildContext,
    get_plugin_registry,
)

# Import Agent Session Pool components
from .agent_session_pool import (
    AgentSessionContext,
    MCPToolsCacheEntry,
    cleanup_expired_sessions,
    clear_all_caches,
    compute_skills_hash,
    compute_subagents_hash,
    compute_tools_hash,
    generate_session_key,
    get_mcp_tools_from_cache,
    get_or_create_agent_session,
    get_or_create_subagent_router,
    get_or_create_tool_definitions,
    get_pool_stats,
    get_system_prompt_manager,
    invalidate_agent_session,
    invalidate_mcp_tools_cache,
    invalidate_subagent_router_cache,
    invalidate_tool_definitions_cache,
    update_mcp_tools_cache,
)

logger = logging.getLogger(__name__)

# Re-export Agent Session Pool components for convenience
__all__ = [
    # Session Pool
    "AgentSessionContext",
    "MCPToolsCacheEntry",
    "get_or_create_agent_session",
    "invalidate_agent_session",
    "cleanup_expired_sessions",
    "get_pool_stats",
    "clear_all_caches",
    # Tool Definitions
    "get_or_create_tool_definitions",
    "invalidate_tool_definitions_cache",
    "compute_tools_hash",
    # MCP Tools
    "get_mcp_tools_from_cache",
    "update_mcp_tools_cache",
    "invalidate_mcp_tools_cache",
    # MCP Sandbox Adapter
    "set_mcp_sandbox_adapter",
    "get_mcp_sandbox_adapter",
    "sync_mcp_sandbox_adapter_from_docker",
    # SubAgentRouter
    "get_or_create_subagent_router",
    "invalidate_subagent_router_cache",
    "compute_subagents_hash",
    # SystemPromptManager
    "get_system_prompt_manager",
    # Skills
    "compute_skills_hash",
    # Provider config
    "get_or_create_provider_config",
    # Graph service
    "get_or_create_agent_graph_service",
    "get_agent_graph_service",
    "set_agent_graph_service",
    # Prewarm
    "prewarm_agent_session",
    # Utilities
    "generate_session_key",
    # Tools cache access (hot-plug support)
    "get_cached_tools",
    "get_cached_tools_for_project",
    "invalidate_tools_cache",
    "invalidate_all_caches_for_project",
    "get_or_create_tools",
    # Pool Manager (new 3-tier architecture)
    "set_pool_adapter",
    "get_pool_adapter",
    "is_pool_enabled",
    # HITL Response Listener (real-time delivery)
    "set_hitl_response_listener",
    "get_hitl_response_listener",
    "get_session_registry",
    # Tool Discovery with Retry
    "discover_tools_with_retry",
]

# Global state for agent worker
_agent_graph_service: Optional[Any] = None
_tenant_graph_services: Dict[str, Any] = {}
_tenant_graph_service_lock = asyncio.Lock()
_redis_pool: Optional[redis.ConnectionPool] = None
_mcp_sandbox_adapter: Optional[Any] = None
_pool_adapter: Optional[Any] = None  # PooledAgentSessionAdapter (when enabled)
_hitl_response_listener: Optional[Any] = None  # HITLResponseListener (real-time)

# LLM client cache (by provider:model key)
_llm_client_cache: Dict[str, Any] = {}
_llm_cache_lock = asyncio.Lock()

# Tool set cache (by project_id key)
_tools_cache: Dict[str, Dict[str, Any]] = {}
_tools_cache_lock = asyncio.Lock()

# Skills cache (by tenant_id:project_id key)
_skills_cache: Dict[str, list] = {}
_skills_cache_lock = asyncio.Lock()

# SkillLoaderTool cache (by tenant_id:project_id:agent_mode key)
_skill_loader_cache: Dict[str, Any] = {}
_skill_loader_cache_lock = asyncio.Lock()

# Provider config cache
_provider_config_cache: Optional[Any] = None
_provider_config_cached_at: float = 0.0
_provider_config_cache_lock = asyncio.Lock()
_provider_config_cache_ttl_seconds = int(os.getenv("PROVIDER_CONFIG_CACHE_TTL_SECONDS", "60"))


def set_agent_graph_service(service: Any) -> None:
    """Set the global graph service instance for agent worker.

    Called during Agent Worker initialization to make graph_service
    available to all Agent Activities.

    Args:
        service: The graph service (NativeGraphAdapter) instance
    """
    global _agent_graph_service
    _agent_graph_service = service
    _tenant_graph_services.setdefault("default", service)
    logger.info("Agent Worker: Graph service registered for Activities")


def get_agent_graph_service() -> Optional[Any]:
    """Get the global graph service instance for agent worker.

    Returns:
        The graph service instance or None if not initialized
    """
    return _agent_graph_service


async def get_or_create_agent_graph_service(tenant_id: Optional[str] = None) -> Any:
    """Get tenant-scoped graph service, creating and caching when needed."""
    cache_key = tenant_id or "default"
    if cache_key in _tenant_graph_services:
        return _tenant_graph_services[cache_key]

    async with _tenant_graph_service_lock:
        if cache_key in _tenant_graph_services:
            return _tenant_graph_services[cache_key]

        from src.configuration.factories import create_native_graph_adapter

        graph_service = await create_native_graph_adapter(tenant_id=tenant_id)
        _tenant_graph_services[cache_key] = graph_service

        # Keep backward compatibility for callers that still use global getter
        if cache_key == "default":
            global _agent_graph_service
            _agent_graph_service = graph_service

        logger.info("Agent Worker: Graph service cached for tenant key '%s'", cache_key)
        return graph_service


def set_mcp_sandbox_adapter(adapter: Any) -> None:
    """Set the global MCP Sandbox Adapter instance for agent worker.

    Called during Agent Worker initialization to make MCPSandboxAdapter
    available to all Agent Activities for loading Project Sandbox MCP tools.

    Args:
        adapter: The MCPSandboxAdapter instance
    """
    global _mcp_sandbox_adapter
    _mcp_sandbox_adapter = adapter
    logger.info("Agent Worker: MCP Sandbox Adapter registered for Activities")


async def sync_mcp_sandbox_adapter_from_docker() -> int:
    """Sync existing sandbox containers from Docker on startup.

    Called during Agent Worker initialization to discover and recover
    existing sandbox containers that may have been created before
    the adapter was (re)initialized.

    Returns:
        Number of sandboxes discovered and synced
    """
    if _mcp_sandbox_adapter is None:
        return 0

    try:
        count = await _mcp_sandbox_adapter.sync_from_docker()
        if count > 0:
            logger.info(f"Agent Worker: Synced {count} existing sandboxes from Docker")
        return count
    except Exception as e:
        logger.warning(f"Agent Worker: Failed to sync sandboxes from Docker: {e}")
        return 0


def get_mcp_sandbox_adapter() -> Optional[Any]:
    """Get the global MCP Sandbox Adapter instance for agent worker.

    Returns:
        The MCPSandboxAdapter instance or None if not initialized
    """
    return _mcp_sandbox_adapter


# ============================================================================
# Agent Pool Adapter State (NEW: 3-tier architecture)
# ============================================================================


def set_pool_adapter(adapter: Any) -> None:
    """Set the global Pool Adapter instance for agent worker.

    Called during Agent Worker initialization when AGENT_POOL_ENABLED=true.
    The adapter provides pooled instance management with tier-based isolation.

    Args:
        adapter: The PooledAgentSessionAdapter instance
    """
    global _pool_adapter
    _pool_adapter = adapter
    logger.info("Agent Worker: Pool Adapter registered for Activities")


def get_pool_adapter() -> Optional[Any]:
    """Get the global Pool Adapter instance for agent worker.

    Returns:
        The PooledAgentSessionAdapter instance or None if not initialized/disabled
    """
    return _pool_adapter


def is_pool_enabled() -> bool:
    """Check if pool-based architecture is enabled.

    Returns:
        True if pool adapter is available and started
    """
    return _pool_adapter is not None and _pool_adapter._running


async def get_redis_pool() -> redis.ConnectionPool:
    """Get or create the Redis connection pool for agent worker.

    Returns:
        The Redis connection pool
    """
    global _redis_pool
    if _redis_pool is None:
        from src.configuration.config import get_settings

        settings = get_settings()
        _redis_pool = redis.ConnectionPool.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=50,
        )
        logger.info("Agent Worker: Redis connection pool created")
    return _redis_pool


async def get_redis_client() -> redis.Redis:
    """Get a Redis client from the connection pool.

    Returns:
        A Redis client connected to the pool
    """
    pool = await get_redis_pool()
    return redis.Redis(connection_pool=pool)


async def close_redis_pool() -> None:
    """Close the Redis connection pool.

    Called during Agent Worker shutdown for cleanup.
    """
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.aclose()
        _redis_pool = None
        logger.info("Agent Worker: Redis connection pool closed")


def clear_state() -> None:
    """Clear all agent worker global state.

    Called during Agent Worker shutdown for cleanup.

    Note: This clears references but does not close async resources.
    Use close_redis_pool() separately to properly close the Redis pool.
    """
    global \
        _agent_graph_service, \
        _tenant_graph_services, \
        _llm_client_cache, \
        _tools_cache, \
        _skills_cache, \
        _skill_loader_cache, \
        _provider_config_cache, \
        _provider_config_cached_at
    _agent_graph_service = None
    _tenant_graph_services.clear()
    _llm_client_cache.clear()
    _tools_cache.clear()
    _skills_cache.clear()
    _skill_loader_cache.clear()
    _provider_config_cache = None
    _provider_config_cached_at = 0.0

    # Also clear Agent Session Pool caches
    pool_stats = clear_all_caches()

    logger.info(f"Agent Worker state cleared (pool: {pool_stats})")


# ============================================================================
# LLM Client Caching
# ============================================================================


def get_cached_llm_clients() -> Dict[str, Any]:
    """Get all cached LLM clients (for debugging/monitoring)."""
    return dict(_llm_client_cache)


# ============================================================================
# Tool Set Caching
# ============================================================================


async def get_or_create_tools(
    project_id: str,
    tenant_id: str,
    graph_service: Any,
    redis_client: Any,
    llm: Any = None,
    agent_mode: str = "default",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Get or create a cached tool set for a project, including sandbox tools and skills.

    This function caches built-in tool instances by project_id to avoid
    repeated tool initialization overhead. Sandbox MCP tools are loaded
    dynamically from the project sandbox container.

    Args:
        project_id: Project ID for cache key
        tenant_id: Tenant ID for sandbox tool loading and skill scoping
        graph_service: Graph service instance (NativeGraphAdapter)
        redis_client: Redis client instance
        llm: LangChain chat model for tools that require LLM (e.g., SummaryTool)
        agent_mode: Agent mode for skill filtering (e.g., "default", "plan")
        **kwargs: Accepted for backward compatibility (mcp_tools_ttl_seconds, etc.)

    Returns:
        Dictionary of tool name -> tool instance (built-in + sandbox + skill_loader)
    """
    from src.infrastructure.agent.tools import WebScrapeTool, WebSearchTool
    from src.infrastructure.agent.tools.clarification import ClarificationTool
    from src.infrastructure.agent.tools.decision import DecisionTool

    # 1. Get or create cached built-in tools
    async with _tools_cache_lock:
        if project_id not in _tools_cache:
            # Get neo4j_client from graph_service
            neo4j_client = getattr(graph_service, "neo4j_client", None)
            if neo4j_client is None:
                neo4j_client = getattr(graph_service, "_neo4j_client", None)

            _tools_cache[project_id] = {
                "web_search": WebSearchTool(redis_client),
                "web_scrape": WebScrapeTool(),
                "ask_clarification": ClarificationTool(),
                "request_decision": DecisionTool(),
            }
            logger.info(f"Agent Worker: Tool set cached for project {project_id}")

    # 2. Copy built-in tools (avoid mutating cache)
    tools = dict(_tools_cache[project_id])

    # 3. Load Project Sandbox MCP tools (if sandbox exists for project)
    if _mcp_sandbox_adapter is not None:
        try:
            sandbox_tools = await _load_project_sandbox_tools(
                project_id=project_id,
                tenant_id=tenant_id,
                redis_client=redis_client,
            )
            if sandbox_tools:
                tools.update(sandbox_tools)
                logger.info(
                    f"Agent Worker: Loaded {len(sandbox_tools)} Project Sandbox tools "
                    f"for project {project_id}"
                )
        except Exception as e:
            logger.warning(
                f"Agent Worker: Failed to load Project Sandbox tools for project {project_id}: {e}"
            )

    # 4. Add SkillLoaderTool (initialized with skill list in description)
    # This enables LLM to see available skills and make autonomous decisions
    try:
        skill_loader = await get_or_create_skill_loader_tool(
            tenant_id=tenant_id,
            project_id=project_id,
            agent_mode=agent_mode,
        )
        # Set sandbox_id from loaded sandbox tools for resource sync
        for tool in tools.values():
            if hasattr(tool, "sandbox_id") and tool.sandbox_id:
                skill_loader.set_sandbox_id(tool.sandbox_id)
                break
        tools["skill_loader"] = skill_loader
        logger.info(
            f"Agent Worker: SkillLoaderTool added for tenant {tenant_id}, agent_mode={agent_mode}"
        )
    except Exception as e:
        logger.warning(f"Agent Worker: Failed to create SkillLoaderTool: {e}")

    # 5. Add SkillInstallerTool for installing skills from skills.sh
    try:
        from pathlib import Path

        from src.infrastructure.agent.tools.plugin_manager import PluginManagerTool
        from src.infrastructure.agent.tools.skill_installer import SkillInstallerTool

        # Use the project path from config or fallback to current working directory
        project_path = Path.cwd()
        skill_installer = SkillInstallerTool(
            project_path=project_path,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        tools["skill_installer"] = skill_installer
        logger.info(f"Agent Worker: SkillInstallerTool added for project {project_id}")

        plugin_manager = PluginManagerTool(
            tenant_id=tenant_id,
            project_id=project_id,
        )
        tools["plugin_manager"] = plugin_manager
        logger.info(f"Agent Worker: PluginManagerTool added for project {project_id}")
    except Exception as e:
        logger.warning(f"Agent Worker: Failed to create SkillInstallerTool/PluginManagerTool: {e}")

    # 5b. Add SkillSyncTool for syncing skills from sandbox back to the system
    try:
        from src.infrastructure.adapters.secondary.persistence.database import (
            async_session_factory as sync_session_factory,
        )
        from src.infrastructure.agent.tools.skill_sync import SkillSyncTool

        skill_sync_tool = SkillSyncTool(
            tenant_id=tenant_id,
            project_id=project_id,
            sandbox_adapter=_mcp_sandbox_adapter,
            session_factory=sync_session_factory,
        )
        # Set sandbox_id from loaded sandbox tools
        for tool in tools.values():
            if hasattr(tool, "sandbox_id") and tool.sandbox_id:
                skill_sync_tool.set_sandbox_id(tool.sandbox_id)
                break
        # Set reference to skill_loader for cache invalidation
        if "skill_loader" in tools:
            skill_sync_tool.set_skill_loader_tool(tools["skill_loader"])
        tools["skill_sync"] = skill_sync_tool
        logger.info(f"Agent Worker: SkillSyncTool added for tenant {tenant_id}")
    except Exception as e:
        logger.warning(f"Agent Worker: Failed to create SkillSyncTool: {e}")

    # 7. Add Environment Variable Tools (GetEnvVarTool, RequestEnvVarTool, CheckEnvVarsTool)
    try:
        from src.infrastructure.adapters.secondary.persistence.database import (
            async_session_factory,
        )
        from src.infrastructure.agent.tools.env_var_tools import (
            CheckEnvVarsTool,
            GetEnvVarTool,
            RequestEnvVarTool,
        )
        from src.infrastructure.security.encryption_service import get_encryption_service

        encryption_service = get_encryption_service()

        # Create env var tools with session_factory for worker context
        # Each tool will create its own session when execute() is called
        get_env_var_tool = GetEnvVarTool(
            repository=None,  # Will use session_factory instead
            encryption_service=encryption_service,
            tenant_id=tenant_id,
            project_id=project_id,
            session_factory=async_session_factory,
        )
        request_env_var_tool = RequestEnvVarTool(
            repository=None,  # Will use session_factory instead
            encryption_service=encryption_service,
            tenant_id=tenant_id,
            project_id=project_id,
            session_factory=async_session_factory,
        )
        check_env_vars_tool = CheckEnvVarsTool(
            repository=None,  # Will use session_factory instead
            encryption_service=encryption_service,
            tenant_id=tenant_id,
            project_id=project_id,
            session_factory=async_session_factory,
        )

        tools["get_env_var"] = get_env_var_tool
        tools["request_env_var"] = request_env_var_tool
        tools["check_env_vars"] = check_env_vars_tool
        logger.info(
            f"Agent Worker: Environment variable tools added for tenant {tenant_id}, "
            f"project {project_id}"
        )
    except Exception as e:
        logger.warning(f"Agent Worker: Failed to create environment variable tools: {e}")

    # 8. Add Human-in-the-Loop Tools (ClarificationTool, DecisionTool)
    try:
        from src.infrastructure.agent.tools.clarification import ClarificationTool
        from src.infrastructure.agent.tools.decision import DecisionTool

        clarification_tool = ClarificationTool()
        decision_tool = DecisionTool()

        tools["ask_clarification"] = clarification_tool
        tools["request_decision"] = decision_tool
        logger.info(
            f"Agent Worker: Human-in-the-loop tools (ask_clarification, request_decision) "
            f"added for project {project_id}"
        )
    except Exception as e:
        logger.warning(f"Agent Worker: Failed to create HITL tools: {e}")

    # 9. Add Todo Tools (DB-persistent task tracking)
    try:
        from src.infrastructure.adapters.secondary.persistence.database import (
            async_session_factory as todo_session_factory,
        )
        from src.infrastructure.agent.tools.todo_tools import TodoReadTool, TodoWriteTool

        tools["todoread"] = TodoReadTool(session_factory=todo_session_factory)
        tools["todowrite"] = TodoWriteTool(session_factory=todo_session_factory)
        logger.info(f"Agent Worker: Todo tools added for project {project_id}")
    except Exception as e:
        logger.warning(f"Agent Worker: Failed to create todo tools: {e}")

    # 10. Add RegisterMCPServerTool (register full MCP servers built in sandbox)
    try:
        from src.infrastructure.adapters.secondary.persistence.database import (
            async_session_factory as app_session_factory,
        )
        from src.infrastructure.agent.tools.register_mcp_server import RegisterMCPServerTool

        # Resolve sandbox_id from loaded sandbox tools
        sandbox_id_for_tools = None
        for tool in tools.values():
            if hasattr(tool, "sandbox_id") and tool.sandbox_id:
                sandbox_id_for_tools = tool.sandbox_id
                break

        register_server_tool = RegisterMCPServerTool(
            tenant_id=tenant_id,
            project_id=project_id,
            sandbox_adapter=_mcp_sandbox_adapter,
            sandbox_id=sandbox_id_for_tools,
            session_factory=app_session_factory,
        )
        tools["register_mcp_server"] = register_server_tool
        logger.info(f"Agent Worker: RegisterMCPServerTool added for project {project_id}")
    except Exception as e:
        logger.warning(f"Agent Worker: Failed to create RegisterMCPServerTool: {e}")

    # 11. Add Memory Tools (memory_search + memory_get)
    try:
        from src.infrastructure.adapters.secondary.persistence.database import (
            async_session_factory as mem_session_factory,
        )
        from src.infrastructure.agent.tools.memory_tools import MemoryGetTool, MemorySearchTool
        from src.infrastructure.memory.cached_embedding import CachedEmbeddingService
        from src.infrastructure.memory.chunk_search import ChunkHybridSearch

        embedding_service = getattr(graph_service, "embedder", None)
        if embedding_service and redis_client:
            cached_emb = CachedEmbeddingService(embedding_service, redis_client)
            chunk_search = ChunkHybridSearch(cached_emb, mem_session_factory)
            tools["memory_search"] = MemorySearchTool(
                chunk_search=chunk_search,
                graph_service=graph_service,
                project_id=project_id,
            )
            tools["memory_get"] = MemoryGetTool(
                session_factory=mem_session_factory,
                project_id=project_id,
            )
            logger.info(f"Agent Worker: Memory tools added for project {project_id}")
    except Exception as e:
        logger.debug(f"Agent Worker: Memory tools not available: {e}")

    # 12. Ensure plugin runtime is loaded before building plugin-provided tools.
    runtime_manager = get_plugin_runtime_manager()
    runtime_diagnostics = await runtime_manager.ensure_loaded()
    for diagnostic in runtime_diagnostics:
        _log_plugin_diagnostic(diagnostic, context="runtime_load")

    # 13. Add plugin tools registered via plugin runtime (phase-1 foundation).
    # Default behavior stays unchanged when no plugins are registered.
    plugin_registry = get_plugin_registry()
    plugin_tools, diagnostics = await plugin_registry.build_tools(
        PluginToolBuildContext(
            tenant_id=tenant_id,
            project_id=project_id,
            base_tools=tools,
        )
    )
    for diagnostic in diagnostics:
        _log_plugin_diagnostic(diagnostic, context="tool_build")
    if plugin_tools:
        tools.update(plugin_tools)
        logger.info(
            "Agent Worker: Added %d plugin tools for project %s",
            len(plugin_tools),
            project_id,
        )

    return tools


def _log_plugin_diagnostic(diagnostic: PluginDiagnostic, *, context: str) -> None:
    """Log plugin runtime diagnostics consistently."""
    message = (
        f"[AgentWorker][Plugin:{diagnostic.plugin_name}][{context}] "
        f"{diagnostic.code}: {diagnostic.message}"
    )
    if diagnostic.level == "error":
        logger.error(message)
        return
    if diagnostic.level == "info":
        logger.info(message)
        return
    logger.warning(message)


async def _load_project_sandbox_tools(
    project_id: str,
    tenant_id: str,
    redis_client: Optional[redis.Redis] = None,
) -> Dict[str, Any]:
    """Load MCP tools from project's sandbox.

    This function first queries the database for existing sandbox associations,
    then falls back to Docker discovery. It NEVER creates new sandboxes -
    sandbox creation is handled by ProjectSandboxLifecycleService.

    CRITICAL: This ensures API Server and Agent Worker use the SAME sandbox,

    Args:
        project_id: Project ID.
        tenant_id: Tenant ID.
        redis_client: Optional Redis client for distributed locking during MCP restore.
    preventing the duplicate container bug.

    Args:
        project_id: Project ID
        tenant_id: Tenant ID

    Returns:
        Dictionary of tool name -> SandboxMCPToolWrapper instances
    """
    import asyncio

    from src.infrastructure.agent.tools.sandbox_tool_wrapper import SandboxMCPToolWrapper

    tools: Dict[str, Any] = {}

    if _mcp_sandbox_adapter is None:
        return tools

    project_sandbox_id = None

    try:
        # STEP 1: Query DATABASE first (single source of truth)
        # This ensures we use the same sandbox that API Server created
        from src.infrastructure.adapters.secondary.persistence.database import (
            async_session_factory,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_project_sandbox_repository import (
            SqlProjectSandboxRepository,
        )

        async with async_session_factory() as db:
            sandbox_repo = SqlProjectSandboxRepository(db)
            assoc = await sandbox_repo.find_by_project(project_id)
            if assoc and assoc.sandbox_id:
                project_sandbox_id = assoc.sandbox_id
                logger.info(
                    f"[AgentWorker] Found sandbox_id from DB for project {project_id}: "
                    f"{project_sandbox_id}"
                )

        # STEP 2: If found in DB, verify container exists and sync to adapter
        if project_sandbox_id:
            # Sync from Docker to ensure adapter has the container in its cache
            if project_sandbox_id not in _mcp_sandbox_adapter._active_sandboxes:
                logger.info(
                    f"[AgentWorker] Syncing sandbox {project_sandbox_id} from Docker "
                    f"to adapter's internal state"
                )
                await _mcp_sandbox_adapter.sync_from_docker()

            # Verify container actually exists after sync
            if project_sandbox_id not in _mcp_sandbox_adapter._active_sandboxes:
                # Container might have been deleted - check if it's running in Docker
                container_exists = await _mcp_sandbox_adapter.container_exists(project_sandbox_id)
                if not container_exists:
                    logger.warning(
                        f"[AgentWorker] Sandbox {project_sandbox_id} in DB but container "
                        f"doesn't exist. Sandbox will be recreated by API on next access."
                    )
                    return tools

        # STEP 3: If not in DB, fall back to Docker discovery (for backwards compat)
        if not project_sandbox_id:
            logger.info(
                f"[AgentWorker] No sandbox association in DB for project {project_id}, "
                f"checking Docker directly..."
            )
            loop = asyncio.get_event_loop()

            # List all containers with memstack.sandbox label
            containers = await loop.run_in_executor(
                None,
                lambda: _mcp_sandbox_adapter._docker.containers.list(
                    all=True,
                    filters={"label": "memstack.sandbox=true"},
                ),
            )

            for container in containers:
                # Check if this container belongs to the project
                labels = container.labels or {}
                if labels.get("memstack.project_id") == project_id:
                    project_sandbox_id = container.name
                    # If container exists but is not running, try to start it
                    if container.status != "running":
                        logger.info(
                            f"[AgentWorker] Starting existing sandbox {project_sandbox_id} "
                            f"for project {project_id}"
                        )
                        await loop.run_in_executor(None, lambda c=container: c.start())
                        await asyncio.sleep(2)
                    break

                # Also check by project path
                mounts = container.attrs.get("Mounts", [])
                for mount in mounts:
                    source = mount.get("Source", "")
                    if source and f"memstack_{project_id}" in source:
                        project_sandbox_id = container.name
                        break
                if project_sandbox_id:
                    break

            # Sync to adapter if found in Docker
            if project_sandbox_id:
                if project_sandbox_id not in _mcp_sandbox_adapter._active_sandboxes:
                    await _mcp_sandbox_adapter.sync_from_docker()

        # STEP 4: If still no sandbox found, DON'T CREATE ONE
        # Let the API Server handle sandbox creation via ProjectSandboxLifecycleService
        if not project_sandbox_id:
            logger.info(
                f"[AgentWorker] No sandbox found for project {project_id}. "
                f"Sandbox will be created by API Server on first request."
            )
            return tools

        # STEP 5: Connect to MCP and load tools
        await _mcp_sandbox_adapter.connect_mcp(project_sandbox_id)

        # List tools from the sandbox
        tool_list = await _mcp_sandbox_adapter.list_tools(project_sandbox_id)

        # MCP management tools are internal, not exposed to agents
        _MCP_MANAGEMENT_TOOLS = {
            "mcp_server_install",
            "mcp_server_start",
            "mcp_server_stop",
            "mcp_server_list",
            "mcp_server_discover_tools",
            "mcp_server_call_tool",
        }

        # Wrap each tool with SandboxMCPToolWrapper
        for tool_info in tool_list:
            tool_name = tool_info.get("name", "")
            if not tool_name:
                continue

            # Skip internal MCP management tools
            if tool_name in _MCP_MANAGEMENT_TOOLS:
                continue

            wrapper = SandboxMCPToolWrapper(
                sandbox_id=project_sandbox_id,
                tool_name=tool_name,
                tool_schema=tool_info,
                sandbox_adapter=_mcp_sandbox_adapter,
            )

            # Use namespaced name as the key
            tools[wrapper.name] = wrapper

        logger.info(
            f"[AgentWorker] Loaded {len(tools)} tools from sandbox {project_sandbox_id} "
            f"for project {project_id}"
        )

        # STEP 6: Load user MCP server tools running inside the sandbox
        user_mcp_tools = await _load_user_mcp_server_tools(
            sandbox_adapter=_mcp_sandbox_adapter,
            sandbox_id=project_sandbox_id,
            project_id=project_id,
            redis_client=redis_client,
        )
        if user_mcp_tools:
            tools.update(user_mcp_tools)
            logger.info(
                f"[AgentWorker] Loaded {len(user_mcp_tools)} user MCP server tools "
                f"from sandbox {project_sandbox_id} for project {project_id}"
            )

            # Resolve MCPApp IDs for sandbox MCP tools so processor can emit app events.
            # This handles tools that declare _meta.ui. We fetch ALL project apps
            # from DB and fuzzy-match against all adapters.
            from src.infrastructure.mcp.sandbox_tool_adapter import SandboxMCPServerToolAdapter

            all_adapters = [
                t for t in user_mcp_tools.values() if isinstance(t, SandboxMCPServerToolAdapter)
            ]
            if all_adapters:
                try:
                    from src.infrastructure.adapters.secondary.persistence.sql_mcp_app_repository import (
                        SqlMCPAppRepository,
                    )

                    async with async_session_factory() as db:
                        app_repo = SqlMCPAppRepository(db)
                        project_apps = await app_repo.find_by_project(project_id)

                    logger.info(
                        "[AgentWorker] Found %d project apps, matching against %d adapters",
                        len(project_apps) if project_apps else 0,
                        len(all_adapters),
                    )
                    if project_apps:
                        for adapter in all_adapters:
                            matched_app = _match_adapter_to_app(adapter, project_apps)
                            if matched_app:
                                adapter._app_id = matched_app.id
                                if not adapter._ui_metadata and matched_app.ui_metadata:
                                    adapter._ui_metadata = matched_app.ui_metadata.to_dict()
                                logger.info(
                                    "[AgentWorker] Resolved MCPApp %s for tool %s (ui_metadata=%s)",
                                    matched_app.id,
                                    adapter.name,
                                    adapter._ui_metadata,
                                )
                            else:
                                logger.warning(
                                    "[AgentWorker] No MCPApp match for tool %s "
                                    "(server=%s, original=%s, has _ui_metadata=%s)",
                                    adapter.name,
                                    adapter._server_name,
                                    adapter._original_tool_name,
                                    adapter._ui_metadata is not None,
                                )
                except Exception as e:
                    logger.warning(f"[AgentWorker] Failed to resolve MCPApp IDs: {e}")

    except Exception as e:
        logger.warning(f"[AgentWorker] Failed to load project sandbox tools: {e}")
        import traceback

        logger.debug(f"[AgentWorker] Traceback: {traceback.format_exc()}")

    return tools


async def _discover_single_server_tools(
    sandbox_adapter: Any,
    sandbox_id: str,
    server_name: str,
) -> List[Dict[str, Any]]:
    """Discover tools from a single MCP server.

    This is a helper function for parallel discovery. It handles errors
    gracefully and returns an empty list on failure.

    Args:
        sandbox_adapter: MCPSandboxAdapter instance.
        sandbox_id: Sandbox container ID.
        server_name: Name of the MCP server to discover tools from.

    Returns:
        List of tool info dictionaries, or empty list on error.
    """
    try:
        discover_result = await sandbox_adapter.call_tool(
            sandbox_id=sandbox_id,
            tool_name="mcp_server_discover_tools",
            arguments={"name": server_name},
            timeout=20.0,  # Fast fail for tool discovery
        )

        if discover_result.get("is_error"):
            logger.warning(f"[AgentWorker] Failed to discover tools for server {server_name}")
            return []

        return _parse_discovered_tools(discover_result.get("content", []))

    except Exception as e:
        logger.warning(f"[AgentWorker] Error discovering tools for server {server_name}: {e}")
        return []


async def _discover_tools_for_servers_parallel(
    sandbox_adapter: Any,
    sandbox_id: str,
    servers: List[Dict[str, Any]],
    overall_timeout_seconds: Optional[float] = None,
) -> List[List[Dict[str, Any]]]:
    """Discover tools from multiple MCP servers in parallel.

    Uses asyncio.gather with return_exceptions=True to ensure that
    one server failure doesn't block discovery of other servers.

    If overall_timeout_seconds is specified, the entire operation will be
    wrapped with asyncio.wait_for, and partial results will be returned
    on timeout.

    Args:
        sandbox_adapter: MCPSandboxAdapter instance.
        sandbox_id: Sandbox container ID.
        servers: List of server info dictionaries with 'name' and 'status' keys.
        overall_timeout_seconds: Optional timeout for the entire discovery operation.
            If specified and timeout occurs, returns whatever results have been
            collected so far. Default is None (no timeout).

    Returns:
        List of tool lists, one per server (excluding failed/timed out servers).
    """
    # Filter to only running servers
    running_servers = [s for s in servers if s.get("name") and s.get("status") == "running"]

    if not running_servers:
        return []

    # Create discovery tasks for all running servers
    discovery_tasks = [
        _discover_single_server_tools(
            sandbox_adapter=sandbox_adapter,
            sandbox_id=sandbox_id,
            server_name=server_info["name"],
        )
        for server_info in running_servers
    ]

    # Execute all discoveries in parallel
    # return_exceptions=True ensures one failure doesn't block others
    if overall_timeout_seconds is not None:
        # Wrap with timeout - return partial results on timeout
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*discovery_tasks, return_exceptions=True),
                timeout=overall_timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning(
                f"[AgentWorker] Parallel discovery timed out after {overall_timeout_seconds}s "
                f"for {len(running_servers)} servers, returning empty results"
            )
            # On timeout, return empty list (no partial results available)
            return []
    else:
        # No timeout - wait for all to complete
        results = await asyncio.gather(*discovery_tasks, return_exceptions=True)

    # Filter out exceptions and empty results, but keep successful ones
    successful_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning(
                f"[AgentWorker] Discovery failed for {running_servers[i]['name']}: {result}"
            )
        elif isinstance(result, list) and result:
            successful_results.append(result)

    return successful_results


async def _load_user_mcp_server_tools(
    sandbox_adapter: Any,
    sandbox_id: str,
    project_id: str,
    redis_client: Optional[redis.Redis] = None,
) -> Dict[str, Any]:
    """Load user-configured MCP server tools running inside the sandbox.

    Calls mcp_server_list to discover running servers, then mcp_server_discover_tools
    for each to get their tools, wrapping them with SandboxMCPServerToolAdapter.

    If no servers are running but the DB has enabled servers configured,
    automatically installs and starts them (e.g. after sandbox restart).

    Args:
        sandbox_adapter: MCPSandboxAdapter instance.
        sandbox_id: Sandbox container ID.
        project_id: Project ID.
        redis_client: Optional Redis client for distributed locking during MCP restore.

    Returns:
        Dictionary of tool name -> SandboxMCPServerToolAdapter instances.
    """

    from src.infrastructure.mcp.sandbox_tool_adapter import SandboxMCPServerToolAdapter

    tools: Dict[str, Any] = {}

    try:
        # List running user MCP servers
        list_result = await sandbox_adapter.call_tool(
            sandbox_id=sandbox_id,
            tool_name="mcp_server_list",
            arguments={},
            timeout=10.0,
        )

        content = list_result.get("content", [])
        if list_result.get("is_error"):
            logger.warning("[AgentWorker] mcp_server_list returned error")
            return tools

        # Parse server list from response
        servers = _parse_mcp_server_list(content)
        running_names = {s.get("name") for s in servers if s.get("status") == "running"}

        # Auto-restore: if DB has enabled servers not running, install & start them
        await _auto_restore_mcp_servers(
            sandbox_adapter=sandbox_adapter,
            sandbox_id=sandbox_id,
            project_id=project_id,
            running_names=running_names,
            redis_client=redis_client,
        )

        # Re-list if we restored any servers
        if not running_names:
            list_result = await sandbox_adapter.call_tool(
                sandbox_id=sandbox_id,
                tool_name="mcp_server_list",
                arguments={},
                timeout=10.0,
            )
            content = list_result.get("content", [])
            servers = _parse_mcp_server_list(content)

        # Discover tools from all running servers in parallel
        discovery_results = await _discover_tools_for_servers_parallel(
            sandbox_adapter=sandbox_adapter,
            sandbox_id=sandbox_id,
            servers=servers,
        )

        # Create adapters for all discovered tools
        # We need to map back to server names for adapter creation
        running_servers = [s for s in servers if s.get("name") and s.get("status") == "running"]

        for i, discovered_tools in enumerate(discovery_results):
            if i < len(running_servers):
                server_name = running_servers[i]["name"]
                for tool_info in discovered_tools:
                    adapter = SandboxMCPServerToolAdapter(
                        sandbox_adapter=sandbox_adapter,
                        sandbox_id=sandbox_id,
                        server_name=server_name,
                        tool_info=tool_info,
                    )
                    tools[adapter.name] = adapter

    except Exception as e:
        logger.warning(f"[AgentWorker] Error loading user MCP server tools: {e}")

    return tools


async def _auto_restore_mcp_servers(
    sandbox_adapter: Any,
    sandbox_id: str,
    project_id: str,
    running_names: set,
    redis_client: Optional[redis.Redis] = None,
) -> None:
    """Auto-restore enabled MCP servers from DB that aren't running in sandbox.

    Called during tool loading to ensure MCP servers survive sandbox restarts.
    Each server is installed and started via the sandbox's management tools.
    Failures are logged but don't block other servers or tool loading.

    Uses distributed lock when redis_client is provided to prevent race conditions
    when multiple workers attempt to restore the same MCP server simultaneously.

    Args:
        sandbox_adapter: MCP sandbox adapter for calling tools.
        sandbox_id: Target sandbox container ID.
        project_id: Project ID for DB lookup.
        running_names: Set of MCP server names already running in sandbox.
        redis_client: Optional Redis client for distributed locking.
                     If None, falls back to no-lock behavior (backward compatible).

    Lock Behavior:
        - Lock key format: memstack:lock:mcp_restore:{project_id}:{server_name}
        - Lock TTL: 60 seconds
        - Non-blocking: If lock cannot be acquired, skip that server
        - Double-check: Server is re-checked inside lock before restore
    """
    import uuid

    try:
        from src.infrastructure.adapters.secondary.persistence.database import (
            async_session_factory,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
            SqlMCPServerRepository,
        )

        async with async_session_factory() as session:
            repo = SqlMCPServerRepository(session)
            db_servers = await repo.list_by_project(project_id, enabled_only=True)

        # Find servers that need restoring
        servers_to_restore = [s for s in db_servers if s.name and s.name not in running_names]

        if not servers_to_restore:
            return

        logger.info(
            f"[AgentWorker] Auto-restoring {len(servers_to_restore)} MCP servers "
            f"for project {project_id}: "
            f"{[s.name for s in servers_to_restore]}"
        )

        for server in servers_to_restore:
            server_name = server.name
            server_type = server.server_type or "stdio"
            transport_config = server.transport_config or {}

            # Use distributed lock if redis_client is available
            if redis_client is not None:
                lock_key = f"memstack:lock:mcp_restore:{project_id}:{server_name}"
                lock_owner = str(uuid.uuid4())
                lock_ttl = 60

                # Try to acquire lock (non-blocking)
                acquired = await redis_client.set(lock_key, lock_owner, nx=True, ex=lock_ttl)

                if not acquired:
                    logger.debug(
                        f"[AgentWorker] Skip restore '{server_name}': lock held by another worker"
                    )
                    continue

                try:
                    # Double-check: Re-verify server is still not running inside lock
                    # (another worker may have just restored it)
                    try:
                        list_result = await sandbox_adapter.call_tool(
                            sandbox_id=sandbox_id,
                            tool_name="mcp_server_list",
                            arguments={},
                            timeout=10.0,
                        )
                        current_servers = _parse_mcp_server_list(list_result.get("content", []))
                        current_running = {
                            s.get("name") for s in current_servers if s.get("status") == "running"
                        }
                        if server_name in current_running:
                            logger.debug(
                                f"[AgentWorker] Skip restore '{server_name}': "
                                f"already running (double-check)"
                            )
                            continue
                    except Exception as e:
                        logger.warning(
                            f"[AgentWorker] Double-check failed for '{server_name}': {e}"
                        )
                        # Continue with restore if double-check fails

                    # Perform restore inside lock
                    restored, restore_error = await _restore_single_server(
                        sandbox_adapter=sandbox_adapter,
                        sandbox_id=sandbox_id,
                        server_name=server_name,
                        server_type=server_type,
                        transport_config=transport_config,
                    )
                    server_id = getattr(server, "id", None)
                    server_tenant_id = getattr(server, "tenant_id", None)
                    if server_id and server_tenant_id:
                        await _persist_restore_lifecycle_result(
                            tenant_id=server_tenant_id,
                            project_id=project_id,
                            server_id=server_id,
                            restored=restored,
                            error_message=restore_error,
                        )

                finally:
                    # Release lock (only if we own it)
                    try:
                        current_owner = await redis_client.get(lock_key)
                        if current_owner == lock_owner:
                            await redis_client.delete(lock_key)
                    except Exception as e:
                        logger.warning(
                            f"[AgentWorker] Failed to release lock for '{server_name}': {e}"
                        )
            else:
                # Fallback: No lock (backward compatible)
                restored, restore_error = await _restore_single_server(
                    sandbox_adapter=sandbox_adapter,
                    sandbox_id=sandbox_id,
                    server_name=server_name,
                    server_type=server_type,
                    transport_config=transport_config,
                )
                server_id = getattr(server, "id", None)
                server_tenant_id = getattr(server, "tenant_id", None)
                if server_id and server_tenant_id:
                    await _persist_restore_lifecycle_result(
                        tenant_id=server_tenant_id,
                        project_id=project_id,
                        server_id=server_id,
                        restored=restored,
                        error_message=restore_error,
                    )

    except Exception as e:
        logger.warning(f"[AgentWorker] Error in auto-restore MCP servers: {e}")


async def _restore_single_server(
    sandbox_adapter: Any,
    sandbox_id: str,
    server_name: str,
    server_type: str,
    transport_config: dict,
) -> tuple[bool, Optional[str]]:
    """Restore a single MCP server by installing and starting it.

    Args:
        sandbox_adapter: MCP sandbox adapter.
        sandbox_id: Target sandbox ID.
        server_name: MCP server name.
        server_type: Server type (e.g., 'stdio').
        transport_config: Transport configuration dict.

    Returns:
        Tuple[success, error_message].
    """
    import json

    try:
        config_json = json.dumps(transport_config)

        # Install
        install_result = await sandbox_adapter.call_tool(
            sandbox_id=sandbox_id,
            tool_name="mcp_server_install",
            arguments={
                "name": server_name,
                "server_type": server_type,
                "transport_config": config_json,
            },
            timeout=120.0,
        )
        if install_result.get("is_error"):
            error_message = f"install failed: {install_result}"
            logger.warning(
                f"[AgentWorker] Failed to install MCP server '{server_name}': {install_result}"
            )
            return False, error_message

        # Start
        start_result = await sandbox_adapter.call_tool(
            sandbox_id=sandbox_id,
            tool_name="mcp_server_start",
            arguments={
                "name": server_name,
                "server_type": server_type,
                "transport_config": config_json,
            },
            timeout=60.0,
        )
        if start_result.get("is_error"):
            error_message = f"start failed: {start_result}"
            logger.warning(
                f"[AgentWorker] Failed to start MCP server '{server_name}': {start_result}"
            )
            return False, error_message

        logger.info(
            f"[AgentWorker] Auto-restored MCP server '{server_name}' in sandbox {sandbox_id}"
        )
        return True, None

    except Exception as e:
        logger.warning(f"[AgentWorker] Error restoring MCP server '{server_name}': {e}")
        return False, str(e)


async def _persist_restore_lifecycle_result(
    tenant_id: str,
    project_id: str,
    server_id: str,
    restored: bool,
    error_message: Optional[str],
) -> None:
    """Persist auto-restore metadata and audit event."""
    import uuid

    from src.infrastructure.adapters.secondary.persistence.database import (
        async_session_factory,
    )
    from src.infrastructure.adapters.secondary.persistence.models import MCPLifecycleEvent
    from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
        SqlMCPServerRepository,
    )

    try:
        async with async_session_factory() as session:
            repo = SqlMCPServerRepository(session)
            await repo.update_runtime_metadata(
                server_id=server_id,
                runtime_status="running" if restored else "error",
                runtime_metadata={
                    "last_auto_restore_at": datetime.now(timezone.utc).isoformat(),
                    "last_auto_restore_status": "success" if restored else "failed",
                    "last_error": error_message if error_message else "",
                },
            )
            session.add(
                MCPLifecycleEvent(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    project_id=project_id,
                    server_id=server_id,
                    app_id=None,
                    event_type="server.auto_restore",
                    status="success" if restored else "failed",
                    error_message=error_message,
                    metadata_json={},
                )
            )
            await session.commit()
    except Exception as e:
        logger.warning(
            "[AgentWorker] Failed to persist MCP auto-restore metadata for server %s: %s",
            server_id,
            e,
        )


def _parse_mcp_server_list(content: list) -> list:
    """Parse server list from mcp_server_list tool response."""
    import json

    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            text = item.get("text", "")
            try:
                data = json.loads(text)
                if isinstance(data, dict) and "servers" in data:
                    return data["servers"]
                if isinstance(data, list):
                    return data
            except (json.JSONDecodeError, TypeError):
                pass
    return []


def _parse_discovered_tools(content: list) -> list:
    """Parse tool list from mcp_server_discover_tools response."""
    import json

    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            text = item.get("text", "")
            try:
                data = json.loads(text)
                if isinstance(data, dict) and "tools" in data:
                    return data["tools"]
                if isinstance(data, list):
                    return data
            except (json.JSONDecodeError, TypeError):
                pass
    return []


def _match_adapter_to_app(adapter: Any, apps: list) -> Any:
    """Match a SandboxMCPServerToolAdapter to an MCPApp from DB.

    Matching strategy (in priority order):
    1. Exact server_name + tool_name match (score: 1.0)
    2. Normalized server_name + tool_name match (score: 0.8)
       - Handles hyphens vs underscores
    3. Fuzzy server_name match with usability check (score: 0.5)
       - Requires resource HTML or ui_metadata

    Args:
        adapter: SandboxMCPServerToolAdapter instance
        apps: List of MCPApp domain objects from DB

    Returns:
        Matched MCPApp or None
    """
    matched_app, _ = _match_adapter_to_app_with_score(adapter, apps)
    return matched_app


def _match_adapter_to_app_with_score(adapter: Any, apps: list) -> tuple:
    """Match a SandboxMCPServerToolAdapter to an MCPApp from DB with confidence score.

    This function returns both the matched app and a confidence score,
    useful for debugging and logging match attempts.

    Matching strategy (in priority order):
    1. Exact server_name + tool_name match (score: 1.0)
    2. Normalized server_name + tool_name match (score: 0.8)
       - Handles hyphens vs underscores
    3. Fuzzy server_name match with usability check (score: 0.5)
       - Requires resource HTML or ui_metadata

    Args:
        adapter: SandboxMCPServerToolAdapter instance
        apps: List of MCPApp domain objects from DB

    Returns:
        Tuple of (matched MCPApp or None, confidence score 0.0-1.0)
    """
    adapter_server = getattr(adapter, "_server_name", "")
    adapter_tool = getattr(adapter, "_original_tool_name", "")

    if not adapter_server:
        logger.debug("MCPApp matching: adapter has no server_name")
        return None, 0.0

    if not apps:
        logger.debug(f"MCPApp matching: no apps to match against for {adapter_server}")
        return None, 0.0

    # Normalize for comparison: lowercase, replace hyphens with underscores
    def _norm(s: str) -> str:
        return s.lower().replace("-", "_")

    norm_server = _norm(adapter_server)
    norm_tool = _norm(adapter_tool)

    # Log match attempt details at debug level
    logger.debug(
        f"MCPApp matching: attempting to match adapter "
        f"(server={adapter_server}, tool={adapter_tool}) against {len(apps)} apps"
    )

    # Priority 1: exact server_name + tool_name (score: 1.0)
    for app in apps:
        if app.server_name == adapter_server and app.tool_name == adapter_tool:
            logger.debug(
                f"MCPApp matching: EXACT match found - "
                f"adapter({adapter_server}/{adapter_tool}) -> app({app.server_name}/{app.tool_name}) "
                f"[id={app.id}, score=1.0]"
            )
            return app, 1.0

    # Priority 2: normalized server_name + tool_name (score: 0.8)
    for app in apps:
        if _norm(app.server_name) == norm_server and _norm(app.tool_name) == norm_tool:
            logger.debug(
                f"MCPApp matching: NORMALIZED match found - "
                f"adapter({adapter_server}/{adapter_tool}) -> app({app.server_name}/{app.tool_name}) "
                f"[id={app.id}, score=0.8]"
            )
            return app, 0.8

    # Priority 3: fuzzy server_name match with usability check (score: 0.5)
    for app in apps:
        app_norm = _norm(app.server_name)
        if norm_server in app_norm or app_norm in norm_server:
            # Accept apps with resource HTML or ui_metadata (resourceUri-based apps)
            if (app.resource and app.resource.html_content) or app.ui_metadata:
                logger.debug(
                    f"MCPApp matching: FUZZY match found - "
                    f"adapter({adapter_server}/{adapter_tool}) -> app({app.server_name}/{app.tool_name}) "
                    f"[id={app.id}, score=0.5, has_ui=True]"
                )
                return app, 0.5

    # No match found - log candidates for debugging
    candidate_info = [
        f"({app.server_name}/{app.tool_name}, id={app.id})"
        for app in apps[:5]  # Limit to first 5 for log readability
    ]
    logger.warning(
        f"MCPApp matching: NO MATCH found - "
        f"adapter(server={adapter_server}, tool={adapter_tool}) "
        f"candidates=[{', '.join(candidate_info)}]"
    )

    return None, 0.0


def get_cached_tools() -> Dict[str, Dict[str, Any]]:
    """Get all cached tool sets (for debugging/monitoring)."""
    return dict(_tools_cache)


def get_cached_tools_for_project(project_id: str) -> Optional[Dict[str, Any]]:
    """Get cached tools for a specific project (synchronous, for hot-plug support).

    This is used by ReActAgent's tool_provider to get current tools without
    async overhead. Returns None if tools not yet cached (caller should use
    get_or_create_tools() first to populate cache).

    Args:
        project_id: Project ID to get tools for

    Returns:
        Dictionary of tool name -> tool instance, or None if not cached
    """
    return _tools_cache.get(project_id)


def invalidate_tools_cache(project_id: Optional[str] = None) -> None:
    """Invalidate tool cache for a project or all projects.

    Args:
        project_id: Project ID to invalidate, or None to invalidate all
    """
    global _tools_cache
    if project_id:
        _tools_cache.pop(project_id, None)
        logger.info(f"Agent Worker: Tool cache invalidated for project {project_id}")
    else:
        _tools_cache.clear()
        logger.info("Agent Worker: All tool caches invalidated")


def invalidate_all_caches_for_project(
    project_id: str,
    tenant_id: Optional[str] = None,
    clear_tool_definitions: bool = True,
) -> Dict[str, Any]:
    """Invalidate all caches related to a project.

    This unified function clears all caches that may contain stale data after
    MCP tools are registered or updated. It should be called after:
    - register_mcp_server tool execution
    - MCP server enable/disable/sync operations
    - Any operation that changes available tools for a project

    Caches invalidated (in order):
    1. tools_cache[project_id] - Built-in tool instances
    2. agent_sessions (tenant:project:*) - Session contexts with tool definitions
    3. tool_definitions_cache (all if clear_tool_definitions=True) - Converted tools
    4. mcp_tools_cache[tenant_id] - MCP tools from workflows (if tenant_id provided)

    Args:
        project_id: Project ID to invalidate caches for
        tenant_id: Optional tenant ID for MCP tools cache invalidation
        clear_tool_definitions: Whether to clear tool definitions cache (default: True)

    Returns:
        Dictionary with invalidation summary:
        {
            "project_id": str,
            "tenant_id": Optional[str],
            "invalidated": {
                "tools_cache": int,
                "agent_sessions": int,
                "tool_definitions": int,
                "mcp_tools": int,
            }
        }
    """
    invalidated = {
        "tools_cache": 0,
        "agent_sessions": 0,
        "tool_definitions": 0,
        "mcp_tools": 0,
    }

    # 1. Invalidate tools_cache for this project
    if project_id in _tools_cache:
        del _tools_cache[project_id]
        invalidated["tools_cache"] = 1
        logger.info(f"Agent Worker: tools_cache invalidated for project {project_id}")

    # 2. Invalidate agent sessions for this project
    # Sessions are keyed by tenant_id:project_id:agent_mode
    sessions_invalidated = invalidate_agent_session(
        tenant_id=tenant_id,
        project_id=project_id,
    )
    invalidated["agent_sessions"] = sessions_invalidated
    if sessions_invalidated > 0:
        logger.info(
            f"Agent Worker: Invalidated {sessions_invalidated} agent sessions "
            f"for project {project_id}"
        )

    # 3. Invalidate tool definitions cache (if requested)
    # Tool definitions are keyed by tools_hash, which changes when tools change.
    # We clear all entries since we can't know which hashes correspond to this project.
    if clear_tool_definitions:
        invalidated["tool_definitions"] = invalidate_tool_definitions_cache()

    # 4. Invalidate MCP tools cache for tenant (if tenant_id provided)
    if tenant_id:
        invalidated["mcp_tools"] = invalidate_mcp_tools_cache(tenant_id)

    logger.info(
        f"Agent Worker: Cache invalidation complete for project {project_id}: {invalidated}"
    )

    return {
        "project_id": project_id,
        "tenant_id": tenant_id,
        "invalidated": invalidated,
    }


# ============================================================================
# Skills Caching
# ============================================================================


async def get_or_create_skills(
    tenant_id: str,
    project_id: Optional[str] = None,
) -> list:
    """Get or create a cached skills list for a tenant/project.

    This function caches skills by tenant_id:project_id key to avoid
    repeated file system scanning overhead.

    Args:
        tenant_id: Tenant ID for cache key
        project_id: Optional project ID for cache key

    Returns:
        List of Skill domain entities
    """
    from pathlib import Path

    from src.application.services.filesystem_skill_loader import FileSystemSkillLoader
    from src.infrastructure.skill.filesystem_scanner import FileSystemSkillScanner

    cache_key = f"{tenant_id}:{project_id or 'global'}"

    async with _skills_cache_lock:
        if cache_key not in _skills_cache:
            # Use current working directory as base path for skill scanning
            base_path = Path.cwd()

            # Create scanner with standard skill directories
            scanner = FileSystemSkillScanner(
                skill_dirs=[".memstack/skills/"],
            )

            # Create file system loader
            fs_loader = FileSystemSkillLoader(
                base_path=base_path,
                tenant_id=tenant_id,
                project_id=project_id,
                scanner=scanner,
            )

            # Load all skills
            result = await fs_loader.load_all()

            # Extract Skill domain entities
            skills = [loaded.skill for loaded in result.skills]

            _skills_cache[cache_key] = skills
            logger.info(
                f"Agent Worker: Skills cached for {cache_key}, "
                f"loaded {len(skills)} skills, errors: {len(result.errors)}"
            )
            if result.errors:
                for error in result.errors:
                    logger.warning(f"Agent Worker: Skill loading error: {error}")

        return _skills_cache[cache_key]


async def get_or_create_provider_config(
    tenant_id: Optional[str] = None,
    force_refresh: bool = False,
) -> Any:
    """Get or create cached default LLM provider config.

    Delegates to AIServiceFactory which handles caching and provider resolution.

    Args:
        tenant_id: Tenant ID for provider resolution (optional for backward compat)
        force_refresh: Force refresh from database (ignored by factory for now, relying on LRU)

    Returns:
        ProviderConfig instance
    """
    from src.infrastructure.llm.provider_factory import get_ai_service_factory

    # If tenant_id not provided, default to "default" to ensure we get *some* config
    # This maintains behavior of "system global default" if no tenant specified
    if not tenant_id:
        tenant_id = "default"

    factory = get_ai_service_factory()
    return await factory.resolve_provider(tenant_id)


async def get_or_create_llm_client(
    provider_config: Any = None,
    tenant_id: Optional[str] = None,
) -> Any:
    """Get or create a cached LLM client using AIServiceFactory.

    Delegates to AIServiceFactory which handles caching and provider resolution.

    Args:
        provider_config: Legacy argument, ignored in favor of tenant_id resolution
        tenant_id: Tenant ID for provider resolution

    Returns:
        Cached or newly created LLM client
    """
    from src.infrastructure.llm.provider_factory import get_ai_service_factory

    # If tenant_id not provided, we might have issues resolving the correct provider.
    # But for backward compatibility with tests/legacy calls that pass provider_config,
    # we might need to handle it. However, the goal is to enforce tenant isolation.
    # Since we updated the main caller (ProjectReActAgent), we assume tenant_id is present.

    if not tenant_id:
        # Fallback to "default" tenant if not provided
        logger.warning("get_or_create_llm_client called without tenant_id, using 'default'")
        tenant_id = "default"

    factory = get_ai_service_factory()
    # Resolve provider config first
    resolved_config = await factory.resolve_provider(tenant_id)
    # Create client using resolved config
    return factory.create_llm_client(resolved_config)


def get_cached_skills() -> Dict[str, list]:
    """Get all cached skill lists (for debugging/monitoring)."""
    return dict(_skills_cache)


def invalidate_skills_cache(tenant_id: Optional[str] = None) -> None:
    """Invalidate skills cache for a tenant or all tenants.

    Args:
        tenant_id: Tenant ID to invalidate (partial match), or None to invalidate all
    """
    global _skills_cache
    if tenant_id:
        keys_to_remove = [k for k in _skills_cache if k.startswith(f"{tenant_id}:")]
        for key in keys_to_remove:
            _skills_cache.pop(key, None)
        logger.info(f"Agent Worker: Skills cache invalidated for tenant {tenant_id}")
    else:
        _skills_cache.clear()
        logger.info("Agent Worker: All skills caches invalidated")


# ============================================================================
# SkillLoaderTool Caching
# ============================================================================


async def get_or_create_skill_loader_tool(
    tenant_id: str,
    project_id: Optional[str] = None,
    agent_mode: str = "default",
) -> Any:
    """Get or create a cached and initialized SkillLoaderTool.

    This function caches SkillLoaderTool instances by tenant_id:project_id:agent_mode
    key. The tool is initialized with skill metadata so its description contains
    the available skills list for LLM to see.

    Reference: OpenCode SkillTool pattern - skills embedded in tool description
    allows LLM to make autonomous decisions about which skill to load.

    Args:
        tenant_id: Tenant ID for skill scoping
        project_id: Optional project ID for filtering
        agent_mode: Agent mode for filtering skills (e.g., "default", "plan")

    Returns:
        Initialized SkillLoaderTool instance with dynamic description
    """
    from pathlib import Path
    from typing import List, Optional as Opt

    from src.application.services.filesystem_skill_loader import FileSystemSkillLoader
    from src.application.services.skill_service import SkillService
    from src.domain.model.agent.skill import Skill, SkillStatus
    from src.domain.ports.repositories.skill_repository import SkillRepositoryPort
    from src.infrastructure.agent.tools.skill_loader import SkillLoaderTool
    from src.infrastructure.skill.filesystem_scanner import FileSystemSkillScanner

    # Create a NullSkillRepository for SkillService
    # We only use filesystem skills (skip_database=True), so no DB operations needed
    class NullSkillRepository(SkillRepositoryPort):
        """Null implementation - all methods return empty/None."""

        async def create(self, skill: Skill) -> Skill:
            return skill

        async def get_by_id(self, skill_id: str) -> Opt[Skill]:
            return None

        async def get_by_name(self, tenant_id: str, name: str) -> Opt[Skill]:
            return None

        async def list_by_tenant(
            self, tenant_id: str, status: Opt[SkillStatus] = None
        ) -> List[Skill]:
            return []

        async def list_by_project(
            self, project_id: str, status: Opt[SkillStatus] = None
        ) -> List[Skill]:
            return []

        async def update(self, skill: Skill) -> Skill:
            return skill

        async def delete(self, skill_id: str) -> None:
            pass

        async def find_matching_skills(
            self,
            tenant_id: str,
            query: str,
            threshold: float = 0.5,
            limit: int = 5,
        ) -> List[Skill]:
            return []

        async def increment_usage(self, skill_id: str, success: bool = True) -> None:
            pass

        async def count_by_tenant(self, tenant_id: str, status: Opt[SkillStatus] = None) -> int:
            return 0

    cache_key = f"{tenant_id}:{project_id or 'global'}:{agent_mode}"

    async with _skill_loader_cache_lock:
        if cache_key not in _skill_loader_cache:
            # Use current working directory as base path
            base_path = Path.cwd()

            # Create scanner with standard skill directories
            scanner = FileSystemSkillScanner(
                skill_dirs=[".memstack/skills/"],
            )

            # Create file system loader
            fs_loader = FileSystemSkillLoader(
                base_path=base_path,
                tenant_id=tenant_id,
                project_id=project_id,
                scanner=scanner,
            )

            # Create SkillService with NullSkillRepository (we only use filesystem skills)
            skill_service = SkillService(
                skill_repository=NullSkillRepository(),
                filesystem_loader=fs_loader,
            )

            # Create SkillLoaderTool
            tool = SkillLoaderTool(
                skill_service=skill_service,
                tenant_id=tenant_id,
                project_id=project_id,
                agent_mode=agent_mode,
            )

            # Initialize from cached skills to avoid double filesystem scan
            cached_skills = await get_or_create_skills(
                tenant_id=tenant_id,
                project_id=project_id,
            )
            filtered_skills = [
                skill
                for skill in cached_skills
                if "*" in getattr(skill, "agent_modes", ["*"])
                or agent_mode in getattr(skill, "agent_modes", [])
            ]
            await tool.initialize_with_skills(filtered_skills)

            _skill_loader_cache[cache_key] = tool
            logger.info(
                f"Agent Worker: SkillLoaderTool cached for {cache_key}, "
                f"skills in description: {len(tool.get_available_skills())}"
            )

        return _skill_loader_cache[cache_key]


def get_cached_skill_loaders() -> Dict[str, Any]:
    """Get all cached SkillLoaderTool instances (for debugging/monitoring)."""
    return dict(_skill_loader_cache)


def invalidate_skill_loader_cache(tenant_id: Optional[str] = None) -> None:
    """Invalidate SkillLoaderTool cache for a tenant or all tenants.

    Args:
        tenant_id: Tenant ID to invalidate (partial match), or None to invalidate all
    """
    global _skill_loader_cache
    if tenant_id:
        keys_to_remove = [k for k in _skill_loader_cache if k.startswith(f"{tenant_id}:")]
        for key in keys_to_remove:
            _skill_loader_cache.pop(key, None)
        logger.info(f"Agent Worker: SkillLoaderTool cache invalidated for tenant {tenant_id}")
    else:
        _skill_loader_cache.clear()
        logger.info("Agent Worker: All SkillLoaderTool caches invalidated")


# ==========================================================================
# Prewarm Helpers
# ==========================================================================


async def prewarm_agent_session(
    tenant_id: str,
    project_id: str,
    agent_mode: str = "default",
    mcp_tools_ttl_seconds: int = 300,
) -> None:
    """Prewarm tools, skills, and agent session cache for a tenant/project.

    This is used to reduce first-request latency by warming caches
    outside of the critical request path.
    """
    try:
        graph_service = await get_or_create_agent_graph_service(tenant_id=tenant_id)

        redis_client = await get_redis_client()

        provider_config = await get_or_create_provider_config()
        llm_client = await get_or_create_llm_client(provider_config)

        tools = await get_or_create_tools(
            project_id=project_id,
            tenant_id=tenant_id,
            graph_service=graph_service,
            redis_client=redis_client,
            llm=llm_client,
            agent_mode=agent_mode,
            mcp_tools_ttl_seconds=mcp_tools_ttl_seconds,
        )

        skills = await get_or_create_skills(
            tenant_id=tenant_id,
            project_id=project_id,
        )

        from src.infrastructure.agent.core.processor import ProcessorConfig

        processor_config = ProcessorConfig(
            model="",
            api_key="",
            base_url=None,
            temperature=0.7,
            max_tokens=4096,
            max_steps=20,
        )

        await get_or_create_agent_session(
            tenant_id=tenant_id,
            project_id=project_id,
            agent_mode=agent_mode,
            tools=tools,
            skills=skills,
            subagents=[],
            processor_config=processor_config,
        )

        logger.info(
            f"Agent Worker: Prewarmed session cache for tenant={tenant_id}, project={project_id}"
        )
    except Exception as e:
        logger.warning(
            f"Agent Worker: Prewarm failed for tenant={tenant_id}, project={project_id}: {e}"
        )


# ============================================================================
# HITL Response Listener State (Real-time Delivery)
# ============================================================================


def set_hitl_response_listener(listener: Any) -> None:
    """Set the global HITL Response Listener instance for agent worker.

    Called during Agent Worker initialization to enable real-time
    HITL response delivery via Redis Streams.

    Args:
        listener: The HITLResponseListener instance
    """
    global _hitl_response_listener
    _hitl_response_listener = listener
    logger.info("Agent Worker: HITL Response Listener registered for Activities")


def get_hitl_response_listener() -> Optional[Any]:
    """Get the global HITL Response Listener instance for agent worker.

    Returns:
        The HITLResponseListener instance or None if not initialized
    """
    return _hitl_response_listener


def get_session_registry():
    """Get the AgentSessionRegistry for HITL waiter tracking.

    Returns:
        AgentSessionRegistry instance (singleton per worker)
    """
    from src.infrastructure.agent.hitl.session_registry import (
        get_session_registry as _get_registry,
    )

    return _get_registry()


async def register_hitl_waiter(
    request_id: str,
    conversation_id: str,
    hitl_type: str,
    tenant_id: str,
    project_id: str,
) -> bool:
    """
    Register an HITL waiter and add project to listener.

    This is the main entry point for Activities to register
    that they're waiting for an HITL response.

    Args:
        request_id: HITL request ID
        conversation_id: Conversation ID
        hitl_type: Type of HITL
        tenant_id: Tenant ID
        project_id: Project ID

    Returns:
        True if registered successfully
    """
    registry = get_session_registry()
    await registry.register_waiter(
        request_id=request_id,
        conversation_id=conversation_id,
        hitl_type=hitl_type,
    )

    # Ensure listener is monitoring this project
    if _hitl_response_listener:
        await _hitl_response_listener.add_project(tenant_id, project_id)

    logger.debug(
        f"Agent Worker: Registered HITL waiter: request={request_id}, project={project_id}"
    )
    return True


async def unregister_hitl_waiter(request_id: str) -> bool:
    """
    Unregister an HITL waiter after response received or timeout.

    Args:
        request_id: HITL request ID

    Returns:
        True if unregistered successfully
    """
    registry = get_session_registry()
    return await registry.unregister_waiter(request_id)


async def wait_for_hitl_response_realtime(
    request_id: str,
    timeout: float = 5.0,
) -> Optional[Dict[str, Any]]:
    """
    Wait for HITL response via real-time Redis Stream delivery.

    This is a fast-path check before falling back to Temporal Signal.
    Returns quickly if response arrives via Redis, or None if timeout.

    Args:
        request_id: HITL request ID
        timeout: Max seconds to wait (should be short, e.g., 5s)

    Returns:
        Response data if delivered via Redis, None otherwise
    """
    registry = get_session_registry()
    return await registry.wait_for_response(request_id, timeout=timeout)


# ============================================================================
# Tool Discovery with Retry (exponential backoff)
# ============================================================================


async def discover_tools_with_retry(
    sandbox_adapter: Any,
    sandbox_id: str,
    server_name: str,
    max_retries: int = 3,
    base_delay_ms: int = 1000,
    max_delay_ms: int = 30000,
    timeout: float = 30.0,
) -> Optional[Dict[str, Any]]:
    """
    Discover MCP server tools with exponential backoff retry.

    Retries on transient errors (connection issues, timeouts) with
    exponentially increasing delays between attempts.

    Args:
        sandbox_adapter: MCPSandboxAdapter instance
        sandbox_id: Sandbox container ID
        server_name: Name of the MCP server
        max_retries: Maximum number of retry attempts (default: 3)
        base_delay_ms: Base delay in milliseconds (default: 1000)
        max_delay_ms: Maximum delay cap in milliseconds (default: 30000)
        timeout: Tool call timeout in seconds (default: 30.0)

    Returns:
        Discovery result dict if successful, None if all retries exhausted
    """
    import random

    for attempt in range(max_retries + 1):  # +1 for initial attempt
        try:
            result = await sandbox_adapter.call_tool(
                sandbox_id=sandbox_id,
                tool_name="mcp_server_discover_tools",
                arguments={"name": server_name},
                timeout=timeout,
            )

            # Check for error
            if result.get("is_error") or result.get("isError"):
                # Check if it's a transient error worth retrying
                error_text = _extract_error_text(result)
                is_transient = _is_transient_error(error_text)

                if is_transient and attempt < max_retries:
                    delay_ms = min(base_delay_ms * (2**attempt), max_delay_ms)
                    # Add jitter (±10%)
                    jitter = delay_ms * 0.1 * random.random()
                    actual_delay = (delay_ms + jitter) / 1000  # Convert to seconds

                    logger.warning(
                        f"[AgentWorker] Tool discovery transient error for '{server_name}' "
                        f"(attempt {attempt + 1}/{max_retries + 1}): {error_text}. "
                        f"Retrying in {actual_delay:.2f}s..."
                    )
                    await asyncio.sleep(actual_delay)
                    continue
                else:
                    logger.warning(
                        f"[AgentWorker] Tool discovery failed for '{server_name}' "
                        f"after {attempt + 1} attempts: {error_text}"
                    )
                    return None

            # Success!
            if attempt > 0:
                logger.info(
                    f"[AgentWorker] Tool discovery succeeded for '{server_name}' "
                    f"on attempt {attempt + 1}"
                )
            return result

        except Exception as e:
            error_text = str(e)
            is_transient = _is_transient_error(error_text)

            if is_transient and attempt < max_retries:
                delay_ms = min(base_delay_ms * (2**attempt), max_delay_ms)
                jitter = delay_ms * 0.1 * random.random()
                actual_delay = (delay_ms + jitter) / 1000

                logger.warning(
                    f"[AgentWorker] Tool discovery exception for '{server_name}' "
                    f"(attempt {attempt + 1}/{max_retries + 1}): {e}. "
                    f"Retrying in {actual_delay:.2f}s..."
                )
                await asyncio.sleep(actual_delay)
                continue
            else:
                logger.error(
                    f"[AgentWorker] Tool discovery failed for '{server_name}' "
                    f"after {attempt + 1} attempts: {e}"
                )
                return None

    return None


def _extract_error_text(result: Dict[str, Any]) -> str:
    """Extract error text from MCP tool result."""
    content = result.get("content", [])
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            return item.get("text", "Unknown error")
    return result.get("error_message", "Unknown error")


def _is_transient_error(error_text: str) -> bool:
    """Check if an error is likely transient and worth retrying."""
    transient_patterns = [
        "connection reset",
        "connection refused",
        "timeout",
        "timed out",
        "network",
        "temporary",
        "retry",
        "unavailable",
        "ECONNRESET",
        "ECONNREFUSED",
        "ETIMEDOUT",
        "socket",
        "broken pipe",
    ]
    error_lower = error_text.lower()
    return any(pattern in error_lower for pattern in transient_patterns)
