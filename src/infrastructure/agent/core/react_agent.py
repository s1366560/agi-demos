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
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, cast

from src.domain.events.agent_events import (
    AgentDomainEvent,
)
from src.domain.model.agent.agent_definition import Agent
from src.domain.model.agent.skill import Skill
from src.domain.model.agent.subagent import SubAgent
from src.domain.model.agent.tenant_agent_config import TenantAgentConfig

from ..commands.builtins import register_builtin_commands
from ..commands.interceptor import CommandInterceptor
from ..commands.registry import CommandRegistry
from ..config import ExecutionConfig
from ..context import ContextFacade, ContextWindowConfig, ContextWindowManager
from ..events import EventConverter
from ..events.converter import normalize_event_dict
from ..heartbeat.config import HeartbeatConfig
from ..heartbeat.runner import HeartbeatRunner
from ..permission import PermissionManager
from ..planning.plan_detector import PlanDetector
from ..plugins.policy_context import normalize_policy_layers
from ..plugins.registry import get_plugin_registry
from ..plugins.selection_pipeline import (
    ToolSelectionContext,
    ToolSelectionTraceStep,
    build_default_tool_selection_pipeline,
)
from ..prompts import SystemPromptManager
from ..routing import (
    IntentGate,
)
from ..sisyphus.prompt_builder import SisyphusPromptBuilder
from .processor import (
    ProcessorConfig,
    ProcessorFactory,
    ToolDefinition,
)
from .subagent_router import SubAgentMatch, SubAgentRouter
from .subagent_runner import SubAgentRunnerDeps, SubAgentSessionRunner
from .subagent_tools import SubAgentToolBuilder, SubAgentToolBuilderDeps
from .tool_converter import convert_tools
from .tool_name_policy import canonical_tool_policy_names

if TYPE_CHECKING:
    from src.application.services.artifact_service import ArtifactService
    from src.domain.llm_providers.llm_types import LLMClient
    from src.domain.ports.services.graph_service_port import GraphServicePort

logger = logging.getLogger(__name__)
_react_bg_tasks: set[asyncio.Task[Any]] = set()

# Re-exported from ``react_agent_profile`` for backward compatibility.
# Anything new should import directly from ``react_agent_profile``.
from .react_agent_composition_mixin import CompositionMixin  # noqa: E402
from .react_agent_profile import (  # noqa: E402, F401  (re-export for back-compat)
    AgentRuntimeProfile,  # pyright: ignore[reportUnusedImport]
    _register_selected_agent_session,  # pyright: ignore[reportUnusedImport]
)
from .react_agent_prompt_mixin import PromptMixin  # noqa: E402
from .react_agent_routing_mixin import RoutingMixin  # noqa: E402
from .react_agent_stream_mixin import StreamMixin  # noqa: E402
from .react_agent_subagent_runner_mixin import SubAgentRunnerMixin  # noqa: E402
from .react_agent_tool_policy import (  # noqa: E402
    WORKSPACE_ROOT_TOOL_BYPASS_NAMES,
)


class ReActAgent(RoutingMixin, PromptMixin, StreamMixin, SubAgentRunnerMixin, CompositionMixin):
    _WORKSPACE_ROOT_TOOL_BYPASS_NAMES: ClassVar[frozenset[str]] = WORKSPACE_ROOT_TOOL_BYPASS_NAMES

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

    # -- Instance variable type declarations (for pyright) --
    # _init_tool_pipeline
    _tool_selection_pipeline: Any
    _tool_selection_max_tools: int
    _tool_selection_semantic_backend: str
    _router_mode_tool_count_threshold: int
    _tool_policy_layers: dict[str, dict[str, Any]]
    _last_tool_selection_trace: tuple[ToolSelectionTraceStep, ...]
    # _init_memory_hooks
    _memory_runtime: Any
    _session_factory: Any
    # _init_prompt_and_context
    prompt_manager: Any
    context_manager: ContextWindowManager
    context_facade: ContextFacade
    # _init_skill_system
    skills: list[Skill]
    skill_match_threshold: float
    skill_fallback_on_error: bool
    skill_execution_timeout: int
    _filesystem_skills_loaded: bool
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
    # _intent_gate
    _intent_gate: IntentGate

    def __init__(  # noqa: PLR0913
        self,
        model: str,
        tools: dict[str, Any] | None = None,  # Tool name -> Tool instance (static)
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 32768,  # Larger budget prevents write/tool JSON truncation.
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
        # Workspace persona manager (loaded from .memstack/workspace/)
        workspace_manager: Any | None = None,
        # Heartbeat configuration (periodic self-check during long sessions)
        heartbeat_config: HeartbeatConfig | None = None,
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
        # Memory runtime + infrastructure
        memory_runtime: Any | None = None,
        session_factory: Any = None,
        tool_selection_pipeline: Any | None = None,
        tool_selection_max_tools: int = 40,
        tool_selection_semantic_backend: str = "embedding_vector",
        router_mode_tool_count_threshold: int = 100,
        tool_policy_layers: Mapping[str, Any] | None = None,
        span_service: Any | None = None,
        fork_merge_service: Any | None = None,
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
        self._workspace_manager = workspace_manager  # Workspace persona/soul file loader
        self._sisyphus_prompt_builder = SisyphusPromptBuilder()
        self._heartbeat_runner: HeartbeatRunner | None = None
        if heartbeat_config and heartbeat_config.enabled:
            self._heartbeat_runner = HeartbeatRunner(
                config=heartbeat_config,
                workspace_manager=workspace_manager,
            )
        self._plan_detector = plan_detector or PlanDetector()
        self._intent_gate = IntentGate()

        self._init_tool_pipeline(
            tool_selection_pipeline,
            tool_selection_max_tools,
            tool_selection_semantic_backend,
            router_mode_tool_count_threshold,
            tool_policy_layers,
        )
        self._init_memory_hooks(
            memory_runtime=memory_runtime,
            session_factory=session_factory,
        )
        self._init_prompt_and_context(
            _cached_system_prompt_manager,
            context_window_config,
            max_context_tokens,
            max_tokens,
            workspace_manager,
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
            span_service=span_service,
            fork_merge_service=fork_merge_service,
        )
        self._init_orchestrators()
        self._init_background_services(llm_client)
        self._init_tool_definitions(
            _cached_tool_definitions, model, api_key, base_url, temperature, max_tokens, max_steps
        )
        self._reset_stream_state()

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
            plugin_registry=get_plugin_registry(),
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
        self._last_tool_selection_trace = ()

    def _init_memory_hooks(
        self,
        *,
        memory_runtime: Any,
        session_factory: Any,
    ) -> None:
        """Initialize memory runtime and its supporting infrastructure."""
        self._memory_runtime = memory_runtime
        self._session_factory = session_factory

    def _reset_stream_state(self) -> None:
        """Reset per-stream transient state before a new run starts."""
        self._stream_skill_state = {
            "matched_skill": None,
            "is_forced": False,
            "should_inject_prompt": False,
        }
        self._stream_memory_context = None
        self._stream_context_result = None
        self._stream_messages = []
        self._stream_cached_summary = None
        self._stream_tools_to_use = []
        self._stream_final_content = ""
        self._stream_success = False

    def _init_prompt_and_context(
        self,
        cached_prompt_manager: Any | None,
        context_window_config: ContextWindowConfig | None,
        max_context_tokens: int,
        max_tokens: int,
        workspace_manager: Any | None = None,
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
        self._filesystem_skills_loaded = False

        # Skill-embedded MCP manager (lazy import to avoid circular deps)
        from ..mcp.skill_mcp_manager import SkillMCPManager

        self._skill_mcp_manager = SkillMCPManager()
        self._skill_mcp_tools: list[ToolDefinition] = []

    async def _load_filesystem_skills(
        self,
        tenant_id: str,
        project_id: str,
    ) -> None:
        """Lazy-load Skills from .memstack/skills/ on first stream() call.

        Filesystem skills are appended to self.skills without replacing
        any database-sourced skills. Loading happens at most once per agent
        instance (guarded by _filesystem_skills_loaded flag).
        """
        if self._filesystem_skills_loaded:
            return
        self._filesystem_skills_loaded = True

        # Lazy import to avoid circular deps and basedpyright indexing issues
        from src.infrastructure.agent.skill.filesystem_loader import FileSystemSkillLoader

        try:
            loader = FileSystemSkillLoader(
                base_path=self.project_root,
                tenant_id=tenant_id,
                project_id=project_id,
            )
            result = await loader.load_all()
            if result.count > 0:
                self.skills.extend(loaded.skill for loaded in result.skills)
                # P1-Fix3: Update ProcessorConfig.skill_names so /skills
                # command fallback stays current after lazy filesystem load.
                self.config.skill_names = [s.name for s in self.skills]
                logger.info(
                    "[ReActAgent] Loaded %d filesystem skills from %s",
                    result.count,
                    self.project_root,
                )
            if result.errors:
                for err in result.errors:
                    logger.warning("[ReActAgent] Filesystem skill load error: %s", err)
        except Exception as e:
            logger.warning("[ReActAgent] Failed to load filesystem skills: %s", e)

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
        span_service: Any | None = None,
        fork_merge_service: Any | None = None,
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
        self._span_service = span_service
        self._fork_merge_service = fork_merge_service
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
        from ..subagent.run_registry import get_shared_subagent_run_registry

        self._subagent_run_registry = get_shared_subagent_run_registry(
            persistence_path=subagent_run_registry_path,
            postgres_persistence_dsn=subagent_run_postgres_dsn,
            sqlite_persistence_path=subagent_run_sqlite_path,
            redis_cache_url=subagent_run_redis_cache_url,
            redis_cache_ttl_seconds=subagent_run_redis_cache_ttl_seconds,
            terminal_retention_seconds=subagent_terminal_retention_seconds,
        )
        self._subagent_session_tasks = {}

    def _init_orchestrators(self) -> None:
        """Initialize orchestrators for modular components."""
        self._event_converter = EventConverter(debug_logging=False)

    def _init_background_services(self, llm_client: Any | None) -> None:
        """Initialize background SubAgent services."""
        from ..subagent.background_executor import BackgroundExecutor
        from ..subagent.result_aggregator import ResultAggregator
        from ..subagent.template_registry import TemplateRegistry

        self._background_executor = BackgroundExecutor(
            span_service=self._span_service,
            fork_merge_service=self._fork_merge_service,
        )
        self._template_registry = TemplateRegistry()

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

        # Build reasoning-aware provider options for the model
        from src.infrastructure.llm.reasoning_config import build_reasoning_config

        _reasoning_cfg = build_reasoning_config(model)
        _provider_opts: dict[str, Any] = {}
        if _reasoning_cfg:
            _provider_opts = {
                **_reasoning_cfg.provider_options,
                "__omit_temperature": _reasoning_cfg.omit_temperature,
                "__use_max_completion_tokens": _reasoning_cfg.use_max_completion_tokens,
                "__override_max_tokens": _reasoning_cfg.override_max_tokens,
            }

        self.config = ProcessorConfig(
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            max_steps=max_steps,
            llm_client=self._llm_client,
            plugin_registry=get_plugin_registry(),
            skill_names=[s.name for s in (self.skills or [])],
            provider_options=_provider_opts,
        )

    async def _notify_runtime_hook(
        self,
        hook_name: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Dispatch one runtime hook via the shared plugin registry."""
        effective_payload = dict(payload or {})
        plugin_registry = getattr(self.config, "plugin_registry", None)
        if plugin_registry is None:
            return effective_payload

        try:
            result = await plugin_registry.apply_hook(
                hook_name,
                payload=effective_payload,
                runtime_overrides=getattr(self.config, "runtime_hook_overrides", []),
            )
            for diagnostic in result.diagnostics:
                log_level = logging.ERROR if diagnostic.level == "error" else logging.WARNING
                logger.log(
                    log_level,
                    "[ReActAgent] Runtime hook %s diagnostic [%s]: %s",
                    hook_name,
                    diagnostic.plugin_name,
                    diagnostic.message,
                )
            return dict(result.payload)
        except Exception:
            logger.warning("[ReActAgent] Runtime hook %r failed", hook_name, exc_info=True)
            return effective_payload

    async def _apply_before_prompt_build_hook(
        self,
        *,
        processed_user_message: str,
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        conversation_id: str,
        effective_mode: str,
        matched_skill: Skill | None,
        selected_agent: Agent,
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """Allow runtime hooks to refine prompt-bound memory context."""
        hook_payload = await self._notify_runtime_hook(
            "before_prompt_build",
            {
                "project_id": project_id,
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "mode": effective_mode,
                "user_message": processed_user_message,
                "conversation_context": list(conversation_context),
                "memory_context": self._stream_memory_context,
                "memory_runtime": self._memory_runtime,
                "matched_skill_name": matched_skill.name if matched_skill else None,
                "selected_agent_id": selected_agent.id,
                "selected_agent_name": selected_agent.name,
            },
        )
        memory_context = hook_payload.get("memory_context", self._stream_memory_context)
        if memory_context is not None and not isinstance(memory_context, str):
            memory_context = self._stream_memory_context
        self._stream_memory_context = cast(str | None, memory_context)
        emitted_events = hook_payload.get("emitted_events")
        return self._stream_memory_context, (
            list(emitted_events) if isinstance(emitted_events, list) else []
        )

    async def _notify_context_overflow_hook(
        self,
        *,
        tenant_id: str,
        project_id: str,
        conversation_id: str,
        conversation_context: list[dict[str, str]],
        context_result: Any,
    ) -> list[dict[str, Any]]:
        """Emit a runtime hook when context overflow causes compression."""
        hook_payload = await self._notify_runtime_hook(
            "on_context_overflow",
            {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "conversation_id": conversation_id,
                "conversation_context": list(conversation_context),
                "memory_runtime": self._memory_runtime,
                "compression_level": context_result.compression_strategy.value,
                "summary_text": context_result.summary,
                "original_message_count": context_result.original_message_count,
                "final_message_count": context_result.final_message_count,
                "summarized_message_count": context_result.summarized_message_count,
                "estimated_tokens": context_result.estimated_tokens,
            },
        )
        emitted_events = hook_payload.get("emitted_events")
        return list(emitted_events) if isinstance(emitted_events, list) else []

    async def _notify_after_turn_complete_hook(
        self,
        *,
        processed_user_message: str,
        final_content: str,
        project_id: str,
        tenant_id: str,
        conversation_id: str,
        conversation_context: list[dict[str, str]],
        matched_skill: Skill | None,
        success: bool,
        execution_time_ms: int = 0,
        tool_call_count: int = 0,
        llm_client_override: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Emit a runtime hook after turn completion side effects finish."""
        hook_payload = await self._notify_runtime_hook(
            "after_turn_complete",
            {
                "project_id": project_id,
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "conversation_context": list(conversation_context),
                "user_message": processed_user_message,
                "final_content": final_content,
                "memory_runtime": self._memory_runtime,
                "matched_skill_name": matched_skill.name if matched_skill else None,
                "success": success,
                "execution_time_ms": execution_time_ms,
                "tool_call_count": tool_call_count,
                "llm_client_override": llm_client_override,
            },
        )
        emitted_events = hook_payload.get("emitted_events")
        return list(emitted_events) if isinstance(emitted_events, list) else []

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

    def _load_tenant_agent_config(
        self,
        tenant_id: str,
        tenant_agent_config_data: dict[str, Any] | None,
    ) -> TenantAgentConfig:
        """Load tenant config from request payload or fall back to defaults."""
        if isinstance(tenant_agent_config_data, dict):
            try:
                return TenantAgentConfig.from_dict(tenant_agent_config_data)
            except Exception:
                logger.exception("[ReActAgent] Failed to parse tenant agent config override")
        return TenantAgentConfig.create_default(tenant_id=tenant_id)

    def _build_runtime_workspace_manager(self, agent: Agent | None) -> Any | None:
        """Return an agent-scoped workspace manager clone when available."""
        if self._workspace_manager is None:
            return None
        scoped_agent_id = None
        if agent is not None:
            scoped_agent_id = agent.id.replace(":", "__")
        if hasattr(self._workspace_manager, "for_agent"):
            return self._workspace_manager.for_agent(scoped_agent_id)
        return self._workspace_manager

    def _filter_skills_for_agent(self, selected_agent: Agent | None) -> list[Skill]:
        """Filter skills using the selected agent's allowlist."""
        available_skills = list(self.skills or [])
        if selected_agent is None or not selected_agent.allowed_skills:
            return available_skills
        allowed_skill_names = {
            skill_name.strip().lower() for skill_name in selected_agent.allowed_skills
        }
        return [
            skill for skill in available_skills if skill.name.strip().lower() in allowed_skill_names
        ]

    def _resolve_tool_policy(
        self,
        *,
        selected_agent: Agent | None,
        tenant_agent_config: TenantAgentConfig,
    ) -> tuple[list[str], list[str]]:
        """Resolve effective tool allow/deny lists for this request."""
        allowlists: list[set[str]] = []
        if (
            selected_agent
            and selected_agent.allowed_tools
            and "*" not in selected_agent.allowed_tools
        ):
            allowlists.append(set(canonical_tool_policy_names(selected_agent.allowed_tools)))
        if tenant_agent_config.enabled_tools:
            allowlists.append(set(canonical_tool_policy_names(tenant_agent_config.enabled_tools)))

        effective_allow = set.intersection(*allowlists) if allowlists else set()
        effective_deny = set(canonical_tool_policy_names(tenant_agent_config.disabled_tools))
        return sorted(effective_allow), sorted(effective_deny)

    async def _inject_lane_jit_guidance(
        self,
        *,
        processor: Any,
        project_id: str,
        workspace_task: Any | None,
    ) -> None:
        """Build and inject lane JIT guidance for a workspace-scoped session.

        Sources the friction ledger from the process-level singleton wired
        by :func:`configure_friction_ingest` at app startup, and a
        SQL-backed playbook repository scoped to a fresh DB session.

        No-op when:
        - no workspace task is bound to the session,
        - no DB session factory or friction ledger is available,
        - the task's current status has no registered :class:`LaneContract`,
        - any composition step raises (logged + swallowed; this hook must
          never break the agent loop).
        """
        if workspace_task is None:
            return
        session_factory = self._session_factory
        if session_factory is None:
            return

        task_status = getattr(workspace_task, "status", None)
        lane_id = getattr(task_status, "value", None) or (
            task_status if isinstance(task_status, str) else None
        )
        if not lane_id:
            return

        try:
            from src.application.services.friction_runtime import (
                get_friction_ledger,
            )
            from src.application.services.lane_experience_runtime import (
                inject_lane_jit_context,
            )
            from src.application.services.lane_experience_service import (
                LaneExperienceService,
            )
            from src.domain.model.lane_contract import LaneContractRegistry
            from src.infrastructure.adapters.secondary.persistence.sql_playbook_repository import (
                SqlPlaybookRepository,
            )

            ledger = get_friction_ledger()
            if ledger is None:
                return

            registry = LaneContractRegistry.default()
            contract = registry.get(lane_id)
            if contract is None:
                return

            card_body = getattr(workspace_task, "description", None) or ""

            async with session_factory() as session:
                service = LaneExperienceService(
                    friction_ledger=ledger,
                    playbook_repository=SqlPlaybookRepository(session),
                )
                ctx = await service.build(
                    project_id=project_id,
                    lane_contract=contract,
                    card_body=card_body,
                )
            await inject_lane_jit_context(processor, ctx)
        except Exception:
            logger.warning(
                "lane_jit_guidance injection failed (project=%s, task=%s)",
                project_id,
                getattr(workspace_task, "id", None),
                exc_info=True,
            )

    def _convert_domain_event(
        self,
        domain_event: AgentDomainEvent | dict[str, Any],
        agent_id: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Convert AgentDomainEvent to event dictionary format.

        Delegates to EventConverter for modular implementation.

        Args:
            domain_event: AgentDomainEvent from processor
            agent_id: Optional agent ID to inject into event data

        Returns:
            Event dict or None to skip
        """
        if isinstance(domain_event, dict):
            return cast(
                dict[str, Any] | None,
                normalize_event_dict(domain_event, agent_id=agent_id),
            )

        # Delegate to EventConverter
        return cast(
            dict[str, Any] | None,
            self._event_converter.convert(domain_event, agent_id=agent_id),
        )


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
