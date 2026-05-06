# pyright: reportUninitializedInstanceVariable=false
"""LifecycleMixin: ``_init_*`` helpers extracted from :class:`ReActAgent`.

Pure code move — no behavior change.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, Protocol

from src.domain.model.agent.skill import Skill
from src.domain.model.agent.subagent import SubAgent

from ..config import ExecutionConfig
from ..context import ContextFacade, ContextWindowConfig, ContextWindowManager
from ..events import EventConverter
from ..plugins.policy_context import normalize_policy_layers
from ..plugins.registry import get_plugin_registry
from ..plugins.selection_pipeline import build_default_tool_selection_pipeline
from ..prompts import SystemPromptManager
from .processor import ProcessorConfig, ToolDefinition
from .subagent_router import SubAgentRouter
from .tool_converter import convert_tools

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class _LifecycleAgent(Protocol):
    """Subset of :class:`ReActAgent` used by :class:`LifecycleMixin`."""

    project_root: Any
    raw_tools: Any
    skills: Any
    config: Any
    prompt_manager: Any
    context_manager: Any
    context_facade: Any
    tool_definitions: Any
    subagents: Any
    subagent_router: Any
    subagent_match_threshold: Any
    skill_match_threshold: Any
    skill_fallback_on_error: Any
    skill_execution_timeout: Any
    _tool_builder: Any
    _tool_provider: Any
    _llm_client: Any
    _span_service: Any
    _fork_merge_service: Any
    _tool_selection_pipeline: Any
    _tool_selection_max_tools: Any
    _tool_selection_semantic_backend: Any
    _router_mode_tool_count_threshold: Any
    _tool_policy_layers: Any
    _last_tool_selection_trace: Any
    _memory_runtime: Any
    _session_factory: Any
    _stream_skill_state: Any
    _stream_memory_context: Any
    _stream_context_result: Any
    _stream_messages: Any
    _stream_cached_summary: Any
    _stream_tools_to_use: Any
    _stream_final_content: Any
    _stream_success: Any
    _filesystem_skills_loaded: Any
    _skill_mcp_manager: Any
    _skill_mcp_tools: Any
    _enable_subagent_as_tool: Any
    _max_subagent_delegation_depth: Any
    _max_subagent_active_runs: Any
    _max_subagent_children_per_requester: Any
    _max_subagent_active_runs_per_lineage: Any
    _max_subagent_lane_concurrency: Any
    _subagent_announce_max_events: Any
    _subagent_announce_max_retries: Any
    _subagent_announce_retry_delay_ms: Any
    _subagent_lane_semaphore: Any
    _subagent_lifecycle_hook: Any
    _subagent_lifecycle_hook_failures: Any
    _subagent_run_registry: Any
    _subagent_session_tasks: Any
    _event_converter: Any
    _background_executor: Any
    _template_registry: Any
    _result_aggregator: Any
    _use_dynamic_tools: Any

    def _get_current_tools(self, *args: Any, **kwargs: Any) -> Any: ...
    def _get_subagent_observability_stats(self, *args: Any, **kwargs: Any) -> Any: ...
    def _execute_subagent(self, *args: Any, **kwargs: Any) -> Any: ...
    def _launch_subagent_session(self, *args: Any, **kwargs: Any) -> Any: ...
    def _cancel_subagent_session(self, *args: Any, **kwargs: Any) -> Any: ...
    def _init_subagent_router(self, *args: Any, **kwargs: Any) -> None: ...
    def _init_subagent_run_registry(self, *args: Any, **kwargs: Any) -> None: ...


class LifecycleMixin:
    """Mixin housing the ``_init_*`` family + ``_reset_stream_state`` + ``_load_filesystem_skills``."""

    def _init_tool_pipeline(
        self: _LifecycleAgent,
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
        self: _LifecycleAgent,
        *,
        memory_runtime: Any,
        session_factory: Any,
    ) -> None:
        """Initialize memory runtime and its supporting infrastructure."""
        self._memory_runtime = memory_runtime
        self._session_factory = session_factory

    def _reset_stream_state(self: _LifecycleAgent) -> None:
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
        self: _LifecycleAgent,
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
        self: _LifecycleAgent,
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
        self: _LifecycleAgent,
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
        self: _LifecycleAgent,
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

    def _init_subagent_system(
        self: _LifecycleAgent,
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
        self: _LifecycleAgent,
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
        self: _LifecycleAgent,
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

    def _init_orchestrators(self: _LifecycleAgent) -> None:
        """Initialize orchestrators for modular components."""
        self._event_converter = EventConverter(debug_logging=False)

    def _init_background_services(self: _LifecycleAgent, llm_client: Any | None) -> None:
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
        self: _LifecycleAgent,
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
