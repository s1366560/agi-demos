# pyright: reportUninitializedInstanceVariable=false
"""
Self-developed ReAct Agent - Replaces LangGraph implementation.

This module provides a ReAct (Reasoning + Acting) agent implementation
using the self-developed SessionProcessor, replacing the LangGraph dependency.

Features:
- Multi-level thinking (Work Plan -> Steps -> Task execution)
- Real-time SSE streaming events
- Doom loop detection
- Intelligent retry with backoff
- Real-time cost tracking
- Permission control
- Skill System (L2 layer) - declarative tool compositions
- SubAgent System (L3 layer) - specialized agent routing

Reference: OpenCode SessionProcessor architecture
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections.abc import AsyncIterator, Callable, Coroutine, Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from src.domain.events.agent_events import (
    AgentDomainEvent,
)
from src.domain.model.agent.skill import Skill
from src.domain.model.agent.subagent import SubAgent
from src.domain.ports.agent.context_manager_port import ContextBuildRequest

from ..commands.builtins import register_builtin_commands
from ..commands.interceptor import CommandInterceptor
from ..commands.registry import CommandRegistry
from ..config import ExecutionConfig
from ..context import ContextFacade, ContextWindowConfig, ContextWindowManager
from ..events import EventConverter
from ..permission import PermissionManager
from ..planning.plan_detector import PlanDetector
from ..plugins.policy_context import PolicyContext, normalize_policy_layers
from ..plugins.selection_pipeline import (
    ToolSelectionContext,
    ToolSelectionTraceStep,
    build_default_tool_selection_pipeline,
)
from ..prompts import PromptContext, PromptMode, SystemPromptManager
from ..routing import (
    ExecutionPath,
    RoutingDecision,
)
from ..skill import SkillProtocol
from .processor import (
    ProcessorConfig,
    ProcessorFactory,
    RunContext,
    SessionProcessor,
    ToolDefinition,
)
from .subagent_router import SubAgentMatch, SubAgentRouter
from .subagent_runner import SubAgentRunnerDeps, SubAgentSessionRunner
from .subagent_tools import SubAgentToolBuilder, SubAgentToolBuilderDeps
from .tool_converter import convert_tools

if TYPE_CHECKING:
    from src.application.services.artifact_service import ArtifactService
    from src.domain.llm_providers.llm_types import LLMClient
    from src.domain.ports.services.graph_service_port import GraphServicePort

logger = logging.getLogger(__name__)
_react_bg_tasks: set[asyncio.Task[Any]] = set()


class ReActAgent:
    """
    Self-developed ReAct Agent implementation.

    Replaces the LangGraph-based ReActAgentGraph with a pure Python
    implementation using SessionProcessor.

    Features:
    - Multi-level thinking (work plan -> steps -> execution)
    - Streaming SSE events for real-time UI updates
    - Tool execution with permission control
    - Doom loop detection
    - Intelligent retry strategy
    - Cost tracking
    - Skill matching and execution (L2 layer)
    - SubAgent routing and delegation (L3 layer)

    Usage:
        agent = ReActAgent(
            model="gpt-4",
            tools=[...],
            api_key="...",
            skills=[...],       # Optional: available skills
            subagents=[...],    # Optional: available subagents
        )

        async for event in agent.stream(
            conversation_id="...",
            user_message="...",
            conversation_context=[...],
        ):
            yield event
    """

    _SUBAGENT_ANNOUNCE_MAX_EVENTS = 20
    _SUBAGENT_ANNOUNCE_MAX_RETRIES = 2
    _SUBAGENT_ANNOUNCE_RETRY_DELAY_MS = 200
    _DOMAIN_LANE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("plugin", ("plugin", "channel", "reload", "install", "uninstall", "enable", "disable")),
        ("mcp", ("mcp", "sandbox", "tool server", "connector")),
        ("governance", ("policy", "permission", "compliance", "audit", "risk", "guard")),
        ("code", ("code", "refactor", "test", "build", "compile", "debug", "function", "class")),
        ("data", ("memory", "entity", "graph", "sql", "database", "query", "episode")),
    )

    # -- Instance variable type declarations (for pyright) --
    # _init_tool_pipeline
    _tool_selection_pipeline: Any
    _tool_selection_max_tools: int
    _tool_selection_semantic_backend: str
    _router_mode_tool_count_threshold: int
    _tool_policy_layers: dict[str, dict[str, Any]]
    _last_tool_selection_trace: tuple[ToolSelectionTraceStep, ...]
    # _init_memory_hooks
    _memory_recall: Any
    _memory_capture: Any
    _memory_flush: Any
    # _init_prompt_and_context
    prompt_manager: Any
    context_manager: ContextWindowManager
    context_facade: ContextFacade
    # _init_skill_system
    skills: list[Skill]
    skill_match_threshold: float
    skill_fallback_on_error: bool
    skill_execution_timeout: int
    # _init_subagent_system
    subagents: list[SubAgent]
    subagent_match_threshold: float
    _enable_subagent_as_tool: bool
    _max_subagent_delegation_depth: int
    _max_subagent_active_runs: int
    _max_subagent_children_per_requester: int
    _max_subagent_active_runs_per_lineage: int
    _max_subagent_lane_concurrency: int
    _subagent_announce_max_events: int
    _subagent_announce_max_retries: int
    _subagent_announce_retry_delay_ms: int
    _subagent_lane_semaphore: asyncio.Semaphore
    _subagent_lifecycle_hook: Callable[[dict[str, Any]], Any] | None
    _subagent_lifecycle_hook_failures: list[int]
    # _init_subagent_router
    subagent_router: Any
    # _init_subagent_run_registry
    _subagent_run_registry: Any
    _subagent_session_tasks: dict[str, asyncio.Task[Any]]
    # _init_orchestrators
    _event_converter: EventConverter
    # _init_background_services
    _background_executor: Any
    _template_registry: Any
    _task_decomposer: Any
    _result_aggregator: Any
    # _init_tool_definitions
    tool_definitions: list[Any]
    _use_dynamic_tools: bool
    config: ProcessorConfig
    # stream-phase instance state
    _stream_skill_state: dict[str, Any]
    _stream_memory_context: Any
    _stream_context_result: Any
    _stream_messages: list[dict[str, Any]]
    _stream_cached_summary: Any
    _stream_tools_to_use: list[ToolDefinition]
    _stream_final_content: str
    _stream_success: bool

    def __init__(  # noqa: PLR0913
        self,
        model: str,
        tools: dict[str, Any] | None = None,  # Tool name -> Tool instance (static)
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        max_steps: int = 20,
        permission_manager: PermissionManager | None = None,
        skills: list[Skill] | None = None,
        subagents: list[SubAgent] | None = None,
        # Skill matching thresholds - increased to let LLM make autonomous decisions
        # LLM sees skill_loader tool with available skills list and decides when to load
        # Rule-based matching is now a fallback for very high confidence matches only
        skill_match_threshold: float = 0.9,  # Was 0.5, increased to reduce rule matching
        skill_fallback_on_error: bool = True,
        skill_execution_timeout: int = 300,  # Increased from 60 to 300 (5 minutes)
        subagent_match_threshold: float = 0.5,
        # SubAgent-as-Tool: let LLM autonomously decide delegation
        enable_subagent_as_tool: bool = True,
        max_subagent_delegation_depth: int = 2,
        max_subagent_active_runs: int = 16,
        max_subagent_children_per_requester: int = 8,
        max_subagent_active_runs_per_lineage: int = 8,
        max_subagent_lane_concurrency: int = 8,
        subagent_run_registry_path: str | None = None,
        subagent_run_postgres_dsn: str | None = None,
        subagent_run_sqlite_path: str | None = None,
        subagent_run_redis_cache_url: str | None = None,
        subagent_run_redis_cache_ttl_seconds: int = 60,
        subagent_terminal_retention_seconds: int = 86400,
        subagent_announce_max_events: int = 20,
        subagent_announce_max_retries: int = 2,
        subagent_announce_retry_delay_ms: int = 200,
        subagent_lifecycle_hook: Callable[[dict[str, Any]], Any] | None = None,
        # Context window management
        context_window_config: ContextWindowConfig | None = None,
        max_context_tokens: int = 128000,
        # Agent mode for skill filtering
        agent_mode: str = "default",
        # Project root for custom rules loading
        project_root: Path | None = None,
        # Artifact service for rich output handling
        artifact_service: ArtifactService | None = None,
        # LLM client for unified resilience (circuit breaker + rate limiter)
        llm_client: LLMClient | None = None,
        # Skill resource sync service for sandbox resource injection
        resource_sync_service: Any | None = None,
        # Graph service for SubAgent memory sharing (Phase 5.1)
        graph_service: GraphServicePort | None = None,
        # ====================================================================
        # Hot-plug support: Optional tool provider function for dynamic tools
        # When provided, tools are fetched at each stream() call instead of
        # being fixed at initialization time.
        # ====================================================================
        tool_provider: Callable[..., Any] | None = None,
        # ====================================================================
        # Agent Session Pool: Pre-cached components for performance optimization
        # These are internal parameters set by execute_react_agent_activity
        # when using the Agent Session Pool for component reuse.
        # ====================================================================
        _cached_tool_definitions: list[Any] | None = None,
        _cached_system_prompt_manager: Any | None = None,
        _cached_subagent_router: Any | None = None,
        # Plan Mode detection
        plan_detector: PlanDetector | None = None,
        # Memory auto-recall / auto-capture preprocessors
        memory_recall: Any | None = None,
        memory_capture: Any | None = None,
        memory_flush: Any | None = None,
        tool_selection_pipeline: Any | None = None,
        tool_selection_max_tools: int = 40,
        tool_selection_semantic_backend: str = "embedding_vector",
        router_mode_tool_count_threshold: int = 100,
        tool_policy_layers: Mapping[str, Any] | None = None,
    ) -> None:
        """
        Initialize ReAct Agent.

        Args:
            model: LLM model name (e.g., "gpt-4", "claude-3-opus")
            tools: Dictionary of tool name -> tool instance (static, mutually exclusive with tool_provider)
            api_key: Optional API key for LLM
            base_url: Optional base URL for LLM provider
            temperature: LLM temperature (default: 0.0)
            max_tokens: Maximum output tokens (default: 4096)
            max_steps: Maximum execution steps (default: 20)
            permission_manager: Optional permission manager
            skills: Optional list of available skills (L2 layer)
            subagents: Optional list of available subagents (L3 layer)
            skill_match_threshold: Threshold for skill prompt injection (default: 0.9)
                High threshold means LLM decides via skill_loader tool instead of auto-matching
            skill_fallback_on_error: Whether to fallback to LLM on skill error (default: True)
            skill_execution_timeout: Timeout for skill execution in seconds (default: 300)
            subagent_match_threshold: Threshold for subagent routing (default: 0.5)
            enable_subagent_as_tool: When True, SubAgents are exposed as a
                delegate_to_subagent tool in the ReAct loop, letting the LLM
                decide when to delegate. When False, uses pre-routing keyword
                matching (legacy behavior). Default: True.
            max_subagent_delegation_depth: Maximum nested delegation depth.
            max_subagent_active_runs: Maximum active subagent runs per conversation.
            max_subagent_children_per_requester: Maximum active child runs per requester key.
            max_subagent_lane_concurrency: Maximum concurrent detached SubAgent sessions.
            subagent_run_registry_path: Optional persistence path for SubAgent run registry.
            subagent_run_postgres_dsn: Optional PostgreSQL DSN for DB-backed run repository.
            subagent_run_sqlite_path: Optional SQLite path for DB-backed run repository.
            subagent_run_redis_cache_url: Optional Redis URL for run snapshot cache.
            subagent_run_redis_cache_ttl_seconds: TTL for run snapshot cache.
            subagent_terminal_retention_seconds: Terminal run retention TTL in seconds.
            subagent_announce_max_events: Max retained announce events in run metadata.
            subagent_announce_max_retries: Max retries for completion announce metadata updates.
            subagent_announce_retry_delay_ms: Base retry delay in milliseconds.
            subagent_lifecycle_hook: Optional callback for detached subagent lifecycle events.
            context_window_config: Optional context window configuration
            max_context_tokens: Maximum context tokens (default: 128000)
            agent_mode: Agent mode for skill filtering (default: "default")
            project_root: Optional project root path for custom rules loading
            artifact_service: Optional artifact service for handling rich tool outputs
            llm_client: Optional LiteLLMClient for unified resilience (circuit breaker + rate limiter)
            tool_provider: Optional callable that returns Dict[str, Any] of tools. When provided,
                tools are fetched dynamically at each stream() call, enabling hot-plug functionality.
                Mutually exclusive with 'tools' parameter.
            _cached_tool_definitions: Pre-cached tool definitions from Session Pool
            _cached_system_prompt_manager: Pre-cached SystemPromptManager singleton
            _cached_subagent_router: Pre-cached SubAgentRouter with built index
        """
        # Validate mutually exclusive tools parameters
        if tools is None and tool_provider is None and _cached_tool_definitions is None:
            raise ValueError(
                "Either 'tools', 'tool_provider', or '_cached_tool_definitions' must be provided"
            )

        # Default sandbox workspace path - Agent should only see sandbox, not host filesystem
        DEFAULT_SANDBOX_WORKSPACE = Path("/workspace")

        self.model = model
        self._tool_provider = tool_provider  # Hot-plug: callable returning tools dict
        self.raw_tools = tools or {}  # Static tools (may be empty if using tool_provider)
        self.api_key = api_key
        self.base_url = base_url
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_steps = max_steps
        self.permission_manager = permission_manager or PermissionManager()
        self.agent_mode = agent_mode  # Store agent mode for skill filtering
        # Always use sandbox workspace path, never expose host filesystem
        self.project_root = project_root or DEFAULT_SANDBOX_WORKSPACE
        self.artifact_service = artifact_service  # Artifact service for rich outputs
        self._llm_client = llm_client  # LLM client for unified resilience
        self._resource_sync_service = resource_sync_service  # Skill resource sync
        self._graph_service = graph_service  # Graph service for SubAgent memory sharing
        self._plan_detector = plan_detector or PlanDetector()

        self._init_tool_pipeline(
            tool_selection_pipeline,
            tool_selection_max_tools,
            tool_selection_semantic_backend,
            router_mode_tool_count_threshold,
            tool_policy_layers,
        )
        self._init_memory_hooks(memory_recall, memory_capture, memory_flush)
        self._init_prompt_and_context(
            _cached_system_prompt_manager, context_window_config, max_context_tokens, max_tokens
        )

        execution_config = self._init_execution_config(
            subagent_match_threshold,
            enable_subagent_as_tool,
        )

        self._init_skill_system(
            skills,
            tools,
            skill_match_threshold,
            skill_fallback_on_error,
            skill_execution_timeout,
            agent_mode,
        )
        self._init_subagent_system(
            subagents,
            execution_config,
            _cached_subagent_router,
            enable_subagent_as_tool,
            max_subagent_delegation_depth,
            max_subagent_active_runs,
            max_subagent_children_per_requester,
            max_subagent_active_runs_per_lineage,
            max_subagent_lane_concurrency,
            subagent_announce_max_events,
            subagent_announce_max_retries,
            subagent_announce_retry_delay_ms,
            subagent_lifecycle_hook,
            subagent_run_registry_path,
            subagent_run_postgres_dsn,
            subagent_run_sqlite_path,
            subagent_run_redis_cache_url,
            subagent_run_redis_cache_ttl_seconds,
            subagent_terminal_retention_seconds,
        )
        self._init_orchestrators()
        self._init_background_services(llm_client)
        self._init_tool_definitions(
            _cached_tool_definitions, model, api_key, base_url, temperature, max_tokens, max_steps
        )

        # -- Create CommandRegistry and interceptor for slash commands --
        command_registry = CommandRegistry()
        register_builtin_commands(command_registry)
        command_interceptor = CommandInterceptor(command_registry)

        # -- Create ProcessorFactory for shared processor creation --
        self._processor_factory = ProcessorFactory(
            llm_client=self._llm_client,
            permission_manager=self.permission_manager,
            artifact_service=self.artifact_service,
            command_interceptor=command_interceptor,
            base_model=self.model,
            base_api_key=self.api_key,
            base_url=self.base_url,
        )

        # -- Wire extracted SubAgent helpers --
        self._session_runner = SubAgentSessionRunner(
            SubAgentRunnerDeps(
                graph_service=self._graph_service,
                llm_client=self._llm_client,
                permission_manager=self.permission_manager,
                artifact_service=self.artifact_service,
                background_executor=self._background_executor,
                result_aggregator=self._result_aggregator,
                subagent_run_registry=self._subagent_run_registry,
                subagent_lane_semaphore=self._subagent_lane_semaphore,
                subagent_lifecycle_hook=self._subagent_lifecycle_hook,
                subagent_lifecycle_hook_failures=self._subagent_lifecycle_hook_failures,
                subagent_session_tasks=self._subagent_session_tasks,
                model=self.model,
                api_key=self.api_key,
                base_url=self.base_url,
                config=self.config,
                subagents=self.subagents,
                max_subagent_delegation_depth=self._max_subagent_delegation_depth,
                max_subagent_active_runs=self._max_subagent_active_runs,
                max_subagent_active_runs_per_lineage=(self._max_subagent_active_runs_per_lineage),
                max_subagent_children_per_requester=(self._max_subagent_children_per_requester),
                enable_subagent_as_tool=self._enable_subagent_as_tool,
                subagent_announce_max_retries=self._subagent_announce_max_retries,
                subagent_announce_max_events=self._subagent_announce_max_events,
                subagent_announce_retry_delay_ms=(self._subagent_announce_retry_delay_ms),
                factory=self._processor_factory,
            )
        )
        self._tool_builder = SubAgentToolBuilder(
            SubAgentToolBuilderDeps(
                subagent_run_registry=self._subagent_run_registry,
                subagents=self.subagents,
                enable_subagent_as_tool=self._enable_subagent_as_tool,
                max_subagent_delegation_depth=(self._max_subagent_delegation_depth),
                max_subagent_active_runs=self._max_subagent_active_runs,
                max_subagent_active_runs_per_lineage=(self._max_subagent_active_runs_per_lineage),
                max_subagent_children_per_requester=(self._max_subagent_children_per_requester),
                subagent_router=self.subagent_router,
            )
        )

        # Cross-wire callbacks (after both objects exist)
        self._session_runner.deps.get_current_tools_fn = self._get_current_tools
        self._session_runner.deps.filter_tools_fn = self._subagent_filter_tools
        self._session_runner.deps.inject_nested_tools_fn = self._subagent_inject_nested_tools

        self._tool_builder.deps.get_current_tools_fn = self._get_current_tools
        self._tool_builder.deps.get_observability_stats_fn = self._get_subagent_observability_stats
        self._tool_builder.deps.execute_subagent_fn = self._execute_subagent
        self._tool_builder.deps.launch_session_fn = self._launch_subagent_session
        self._tool_builder.deps.cancel_session_fn = self._cancel_subagent_session

    def _init_tool_pipeline(
        self,
        tool_selection_pipeline: Any,
        tool_selection_max_tools: int,
        tool_selection_semantic_backend: str,
        router_mode_tool_count_threshold: int,
        tool_policy_layers: Mapping[str, Any] | None,
    ) -> None:
        """Initialize tool selection pipeline and policy layers."""
        self._tool_selection_pipeline = (
            tool_selection_pipeline or build_default_tool_selection_pipeline()
        )
        self._tool_selection_max_tools = max(8, int(tool_selection_max_tools))
        normalized_backend = str(tool_selection_semantic_backend).strip().lower()
        if normalized_backend not in {"keyword", "token_vector", "embedding_vector"}:
            normalized_backend = "token_vector"
        self._tool_selection_semantic_backend = normalized_backend
        self._router_mode_tool_count_threshold = max(1, int(router_mode_tool_count_threshold))
        self._tool_policy_layers = normalize_policy_layers(
            {"policy_layers": dict(tool_policy_layers or {})}
        )
        self._last_tool_selection_trace: tuple[ToolSelectionTraceStep, ...] = ()

    def _init_memory_hooks(
        self,
        memory_recall: Any,
        memory_capture: Any,
        memory_flush: Any,
    ) -> None:
        """Initialize memory auto-recall / auto-capture hooks."""
        self._memory_recall = memory_recall
        self._memory_capture = memory_capture
        self._memory_flush = memory_flush

    def _init_prompt_and_context(
        self,
        cached_prompt_manager: Any | None,
        context_window_config: ContextWindowConfig | None,
        max_context_tokens: int,
        max_tokens: int,
    ) -> None:
        """Initialize System Prompt Manager and Context Window Manager."""
        if cached_prompt_manager is not None:
            self.prompt_manager = cached_prompt_manager
            logger.debug("ReActAgent: Using cached SystemPromptManager")
        else:
            self.prompt_manager = SystemPromptManager(project_root=self.project_root)

        if context_window_config:
            self.context_manager = ContextWindowManager(context_window_config)
        else:
            self.context_manager = ContextWindowManager(
                ContextWindowConfig(
                    max_context_tokens=max_context_tokens,
                    max_output_tokens=max_tokens,
                )
            )

        self.context_facade = ContextFacade(window_manager=self.context_manager)

    def _init_execution_config(
        self,
        subagent_match_threshold: float,
        enable_subagent_as_tool: bool,
    ) -> ExecutionConfig:
        """Build and validate execution configuration."""
        execution_config = ExecutionConfig(
            skill_match_threshold=0.95,  # Legacy: was skill_direct_execute_threshold
            subagent_match_threshold=subagent_match_threshold,
            allow_direct_execution=True,
            enable_plan_mode=True,
            enable_subagent_routing=not enable_subagent_as_tool,
        )
        execution_config.validate()
        return execution_config

    def _init_skill_system(
        self,
        skills: list[Skill] | None,
        tools: dict[str, Any] | None,
        skill_match_threshold: float,
        skill_fallback_on_error: bool,
        skill_execution_timeout: int,
        agent_mode: str,
    ) -> None:
        """Initialize Skill System (L2 layer)."""
        self.skills = skills or []
        self.skill_match_threshold = skill_match_threshold
        self.skill_fallback_on_error = skill_fallback_on_error
        self.skill_execution_timeout = skill_execution_timeout

    def _init_subagent_system(  # noqa: PLR0913
        self,
        subagents: list[SubAgent] | None,
        execution_config: ExecutionConfig,
        cached_subagent_router: Any | None,
        enable_subagent_as_tool: bool,
        max_subagent_delegation_depth: int,
        max_subagent_active_runs: int,
        max_subagent_children_per_requester: int,
        max_subagent_active_runs_per_lineage: int,
        max_subagent_lane_concurrency: int,
        subagent_announce_max_events: int,
        subagent_announce_max_retries: int,
        subagent_announce_retry_delay_ms: int,
        subagent_lifecycle_hook: Callable[[dict[str, Any]], Any] | None,
        subagent_run_registry_path: str | None,
        subagent_run_postgres_dsn: str | None,
        subagent_run_sqlite_path: str | None,
        subagent_run_redis_cache_url: str | None,
        subagent_run_redis_cache_ttl_seconds: int,
        subagent_terminal_retention_seconds: int,
    ) -> None:
        """Initialize SubAgent System (L3 layer)."""
        self.subagents = subagents or []
        self.subagent_match_threshold = execution_config.subagent_match_threshold
        self._enable_subagent_as_tool = enable_subagent_as_tool
        self._max_subagent_delegation_depth = max(1, max_subagent_delegation_depth)
        self._max_subagent_active_runs = max(1, max_subagent_active_runs)
        self._max_subagent_children_per_requester = max(1, max_subagent_children_per_requester)
        self._max_subagent_active_runs_per_lineage = max(1, max_subagent_active_runs_per_lineage)
        self._max_subagent_lane_concurrency = max(1, max_subagent_lane_concurrency)
        self._subagent_announce_max_events = max(1, int(subagent_announce_max_events))
        self._subagent_announce_max_retries = max(0, int(subagent_announce_max_retries))
        self._subagent_announce_retry_delay_ms = max(0, int(subagent_announce_retry_delay_ms))
        self._subagent_lane_semaphore = asyncio.Semaphore(self._max_subagent_lane_concurrency)
        self._subagent_lifecycle_hook = subagent_lifecycle_hook
        self._subagent_lifecycle_hook_failures = [0]
        self._init_subagent_router(subagents, execution_config, cached_subagent_router)
        self._init_subagent_run_registry(
            subagent_run_registry_path,
            subagent_run_postgres_dsn,
            subagent_run_sqlite_path,
            subagent_run_redis_cache_url,
            subagent_run_redis_cache_ttl_seconds,
            subagent_terminal_retention_seconds,
        )

    def _init_subagent_router(
        self,
        subagents: list[SubAgent] | None,
        execution_config: ExecutionConfig,
        cached_subagent_router: Any | None,
    ) -> None:
        """Initialize SubAgent router (cached or keyword)."""
        if cached_subagent_router is not None:
            self.subagent_router = cached_subagent_router
            logger.debug("ReActAgent: Using cached SubAgentRouter")
        elif subagents:
            self.subagent_router = SubAgentRouter(
                subagents=subagents,
                default_confidence_threshold=execution_config.subagent_match_threshold,
            )
        else:
            self.subagent_router = None

    def _init_subagent_run_registry(
        self,
        subagent_run_registry_path: str | None,
        subagent_run_postgres_dsn: str | None,
        subagent_run_sqlite_path: str | None,
        subagent_run_redis_cache_url: str | None,
        subagent_run_redis_cache_ttl_seconds: int,
        subagent_terminal_retention_seconds: int,
    ) -> None:
        """Initialize SubAgent run registry with persistence backend."""
        from ..subagent.run_registry import SubAgentRunRegistry

        resolved_registry_path = subagent_run_registry_path or os.getenv(
            "AGENT_SUBAGENT_RUN_REGISTRY_PATH"
        )
        resolved_postgres_registry_dsn = subagent_run_postgres_dsn or os.getenv(
            "AGENT_SUBAGENT_RUN_POSTGRES_DSN"
        )
        resolved_sqlite_registry_path = subagent_run_sqlite_path or os.getenv(
            "AGENT_SUBAGENT_RUN_SQLITE_PATH"
        )
        resolved_run_cache_url = subagent_run_redis_cache_url or os.getenv(
            "AGENT_SUBAGENT_RUN_REDIS_CACHE_URL"
        )
        self._subagent_run_registry = SubAgentRunRegistry(
            persistence_path=(
                resolved_registry_path
                if not resolved_postgres_registry_dsn and not resolved_sqlite_registry_path
                else None
            ),
            postgres_persistence_dsn=resolved_postgres_registry_dsn,
            sqlite_persistence_path=resolved_sqlite_registry_path,
            redis_cache_url=resolved_run_cache_url,
            redis_cache_ttl_seconds=subagent_run_redis_cache_ttl_seconds,
            terminal_retention_seconds=subagent_terminal_retention_seconds,
        )
        self._subagent_session_tasks: dict[str, asyncio.Task[Any]] = {}

    def _init_orchestrators(self) -> None:
        """Initialize orchestrators for modular components."""
        self._event_converter = EventConverter(debug_logging=False)

    def _init_background_services(self, llm_client: Any | None) -> None:
        """Initialize background SubAgent services."""
        from ..subagent.background_executor import BackgroundExecutor
        from ..subagent.result_aggregator import ResultAggregator
        from ..subagent.task_decomposer import TaskDecomposer
        from ..subagent.template_registry import TemplateRegistry

        self._background_executor = BackgroundExecutor()
        self._template_registry = TemplateRegistry()

        agent_names = [sa.name for sa in self.subagents] if self.subagents else []
        self._task_decomposer = (
            TaskDecomposer(
                llm_client=llm_client,
                available_agent_names=agent_names,
            )
            if llm_client and self.subagents
            else None
        )
        self._result_aggregator = ResultAggregator(llm_client=llm_client)

    def _init_tool_definitions(
        self,
        cached_tool_definitions: list[Any] | None,
        model: str,
        api_key: str | None,
        base_url: str | None,
        temperature: float,
        max_tokens: int,
        max_steps: int,
    ) -> None:
        """Initialize tool definitions and processor config."""
        if cached_tool_definitions is not None:
            self.tool_definitions = cached_tool_definitions
            self._use_dynamic_tools = False
            logger.debug(
                f"ReActAgent: Using {len(cached_tool_definitions)} cached tool definitions"
            )
        elif self._tool_provider is not None:
            self.tool_definitions = []
            self._use_dynamic_tools = True
            logger.debug("ReActAgent: Using dynamic tool_provider (hot-plug enabled)")
        else:
            self.tool_definitions = convert_tools(self.raw_tools)
            self._use_dynamic_tools = False

        self.config = ProcessorConfig(
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            max_steps=max_steps,
            llm_client=self._llm_client,
        )

    def _build_tool_selection_context(
        self,
        *,
        tenant_id: str,
        project_id: str,
        user_message: str,
        conversation_context: list[dict[str, str]],
        effective_mode: str,
        routing_metadata: Mapping[str, Any] | None = None,
    ) -> ToolSelectionContext:
        """Build selection context for context/intent/semantic/policy pipeline."""
        policy_context = PolicyContext.from_metadata(
            {"policy_layers": dict(self._tool_policy_layers)},
        )
        deny_tools: list[str] = []
        if effective_mode == "plan":
            deny_tools = ["plugin_manager", "skill_installer", "skill_sync"]
        metadata: dict[str, Any] = {
            "user_message": user_message,
            "conversation_history": conversation_context,
            "effective_mode": effective_mode,
            "agent_mode": self.agent_mode,
            "max_tools": self._tool_selection_max_tools,
            "semantic_backend": self._tool_selection_semantic_backend,
            "deny_tools": deny_tools,
            "policy_agent": {"deny_tools": deny_tools} if deny_tools else {},
        }
        if routing_metadata:
            domain_lane = routing_metadata.get("domain_lane")
            if isinstance(domain_lane, str) and domain_lane:
                metadata["domain_lane"] = domain_lane
            route_id = routing_metadata.get("route_id")
            if isinstance(route_id, str) and route_id:
                metadata["route_id"] = route_id
            trace_id = routing_metadata.get("trace_id")
            if isinstance(trace_id, str) and trace_id:
                metadata["trace_id"] = trace_id
            metadata["routing_metadata"] = dict(routing_metadata)
        if self._tool_policy_layers:
            metadata["policy_layers"] = policy_context.to_mapping()
        return ToolSelectionContext(
            tenant_id=tenant_id,
            project_id=project_id,
            metadata=metadata,
            policy_context=policy_context,
        )

    def _infer_domain_lane(
        self,
        *,
        message: str,
        forced_subagent_name: str | None = None,
        forced_skill_name: str | None = None,
        plan_mode_requested: bool = False,
    ) -> str:
        """Infer routing lane for router-fabric diagnostics."""
        if forced_subagent_name:
            return "subagent"
        if forced_skill_name:
            return "skill"
        if plan_mode_requested:
            return "planning"

        normalized = message.lower()
        for lane, keywords in self._DOMAIN_LANE_RULES:
            if any(keyword in normalized for keyword in keywords):
                return lane
        return "general"

    def _decide_execution_path(
        self,
        *,
        message: str,
        conversation_context: list[dict[str, str]],
        forced_subagent_name: str | None = None,
        forced_skill_name: str | None = None,
        plan_mode_requested: bool = False,
    ) -> RoutingDecision:
        """Decide execution path via centralized ExecutionRouter."""
        domain_lane = self._infer_domain_lane(
            message=message,
            forced_subagent_name=forced_subagent_name,
            forced_skill_name=forced_skill_name,
            plan_mode_requested=plan_mode_requested,
        )
        if forced_subagent_name:
            return RoutingDecision(
                path=ExecutionPath.REACT_LOOP,
                confidence=1.0,
                reason="Forced delegation via system instruction (subagent-as-tool)",
                target=forced_subagent_name,
                metadata={
                    "forced_subagent": forced_subagent_name,
                    "domain_lane": domain_lane,
                    "router_fabric_version": "lane-v1",
                },
            )
        if forced_skill_name:
            return RoutingDecision(
                path=ExecutionPath.DIRECT_SKILL,
                confidence=1.0,
                reason="Forced skill execution requested",
                target=forced_skill_name,
                metadata={
                    "domain_lane": domain_lane,
                    "router_fabric_version": "lane-v1",
                },
            )
        if plan_mode_requested:
            return RoutingDecision(
                path=ExecutionPath.PLAN_MODE,
                confidence=1.0,
                reason="Plan mode explicitly requested",
                metadata={
                    "domain_lane": domain_lane,
                    "router_fabric_version": "lane-v1",
                },
            )

        # Default to ReAct loop -- prompt-driven routing replaces confidence scoring
        return RoutingDecision(
            path=ExecutionPath.REACT_LOOP,
            confidence=0.5,
            reason="Standard ReAct reasoning loop",
            metadata={
                "domain_lane": domain_lane,
                "router_fabric_version": "lane-v1",
            },
        )

    def _estimate_available_tool_count(self) -> int:
        """Estimate available tool count without mutating selection trace state."""
        if self._use_dynamic_tools and self._tool_provider is not None:
            try:
                dynamic_tools = self._tool_provider()
                if isinstance(dynamic_tools, dict):
                    return len(dynamic_tools)
            except Exception:
                logger.warning(
                    "Failed to fetch dynamic tools for router threshold check", exc_info=True
                )
        return len(self.raw_tools)

    def _get_current_tools(
        self,
        selection_context: ToolSelectionContext | None = None,
    ) -> tuple[dict[str, Any], list[ToolDefinition]]:
        """
        Get current tools - either from static tools or dynamic tool_provider.

        Returns:
            Tuple of (raw_tools dict, tool_definitions list)
        """
        if self._use_dynamic_tools and self._tool_provider is not None:
            raw_tools = self._tool_provider()
        else:
            raw_tools = self.raw_tools

        # Apply tool selection pipeline when context is provided.
        # Context-free calls (e.g. cache maintenance) keep full toolset.
        if selection_context and self._tool_selection_pipeline is not None:
            selection_result = self._tool_selection_pipeline.select_with_trace(
                raw_tools,
                selection_context,
            )
            selected_raw_tools = selection_result.tools
            self._last_tool_selection_trace = selection_result.trace
            tool_definitions = convert_tools(selected_raw_tools)
            logger.debug(
                "ReActAgent: Selected %d/%d tools via pipeline",
                len(selected_raw_tools),
                len(raw_tools),
            )
            return selected_raw_tools, tool_definitions

        self._last_tool_selection_trace = ()
        if self._use_dynamic_tools and self._tool_provider is not None:
            tool_definitions = convert_tools(raw_tools)
            logger.debug("ReActAgent: Dynamically loaded %d tools", len(tool_definitions))
            return raw_tools, tool_definitions

        return self.raw_tools, self.tool_definitions

    def _match_skill(self, query: str) -> tuple[SkillProtocol | None, float]:
        """Match query against available skills, filtered by agent_mode.

        Inlined from SkillOrchestrator.match() (Wave 5.1).

        Args:
            query: User query

        Returns:
            Tuple of (best matching skill or None, match score)
        """
        skills = cast("list[SkillProtocol]", self.skills or [])
        if not skills:
            logger.debug("[ReActAgent] No skills available for matching")
            return None, 0.0

        best_skill: SkillProtocol | None = None
        best_score = 0.0

        for skill in skills:
            if not skill.is_accessible_by_agent(self.agent_mode):
                continue
            if skill.status.value != "active":
                continue
            score = skill.matches_query(query)
            if score > best_score:
                best_score = score
                best_skill = skill

        if best_skill and best_score >= self.skill_match_threshold:
            logger.info(
                f"[ReActAgent] Matched skill: {best_skill.name} with score {best_score:.2f}"
            )
            return best_skill, best_score

        logger.debug("[ReActAgent] No skill matched for query")
        return None, 0.0

    def _match_subagent(self, query: str) -> SubAgentMatch:
        """
        Match query against available subagents using keyword router.

        Args:
            query: User query

        Returns:
            SubAgentMatch result
        """
        if not self.subagent_router:
            return SubAgentMatch(subagent=None, confidence=0.0, match_reason="no_router")

        result = self.subagent_router.match(query)
        if result.subagent:
            logger.info(
                f"[ReActAgent] Matched subagent: {result.subagent.name} "
                f"with confidence {result.confidence:.2f} ({result.match_reason})"
            )
        return result

    async def _match_subagent_async(
        self,
        query: str,
        conversation_context: list[dict[str, str]] | None = None,
    ) -> SubAgentMatch:
        """Async match -- delegates to sync keyword router.

        Args:
            query: User query.
            conversation_context: Unused (kept for API compatibility).

        Returns:
            SubAgentMatch result.
        """
        return self._match_subagent(query)

    async def _background_index_conversation(
        self,
        messages: list[dict[str, Any]],
        project_id: str,
        conversation_id: str,
    ) -> None:
        """Index conversation messages as searchable chunks (fire-and-forget)."""
        try:
            if not self._memory_capture or not hasattr(self._memory_capture, "_session_factory"):
                return
            session_factory = self._memory_capture._session_factory
            if session_factory is None:
                return

            from src.infrastructure.adapters.secondary.persistence.sql_chunk_repository import (
                SqlChunkRepository,
            )

            session = session_factory()
            try:
                chunk_repo = SqlChunkRepository(session)
                embedding_svc = self._memory_capture._embedding

                from src.application.services.memory_index_service import MemoryIndexService

                index_svc = MemoryIndexService(chunk_repo, embedding_svc)
                indexed = await index_svc.index_conversation(conversation_id, messages, project_id)
                if indexed > 0:
                    await session.commit()
                    logger.info(
                        f"[ReActAgent] Indexed {indexed} conversation chunks "
                        f"(conversation={conversation_id})"
                    )
            finally:
                await session.close()
        except Exception as e:
            logger.debug(f"[ReActAgent] Background conversation indexing failed: {e}")

    async def _build_system_prompt(
        self,
        user_query: str,
        conversation_context: list[dict[str, str]],
        matched_skill: Skill | None = None,
        subagent: SubAgent | None = None,
        mode: str = "build",
        current_step: int = 1,
        project_id: str = "",
        tenant_id: str = "",
        force_execution: bool = False,
        memory_context: str | None = None,
        selection_context: ToolSelectionContext | None = None,
    ) -> str:
        """
        Build system prompt for the agent using SystemPromptManager.

        Args:
            user_query: User's query
            conversation_context: Conversation history
            matched_skill: Optional matched skill to highlight
            subagent: Optional SubAgent (uses its system prompt if provided)
            mode: Agent mode ("build" or "plan")
            current_step: Current execution step number
            project_id: Project ID for context
            tenant_id: Tenant ID for context
            force_execution: If True, skill injection uses mandatory wording

        Returns:
            System prompt string
        """
        # Detect model provider from model name
        model_provider = SystemPromptManager.detect_model_provider(self.model)

        # Convert skills to dict format for PromptContext
        skills_data = None
        if self.skills:
            skills_data = [
                {
                    "name": s.name,
                    "description": s.description,
                    "tools": s.tools,
                    "status": s.status.value,
                    "prompt_template": s.prompt_template,
                }
                for s in self.skills
            ]

        # Convert matched skill to dict format
        matched_skill_data = None
        if matched_skill:
            matched_skill_data = {
                "name": matched_skill.name,
                "description": matched_skill.description,
                "tools": matched_skill.tools,
                "prompt_template": matched_skill.prompt_template,
                "force_execution": force_execution,
            }

        # Convert tool definitions to dict format - use current tools (hot-plug support)
        _, current_tool_definitions = self._get_current_tools(selection_context=selection_context)
        # When a forced skill is active, exclude skill_loader from tool list
        # to prevent the LLM from calling it and loading a different skill.
        if force_execution and matched_skill:
            tool_defs = [
                {"name": t.name, "description": t.description}
                for t in current_tool_definitions
                if t.name != "skill_loader"
            ]
        else:
            tool_defs = [
                {"name": t.name, "description": t.description} for t in current_tool_definitions
            ]

        # Convert SubAgents to dict format for PromptContext (SubAgent-as-Tool mode)
        subagents_data = None
        if self.subagents and self._enable_subagent_as_tool:
            subagents_data = [
                {
                    "name": sa.name,
                    "display_name": sa.display_name,
                    "description": sa.system_prompt[:200] if sa.system_prompt else "",
                    "trigger_description": (
                        sa.trigger.description if sa.trigger else "general tasks"
                    ),
                }
                for sa in self.subagents
                if sa.enabled
            ]

        # Build prompt context
        context = PromptContext(
            model_provider=model_provider,
            mode=PromptMode(mode),
            tool_definitions=tool_defs,
            skills=skills_data,
            subagents=subagents_data,
            matched_skill=matched_skill_data,
            project_id=project_id,
            tenant_id=tenant_id,
            working_directory=str(self.project_root),
            conversation_history_length=len(conversation_context),
            user_query=user_query,
            current_step=current_step,
            max_steps=self.max_steps,
            memory_context=memory_context,
        )

        # Use SystemPromptManager to build the prompt
        return cast(
            str,
            await self.prompt_manager.build_system_prompt(
                context=context,
                subagent=subagent,
            ),
        )

    async def _stream_detect_plan_mode(
        self,
        user_message: str,
        conversation_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Detect plan mode and yield suggestion event if appropriate."""
        suggestion = self._plan_detector.detect(user_message)
        if suggestion.should_suggest:
            yield {
                "type": "plan_suggested",
                "data": {
                    "plan_id": "",  # Will be set by PlanCoordinator
                    "conversation_id": conversation_id,
                    "reason": suggestion.reason,
                    "confidence": suggestion.confidence,
                },
                "timestamp": datetime.now(UTC).isoformat(),
            }
            logger.info(
                f"[ReActAgent] Plan Mode suggested (confidence={suggestion.confidence:.2f})"
            )

    def _stream_parse_forced_subagent(
        self,
        user_message: str,
    ) -> tuple[str | None, str]:
        """Parse forced SubAgent delegation from system instruction prefix.

        Returns:
            Tuple of (forced_subagent_name or None, processed_user_message).
        """
        forced_prefix = '[System Instruction: Delegate this task strictly to SubAgent "'
        if not user_message.startswith(forced_prefix):
            return None, user_message

        try:
            match = re.match(
                r'^\[System Instruction: Delegate this task strictly to SubAgent "([^"]+)"\]',
                user_message,
            )
            if match:
                forced_name = match.group(1)
                processed = user_message.replace(match.group(0), "", 1).strip()
                return forced_name, processed if processed else user_message
        except Exception as e:
            logger.warning(f"[ReActAgent] Failed to parse forced subagent instruction: {e}")

        return None, user_message

    def _resolve_subagent_by_name(self, name: str) -> Any | None:
        """Find a SubAgent by name or display_name."""
        for sa in self.subagents or []:
            if sa.enabled and (sa.name == name or sa.display_name == name):
                return sa
        return None

    def _stream_match_skill(
        self,
        processed_user_message: str,
        forced_skill_name: str | None,
    ) -> Iterator[dict[str, Any]]:
        """Match skill and yield skill_matched event.

        Sets self._stream_skill_state with matched_skill info.
        """
        is_forced = False
        matched_skill = None
        skill_score = 0.0
        should_inject_prompt = False

        if forced_skill_name:
            # Inline find_by_name: case-insensitive name lookup (Wave 5.1)
            name_lower = forced_skill_name.strip().lower()
            found_skill: SkillProtocol | None = None
            for skill in cast("list[SkillProtocol]", self.skills or []):
                if skill.name.lower() == name_lower and skill.status.value == "active":
                    found_skill = skill
                    break
            if found_skill is not None:
                matched_skill = found_skill
                skill_score = 1.0
                is_forced = True
                logger.info(f"[ReActAgent] Forced skill found: {found_skill.name}")
            else:
                yield {
                    "type": "thought",
                    "data": {
                        "content": f"Forced skill '{forced_skill_name}' not found, "
                        f"falling back to normal matching",
                    },
                    "timestamp": datetime.now(UTC).isoformat(),
                }
                matched_skill, skill_score = self._match_skill(processed_user_message)
        else:
            matched_skill, skill_score = self._match_skill(processed_user_message)

        should_inject_prompt = matched_skill is not None and (
            is_forced or skill_score >= self.skill_match_threshold
        )

        if not is_forced and matched_skill and skill_score < self.skill_match_threshold:
            matched_skill = None
            skill_score = 0.0

        if matched_skill:
            execution_mode = "forced" if is_forced else "prompt"
            logger.info(
                f"[ReActAgent] Skill matched: name={matched_skill.name}, "
                f"mode={execution_mode}, score={skill_score}, "
                f"prompt_len={len(matched_skill.prompt_template or '')}, "
                f"tools={list(matched_skill.tools)}"
            )
            yield {
                "type": "skill_matched",
                "data": {
                    "skill_id": matched_skill.id,
                    "skill_name": matched_skill.name,
                    "tools": list(matched_skill.tools),
                    "match_score": skill_score,
                    "execution_mode": execution_mode,
                },
                "timestamp": datetime.now(UTC).isoformat(),
            }

        self._stream_skill_state = {
            "matched_skill": matched_skill,
            "skill_score": skill_score,
            "is_forced": is_forced,
            "should_inject_prompt": should_inject_prompt,
        }

    async def _stream_sync_skill_resources(
        self,
        matched_skill: Skill,
    ) -> None:
        """Sync skill resources to sandbox before prompt injection."""
        if not self._resource_sync_service:
            return
        sandbox_id = self._extract_sandbox_id_from_tools()
        if not sandbox_id:
            return
        try:
            await self._resource_sync_service.sync_for_skill(
                skill_name=matched_skill.name,
                sandbox_id=sandbox_id,
                skill_content=matched_skill.prompt_template,
            )
        except Exception as e:
            logger.warning(
                f"Skill resource sync failed for INJECT mode (skill={matched_skill.name}): {e}"
            )

    async def _stream_recall_memory(
        self,
        processed_user_message: str,
        project_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Recall memory context and yield memory recalled event.

        Sets self._stream_memory_context with the result.
        """
        self._stream_memory_context = None
        if not self._memory_recall:
            return
        try:
            memory_context = await self._memory_recall.recall(processed_user_message, project_id)
            self._stream_memory_context = memory_context
            if memory_context and self._memory_recall.last_results:
                from src.domain.events.agent_events import AgentMemoryRecalledEvent

                yield cast(
                    dict[str, Any],
                    AgentMemoryRecalledEvent(
                        memories=self._memory_recall.last_results,
                        count=len(self._memory_recall.last_results),
                        search_ms=self._memory_recall.last_search_ms,
                    ).to_event_dict(),
                )
        except Exception as e:
            logger.warning(f"[ReActAgent] Memory recall failed: {e}")

    async def _stream_build_context(
        self,
        *,
        system_prompt: str,
        conversation_context: list[dict[str, str]],
        processed_user_message: str,
        attachment_metadata: list[dict[str, Any]] | None,
        attachment_content: list[dict[str, Any]] | None,
        context_summary_data: dict[str, Any] | None,
        project_id: str,
        conversation_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Build context via ContextFacade, yield compression/flush events.

        Sets self._stream_context_result and self._stream_messages.
        """
        cached_summary = None
        if context_summary_data:
            from src.domain.model.agent.conversation.context_summary import ContextSummary

            try:
                cached_summary = ContextSummary.from_dict(context_summary_data)
            except (KeyError, TypeError, ValueError) as e:
                logger.warning(f"[ReActAgent] Invalid context summary data: {e}")

        context_request = ContextBuildRequest(
            system_prompt=system_prompt,
            conversation_context=conversation_context,
            user_message=processed_user_message,
            attachment_metadata=attachment_metadata,
            attachment_content=attachment_content,
            is_hitl_resume=False,
            context_summary=cached_summary,
            llm_client=self._llm_client,
        )
        context_result = await self.context_facade.build_context(context_request)
        self._stream_context_result = context_result
        self._stream_messages = context_result.messages
        self._stream_cached_summary = cached_summary

        if attachment_metadata:
            logger.info(
                f"[ReActAgent] Context built with {len(attachment_metadata)} attachments: "
                f"{[m.get('filename') for m in attachment_metadata]}"
            )
        if attachment_content:
            logger.info(f"[ReActAgent] Added {len(attachment_content)} multimodal attachments")

        # Emit context_compressed event if compression occurred
        if context_result.was_compressed:
            yield {
                "type": "context_compressed",
                "data": context_result.to_event_data(),
                "timestamp": datetime.now(UTC).isoformat(),
            }
            logger.info(
                f"Context compressed: {context_result.original_message_count} -> "
                f"{context_result.final_message_count} messages, "
                f"strategy: {context_result.compression_strategy.value}"
            )

            if context_result.summary and not cached_summary:
                yield {
                    "type": "context_summary_generated",
                    "data": {
                        "summary_text": context_result.summary,
                        "summary_tokens": context_result.estimated_tokens,
                        "messages_covered_count": context_result.summarized_message_count,
                        "compression_level": context_result.compression_strategy.value,
                    },
                    "timestamp": datetime.now(UTC).isoformat(),
                }

            # Pre-compaction memory flush
            if self._memory_flush and conversation_context:
                try:
                    flushed = await self._memory_flush.flush(
                        conversation_context, project_id, conversation_id
                    )
                    if flushed > 0:
                        from src.domain.events.agent_events import AgentMemoryCapturedEvent

                        yield cast(
                            dict[str, Any],
                            AgentMemoryCapturedEvent(
                                captured_count=flushed,
                                categories=["flush"],
                            ).to_event_dict(),
                        )
                except Exception as e:
                    logger.warning(f"[ReActAgent] Pre-compaction flush failed: {e}")

        # Emit initial context_status
        compression_level = context_result.metadata.get("compression_level", "none")
        yield {
            "type": "context_status",
            "data": {
                "current_tokens": context_result.estimated_tokens,
                "token_budget": context_result.token_budget,
                "occupancy_pct": round(context_result.budget_utilization_pct, 1),
                "compression_level": compression_level,
                "token_distribution": {},
                "compression_history_summary": context_result.metadata.get(
                    "compression_history", {}
                ),
                "from_cache": cached_summary is not None,
                "messages_in_summary": (
                    cached_summary.messages_covered_count if cached_summary else 0
                ),
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def _stream_prepare_tools(
        self,
        selection_context: ToolSelectionContext,
        is_forced: bool,
        matched_skill: Skill | None,
    ) -> Iterator[dict[str, Any]]:
        """Prepare tools with selection trace and policy filtering events.

        Sets self._stream_tools_to_use.
        """
        _current_raw_tools, current_tool_definitions = self._get_current_tools(
            selection_context=selection_context
        )
        if self._last_tool_selection_trace:
            removed_total = sum(len(step.removed_tools) for step in self._last_tool_selection_trace)
            route_id = selection_context.metadata.get("route_id")
            trace_id = selection_context.metadata.get("trace_id", route_id)
            trace_data = [
                {
                    "stage": step.stage,
                    "before_count": step.before_count,
                    "after_count": step.after_count,
                    "removed_count": len(step.removed_tools),
                    "duration_ms": step.duration_ms,
                    "explain": dict(step.explain),
                }
                for step in self._last_tool_selection_trace
            ]
            semantic_stage = next(
                (stage for stage in trace_data if stage["stage"] == "semantic_ranker_stage"),
                None,
            )
            tool_budget_value = (
                semantic_stage.get("explain", {}).get("max_tools") if semantic_stage else None  # type: ignore[attr-defined]
            )
            tool_budget = (
                int(tool_budget_value)
                if isinstance(tool_budget_value, (int, float))
                else self._tool_selection_max_tools
            )
            budget_exceeded_stages = [
                stage["stage"]
                for stage in trace_data
                if isinstance(stage.get("explain"), dict)
                and stage["explain"].get("budget_exceeded")  # type: ignore[attr-defined]
            ]
            yield {
                "type": "selection_trace",
                "data": {
                    "route_id": route_id,
                    "trace_id": trace_id,
                    "initial_count": trace_data[0]["before_count"],
                    "final_count": trace_data[-1]["after_count"],
                    "removed_total": removed_total,
                    "domain_lane": selection_context.metadata.get("domain_lane"),
                    "tool_budget": tool_budget,
                    "budget_exceeded_stages": budget_exceeded_stages,
                    "stages": trace_data,
                },
                "timestamp": datetime.now(UTC).isoformat(),
            }
            if removed_total > 0:
                yield {
                    "type": "policy_filtered",
                    "data": {
                        "route_id": route_id,
                        "trace_id": trace_id,
                        "removed_total": removed_total,
                        "stage_count": len(trace_data),
                        "domain_lane": selection_context.metadata.get("domain_lane"),
                        "tool_budget": tool_budget,
                        "budget_exceeded_stages": budget_exceeded_stages,
                    },
                    "timestamp": datetime.now(UTC).isoformat(),
                }
        tools_to_use = list(current_tool_definitions)

        # When a forced skill is active, keep all core tools available
        # but remove skill_loader to prevent loading other skills.
        # The skill's prompt template is already injected into the system prompt,
        # so the agent can use any core tool to fulfill the skill's instructions.
        if is_forced and matched_skill:
            tools_to_use = [t for t in tools_to_use if t.name != "skill_loader"]
            skill_tools = set(matched_skill.tools) if matched_skill.tools else set()
            logger.info(
                f"[ReActAgent] Forced skill '{matched_skill.name}' active: "
                f"removed skill_loader, keeping {len(tools_to_use)} tools. "
                f"Skill declared tools={list(skill_tools)}"
            )

        self._stream_tools_to_use = tools_to_use

    def _stream_inject_subagent_tools(
        self,
        tools_to_use: list[ToolDefinition],
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        conversation_id: str,
        abort_signal: asyncio.Event | None,
    ) -> list[ToolDefinition]:
        """Inject SubAgent-as-Tool delegation tools when enabled.

        Returns updated tools list with SubAgent tools appended.
        """
        if not self.subagents or not self._enable_subagent_as_tool:
            return tools_to_use

        enabled_subagents = [sa for sa in self.subagents if sa.enabled]
        if not enabled_subagents:
            return tools_to_use

        subagent_map = {sa.name: sa for sa in enabled_subagents}
        subagent_descriptions = {
            sa.name: (sa.trigger.description if sa.trigger else sa.display_name)
            for sa in enabled_subagents
        }

        # Create delegation callback that captures stream-scoped context
        async def _delegate_callback(
            subagent_name: str,
            task: str,
            on_event: Callable[[dict[str, Any]], None] | None = None,
        ) -> str:
            target = subagent_map.get(subagent_name)
            if not target:
                return f"SubAgent '{subagent_name}' not found"

            events = []
            async for evt in self._execute_subagent(
                subagent=target,
                user_message=task,
                conversation_context=conversation_context,
                project_id=project_id,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                abort_signal=abort_signal,
            ):
                if on_event:
                    event_type = evt.get("type")
                    if event_type not in {"complete", "error"}:
                        on_event(evt)
                events.append(evt)

            complete_evt = next(
                (e for e in events if e.get("type") == "complete"),
                None,
            )
            if complete_evt:
                data = complete_evt.get("data", {})
                content = data.get("content", "")
                sa_result = data.get("subagent_result")
                if sa_result:
                    summary = sa_result.get("summary", content)
                    tokens = sa_result.get("tokens_used", 0)
                    return (
                        f"[SubAgent '{subagent_name}' completed]\n"
                        f"Result: {summary}\n"
                        f"Tokens used: {tokens}"
                    )
                return content or "SubAgent completed with no output"

            return "SubAgent execution completed but no result returned"

        async def _spawn_callback(
            subagent_name: str,
            task: str,
            run_id: str,
            **spawn_options: Any,
        ) -> str:
            target = subagent_map.get(subagent_name)
            if not target:
                raise ValueError(f"SubAgent '{subagent_name}' not found")
            await self._launch_subagent_session(
                run_id=run_id,
                subagent=target,
                user_message=task,
                conversation_id=conversation_id,
                conversation_context=conversation_context,
                project_id=project_id,
                tenant_id=tenant_id,
                abort_signal=abort_signal,
                model_override=(str(spawn_options.get("model") or "").strip() or None),
                thinking_override=(str(spawn_options.get("thinking") or "").strip() or None),
                spawn_mode=str(spawn_options.get("spawn_mode") or "run"),
                thread_requested=bool(spawn_options.get("thread_requested")),
                cleanup=str(spawn_options.get("cleanup") or "keep"),
            )
            return run_id

        async def _cancel_spawn_callback(run_id: str) -> bool:
            return await self._cancel_subagent_session(run_id)

        tools_to_use = self._build_subagent_tool_definitions(
            subagent_map=subagent_map,
            subagent_descriptions=subagent_descriptions,
            enabled_subagents=enabled_subagents,
            delegate_callback=_delegate_callback,
            spawn_callback=_spawn_callback,
            cancel_callback=_cancel_spawn_callback,
            conversation_id=conversation_id,
            tools_to_use=tools_to_use,
        )

        logger.info(
            f"[ReActAgent] Injected SubAgent delegation tools "
            f"({len(enabled_subagents)} SubAgents, "
            f"parallel={'yes' if len(enabled_subagents) >= 2 else 'no'}, "
            "sessions=yes)"
        )

        return tools_to_use

    def _build_subagent_tool_definitions(
        self,
        *,
        subagent_map: dict[str, Any],
        subagent_descriptions: dict[str, str],
        enabled_subagents: list[Any],
        delegate_callback: Any,
        spawn_callback: Any,
        cancel_callback: Any,
        conversation_id: str,
        tools_to_use: list[ToolDefinition],
    ) -> list[ToolDefinition]:
        """Build and append all SubAgent tool definitions to tools list."""
        return self._tool_builder.build_subagent_tool_definitions(
            subagent_map=subagent_map,
            subagent_descriptions=subagent_descriptions,
            enabled_subagents=enabled_subagents,
            delegate_callback=delegate_callback,
            spawn_callback=spawn_callback,
            cancel_callback=cancel_callback,
            conversation_id=conversation_id,
            tools_to_use=tools_to_use,
        )

    def _stream_create_processor_config(
        self,
        config: ProcessorConfig,
        selection_context: ToolSelectionContext,
    ) -> ProcessorConfig:
        """Create processor config, optionally with dynamic tool provider."""
        if not (self._use_dynamic_tools and self._tool_provider is not None):
            return config

        def _tool_provider_wrapper() -> list[ToolDefinition]:
            _, tool_defs = self._get_current_tools(selection_context=selection_context)
            return list(tool_defs)

        new_config = ProcessorConfig(
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            max_steps=config.max_steps,
            max_tool_calls_per_step=config.max_tool_calls_per_step,
            doom_loop_threshold=config.doom_loop_threshold,
            max_attempts=config.max_attempts,
            initial_delay_ms=config.initial_delay_ms,
            permission_timeout=config.permission_timeout,
            continue_on_deny=config.continue_on_deny,
            context_limit=config.context_limit,
            llm_client=config.llm_client,
            tool_provider=_tool_provider_wrapper,
            forced_skill_name=config.forced_skill_name,
            forced_skill_tools=config.forced_skill_tools,
        )
        logger.debug("[ReActAgent] Created processor config with tool_provider for dynamic tools")
        return new_config

    async def _stream_process_events(
        self,
        processor: SessionProcessor,
        messages: list[dict[str, Any]],
        langfuse_context: dict[str, Any],
        abort_signal: asyncio.Event | None,
        matched_skill: Skill | None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Process events from SessionProcessor and yield converted events.

        Sets self._stream_final_content and self._stream_success.
        """
        self._stream_final_content = ""
        self._stream_success = True

        try:
            run_ctx = RunContext(
                abort_signal=abort_signal,
                langfuse_context=langfuse_context,
                conversation_id=langfuse_context.get("conversation_id")
                if langfuse_context
                else None,
            )
            async for domain_event in processor.process(
                session_id=langfuse_context["conversation_id"],
                messages=messages,
                run_ctx=run_ctx,
            ):
                event = self._convert_domain_event(domain_event)
                if event:
                    if event.get("type") == "text_delta":
                        self._stream_final_content += event.get("data", {}).get("delta", "")
                    elif event.get("type") == "text_end":
                        text_end_content = event.get("data", {}).get("full_text", "")
                        if text_end_content:
                            self._stream_final_content = text_end_content

                    yield event

        except Exception as e:
            logger.error(f"[ReActAgent] Error in stream: {e}", exc_info=True)
            self._stream_success = False
            yield {
                "type": "error",
                "data": {
                    "message": str(e),
                    "code": type(e).__name__,
                },
                "timestamp": datetime.now(UTC).isoformat(),
            }

    async def _stream_post_process(
        self,
        *,
        processed_user_message: str,
        final_content: str,
        project_id: str,
        conversation_id: str,
        conversation_context: list[dict[str, str]],
        matched_skill: Skill | None,
        success: bool,
    ) -> AsyncIterator[dict[str, Any]]:
        """Post-process: memory capture, conversation indexing, final complete event."""
        # Auto-capture important user messages for memory indexing
        if self._memory_capture and success:
            try:
                captured = await self._memory_capture.capture(
                    user_message=processed_user_message,
                    assistant_response=final_content or "",
                    project_id=project_id,
                    conversation_id=conversation_id or "unknown",
                )
                if captured > 0:
                    from src.domain.events.agent_events import AgentMemoryCapturedEvent

                    yield cast(
                        dict[str, Any],
                        AgentMemoryCapturedEvent(
                            captured_count=captured,
                            categories=self._memory_capture.last_categories,
                        ).to_event_dict(),
                    )
            except Exception as e:
                logger.warning(f"[ReActAgent] Memory capture failed: {e}")

        # Async conversation indexing (fire-and-forget)
        if conversation_id and conversation_context and success:
            try:
                import asyncio

                _idx_task = asyncio.create_task(
                    self._background_index_conversation(
                        conversation_context, project_id, conversation_id
                    )
                )
                _react_bg_tasks.add(_idx_task)
                _idx_task.add_done_callback(_react_bg_tasks.discard)
            except Exception as e:
                logger.debug(f"[ReActAgent] Conversation indexing skipped: {e}")

        # Yield final complete event
        yield {
            "type": "complete",
            "data": {
                "content": final_content,
                "skill_used": matched_skill.name if matched_skill else None,
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def _stream_decide_route(
        self,
        *,
        processed_user_message: str,
        conversation_context: list[dict[str, str]],
        forced_subagent_name: str | None,
        forced_skill_name: str | None,
        plan_mode: bool,
    ) -> tuple[RoutingDecision, str, str, dict[str, Any], str | None, dict[str, Any]]:
        """Compute routing decision and build the execution_path_decided event.

        Returns:
            (routing_decision, route_id, trace_id, routing_metadata,
             forced_skill_name, event_dict)
        """
        routing_decision = self._decide_execution_path(
            message=processed_user_message,
            conversation_context=conversation_context,
            forced_subagent_name=forced_subagent_name,
            forced_skill_name=forced_skill_name,
            plan_mode_requested=plan_mode,
        )
        route_id = uuid4().hex
        trace_id = route_id
        routing_metadata = dict(routing_decision.metadata or {})
        routing_metadata["route_id"] = route_id
        routing_metadata["trace_id"] = trace_id
        event_dict = {
            "type": "execution_path_decided",
            "data": {
                "route_id": route_id,
                "trace_id": trace_id,
                "path": routing_decision.path.value,
                "confidence": routing_decision.confidence,
                "reason": routing_decision.reason,
                "target": routing_decision.target,
                "metadata": routing_metadata,
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }
        if (
            not forced_skill_name
            and routing_decision.path == ExecutionPath.DIRECT_SKILL
            and routing_decision.target
        ):
            forced_skill_name = routing_decision.target
        return routing_decision, route_id, trace_id, routing_metadata, forced_skill_name, event_dict

    def _stream_resolve_mode(
        self,
        *,
        plan_mode: bool,
        routing_decision: RoutingDecision,
        routing_metadata: dict[str, Any],
        tenant_id: str,
        project_id: str,
        processed_user_message: str,
        conversation_context: list[dict[str, str]],
    ) -> tuple[str, ToolSelectionContext]:
        """Resolve effective mode and build selection context.

        Returns:
            (effective_mode, selection_context)
        """
        from src.infrastructure.agent.permission.manager import AgentPermissionMode

        plan_mode = plan_mode or routing_decision.path == ExecutionPath.PLAN_MODE
        effective_mode = (
            "plan"
            if plan_mode
            else (self.agent_mode if self.agent_mode in ["build", "plan"] else "build")
        )
        selection_context = self._build_tool_selection_context(
            tenant_id=tenant_id,
            project_id=project_id,
            user_message=processed_user_message,
            conversation_context=conversation_context,
            effective_mode=effective_mode,
            routing_metadata=routing_metadata,
        )
        if effective_mode == "plan":
            self.permission_manager.set_mode(AgentPermissionMode.PLAN)
        else:
            self.permission_manager.set_mode(AgentPermissionMode.BUILD)
        return effective_mode, selection_context

    def _stream_determine_mode_and_permissions(
        self,
        plan_mode: bool,
        routing_decision: RoutingDecision,
    ) -> str:
        """Determine effective execution mode and set permission mode.

        Returns:
            effective_mode: "plan" or "build"
        """
        from src.infrastructure.agent.permission.manager import AgentPermissionMode

        resolved_plan_mode = plan_mode or routing_decision.path == ExecutionPath.PLAN_MODE
        effective_mode = (
            "plan"
            if resolved_plan_mode
            else (self.agent_mode if self.agent_mode in ["build", "plan"] else "build")
        )

        if effective_mode == "plan":
            self.permission_manager.set_mode(AgentPermissionMode.PLAN)
        else:
            self.permission_manager.set_mode(AgentPermissionMode.BUILD)

        return effective_mode

    def _stream_record_skill_usage(self, matched_skill: Any, success: bool) -> None:
        """Record skill usage statistics after stream completion."""
        if matched_skill:
            matched_skill.record_usage(success)
            logger.info(
                f"[ReActAgent] Skill {matched_skill.name} usage recorded: success={success}"
            )

    async def stream(  # noqa: PLR0913
        self,
        conversation_id: str,
        user_message: str,
        project_id: str,
        user_id: str,
        tenant_id: str,
        conversation_context: list[dict[str, str]] | None = None,
        message_id: str | None = None,
        attachment_content: list[dict[str, Any]] | None = None,
        attachment_metadata: list[dict[str, Any]] | None = None,
        abort_signal: asyncio.Event | None = None,
        forced_skill_name: str | None = None,
        context_summary_data: dict[str, Any] | None = None,
        plan_mode: bool = False,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Stream agent response with ReAct loop.

        This is the main entry point for agent execution. It:
        1. Checks for Plan Mode triggering
        2. Checks for SubAgent routing (L3)
        3. Checks for Skill matching (L2)
        4. Builds messages from context
        5. Creates SessionProcessor
        6. Streams events back to caller

        Args:
            conversation_id: Conversation ID
            user_message: User's message
            project_id: Project ID
            user_id: User ID
            tenant_id: Tenant ID
            conversation_context: Optional conversation history
            message_id: Optional message ID for HITL request persistence
            forced_skill_name: Optional skill name to force direct execution

        Yields:
            Event dictionaries compatible with existing SSE format:
            - {"type": "plan_mode_triggered", "data": {...}}
            - {"type": "thought", "data": {...}}
            - {"type": "act", "data": {...}}
            - {"type": "observe", "data": {...}}
            - {"type": "complete", "data": {...}}
            - {"type": "error", "data": {...}}
        """
        conversation_context = conversation_context or []
        start_time = time.time()

        logger.info(
            f"[ReActAgent] Starting stream for conversation {conversation_id}, "
            f"user: {user_id}, message: {user_message[:50]}..."
        )

        # Phase 1: Plan mode detection
        async for event in self._stream_detect_plan_mode(user_message, conversation_id):
            yield event

        # Phase 2: Parse forced subagent from system instruction
        forced_subagent_name, processed_user_message = self._stream_parse_forced_subagent(
            user_message
        )

        # Phase 3: Routing decision
        routing_decision, _route_id, _trace_id, routing_metadata, forced_skill_name, route_event = (
            self._stream_decide_route(
                processed_user_message=processed_user_message,
                conversation_context=conversation_context,
                forced_subagent_name=forced_subagent_name,
                forced_skill_name=forced_skill_name,
                plan_mode=plan_mode,
            )
        )
        yield route_event

        # Phase 5: Skill matching
        for event in self._stream_match_skill(processed_user_message, forced_skill_name):
            yield event
        skill_state = self._stream_skill_state
        matched_skill: Skill | None = cast("Skill | None", skill_state["matched_skill"])
        is_forced: bool = cast(bool, skill_state["is_forced"])
        should_inject_prompt: bool = cast(bool, skill_state["should_inject_prompt"])

        # Phase 5b: Sync skill resources
        if should_inject_prompt and matched_skill:
            await self._stream_sync_skill_resources(matched_skill)

        # Phase 6: Mode/selection context setup
        effective_mode, selection_context = self._stream_resolve_mode(
            plan_mode=plan_mode,
            routing_decision=routing_decision,
            routing_metadata=routing_metadata,
            tenant_id=tenant_id,
            project_id=project_id,
            processed_user_message=processed_user_message,
            conversation_context=conversation_context,
        )

        # Phase 6b: Inject matched skill's declared tools into selection context
        # so the tool selection pipeline can pin them (survive semantic budget + deny lists)
        if matched_skill and matched_skill.tools:
            skill_pinned = list(matched_skill.tools)
            cast(dict[str, Any], selection_context.metadata)["skill_pinned_tools"] = skill_pinned
            logger.info(
                f"[ReActAgent] Skill '{matched_skill.name}' declares tools={skill_pinned}, "
                f"injecting into selection context for pipeline pinning"
            )

        # Phase 7: Memory recall
        async for event in self._stream_recall_memory(processed_user_message, project_id):
            yield event
        memory_context = self._stream_memory_context

        # Phase 8: System prompt building
        system_prompt = await self._build_system_prompt(
            processed_user_message,
            conversation_context,
            matched_skill=matched_skill if should_inject_prompt else None,
            subagent=None,
            mode=effective_mode,
            current_step=1,
            project_id=project_id,
            tenant_id=tenant_id,
            force_execution=is_forced,
            memory_context=memory_context,
            selection_context=selection_context,
        )

        # Phase 9: Context building
        async for event in self._stream_build_context(
            system_prompt=system_prompt,
            conversation_context=conversation_context,
            processed_user_message=processed_user_message,
            attachment_metadata=attachment_metadata,
            attachment_content=attachment_content,
            context_summary_data=context_summary_data,
            project_id=project_id,
            conversation_id=conversation_id,
        ):
            yield event
        messages = self._stream_messages

        # Phase 10: Tool preparation
        for event in self._stream_prepare_tools(selection_context, is_forced, matched_skill):
            yield event
        tools_to_use = self._stream_tools_to_use

        # Phase 11: SubAgent-as-Tool injection
        tools_to_use = self._stream_inject_subagent_tools(
            tools_to_use=tools_to_use,
            conversation_context=conversation_context,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            abort_signal=abort_signal,
        )

        # Phase 12: Processor creation
        config = self._stream_create_processor_config(self.config, selection_context)
        # Pass forced skill context to processor for loop reinforcement (Fix 4)
        if is_forced and matched_skill:
            config.forced_skill_name = matched_skill.name
            config.forced_skill_tools = list(matched_skill.tools) if matched_skill.tools else None
        processor = self._processor_factory.create_for_main(
            config=config,
            tools=tools_to_use,
        )

        langfuse_context = {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "message_id": message_id,
        }

        # Phase 13: Event processing
        async for event in self._stream_process_events(
            processor=processor,
            messages=messages,
            langfuse_context=langfuse_context,
            abort_signal=abort_signal,
            matched_skill=matched_skill,
        ):
            yield event

        # Phase 14: Post-processing
        async for event in self._stream_post_process(
            processed_user_message=processed_user_message,
            final_content=self._stream_final_content,
            project_id=project_id,
            conversation_id=conversation_id,
            conversation_context=conversation_context,
            matched_skill=matched_skill,
            success=self._stream_success,
        ):
            yield event

        # Finally: Record execution statistics
        end_time = time.time()
        execution_time_ms = int((end_time - start_time) * 1000)
        logger.debug(f"[ReActAgent] Stream finished in {execution_time_ms}ms")
        self._stream_record_skill_usage(matched_skill, self._stream_success)

    async def _subagent_fetch_memory_context(
        self,
        user_message: str,
        project_id: str,
    ) -> str:
        """Search for relevant memories to inject into SubAgent context."""
        return await self._session_runner.fetch_memory_context(
            user_message,
            project_id,
        )

    def _subagent_filter_tools(
        self,
        subagent: SubAgent,
    ) -> tuple[list[ToolDefinition], set[str]]:
        """Filter tools for SubAgent permissions and return mutable collections."""
        return self._tool_builder.filter_tools(subagent)

    def _subagent_inject_nested_tools(
        self,
        *,
        subagent: SubAgent,
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        conversation_id: str,
        abort_signal: asyncio.Event | None,
        delegation_depth: int,
        filtered_tools: list[ToolDefinition],
        existing_tool_names: set[str],
    ) -> None:
        """Inject SubAgent delegation tools for nested orchestration (bounded depth)."""
        self._tool_builder.inject_nested_tools(
            subagent=subagent,
            conversation_context=conversation_context,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            abort_signal=abort_signal,
            delegation_depth=delegation_depth,
            filtered_tools=filtered_tools,
            existing_tool_names=existing_tool_names,
        )

    def _build_nested_subagent_callbacks(
        self,
        *,
        nested_map: dict[str, SubAgent],
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        conversation_id: str,
        abort_signal: asyncio.Event | None,
        delegation_depth: int,
    ) -> tuple[
        Callable[..., Coroutine[Any, Any, str]],
        Callable[..., Coroutine[Any, Any, str]],
        Callable[..., Coroutine[Any, Any, bool]],
    ]:
        """Build nested delegate, spawn and cancel callbacks."""
        return self._tool_builder.build_nested_subagent_callbacks(
            nested_map=nested_map,
            conversation_context=conversation_context,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            abort_signal=abort_signal,
            delegation_depth=delegation_depth,
        )

    def _append_nested_session_tools(
        self,
        *,
        append_fn: Callable[[Any], None],
        conversation_id: str,
        nested_depth: int,
        max_delegation_depth: int,
        nested_map: dict[str, Any],
        nested_descriptions: dict[str, str],
        cancel_callback: Callable[..., Coroutine[Any, Any, bool]],
        restart_callback: Callable[..., Coroutine[Any, Any, str]],
    ) -> None:
        """Append session management tools."""
        self._tool_builder.append_nested_session_tools(
            append_fn=append_fn,
            conversation_id=conversation_id,
            nested_depth=nested_depth,
            max_delegation_depth=max_delegation_depth,
            nested_map=nested_map,
            nested_descriptions=nested_descriptions,
            cancel_callback=cancel_callback,
            restart_callback=restart_callback,
        )

    def _append_nested_delegate_tools(
        self,
        *,
        append_fn: Callable[[Any], None],
        nested_candidates: list[SubAgent],
        nested_map: dict[str, Any],
        nested_descriptions: dict[str, str],
        delegate_callback: Callable[..., Coroutine[Any, Any, str]],
        conversation_id: str,
        nested_depth: int,
    ) -> None:
        """Append delegate and parallel-delegate tools."""
        self._tool_builder.append_nested_delegate_tools(
            append_fn=append_fn,
            nested_candidates=nested_candidates,
            nested_map=nested_map,
            nested_descriptions=nested_descriptions,
            delegate_callback=delegate_callback,
            conversation_id=conversation_id,
            nested_depth=nested_depth,
        )

    async def _execute_subagent(
        self,
        subagent: SubAgent,
        user_message: str,
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        conversation_id: str = "",
        abort_signal: asyncio.Event | None = None,
        delegation_depth: int = 0,
        model_override: str | None = None,
        thinking_override: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute a SubAgent in an independent ReAct loop."""
        async for evt in self._session_runner.execute_subagent(
            subagent=subagent,
            user_message=user_message,
            conversation_context=conversation_context,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            abort_signal=abort_signal,
            delegation_depth=delegation_depth,
            model_override=model_override,
            thinking_override=thinking_override,
        ):
            yield evt

    async def _execute_parallel(
        self,
        subtasks: list[Any],
        user_message: str,
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        conversation_id: str | None = None,
        route_id: str | None = None,
        abort_signal: asyncio.Event | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute multiple SubAgents in parallel."""
        async for evt in self._session_runner.execute_parallel(
            subtasks=subtasks,
            user_message=user_message,
            conversation_context=conversation_context,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            route_id=route_id,
            abort_signal=abort_signal,
        ):
            yield evt

    async def _execute_chain(
        self,
        subtasks: list[Any],
        user_message: str,
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        conversation_id: str | None = None,
        route_id: str | None = None,
        abort_signal: asyncio.Event | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute SubAgents as a sequential chain."""
        async for evt in self._session_runner.execute_chain(
            subtasks=subtasks,
            user_message=user_message,
            conversation_context=conversation_context,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            route_id=route_id,
            abort_signal=abort_signal,
        ):
            yield evt

    async def _execute_background(
        self,
        subagent: SubAgent,
        user_message: str,
        conversation_id: str,
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Launch a SubAgent for background execution."""
        async for evt in self._session_runner.execute_background(
            subagent=subagent,
            user_message=user_message,
            conversation_id=conversation_id,
            conversation_context=conversation_context,
            project_id=project_id,
            tenant_id=tenant_id,
        ):
            yield evt

    async def _emit_subagent_lifecycle_hook(
        self,
        event: dict[str, Any],
    ) -> None:
        """Emit detached SubAgent lifecycle hook event."""
        await self._session_runner.emit_subagent_lifecycle_hook(event)

    def _get_subagent_observability_stats(self) -> dict[str, int]:
        """Return subagent lifecycle observability counters."""
        return self._session_runner.get_subagent_observability_stats()

    def _runner_resolve_overrides(
        self,
        conversation_id: str,
        run_id: str,
        requested_model: str | None,
        requested_thinking: str | None,
        normalized_spawn_mode: str,
        thread_requested: bool,
        normalized_cleanup: str,
    ) -> tuple[str | None, str | None, float]:
        """Resolve model/thinking overrides."""
        return self._session_runner.runner_resolve_overrides(
            conversation_id=conversation_id,
            run_id=run_id,
            requested_model=requested_model,
            requested_thinking=requested_thinking,
            normalized_spawn_mode=normalized_spawn_mode,
            thread_requested=thread_requested,
            normalized_cleanup=normalized_cleanup,
        )

    def _runner_mark_completion(
        self,
        conversation_id: str,
        run_id: str,
        result_success: bool,
        result_error: str | None,
        summary: str,
        tokens_used: int | None,
        execution_time_ms: int | None,
        started_at: float,
    ) -> None:
        """Mark a SubAgent run as completed or failed."""
        self._session_runner.runner_mark_completion(
            conversation_id=conversation_id,
            run_id=run_id,
            result_success=result_success,
            result_error=result_error,
            summary=summary,
            tokens_used=tokens_used,
            execution_time_ms=execution_time_ms,
            started_at=started_at,
        )

    def _runner_mark_timeout(
        self,
        conversation_id: str,
        run_id: str,
        configured_timeout: float,
    ) -> None:
        """Handle TimeoutError for a SubAgent runner."""
        self._session_runner.runner_mark_timeout(
            conversation_id=conversation_id,
            run_id=run_id,
            configured_timeout=configured_timeout,
        )

    def _runner_mark_cancelled(
        self,
        conversation_id: str,
        run_id: str,
    ) -> None:
        """Handle CancelledError for a SubAgent runner."""
        self._session_runner.runner_mark_cancelled(
            conversation_id=conversation_id,
            run_id=run_id,
        )

    def _runner_mark_error(
        self,
        conversation_id: str,
        run_id: str,
        exc: Exception,
        started_at: float,
    ) -> None:
        """Handle generic Exception for a SubAgent runner."""
        self._session_runner.runner_mark_error(
            conversation_id=conversation_id,
            run_id=run_id,
            exc=exc,
            started_at=started_at,
        )

    async def _runner_finalize(
        self,
        *,
        conversation_id: str,
        run_id: str,
        subagent: SubAgent,
        cancelled_by_control: bool,
        summary: str,
        tokens_used: int | None,
        execution_time_ms: int | None,
        normalized_spawn_mode: str,
        thread_requested: bool,
        normalized_cleanup: str,
        resolved_model_override: str | None,
        resolved_thinking_override: str | None,
    ) -> None:
        """Finalize a SubAgent runner."""
        await self._session_runner.runner_finalize(
            conversation_id=conversation_id,
            run_id=run_id,
            subagent=subagent,
            cancelled_by_control=cancelled_by_control,
            summary=summary,
            tokens_used=tokens_used,
            execution_time_ms=execution_time_ms,
            normalized_spawn_mode=normalized_spawn_mode,
            thread_requested=thread_requested,
            normalized_cleanup=normalized_cleanup,
            resolved_model_override=resolved_model_override,
            resolved_thinking_override=resolved_thinking_override,
        )

    async def _launch_emit_lifecycle_hooks(
        self,
        *,
        conversation_id: str,
        run_id: str,
        subagent: SubAgent,
        normalized_spawn_mode: str,
        thread_requested: bool,
        normalized_cleanup: str,
        requested_model_override: str | None,
        requested_thinking_override: str | None,
    ) -> None:
        """Emit spawning + spawned lifecycle hooks."""
        await self._session_runner.launch_emit_lifecycle_hooks(
            conversation_id=conversation_id,
            run_id=run_id,
            subagent=subagent,
            normalized_spawn_mode=normalized_spawn_mode,
            thread_requested=thread_requested,
            normalized_cleanup=normalized_cleanup,
            requested_model_override=requested_model_override,
            requested_thinking_override=requested_thinking_override,
        )

    @staticmethod
    def _normalize_launch_params(
        spawn_mode: str,
        cleanup: str,
        model_override: str | None,
        thinking_override: str | None,
    ) -> tuple[str, str, str | None, str | None]:
        """Normalize input parameters for subagent session launch."""
        return SubAgentSessionRunner.normalize_launch_params(
            spawn_mode,
            cleanup,
            model_override,
            thinking_override,
        )

    async def _runner_consume_and_extract(
        self,
        *,
        subagent: SubAgent,
        user_message: str,
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        conversation_id: str,
        abort_signal: asyncio.Event | None,
        model_override: str | None,
        thinking_override: str | None,
    ) -> tuple[str, int | None, int | None, bool, str | None]:
        """Consume subagent events and extract completion results."""
        return await self._session_runner.runner_consume_and_extract(
            subagent=subagent,
            user_message=user_message,
            conversation_context=conversation_context,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            abort_signal=abort_signal,
            model_override=model_override,
            thinking_override=thinking_override,
        )

    async def _launch_subagent_session(  # noqa: PLR0913
        self,
        run_id: str,
        subagent: SubAgent,
        user_message: str,
        conversation_id: str,
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        abort_signal: asyncio.Event | None = None,
        model_override: str | None = None,
        thinking_override: str | None = None,
        spawn_mode: str = "run",
        thread_requested: bool = False,
        cleanup: str = "keep",
    ) -> None:
        """Launch a detached SubAgent session tied to a run_id."""
        await self._session_runner.launch_subagent_session(
            run_id=run_id,
            subagent=subagent,
            user_message=user_message,
            conversation_id=conversation_id,
            conversation_context=conversation_context,
            project_id=project_id,
            tenant_id=tenant_id,
            abort_signal=abort_signal,
            model_override=model_override,
            thinking_override=thinking_override,
            spawn_mode=spawn_mode,
            thread_requested=thread_requested,
            cleanup=cleanup,
        )

    @staticmethod
    def _resolve_subagent_completion_outcome(
        status: str,
    ) -> tuple[str, str]:
        """Map terminal run status to announce outcome labels."""
        return SubAgentSessionRunner.resolve_subagent_completion_outcome(
            status,
        )

    def _append_capped_announce_event(
        self,
        events: list[dict[str, Any]],
        dropped_count: int,
        event: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], int]:
        """Append announce event while enforcing bounded history size."""
        return self._session_runner.append_capped_announce_event(
            events,
            dropped_count,
            event,
        )

    @classmethod
    def _build_subagent_completion_payload(
        cls,
        *,
        run: Any,
        fallback_summary: str,
        fallback_tokens_used: int | None,
        fallback_execution_time_ms: int | None,
        spawn_mode: str,
        thread_requested: bool,
        cleanup: str,
        model_override: str | None,
        thinking_override: str | None,
    ) -> dict[str, Any]:
        """Build normalized completion announce payload."""
        return SubAgentSessionRunner.build_subagent_completion_payload(
            run=run,
            fallback_summary=fallback_summary,
            fallback_tokens_used=fallback_tokens_used,
            fallback_execution_time_ms=fallback_execution_time_ms,
            spawn_mode=spawn_mode,
            thread_requested=thread_requested,
            cleanup=cleanup,
            model_override=model_override,
            thinking_override=thinking_override,
        )

    async def _persist_subagent_completion_announce(
        self,
        *,
        conversation_id: str,
        run_id: str,
        fallback_summary: str,
        fallback_tokens_used: int | None,
        fallback_execution_time_ms: int | None,
        spawn_mode: str,
        thread_requested: bool,
        cleanup: str,
        model_override: str | None,
        thinking_override: str | None,
        max_retries: int,
    ) -> None:
        """Persist terminal announce payload with retry/backoff."""
        await self._session_runner.persist_subagent_completion_announce(
            conversation_id=conversation_id,
            run_id=run_id,
            fallback_summary=fallback_summary,
            fallback_tokens_used=fallback_tokens_used,
            fallback_execution_time_ms=fallback_execution_time_ms,
            spawn_mode=spawn_mode,
            thread_requested=thread_requested,
            cleanup=cleanup,
            model_override=model_override,
            thinking_override=thinking_override,
            max_retries=max_retries,
        )

    async def _cancel_subagent_session(self, run_id: str) -> bool:
        """Cancel a detached SubAgent session by run_id."""
        return await self._session_runner.cancel_subagent_session(run_id)

    @staticmethod
    def _topological_sort_subtasks(
        subtasks: list[Any],
    ) -> list[Any]:
        """Sort subtasks by dependency order."""
        return SubAgentSessionRunner.topological_sort_subtasks(subtasks)

    def _extract_sandbox_id_from_tools(self) -> str | None:
        """Extract sandbox_id from any available sandbox tool wrapper."""
        current_tools, _ = self._get_current_tools()
        for tool in current_tools.values():
            if hasattr(tool, "sandbox_id") and tool.sandbox_id:
                return cast(str | None, tool.sandbox_id)
        return None

    def _convert_domain_event(
        self, domain_event: AgentDomainEvent | dict[str, Any]
    ) -> dict[str, Any] | None:
        """
        Convert AgentDomainEvent to event dictionary format.

        Delegates to EventConverter for modular implementation.

        Args:
            domain_event: AgentDomainEvent from processor

        Returns:
            Event dict or None to skip
        """
        if isinstance(domain_event, dict):
            return domain_event

        # Delegate to EventConverter
        return cast(dict[str, Any] | None, self._event_converter.convert(domain_event))

    async def astream_multi_level(
        self,
        conversation_id: str,
        project_id: str,
        user_id: str,
        tenant_id: str,
        user_query: str,
        conversation_context: list[dict[str, str]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Stream with multi-level thinking (compatibility method).

        This method provides compatibility with the existing AgentService
        interface that expects astream_multi_level.

        Args:
            conversation_id: Conversation ID
            project_id: Project ID
            user_id: User ID
            tenant_id: Tenant ID
            user_query: User's query
            conversation_context: Conversation history

        Yields:
            Event dictionaries
        """
        # Delegate to stream method
        async for event in self.stream(
            conversation_id=conversation_id,
            user_message=user_query,
            project_id=project_id,
            user_id=user_id,
            tenant_id=tenant_id,
            conversation_context=conversation_context,
        ):
            yield event


def create_react_agent(
    model: str,
    tools: dict[str, Any],
    api_key: str | None = None,
    base_url: str | None = None,
    skills: list[Skill] | None = None,
    subagents: list[SubAgent] | None = None,
    **kwargs: Any,
) -> ReActAgent:
    """
    Factory function to create ReAct Agent.

    Args:
        model: LLM model name
        tools: Dictionary of tools
        api_key: Optional API key
        base_url: Optional base URL
        skills: Optional list of Skills (L2 layer)
        subagents: Optional list of SubAgents (L3 layer)
        **kwargs: Additional configuration

    Returns:
        Configured ReActAgent instance
    """
    return ReActAgent(
        model=model,
        tools=tools,
        api_key=api_key,
        base_url=base_url,
        skills=skills,
        subagents=subagents,
        **kwargs,
    )
