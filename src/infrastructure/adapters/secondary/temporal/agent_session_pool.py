"""Agent Session Pool for caching and reusing agent components.

This module provides a session pool mechanism similar to MCP Worker's
_mcp_clients pattern, enabling efficient reuse of expensive-to-create
components like tool definitions, SubAgentRouter, and SkillExecutor.

Key benefits:
- Tool definition conversion cached (50-200ms -> <1ms on cache hit)
- SubAgentRouter keyword index cached (10-50ms -> <1ms on cache hit)
- MCP tools cached with TTL (200-500ms -> <1ms on cache hit)
- SystemPromptManager shared as singleton

Reference: MCP Worker lifecycle pattern in mcp/activities.py
"""

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================================
# Data Structures
# ============================================================================


@dataclass
class AgentSessionContext:
    """Cached agent session context with reusable components.

    This class holds pre-initialized components that can be safely reused
    across multiple agent executions for the same tenant/project/mode.

    Components are categorized as:
    - Stateless: Can be shared freely (tool_definitions, subagent_router)
    - Configurable: Safe to share with same config (processor_config)
    - Per-request: Must be created fresh (SessionProcessor, LLMStream)
    """

    # Identification
    session_key: str  # "{tenant_id}:{project_id}:{agent_mode}"
    tenant_id: str
    project_id: str
    agent_mode: str

    # Cached stateless components
    tool_definitions: List[Any]  # List[ToolDefinition] - converted tools with closures
    raw_tools: Dict[str, Any]  # Original tool instances for SubAgent filtering

    # Cached optional components
    subagent_router: Optional[Any] = None  # SubAgentRouter with built keyword index
    skill_executor: Optional[Any] = None  # SkillExecutor instance
    skills: List[Any] = field(default_factory=list)  # List[Skill]

    # Shared singleton references
    system_prompt_manager: Optional[Any] = None  # SystemPromptManager singleton

    # Configuration (for validation)
    processor_config: Optional[Any] = None  # ProcessorConfig

    # Cache validity detection
    tools_hash: str = ""  # Hash of tool names for change detection
    skills_hash: str = ""  # Hash of skill names for change detection
    subagents_hash: str = ""  # Hash of subagent names for change detection

    # TTL and usage tracking
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)
    use_count: int = 0
    ttl_seconds: int = 1800  # 30 minutes default TTL

    def is_expired(self) -> bool:
        """Check if this session context has expired."""
        return time.time() - self.last_used_at > self.ttl_seconds

    def touch(self) -> None:
        """Update last used timestamp and increment use count."""
        self.last_used_at = time.time()
        self.use_count += 1

    def is_valid_for(
        self,
        tools_hash: str,
        skills_hash: str = "",
        subagents_hash: str = "",
    ) -> bool:
        """Check if this context is still valid for the given configuration.

        Args:
            tools_hash: Hash of current tool names
            skills_hash: Hash of current skill names
            subagents_hash: Hash of current subagent names

        Returns:
            True if the cached context is still valid
        """
        if self.is_expired():
            return False

        if self.tools_hash != tools_hash:
            logger.debug(f"Session {self.session_key}: tools hash mismatch")
            return False

        if skills_hash and self.skills_hash != skills_hash:
            logger.debug(f"Session {self.session_key}: skills hash mismatch")
            return False

        if subagents_hash and self.subagents_hash != subagents_hash:
            logger.debug(f"Session {self.session_key}: subagents hash mismatch")
            return False

        return True


@dataclass
class MCPToolsCacheEntry:
    """MCP tools cache entry with TTL support.

    MCP tools are loaded from Temporal workflows and cached with a
    configurable TTL to avoid frequent workflow calls.
    """

    tools: Dict[str, Any]  # Tool instances from MCP
    fetched_at: float  # Timestamp when fetched
    tenant_id: str
    version: int = 0  # Incremented on MCP config changes

    def is_expired(self, ttl_seconds: int = 300) -> bool:
        """Check if cache entry has expired (default 5 minutes)."""
        return time.time() - self.fetched_at > ttl_seconds


# ============================================================================
# Global Caches (similar to MCP Worker's _mcp_clients pattern)
# ============================================================================

# Agent Session Pool - main cache for session contexts
_agent_session_pool: Dict[str, AgentSessionContext] = {}
_agent_session_pool_lock = asyncio.Lock()

# Tool Definitions Cache - converted ToolDefinition objects
_tool_definitions_cache: Dict[str, List[Any]] = {}
_tool_definitions_cache_lock = asyncio.Lock()

# MCP Tools Cache - tools loaded from MCP workflows with TTL
_mcp_tools_cache: Dict[str, MCPToolsCacheEntry] = {}
_mcp_tools_cache_lock = asyncio.Lock()

# SubAgentRouter Cache - routers with built keyword index
_subagent_router_cache: Dict[str, Any] = {}
_subagent_router_cache_lock = asyncio.Lock()

# SystemPromptManager Singleton
_system_prompt_manager: Optional[Any] = None
_system_prompt_manager_lock = asyncio.Lock()


# ============================================================================
# Hash Utilities
# ============================================================================


def compute_tools_hash(tools: Dict[str, Any]) -> str:
    """Compute a hash of tool names for change detection.

    Args:
        tools: Dictionary of tool name -> tool instance

    Returns:
        MD5 hash string of sorted tool names
    """
    tool_names = sorted(tools.keys())
    content = ",".join(tool_names)
    return hashlib.md5(content.encode()).hexdigest()[:16]


def compute_skills_hash(skills: List[Any]) -> str:
    """Compute a hash of skill names and versions for change detection.

    Args:
        skills: List of Skill domain entities

    Returns:
        MD5 hash string of sorted skill identifiers
    """
    if not skills:
        return ""

    skill_ids = sorted(f"{s.name}:{getattr(s, 'version', '1')}" for s in skills)
    content = ",".join(skill_ids)
    return hashlib.md5(content.encode()).hexdigest()[:16]


def compute_subagents_hash(subagents: List[Any]) -> str:
    """Compute a hash of subagent names for change detection.

    Args:
        subagents: List of SubAgent domain entities

    Returns:
        MD5 hash string of sorted subagent names
    """
    if not subagents:
        return ""

    subagent_names = sorted(s.name for s in subagents)
    content = ",".join(subagent_names)
    return hashlib.md5(content.encode()).hexdigest()[:16]


def generate_session_key(
    tenant_id: str,
    project_id: str,
    agent_mode: str,
) -> str:
    """Generate a unique session key.

    Args:
        tenant_id: Tenant identifier
        project_id: Project identifier
        agent_mode: Agent mode (e.g., "default", "plan")

    Returns:
        Session key string
    """
    return f"{tenant_id}:{project_id}:{agent_mode}"


# ============================================================================
# SystemPromptManager Singleton
# ============================================================================


async def get_system_prompt_manager() -> Any:
    """Get or create the global SystemPromptManager singleton.

    Returns:
        SystemPromptManager instance (shared across all sessions)
    """
    global _system_prompt_manager

    if _system_prompt_manager is not None:
        return _system_prompt_manager

    async with _system_prompt_manager_lock:
        if _system_prompt_manager is None:
            from pathlib import Path

            from src.infrastructure.agent.prompts import SystemPromptManager

            _system_prompt_manager = SystemPromptManager(project_root=Path.cwd())
            logger.info("Agent Session Pool: SystemPromptManager singleton created")

        return _system_prompt_manager


# ============================================================================
# Tool Definitions Cache
# ============================================================================


async def get_or_create_tool_definitions(
    tools: Dict[str, Any],
    tools_hash: Optional[str] = None,
) -> List[Any]:
    """Get or create cached tool definitions.

    This caches the expensive _convert_tools() operation that creates
    closures and extracts parameter schemas for each tool.

    Args:
        tools: Dictionary of tool name -> tool instance
        tools_hash: Pre-computed hash (optional, will compute if not provided)

    Returns:
        List of ToolDefinition objects
    """
    if tools_hash is None:
        tools_hash = compute_tools_hash(tools)

    async with _tool_definitions_cache_lock:
        if tools_hash in _tool_definitions_cache:
            logger.debug(f"Agent Session Pool: Tool definitions cache hit for {tools_hash}")
            return _tool_definitions_cache[tools_hash]

        # Cache miss - convert tools
        logger.info(f"Agent Session Pool: Converting {len(tools)} tools (hash={tools_hash})")
        start_time = time.time()

        definitions = _convert_tools_to_definitions(tools)

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(f"Agent Session Pool: Tool conversion took {elapsed_ms:.1f}ms")

        _tool_definitions_cache[tools_hash] = definitions
        return definitions


def _convert_tools_to_definitions(tools: Dict[str, Any]) -> List[Any]:
    """Convert tool instances to ToolDefinition format.

    This is the same logic as ReActAgent._convert_tools() but extracted
    for caching purposes.

    Args:
        tools: Dictionary of tool name -> tool instance

    Returns:
        List of ToolDefinition objects
    """
    from src.infrastructure.agent.core.processor import ToolDefinition

    definitions = []

    for name, tool in tools.items():
        # Extract tool metadata
        description = getattr(tool, "description", f"Tool: {name}")

        # Get parameters schema
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
                    if hasattr(tool_instance, "execute"):
                        result = tool_instance.execute(**kwargs)
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
                    return f"Error executing tool {tool_name}: {str(e)}"

            return execute_wrapper

        definitions.append(
            ToolDefinition(
                name=name,
                description=description,
                parameters=parameters,
                execute=make_execute_wrapper(tool, name),
            )
        )

    return definitions


def invalidate_tool_definitions_cache(tools_hash: Optional[str] = None) -> int:
    """Invalidate tool definitions cache.

    Args:
        tools_hash: Specific hash to invalidate, or None for all

    Returns:
        Number of entries invalidated
    """
    global _tool_definitions_cache

    if tools_hash:
        if tools_hash in _tool_definitions_cache:
            del _tool_definitions_cache[tools_hash]
            logger.info(f"Agent Session Pool: Tool definitions cache invalidated for {tools_hash}")
            return 1
        return 0
    else:
        count = len(_tool_definitions_cache)
        _tool_definitions_cache.clear()
        logger.info(f"Agent Session Pool: All tool definitions cache cleared ({count} entries)")
        return count


# ============================================================================
# MCP Tools Cache
# ============================================================================


async def get_mcp_tools_from_cache(
    tenant_id: str,
    ttl_seconds: int = 300,
) -> Optional[Dict[str, Any]]:
    """Get MCP tools from cache if not expired.

    Args:
        tenant_id: Tenant identifier
        ttl_seconds: TTL in seconds (default 5 minutes)

    Returns:
        Cached tools dict or None if cache miss/expired
    """
    async with _mcp_tools_cache_lock:
        entry = _mcp_tools_cache.get(tenant_id)

        if entry is None:
            return None

        if entry.is_expired(ttl_seconds):
            del _mcp_tools_cache[tenant_id]
            logger.debug(f"Agent Session Pool: MCP tools cache expired for tenant {tenant_id}")
            return None

        logger.debug(f"Agent Session Pool: MCP tools cache hit for tenant {tenant_id}")
        return entry.tools


async def update_mcp_tools_cache(
    tenant_id: str,
    tools: Dict[str, Any],
    version: int = 0,
) -> None:
    """Update MCP tools cache.

    Args:
        tenant_id: Tenant identifier
        tools: Tools dict to cache
        version: Optional version number
    """
    async with _mcp_tools_cache_lock:
        _mcp_tools_cache[tenant_id] = MCPToolsCacheEntry(
            tools=tools,
            fetched_at=time.time(),
            tenant_id=tenant_id,
            version=version,
        )
        logger.info(
            f"Agent Session Pool: MCP tools cached for tenant {tenant_id} ({len(tools)} tools)"
        )


def invalidate_mcp_tools_cache(tenant_id: Optional[str] = None) -> int:
    """Invalidate MCP tools cache.

    Args:
        tenant_id: Specific tenant to invalidate, or None for all

    Returns:
        Number of entries invalidated
    """
    global _mcp_tools_cache

    if tenant_id:
        if tenant_id in _mcp_tools_cache:
            del _mcp_tools_cache[tenant_id]
            logger.info(f"Agent Session Pool: MCP tools cache invalidated for {tenant_id}")
            return 1
        return 0
    else:
        count = len(_mcp_tools_cache)
        _mcp_tools_cache.clear()
        logger.info(f"Agent Session Pool: All MCP tools cache cleared ({count} entries)")
        return count


# ============================================================================
# SubAgentRouter Cache
# ============================================================================


async def get_or_create_subagent_router(
    tenant_id: str,
    subagents: List[Any],
    subagents_hash: Optional[str] = None,
    match_threshold: float = 0.5,
) -> Optional[Any]:
    """Get or create cached SubAgentRouter with built keyword index.

    Args:
        tenant_id: Tenant identifier for cache key
        subagents: List of SubAgent domain entities
        subagents_hash: Pre-computed hash (optional)
        match_threshold: Default confidence threshold

    Returns:
        SubAgentRouter instance or None if no subagents
    """
    if not subagents:
        return None

    if subagents_hash is None:
        subagents_hash = compute_subagents_hash(subagents)

    cache_key = f"{tenant_id}:{subagents_hash}"

    async with _subagent_router_cache_lock:
        if cache_key in _subagent_router_cache:
            logger.debug(f"Agent Session Pool: SubAgentRouter cache hit for {cache_key}")
            return _subagent_router_cache[cache_key]

        # Cache miss - create router
        logger.info(
            f"Agent Session Pool: Creating SubAgentRouter for {tenant_id} "
            f"({len(subagents)} subagents)"
        )
        start_time = time.time()

        from src.infrastructure.agent.core.subagent_router import SubAgentRouter

        router = SubAgentRouter(
            subagents=subagents,
            default_confidence_threshold=match_threshold,
        )

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(f"Agent Session Pool: SubAgentRouter creation took {elapsed_ms:.1f}ms")

        _subagent_router_cache[cache_key] = router
        return router


def invalidate_subagent_router_cache(tenant_id: Optional[str] = None) -> int:
    """Invalidate SubAgentRouter cache.

    Args:
        tenant_id: Specific tenant to invalidate (partial match), or None for all

    Returns:
        Number of entries invalidated
    """
    global _subagent_router_cache

    if tenant_id:
        keys_to_remove = [k for k in _subagent_router_cache if k.startswith(f"{tenant_id}:")]
        for key in keys_to_remove:
            del _subagent_router_cache[key]
        if keys_to_remove:
            logger.info(
                f"Agent Session Pool: SubAgentRouter cache invalidated for {tenant_id} "
                f"({len(keys_to_remove)} entries)"
            )
        return len(keys_to_remove)
    else:
        count = len(_subagent_router_cache)
        _subagent_router_cache.clear()
        logger.info(f"Agent Session Pool: All SubAgentRouter cache cleared ({count} entries)")
        return count


# ============================================================================
# Agent Session Pool (Main API)
# ============================================================================


async def get_or_create_agent_session(
    tenant_id: str,
    project_id: str,
    agent_mode: str,
    tools: Dict[str, Any],
    skills: Optional[List[Any]] = None,
    subagents: Optional[List[Any]] = None,
    processor_config: Optional[Any] = None,
    subagent_match_threshold: float = 0.5,
) -> AgentSessionContext:
    """Get or create an agent session context with cached components.

    This is the main entry point for the Agent Session Pool. It manages
    the lifecycle of expensive-to-create components and enables efficient
    reuse across multiple agent executions.

    Args:
        tenant_id: Tenant identifier
        project_id: Project identifier
        agent_mode: Agent mode (e.g., "default", "plan")
        tools: Dictionary of tool name -> tool instance
        skills: Optional list of Skill domain entities
        subagents: Optional list of SubAgent domain entities
        processor_config: Optional ProcessorConfig
        subagent_match_threshold: Threshold for SubAgentRouter

    Returns:
        AgentSessionContext with cached components
    """
    skills = skills or []
    subagents = subagents or []

    session_key = generate_session_key(tenant_id, project_id, agent_mode)
    tools_hash = compute_tools_hash(tools)
    skills_hash = compute_skills_hash(skills)
    subagents_hash = compute_subagents_hash(subagents)

    async with _agent_session_pool_lock:
        # Check for existing valid session
        existing = _agent_session_pool.get(session_key)

        if existing and existing.is_valid_for(tools_hash, skills_hash, subagents_hash):
            existing.touch()
            logger.debug(
                f"Agent Session Pool: Cache hit for {session_key} (use_count={existing.use_count})"
            )
            return existing

        # Cache miss or invalid - create new session
        logger.info(
            f"Agent Session Pool: Creating session for {session_key} "
            f"(tools={len(tools)}, skills={len(skills)}, subagents={len(subagents)})"
        )
        start_time = time.time()

    # Release lock during expensive operations

    # Get or create tool definitions (cached separately)
    tool_definitions = await get_or_create_tool_definitions(tools, tools_hash)

    # Get or create SubAgentRouter (cached separately)
    subagent_router = await get_or_create_subagent_router(
        tenant_id=tenant_id,
        subagents=subagents,
        subagents_hash=subagents_hash,
        match_threshold=subagent_match_threshold,
    )

    # Create SkillExecutor (lightweight, doesn't need separate cache)
    skill_executor = None
    if skills:
        from src.infrastructure.agent.core.skill_executor import SkillExecutor

        skill_executor = SkillExecutor(tools)

    # Get SystemPromptManager singleton
    system_prompt_manager = await get_system_prompt_manager()

    # Create session context
    session = AgentSessionContext(
        session_key=session_key,
        tenant_id=tenant_id,
        project_id=project_id,
        agent_mode=agent_mode,
        tool_definitions=tool_definitions,
        raw_tools=tools,
        subagent_router=subagent_router,
        skill_executor=skill_executor,
        skills=skills,
        system_prompt_manager=system_prompt_manager,
        processor_config=processor_config,
        tools_hash=tools_hash,
        skills_hash=skills_hash,
        subagents_hash=subagents_hash,
    )

    # Store in pool
    async with _agent_session_pool_lock:
        _agent_session_pool[session_key] = session

    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(f"Agent Session Pool: Session created for {session_key} in {elapsed_ms:.1f}ms")

    return session


def invalidate_agent_session(
    tenant_id: Optional[str] = None,
    project_id: Optional[str] = None,
    agent_mode: Optional[str] = None,
) -> int:
    """Invalidate agent sessions matching the criteria.

    Args:
        tenant_id: Tenant to match (partial match if project_id not specified)
        project_id: Project to match
        agent_mode: Agent mode to match

    Returns:
        Number of sessions invalidated
    """
    global _agent_session_pool

    if not tenant_id:
        # Clear all
        count = len(_agent_session_pool)
        _agent_session_pool.clear()
        logger.info(f"Agent Session Pool: All sessions cleared ({count} entries)")
        return count

    # Build partial key for matching
    if project_id and agent_mode:
        # Exact match
        key = generate_session_key(tenant_id, project_id, agent_mode)
        if key in _agent_session_pool:
            del _agent_session_pool[key]
            logger.info(f"Agent Session Pool: Session invalidated for {key}")
            return 1
        return 0
    elif project_id:
        # Match tenant:project:*
        prefix = f"{tenant_id}:{project_id}:"
    else:
        # Match tenant:*
        prefix = f"{tenant_id}:"

    keys_to_remove = [k for k in _agent_session_pool if k.startswith(prefix)]
    for key in keys_to_remove:
        del _agent_session_pool[key]

    if keys_to_remove:
        logger.info(
            f"Agent Session Pool: Sessions invalidated for prefix '{prefix}' "
            f"({len(keys_to_remove)} entries)"
        )

    return len(keys_to_remove)


async def cleanup_expired_sessions(ttl_seconds: Optional[int] = None) -> int:
    """Clean up expired session contexts.

    This should be called periodically (e.g., every 10 minutes) to
    prevent memory leaks from unused sessions.

    Args:
        ttl_seconds: Override TTL for expiry check

    Returns:
        Number of sessions cleaned up
    """
    global _agent_session_pool

    async with _agent_session_pool_lock:
        now = time.time()
        expired_keys = []

        for key, session in _agent_session_pool.items():
            effective_ttl = ttl_seconds or session.ttl_seconds
            if now - session.last_used_at > effective_ttl:
                expired_keys.append(key)

        for key in expired_keys:
            del _agent_session_pool[key]

        if expired_keys:
            logger.info(f"Agent Session Pool: Cleaned up {len(expired_keys)} expired sessions")

        return len(expired_keys)


def get_pool_stats() -> Dict[str, Any]:
    """Get statistics about the agent session pool.

    Returns:
        Dictionary with pool statistics for monitoring
    """
    now = time.time()

    sessions = list(_agent_session_pool.values())

    total_use_count = sum(s.use_count for s in sessions)
    avg_age = sum(now - s.created_at for s in sessions) / len(sessions) if sessions else 0

    return {
        "total_sessions": len(_agent_session_pool),
        "tool_definitions_cached": len(_tool_definitions_cache),
        "mcp_tools_cached": len(_mcp_tools_cache),
        "subagent_routers_cached": len(_subagent_router_cache),
        "total_use_count": total_use_count,
        "avg_session_age_seconds": round(avg_age, 1),
        "system_prompt_manager_initialized": _system_prompt_manager is not None,
    }


async def clear_session_cache(
    tenant_id: str,
    project_id: str,
    agent_mode: str,
) -> bool:
    """Clear cache for a specific session.

    This function is called when a Workflow session stops to free memory.

    Args:
        tenant_id: Tenant identifier
        project_id: Project identifier
        agent_mode: Agent mode

    Returns:
        True if cache was cleared, False if not found
    """
    session_key = generate_session_key(tenant_id, project_id, agent_mode)

    async with _agent_session_pool_lock:
        if session_key in _agent_session_pool:
            del _agent_session_pool[session_key]
            logger.info(f"Agent Session Pool: Session cache cleared for {session_key}")
            return True

    return False


def clear_all_caches() -> Dict[str, int]:
    """Clear all caches (for shutdown or testing).

    Returns:
        Dictionary with count of cleared items per cache
    """
    global _agent_session_pool, _tool_definitions_cache
    global _mcp_tools_cache, _subagent_router_cache, _system_prompt_manager

    counts = {
        "sessions": len(_agent_session_pool),
        "tool_definitions": len(_tool_definitions_cache),
        "mcp_tools": len(_mcp_tools_cache),
        "subagent_routers": len(_subagent_router_cache),
    }

    _agent_session_pool.clear()
    _tool_definitions_cache.clear()
    _mcp_tools_cache.clear()
    _subagent_router_cache.clear()
    _system_prompt_manager = None

    logger.info(f"Agent Session Pool: All caches cleared: {counts}")

    return counts
