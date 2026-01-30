"""
Project-level ReAct Agent Lifecycle Management.

This module provides a project-scoped ReActAgent wrapper that manages
the complete lifecycle of an agent instance for a specific project.
Each project has its own persistent Temporal workflow instance with:
- Isolated tool sets and configurations
- Project-scoped caching
- Independent lifecycle management
- Resource isolation

Usage:
    # Get or create project agent instance
    agent = await project_agent_manager.get_or_create_agent(
        tenant_id="tenant-123",
        project_id="project-456",
        agent_mode="default"
    )
    
    # Execute chat
    async for event in agent.execute_chat(
        conversation_id="conv-789",
        user_message="Hello",
        user_id="user-abc"
    ):
        yield event
    
    # Get project agent status
    status = await agent.get_status()
    
    # Stop project agent
    await agent.stop()
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional

from src.domain.model.agent.skill import Skill
from src.domain.model.agent.subagent import SubAgent

logger = logging.getLogger(__name__)


@dataclass
class ProjectAgentConfig:
    """Configuration for a project-level agent instance."""

    tenant_id: str
    project_id: str
    agent_mode: str = "default"

    # LLM Configuration
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 4096
    max_steps: int = 20

    # Session Configuration
    idle_timeout_seconds: int = 1800  # 30 minutes
    max_concurrent_chats: int = 10

    # Tool Configuration
    mcp_tools_ttl_seconds: int = 300  # 5 minutes

    # Feature Flags
    enable_skills: bool = True
    enable_subagents: bool = True
    enable_plan_mode: bool = True


@dataclass
class ProjectAgentStatus:
    """Status of a project-level agent instance."""

    tenant_id: str
    project_id: str
    agent_mode: str

    is_initialized: bool = False
    is_active: bool = False
    is_executing: bool = False

    total_chats: int = 0
    active_chats: int = 0
    failed_chats: int = 0

    tool_count: int = 0
    skill_count: int = 0
    subagent_count: int = 0

    created_at: Optional[str] = None
    last_activity_at: Optional[str] = None
    last_error: Optional[str] = None

    # Performance metrics
    avg_execution_time_ms: float = 0.0
    total_execution_time_ms: float = 0.0


@dataclass
class ProjectAgentMetrics:
    """Detailed metrics for project agent."""

    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0

    total_tokens_used: int = 0
    total_cost_usd: float = 0.0

    tool_execution_count: Dict[str, int] = field(default_factory=dict)
    skill_invocation_count: Dict[str, int] = field(default_factory=dict)

    # Latency percentiles (in ms)
    latency_p50: float = 0.0
    latency_p95: float = 0.0
    latency_p99: float = 0.0


class ProjectReActAgent:
    """
    Project-scoped ReAct Agent instance.

    This class encapsulates all resources and state for a single project's
    agent instance. It provides:

    1. Lifecycle Management:
       - initialize(): Set up tools, skills, and cached components
       - execute_chat(): Process a chat request
       - pause/resume(): Temporary stop/start
       - stop(): Clean shutdown

    2. Resource Isolation:
       - Project-specific tool sets
       - Project-scoped skill loading
       - Independent configuration

    3. State Management:
       - Track execution metrics
       - Monitor health status
       - Handle errors and recovery

    Usage:
        agent = ProjectReActAgent(config)
        await agent.initialize()
        
        async for event in agent.execute_chat(...):
            yield event
            
        status = agent.get_status()
        await agent.stop()
    """

    def __init__(self, config: ProjectAgentConfig):
        """
        Initialize project agent (not fully ready until initialize() is called).

        Args:
            config: Project agent configuration
        """
        self.config = config
        self._status = ProjectAgentStatus(
            tenant_id=config.tenant_id,
            project_id=config.project_id,
            agent_mode=config.agent_mode,
            created_at=datetime.utcnow().isoformat(),
        )
        self._metrics = ProjectAgentMetrics()

        # Cached components (initialized in initialize())
        self._tools: Optional[Dict[str, Any]] = None
        self._skills: Optional[List[Skill]] = None
        self._subagents: Optional[List[SubAgent]] = None
        self._session_context: Optional[Any] = None
        self._react_agent: Optional[Any] = None

        # Execution tracking
        self._execution_lock = asyncio.Lock()
        self._is_shutting_down = False
        self._initialized = False

        # Latency tracking for percentiles
        self._latencies: List[float] = []

    @property
    def is_initialized(self) -> bool:
        """Check if agent is initialized."""
        return self._initialized

    @property
    def is_active(self) -> bool:
        """Check if agent is active (initialized and not shutting down)."""
        return self._initialized and not self._is_shutting_down

    @property
    def project_key(self) -> str:
        """Get unique project key."""
        return f"{self.config.tenant_id}:{self.config.project_id}:{self.config.agent_mode}"

    async def initialize(self, force_refresh: bool = False) -> bool:
        """
        Initialize the project agent and warm up caches.

        This method:
        1. Loads project-specific tools (including MCP tools)
        2. Loads skills for the project
        3. Creates SubAgentRouter if enabled
        4. Pre-converts tool definitions
        5. Initializes the ReActAgent instance

        Args:
            force_refresh: Force refresh of all caches

        Returns:
            True if initialization succeeded
        """
        if self._initialized and not force_refresh:
            logger.debug(f"ProjectReActAgent[{self.project_key}]: Already initialized")
            return True

        start_time = time.time()

        try:
            logger.info(f"ProjectReActAgent[{self.project_key}]: Initializing...")

            # Import dependencies here to avoid circular imports
            from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
                get_agent_graph_service,
                get_or_create_agent_session,
                get_or_create_llm_client,
                get_or_create_provider_config,
                get_or_create_skills,
                get_or_create_tools,
                get_redis_client,
            )
            from src.infrastructure.agent.core.processor import ProcessorConfig
            from src.infrastructure.agent.core.react_agent import ReActAgent

            # Get shared services
            graph_service = get_agent_graph_service()
            if not graph_service:
                raise RuntimeError("Graph service not available")

            redis_client = await get_redis_client()

            # Get LLM provider configuration
            provider_config = await get_or_create_provider_config(force_refresh=force_refresh)
            llm_client = await get_or_create_llm_client(provider_config)

            # Load tools
            self._tools = await get_or_create_tools(
                project_id=self.config.project_id,
                tenant_id=self.config.tenant_id,
                graph_service=graph_service,
                redis_client=redis_client,
                llm=llm_client,
                agent_mode=self.config.agent_mode,
                mcp_tools_ttl_seconds=0 if force_refresh else self.config.mcp_tools_ttl_seconds,
                force_mcp_refresh=force_refresh,
            )

            # Load skills
            if self.config.enable_skills:
                self._skills = await get_or_create_skills(
                    tenant_id=self.config.tenant_id,
                    project_id=self.config.project_id,
                )
            else:
                self._skills = []

            # Load subagents (if enabled)
            if self.config.enable_subagents:
                self._subagents = await self._load_subagents()
            else:
                self._subagents = []

            # Create processor config
            processor_config = ProcessorConfig(
                model=provider_config.llm_model,
                api_key="",  # Will be set from provider_config
                base_url=provider_config.base_url,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                max_steps=self.config.max_steps,
            )

            # Get or create agent session (caches tool definitions, router, etc.)
            self._session_context = await get_or_create_agent_session(
                tenant_id=self.config.tenant_id,
                project_id=self.config.project_id,
                agent_mode=self.config.agent_mode,
                tools=self._tools,
                skills=self._skills,
                subagents=self._subagents,
                processor_config=processor_config,
            )

            # Create ReActAgent instance with cached components
            self._react_agent = ReActAgent(
                model=provider_config.llm_model,
                tools=self._tools,
                api_key=None,  # Set from provider_config during execution
                base_url=provider_config.base_url,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                max_steps=self.config.max_steps,
                agent_mode=self.config.agent_mode,
                skills=self._skills,
                subagents=self._subagents,
                # Use cached components from session pool
                _cached_tool_definitions=self._session_context.tool_definitions,
                _cached_system_prompt_manager=self._session_context.system_prompt_manager,
                _cached_subagent_router=self._session_context.subagent_router,
            )

            # Update status
            self._initialized = True
            self._status.is_initialized = True
            self._status.is_active = True
            self._status.tool_count = len(self._tools)
            self._status.skill_count = len(self._skills) if self._skills else 0
            self._status.subagent_count = len(self._subagents) if self._subagents else 0

            init_time_ms = (time.time() - start_time) * 1000
            logger.info(
                f"ProjectReActAgent[{self.project_key}]: Initialized in {init_time_ms:.1f}ms, "
                f"tools={self._status.tool_count}, skills={self._status.skill_count}"
            )

            return True

        except Exception as e:
            self._status.last_error = str(e)
            logger.error(
                f"ProjectReActAgent[{self.project_key}]: Initialization failed: {e}",
                exc_info=True
            )
            return False

    async def _check_and_refresh_sandbox_tools(self) -> bool:
        """Check if sandbox tools need to be refreshed and refresh if needed.

        This method checks if a Project Sandbox exists but its tools are not
        loaded in the current tool set. If so, it refreshes the tools.

        Returns:
            True if tools were refreshed, False otherwise
        """
        if not self._initialized or not self._tools:
            return False

        try:
            from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
                get_mcp_sandbox_adapter,
            )

            sandbox_adapter = get_mcp_sandbox_adapter()
            if not sandbox_adapter:
                return False

            # Check if there's an active sandbox for this project
            all_sandboxes = await sandbox_adapter.list_sandboxes()
            project_sandbox_id = None

            for sandbox in all_sandboxes:
                project_path = getattr(sandbox, 'project_path', '') or ''
                if project_path and f"memstack_{self.config.project_id}" in project_path:
                    project_sandbox_id = sandbox.id
                    break

                labels = getattr(sandbox, 'labels', {}) or {}
                if labels.get('memstack.project_id') == self.config.project_id:
                    project_sandbox_id = sandbox.id
                    break

            if not project_sandbox_id:
                return False

            # Check if we already have sandbox tools loaded
            sandbox_prefix = f"sandbox_{project_sandbox_id}_"
            has_sandbox_tools = any(
                name.startswith(sandbox_prefix) for name in self._tools.keys()
            )

            if has_sandbox_tools:
                # Sandbox tools already loaded
                return False

            # Sandbox exists but tools not loaded - refresh tools
            logger.info(
                f"ProjectReActAgent[{self.project_key}]: "
                f"Detected new sandbox {project_sandbox_id}, refreshing tools..."
            )

            # Re-initialize with force_refresh to load sandbox tools
            success = await self.initialize(force_refresh=True)
            return success

        except Exception as e:
            logger.warning(
                f"ProjectReActAgent[{self.project_key}]: "
                f"Error checking sandbox tools: {e}"
            )
            return False

    async def execute_chat(
        self,
        conversation_id: str,
        user_message: str,
        user_id: str,
        conversation_context: Optional[List[Dict[str, str]]] = None,
        tenant_id: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Execute a chat request using the project agent.

        This method:
        1. Ensures agent is initialized
        2. Acquires execution lock (respects max_concurrent_chats)
        3. Executes the ReActAgent stream
        4. Updates metrics and status
        5. Yields events for streaming

        Args:
            conversation_id: Conversation ID
            user_message: User's message
            user_id: User ID
            conversation_context: Optional conversation history
            tenant_id: Optional tenant ID (defaults to config.tenant_id)

        Yields:
            Event dictionaries for streaming
        """
        if not self._initialized:
            # Auto-initialize on first use
            success = await self.initialize()
            if not success:
                yield {
                    "type": "error",
                    "data": {
                        "message": "Agent initialization failed",
                        "code": "AGENT_NOT_INITIALIZED",
                    },
                    "timestamp": datetime.utcnow().isoformat(),
                }
                return

        # Check if sandbox tools need to be refreshed (for sandboxes created after initialization)
        await self._check_and_refresh_sandbox_tools()

        if self._is_shutting_down:
            yield {
                "type": "error",
                "data": {
                    "message": "Agent is shutting down",
                    "code": "AGENT_SHUTTING_DOWN",
                },
                "timestamp": datetime.utcnow().isoformat(),
            }
            return

        # Check concurrent limit
        if self._status.active_chats >= self.config.max_concurrent_chats:
            yield {
                "type": "error",
                "data": {
                    "message": f"Max concurrent chats ({self.config.max_concurrent_chats}) reached",
                    "code": "MAX_CONCURRENT_CHATS",
                },
                "timestamp": datetime.utcnow().isoformat(),
            }
            return

        start_time = time.time()
        effective_tenant_id = tenant_id or self.config.tenant_id

        # Update status
        self._status.active_chats += 1
        self._status.is_executing = True
        self._status.last_activity_at = datetime.utcnow().isoformat()

        final_content = ""
        is_error = False
        error_message = None
        event_count = 0

        try:
            logger.info(
                f"ProjectReActAgent[{self.project_key}]: Executing chat "
                f"conversation={conversation_id}, user={user_id}"
            )

            # Execute ReActAgent stream
            async for event in self._react_agent.stream(
                conversation_id=conversation_id,
                user_message=user_message,
                project_id=self.config.project_id,
                user_id=user_id,
                tenant_id=effective_tenant_id,
                conversation_context=conversation_context or [],
            ):
                event_count += 1

                # Track content from complete events
                event_type = event.get("type")
                if event_type == "complete":
                    final_content = event.get("data", {}).get("content", "")
                elif event_type == "error":
                    is_error = True
                    error_message = event.get("data", {}).get("message", "Unknown error")

                yield event

            # Update metrics
            execution_time_ms = (time.time() - start_time) * 1000
            self._latencies.append(execution_time_ms)
            self._trim_latencies()

            self._update_metrics(execution_time_ms, is_error)

            if is_error:
                self._status.failed_chats += 1
                self._status.last_error = error_message
                logger.warning(
                    f"ProjectReActAgent[{self.project_key}]: Chat failed: {error_message}"
                )
            else:
                self._status.total_chats += 1
                logger.info(
                    f"ProjectReActAgent[{self.project_key}]: Chat completed in {execution_time_ms:.1f}ms, "
                    f"events={event_count}"
                )

        except Exception as e:
            is_error = True
            error_message = str(e)
            self._status.last_error = error_message
            self._status.failed_chats += 1

            logger.error(
                f"ProjectReActAgent[{self.project_key}]: Chat execution error: {e}",
                exc_info=True
            )

            yield {
                "type": "error",
                "data": {
                    "message": error_message,
                    "code": "CHAT_EXECUTION_ERROR",
                },
                "timestamp": datetime.utcnow().isoformat(),
            }

        finally:
            self._status.active_chats -= 1
            self._status.is_executing = self._status.active_chats > 0

    async def pause(self) -> bool:
        """
        Pause the agent (prevents new chats but allows current to complete).

        Returns:
            True if paused successfully
        """
        if not self._initialized:
            return False

        self._status.is_active = False
        logger.info(f"ProjectReActAgent[{self.project_key}]: Paused")
        return True

    async def resume(self) -> bool:
        """
        Resume a paused agent.

        Returns:
            True if resumed successfully
        """
        if not self._initialized:
            return await self.initialize()

        self._status.is_active = True
        logger.info(f"ProjectReActAgent[{self.project_key}]: Resumed")
        return True

    async def stop(self) -> bool:
        """
        Stop the agent and clean up resources.

        This method:
        1. Sets shutdown flag (prevents new chats)
        2. Waits for current chats to complete (with timeout)
        3. Clears caches
        4. Updates status

        Returns:
            True if stopped successfully
        """
        if not self._initialized:
            return True

        logger.info(f"ProjectReActAgent[{self.project_key}]: Stopping...")
        self._is_shutting_down = True

        # Wait for current executions to complete
        wait_start = time.time()
        timeout = 30.0  # 30 seconds timeout

        while self._status.active_chats > 0 and (time.time() - wait_start) < timeout:
            await asyncio.sleep(0.1)

        if self._status.active_chats > 0:
            logger.warning(
                f"ProjectReActAgent[{self.project_key}]: Timeout waiting for "
                f"{self._status.active_chats} active chats"
            )

        # Clear session cache
        try:
            from src.infrastructure.adapters.secondary.temporal.agent_session_pool import (
                invalidate_agent_session,
            )

            invalidate_agent_session(
                tenant_id=self.config.tenant_id,
                project_id=self.config.project_id,
                agent_mode=self.config.agent_mode,
            )
        except Exception as e:
            logger.warning(f"ProjectReActAgent[{self.project_key}]: Failed to clear cache: {e}")

        # Update status
        self._initialized = False
        self._status.is_initialized = False
        self._status.is_active = False
        self._status.is_executing = False

        # Clear references
        self._tools = None
        self._skills = None
        self._subagents = None
        self._session_context = None
        self._react_agent = None

        logger.info(f"ProjectReActAgent[{self.project_key}]: Stopped")
        return True

    async def refresh(self) -> bool:
        """
        Refresh the agent (reload tools, skills, clear caches).

        Returns:
            True if refreshed successfully
        """
        logger.info(f"ProjectReActAgent[{self.project_key}]: Refreshing...")

        # Stop current instance
        await self.stop()

        # Re-initialize with force refresh
        return await self.initialize(force_refresh=True)

    def get_status(self) -> ProjectAgentStatus:
        """Get current agent status."""
        # Update calculated fields
        if self._latencies:
            self._status.avg_execution_time_ms = sum(self._latencies) / len(self._latencies)

        return self._status

    def get_metrics(self) -> ProjectAgentMetrics:
        """Get detailed metrics."""
        # Calculate percentiles
        if self._latencies:
            sorted_latencies = sorted(self._latencies)
            n = len(sorted_latencies)
            self._metrics.latency_p50 = sorted_latencies[int(n * 0.5)]
            self._metrics.latency_p95 = sorted_latencies[int(n * 0.95)] if n >= 20 else sorted_latencies[-1]
            self._metrics.latency_p99 = sorted_latencies[int(n * 0.99)] if n >= 100 else sorted_latencies[-1]

        return self._metrics

    async def _load_subagents(self) -> List[SubAgent]:
        """
        Load subagents for the project.

        Loads enabled subagents from the repository scoped to the project.
        Subagents are used for specialized agent routing (L3 layer).

        Returns:
            List of enabled SubAgent instances for the project
        """
        from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
        from src.infrastructure.adapters.secondary.persistence.sql_subagent_repository import (
            SQLSubAgentRepository,
        )

        try:
            async with async_session_factory() as session:
                repository = SQLSubAgentRepository(session)

                # Load enabled subagents for the project
                subagents = await repository.list_by_project(
                    project_id=self.config.project_id,
                    enabled_only=True,
                )

                logger.debug(
                    f"ProjectReActAgent[{self.project_key}]: Loaded {len(subagents)} subagents"
                )
                return subagents

        except Exception as e:
            logger.warning(
                f"ProjectReActAgent[{self.project_key}]: Failed to load subagents: {e}"
            )
            # Return empty list on error - subagents are optional
            return []

    def _update_metrics(self, execution_time_ms: float, is_error: bool) -> None:
        """Update metrics after execution."""
        self._metrics.total_requests += 1

        if is_error:
            self._metrics.failed_requests += 1
        else:
            self._metrics.successful_requests += 1

        self._metrics.total_execution_time_ms += execution_time_ms

    def _trim_latencies(self, max_size: int = 1000) -> None:
        """Trim latency history to prevent unbounded growth."""
        if len(self._latencies) > max_size:
            # Keep most recent 90% and sample from older 10%
            keep_count = int(max_size * 0.9)
            sample_count = max_size - keep_count

            recent = self._latencies[-keep_count:]
            old = self._latencies[:-keep_count]

            # Sample from old latencies
            if old:
                step = len(old) // sample_count
                sampled = old[::step][:sample_count]
                self._latencies = sampled + recent
            else:
                self._latencies = recent


class ProjectAgentManager:
    """
    Manager for project-level ReAct Agent instances.

    This class manages multiple ProjectReActAgent instances, providing:
    - Lifecycle management (create, get, stop)
    - Resource pooling and sharing
    - Health monitoring
    - Cleanup of idle instances

    Usage:
        manager = ProjectAgentManager()
        
        # Get or create project agent
        agent = await manager.get_or_create_agent(
            tenant_id="tenant-123",
            project_id="project-456"
        )
        
        # Get existing agent
        agent = manager.get_agent("tenant-123", "project-456")
        
        # Stop project agent
        await manager.stop_agent("tenant-123", "project-456")
        
        # Stop all agents
        await manager.stop_all()
    """

    def __init__(self):
        """Initialize the project agent manager."""
        self._agents: Dict[str, ProjectReActAgent] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._is_running = False

    async def start(self) -> None:
        """Start the manager and background tasks."""
        self._is_running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("ProjectAgentManager: Started")

    async def stop(self) -> None:
        """Stop the manager and all managed agents."""
        self._is_running = False

        # Cancel cleanup task
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # Stop all agents
        await self.stop_all()
        logger.info("ProjectAgentManager: Stopped")

    async def get_or_create_agent(
        self,
        tenant_id: str,
        project_id: str,
        agent_mode: str = "default",
        config_override: Optional[Dict[str, Any]] = None,
    ) -> Optional[ProjectReActAgent]:
        """
        Get or create a project agent instance.

        Args:
            tenant_id: Tenant ID
            project_id: Project ID
            agent_mode: Agent mode (default: "default")
            config_override: Optional configuration overrides

        Returns:
            ProjectReActAgent instance or None if creation failed
        """
        key = f"{tenant_id}:{project_id}:{agent_mode}"

        async with self._lock:
            # Check if already exists
            if key in self._agents:
                agent = self._agents[key]
                if agent.is_active:
                    logger.debug(f"ProjectAgentManager: Returning existing agent for {key}")
                    return agent
                else:
                    # Agent exists but is not active, remove it
                    logger.warning(f"ProjectAgentManager: Replacing inactive agent for {key}")
                    del self._agents[key]

            # Create new agent
            config = ProjectAgentConfig(
                tenant_id=tenant_id,
                project_id=project_id,
                agent_mode=agent_mode,
            )

            # Apply overrides
            if config_override:
                for field_name, value in config_override.items():
                    if hasattr(config, field_name):
                        setattr(config, field_name, value)

            agent = ProjectReActAgent(config)

            # Initialize the agent
            success = await agent.initialize()
            if not success:
                logger.error(f"ProjectAgentManager: Failed to initialize agent for {key}")
                return None

            self._agents[key] = agent
            logger.info(f"ProjectAgentManager: Created agent for {key}")
            return agent

    def get_agent(
        self,
        tenant_id: str,
        project_id: str,
        agent_mode: str = "default",
    ) -> Optional[ProjectReActAgent]:
        """
        Get an existing project agent (without creating).

        Args:
            tenant_id: Tenant ID
            project_id: Project ID
            agent_mode: Agent mode (default: "default")

        Returns:
            ProjectReActAgent instance or None if not found
        """
        key = f"{tenant_id}:{project_id}:{agent_mode}"
        return self._agents.get(key)

    async def stop_agent(
        self,
        tenant_id: str,
        project_id: str,
        agent_mode: str = "default",
    ) -> bool:
        """
        Stop and remove a project agent.

        Args:
            tenant_id: Tenant ID
            project_id: Project ID
            agent_mode: Agent mode (default: "default")

        Returns:
            True if agent was stopped
        """
        key = f"{tenant_id}:{project_id}:{agent_mode}"

        async with self._lock:
            agent = self._agents.pop(key, None)
            if agent:
                await agent.stop()
                logger.info(f"ProjectAgentManager: Stopped agent for {key}")
                return True

        return False

    async def stop_all(self) -> None:
        """Stop all managed agents."""
        async with self._lock:
            agents_to_stop = list(self._agents.values())
            self._agents.clear()

        # Stop agents outside lock to avoid blocking
        for agent in agents_to_stop:
            try:
                await agent.stop()
            except Exception as e:
                logger.warning(f"ProjectAgentManager: Error stopping agent: {e}")

        logger.info(f"ProjectAgentManager: Stopped {len(agents_to_stop)} agents")

    def list_agents(self) -> List[Dict[str, Any]]:
        """
        List all managed agents and their status.

        Returns:
            List of agent status dictionaries
        """
        return [
            {
                "key": key,
                "tenant_id": agent.config.tenant_id,
                "project_id": agent.config.project_id,
                "agent_mode": agent.config.agent_mode,
                "is_initialized": agent.is_initialized,
                "is_active": agent.is_active,
                "status": agent.get_status(),
            }
            for key, agent in self._agents.items()
        ]

    async def _cleanup_loop(self) -> None:
        """Background task to cleanup idle agents."""
        while self._is_running:
            try:
                await asyncio.sleep(300)  # Run every 5 minutes

                if not self._is_running:
                    break

                await self._cleanup_idle_agents()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"ProjectAgentManager: Cleanup error: {e}")
                await asyncio.sleep(60)  # Wait before retry

    async def _cleanup_idle_agents(self, idle_threshold_seconds: int = 3600) -> int:
        """
        Cleanup agents that have been idle for too long.

        Args:
            idle_threshold_seconds: Idle time threshold (default: 1 hour)

        Returns:
            Number of agents cleaned up
        """
        now = datetime.utcnow()
        agents_to_stop = []

        async with self._lock:
            for key, agent in list(self._agents.items()):
                if not agent.is_active or agent._status.active_chats > 0:
                    continue

                last_activity = agent._status.last_activity_at
                if last_activity:
                    last_activity_time = datetime.fromisoformat(last_activity)
                    idle_seconds = (now - last_activity_time).total_seconds()

                    if idle_seconds > idle_threshold_seconds:
                        agents_to_stop.append(key)

            # Remove from active agents dict
            for key in agents_to_stop:
                self._agents.pop(key, None)

        # Stop agents outside lock
        for key in agents_to_stop:
            try:
                # Get agent from local list (already removed from dict)
                agent = next(
                    (a for k, a in self._agents.items() if k == key),
                    None
                )
                if agent:
                    await agent.stop()
                    logger.info(f"ProjectAgentManager: Cleaned up idle agent {key}")
            except Exception as e:
                logger.warning(f"ProjectAgentManager: Error cleaning up agent {key}: {e}")

        if agents_to_stop:
            logger.info(f"ProjectAgentManager: Cleaned up {len(agents_to_stop)} idle agents")

        return len(agents_to_stop)


# Global manager instance
_project_agent_manager: Optional[ProjectAgentManager] = None
_manager_lock = asyncio.Lock()


async def get_project_agent_manager() -> ProjectAgentManager:
    """
    Get the global ProjectAgentManager instance.

    Returns:
        ProjectAgentManager singleton
    """
    global _project_agent_manager

    if _project_agent_manager is None:
        async with _manager_lock:
            if _project_agent_manager is None:
                _project_agent_manager = ProjectAgentManager()
                await _project_agent_manager.start()
                logger.info("ProjectAgentManager: Global instance created")

    return _project_agent_manager


async def stop_project_agent_manager() -> None:
    """Stop the global ProjectAgentManager."""
    global _project_agent_manager

    if _project_agent_manager:
        await _project_agent_manager.stop()
        _project_agent_manager = None
        logger.info("ProjectAgentManager: Global instance stopped")
