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

    Returns:
        Dictionary of tool name -> tool instance (built-in + MCP + skill_loader)
    """
    from src.infrastructure.agent.tools import (
        WebScrapeTool,
        WebSearchTool,
    )

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

    # 3. Load MCP tools with TTL cache (optimized: avoids frequent Temporal calls)
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
                # Cache miss or forced refresh - load from Temporal
                start_time = time.time()
                from src.infrastructure.mcp.temporal_tool_loader import MCPTemporalToolLoader

                loader = MCPTemporalToolLoader(
                    mcp_temporal_adapter=_mcp_temporal_adapter,
                    tenant_id=tenant_id,
                )
                # Load fresh tools
                mcp_tools = await loader.load_all_tools(refresh=True)

                # Update cache
                await update_mcp_tools_cache(
                    tenant_id=tenant_id,
                    tools=mcp_tools,
                )

                elapsed_ms = (time.time() - start_time) * 1000
                logger.info(
                    f"Agent Worker: Loaded {len(mcp_tools)} MCP tools for tenant {tenant_id} "
                    f"in {elapsed_ms:.1f}ms (cache updated)"
                )
            else:
                logger.debug(
                    f"Agent Worker: MCP tools cache hit for tenant {tenant_id} "
                    f"({len(mcp_tools)} tools)"
                )

            tools.update(mcp_tools)
        except Exception as e:
            logger.warning(f"Agent Worker: Failed to load MCP tools for tenant {tenant_id}: {e}")

    # 4. Add SkillLoaderTool (initialized with skill list in description)
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
