"""
Project-level ReAct Agent Lifecycle Management.

This module provides a project-scoped ReActAgent wrapper that manages
the complete lifecycle of an agent instance for a specific project.
Each project has its own persistent Temporal workflow instance with:
- Isolated tool sets and configurations
- Project-scoped caching
- Independent lifecycle management
- Resource isolation
- WebSocket notifications for lifecycle state changes

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
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.domain.model.agent.skill import Skill
from src.domain.model.agent.subagent import SubAgent

logger = logging.getLogger(__name__)

# Global reference to the WebSocket connection manager
# Set by the web application on startup
_websocket_manager: Any | None = None


def get_websocket_notifier() -> Any | None:
    """
    Get the global WebSocket notifier.

    Returns the WebSocketNotifier instance if the connection manager
    has been registered, otherwise returns None.

    Returns:
        WebSocketNotifier instance or None
    """
    if _websocket_manager is None:
        return None

    from src.infrastructure.adapters.secondary.websocket_notifier import (
        WebSocketNotifier,
    )

    return WebSocketNotifier(_websocket_manager)


def register_websocket_manager(manager: Any) -> None:
    """
    Register the WebSocket connection manager globally.

    This should be called during application startup to enable
    lifecycle state notifications.

    Args:
        manager: ConnectionManager instance from agent_websocket.py
    """
    global _websocket_manager
    _websocket_manager = manager
    logger.info("[ProjectReActAgent] WebSocket manager registered for lifecycle notifications")


@dataclass
class ProjectAgentConfig:
    """Configuration for a project-level agent instance."""

    tenant_id: str
    project_id: str
    agent_mode: str = "default"

    # LLM Configuration
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.7
    max_tokens: int = 4096
    max_steps: int = 20

    # Session Configuration
    # Note: Agent now runs persistently until explicitly stopped
    persistent: bool = True  # Agent runs forever until explicitly stopped
    idle_timeout_seconds: int = 3600  # 1 hour idle timeout
    max_concurrent_chats: int = 10

    # Tool Configuration
    mcp_tools_ttl_seconds: int = 300  # 5 minutes

    # Feature Flags
    enable_skills: bool = True
    enable_subagents: bool = True


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

    created_at: str | None = None
    last_activity_at: str | None = None
    last_error: str | None = None

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

    tool_execution_count: dict[str, int] = field(default_factory=dict)
    skill_invocation_count: dict[str, int] = field(default_factory=dict)

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

    def __init__(self, config: ProjectAgentConfig) -> None:
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
            created_at=datetime.now(UTC).isoformat(),
        )
        self._metrics = ProjectAgentMetrics()

        # Cached components (initialized in initialize())
        self._tools: dict[str, Any] | None = None
        self._skills: list[Skill] | None = None
        self._subagents: list[SubAgent] | None = None
        self._session_context: Any | None = None
        self._react_agent: Any | None = None

        # Execution tracking
        self._execution_lock = asyncio.Lock()
        self._is_shutting_down = False
        self._initialized = False

        # Latency tracking for percentiles
        self._latencies: list[float] = []

        # Optional plan repository for Plan Mode awareness
        self._plan_repo: Any | None = None

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
        1. Sends 'initializing' lifecycle notification
        2. Loads project-specific tools (including MCP tools)
        3. Loads skills for the project
        4. Creates SubAgentRouter if enabled
        5. Pre-converts tool definitions
        6. Initializes the ReActAgent instance
        7. Sends 'ready' lifecycle notification on success
        8. Sends 'error' lifecycle notification on failure

        Args:
            force_refresh: Force refresh of all caches

        Returns:
            True if initialization succeeded
        """
        if self._initialized and not force_refresh:
            logger.debug(f"ProjectReActAgent[{self.project_key}]: Already initialized")
            return True

        start_time = time.time()
        notifier = get_websocket_notifier()

        # Notify initialization started
        if notifier:
            await notifier.notify_initializing(
                tenant_id=self.config.tenant_id,
                project_id=self.config.project_id,
            )

        try:
            logger.info(f"ProjectReActAgent[{self.project_key}]: Initializing...")

            # Import dependencies here to avoid circular imports
            from src.configuration.di_container import DIContainer as Container
            from src.infrastructure.agent.core.processor import ProcessorConfig
            from src.infrastructure.agent.core.react_agent import ReActAgent
            from src.infrastructure.agent.state.agent_worker_state import (
                get_or_create_agent_graph_service,
                get_or_create_agent_session,
                get_or_create_llm_client,
                get_or_create_provider_config,
                get_or_create_skills,
                get_or_create_tools,
                get_redis_client,
            )

            # Graph service must be resolved by tenant so embedding/rerank mappings are honored.
            graph_service = await get_or_create_agent_graph_service(tenant_id=self.config.tenant_id)
            if not graph_service:
                raise RuntimeError("Graph service not available")

            redis_client = await get_redis_client()

            # Get artifact service for rich output handling
            try:
                container = Container()
                artifact_service = container.artifact_service()
            except Exception as e:
                logger.warning(f"Could not initialize artifact service: {e}")
                artifact_service = None

            # Get LLM provider configuration
            # Use tenant-specific provider resolution via AIServiceFactory
            provider_config = await get_or_create_provider_config(
                tenant_id=self.config.tenant_id, force_refresh=force_refresh
            )
            llm_client = await get_or_create_llm_client(tenant_id=self.config.tenant_id)

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

            # Create processor config with llm_client for unified resilience
            processor_config = ProcessorConfig(
                model=provider_config.llm_model,
                api_key="",  # Will be set from provider_config
                base_url=provider_config.base_url,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                max_steps=self.config.max_steps,
                llm_client=llm_client,  # Pass cached LiteLLMClient for circuit breaker + rate limiter
            )

            # Store artifact_service for use in ReActAgent
            self._artifact_service = artifact_service

            # Memory services: recall preprocessor + capture postprocessor + flush
            memory_recall = None
            memory_capture = None
            memory_flush = None
            try:
                from src.infrastructure.agent.memory.capture import MemoryCapturePostprocessor
                from src.infrastructure.agent.memory.recall import MemoryRecallPreprocessor
                from src.infrastructure.memory.cached_embedding import CachedEmbeddingService
                from src.infrastructure.memory.chunk_search import ChunkHybridSearch

                # Session factory for on-demand DB access (shared by all memory services)
                session_factory = None
                try:
                    from src.infrastructure.adapters.secondary.persistence.database import (
                        async_session_factory,
                    )

                    session_factory = async_session_factory
                except Exception:
                    pass

                embedding_service = getattr(graph_service, "embedder", None)
                if embedding_service and redis_client:
                    cached_embedding = CachedEmbeddingService(embedding_service, redis_client)
                    chunk_search = ChunkHybridSearch(cached_embedding, session_factory)
                    memory_recall = MemoryRecallPreprocessor(
                        chunk_search=chunk_search,
                        graph_search=graph_service,
                    )
                    logger.info(f"ProjectReActAgent[{self.project_key}]: Memory recall enabled")

                # LLM-driven capture (requires llm_client, works without chunk_repo/embedding)
                if llm_client:
                    cached_emb = (
                        CachedEmbeddingService(embedding_service, redis_client)
                        if embedding_service and redis_client
                        else None
                    )
                    memory_capture = MemoryCapturePostprocessor(
                        llm_client=llm_client,
                        session_factory=session_factory,
                        embedding_service=cached_emb,
                    )
                    logger.info(f"ProjectReActAgent[{self.project_key}]: Memory capture enabled")

                    # Pre-compaction flush shares LLM + session_factory
                    from src.infrastructure.agent.memory.flush import MemoryFlushService

                    memory_flush = MemoryFlushService(
                        llm_client=llm_client,
                        embedding_service=cached_emb,
                        session_factory=session_factory,
                    )
            except Exception as e:
                logger.debug(f"Memory services not available: {e}")

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
            # Build context window config from application settings
            from src.configuration.config import get_settings
            from src.infrastructure.agent.context.window_manager import ContextWindowConfig
            from src.infrastructure.llm.model_registry import (
                clamp_max_tokens as _clamp_max_tokens,
                get_model_context_window,
            )

            app_settings = get_settings()
            model_context_window = get_model_context_window(provider_config.llm_model)
            clamped_max_tokens = _clamp_max_tokens(
                provider_config.llm_model, self.config.max_tokens
            )
            context_window_config = ContextWindowConfig(
                max_context_tokens=model_context_window,
                max_output_tokens=clamped_max_tokens,
                l1_trigger_pct=app_settings.compression_l1_trigger_pct,
                l2_trigger_pct=app_settings.compression_l2_trigger_pct,
                l3_trigger_pct=app_settings.compression_l3_trigger_pct,
                chunk_size=app_settings.compression_chunk_size,
                summary_max_tokens=app_settings.compression_summary_max_tokens,
                prune_min_tokens=app_settings.compression_prune_min_tokens,
                prune_protect_tokens=app_settings.compression_prune_protect_tokens,
                prune_protected_tools=app_settings.compression_prune_protected_tools,
                assistant_truncate_chars=app_settings.compression_assistant_truncate_chars,
                truncate_user=app_settings.compression_truncate_user,
                truncate_assistant=app_settings.compression_truncate_assistant,
                truncate_tool=app_settings.compression_truncate_tool,
                truncate_system=app_settings.compression_truncate_system,
            )

            async def _subagent_lifecycle_hook(event: dict[str, Any]) -> None:
                if not notifier:
                    return
                await notifier.notify_subagent_lifecycle_event(
                    tenant_id=self.config.tenant_id,
                    project_id=self.config.project_id,
                    event=event,
                )

            self._react_agent = ReActAgent(
                model=provider_config.llm_model,
                tools=self._tools,
                api_key=None,  # Set from provider_config during execution
                base_url=provider_config.base_url,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                max_steps=self.config.max_steps,
                agent_mode=self.config.agent_mode,
                context_window_config=context_window_config,
                skills=self._skills,
                subagents=self._subagents,
                artifact_service=self._artifact_service,  # Pass artifact service
                llm_client=llm_client,  # Pass cached LiteLLMClient
                resource_sync_service=self._session_context.resource_sync_service,
                graph_service=graph_service,  # Pass graph service for SubAgent memory sharing
                # Memory auto-recall / auto-capture / pre-compaction flush
                memory_recall=memory_recall,
                memory_capture=memory_capture,
                memory_flush=memory_flush,
                max_subagent_delegation_depth=app_settings.agent_subagent_max_delegation_depth,
                max_subagent_active_runs=app_settings.agent_subagent_max_active_runs,
                max_subagent_children_per_requester=(
                    app_settings.agent_subagent_max_children_per_requester
                ),
                max_subagent_lane_concurrency=app_settings.agent_subagent_lane_concurrency,
                subagent_terminal_retention_seconds=(
                    app_settings.agent_subagent_terminal_retention_seconds
                ),
                subagent_announce_max_events=app_settings.agent_subagent_announce_max_events,
                subagent_announce_max_retries=app_settings.agent_subagent_announce_max_retries,
                subagent_announce_retry_delay_ms=(
                    app_settings.agent_subagent_announce_retry_delay_ms
                ),
                subagent_lifecycle_hook=_subagent_lifecycle_hook,
                # Use cached components from session pool
                _cached_tool_definitions=self._session_context.tool_definitions,
                _cached_system_prompt_manager=self._session_context.system_prompt_manager,
                _cached_subagent_router=self._session_context.subagent_router,
            )

            # Calculate detailed tool statistics
            builtin_tool_count = 0
            mcp_tool_count = 0
            for tool_name in self._tools.keys():
                # MCP tools have prefixes like "mcp_", "sandbox_", or server-specific prefixes
                if tool_name.startswith(("mcp_", "sandbox_")) or "_mcp_" in tool_name:
                    mcp_tool_count += 1
                else:
                    builtin_tool_count += 1

            # Calculate skill statistics
            loaded_skill_count = len(self._skills) if self._skills else 0
            # TODO: Get total_skill_count from skill registry if available
            total_skill_count = loaded_skill_count  # For now, same as loaded

            # Update status
            self._initialized = True
            self._status.is_initialized = True
            self._status.is_active = True
            self._status.tool_count = len(self._tools)
            self._status.skill_count = loaded_skill_count
            self._status.subagent_count = len(self._subagents) if self._subagents else 0

            init_time_ms = (time.time() - start_time) * 1000
            logger.info(
                f"ProjectReActAgent[{self.project_key}]: Initialized in {init_time_ms:.1f}ms, "
                f"tools={self._status.tool_count} (builtin={builtin_tool_count}, mcp={mcp_tool_count}), "
                f"skills={loaded_skill_count}"
            )

            # Notify ready state with detailed stats
            if notifier:
                await notifier.notify_ready(
                    tenant_id=self.config.tenant_id,
                    project_id=self.config.project_id,
                    tool_count=self._status.tool_count,
                    builtin_tool_count=builtin_tool_count,
                    mcp_tool_count=mcp_tool_count,
                    skill_count=loaded_skill_count,
                    total_skill_count=total_skill_count,
                    loaded_skill_count=loaded_skill_count,
                    subagent_count=self._status.subagent_count,
                )

            return True

        except Exception as e:
            self._status.last_error = str(e)
            error_message = str(e)

            logger.error(
                f"ProjectReActAgent[{self.project_key}]: Initialization failed: {e}", exc_info=True
            )

            # Notify error state
            if notifier:
                await notifier.notify_error(
                    tenant_id=self.config.tenant_id,
                    project_id=self.config.project_id,
                    error_message=error_message,
                )

            return False

    async def _check_and_refresh_mcp_tools(self) -> bool:
        """Check if MCP tools need to be refreshed and refresh if needed.

        Compares the count of MCP tools currently loaded in the agent against
        the count of discovered tools in the database for enabled servers.
        If they differ, triggers a full tool refresh.

        Returns:
            True if tools were refreshed, False otherwise
        """
        if not self._initialized or not self._tools:
            return False

        try:
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )
            from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
                SqlMCPServerRepository,
            )

            async with async_session_factory() as session:
                repo = SqlMCPServerRepository(session)
                servers = await repo.list_by_project(self.config.project_id, enabled_only=True)

            # Count expected MCP tools from DB
            db_tool_count = 0
            for server in servers:
                discovered = server.discovered_tools or []
                db_tool_count += len(discovered)

            # Count current MCP tools in agent
            current_mcp_count = sum(1 for name in self._tools.keys() if name.startswith("mcp__"))

            if db_tool_count == current_mcp_count:
                return False

            logger.info(
                f"ProjectReActAgent[{self.project_key}]: "
                f"MCP tools changed (loaded={current_mcp_count}, db={db_tool_count}), "
                f"refreshing tools..."
            )

            success = await self.initialize(force_refresh=True)
            return success

        except Exception as e:
            logger.warning(f"ProjectReActAgent[{self.project_key}]: Error checking MCP tools: {e}")
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
            from src.infrastructure.agent.state.agent_worker_state import (
                get_mcp_sandbox_adapter,
            )

            sandbox_adapter = get_mcp_sandbox_adapter()
            if not sandbox_adapter:
                return False

            # Check if there's an active sandbox for this project
            all_sandboxes = await sandbox_adapter.list_sandboxes()
            project_sandbox_id = None

            for sandbox in all_sandboxes:
                project_path = getattr(sandbox, "project_path", "") or ""
                if project_path and f"memstack_{self.config.project_id}" in project_path:
                    project_sandbox_id = sandbox.id
                    break

                labels = getattr(sandbox, "labels", {}) or {}
                if labels.get("memstack.project_id") == self.config.project_id:
                    project_sandbox_id = sandbox.id
                    break

            if not project_sandbox_id:
                return False

            # Check if we already have sandbox tools loaded
            # SandboxMCPToolWrapper registers tools with original names (no prefix),
            # so check for the sandbox_id attribute instead
            has_sandbox_tools = any(
                getattr(tool, "sandbox_id", None) == project_sandbox_id
                for tool in self._tools.values()
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
                f"ProjectReActAgent[{self.project_key}]: Error checking sandbox tools: {e}"
            )
            return False

    async def execute_chat(
        self,
        conversation_id: str,
        user_message: str,
        user_id: str,
        conversation_context: list[dict[str, str]] | None = None,
        tenant_id: str | None = None,
        message_id: str | None = None,
        abort_signal: asyncio.Event | None = None,
        file_metadata: list[dict[str, Any]] | None = None,
        forced_skill_name: str | None = None,
        context_summary_data: dict[str, Any] | None = None,
        plan_mode: bool = False,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Execute a chat request using the project agent.

        This method:
        1. Ensures agent is initialized
        2. Sends 'executing' lifecycle notification
        3. Acquires execution lock (respects max_concurrent_chats)
        4. Executes the ReActAgent stream
        5. Updates metrics and status
        6. Sends 'ready' lifecycle notification on completion
        7. Sends 'error' lifecycle notification on failure
        8. Yields events for streaming

        Args:
            conversation_id: Conversation ID
            user_message: User's message
            user_id: User ID
            conversation_context: Optional conversation history
            tenant_id: Optional tenant ID (defaults to config.tenant_id)
            message_id: Optional message ID for HITL request persistence
            hitl_response: Optional HITL response for resuming from HITL pause

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
                    "timestamp": datetime.now(UTC).isoformat(),
                }
                return

        # Check if sandbox tools need to be refreshed (for sandboxes created after initialization)
        await self._check_and_refresh_sandbox_tools()

        # Check if MCP tools need to be refreshed (for MCP servers added after initialization)
        await self._check_and_refresh_mcp_tools()

        if self._is_shutting_down:
            yield {
                "type": "error",
                "data": {
                    "message": "Agent is shutting down",
                    "code": "AGENT_SHUTTING_DOWN",
                },
                "timestamp": datetime.now(UTC).isoformat(),
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
                "timestamp": datetime.now(UTC).isoformat(),
            }
            return

        start_time = time.time()
        effective_tenant_id = tenant_id or self.config.tenant_id
        notifier = get_websocket_notifier()

        # Update status
        self._status.active_chats += 1
        self._status.is_executing = True
        self._status.last_activity_at = datetime.now(UTC).isoformat()

        # Notify executing state
        if notifier:
            await notifier.notify_executing(
                tenant_id=self.config.tenant_id,
                project_id=self.config.project_id,
                conversation_id=conversation_id,
            )

        is_error = False
        error_message = None
        event_count = 0

        try:
            logger.info(
                f"ProjectReActAgent[{self.project_key}]: Executing chat "
                f"conversation={conversation_id}, user={user_id}"
            )

            # Plan Mode check: use parameter from caller (set from conversation.current_mode)
            is_plan_mode = plan_mode

            # Execute ReActAgent stream
            async for event in self._react_agent.stream(
                conversation_id=conversation_id,
                user_message=user_message,
                project_id=self.config.project_id,
                user_id=user_id,
                tenant_id=effective_tenant_id,
                conversation_context=conversation_context or [],
                message_id=message_id,
                abort_signal=abort_signal,
                attachment_metadata=file_metadata,
                forced_skill_name=forced_skill_name,
                context_summary_data=context_summary_data,
                plan_mode=is_plan_mode,
            ):
                event_count += 1

                # Track content from complete events
                event_type = event.get("type")
                if event_type == "complete":
                    pass  # Content is in the event itself
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
                f"ProjectReActAgent[{self.project_key}]: Chat execution error: {e}", exc_info=True
            )

            yield {
                "type": "error",
                "data": {
                    "message": error_message,
                    "code": "CHAT_EXECUTION_ERROR",
                },
                "timestamp": datetime.now(UTC).isoformat(),
            }

        finally:
            self._status.active_chats -= 1
            self._status.is_executing = self._status.active_chats > 0

            # Notify ready state after completion (or error)
            if notifier:
                if is_error and error_message:
                    await notifier.notify_error(
                        tenant_id=self.config.tenant_id,
                        project_id=self.config.project_id,
                        error_message=error_message,
                    )
                else:
                    await notifier.notify_ready(
                        tenant_id=self.config.tenant_id,
                        project_id=self.config.project_id,
                        tool_count=self._status.tool_count,
                        skill_count=self._status.skill_count,
                        subagent_count=self._status.subagent_count,
                    )

    async def pause(self) -> bool:
        """
        Pause the agent (prevents new chats but allows current to complete).

        Sends 'paused' lifecycle notification via WebSocket.

        Returns:
            True if paused successfully
        """
        if not self._initialized:
            return False

        self._status.is_active = False

        # Notify paused state
        notifier = get_websocket_notifier()
        if notifier:
            await notifier.notify_paused(
                tenant_id=self.config.tenant_id,
                project_id=self.config.project_id,
            )

        logger.info(f"ProjectReActAgent[{self.project_key}]: Paused")
        return True

    async def resume(self) -> bool:
        """
        Resume a paused agent.

        Sends 'ready' lifecycle notification via WebSocket.

        Returns:
            True if resumed successfully
        """
        if not self._initialized:
            return await self.initialize()

        self._status.is_active = True

        # Notify ready state
        notifier = get_websocket_notifier()
        if notifier:
            await notifier.notify_ready(
                tenant_id=self.config.tenant_id,
                project_id=self.config.project_id,
                tool_count=self._status.tool_count,
                skill_count=self._status.skill_count,
                subagent_count=self._status.subagent_count,
            )

        logger.info(f"ProjectReActAgent[{self.project_key}]: Resumed")
        return True

    async def stop(self) -> bool:
        """
        Stop the agent and clean up resources.

        This method:
        1. Sends 'shutting_down' lifecycle notification
        2. Sets shutdown flag (prevents new chats)
        3. Waits for current chats to complete (with timeout)
        4. Clears caches
        5. Updates status

        Returns:
            True if stopped successfully
        """
        if not self._initialized:
            return True

        logger.info(f"ProjectReActAgent[{self.project_key}]: Stopping...")
        self._is_shutting_down = True

        # Notify shutting down state
        notifier = get_websocket_notifier()
        if notifier:
            await notifier.notify_shutting_down(
                tenant_id=self.config.tenant_id,
                project_id=self.config.project_id,
            )

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
            from src.infrastructure.agent.state.agent_session_pool import (
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
            self._metrics.latency_p95 = (
                sorted_latencies[int(n * 0.95)] if n >= 20 else sorted_latencies[-1]
            )
            self._metrics.latency_p99 = (
                sorted_latencies[int(n * 0.99)] if n >= 100 else sorted_latencies[-1]
            )

        return self._metrics

    async def _load_subagents(self) -> list[SubAgent]:
        """
        Load subagents for the project from both filesystem and database.

        Merges SubAgents from .memstack/agents/*.md (filesystem) with
        database SubAgents. DB SubAgents override filesystem ones by name.

        Returns:
            List of enabled SubAgent instances for the project
        """
        from pathlib import Path

        from src.application.services.subagent_service import SubAgentService
        from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
        from src.infrastructure.adapters.secondary.persistence.sql_subagent_repository import (
            SqlSubAgentRepository,
        )
        from src.infrastructure.agent.subagent.filesystem_loader import (
            FileSystemSubAgentLoader,
        )

        db_subagents: list[SubAgent] = []
        fs_subagents: list[SubAgent] = []

        # Load from database
        try:
            async with async_session_factory() as session:
                repository = SqlSubAgentRepository(session)
                db_subagents = await repository.list_by_project(
                    project_id=self.config.project_id,
                    tenant_id=self.config.tenant_id,
                    enabled_only=True,
                )
        except Exception as e:
            logger.warning(
                f"ProjectReActAgent[{self.project_key}]: Failed to load DB subagents: {e}"
            )

        # Load from filesystem
        try:
            fs_loader = FileSystemSubAgentLoader(
                base_path=Path.cwd(),
                tenant_id=self.config.tenant_id,
                project_id=self.config.project_id,
            )
            service = SubAgentService(filesystem_loader=fs_loader)
            fs_subagents = await service.load_filesystem_subagents()
        except Exception as e:
            logger.warning(
                f"ProjectReActAgent[{self.project_key}]: Failed to load FS subagents: {e}"
            )

        # Merge: DB overrides FS by name
        service = SubAgentService()
        merged = service.merge(db_subagents, fs_subagents)

        # Filter to enabled only (FS agents respect their enabled field)
        enabled = [sa for sa in merged if sa.enabled]

        logger.debug(
            f"ProjectReActAgent[{self.project_key}]: "
            f"Loaded {len(enabled)} subagents (DB={len(db_subagents)}, FS={len(fs_subagents)})"
        )
        return enabled

    def _update_metrics(self, execution_time_ms: float, is_error: bool) -> None:
        """Update metrics after execution."""
        self._metrics.total_requests += 1

        if is_error:
            self._metrics.failed_requests += 1
        else:
            self._metrics.successful_requests += 1

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

    def __init__(self) -> None:
        """Initialize the project agent manager."""
        self._agents: dict[str, ProjectReActAgent] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task | None = None
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
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task

        # Stop all agents
        await self.stop_all()
        logger.info("ProjectAgentManager: Stopped")

    async def get_or_create_agent(
        self,
        tenant_id: str,
        project_id: str,
        agent_mode: str = "default",
        config_override: dict[str, Any] | None = None,
    ) -> ProjectReActAgent | None:
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
    ) -> ProjectReActAgent | None:
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

    def list_agents(self) -> list[dict[str, Any]]:
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
        now = datetime.now(UTC)
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
                agent = next((a for k, a in self._agents.items() if k == key), None)
                if agent:
                    await agent.stop()
                    logger.info(f"ProjectAgentManager: Cleaned up idle agent {key}")
            except Exception as e:
                logger.warning(f"ProjectAgentManager: Error cleaning up agent {key}: {e}")

        if agents_to_stop:
            logger.info(f"ProjectAgentManager: Cleaned up {len(agents_to_stop)} idle agents")

        return len(agents_to_stop)


# Global manager instance
_project_agent_manager: ProjectAgentManager | None = None
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
