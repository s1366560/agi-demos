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
import inspect
import logging
import os
import re
import time
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from src.domain.events.agent_events import (
    AgentDomainEvent,
)
from src.domain.model.agent.skill import Skill
from src.domain.model.agent.subagent import SubAgent
from src.domain.model.agent.subagent_result import SubAgentResult
from src.domain.ports.agent.context_manager_port import ContextBuildRequest

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
    ExecutionRouter,
    RoutingDecision,
    SubAgentOrchestrator,
    SubAgentOrchestratorConfig,
)
from ..routing.hybrid_router import HybridRouter, HybridRouterConfig
from ..skill import SkillExecutionConfig, SkillExecutionContext, SkillOrchestrator
from .processor import ProcessorConfig, SessionProcessor, ToolDefinition
from .skill_executor import SkillExecutor
from .subagent_router import SubAgentMatch, SubAgentRouter
from .tool_converter import convert_tools

if TYPE_CHECKING:
    from src.application.services.artifact_service import ArtifactService
    from src.domain.llm_providers.llm_types import LLMClient
    from src.domain.ports.services.graph_service_port import GraphServicePort

logger = logging.getLogger(__name__)


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

    def __init__(
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
        skill_direct_execute_threshold: float = 0.95,  # Was 0.8, increased to favor LLM decision
        skill_fallback_on_error: bool = True,
        skill_execution_timeout: int = 300,  # Increased from 60 to 300 (5 minutes)
        subagent_match_threshold: float = 0.5,
        subagent_keyword_skip_threshold: float = 0.85,
        subagent_keyword_floor_threshold: float = 0.3,
        subagent_llm_min_confidence: float = 0.6,
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
        tool_provider: callable | None = None,
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
            skill_direct_execute_threshold: Threshold for skill direct execution (default: 0.95)
                High threshold means skill_loader tool is preferred over direct execution
            skill_fallback_on_error: Whether to fallback to LLM on skill error (default: True)
            skill_execution_timeout: Timeout for skill execution in seconds (default: 300)
            subagent_match_threshold: Threshold for subagent routing (default: 0.5)
            subagent_keyword_skip_threshold: Keyword match confidence threshold to skip
                LLM routing fallback in HybridRouter (default: 0.85).
            subagent_keyword_floor_threshold: Lower bound for keyword fallback confidence
                when LLM routing does not produce a strong match (default: 0.3).
            subagent_llm_min_confidence: Minimum confidence required for LLM-based
                routing decisions in HybridRouter (default: 0.6).
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

        # Memory auto-recall / auto-capture (optional, injected from DI)
        self._memory_recall = memory_recall
        self._memory_capture = memory_capture
        self._memory_flush = memory_flush

        # System Prompt Manager - use cached singleton if provided
        if _cached_system_prompt_manager is not None:
            self.prompt_manager = _cached_system_prompt_manager
            logger.debug("ReActAgent: Using cached SystemPromptManager")
        else:
            self.prompt_manager = SystemPromptManager(project_root=self.project_root)

        # Context Window Management
        if context_window_config:
            self.context_manager = ContextWindowManager(context_window_config)
        else:
            self.context_manager = ContextWindowManager(
                ContextWindowConfig(
                    max_context_tokens=max_context_tokens,
                    max_output_tokens=max_tokens,
                )
            )

        # Context Facade - unified entry point for context building
        self.context_facade = ContextFacade(window_manager=self.context_manager)

        execution_config = ExecutionConfig(
            skill_match_threshold=skill_direct_execute_threshold,
            subagent_match_threshold=subagent_match_threshold,
            subagent_keyword_skip_threshold=subagent_keyword_skip_threshold,
            subagent_keyword_floor_threshold=subagent_keyword_floor_threshold,
            subagent_llm_min_confidence=subagent_llm_min_confidence,
            allow_direct_execution=True,
            enable_plan_mode=True,
            enable_subagent_routing=not enable_subagent_as_tool,
        )
        execution_config.validate()

        # Skill System (L2)
        self.skills = skills or []
        self.skill_match_threshold = skill_match_threshold
        self.skill_direct_execute_threshold = skill_direct_execute_threshold
        self.skill_fallback_on_error = skill_fallback_on_error
        self.skill_execution_timeout = skill_execution_timeout
        self.skill_executor = SkillExecutor(tools) if skills else None

        # SubAgent System (L3) - use cached router if provided
        # When LLM client is available, use HybridRouter for keyword + LLM routing
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
        self._subagent_lifecycle_hook_failures = 0
        if _cached_subagent_router is not None:
            self.subagent_router = _cached_subagent_router
            logger.debug("ReActAgent: Using cached SubAgentRouter")
        elif subagents:
            if llm_client:
                self.subagent_router = HybridRouter(
                    subagents=subagents,
                    llm_client=llm_client,
                    config=HybridRouterConfig.from_execution_config(execution_config),
                    default_confidence_threshold=execution_config.subagent_match_threshold,
                )
                logger.info("ReActAgent: Using HybridRouter (keyword + LLM)")
            else:
                self.subagent_router = SubAgentRouter(
                    subagents=subagents,
                    default_confidence_threshold=execution_config.subagent_match_threshold,
                )
        else:
            self.subagent_router = None
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
        self._subagent_session_tasks: dict[str, asyncio.Task] = {}

        # ====================================================================
        # Phase 3 Refactoring: Initialize orchestrators for modular components
        # ====================================================================

        # Event Converter for domain event -> SSE conversion
        self._event_converter = EventConverter(debug_logging=False)

        # Skill Orchestrator for skill matching and execution
        self._skill_orchestrator = SkillOrchestrator(
            skills=skills,
            skill_executor=self.skill_executor,
            tools=tools,
            config=SkillExecutionConfig(
                match_threshold=skill_match_threshold,
                direct_execute_threshold=skill_direct_execute_threshold,
                fallback_on_error=skill_fallback_on_error,
                execution_timeout=skill_execution_timeout,
            ),
            agent_mode=agent_mode,
            debug_logging=False,
        )

        # SubAgent Orchestrator for subagent routing
        self._subagent_orchestrator = SubAgentOrchestrator(
            router=self.subagent_router,
            config=SubAgentOrchestratorConfig(
                default_confidence_threshold=execution_config.subagent_match_threshold,
                emit_routing_events=True,
            ),
            base_model=model,
            base_api_key=api_key,
            base_url=base_url,
            debug_logging=False,
        )

        self._execution_router = ExecutionRouter(
            config=execution_config,
            skill_matcher=self._ExecutionRouterSkillMatcher(self),
            subagent_matcher=self._ExecutionRouterSubAgentMatcher(self),
            plan_evaluator=self._ExecutionRouterPlanEvaluator(self._plan_detector),
        )

        # Background SubAgent executor for non-blocking execution
        from ..subagent.background_executor import BackgroundExecutor

        self._background_executor = BackgroundExecutor()

        # SubAgent template registry for marketplace
        from ..subagent.template_registry import TemplateRegistry

        self._template_registry = TemplateRegistry()

        # Task decomposer for multi-SubAgent orchestration (Phase 7.1)
        from ..subagent.task_decomposer import TaskDecomposer

        agent_names = [sa.name for sa in self.subagents] if self.subagents else []
        self._task_decomposer = (
            TaskDecomposer(
                llm_client=llm_client,
                available_agent_names=agent_names,
            )
            if llm_client and self.subagents
            else None
        )

        # Result aggregator for multi-SubAgent result merging
        from ..subagent.result_aggregator import ResultAggregator

        self._result_aggregator = ResultAggregator(llm_client=llm_client)

        # Convert tools to ToolDefinition - use cached definitions if provided
        # Hot-plug mode: tool_definitions will be set to None, and fetched dynamically in _get_current_tools()
        if _cached_tool_definitions is not None:
            self.tool_definitions = _cached_tool_definitions
            self._use_dynamic_tools = False
            logger.debug(
                f"ReActAgent: Using {len(_cached_tool_definitions)} cached tool definitions"
            )
        elif self._tool_provider is not None:
            # Hot-plug mode: defer tool conversion to runtime
            self.tool_definitions = []  # Will be populated dynamically
            self._use_dynamic_tools = True
            logger.debug("ReActAgent: Using dynamic tool_provider (hot-plug enabled)")
        else:
            self.tool_definitions = convert_tools(self.raw_tools)
            self._use_dynamic_tools = False

        # Create processor config with llm_client for unified resilience
        self.config = ProcessorConfig(
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            max_steps=max_steps,
            llm_client=self._llm_client,
        )

    class _ExecutionRouterSkillMatcher:
        """Skill matcher adapter for ExecutionRouter."""

        def __init__(self, agent: ReActAgent) -> None:
            self._agent = agent

        def match(self, query: str, context: dict[str, Any]) -> str | None:
            matched_skill, _ = self._agent._match_skill(query)
            return matched_skill.name if matched_skill else None

        def can_execute_directly(self, skill_name: str) -> bool:
            result = self._agent._skill_orchestrator.find_by_name(skill_name)
            return result.matched

    class _ExecutionRouterSubAgentMatcher:
        """SubAgent matcher adapter for ExecutionRouter."""

        def __init__(self, agent: ReActAgent) -> None:
            self._agent = agent

        def match(self, query: str, context: dict[str, Any]) -> str | None:
            if not bool(context.get("router_mode_enabled", True)):
                return None
            match = self._agent._match_subagent(query)
            return match.subagent.name if match.subagent else None

        def get_subagent(self, name: str) -> Any:
            for subagent in self._agent.subagents:
                if subagent.name == name:
                    return subagent
            return None

    class _ExecutionRouterPlanEvaluator:
        """Plan evaluator adapter for ExecutionRouter."""

        def __init__(self, detector: PlanDetector) -> None:
            self._detector = detector

        def should_use_plan_mode(self, query: str, context: dict[str, Any]) -> bool:
            return self._detector.detect(query).should_suggest

        def estimate_plan_complexity(self, query: str) -> float:
            return self._detector.detect(query).confidence

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
            deny_tools = ["plugin_manager", "register_mcp_server", "skill_installer", "skill_sync"]
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
                path=ExecutionPath.SUBAGENT,
                confidence=1.0,
                reason="Forced delegation via system instruction",
                target=forced_subagent_name,
                metadata={
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
        if self.subagents and not self._enable_subagent_as_tool:
            # Preserve legacy pre-routing behavior: when subagent-as-tool is disabled,
            # stream() should attempt subagent matching before the ReAct loop.
            return RoutingDecision(
                path=ExecutionPath.SUBAGENT,
                confidence=0.6,
                reason="Legacy subagent pre-routing enabled",
                metadata={
                    "legacy_preroute": True,
                    "domain_lane": domain_lane,
                    "router_fabric_version": "lane-v1",
                },
            )

        available_tool_count = self._estimate_available_tool_count()
        router_mode_enabled = available_tool_count > self._router_mode_tool_count_threshold
        routing_context = {
            "recent_messages": [m.get("content", "") for m in conversation_context[-3:]],
            "available_tool_count": available_tool_count,
            "router_mode_enabled": router_mode_enabled,
            "router_mode_tool_count_threshold": self._router_mode_tool_count_threshold,
        }
        decision = self._execution_router.decide(message, routing_context)
        decision.metadata = dict(decision.metadata or {})
        decision.metadata.setdefault("domain_lane", domain_lane)
        decision.metadata.setdefault("router_fabric_version", "lane-v1")
        decision.metadata["router_mode_enabled"] = router_mode_enabled
        decision.metadata["available_tool_count"] = available_tool_count
        return decision

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

    def _match_skill(self, query: str) -> tuple[Skill | None, float]:
        """
        Match query against available skills, filtered by agent_mode.

        Delegates to SkillOrchestrator for modular implementation.

        Args:
            query: User query

        Returns:
            Tuple of (best matching skill or None, match score)
        """
        # Delegate to SkillOrchestrator
        result = self._skill_orchestrator.match(query)

        if result.matched:
            logger.info(
                f"[ReActAgent] Matched skill: {result.skill.name} "
                f"with score {result.score:.2f} (mode={result.mode.value})"
            )
            return result.skill, result.score
        else:
            logger.debug("[ReActAgent] No skill matched for query")
            return None, 0.0

    def _match_subagent(self, query: str) -> SubAgentMatch:
        """
        Match query against available subagents.

        Delegates to SubAgentOrchestrator for modular implementation.

        Args:
            query: User query

        Returns:
            SubAgentMatch result
        """
        # Delegate to SubAgentOrchestrator
        result = self._subagent_orchestrator.match(query)

        if result.matched:
            logger.info(
                f"[ReActAgent] Matched subagent: {result.subagent.name} "
                f"with confidence {result.confidence:.2f} ({result.match_reason})"
            )
            # Convert to legacy SubAgentMatch for backward compatibility
            return SubAgentMatch(
                subagent=result.subagent,
                confidence=result.confidence,
                match_reason=result.match_reason,
            )
        else:
            return SubAgentMatch(subagent=None, confidence=0.0, match_reason=result.match_reason)

    async def _match_subagent_async(
        self,
        query: str,
        conversation_context: list[dict[str, str]] | None = None,
    ) -> SubAgentMatch:
        """Async match with hybrid routing (keyword + LLM semantic).

        Uses SubAgentOrchestrator.match_async() which delegates to
        HybridRouter.match_async() when available, enabling LLM-based
        semantic routing as a fallback when keyword matching is uncertain.

        Args:
            query: User query.
            conversation_context: Recent conversation for LLM context.

        Returns:
            SubAgentMatch result.
        """
        # Build a brief context string for the LLM router
        context_str = None
        if conversation_context:
            recent = conversation_context[-3:]
            context_str = "\n".join(
                f"{m.get('role', 'user')}: {m.get('content', '')[:200]}" for m in recent
            )

        result = await self._subagent_orchestrator.match_async(
            query,
            conversation_context=context_str,
        )

        if result.matched:
            logger.info(
                f"[ReActAgent] Matched subagent (async): {result.subagent.name} "
                f"with confidence {result.confidence:.2f} ({result.match_reason})"
            )
            return SubAgentMatch(
                subagent=result.subagent,
                confidence=result.confidence,
                match_reason=result.match_reason,
            )
        else:
            return SubAgentMatch(subagent=None, confidence=0.0, match_reason=result.match_reason)

    async def _background_index_conversation(
        self,
        messages: list[dict],
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
        return await self.prompt_manager.build_system_prompt(
            context=context,
            subagent=subagent,
        )

    async def stream(
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

        # Plan Mode detection: suggest plan mode for complex queries
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

        # Check for forced SubAgent delegation via system instruction
        # Format: [System Instruction: Delegate this task strictly to SubAgent "NAME"]
        forced_subagent_name = None
        processed_user_message = user_message
        forced_prefix = '[System Instruction: Delegate this task strictly to SubAgent "'
        if user_message.startswith(forced_prefix):
            try:
                match = re.match(
                    r'^\[System Instruction: Delegate this task strictly to SubAgent "([^"]+)"\]',
                    user_message,
                )
                if match:
                    forced_subagent_name = match.group(1)
                    processed_user_message = user_message.replace(match.group(0), "", 1).strip()
                    if not processed_user_message:
                        processed_user_message = user_message
            except Exception as e:
                logger.warning(f"[ReActAgent] Failed to parse forced subagent instruction: {e}")

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
        yield {
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

        # Check for SubAgent routing (L3)
        # When enable_subagent_as_tool is True, skip pre-routing and let the LLM
        # decide via the delegate_to_subagent tool in the ReAct loop.
        # When False, use legacy pre-routing with keyword/LLM hybrid matching.
        # BUT if forced_subagent_name is present, we override everything.
        should_preroute_subagent = routing_decision.path == ExecutionPath.SUBAGENT and (
            forced_subagent_name is not None or not self._enable_subagent_as_tool
        )
        if should_preroute_subagent:
            active_subagent = None
            subagent_match = None

            if forced_subagent_name:
                # Find the subagent
                for sa in self.subagents or []:
                    if sa.enabled and (
                        sa.name == forced_subagent_name or sa.display_name == forced_subagent_name
                    ):
                        active_subagent = sa
                        break

                if active_subagent:
                    yield {
                        "type": "subagent_routed",
                        "data": {
                            "route_id": route_id,
                            "trace_id": trace_id,
                            "session_id": conversation_id,
                            "subagent_id": active_subagent.id,
                            "subagent_name": active_subagent.display_name,
                            "confidence": 1.0,
                            "reason": "Forced delegation via user instruction",
                        },
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                else:
                    logger.warning(
                        f"[ReActAgent] Forced subagent '{forced_subagent_name}' not found"
                    )
            else:
                # Normal pre-routing
                subagent_match = await self._match_subagent_async(
                    processed_user_message, conversation_context
                )
                active_subagent = subagent_match.subagent

                if active_subagent:
                    yield {
                        "type": "subagent_routed",
                        "data": {
                            "route_id": route_id,
                            "trace_id": trace_id,
                            "session_id": conversation_id,
                            "subagent_id": active_subagent.id,
                            "subagent_name": active_subagent.display_name,
                            "confidence": subagent_match.confidence,
                            "reason": subagent_match.match_reason,
                        },
                        "timestamp": datetime.now(UTC).isoformat(),
                    }

            if active_subagent:
                if forced_subagent_name:
                    async for event in self._execute_subagent(
                        subagent=active_subagent,
                        user_message=processed_user_message,
                        conversation_context=conversation_context,
                        project_id=project_id,
                        tenant_id=tenant_id,
                        conversation_id=conversation_id,
                        abort_signal=abort_signal,
                    ):
                        yield event
                    return  # Forced SubAgent completed, exit early

                # Multi-SubAgent orchestration: decompose task if possible
                if self._task_decomposer and len(self.subagents) > 1:
                    try:
                        context_str = None
                        if conversation_context:
                            recent = conversation_context[-3:]
                            context_str = "\n".join(
                                f"{m.get('role', 'user')}: {m.get('content', '')[:200]}"
                                for m in recent
                            )
                        decomposition = await self._task_decomposer.decompose(
                            processed_user_message, conversation_context=context_str
                        )

                        if decomposition.is_decomposed:
                            # Check if tasks form a chain (linear dependencies)
                            has_chain = any(st.dependencies for st in decomposition.subtasks)
                            all_linear = has_chain and all(
                                len(st.dependencies) <= 1 for st in decomposition.subtasks
                            )

                            if all_linear and has_chain:
                                # Chain execution (sequential pipeline)
                                async for event in self._execute_chain(
                                    subtasks=list(decomposition.subtasks),
                                    user_message=processed_user_message,
                                    conversation_context=conversation_context,
                                    project_id=project_id,
                                    tenant_id=tenant_id,
                                    conversation_id=conversation_id,
                                    route_id=route_id,
                                    abort_signal=abort_signal,
                                ):
                                    yield event
                                return
                            else:
                                # Parallel execution
                                async for event in self._execute_parallel(
                                    subtasks=list(decomposition.subtasks),
                                    user_message=processed_user_message,
                                    conversation_context=conversation_context,
                                    project_id=project_id,
                                    tenant_id=tenant_id,
                                    conversation_id=conversation_id,
                                    route_id=route_id,
                                    abort_signal=abort_signal,
                                ):
                                    yield event
                                return
                    except Exception as e:
                        logger.warning(
                            f"[ReActAgent] Task decomposition failed: {e}, "
                            "falling back to single SubAgent"
                        )

                # Single SubAgent delegation (default path)
                async for event in self._execute_subagent(
                    subagent=active_subagent,
                    user_message=processed_user_message,
                    conversation_context=conversation_context,
                    project_id=project_id,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    abort_signal=abort_signal,
                ):
                    yield event
                return  # SubAgent completed, exit early

        # Check for Skill matching (L2) - forced or confidence-based
        is_forced = False
        if forced_skill_name:
            result = self._skill_orchestrator.find_by_name(forced_skill_name)
            if result.matched:
                matched_skill = result.skill
                skill_score = result.score
                is_forced = True
            else:
                # Forced skill not found - emit warning, fall back to normal matching
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

        # All skill execution goes through prompt injection into the ReAct loop.
        # Forced skills use mandatory injection; confidence-based uses recommendation.
        should_inject_prompt = matched_skill is not None and (
            is_forced or skill_score >= self.skill_match_threshold
        )

        # If score is too low and not forced, don't use skill at all
        if not is_forced and matched_skill and skill_score < self.skill_match_threshold:
            matched_skill = None
            skill_score = 0.0

        # Emit skill_matched event
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

        # Sync skill resources to sandbox before prompt injection
        # This ensures resources are available when LLM generates tool calls
        if should_inject_prompt and matched_skill and self._resource_sync_service:
            sandbox_id = self._extract_sandbox_id_from_tools()
            if sandbox_id:
                try:
                    await self._resource_sync_service.sync_for_skill(
                        skill_name=matched_skill.name,
                        sandbox_id=sandbox_id,
                        skill_content=matched_skill.prompt_template,
                    )
                except Exception as e:
                    logger.warning(
                        f"Skill resource sync failed for INJECT mode "
                        f"(skill={matched_skill.name}): {e}"
                    )

        # Determine agent mode: plan mode overrides default
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

        # Set permission manager mode to enforce tool restrictions
        from src.infrastructure.agent.permission.manager import AgentPermissionMode

        if effective_mode == "plan":
            self.permission_manager.set_mode(AgentPermissionMode.PLAN)
        else:
            self.permission_manager.set_mode(AgentPermissionMode.BUILD)

        # Build system prompt
        # Inject skill into prompt: mandatory for forced, recommendation for matched
        # Auto-recall memory context if preprocessor is available
        memory_context = None
        if self._memory_recall:
            try:
                memory_context = await self._memory_recall.recall(
                    processed_user_message, project_id
                )
                if memory_context and self._memory_recall.last_results:
                    from src.domain.events.agent_events import AgentMemoryRecalledEvent

                    yield AgentMemoryRecalledEvent(
                        memories=self._memory_recall.last_results,
                        count=len(self._memory_recall.last_results),
                        search_ms=self._memory_recall.last_search_ms,
                    ).to_event_dict()
            except Exception as e:
                logger.warning(f"[ReActAgent] Memory recall failed: {e}")

        system_prompt = await self._build_system_prompt(
            processed_user_message,
            conversation_context,
            matched_skill=matched_skill if should_inject_prompt else None,
            subagent=None,
            mode=effective_mode,
            current_step=1,  # Initial step
            project_id=project_id,
            tenant_id=tenant_id,
            force_execution=is_forced,
            memory_context=memory_context,
            selection_context=selection_context,
        )

        # Build context using ContextFacade - replaces inline message building
        # and attachment injection (was ~115 lines, now ~10 lines)
        # Deserialize cached context summary if available
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
        messages = context_result.messages

        # Log attachment info if present
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

            # Emit summary save event if compression produced a summary
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

            # Pre-compaction memory flush: extract durable memories from
            # compressed-away messages before they are lost
            if self._memory_flush and conversation_context:
                try:
                    flushed = await self._memory_flush.flush(
                        conversation_context, project_id, conversation_id
                    )
                    if flushed > 0:
                        from src.domain.events.agent_events import AgentMemoryCapturedEvent

                        yield AgentMemoryCapturedEvent(
                            captured_count=flushed,
                            categories=["flush"],
                        ).to_event_dict()
                except Exception as e:
                    logger.warning(f"[ReActAgent] Pre-compaction flush failed: {e}")

        # Emit initial context_status with token estimation from context build
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

        # Determine tools to use - hot-plug support: fetch current tools
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
                semantic_stage.get("explain", {}).get("max_tools") if semantic_stage else None
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
                and stage["explain"].get("budget_exceeded")
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

        # When a forced skill is active, remove skill_loader from the tool list
        # to prevent the LLM from loading a different skill instead of following
        # the already-injected mandatory skill instructions.
        if is_forced and matched_skill:
            tools_to_use = [t for t in tools_to_use if t.name != "skill_loader"]

        # Inject delegate_to_subagent tool when SubAgent-as-Tool mode is enabled
        if self.subagents and self._enable_subagent_as_tool:
            from ..tools.delegate_subagent import (
                DelegateSubAgentTool,
                ParallelDelegateSubAgentTool,
            )
            from ..tools.subagent_sessions import (
                SessionsAckTool,
                SessionsHistoryTool,
                SessionsListTool,
                SessionsOverviewTool,
                SessionsSendTool,
                SessionsSpawnTool,
                SessionsTimelineTool,
                SessionsWaitTool,
                SubAgentsControlTool,
            )

            enabled_subagents = [sa for sa in self.subagents if sa.enabled]
            if enabled_subagents:
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

                    # Extract result from the complete event
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
                        thinking_override=(
                            str(spawn_options.get("thinking") or "").strip() or None
                        ),
                        spawn_mode=str(spawn_options.get("spawn_mode") or "run"),
                        thread_requested=bool(spawn_options.get("thread_requested")),
                        cleanup=str(spawn_options.get("cleanup") or "keep"),
                    )
                    return run_id

                async def _cancel_spawn_callback(run_id: str) -> bool:
                    return await self._cancel_subagent_session(run_id)

                delegate_tool = DelegateSubAgentTool(
                    subagent_names=list(subagent_map.keys()),
                    subagent_descriptions=subagent_descriptions,
                    execute_callback=_delegate_callback,
                    run_registry=self._subagent_run_registry,
                    conversation_id=conversation_id,
                    delegation_depth=0,
                    max_active_runs=self._max_subagent_active_runs,
                )
                # Convert to ToolDefinition for SessionProcessor
                delegate_td = ToolDefinition(
                    name=delegate_tool.name,
                    description=delegate_tool.description,
                    parameters=delegate_tool.get_parameters_schema(),
                    execute=delegate_tool.execute,
                    _tool_instance=delegate_tool,
                )
                tools_to_use.append(delegate_td)

                sessions_spawn_tool = SessionsSpawnTool(
                    subagent_names=list(subagent_map.keys()),
                    subagent_descriptions=subagent_descriptions,
                    spawn_callback=_spawn_callback,
                    run_registry=self._subagent_run_registry,
                    conversation_id=conversation_id,
                    max_active_runs=self._max_subagent_active_runs,
                    max_active_runs_per_lineage=self._max_subagent_active_runs_per_lineage,
                    max_children_per_requester=self._max_subagent_children_per_requester,
                    requester_session_key=conversation_id,
                    delegation_depth=0,
                    max_delegation_depth=self._max_subagent_delegation_depth,
                )
                tools_to_use.append(
                    ToolDefinition(
                        name=sessions_spawn_tool.name,
                        description=sessions_spawn_tool.description,
                        parameters=sessions_spawn_tool.get_parameters_schema(),
                        execute=sessions_spawn_tool.execute,
                        _tool_instance=sessions_spawn_tool,
                    )
                )

                sessions_send_tool = SessionsSendTool(
                    run_registry=self._subagent_run_registry,
                    conversation_id=conversation_id,
                    spawn_callback=_spawn_callback,
                    max_active_runs=self._max_subagent_active_runs,
                    max_active_runs_per_lineage=self._max_subagent_active_runs_per_lineage,
                    max_children_per_requester=self._max_subagent_children_per_requester,
                    requester_session_key=conversation_id,
                    delegation_depth=0,
                    max_delegation_depth=self._max_subagent_delegation_depth,
                )
                tools_to_use.append(
                    ToolDefinition(
                        name=sessions_send_tool.name,
                        description=sessions_send_tool.description,
                        parameters=sessions_send_tool.get_parameters_schema(),
                        execute=sessions_send_tool.execute,
                        _tool_instance=sessions_send_tool,
                    )
                )

                sessions_list_tool = SessionsListTool(
                    run_registry=self._subagent_run_registry,
                    conversation_id=conversation_id,
                    requester_session_key=conversation_id,
                    visibility_default="tree",
                )
                tools_to_use.append(
                    ToolDefinition(
                        name=sessions_list_tool.name,
                        description=sessions_list_tool.description,
                        parameters=sessions_list_tool.get_parameters_schema(),
                        execute=sessions_list_tool.execute,
                        _tool_instance=sessions_list_tool,
                    )
                )

                sessions_history_tool = SessionsHistoryTool(
                    run_registry=self._subagent_run_registry,
                    conversation_id=conversation_id,
                    requester_session_key=conversation_id,
                    visibility_default="tree",
                )
                tools_to_use.append(
                    ToolDefinition(
                        name=sessions_history_tool.name,
                        description=sessions_history_tool.description,
                        parameters=sessions_history_tool.get_parameters_schema(),
                        execute=sessions_history_tool.execute,
                        _tool_instance=sessions_history_tool,
                    )
                )

                sessions_wait_tool = SessionsWaitTool(
                    run_registry=self._subagent_run_registry,
                    conversation_id=conversation_id,
                )
                tools_to_use.append(
                    ToolDefinition(
                        name=sessions_wait_tool.name,
                        description=sessions_wait_tool.description,
                        parameters=sessions_wait_tool.get_parameters_schema(),
                        execute=sessions_wait_tool.execute,
                        _tool_instance=sessions_wait_tool,
                    )
                )

                sessions_ack_tool = SessionsAckTool(
                    run_registry=self._subagent_run_registry,
                    conversation_id=conversation_id,
                    requester_session_key=conversation_id,
                )
                tools_to_use.append(
                    ToolDefinition(
                        name=sessions_ack_tool.name,
                        description=sessions_ack_tool.description,
                        parameters=sessions_ack_tool.get_parameters_schema(),
                        execute=sessions_ack_tool.execute,
                        _tool_instance=sessions_ack_tool,
                    )
                )

                sessions_timeline_tool = SessionsTimelineTool(
                    run_registry=self._subagent_run_registry,
                    conversation_id=conversation_id,
                )
                tools_to_use.append(
                    ToolDefinition(
                        name=sessions_timeline_tool.name,
                        description=sessions_timeline_tool.description,
                        parameters=sessions_timeline_tool.get_parameters_schema(),
                        execute=sessions_timeline_tool.execute,
                        _tool_instance=sessions_timeline_tool,
                    )
                )

                sessions_overview_tool = SessionsOverviewTool(
                    run_registry=self._subagent_run_registry,
                    conversation_id=conversation_id,
                    requester_session_key=conversation_id,
                    visibility_default="tree",
                    observability_stats_provider=self._get_subagent_observability_stats,
                )
                tools_to_use.append(
                    ToolDefinition(
                        name=sessions_overview_tool.name,
                        description=sessions_overview_tool.description,
                        parameters=sessions_overview_tool.get_parameters_schema(),
                        execute=sessions_overview_tool.execute,
                        _tool_instance=sessions_overview_tool,
                    )
                )

                subagents_control_tool = SubAgentsControlTool(
                    run_registry=self._subagent_run_registry,
                    conversation_id=conversation_id,
                    subagent_names=list(subagent_map.keys()),
                    subagent_descriptions=subagent_descriptions,
                    cancel_callback=_cancel_spawn_callback,
                    restart_callback=_spawn_callback,
                    max_active_runs=self._max_subagent_active_runs,
                    max_active_runs_per_lineage=self._max_subagent_active_runs_per_lineage,
                    max_children_per_requester=self._max_subagent_children_per_requester,
                    requester_session_key=conversation_id,
                    delegation_depth=0,
                    max_delegation_depth=self._max_subagent_delegation_depth,
                )
                tools_to_use.append(
                    ToolDefinition(
                        name=subagents_control_tool.name,
                        description=subagents_control_tool.description,
                        parameters=subagents_control_tool.get_parameters_schema(),
                        execute=subagents_control_tool.execute,
                        _tool_instance=subagents_control_tool,
                    )
                )

                # Inject parallel delegation tool when 2+ SubAgents available
                if len(enabled_subagents) >= 2:
                    parallel_tool = ParallelDelegateSubAgentTool(
                        subagent_names=list(subagent_map.keys()),
                        subagent_descriptions=subagent_descriptions,
                        execute_callback=_delegate_callback,
                        run_registry=self._subagent_run_registry,
                        conversation_id=conversation_id,
                        delegation_depth=0,
                        max_active_runs=self._max_subagent_active_runs,
                    )
                    parallel_td = ToolDefinition(
                        name=parallel_tool.name,
                        description=parallel_tool.description,
                        parameters=parallel_tool.get_parameters_schema(),
                        execute=parallel_tool.execute,
                        _tool_instance=parallel_tool,
                    )
                    tools_to_use.append(parallel_td)

                logger.info(
                    f"[ReActAgent] Injected SubAgent delegation tools "
                    f"({len(enabled_subagents)} SubAgents, "
                    f"parallel={'yes' if len(enabled_subagents) >= 2 else 'no'}, "
                    "sessions=yes)"
                )

        # Use main agent config (SubAgent path returns early above)
        config = self.config

        # For dynamic tools mode, create config with tool_provider callback
        # This enables the processor to refresh tools after register_mcp_server
        if self._use_dynamic_tools and self._tool_provider is not None:
            # Create a wrapper that converts raw tools to ToolDefinitions
            def _tool_provider_wrapper() -> list[ToolDefinition]:
                _, tool_defs = self._get_current_tools(selection_context=selection_context)
                return list(tool_defs)

            # Create config copy with tool_provider
            config = ProcessorConfig(
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
            )
            logger.debug(
                "[ReActAgent] Created processor config with tool_provider for dynamic tools"
            )

        # Create processor with artifact service for rich output handling
        processor = SessionProcessor(
            config=config,
            tools=tools_to_use,
            permission_manager=self.permission_manager,
            artifact_service=self.artifact_service,
        )

        # Track final content
        final_content = ""
        success = True

        # Build langfuse context for persistence (HITL requests need this)
        langfuse_context = {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "message_id": message_id,
        }

        try:
            # Process and convert Domain events to legacy format
            async for domain_event in processor.process(
                session_id=conversation_id,
                messages=messages,
                langfuse_context=langfuse_context,
                abort_signal=abort_signal,
            ):
                # Convert AgentDomainEvent to legacy event format
                event = self._convert_domain_event(domain_event)
                if event:
                    # Track complete content from text_delta events
                    if event.get("type") == "text_delta":
                        final_content += event.get("data", {}).get("delta", "")
                    # Use text_end full_text as authoritative final content (handles buffer edge cases)
                    elif event.get("type") == "text_end":
                        text_end_content = event.get("data", {}).get("full_text", "")
                        if text_end_content:
                            final_content = (
                                text_end_content  # Override with authoritative full text
                            )

                    yield event

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

                        yield AgentMemoryCapturedEvent(
                            captured_count=captured,
                            categories=self._memory_capture.last_categories,
                        ).to_event_dict()
                except Exception as e:
                    logger.warning(f"[ReActAgent] Memory capture failed: {e}")

            # Async conversation indexing (fire-and-forget)
            if conversation_id and conversation_context and success:
                try:
                    import asyncio

                    asyncio.create_task(
                        self._background_index_conversation(
                            conversation_context, project_id, conversation_id
                        )
                    )
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

        except Exception as e:
            logger.error(f"[ReActAgent] Error in stream: {e}", exc_info=True)
            success = False
            yield {
                "type": "error",
                "data": {
                    "message": str(e),
                    "code": type(e).__name__,
                },
                "timestamp": datetime.now(UTC).isoformat(),
            }

        finally:
            # Record execution statistics
            end_time = time.time()
            execution_time_ms = int((end_time - start_time) * 1000)
            logger.debug(f"[ReActAgent] Stream finished in {execution_time_ms}ms")

            if matched_skill:
                matched_skill.record_usage(success)
                logger.info(
                    f"[ReActAgent] Skill {matched_skill.name} usage recorded: success={success}"
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
        """Execute a SubAgent in an independent ReAct loop.

        Creates a SubAgentProcess with its own context window and processor,
        forwards SSE events, and yields a final complete event with the result.

        Optionally injects relevant memories from the knowledge graph when
        graph_service is available (Phase 5.1 Memory Sharing).

        Args:
            subagent: The matched SubAgent to execute.
            user_message: The user's original message.
            conversation_context: Recent conversation for context bridging.
            project_id: Project ID for scoping.
            tenant_id: Tenant ID for scoping.
            conversation_id: Conversation ID used to track subagent run lifecycle.
            abort_signal: Optional signal to abort execution.

        Yields:
            SSE event dicts including subagent lifecycle and tool events.
        """
        from ..subagent.context_bridge import ContextBridge
        from ..subagent.process import SubAgentProcess

        # Search for relevant memories if graph service is available
        memory_context = ""
        if self._graph_service and project_id:
            try:
                from ..subagent.memory_accessor import MemoryAccessor

                accessor = MemoryAccessor(
                    graph_service=self._graph_service,
                    project_id=project_id,
                    writable=False,
                )
                items = await accessor.search(user_message)
                memory_context = accessor.format_for_context(items)
                if memory_context:
                    logger.debug(
                        f"[ReActAgent] Injecting {len(items)} memory items into SubAgent context"
                    )
            except Exception as e:
                logger.warning(f"[ReActAgent] Memory search failed: {e}")

        # Build condensed context for the SubAgent
        bridge = ContextBridge()
        subagent_context = bridge.build_subagent_context(
            user_message=user_message,
            subagent_system_prompt=subagent.system_prompt,
            conversation_context=conversation_context,
            main_token_budget=self.config.context_limit,
            project_id=project_id,
            tenant_id=tenant_id,
            memory_context=memory_context,
        )

        # Filter tools for SubAgent permissions
        current_raw_tools, current_tool_definitions = self._get_current_tools()
        if self.subagent_router:
            filtered_raw = self.subagent_router.filter_tools(subagent, current_raw_tools)
            filtered_tools = list(convert_tools(filtered_raw))
        else:
            filtered_tools = list(current_tool_definitions)
        existing_tool_names = {tool.name for tool in filtered_tools}

        def _append_nested_tool(tool_instance: Any) -> None:
            if tool_instance.name in existing_tool_names:
                return
            filtered_tools.append(
                ToolDefinition(
                    name=tool_instance.name,
                    description=tool_instance.description,
                    parameters=tool_instance.get_parameters_schema(),
                    execute=tool_instance.execute,
                    _tool_instance=tool_instance,
                )
            )
            existing_tool_names.add(tool_instance.name)

        # Inject SubAgent delegation tools for nested orchestration (bounded depth).
        max_delegation_depth = self._max_subagent_delegation_depth
        if (
            self.subagents
            and self._enable_subagent_as_tool
            and delegation_depth < max_delegation_depth
        ):
            from ..tools.delegate_subagent import (
                DelegateSubAgentTool,
                ParallelDelegateSubAgentTool,
            )
            from ..tools.subagent_sessions import (
                SessionsHistoryTool,
                SessionsListTool,
                SessionsOverviewTool,
                SessionsTimelineTool,
                SessionsWaitTool,
                SubAgentsControlTool,
            )

            nested_candidates = [sa for sa in self.subagents if sa.enabled and sa.id != subagent.id]
            if nested_candidates:
                nested_map = {sa.name: sa for sa in nested_candidates}
                nested_descriptions = {
                    sa.name: (sa.trigger.description if sa.trigger else sa.display_name)
                    for sa in nested_candidates
                }
                nested_depth = delegation_depth + 1

                async def _nested_delegate_callback(
                    subagent_name: str,
                    task: str,
                    on_event: Callable[[dict[str, Any]], None] | None = None,
                ) -> str:
                    target = nested_map.get(subagent_name)
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
                        delegation_depth=delegation_depth + 1,
                    ):
                        if on_event:
                            event_type = evt.get("type")
                            if event_type not in {"complete", "error"}:
                                on_event(evt)
                        events.append(evt)

                    complete_evt = next(
                        (event for event in events if event.get("type") == "complete"),
                        None,
                    )
                    if not complete_evt:
                        return "SubAgent execution completed but no result returned"

                    data = complete_evt.get("data", {})
                    content = data.get("content", "")
                    subagent_result = data.get("subagent_result")
                    if subagent_result:
                        summary = subagent_result.get("summary", content)
                        tokens = subagent_result.get("tokens_used", 0)
                        return (
                            f"[SubAgent '{subagent_name}' completed]\n"
                            f"Result: {summary}\n"
                            f"Tokens used: {tokens}"
                        )

                    return content or "SubAgent completed with no output"

                async def _nested_spawn_callback(
                    subagent_name: str,
                    task: str,
                    run_id: str,
                    **spawn_options: Any,
                ) -> str:
                    target = nested_map.get(subagent_name)
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
                        thinking_override=(
                            str(spawn_options.get("thinking") or "").strip() or None
                        ),
                        spawn_mode=str(spawn_options.get("spawn_mode") or "run"),
                        thread_requested=bool(spawn_options.get("thread_requested")),
                        cleanup=str(spawn_options.get("cleanup") or "keep"),
                    )
                    return run_id

                async def _nested_cancel_callback(run_id: str) -> bool:
                    return await self._cancel_subagent_session(run_id)

                nested_visibility = "tree" if nested_depth < max_delegation_depth else "self"
                _append_nested_tool(
                    SessionsListTool(
                        run_registry=self._subagent_run_registry,
                        conversation_id=conversation_id,
                        requester_session_key=conversation_id,
                        visibility_default=nested_visibility,
                    )
                )
                _append_nested_tool(
                    SessionsHistoryTool(
                        run_registry=self._subagent_run_registry,
                        conversation_id=conversation_id,
                        requester_session_key=conversation_id,
                        visibility_default=nested_visibility,
                    )
                )
                _append_nested_tool(
                    SessionsWaitTool(
                        run_registry=self._subagent_run_registry,
                        conversation_id=conversation_id,
                    )
                )
                _append_nested_tool(
                    SessionsTimelineTool(
                        run_registry=self._subagent_run_registry,
                        conversation_id=conversation_id,
                    )
                )
                _append_nested_tool(
                    SessionsOverviewTool(
                        run_registry=self._subagent_run_registry,
                        conversation_id=conversation_id,
                        requester_session_key=conversation_id,
                        visibility_default=nested_visibility,
                        observability_stats_provider=self._get_subagent_observability_stats,
                    )
                )
                _append_nested_tool(
                    SubAgentsControlTool(
                        run_registry=self._subagent_run_registry,
                        conversation_id=conversation_id,
                        subagent_names=list(nested_map.keys()),
                        subagent_descriptions=nested_descriptions,
                        cancel_callback=_nested_cancel_callback,
                        restart_callback=_nested_spawn_callback,
                        max_active_runs=self._max_subagent_active_runs,
                        max_active_runs_per_lineage=self._max_subagent_active_runs_per_lineage,
                        max_children_per_requester=self._max_subagent_children_per_requester,
                        requester_session_key=conversation_id,
                        delegation_depth=nested_depth,
                        max_delegation_depth=max_delegation_depth,
                    )
                )

                nested_delegate_tool = DelegateSubAgentTool(
                    subagent_names=list(nested_map.keys()),
                    subagent_descriptions=nested_descriptions,
                    execute_callback=_nested_delegate_callback,
                    run_registry=self._subagent_run_registry,
                    conversation_id=conversation_id,
                    delegation_depth=nested_depth,
                    max_active_runs=self._max_subagent_active_runs,
                )
                _append_nested_tool(nested_delegate_tool)

                if len(nested_candidates) >= 2:
                    nested_parallel_tool = ParallelDelegateSubAgentTool(
                        subagent_names=list(nested_map.keys()),
                        subagent_descriptions=nested_descriptions,
                        execute_callback=_nested_delegate_callback,
                        run_registry=self._subagent_run_registry,
                        conversation_id=conversation_id,
                        delegation_depth=nested_depth,
                        max_active_runs=self._max_subagent_active_runs,
                    )
                    _append_nested_tool(nested_parallel_tool)

        # Create independent SubAgent process
        process = SubAgentProcess(
            subagent=subagent,
            context=subagent_context,
            tools=filtered_tools,
            base_model=(model_override or self.model),
            base_api_key=self.api_key,
            base_url=self.base_url,
            llm_client=self._llm_client,
            permission_manager=self.permission_manager,
            artifact_service=self.artifact_service,
            abort_signal=abort_signal,
        )

        # Execute and relay all events
        async for event in process.execute():
            yield event

        # Get structured result
        result = process.result

        # Yield final complete event with SubAgent result
        yield {
            "type": "complete",
            "data": {
                "content": result.final_content if result else "",
                "subagent_used": subagent.name,
                "subagent_result": result.to_event_data() if result else None,
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }

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
        """Execute multiple SubAgents in parallel via ParallelScheduler.

        Args:
            subtasks: Decomposed sub-tasks from TaskDecomposer.
            user_message: Original user message.
            conversation_context: Recent conversation history.
            project_id: Project ID for scoping.
            tenant_id: Tenant ID for scoping.
            abort_signal: Optional abort signal.

        Yields:
            SSE event dicts including parallel lifecycle events.
        """
        from ..subagent.parallel_scheduler import ParallelScheduler

        yield {
            "type": "parallel_started",
            "data": {
                "task_count": len(subtasks),
                "session_id": conversation_id or None,
                "route_id": route_id,
                "trace_id": route_id,
                "subtasks": [
                    {"id": st.id, "description": st.description, "agent": st.target_subagent}
                    for st in subtasks
                ],
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }

        # Build subagent name -> SubAgent mapping
        subagent_map = {sa.name: sa for sa in self.subagents}

        # Get current tools
        _, current_tool_definitions = self._get_current_tools()

        scheduler = ParallelScheduler()
        results: list[SubAgentResult] = []

        async for event in scheduler.execute(
            subtasks=subtasks,
            subagent_map=subagent_map,
            tools=current_tool_definitions,
            base_model=self.model,
            base_api_key=self.api_key,
            base_url=self.base_url,
            llm_client=self._llm_client,
            conversation_context=conversation_context,
            main_token_budget=self.config.context_limit,
            project_id=project_id,
            tenant_id=tenant_id,
            abort_signal=abort_signal,
        ):
            if route_id or conversation_id:
                event_data = event.get("data")
                if isinstance(event_data, dict):
                    tagged_data = dict(event_data)
                    if route_id:
                        tagged_data.setdefault("route_id", route_id)
                        tagged_data.setdefault("trace_id", route_id)
                    if conversation_id:
                        tagged_data.setdefault("session_id", conversation_id)
                    event = {**event, "data": tagged_data}
            yield event
            # Collect results from completed subtask events
            if event.get("type") == "subtask_completed" and event.get("data", {}).get("result"):
                result_data = event["data"]["result"]
                if isinstance(result_data, SubAgentResult):
                    results.append(result_data)

        # Aggregate results
        aggregated = await self._result_aggregator.aggregate_with_llm(results)

        yield {
            "type": "parallel_completed",
            "data": {
                "session_id": conversation_id or None,
                "route_id": route_id,
                "trace_id": route_id,
                "total_tasks": len(subtasks),
                "completed": len(results),
                "all_succeeded": aggregated.all_succeeded,
                "total_tokens": aggregated.total_tokens,
                "failed_agents": list(aggregated.failed_agents),
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }

        yield {
            "type": "complete",
            "data": {
                "content": aggregated.summary,
                "orchestration_mode": "parallel",
                "subtask_count": len(subtasks),
                "session_id": conversation_id or None,
                "route_id": route_id,
                "trace_id": route_id,
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }

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
        """Execute SubAgents as a sequential chain (pipeline).

        Converts decomposed subtasks with linear dependencies into a
        SubAgentChain and executes them sequentially.

        Args:
            subtasks: Decomposed sub-tasks with linear dependencies.
            user_message: Original user message.
            conversation_context: Recent conversation history.
            project_id: Project ID for scoping.
            tenant_id: Tenant ID for scoping.
            abort_signal: Optional abort signal.

        Yields:
            SSE event dicts including chain lifecycle events.
        """
        from ..subagent.chain import ChainStep, SubAgentChain

        # Build subagent name -> SubAgent mapping
        subagent_map = {sa.name: sa for sa in self.subagents}

        # Convert subtasks to ChainSteps, respecting dependency order
        # Sort by dependency: tasks with no deps first, then those depending on them
        ordered = self._topological_sort_subtasks(subtasks)
        chain_steps = []
        for i, st in enumerate(ordered):
            agent = subagent_map.get(st.target_subagent)
            if not agent:
                # Use first available subagent as fallback
                agent = self.subagents[0] if self.subagents else None
            if agent:
                template = "{input}" if i == 0 else "{input}\n\nPrevious result:\n{prev}"
                chain_steps.append(
                    ChainStep(
                        subagent=agent,
                        task_template=st.description + "\n\n" + template,
                        name=st.id,
                    )
                )

        if not chain_steps:
            return

        chain = SubAgentChain(steps=chain_steps)
        _, current_tool_definitions = self._get_current_tools()

        async for event in chain.execute(
            user_message=user_message,
            tools=current_tool_definitions,
            base_model=self.model,
            base_api_key=self.api_key,
            base_url=self.base_url,
            llm_client=self._llm_client,
            conversation_context=conversation_context,
            main_token_budget=self.config.context_limit,
            project_id=project_id,
            tenant_id=tenant_id,
            abort_signal=abort_signal,
        ):
            if route_id or conversation_id:
                event_data = event.get("data")
                if isinstance(event_data, dict):
                    tagged_data = dict(event_data)
                    if route_id:
                        tagged_data.setdefault("route_id", route_id)
                        tagged_data.setdefault("trace_id", route_id)
                    if conversation_id:
                        tagged_data.setdefault("session_id", conversation_id)
                    event = {**event, "data": tagged_data}
            yield event

        chain_result = chain.result
        yield {
            "type": "complete",
            "data": {
                "content": chain_result.final_summary if chain_result else "",
                "orchestration_mode": "chain",
                "step_count": len(chain_steps),
                "session_id": conversation_id or None,
                "route_id": route_id,
                "trace_id": route_id,
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }

    async def _execute_background(
        self,
        subagent: SubAgent,
        user_message: str,
        conversation_id: str,
        conversation_context: list[dict[str, str]],
        project_id: str,
        tenant_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Launch a SubAgent for background execution (non-blocking).

        The SubAgent starts running asynchronously and results are
        delivered via the BackgroundExecutor callback.

        Args:
            subagent: SubAgent to run in background.
            user_message: Task description.
            conversation_id: Parent conversation ID.
            conversation_context: Recent conversation history.
            project_id: Project ID.
            tenant_id: Tenant ID.

        Yields:
            SSE event confirming background launch.
        """
        _, current_tool_definitions = self._get_current_tools()

        execution_id = self._background_executor.launch(
            subagent=subagent,
            user_message=user_message,
            conversation_id=conversation_id,
            tools=current_tool_definitions,
            base_model=self.model,
            conversation_context=conversation_context,
            main_token_budget=self.config.context_limit,
            project_id=project_id,
            tenant_id=tenant_id,
            base_api_key=self.api_key,
            base_url=self.base_url,
            llm_client=self._llm_client,
        )

        yield {
            "type": "background_launched",
            "data": {
                "execution_id": execution_id,
                "subagent_id": subagent.id,
                "subagent_name": subagent.display_name,
                "task": user_message[:200],
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }

        yield {
            "type": "complete",
            "data": {
                "content": (
                    f"Task delegated to {subagent.display_name} in background "
                    f"(ID: {execution_id}). You will be notified when it completes."
                ),
                "orchestration_mode": "background",
                "execution_id": execution_id,
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }

    async def _emit_subagent_lifecycle_hook(self, event: dict[str, Any]) -> None:
        """Emit detached SubAgent lifecycle hook event if callback is configured."""
        if not self._subagent_lifecycle_hook:
            return
        try:
            result = self._subagent_lifecycle_hook(event)
            if inspect.isawaitable(result):
                await result
        except Exception:
            self._subagent_lifecycle_hook_failures += 1
            logger.warning(
                "SubAgent lifecycle hook failed",
                extra={"event_type": event.get("type"), "run_id": event.get("run_id")},
                exc_info=True,
            )

    def _get_subagent_observability_stats(self) -> dict[str, int]:
        """Return subagent lifecycle observability counters for overview tools."""
        return {"hook_failures": int(self._subagent_lifecycle_hook_failures)}

    async def _launch_subagent_session(
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
        if run_id in self._subagent_session_tasks:
            raise ValueError(f"Run {run_id} is already running")

        normalized_spawn_mode = (spawn_mode or "run").strip().lower() or "run"
        normalized_cleanup = (cleanup or "keep").strip().lower() or "keep"
        requested_model_override = (model_override or "").strip() or None
        requested_thinking_override = (thinking_override or "").strip() or None
        start_gate = asyncio.Event()

        async def _runner() -> None:
            from src.domain.model.agent.subagent_run import SubAgentRunStatus

            await start_gate.wait()
            started_at = time.time()
            summary = ""
            tokens_used: int | None = None
            execution_time_ms: int | None = None
            result_success = True
            result_error: str | None = None
            configured_timeout = 0.0
            cancelled_by_control = False
            resolved_model_override = requested_model_override
            resolved_thinking_override = requested_thinking_override
            run_state = self._subagent_run_registry.get_run(conversation_id, run_id)
            if run_state:
                try:
                    configured_timeout = float(run_state.metadata.get("run_timeout_seconds") or 0)
                except (TypeError, ValueError):
                    configured_timeout = 0.0
                if not resolved_model_override:
                    resolved_model_override = (
                        str(
                            run_state.metadata.get("model")
                            or run_state.metadata.get("model_override")
                            or ""
                        ).strip()
                        or None
                    )
                if not resolved_thinking_override:
                    resolved_thinking_override = (
                        str(
                            run_state.metadata.get("thinking")
                            or run_state.metadata.get("thinking_override")
                            or ""
                        ).strip()
                        or None
                    )
                self._subagent_run_registry.attach_metadata(
                    conversation_id=conversation_id,
                    run_id=run_id,
                    metadata={
                        "spawn_mode": normalized_spawn_mode,
                        "thread_requested": bool(thread_requested),
                        "cleanup": normalized_cleanup,
                        "model_override": resolved_model_override,
                        "thinking_override": resolved_thinking_override,
                    },
                )

            async def _consume_subagent_events() -> None:
                nonlocal summary, tokens_used, execution_time_ms, result_success, result_error
                async for evt in self._execute_subagent(
                    subagent=subagent,
                    user_message=user_message,
                    conversation_context=conversation_context,
                    project_id=project_id,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    abort_signal=abort_signal,
                    model_override=resolved_model_override,
                    thinking_override=resolved_thinking_override,
                ):
                    if evt.get("type") != "complete":
                        continue
                    data = evt.get("data", {})
                    subagent_result = data.get("subagent_result") or {}
                    summary = subagent_result.get("summary") or data.get("content", "")
                    tokens_used = subagent_result.get("tokens_used")
                    execution_time_ms = subagent_result.get("execution_time_ms")
                    if isinstance(subagent_result, dict):
                        result_success = bool(subagent_result.get("success", True))
                        result_error = subagent_result.get("error")

            try:
                lane_wait_start = time.time()
                async with self._subagent_lane_semaphore:
                    lane_wait_ms = int((time.time() - lane_wait_start) * 1000)
                    if lane_wait_ms > 0:
                        self._subagent_run_registry.attach_metadata(
                            conversation_id=conversation_id,
                            run_id=run_id,
                            metadata={"lane_wait_ms": lane_wait_ms},
                        )
                    if configured_timeout > 0:
                        await asyncio.wait_for(
                            _consume_subagent_events(), timeout=configured_timeout
                        )
                    else:
                        await _consume_subagent_events()

                current = self._subagent_run_registry.get_run(conversation_id, run_id)
                if current and current.status in {
                    SubAgentRunStatus.PENDING,
                    SubAgentRunStatus.RUNNING,
                }:
                    elapsed_ms = execution_time_ms or int((time.time() - started_at) * 1000)
                    if result_success:
                        self._subagent_run_registry.mark_completed(
                            conversation_id=conversation_id,
                            run_id=run_id,
                            summary=summary,
                            tokens_used=tokens_used,
                            execution_time_ms=elapsed_ms,
                            expected_statuses=[
                                SubAgentRunStatus.PENDING,
                                SubAgentRunStatus.RUNNING,
                            ],
                        )
                    else:
                        self._subagent_run_registry.mark_failed(
                            conversation_id=conversation_id,
                            run_id=run_id,
                            error=result_error or "SubAgent session failed",
                            execution_time_ms=elapsed_ms,
                            expected_statuses=[
                                SubAgentRunStatus.PENDING,
                                SubAgentRunStatus.RUNNING,
                            ],
                        )
            except TimeoutError:
                current = self._subagent_run_registry.get_run(conversation_id, run_id)
                if current and current.status in {
                    SubAgentRunStatus.PENDING,
                    SubAgentRunStatus.RUNNING,
                }:
                    self._subagent_run_registry.mark_timed_out(
                        conversation_id=conversation_id,
                        run_id=run_id,
                        reason=(f"SubAgent session exceeded timeout ({configured_timeout}s)"),
                        metadata={"timeout_seconds": configured_timeout},
                        expected_statuses=[SubAgentRunStatus.PENDING, SubAgentRunStatus.RUNNING],
                    )
            except asyncio.CancelledError:
                cancelled_by_control = True
                current = self._subagent_run_registry.get_run(conversation_id, run_id)
                if current and current.status in {
                    SubAgentRunStatus.PENDING,
                    SubAgentRunStatus.RUNNING,
                }:
                    self._subagent_run_registry.mark_cancelled(
                        conversation_id=conversation_id,
                        run_id=run_id,
                        reason="Cancelled by control tool",
                        expected_statuses=[SubAgentRunStatus.PENDING, SubAgentRunStatus.RUNNING],
                    )
                raise
            except Exception as exc:
                current = self._subagent_run_registry.get_run(conversation_id, run_id)
                if current and current.status in {
                    SubAgentRunStatus.PENDING,
                    SubAgentRunStatus.RUNNING,
                }:
                    self._subagent_run_registry.mark_failed(
                        conversation_id=conversation_id,
                        run_id=run_id,
                        error=str(exc),
                        execution_time_ms=int((time.time() - started_at) * 1000),
                        expected_statuses=[SubAgentRunStatus.PENDING, SubAgentRunStatus.RUNNING],
                    )
            finally:
                if not cancelled_by_control:
                    try:
                        await self._persist_subagent_completion_announce(
                            conversation_id=conversation_id,
                            run_id=run_id,
                            fallback_summary=summary,
                            fallback_tokens_used=tokens_used,
                            fallback_execution_time_ms=execution_time_ms,
                            spawn_mode=normalized_spawn_mode,
                            thread_requested=bool(thread_requested),
                            cleanup=normalized_cleanup,
                            model_override=resolved_model_override,
                            thinking_override=resolved_thinking_override,
                            max_retries=self._subagent_announce_max_retries,
                        )
                    except Exception:
                        logger.warning(
                            "Failed to persist completion announce metadata",
                            extra={"conversation_id": conversation_id, "run_id": run_id},
                            exc_info=True,
                        )
                final_run = self._subagent_run_registry.get_run(conversation_id, run_id)
                await self._emit_subagent_lifecycle_hook(
                    {
                        "type": "subagent_ended",
                        "conversation_id": conversation_id,
                        "run_id": run_id,
                        "subagent_name": subagent.name,
                        "status": final_run.status.value if final_run else "unknown",
                        "summary": (final_run.summary if final_run else summary) or "",
                        "error": (final_run.error if final_run else result_error) or "",
                        "spawn_mode": normalized_spawn_mode,
                        "thread_requested": bool(thread_requested),
                        "cleanup": normalized_cleanup,
                    }
                )
                self._subagent_session_tasks.pop(run_id, None)

        task = asyncio.create_task(_runner(), name=f"subagent-session-{run_id}")
        self._subagent_session_tasks[run_id] = task
        await self._emit_subagent_lifecycle_hook(
            {
                "type": "subagent_spawning",
                "conversation_id": conversation_id,
                "run_id": run_id,
                "subagent_name": subagent.name,
                "spawn_mode": normalized_spawn_mode,
                "thread_requested": bool(thread_requested),
                "cleanup": normalized_cleanup,
                "model_override": requested_model_override,
                "thinking_override": requested_thinking_override,
            }
        )
        await self._emit_subagent_lifecycle_hook(
            {
                "type": "subagent_spawned",
                "conversation_id": conversation_id,
                "run_id": run_id,
                "subagent_name": subagent.name,
                "spawn_mode": normalized_spawn_mode,
                "thread_requested": bool(thread_requested),
                "cleanup": normalized_cleanup,
            }
        )
        start_gate.set()

    @staticmethod
    def _resolve_subagent_completion_outcome(status: str) -> tuple[str, str]:
        """Map terminal run status to announce outcome labels."""
        status_key = (status or "").strip().lower()
        if status_key == "completed":
            return "success", "completed successfully"
        if status_key == "failed":
            return "error", "failed"
        if status_key == "timed_out":
            return "timeout", "timed out"
        if status_key == "cancelled":
            return "cancelled", "cancelled"
        return "unknown", status_key or "unknown"

    def _append_capped_announce_event(
        self,
        events: list[dict[str, Any]],
        dropped_count: int,
        event: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], int]:
        """Append announce event while enforcing bounded history size."""
        normalized_events = list(events)
        if len(normalized_events) >= self._subagent_announce_max_events:
            normalized_events = normalized_events[-(self._subagent_announce_max_events - 1) :]
            dropped_count += 1
        normalized_events.append(event)
        return normalized_events, dropped_count

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
        """Build normalized completion announce payload from terminal run state."""
        outcome, status_text = cls._resolve_subagent_completion_outcome(run.status.value)
        result_text = (run.summary or fallback_summary or "").strip() or "(not available)"
        execution_time_ms = (
            run.execution_time_ms
            if run.execution_time_ms is not None
            else fallback_execution_time_ms
        )
        tokens_used = run.tokens_used if run.tokens_used is not None else fallback_tokens_used
        return {
            "run_id": run.run_id,
            "conversation_id": run.conversation_id,
            "subagent_name": run.subagent_name,
            "status": run.status.value,
            "outcome": outcome,
            "status_text": status_text,
            "result": result_text,
            "notes": run.error or "",
            "execution_time_ms": execution_time_ms,
            "tokens_used": tokens_used,
            "spawn_mode": spawn_mode,
            "thread_requested": bool(thread_requested),
            "cleanup": cleanup,
            "model_override": model_override,
            "thinking_override": thinking_override,
            "completed_at": run.ended_at.isoformat() if run.ended_at else None,
        }

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
        """Persist terminal announce payload with retry/backoff and bounded metadata."""
        from src.domain.model.agent.subagent_run import SubAgentRunStatus

        terminal_statuses = [
            SubAgentRunStatus.COMPLETED,
            SubAgentRunStatus.FAILED,
            SubAgentRunStatus.TIMED_OUT,
            SubAgentRunStatus.CANCELLED,
        ]
        attempts_used = 0
        last_error = "announce metadata update conflict"

        for attempt in range(max_retries + 1):
            attempts_used = attempt + 1
            run = self._subagent_run_registry.get_run(conversation_id, run_id)
            if not run or run.status not in terminal_statuses:
                return

            payload = self._build_subagent_completion_payload(
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
            announce_events = run.metadata.get("announce_events")
            if not isinstance(announce_events, list):
                announce_events = []
            dropped_count = int(run.metadata.get("announce_events_dropped") or 0)

            if attempt > 0:
                retry_event = {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "type": "completion_retry",
                    "attempt": attempt,
                    "run_id": run_id,
                    "reason": last_error,
                }
                announce_events, dropped_count = self._append_capped_announce_event(
                    announce_events, dropped_count, retry_event
                )

            delivered_event = {
                "timestamp": datetime.now(UTC).isoformat(),
                "type": "completion_delivered",
                "attempt": attempts_used,
                "run_id": run_id,
                "status": payload["status"],
            }
            announce_events, dropped_count = self._append_capped_announce_event(
                announce_events, dropped_count, delivered_event
            )

            try:
                updated_run = self._subagent_run_registry.attach_metadata(
                    conversation_id=conversation_id,
                    run_id=run_id,
                    metadata={
                        "announce_payload": payload,
                        "announce_status": "delivered",
                        "announce_attempt_count": attempts_used,
                        "announce_completed_at": datetime.now(UTC).isoformat(),
                        "announce_last_error": "",
                        "announce_events": announce_events,
                        "announce_events_dropped": dropped_count,
                    },
                    expected_statuses=terminal_statuses,
                )
            except Exception as exc:
                updated_run = None
                last_error = str(exc)
                logger.warning(
                    "Failed to attach completion announce metadata",
                    extra={
                        "conversation_id": conversation_id,
                        "run_id": run_id,
                        "attempt": attempts_used,
                    },
                    exc_info=True,
                )

            if updated_run is not None:
                return
            if not last_error:
                last_error = "announce metadata update conflict"

            if attempt < max_retries:
                delay_seconds = (self._subagent_announce_retry_delay_ms * (2**attempt)) / 1000.0
                await asyncio.sleep(delay_seconds)

        run = self._subagent_run_registry.get_run(conversation_id, run_id)
        if not run or run.status not in terminal_statuses:
            return
        announce_events = run.metadata.get("announce_events")
        if not isinstance(announce_events, list):
            announce_events = []
        dropped_count = int(run.metadata.get("announce_events_dropped") or 0)
        giveup_event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "type": "completion_giveup",
            "attempt": attempts_used,
            "run_id": run_id,
            "reason": last_error,
        }
        announce_events, dropped_count = self._append_capped_announce_event(
            announce_events, dropped_count, giveup_event
        )
        self._subagent_run_registry.attach_metadata(
            conversation_id=conversation_id,
            run_id=run_id,
            metadata={
                "announce_status": "giveup",
                "announce_attempt_count": attempts_used,
                "announce_last_error": last_error,
                "announce_events": announce_events,
                "announce_events_dropped": dropped_count,
            },
            expected_statuses=terminal_statuses,
        )

    async def _cancel_subagent_session(self, run_id: str) -> bool:
        """Cancel a detached SubAgent session by run_id."""
        task = self._subagent_session_tasks.get(run_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    @staticmethod
    def _topological_sort_subtasks(subtasks: list[Any]) -> list[Any]:
        """Sort subtasks by dependency order (topological sort)."""
        id_to_task = {st.id: st for st in subtasks}
        visited = set()
        result = []

        def visit(task_id: str) -> None:
            if task_id in visited:
                return
            visited.add(task_id)
            task = id_to_task.get(task_id)
            if task:
                for dep in task.dependencies:
                    visit(dep)
                result.append(task)

        for st in subtasks:
            visit(st.id)
        return result

    async def _execute_skill_directly(
        self,
        skill: Skill,
        query: str,
        project_id: str,
        user_id: str,
        tenant_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Execute skill directly via SkillOrchestrator.

        Delegates to SkillOrchestrator for modular implementation.

        Args:
            skill: Matched skill to execute
            query: User query
            project_id: Project ID for context
            user_id: User ID for context
            tenant_id: Tenant ID for context

        Yields:
            Event dictionaries for skill execution progress
        """
        # Delegate to SkillOrchestrator
        context = SkillExecutionContext(
            project_id=project_id,
            user_id=user_id,
            tenant_id=tenant_id,
            query=query,
        )

        async for event in self._skill_orchestrator.execute_directly(skill, context):
            yield event

    def _extract_sandbox_id_from_tools(self) -> str | None:
        """Extract sandbox_id from any available sandbox tool wrapper."""
        current_tools, _ = self._get_current_tools()
        for tool in current_tools.values():
            if hasattr(tool, "sandbox_id") and tool.sandbox_id:
                return tool.sandbox_id
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
        return self._event_converter.convert(domain_event)

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
