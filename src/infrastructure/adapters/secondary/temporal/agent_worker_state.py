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
import time
from typing import Any, Dict, Optional

import redis.asyncio as redis

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
    # MCP Temporal Adapter
    "set_mcp_temporal_adapter",
    "get_mcp_temporal_adapter",
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
    # Prewarm
    "prewarm_agent_session",
    # Utilities
    "generate_session_key",
]

# Global state for agent worker
_agent_graph_service: Optional[Any] = None
_redis_pool: Optional[redis.ConnectionPool] = None
_mcp_temporal_adapter: Optional[Any] = None
_mcp_sandbox_adapter: Optional[Any] = None

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
    logger.info("Agent Worker: Graph service registered for Activities")


def get_agent_graph_service() -> Optional[Any]:
    """Get the global graph service instance for agent worker.

    Returns:
        The graph service instance or None if not initialized
    """
    return _agent_graph_service


# ============================================================================
# MCP Temporal Adapter State
# ============================================================================


def set_mcp_temporal_adapter(adapter: Any) -> None:
    """Set the global MCP Temporal Adapter instance for agent worker.

    Called during Agent Worker initialization to make MCPTemporalAdapter
    available to all Agent Activities for loading MCP tools.

    Args:
        adapter: The MCPTemporalAdapter instance
    """
    global _mcp_temporal_adapter
    _mcp_temporal_adapter = adapter
    logger.info("Agent Worker: MCP Temporal Adapter registered for Activities")


def get_mcp_temporal_adapter() -> Optional[Any]:
    """Get the global MCP Temporal Adapter instance for agent worker.

    Returns:
        The MCPTemporalAdapter instance or None if not initialized
    """
    return _mcp_temporal_adapter


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
        _llm_client_cache, \
        _tools_cache, \
        _mcp_temporal_adapter, \
        _skills_cache, \
        _skill_loader_cache, \
        _provider_config_cache, \
        _provider_config_cached_at
    _agent_graph_service = None
    _mcp_temporal_adapter = None
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


async def get_or_create_llm_client(provider_config: Any) -> Any:
    """Get or create a cached LLM client.

    This function caches LLM clients by provider:model key to avoid
    repeated initialization overhead.

    Args:
        provider_config: Provider configuration object with provider_type and llm_model

    Returns:
        Cached or newly created LLM client
    """
    from src.infrastructure.llm.litellm.litellm_client import create_litellm_client

    # Get provider type as string (handle both enum and string values)
    provider_type_str = (
        provider_config.provider_type.value
        if hasattr(provider_config.provider_type, "value")
        else str(provider_config.provider_type)
    )
    cache_key = f"{provider_type_str}:{provider_config.llm_model}"

    async with _llm_cache_lock:
        if cache_key not in _llm_client_cache:
            _llm_client_cache[cache_key] = create_litellm_client(provider_config)
            logger.info(f"Agent Worker: LLM client cached for {cache_key}")
        return _llm_client_cache[cache_key]


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
    mcp_tools_ttl_seconds: int = 300,  # New: MCP tools TTL (5 minutes)
    force_mcp_refresh: bool = False,  # New: Force MCP tools refresh
    mcp_retry_on_empty: bool = True,  # New: Retry when MCP tools are empty
) -> Dict[str, Any]:
    """Get or create a cached tool set for a project, including MCP tools and skill_loader.

    This function caches built-in tool instances by project_id to avoid
    repeated tool initialization overhead. MCP tools are now cached with TTL
    to avoid frequent Temporal Workflow calls (200-500ms each).

    Args:
        project_id: Project ID for cache key
        tenant_id: Tenant ID for MCP tool loading and skill scoping
        graph_service: Graph service instance (NativeGraphAdapter)
        redis_client: Redis client instance
        llm: LangChain chat model for tools that require LLM (e.g., SummaryTool)
        agent_mode: Agent mode for skill filtering (e.g., "default", "plan")
        mcp_tools_ttl_seconds: TTL for MCP tools cache (default 5 minutes)
        force_mcp_refresh: Force refresh MCP tools (bypass cache)
        mcp_retry_on_empty: Retry loading when MCP tools are empty (default True)

    Returns:
        Dictionary of tool name -> tool instance (built-in + MCP + skill_loader)
    """
    from src.infrastructure.agent.tools import WebScrapeTool, WebSearchTool

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
            }
            logger.info(f"Agent Worker: Tool set cached for project {project_id}")

    # 2. Copy built-in tools (avoid mutating cache)
    tools = dict(_tools_cache[project_id])

    # 3. Load MCP tools with TTL cache and retry logic
    if _mcp_temporal_adapter is not None:
        try:
            # Try to get from cache first (unless force refresh)
            mcp_tools = None
            if not force_mcp_refresh:
                mcp_tools = await get_mcp_tools_from_cache(
                    tenant_id=tenant_id,
                    ttl_seconds=mcp_tools_ttl_seconds,
                )

            if mcp_tools is None:
                # Cache miss or forced refresh - load from Temporal with retry logic
                # This handles the case where MCP servers haven't started yet
                from src.infrastructure.mcp.temporal_tool_loader import MCPTemporalToolLoader

                loader = MCPTemporalToolLoader(
                    mcp_temporal_adapter=_mcp_temporal_adapter,
                    tenant_id=tenant_id,
                )

                # Retry logic: if no MCP tools loaded and retry is enabled, retry with backoff
                # This handles the startup race condition where Agent Worker starts
                # before MCP servers are fully initialized
                max_retries = 3 if mcp_retry_on_empty else 1
                base_delay = 2.0  # Start with 2 second delay
                mcp_tools = {}

                for attempt in range(max_retries):
                    start_time = time.time()
                    mcp_tools = await loader.load_all_tools(refresh=True)
                    elapsed_ms = (time.time() - start_time) * 1000

                    # If we got tools or this is the last attempt, we're done
                    if len(mcp_tools) > 0 or attempt == max_retries - 1:
                        logger.info(
                            f"Agent Worker: Loaded {len(mcp_tools)} MCP tools for tenant {tenant_id} "
                            f"in {elapsed_ms:.1f}ms (cache updated)"
                        )
                        break

                    # No tools loaded - MCP servers might not be ready yet
                    # Wait with exponential backoff before retry
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        f"Agent Worker: No MCP tools loaded for tenant {tenant_id} "
                        f"(attempt {attempt + 1}/{max_retries}). "
                        f"MCP servers may not be ready yet. Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)

                # Update cache with whatever tools we got (may be empty)
                await update_mcp_tools_cache(
                    tenant_id=tenant_id,
                    tools=mcp_tools,
                )
            else:
                logger.debug(
                    f"Agent Worker: MCP tools cache hit for tenant {tenant_id} "
                    f"({len(mcp_tools)} tools)"
                )

            tools.update(mcp_tools)
        except Exception as e:
            logger.warning(f"Agent Worker: Failed to load MCP tools for tenant {tenant_id}: {e}")

    # 4. Load Project Sandbox MCP tools (if sandbox exists for project)
    if _mcp_sandbox_adapter is not None:
        try:
            sandbox_tools = await _load_project_sandbox_tools(
                project_id=project_id,
                tenant_id=tenant_id,
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

    # 5. Add SkillLoaderTool (initialized with skill list in description)
    # This enables LLM to see available skills and make autonomous decisions
    try:
        skill_loader = await get_or_create_skill_loader_tool(
            tenant_id=tenant_id,
            project_id=project_id,
            agent_mode=agent_mode,
        )
        tools["skill_loader"] = skill_loader
        logger.info(
            f"Agent Worker: SkillLoaderTool added for tenant {tenant_id}, agent_mode={agent_mode}"
        )
    except Exception as e:
        logger.warning(f"Agent Worker: Failed to create SkillLoaderTool: {e}")

    # 6. Add SkillInstallerTool for installing skills from skills.sh
    try:
        from pathlib import Path

        from src.infrastructure.agent.tools.skill_installer import SkillInstallerTool

        # Use the project path from config or fallback to current working directory
        project_path = Path.cwd()
        skill_installer = SkillInstallerTool(project_path=project_path)
        tools["skill_installer"] = skill_installer
        logger.info(f"Agent Worker: SkillInstallerTool added for project {project_id}")
    except Exception as e:
        logger.warning(f"Agent Worker: Failed to create SkillInstallerTool: {e}")

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

    return tools


async def _load_project_sandbox_tools(
    project_id: str,
    tenant_id: str,
) -> Dict[str, Any]:
    """Load MCP tools from project's sandbox.

    This function first queries the database for existing sandbox associations,
    then falls back to Docker discovery. It NEVER creates new sandboxes -
    sandbox creation is handled by ProjectSandboxLifecycleService.

    CRITICAL: This ensures API Server and Agent Worker use the SAME sandbox,
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
            SqlAlchemyProjectSandboxRepository,
        )

        async with async_session_factory() as db:
            sandbox_repo = SqlAlchemyProjectSandboxRepository(db)
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

        # Wrap each tool with SandboxMCPToolWrapper
        for tool_info in tool_list:
            tool_name = tool_info.get("name", "")
            if not tool_name:
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

    except Exception as e:
        logger.warning(f"[AgentWorker] Failed to load project sandbox tools: {e}")
        import traceback

        logger.debug(f"[AgentWorker] Traceback: {traceback.format_exc()}")

    return tools


def get_cached_tools() -> Dict[str, Dict[str, Any]]:
    """Get all cached tool sets (for debugging/monitoring)."""
    return dict(_tools_cache)


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


async def get_or_create_provider_config(force_refresh: bool = False) -> Any:
    """Get or create cached default LLM provider config.

    Args:
        force_refresh: Force refresh from database

    Returns:
        ProviderConfig instance
    """
    global _provider_config_cache, _provider_config_cached_at

    now = time.time()
    if (
        not force_refresh
        and _provider_config_cache is not None
        and (now - _provider_config_cached_at) < _provider_config_cache_ttl_seconds
    ):
        return _provider_config_cache

    async with _provider_config_cache_lock:
        now = time.time()
        if (
            not force_refresh
            and _provider_config_cache is not None
            and (now - _provider_config_cached_at) < _provider_config_cache_ttl_seconds
        ):
            return _provider_config_cache

        from src.infrastructure.persistence.llm_providers_repository import (
            SQLAlchemyProviderRepository,
        )

        provider_repo = SQLAlchemyProviderRepository()
        provider_config = await provider_repo.find_default_provider()
        if not provider_config:
            provider_config = await provider_repo.find_first_active_provider()
        if not provider_config:
            raise ValueError("No active LLM provider found. Please configure a provider.")

        _provider_config_cache = provider_config
        _provider_config_cached_at = now

        return provider_config


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
    from typing import List
    from typing import Optional as Opt

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
        graph_service = get_agent_graph_service()
        if not graph_service:
            logger.warning("Agent Worker: Graph service not initialized, skip prewarm")
            return

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
