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
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Callable, Coroutine, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, ClassVar, cast
from uuid import uuid4

from src.domain.events.agent_events import (
    AgentCompleteEvent,
    AgentContextCompressedEvent,
    AgentContextStatusEvent,
    AgentContextSummaryGeneratedEvent,
    AgentDomainEvent,
    AgentErrorEvent,
    AgentPlanSuggestedEvent,
    AgentPolicyFilteredEvent,
    AgentSelectionTraceEvent,
    AgentSkillMatchedEvent,
    AgentThoughtEvent,
)
from src.domain.model.agent.agent_definition import Agent
from src.domain.model.agent.skill import Skill
from src.domain.model.agent.subagent import SubAgent
from src.domain.model.agent.tenant_agent_config import TenantAgentConfig
from src.domain.ports.agent.context_manager_port import ContextBuildRequest
from src.infrastructure.agent.workspace.runtime_role_contract import (
    WORKSPACE_ROLE_LEADER,
    WORKSPACE_SESSION_ROLE_KEY,
    WORKSPACE_TOOL_MODE_KEY,
    WORKSPACE_TOOL_MODE_TASK_LEDGER_ONLY,
    WORKSPACE_TURN_TYPE_KEY,
    WORKSPACE_TURN_TYPE_LEADER_REPLAN,
)

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
from ..plugins.policy_context import PolicyContext, normalize_policy_layers
from ..plugins.registry import get_plugin_registry
from ..plugins.selection_pipeline import (
    ToolSelectionContext,
    ToolSelectionTraceStep,
    build_default_tool_selection_pipeline,
)
from ..prompts import PromptContext, PromptMode, SystemPromptManager
from ..routing import (
    ExecutionPath,
    IntentGate,
    RoutingDecision,
)
from ..sisyphus.builtin_agent import (
    BUILTIN_SISYPHUS_ID,
    build_builtin_sisyphus_agent,
    get_builtin_agent_by_id,
)
from ..sisyphus.prompt_builder import SisyphusPromptBuilder, SisyphusPromptContext
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
from .tool_name_policy import canonical_tool_policy_names

if TYPE_CHECKING:
    from src.application.services.artifact_service import ArtifactService
    from src.domain.llm_providers.llm_types import LLMClient
    from src.domain.ports.services.graph_service_port import GraphServicePort

logger = logging.getLogger(__name__)
_react_bg_tasks: set[asyncio.Task[Any]] = set()
_MODEL_PROVIDER_ALIASES: dict[str, str] = {
    "azure_openai": "openai",
}
_WORKSPACE_WORKER_CODE_TOOL_NAMES: tuple[str, ...] = (
    "read",
    "write",
    "edit",
    "bash",
    "glob",
    "grep",
)
_WORKSPACE_WORKER_REPORT_TOOL_NAMES: tuple[str, ...] = (
    "workspace_report_progress",
    "workspace_report_complete",
    "workspace_report_blocked",
    "workspace_request_clarification",
    "workspace_health_verdict",
)
_WORKSPACE_LEADER_REPLAN_TOOL_NAMES: tuple[str, ...] = (
    "todoread",
    "todowrite",
)


@dataclass(frozen=True)
class AgentRuntimeProfile:
    """Request-scoped runtime profile derived from selected agent + tenant config."""

    selected_agent: Agent | None
    tenant_agent_config: TenantAgentConfig
    available_skills: list[Skill]
    allow_tools: list[str]
    deny_tools: list[str]
    effective_model: str
    effective_temperature: float
    effective_max_tokens: int
    effective_max_steps: int
    primary_agent_prompt: str | None = None
    agent_definition_prompt: str | None = None


def _normalize_model_provider(provider: str | None) -> str | None:
    """Normalize provider identifiers for cross-surface comparisons."""
    if provider is None:
        return None
    normalized = provider.strip().lower()
    if not normalized:
        return None
    if normalized.endswith("_coding"):
        normalized = normalized.removesuffix("_coding")
    return _MODEL_PROVIDER_ALIASES.get(normalized, normalized)


def _infer_provider_from_model_name(model_name: str | None) -> str | None:
    """Infer provider from explicit `<provider>/<model>` naming."""
    if model_name is None:
        return None
    normalized_model = model_name.strip()
    if not normalized_model or "/" not in normalized_model:
        return None
    provider_part = normalized_model.split("/", 1)[0]
    return _normalize_model_provider(provider_part)


async def _register_selected_agent_session(
    *,
    conversation_id: str,
    project_id: str,
    selected_agent_id: str,
) -> None:
    """Best-effort registration of the resolved agent owning a conversation."""
    try:
        from src.infrastructure.agent.state.agent_worker_state import get_agent_orchestrator

        orchestrator = get_agent_orchestrator()
        if orchestrator is None:
            return
        session_registry = getattr(orchestrator, "_session_registry", None)
        if session_registry is None:
            return
        await session_registry.register(
            agent_id=selected_agent_id,
            conversation_id=conversation_id,
            project_id=project_id,
        )
    except Exception:
        logger.warning(
            "[ReActAgent] Failed to register selected agent session: agent=%s conversation=%s "
            "project=%s",
            selected_agent_id,
            conversation_id,
            project_id,
            exc_info=True,
        )


class ReActAgent:
    _WORKSPACE_ROOT_TOOL_BYPASS_NAMES: ClassVar[frozenset[str]] = frozenset(
        {
            "agent_spawn",
            "agent_send",
            "agent_sessions",
            "agent_history",
            "agent_stop",
            "workspace_chat_send",
        }
    )
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

    def _build_tool_selection_context(
        self,
        *,
        tenant_id: str,
        project_id: str,
        user_message: str,
        conversation_context: list[dict[str, str]],
        effective_mode: str,
        routing_metadata: Mapping[str, Any] | None = None,
        allow_tools: list[str] | None = None,
        deny_tools: list[str] | None = None,
    ) -> ToolSelectionContext:
        """Build selection context for context/intent/semantic/policy pipeline."""
        policy_context = PolicyContext.from_metadata(
            {"policy_layers": dict(self._tool_policy_layers)},
        )
        effective_deny_tools = list(deny_tools or [])
        if effective_mode == "plan":
            effective_deny_tools.extend(["plugin_manager", "skill_installer", "skill_sync"])
        effective_deny_tools = sorted({tool for tool in effective_deny_tools if tool})
        metadata: dict[str, Any] = {
            "user_message": user_message,
            "conversation_history": conversation_context,
            "effective_mode": effective_mode,
            "agent_mode": self.agent_mode,
            "max_tools": self._tool_selection_max_tools,
            "semantic_backend": self._tool_selection_semantic_backend,
            "deny_tools": effective_deny_tools,
            "allow_tools": list(allow_tools or []),
            "policy_agent": (
                {
                    "allow_tools": list(allow_tools or []),
                    "deny_tools": effective_deny_tools,
                }
                if allow_tools or effective_deny_tools
                else {}
            ),
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

        # Intent gate: lightweight pattern-based pre-classification
        gate_result = self._intent_gate.classify(
            message,
            _available_skills=[s.name for s in (self.skills or [])],
        )
        if gate_result is not None:
            if gate_result.metadata is None:
                gate_result.metadata = {}
            gate_result.metadata["domain_lane"] = domain_lane
            gate_result.metadata["router_fabric_version"] = "lane-v1"
            return gate_result

        # Default to ReAct loop -- prompt-driven routing replaces
        # confidence scoring
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

    def _match_skill(
        self,
        query: str,
        available_skills: list[SkillProtocol] | None = None,
    ) -> tuple[SkillProtocol | None, float]:
        """Match query against available skills, filtered by agent_mode.

        Inlined from SkillOrchestrator.match() (Wave 5.1).

        Args:
            query: User query

        Returns:
            Tuple of (best matching skill or None, match score)
        """
        skills = available_skills or cast("list[SkillProtocol]", self.skills or [])
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

    async def _build_system_prompt(  # noqa: PLR0913
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
        heartbeat_prompt: str | None = None,
        agent_definition_prompt: str | None = None,
        primary_agent_prompt: str | None = None,
        available_skills: list[Skill] | None = None,
        model_name: str | None = None,
        max_steps_override: int | None = None,
        workspace_manager: Any | None = None,
        selected_agent_name: str | None = None,
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
        model_provider = SystemPromptManager.detect_model_provider(model_name or self.model)

        # Convert skills to dict format for PromptContext
        skills_data = None
        effective_skills = available_skills if available_skills is not None else self.skills
        if effective_skills:
            skills_data = [
                {
                    "name": s.name,
                    "description": s.description,
                    "tools": s.tools,
                    "status": s.status.value,
                    "prompt_template": s.prompt_template,
                }
                for s in effective_skills
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

        # Load workspace persona as first-class AgentPersona
        persona = None
        active_workspace_manager = workspace_manager or self._workspace_manager
        if active_workspace_manager:
            try:
                persona = await active_workspace_manager.build_persona()
            except Exception as e:
                logger.warning("Failed to load workspace persona: %s", e)

        # Fetch dynamic workspace context (members, agents, messages, blackboard)
        workspace_context: str | None = None
        if project_id and tenant_id:
            from src.infrastructure.agent.workspace.workspace_context_builder import (
                build_workspace_context,
            )

            workspace_context = await build_workspace_context(project_id, tenant_id)

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
            max_steps=max_steps_override or self.max_steps,
            memory_context=memory_context,
            persona=persona,
            heartbeat_prompt=heartbeat_prompt,
            workspace_context=workspace_context,
            workspace_authority_active=bool(
                active_workspace_manager
                and getattr(active_workspace_manager, "root_goal_task_id", None)
            ),
            agent_definition_prompt=agent_definition_prompt,
            primary_agent_prompt=primary_agent_prompt,
            selected_agent_name=selected_agent_name,
        )

        # Use SystemPromptManager to build the prompt
        return cast(
            str,
            await self.prompt_manager.build_system_prompt(
                context=context,
                subagent=subagent,
            ),
        )

    async def _load_selected_agent(
        self,
        *,
        agent_id: str,
        tenant_id: str,
        project_id: str,
    ) -> Agent | None:
        """Load the selected runtime agent from built-ins, orchestrator, or DB."""
        builtin_agent = get_builtin_agent_by_id(
            agent_id,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        if builtin_agent is not None:
            return builtin_agent

        from src.infrastructure.agent.state.agent_worker_state import get_agent_orchestrator

        orchestrator = get_agent_orchestrator()
        if orchestrator is not None:
            try:
                agent_def = await orchestrator.get_agent(agent_id)
                if agent_def is not None:
                    return cast(Agent, agent_def)
            except Exception:
                logger.exception("[ReActAgent] Failed orchestrator lookup for agent %s", agent_id)

        session_factory = self._session_factory
        if session_factory is None:
            logger.debug("[ReActAgent] No session_factory available for agent lookup: %s", agent_id)
            return None

        from src.infrastructure.adapters.secondary.persistence.sql_agent_registry import (
            SqlAgentRegistryRepository,
        )

        session = session_factory()
        try:
            repository = SqlAgentRegistryRepository(session)
            agent_def = await repository.get_by_id(
                agent_id,
                tenant_id=tenant_id,
                project_id=project_id,
            )
            if agent_def is None:
                logger.warning("[ReActAgent] Agent definition not found: %s", agent_id)
            return agent_def
        except Exception:
            logger.exception("[ReActAgent] Failed DB lookup for agent definition: %s", agent_id)
            return None
        finally:
            await session.close()

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

    @staticmethod
    def _with_workspace_worker_tool_allowlist(
        runtime_profile: AgentRuntimeProfile,
    ) -> AgentRuntimeProfile:
        """Ensure workspace workers can inspect/edit/report despite persona allowlists."""

        if not runtime_profile.allow_tools or "*" in runtime_profile.allow_tools:
            return runtime_profile
        required_tools = list(_WORKSPACE_WORKER_REPORT_TOOL_NAMES)
        if not runtime_profile.tenant_agent_config.enabled_tools:
            required_tools.extend(_WORKSPACE_WORKER_CODE_TOOL_NAMES)
        expanded = sorted(
            {
                *canonical_tool_policy_names(runtime_profile.allow_tools),
                *required_tools,
            }
        )
        return replace(runtime_profile, allow_tools=expanded)

    @staticmethod
    def _with_workspace_leader_replan_tool_allowlist(
        runtime_profile: AgentRuntimeProfile,
    ) -> AgentRuntimeProfile:
        """Restrict leader remediation turns to task-ledger inspection and updates."""

        allowed = set(_WORKSPACE_LEADER_REPLAN_TOOL_NAMES)
        return replace(
            runtime_profile,
            allow_tools=sorted(allowed),
            deny_tools=sorted(set(runtime_profile.deny_tools) - allowed),
        )

    def _resolve_effective_model(
        self,
        *,
        selected_agent: Agent | None,
        tenant_agent_config: TenantAgentConfig,
    ) -> str:
        """Resolve the request-scoped base model before per-turn overrides."""
        if selected_agent is not None and selected_agent.model.value != "inherit":
            return selected_agent.model.value
        tenant_model = tenant_agent_config.llm_model.strip()
        if tenant_model and tenant_model.lower() != "default":
            return tenant_model
        return self.model

    def _build_runtime_profile(
        self,
        *,
        tenant_id: str,
        tenant_agent_config_data: dict[str, Any] | None,
        selected_agent: Agent | None,
        is_workspace_worker_runtime: bool = False,
    ) -> AgentRuntimeProfile:
        """Build the request-scoped runtime profile."""
        tenant_agent_config = self._load_tenant_agent_config(tenant_id, tenant_agent_config_data)
        available_skills = self._filter_skills_for_agent(selected_agent)
        allow_tools, deny_tools = self._resolve_tool_policy(
            selected_agent=selected_agent,
            tenant_agent_config=tenant_agent_config,
        )
        effective_model = self._resolve_effective_model(
            selected_agent=selected_agent,
            tenant_agent_config=tenant_agent_config,
        )
        is_builtin_sisyphus = (
            selected_agent is not None and selected_agent.id == BUILTIN_SISYPHUS_ID
        )
        effective_temperature = (
            selected_agent.temperature
            if selected_agent is not None and not is_builtin_sisyphus
            else tenant_agent_config.llm_temperature
        )
        effective_max_tokens = (
            selected_agent.max_tokens
            if selected_agent is not None and not is_builtin_sisyphus
            else self.max_tokens
        )
        effective_max_steps = (
            tenant_agent_config.max_work_plan_steps
            if is_workspace_worker_runtime
            else selected_agent.max_iterations
            if (
                selected_agent is not None
                and not is_builtin_sisyphus
                and selected_agent.has_explicit_max_iterations()
            )
            else tenant_agent_config.max_work_plan_steps
        )
        if (
            selected_agent is not None
            and not is_builtin_sisyphus
            and not selected_agent.has_explicit_max_iterations()
        ):
            logger.info(
                "[ReActAgent] Agent %s uses legacy default max_iterations=%s; "
                "falling back to tenant max_work_plan_steps=%s",
                selected_agent.id,
                selected_agent.max_iterations,
                tenant_agent_config.max_work_plan_steps,
            )
        agent_definition_prompt = (
            selected_agent.system_prompt
            if selected_agent is not None and selected_agent.id != BUILTIN_SISYPHUS_ID
            else None
        )

        return AgentRuntimeProfile(
            selected_agent=selected_agent,
            tenant_agent_config=tenant_agent_config,
            available_skills=available_skills,
            allow_tools=allow_tools,
            deny_tools=deny_tools,
            effective_model=effective_model,
            effective_temperature=effective_temperature,
            effective_max_tokens=effective_max_tokens,
            effective_max_steps=effective_max_steps,
            primary_agent_prompt=None,
            agent_definition_prompt=agent_definition_prompt,
        )

    def _build_primary_agent_prompt(
        self,
        *,
        runtime_profile: AgentRuntimeProfile,
        selection_context: ToolSelectionContext,
    ) -> str | None:
        """Build a dynamic primary prompt when the selected agent is built-in Sisyphus."""
        selected_agent = runtime_profile.selected_agent
        if selected_agent is None or selected_agent.id != BUILTIN_SISYPHUS_ID:
            return None
        _, current_tool_definitions = self._get_current_tools(selection_context=selection_context)
        return self._sisyphus_prompt_builder.build(
            SisyphusPromptContext(
                model_name=runtime_profile.effective_model,
                max_steps=runtime_profile.effective_max_steps,
                tools=current_tool_definitions,
                skills=runtime_profile.available_skills,
                subagents=list(self.subagents or []),
            )
        )

    async def _stream_detect_plan_mode(
        self,
        user_message: str,
        conversation_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Detect plan mode and yield suggestion event if appropriate."""
        suggestion = self._plan_detector.detect(user_message)
        if suggestion.should_suggest:
            yield cast(
                dict[str, Any],
                AgentPlanSuggestedEvent(
                    plan_id="",
                    conversation_id=conversation_id,
                    reason=suggestion.reason,
                    confidence=suggestion.confidence,
                ).to_event_dict(),
            )
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
        available_skills: list[SkillProtocol] | None = None,
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
            for skill in available_skills or cast("list[SkillProtocol]", self.skills or []):
                if skill.name.lower() == name_lower and skill.status.value == "active":
                    found_skill = skill
                    break
            if found_skill is not None:
                matched_skill = found_skill
                skill_score = 1.0
                is_forced = True
                logger.info(f"[ReActAgent] Forced skill found: {found_skill.name}")
            else:
                yield cast(
                    dict[str, Any],
                    AgentThoughtEvent(
                        content=(
                            f"Forced skill '{forced_skill_name}'"
                            f" not found, falling back to"
                            f" normal matching"
                        ),
                    ).to_event_dict(),
                )
                matched_skill, skill_score = self._match_skill(
                    processed_user_message,
                    available_skills=available_skills,
                )
        else:
            matched_skill, skill_score = self._match_skill(
                processed_user_message,
                available_skills=available_skills,
            )

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
            yield cast(
                dict[str, Any],
                AgentSkillMatchedEvent(
                    skill_id=matched_skill.id,
                    skill_name=matched_skill.name,
                    tools=list(matched_skill.tools),
                    match_score=skill_score,
                    execution_mode=execution_mode,
                ).to_event_dict(),
            )

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

    async def _stream_build_context(
        self,
        *,
        system_prompt: str,
        conversation_context: list[dict[str, str]],
        processed_user_message: str,
        attachment_metadata: list[dict[str, Any]] | None,
        attachment_content: list[dict[str, Any]] | None,
        context_summary_data: dict[str, Any] | None,
        tenant_id: str,
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
            yield cast(
                dict[str, Any],
                AgentContextCompressedEvent(**context_result.to_event_data()).to_event_dict(),
            )
            logger.info(
                f"Context compressed: {context_result.original_message_count} -> "
                f"{context_result.final_message_count} messages, "
                f"strategy: {context_result.compression_strategy.value}"
            )

            if context_result.summary and not cached_summary:
                yield cast(
                    dict[str, Any],
                    AgentContextSummaryGeneratedEvent(
                        summary_text=context_result.summary,
                        summary_tokens=(context_result.estimated_tokens),
                        messages_covered_count=(context_result.summarized_message_count),
                        compression_level=(context_result.compression_strategy.value),
                    ).to_event_dict(),
                )

            hook_events = await self._notify_context_overflow_hook(
                tenant_id=tenant_id,
                project_id=project_id,
                conversation_id=conversation_id,
                conversation_context=conversation_context,
                context_result=context_result,
            )
            for event in hook_events:
                yield event

        # Emit initial context_status
        compression_level = context_result.metadata.get("compression_level", "none")
        yield cast(
            dict[str, Any],
            AgentContextStatusEvent(
                current_tokens=(context_result.estimated_tokens),
                token_budget=context_result.token_budget,
                occupancy_pct=round(
                    context_result.budget_utilization_pct,
                    1,
                ),
                compression_level=compression_level,
                token_distribution={},
                compression_history_summary=(
                    context_result.metadata.get("compression_history", {})
                ),
                from_cache=cached_summary is not None,
                messages_in_summary=(
                    cached_summary.messages_covered_count if cached_summary else 0
                ),
            ).to_event_dict(),
        )

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
            yield cast(
                dict[str, Any],
                AgentSelectionTraceEvent(
                    route_id=route_id,
                    trace_id=trace_id,
                    initial_count=cast(int, trace_data[0]["before_count"]),
                    final_count=cast(int, trace_data[-1]["after_count"]),
                    removed_total=removed_total,
                    domain_lane=(selection_context.metadata.get("domain_lane")),
                    tool_budget=tool_budget,
                    budget_exceeded_stages=[str(s) for s in budget_exceeded_stages],
                    stages=trace_data,
                ).to_event_dict(),
            )
            if removed_total > 0:
                yield cast(
                    dict[str, Any],
                    AgentPolicyFilteredEvent(
                        route_id=route_id,
                        trace_id=trace_id,
                        removed_total=removed_total,
                        stage_count=len(trace_data),
                        domain_lane=(selection_context.metadata.get("domain_lane")),
                        tool_budget=tool_budget,
                        budget_exceeded_stages=[str(s) for s in budget_exceeded_stages],
                    ).to_event_dict(),
                )
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

    @classmethod
    def _filter_workspace_root_tools(
        cls,
        tools_to_use: list[ToolDefinition],
        workspace_root_task: Any | None,
    ) -> list[ToolDefinition]:
        if workspace_root_task is None:
            return tools_to_use
        return [
            tool for tool in tools_to_use if tool.name not in cls._WORKSPACE_ROOT_TOOL_BYPASS_NAMES
        ]

    @staticmethod
    def _filter_tools_by_name_policy(
        tools_to_use: list[ToolDefinition],
        *,
        allow_tools: Sequence[str] | None,
        deny_tools: Sequence[str] | None,
    ) -> list[ToolDefinition]:
        """Apply final hard allow/deny filtering to the executable tool list."""
        known_tool_names = [tool.name for tool in tools_to_use]
        raw_allow: set[str] = set(canonical_tool_policy_names(allow_tools, known_tool_names))
        allow: set[str] = set() if "*" in raw_allow else raw_allow
        deny: set[str] = set(canonical_tool_policy_names(deny_tools, known_tool_names))
        if not allow and not deny:
            return tools_to_use
        return [
            tool
            for tool in tools_to_use
            if (not allow or tool.name in allow) and tool.name not in deny
        ]

    @staticmethod
    def _workspace_runtime_context(
        conversation_context: Sequence[Mapping[str, Any]],
    ) -> Mapping[str, Any] | None:
        """Return hidden workspace worker app context injected as system metadata."""
        for message in conversation_context:
            if message.get("role") != "system":
                continue
            content = message.get("content")
            if not isinstance(content, str) or "workspace_worker_runtime" not in content:
                continue
            json_start = content.find("{")
            if json_start < 0:
                continue
            try:
                payload = json.loads(content[json_start:])
            except json.JSONDecodeError:
                logger.warning(
                    "[ReActAgent] Failed to parse workspace runtime app context",
                    exc_info=True,
                )
                continue
            if (
                isinstance(payload, Mapping)
                and payload.get("context_type") == "workspace_worker_runtime"
            ):
                return payload
        return None

    @staticmethod
    def _is_workspace_leader_replan_context(payload: Mapping[str, Any] | None) -> bool:
        """Detect task-ledger-only leader remediation turns from structured app context."""

        if not isinstance(payload, Mapping):
            return False
        return (
            payload.get(WORKSPACE_TURN_TYPE_KEY) == WORKSPACE_TURN_TYPE_LEADER_REPLAN
            or payload.get(WORKSPACE_TOOL_MODE_KEY) == WORKSPACE_TOOL_MODE_TASK_LEDGER_ONLY
        )

    @classmethod
    def _has_workspace_runtime_context(cls, conversation_context: Sequence[Mapping[str, Any]]) -> bool:
        """Detect hidden workspace worker app context injected as system metadata."""
        return cls._workspace_runtime_context(conversation_context) is not None

    @staticmethod
    def _normalize_workspace_binding(raw: Mapping[str, Any] | None) -> dict[str, str] | None:
        if not isinstance(raw, Mapping):
            return None
        binding = {
            str(key): str(value).strip()
            for key, value in raw.items()
            if isinstance(key, str) and value is not None and str(value).strip()
        }
        if not binding.get("workspace_id"):
            return None
        return binding

    @classmethod
    def _workspace_binding_from_context(
        cls,
        conversation_context: Sequence[Mapping[str, Any]],
    ) -> dict[str, str] | None:
        payload = cls._workspace_runtime_context(conversation_context)
        raw_binding = payload.get("workspace_binding") if isinstance(payload, Mapping) else None
        return cls._normalize_workspace_binding(raw_binding)

    @classmethod
    def _workspace_binding_from_text(cls, text: str | None) -> dict[str, str] | None:
        """Parse the structural workspace binding block from worker task briefs."""
        if not isinstance(text, str) or "[workspace-task-binding]" not in text:
            return None
        in_block = False
        raw: dict[str, str] = {}
        for line in text.splitlines():
            stripped = line.strip()
            if stripped == "[workspace-task-binding]":
                in_block = True
                continue
            if stripped == "[/workspace-task-binding]":
                break
            if not in_block or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            key = key.strip()
            value = value.strip()
            if key and value:
                raw[key] = value
        return cls._normalize_workspace_binding(raw)

    def _stream_inject_subagent_tools(  # noqa: PLR0915
        self,
        tools_to_use: list[ToolDefinition],
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
        conversation_id: str,
        abort_signal: asyncio.Event | None,
        workspace_root_task: Any | None = None,
        leader_agent_id: str | None = None,
        actor_user_id: str | None = None,
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

        async def _prepare_workspace_delegation(
            *,
            subagent_name: str,
            subagent_id: str,
            task: str,
            workspace_task_id: str | None = None,
        ) -> dict[str, str] | None:
            if workspace_root_task is None or not actor_user_id:
                return None
            from src.infrastructure.agent.workspace.orchestrator import (
                WorkspaceAutonomyOrchestrator,
            )

            return await WorkspaceAutonomyOrchestrator().prepare_subagent_delegation(
                workspace_id=getattr(workspace_root_task, "workspace_id", project_id),
                root_goal_task_id=getattr(workspace_root_task, "id", ""),
                actor_user_id=actor_user_id,
                delegated_task_text=task,
                subagent_name=subagent_name,
                subagent_id=subagent_id,
                leader_agent_id=leader_agent_id,
                workspace_task_id=workspace_task_id,
            )

        def _decorate_workspace_delegate_task(
            task: str,
            task_binding: dict[str, str] | None,
        ) -> str:
            if not task_binding:
                return task
            return (
                "[workspace-task-binding]\n"
                f"workspace_task_id={task_binding['workspace_task_id']}\n"
                f"attempt_id={task_binding.get('attempt_id', '')}\n"
                f"workspace_agent_binding_id={task_binding.get('workspace_agent_binding_id', '')}\n"
                f"root_goal_task_id={task_binding['root_goal_task_id']}\n"
                f"workspace_id={task_binding['workspace_id']}\n"
                "[/workspace-task-binding]\n\n"
                f"{task}"
            )

        async def _finalize_workspace_delegation(
            *,
            task_binding: dict[str, str] | None,
            report_type: str,
            summary: str,
            artifacts: list[str] | None = None,
        ) -> Any:
            if not task_binding or not actor_user_id:
                return None
            from src.infrastructure.agent.workspace.orchestrator import (
                WorkspaceAutonomyOrchestrator,
            )

            return await WorkspaceAutonomyOrchestrator().apply_worker_report(
                workspace_id=task_binding["workspace_id"],
                root_goal_task_id=task_binding["root_goal_task_id"],
                task_id=task_binding["workspace_task_id"],
                attempt_id=task_binding.get("attempt_id"),
                actor_user_id=actor_user_id,
                worker_agent_id=None,
                report_type=report_type,
                summary=summary,
                artifacts=artifacts,
                leader_agent_id=leader_agent_id,
            )

        def _format_workspace_delegate_result(
            *,
            subagent_name: str,
            task_binding: dict[str, str] | None,
            report_type: str,
            summary: str,
            tokens: int | None = None,
        ) -> str:
            if not task_binding:
                return summary

            lines = [
                f"[SubAgent '{subagent_name}' completed]",
                f"Candidate worker report stored for workspace_task_id={task_binding['workspace_task_id']}",
                f"Suggested report_type={report_type}",
                "Leader adjudication required: review the worker evidence, then use todoread/todowrite to decide whether this task should become completed, failed, remain in_progress, or be replanned.",
                f"Result: {summary}",
            ]
            if isinstance(tokens, int):
                lines.append(f"Tokens used: {tokens}")
            return "\n".join(lines)

        # Create delegation callback that captures stream-scoped context
        async def _delegate_callback(
            subagent_name: str,
            task: str,
            workspace_task_id: str | None = None,
            on_event: Callable[[dict[str, Any]], None] | None = None,
        ) -> str:
            target = subagent_map.get(subagent_name)
            if not target:
                return f"SubAgent '{subagent_name}' not found"

            task_binding = await _prepare_workspace_delegation(
                subagent_name=subagent_name,
                subagent_id=target.id,
                task=task,
                workspace_task_id=workspace_task_id,
            )
            delegated_task = _decorate_workspace_delegate_task(task, task_binding)
            events = []
            async for evt in self._execute_subagent(
                subagent=target,
                user_message=delegated_task,
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
                    report_type = "completed" if sa_result.get("success", True) else "blocked"
                    summary = sa_result.get("summary", content)
                    result_summary = summary or content or f"SubAgent {subagent_name} finished"
                    tokens = sa_result.get("tokens_used", 0)
                    await _finalize_workspace_delegation(
                        task_binding=task_binding,
                        report_type=report_type,
                        summary=result_summary,
                    )
                    return _format_workspace_delegate_result(
                        subagent_name=subagent_name,
                        task_binding=task_binding,
                        report_type=report_type,
                        summary=result_summary,
                        tokens=tokens,
                    )
                await _finalize_workspace_delegation(
                    task_binding=task_binding,
                    report_type="completed",
                    summary=content or f"SubAgent {subagent_name} completed",
                )
                return _format_workspace_delegate_result(
                    subagent_name=subagent_name,
                    task_binding=task_binding,
                    report_type="completed",
                    summary=content or "SubAgent completed with no output",
                )

            await _finalize_workspace_delegation(
                task_binding=task_binding,
                report_type="blocked",
                summary=f"SubAgent {subagent_name} execution completed but no result returned",
            )
            return _format_workspace_delegate_result(
                subagent_name=subagent_name,
                task_binding=task_binding,
                report_type="blocked",
                summary="SubAgent execution completed but no result returned",
            )

        async def _spawn_callback(
            subagent_name: str,
            task: str,
            run_id: str,
            **spawn_options: Any,
        ) -> str:
            target = subagent_map.get(subagent_name)
            if not target:
                raise ValueError(f"SubAgent '{subagent_name}' not found")
            task_binding = await _prepare_workspace_delegation(
                subagent_name=subagent_name,
                subagent_id=target.id,
                task=task,
                workspace_task_id=(
                    str(spawn_options.get("workspace_task_id") or "").strip() or None
                ),
            )
            delegated_task = _decorate_workspace_delegate_task(task, task_binding)
            await self._launch_subagent_session(
                run_id=run_id,
                subagent=target,
                user_message=delegated_task,
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
                run_metadata=task_binding,
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
        """Create request-scoped processor config, optionally with dynamic tool provider."""

        tool_provider: Callable[[], list[ToolDefinition]] | None = config.tool_provider
        if self._use_dynamic_tools and self._tool_provider is not None:

            def _tool_provider_wrapper() -> list[ToolDefinition]:
                _, tool_defs = self._get_current_tools(selection_context=selection_context)
                return list(tool_defs)

            tool_provider = _tool_provider_wrapper

        new_config = ProcessorConfig(
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            max_steps=config.max_steps,
            max_tool_calls_per_step=config.max_tool_calls_per_step,
            enable_parallel_tool_execution=config.enable_parallel_tool_execution,
            parallel_tool_batch_size=config.parallel_tool_batch_size,
            doom_loop_threshold=config.doom_loop_threshold,
            max_no_progress_steps=config.max_no_progress_steps,
            max_attempts=config.max_attempts,
            initial_delay_ms=config.initial_delay_ms,
            permission_timeout=config.permission_timeout,
            continue_on_deny=config.continue_on_deny,
            context_limit=config.context_limit,
            max_cost_per_request=config.max_cost_per_request,
            max_cost_per_session=config.max_cost_per_session,
            llm_client=config.llm_client,
            plugin_registry=config.plugin_registry,
            runtime_hook_overrides=[dict(item) for item in config.runtime_hook_overrides],
            runtime_context=dict(config.runtime_context),
            tool_provider=tool_provider,
            forced_skill_name=config.forced_skill_name,
            forced_skill_tools=(
                list(config.forced_skill_tools) if config.forced_skill_tools else None
            ),
            skill_names=list(config.skill_names),
            provider_options=dict(config.provider_options),
            message_bus=config.message_bus,
            control_channel=config.control_channel,
            run_id=config.run_id,
        )
        if tool_provider is not None:
            logger.debug(
                "[ReActAgent] Created processor config with tool_provider for dynamic tools"
            )
        return new_config

    async def _stream_process_events(
        self,
        processor: SessionProcessor,
        messages: list[dict[str, Any]],
        langfuse_context: dict[str, Any],
        abort_signal: asyncio.Event | None,
        matched_skill: Skill | None,
        agent_id: str | None = None,
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
                agent_id=agent_id,
            )
            async for domain_event in processor.process(
                session_id=langfuse_context["conversation_id"],
                messages=messages,
                run_ctx=run_ctx,
            ):
                event = self._convert_domain_event(domain_event, agent_id=agent_id)
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
            yield cast(
                dict[str, Any],
                AgentErrorEvent(
                    message=str(e),
                    code=type(e).__name__,
                ).to_event_dict(),
            )

    async def _stream_post_process(
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
    ) -> AsyncIterator[dict[str, Any]]:
        """Post-process: memory capture, conversation indexing, final complete event."""
        hook_events = await self._notify_after_turn_complete_hook(
            processed_user_message=processed_user_message,
            final_content=final_content,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            conversation_context=conversation_context,
            matched_skill=matched_skill,
            success=success,
            execution_time_ms=execution_time_ms,
            tool_call_count=tool_call_count,
            llm_client_override=llm_client_override,
        )
        for event in hook_events:
            yield event

        # Yield final complete event
        yield cast(
            dict[str, Any],
            AgentCompleteEvent(
                content=final_content,
                skill_used=(matched_skill.name if matched_skill else None),
            ).to_event_dict(),
        )

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
        allow_tools: list[str] | None = None,
        deny_tools: list[str] | None = None,
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
            allow_tools=allow_tools,
            deny_tools=deny_tools,
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

    async def stream(  # noqa: PLR0913, PLR0912, PLR0915
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
        llm_overrides: dict[str, Any] | None = None,
        model_override: str | None = None,
        agent_id: str | None = None,
        tenant_agent_config_data: dict[str, Any] | None = None,
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
        self._reset_stream_state()
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

        # Phase 4b: Filesystem skill loading (lazy, once per agent instance)
        await self._load_filesystem_skills(tenant_id, project_id)

        resolved_agent_id = agent_id or BUILTIN_SISYPHUS_ID
        selected_agent = await self._load_selected_agent(
            agent_id=resolved_agent_id,
            tenant_id=tenant_id,
            project_id=project_id,
        )
        if selected_agent is None:
            logger.warning(
                "[ReActAgent] Falling back to built-in Sisyphus for missing agent %s",
                resolved_agent_id,
            )
            selected_agent = build_builtin_sisyphus_agent(
                tenant_id=tenant_id,
                project_id=project_id,
            )
        await _register_selected_agent_session(
            conversation_id=conversation_id,
            project_id=project_id,
            selected_agent_id=selected_agent.id,
        )
        has_workspace_binding = False
        workspace_runtime_payload = self._workspace_runtime_context(conversation_context)
        workspace_replan_turn = self._is_workspace_leader_replan_context(workspace_runtime_payload)
        workspace_binding = (
            self._normalize_workspace_binding(
                workspace_runtime_payload.get("workspace_binding")
                if isinstance(workspace_runtime_payload, Mapping)
                else None
            )
            or self._workspace_binding_from_text(processed_user_message)
        )
        if project_id and tenant_id and user_id:
            from src.infrastructure.agent.workspace.orchestrator import (
                WorkspaceAutonomyOrchestrator,
            )

            orchestrator = WorkspaceAutonomyOrchestrator()
            has_workspace_binding = workspace_binding is not None
            if orchestrator.should_activate(
                processed_user_message,
                has_workspace_binding=has_workspace_binding,
            ):
                if workspace_binding is not None:
                    workspace_root_task = SimpleNamespace(
                        id=workspace_binding.get("root_goal_task_id")
                        or workspace_binding.get("workspace_task_id")
                        or "",
                        workspace_id=workspace_binding["workspace_id"],
                    )
                else:
                    workspace_root_task = await orchestrator.materialize_goal_candidate(
                        project_id,
                        tenant_id,
                        user_id,
                        leader_agent_id=selected_agent.id,
                        user_query=processed_user_message,
                    )
            else:
                workspace_root_task = None
        else:
            workspace_root_task = None
        runtime_profile = self._build_runtime_profile(
            tenant_id=tenant_id,
            tenant_agent_config_data=tenant_agent_config_data,
            selected_agent=selected_agent,
            is_workspace_worker_runtime=has_workspace_binding,
        )
        if workspace_replan_turn:
            runtime_profile = self._with_workspace_leader_replan_tool_allowlist(runtime_profile)
        elif has_workspace_binding:
            runtime_profile = self._with_workspace_worker_tool_allowlist(runtime_profile)
        self.config.runtime_hook_overrides = [
            runtime_hook.to_dict()
            for runtime_hook in runtime_profile.tenant_agent_config.runtime_hooks
        ]
        runtime_workspace_manager = self._build_runtime_workspace_manager(selected_agent)

        # Phase 5: Skill matching
        if workspace_root_task is not None and not forced_skill_name:
            self._stream_skill_state = {
                "matched_skill": None,
                "is_forced": False,
                "should_inject_prompt": False,
            }
            logger.info(
                "[ReActAgent] Skipping non-forced skill matching because workspace authority is active "
                "for conversation %s",
                conversation_id,
            )
        else:
            for event in self._stream_match_skill(
                processed_user_message,
                forced_skill_name,
                available_skills=cast("list[SkillProtocol]", runtime_profile.available_skills),
            ):
                yield event
        skill_state = self._stream_skill_state
        matched_skill: Skill | None = cast("Skill | None", skill_state["matched_skill"])
        is_forced: bool = cast(bool, skill_state["is_forced"])
        should_inject_prompt: bool = cast(bool, skill_state["should_inject_prompt"])

        # Phase 5b: Sync skill resources
        if should_inject_prompt and matched_skill:
            await self._stream_sync_skill_resources(matched_skill)

        # Phase 5c: Activate skill-embedded MCP servers
        self._skill_mcp_tools = []
        if matched_skill and matched_skill.metadata:
            mcp_servers_raw = matched_skill.metadata.get("mcp_servers")
            if mcp_servers_raw and isinstance(mcp_servers_raw, list):
                from ..mcp.skill_mcp_manager import SkillMCPConfig

                mcp_configs = [
                    SkillMCPConfig(
                        server_name=cfg["server_name"],
                        command=cfg["command"],
                        args=cfg.get("args", []),
                        env=cfg.get("env", {}),
                        auto_start=cfg.get("auto_start", True),
                    )
                    for cfg in mcp_servers_raw
                    if isinstance(cfg, dict) and "server_name" in cfg and "command" in cfg
                ]
                if mcp_configs:
                    try:
                        self._skill_mcp_manager.register_skill_mcps(matched_skill.name, mcp_configs)
                        mcp_tools = await self._skill_mcp_manager.activate_skill(matched_skill.name)
                        # Convert MCPTool objects to ToolDefinition for injection
                        for mcp_tool in mcp_tools:
                            if not mcp_tool.schema.is_model_visible:
                                continue
                            client = self._skill_mcp_manager.get_active_client(mcp_tool.server_name)

                            async def _make_mcp_exec(
                                _client: Any,
                                _tool_name: str,
                            ) -> Any:
                                async def _exec(**kwargs: Any) -> Any:
                                    if _client is None:
                                        return f"MCP server not available for tool {_tool_name}"
                                    result = await _client.call_tool(_tool_name, kwargs)
                                    if isinstance(result, dict):
                                        return result.get("content", str(result))
                                    return result

                                return _exec

                            td = ToolDefinition(
                                name=mcp_tool.schema.name,
                                description=(
                                    mcp_tool.schema.description
                                    or f"MCP tool: {mcp_tool.schema.name}"
                                ),
                                parameters=(
                                    mcp_tool.schema.input_schema
                                    or {
                                        "type": "object",
                                        "properties": {},
                                    }
                                ),
                                execute=await _make_mcp_exec(client, mcp_tool.schema.name),
                            )
                            self._skill_mcp_tools.append(td)
                        if self._skill_mcp_tools:
                            logger.info(
                                "[ReActAgent] Activated %d MCP tool(s) for skill '%s': %s",
                                len(self._skill_mcp_tools),
                                matched_skill.name,
                                [t.name for t in self._skill_mcp_tools],
                            )
                    except Exception:
                        logger.exception(
                            "[ReActAgent] Failed to activate MCP servers for skill '%s'",
                            matched_skill.name,
                        )

        # Phase 6: Mode/selection context setup
        effective_mode, selection_context = self._stream_resolve_mode(
            plan_mode=plan_mode,
            routing_decision=routing_decision,
            routing_metadata=routing_metadata,
            tenant_id=tenant_id,
            project_id=project_id,
            processed_user_message=processed_user_message,
            conversation_context=conversation_context,
            allow_tools=runtime_profile.allow_tools,
            deny_tools=runtime_profile.deny_tools,
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

        # Phase 7: Memory runtime prompt augmentation
        memory_context, hook_events = await self._apply_before_prompt_build_hook(
            processed_user_message=processed_user_message,
            conversation_context=conversation_context,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            effective_mode=effective_mode,
            matched_skill=matched_skill if should_inject_prompt else None,
            selected_agent=selected_agent,
        )
        for event in hook_events:
            yield event

        # Phase 7b: Heartbeat check
        heartbeat_prompt: str | None = None
        if self._heartbeat_runner and self._heartbeat_runner.check_due():
            hb_result = await self._heartbeat_runner.run_once()
            if hb_result.should_run:
                heartbeat_prompt = hb_result.prompt
                logger.info("[ReActAgent] Heartbeat due, injecting heartbeat prompt into context")

        # Phase 7c: Selected agent prompt resolution
        primary_agent_prompt = self._build_primary_agent_prompt(
            runtime_profile=runtime_profile,
            selection_context=selection_context,
        )

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
            heartbeat_prompt=heartbeat_prompt,
            agent_definition_prompt=runtime_profile.agent_definition_prompt,
            primary_agent_prompt=primary_agent_prompt,
            available_skills=runtime_profile.available_skills,
            model_name=(model_override or runtime_profile.effective_model),
            max_steps_override=runtime_profile.effective_max_steps,
            workspace_manager=runtime_workspace_manager,
            selected_agent_name=selected_agent.name,
        )

        # Phase 9: Context building
        async for event in self._stream_build_context(
            system_prompt=system_prompt,
            conversation_context=conversation_context,
            processed_user_message=processed_user_message,
            attachment_metadata=attachment_metadata,
            attachment_content=attachment_content,
            context_summary_data=context_summary_data,
            tenant_id=tenant_id,
            project_id=project_id,
            conversation_id=conversation_id,
        ):
            yield event
        messages = self._stream_messages

        # Phase 10: Tool preparation
        for event in self._stream_prepare_tools(selection_context, is_forced, matched_skill):
            yield event
        tools_to_use = self._filter_workspace_root_tools(
            self._stream_tools_to_use,
            workspace_root_task,
        )

        # Phase 10b: Inject skill-embedded MCP tools
        if self._skill_mcp_tools:
            existing_names = {t.name for t in tools_to_use}
            for mcp_td in self._skill_mcp_tools:
                if mcp_td.name not in existing_names:
                    tools_to_use.append(mcp_td)
            logger.info(
                "[ReActAgent] Injected %d skill MCP tool(s) into tool set",
                len(self._skill_mcp_tools),
            )

        # Phase 11: SubAgent-as-Tool injection
        tools_to_use = self._stream_inject_subagent_tools(
            tools_to_use=tools_to_use,
            conversation_context=conversation_context,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            abort_signal=abort_signal,
            workspace_root_task=workspace_root_task,
            leader_agent_id=selected_agent.id,
            actor_user_id=user_id,
        )
        tools_to_use = self._filter_tools_by_name_policy(
            tools_to_use,
            allow_tools=runtime_profile.allow_tools,
            deny_tools=runtime_profile.deny_tools,
        )

        # Phase 12: Processor creation
        config = self._stream_create_processor_config(self.config, selection_context)
        config.model = runtime_profile.effective_model
        config.temperature = runtime_profile.effective_temperature
        config.max_tokens = runtime_profile.effective_max_tokens
        config.max_steps = runtime_profile.effective_max_steps
        config.skill_names = [skill.name for skill in runtime_profile.available_skills]
        config.runtime_context = {
            **dict(config.runtime_context),
            "selected_agent_id": selected_agent.id,
            "selected_agent_name": selected_agent.name,
            "allowed_skills": list(selected_agent.allowed_skills)
            if selected_agent.allowed_skills
            else [],
            "allowed_tools": list(runtime_profile.allow_tools),
            "denied_tools": list(runtime_profile.deny_tools),
            "route_id": selection_context.metadata.get("route_id"),
            "trace_id": selection_context.metadata.get("trace_id"),
        }
        if workspace_root_task is not None:
            from src.infrastructure.agent.workspace.runtime_role_contract import (
                derive_workspace_session_role,
            )

            workspace_session_role = derive_workspace_session_role(
                has_workspace_binding=has_workspace_binding
            )
            if workspace_replan_turn:
                workspace_session_role = WORKSPACE_ROLE_LEADER
            elif isinstance(workspace_runtime_payload, Mapping):
                runtime_role = workspace_runtime_payload.get(WORKSPACE_SESSION_ROLE_KEY)
                if isinstance(runtime_role, str) and runtime_role.strip():
                    workspace_session_role = runtime_role.strip()

            workspace_runtime_context = {
                "workspace_id": getattr(workspace_root_task, "workspace_id", project_id),
                "root_goal_task_id": getattr(workspace_root_task, "id", ""),
                "task_authority": "workspace",
                WORKSPACE_SESSION_ROLE_KEY: workspace_session_role,
            }
            if isinstance(workspace_runtime_payload, Mapping):
                for key in (WORKSPACE_TURN_TYPE_KEY, WORKSPACE_TOOL_MODE_KEY):
                    value = workspace_runtime_payload.get(key)
                    if isinstance(value, str) and value.strip():
                        workspace_runtime_context[key] = value.strip()
            if workspace_binding is not None:
                for key in ("workspace_task_id", "attempt_id", "leader_agent_id"):
                    value = workspace_binding.get(key)
                    if value:
                        workspace_runtime_context[key] = value
            config.runtime_context = {
                **dict(config.runtime_context),
                **workspace_runtime_context,
            }
        # Set session_id for announce message polling (P0.5)
        config.session_id = conversation_id
        # Pass forced skill context to processor for loop reinforcement (Fix 4)
        if is_forced and matched_skill:
            config.forced_skill_name = matched_skill.name
            config.forced_skill_tools = list(matched_skill.tools) if matched_skill.tools else None

        # Apply per-request model override before LLM parameter overrides.
        normalized_model_override = (model_override or "").strip() or None
        if normalized_model_override:
            from src.infrastructure.llm.model_catalog import get_model_catalog_service
            from src.infrastructure.llm.provider_factory import get_ai_service_factory
            from src.infrastructure.llm.reasoning_config import build_reasoning_config

            catalog = get_model_catalog_service()
            override_meta = catalog.get_model_fuzzy(normalized_model_override)
            current_meta = catalog.get_model_fuzzy(config.model)
            current_provider = _normalize_model_provider(
                current_meta.provider if current_meta is not None else None
            )
            override_provider = _normalize_model_provider(
                override_meta.provider if override_meta is not None else None
            )

            if current_provider is None:
                current_provider = _infer_provider_from_model_name(config.model)
            if override_provider is None:
                override_provider = _infer_provider_from_model_name(normalized_model_override)

            resolved_provider_config: Any | None = None
            resolved_provider: str | None = None
            if tenant_id:
                from src.domain.llm_providers.models import NoActiveProviderError, OperationType

                factory = get_ai_service_factory()
                try:
                    resolved_provider_config = await factory.resolve_provider(
                        tenant_id=tenant_id,
                        operation_type=OperationType.LLM,
                        model_id=normalized_model_override,
                    )
                except NoActiveProviderError:
                    logger.warning(
                        "[ReActAgent] Unable to resolve provider for model override '%s' (tenant=%s)",
                        normalized_model_override,
                        tenant_id,
                    )

                if resolved_provider_config is not None:
                    provider_type_raw = getattr(
                        resolved_provider_config.provider_type,
                        "value",
                        resolved_provider_config.provider_type,
                    )
                    resolved_provider = _normalize_model_provider(str(provider_type_raw))

            if tenant_id:
                # With tenant-scoped providers, fail closed unless resolution succeeds.
                should_apply_override = (
                    resolved_provider_config is not None
                    and resolved_provider_config.is_model_allowed(normalized_model_override)
                )
            elif resolved_provider_config is not None:
                should_apply_override = resolved_provider_config.is_model_allowed(
                    normalized_model_override
                )
            else:
                should_apply_override = override_meta is not None
                if should_apply_override:
                    if current_provider is None or override_provider is None:
                        should_apply_override = False
                    else:
                        should_apply_override = current_provider == override_provider

            if not should_apply_override:
                logger.warning(
                    "[ReActAgent] Ignoring invalid or cross-provider model override '%s' "
                    "(current model: '%s', current provider: '%s', override provider: '%s')",
                    normalized_model_override,
                    config.model,
                    current_provider,
                    override_provider,
                )
                yield {
                    "type": "model_override_rejected",
                    "data": {
                        "model": normalized_model_override,
                        "reason": (
                            f"Cross-provider switch not allowed: override provider "
                            f"'{override_provider}' != current '{current_provider}'"
                        ),
                        "current_model": config.model,
                        "current_provider": current_provider,
                    },
                }
            else:
                if resolved_provider_config is not None:
                    current_client_provider = getattr(config.llm_client, "provider_config", None)
                    current_provider_config_id = getattr(current_client_provider, "id", None)
                    resolved_provider_config_id = getattr(resolved_provider_config, "id", None)
                    should_refresh_llm_client = (
                        current_provider_config_id is None
                        or resolved_provider_config_id is None
                        or current_provider_config_id != resolved_provider_config_id
                    )
                    if should_refresh_llm_client:
                        resolved_provider_label = resolved_provider or _normalize_model_provider(
                            str(
                                getattr(
                                    resolved_provider_config.provider_type,
                                    "value",
                                    resolved_provider_config.provider_type,
                                )
                            )
                        )
                        config.base_url = resolved_provider_config.base_url
                        config.llm_client = get_ai_service_factory().create_llm_client(
                            resolved_provider_config
                        )
                        logger.info(
                            "[ReActAgent] Switched runtime provider for model override '%s': %s -> %s",
                            normalized_model_override,
                            current_provider,
                            resolved_provider_label,
                        )

                config.model = normalized_model_override
                provider_options = dict(config.provider_options)
                for key in (
                    "reasoning_effort",
                    "thinking",
                    "reasoning_split",
                    "__omit_temperature",
                    "__use_max_completion_tokens",
                    "__override_max_tokens",
                ):
                    provider_options.pop(key, None)

                reasoning_cfg = build_reasoning_config(normalized_model_override)
                if reasoning_cfg:
                    provider_options.update(reasoning_cfg.provider_options)
                    provider_options["__omit_temperature"] = reasoning_cfg.omit_temperature
                    provider_options["__use_max_completion_tokens"] = (
                        reasoning_cfg.use_max_completion_tokens
                    )
                    provider_options["__override_max_tokens"] = reasoning_cfg.override_max_tokens
                config.provider_options = provider_options

        # Apply per-request LLM overrides (F1.4)
        if llm_overrides:

            def _to_float(value: Any) -> float | None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None

            def _to_int(value: Any) -> int | None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None

            if "temperature" in llm_overrides:
                parsed = _to_float(llm_overrides["temperature"])
                if parsed is not None:
                    config.temperature = parsed
            if "max_tokens" in llm_overrides:
                parsed = _to_int(llm_overrides["max_tokens"])
                if parsed is not None:
                    config.max_tokens = parsed
            if "top_p" in llm_overrides:
                parsed = _to_float(llm_overrides["top_p"])
                if parsed is not None:
                    config.provider_options["top_p"] = parsed
            if "frequency_penalty" in llm_overrides:
                parsed = _to_float(llm_overrides["frequency_penalty"])
                if parsed is not None:
                    config.provider_options["frequency_penalty"] = parsed
            if "presence_penalty" in llm_overrides:
                parsed = _to_float(llm_overrides["presence_penalty"])
                if parsed is not None:
                    config.provider_options["presence_penalty"] = parsed

        if workspace_replan_turn:
            config.provider_options["tool_choice"] = "required"
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
            "sandbox_id": self._extract_sandbox_id_from_tools(),
            "agent_name": selected_agent.name,
        }

        # Phase 13: Event processing
        async for event in self._stream_process_events(
            processor=processor,
            messages=messages,
            langfuse_context=langfuse_context,
            abort_signal=abort_signal,
            matched_skill=matched_skill,
            agent_id=agent_id,
        ):
            yield event

        # Phase 13b: Heartbeat reply processing
        if self._heartbeat_runner and heartbeat_prompt:
            hb_reply = self._heartbeat_runner.process_reply(self._stream_final_content)
            if hb_reply.should_suppress:
                logger.debug("[ReActAgent] Heartbeat reply acknowledged (HEARTBEAT_OK)")
            elif hb_reply.did_strip:
                self._stream_final_content = hb_reply.cleaned_text

        # Phase 14: Post-processing
        # Calculate execution time before post-process (post-process is
        # lightweight — just hook delivery — so this is accurate enough).
        execution_time_ms = int((time.time() - start_time) * 1000)
        # Count tool calls from conversation context for skill evolution capture.
        tool_call_count = sum(
            1 for msg in conversation_context
            if msg.get("role") in ("tool", "function")
        )
        async for event in self._stream_post_process(
            processed_user_message=processed_user_message,
            final_content=self._stream_final_content,
            project_id=project_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            conversation_context=conversation_context,
            matched_skill=matched_skill,
            success=self._stream_success,
            execution_time_ms=execution_time_ms,
            tool_call_count=tool_call_count,
            llm_client_override=config.llm_client if normalized_model_override else None,
        ):
            yield event

        # Finally: Record execution statistics
        end_time = time.time()
        execution_time_ms = int((end_time - start_time) * 1000)
        logger.debug(f"[ReActAgent] Stream finished in {execution_time_ms}ms")
        self._stream_record_skill_usage(matched_skill, self._stream_success)

        # Cleanup: Deactivate skill MCP servers
        if matched_skill and self._skill_mcp_manager.active_skills:
            try:
                await self._skill_mcp_manager.deactivate_skill(matched_skill.name)
            except Exception:
                logger.exception(
                    "[ReActAgent] Failed to deactivate MCP servers for skill '%s'",
                    matched_skill.name,
                )
        self._skill_mcp_tools = []

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
        for td in self._tool_builder.make_nested_session_tool_defs(
            conversation_id=conversation_id,
            nested_depth=nested_depth,
            max_delegation_depth=max_delegation_depth,
            nested_map=nested_map,
            nested_descriptions=nested_descriptions,
            cancel_callback=cancel_callback,
            restart_callback=restart_callback,
        ):
            append_fn(td)

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
        for td in self._tool_builder.make_nested_delegate_tool_defs(
            nested_candidates=nested_candidates,
            nested_map=nested_map,
            nested_descriptions=nested_descriptions,
            delegate_callback=delegate_callback,
            conversation_id=conversation_id,
            nested_depth=nested_depth,
        ):
            append_fn(td)

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

    async def _runner_finalize(  # noqa: PLR0913
        self,
        *,
        conversation_id: str,
        run_id: str,
        project_id: str,
        tenant_id: str,
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
            project_id=project_id,
            tenant_id=tenant_id,
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
        project_id: str,
        tenant_id: str,
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
            project_id=project_id,
            tenant_id=tenant_id,
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
        run_metadata: dict[str, str] | None = None,
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
            run_metadata=run_metadata,
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
