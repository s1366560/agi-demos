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

import logging
import time
from datetime import datetime
from pathlib import Path

# Plan Mode detection
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Optional

from src.domain.events.agent_events import (
    AgentDomainEvent,
)
from src.domain.model.agent.hitl_types import HITLPendingException
from src.domain.model.agent.skill import Skill
from src.domain.model.agent.subagent import SubAgent
from src.domain.ports.agent.context_manager_port import ContextBuildRequest

from ..context import ContextFacade, ContextWindowConfig, ContextWindowManager
from ..events import EventConverter
from ..permission import PermissionManager
from ..prompts import PromptContext, PromptMode, SystemPromptManager
from ..routing import SubAgentOrchestrator, SubAgentOrchestratorConfig
from ..skill import SkillExecutionConfig, SkillExecutionContext, SkillOrchestrator
from .processor import ProcessorConfig, SessionProcessor, ToolDefinition
from .skill_executor import SkillExecutor
from .subagent_router import SubAgentExecutor, SubAgentMatch, SubAgentRouter

if TYPE_CHECKING:
    from src.application.services.artifact_service import ArtifactService

    from ..planning import HybridPlanModeDetector

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

    def __init__(
        self,
        model: str,
        tools: Optional[Dict[str, Any]] = None,  # Tool name -> Tool instance (static)
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        max_steps: int = 20,
        permission_manager: Optional[PermissionManager] = None,
        skills: Optional[List[Skill]] = None,
        subagents: Optional[List[SubAgent]] = None,
        # Skill matching thresholds - increased to let LLM make autonomous decisions
        # LLM sees skill_loader tool with available skills list and decides when to load
        # Rule-based matching is now a fallback for very high confidence matches only
        skill_match_threshold: float = 0.9,  # Was 0.5, increased to reduce rule matching
        skill_direct_execute_threshold: float = 0.95,  # Was 0.8, increased to favor LLM decision
        skill_fallback_on_error: bool = True,
        skill_execution_timeout: int = 300,  # Increased from 60 to 300 (5 minutes)
        subagent_match_threshold: float = 0.5,
        # Context window management
        context_window_config: Optional[ContextWindowConfig] = None,
        max_context_tokens: int = 128000,
        # Agent mode for skill filtering
        agent_mode: str = "default",
        # Project root for custom rules loading
        project_root: Optional[Path] = None,
        # Plan Mode detection
        plan_mode_detector: Optional["HybridPlanModeDetector"] = None,
        # Artifact service for rich output handling
        artifact_service: Optional["ArtifactService"] = None,
        # LLM client for unified resilience (circuit breaker + rate limiter)
        llm_client: Optional[Any] = None,
        # ====================================================================
        # Hot-plug support: Optional tool provider function for dynamic tools
        # When provided, tools are fetched at each stream() call instead of
        # being fixed at initialization time.
        # ====================================================================
        tool_provider: Optional[callable] = None,
        # ====================================================================
        # Agent Session Pool: Pre-cached components for performance optimization
        # These are internal parameters set by execute_react_agent_activity
        # when using the Agent Session Pool for component reuse.
        # ====================================================================
        _cached_tool_definitions: Optional[List[Any]] = None,
        _cached_system_prompt_manager: Optional[Any] = None,
        _cached_subagent_router: Optional[Any] = None,
    ):
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
            raise ValueError("Either 'tools', 'tool_provider', or '_cached_tool_definitions' must be provided")

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
        self.plan_mode_detector = plan_mode_detector  # Plan Mode detection
        self.artifact_service = artifact_service  # Artifact service for rich outputs
        self._llm_client = llm_client  # LLM client for unified resilience

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

        # Skill System (L2)
        self.skills = skills or []
        self.skill_match_threshold = skill_match_threshold
        self.skill_direct_execute_threshold = skill_direct_execute_threshold
        self.skill_fallback_on_error = skill_fallback_on_error
        self.skill_execution_timeout = skill_execution_timeout
        self.skill_executor = SkillExecutor(tools) if skills else None

        # SubAgent System (L3) - use cached router if provided
        self.subagents = subagents or []
        self.subagent_match_threshold = subagent_match_threshold
        if _cached_subagent_router is not None:
            self.subagent_router = _cached_subagent_router
            logger.debug("ReActAgent: Using cached SubAgentRouter")
        elif subagents:
            self.subagent_router = SubAgentRouter(
                subagents=subagents or [],
                default_confidence_threshold=subagent_match_threshold,
            )
        else:
            self.subagent_router = None

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
                default_confidence_threshold=subagent_match_threshold,
                emit_routing_events=True,
            ),
            base_model=model,
            base_api_key=api_key,
            base_url=base_url,
            debug_logging=False,
        )

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
            self.tool_definitions = self._convert_tools(self.raw_tools)
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

    def _get_current_tools(self) -> tuple[Dict[str, Any], List[ToolDefinition]]:
        """
        Get current tools - either from static tools or dynamic tool_provider.

        Returns:
            Tuple of (raw_tools dict, tool_definitions list)
        """
        if self._use_dynamic_tools and self._tool_provider is not None:
            # Hot-plug mode: fetch tools dynamically
            raw_tools = self._tool_provider()
            tool_definitions = self._convert_tools(raw_tools)
            logger.debug(f"ReActAgent: Dynamically loaded {len(tool_definitions)} tools")
            return raw_tools, tool_definitions
        else:
            # Static mode: use pre-converted tools
            return self.raw_tools, self.tool_definitions

    def _convert_tools(self, tools: Dict[str, Any]) -> List[ToolDefinition]:
        """
        Convert tool instances to ToolDefinition format.

        Args:
            tools: Dictionary of tool name -> tool instance

        Returns:
            List of ToolDefinition objects
        """
        definitions = []

        for name, tool in tools.items():
            # Extract tool metadata
            description = getattr(tool, "description", f"Tool: {name}")

            # Extract permission if available
            permission = getattr(tool, "permission", None)

            # Get parameters schema - prefer get_parameters_schema() method
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
                        # Try different execute method names
                        if hasattr(tool_instance, "execute"):
                            result = tool_instance.execute(**kwargs)
                            # Handle both sync and async execute
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
                    permission=permission,
                )
            )

        return definitions

    def _match_skill(self, query: str) -> tuple[Optional[Skill], float]:
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

    async def _build_system_prompt(
        self,
        user_query: str,
        conversation_context: List[Dict[str, str]],
        matched_skill: Optional[Skill] = None,
        subagent: Optional[SubAgent] = None,
        mode: str = "build",
        current_step: int = 1,
        project_id: str = "",
        tenant_id: str = "",
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
            }

        # Convert tool definitions to dict format - use current tools (hot-plug support)
        _, current_tool_definitions = self._get_current_tools()
        tool_defs = [{"name": t.name, "description": t.description} for t in current_tool_definitions]

        # Build prompt context
        context = PromptContext(
            model_provider=model_provider,
            mode=PromptMode(mode),
            tool_definitions=tool_defs,
            skills=skills_data,
            matched_skill=matched_skill_data,
            project_id=project_id,
            tenant_id=tenant_id,
            working_directory=str(self.project_root),
            conversation_history_length=len(conversation_context),
            user_query=user_query,
            current_step=current_step,
            max_steps=self.max_steps,
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
        conversation_context: Optional[List[Dict[str, str]]] = None,
        message_id: Optional[str] = None,
        attachment_content: Optional[List[Dict[str, Any]]] = None,
        attachment_metadata: Optional[List[Dict[str, Any]]] = None,
        hitl_response: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
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
            hitl_response: Optional HITL response for resuming from HITL pause

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

        # Check for Plan Mode triggering
        if self.plan_mode_detector:
            try:
                detection_result = await self.plan_mode_detector.detect(
                    query=user_message,
                    conversation_context=conversation_context,
                )

                # Emit plan_mode_triggered event
                yield {
                    "type": "plan_mode_triggered",
                    "data": {
                        "method": detection_result.method,
                        "confidence": detection_result.confidence,
                        "should_trigger": detection_result.should_trigger,
                    },
                    "timestamp": datetime.utcnow().isoformat(),
                }

                # If Plan Mode is triggered, execute it
                if detection_result.should_trigger:
                    logger.info(
                        f"[ReActAgent] Plan Mode triggered: method={detection_result.method}, "
                        f"confidence={detection_result.confidence}"
                    )
                    async for event in self._execute_plan_mode(
                        conversation_id=conversation_id,
                        user_message=user_message,
                        project_id=project_id,
                        user_id=user_id,
                        tenant_id=tenant_id,
                        conversation_context=conversation_context,
                        detection_result=detection_result,
                    ):
                        yield event
                    return  # Plan Mode completed, exit early
            except Exception as e:
                # Plan Mode detection/execution failed, fall back to regular ReAct
                logger.warning(
                    f"[ReActAgent] Plan Mode failed with error: {e}, falling back to regular ReAct"
                )
                yield {
                    "type": "plan_mode_failed",
                    "data": {
                        "error": str(e),
                        "fallback": "react",
                    },
                    "timestamp": datetime.utcnow().isoformat(),
                }

        # Check for SubAgent routing (L3)
        subagent_match = self._match_subagent(user_message)
        active_subagent = subagent_match.subagent

        if active_subagent:
            yield {
                "type": "subagent_routed",
                "data": {
                    "subagent_id": active_subagent.id,
                    "subagent_name": active_subagent.display_name,
                    "confidence": subagent_match.confidence,
                    "reason": subagent_match.match_reason,
                },
                "timestamp": datetime.utcnow().isoformat(),
            }

        # Check for Skill matching (L2)
        matched_skill, skill_score = self._match_skill(user_message)

        # Determine execution mode based on match score
        should_direct_execute = (
            matched_skill is not None
            and skill_score >= self.skill_direct_execute_threshold
            and self.skill_executor is not None
        )

        should_inject_prompt = (
            matched_skill is not None
            and skill_score >= self.skill_match_threshold
            and not should_direct_execute
        )

        # If score is too low, don't use skill at all
        if matched_skill and skill_score < self.skill_match_threshold:
            matched_skill = None
            skill_score = 0.0

        # Emit skill_matched event with execution mode
        if matched_skill:
            execution_mode = "direct" if should_direct_execute else "prompt"
            yield {
                "type": "skill_matched",
                "data": {
                    "skill_id": matched_skill.id,
                    "skill_name": matched_skill.name,
                    "tools": list(matched_skill.tools),
                    "match_score": skill_score,
                    "execution_mode": execution_mode,
                },
                "timestamp": datetime.utcnow().isoformat(),
            }

        # Path A: Direct skill execution via SkillExecutor
        if should_direct_execute:
            skill_success = False
            skill_execution_result = None

            try:
                async for skill_event in self._execute_skill_directly(
                    matched_skill,
                    user_message,
                    project_id,
                    user_id,
                    tenant_id,
                ):
                    yield skill_event

                    # Capture final result
                    if skill_event.get("type") == "skill_execution_complete":
                        skill_execution_result = skill_event.get("data", {})
                        skill_success = skill_execution_result.get("success", False)

                # Record skill usage
                matched_skill.record_usage(skill_success)

                if skill_success:
                    # Success: return skill result directly
                    yield {
                        "type": "complete",
                        "data": {
                            "content": skill_execution_result.get("summary", ""),
                            "skill_used": matched_skill.name,
                            "execution_mode": "direct",
                        },
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                    return  # Early exit, skip LLM flow

                elif not self.skill_fallback_on_error:
                    # Failed and no fallback allowed
                    yield {
                        "type": "error",
                        "data": {
                            "message": f"Skill execution failed: "
                            f"{skill_execution_result.get('error', 'Unknown error')}",
                            "code": "SKILL_EXECUTION_FAILED",
                        },
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                    return

                else:
                    # Failed but fallback allowed - continue to LLM flow
                    logger.warning(
                        f"Skill {matched_skill.name} execution failed, falling back to LLM"
                    )
                    yield {
                        "type": "skill_fallback",
                        "data": {
                            "skill_name": matched_skill.name,
                            "reason": "execution_failed",
                            "error": (
                                skill_execution_result.get("error")
                                if skill_execution_result
                                else None
                            ),
                        },
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                    # Inject partial results into context
                    if skill_execution_result and skill_execution_result.get("tool_results"):
                        conversation_context.append(
                            {
                                "role": "system",
                                "content": f"Skill '{matched_skill.name}' attempted but failed. "
                                f"Partial results: {skill_execution_result.get('tool_results', [])}",
                            }
                        )
                    # Reset matched_skill for prompt injection since we're falling back
                    should_inject_prompt = True

            except Exception as e:
                logger.error(f"Skill direct execution error: {e}", exc_info=True)
                matched_skill.record_usage(False)

                if not self.skill_fallback_on_error:
                    yield {
                        "type": "error",
                        "data": {
                            "message": str(e),
                            "code": "SKILL_EXECUTION_ERROR",
                        },
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                    return

                # Fallback to LLM
                yield {
                    "type": "skill_fallback",
                    "data": {
                        "skill_name": matched_skill.name,
                        "reason": "execution_error",
                        "error": str(e),
                    },
                    "timestamp": datetime.utcnow().isoformat(),
                }
                should_inject_prompt = True

        # Path B: Prompt injection mode (existing logic) or fallback from direct execution

        # Build system prompt (uses SubAgent prompt if routed)
        # Only inject skill into prompt if should_inject_prompt is True
        system_prompt = await self._build_system_prompt(
            user_message,
            conversation_context,
            matched_skill=matched_skill if should_inject_prompt else None,
            subagent=active_subagent,
            mode=self.agent_mode if self.agent_mode in ["build", "plan"] else "build",
            current_step=1,  # Initial step
            project_id=project_id,
            tenant_id=tenant_id,
        )

        # Build context using ContextFacade - replaces inline message building
        # and attachment injection (was ~115 lines, now ~10 lines)
        context_request = ContextBuildRequest(
            system_prompt=system_prompt,
            conversation_context=conversation_context,
            user_message=user_message,
            attachment_metadata=attachment_metadata,
            attachment_content=attachment_content,
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
                "timestamp": datetime.utcnow().isoformat(),
            }
            logger.info(
                f"Context compressed: {context_result.original_message_count} -> "
                f"{context_result.final_message_count} messages, "
                f"strategy: {context_result.compression_strategy.value}"
            )

        # Determine tools to use - hot-plug support: fetch current tools
        current_raw_tools, current_tool_definitions = self._get_current_tools()
        tools_to_use = current_tool_definitions

        if active_subagent and self.subagent_router:
            # Filter tools based on SubAgent permissions
            filtered_tools = self.subagent_router.filter_tools(
                active_subagent,
                current_raw_tools,
            )
            tools_to_use = self._convert_tools(filtered_tools)

        # Determine config (may be overridden by SubAgent)
        config = self.config

        if active_subagent:
            executor = SubAgentExecutor(
                subagent=active_subagent,
                base_model=self.model,
                base_api_key=self.api_key,
                base_url=self.base_url,
            )
            subagent_config = executor.get_config()

            config = ProcessorConfig(
                model=subagent_config.get("model") or self.model,
                api_key=self.api_key,
                base_url=self.base_url,
                temperature=subagent_config.get("temperature", self.temperature),
                max_tokens=subagent_config.get("max_tokens", self.max_tokens),
                max_steps=subagent_config.get("max_iterations", self.max_steps),
                llm_client=self._llm_client,  # Pass client to subagent processor
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
            "hitl_response": hitl_response,  # Pass HITL response for resume
        }

        try:
            # Process and convert Domain events to legacy format
            async for domain_event in processor.process(
                session_id=conversation_id,
                messages=messages,
                langfuse_context=langfuse_context,
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

            # Yield final complete event
            yield {
                "type": "complete",
                "data": {
                    "content": final_content,
                    "subagent_used": active_subagent.name if active_subagent else None,
                    "skill_used": matched_skill.name if matched_skill else None,
                },
                "timestamp": datetime.utcnow().isoformat(),
            }

        except HITLPendingException:
            # Let HITLPendingException bubble up to Activity layer
            # The Workflow will wait for user response and resume execution
            raise

        except Exception as e:
            logger.error(f"[ReActAgent] Error in stream: {e}", exc_info=True)
            success = False
            yield {
                "type": "error",
                "data": {
                    "message": str(e),
                    "code": type(e).__name__,
                },
                "timestamp": datetime.utcnow().isoformat(),
            }

        finally:
            # Record execution statistics
            end_time = time.time()
            execution_time_ms = int((end_time - start_time) * 1000)

            if active_subagent:
                active_subagent.record_execution(execution_time_ms, success)
                logger.info(
                    f"[ReActAgent] SubAgent {active_subagent.name} execution: "
                    f"{execution_time_ms}ms, success={success}"
                )

            if matched_skill:
                matched_skill.record_usage(success)
                logger.info(
                    f"[ReActAgent] Skill {matched_skill.name} usage recorded: success={success}"
                )

    async def _execute_skill_directly(
        self,
        skill: Skill,
        query: str,
        project_id: str,
        user_id: str,
        tenant_id: str,
    ) -> AsyncIterator[Dict[str, Any]]:
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

    def _convert_domain_event(self, domain_event: AgentDomainEvent) -> Optional[Dict[str, Any]]:
        """
        Convert AgentDomainEvent to event dictionary format.

        Delegates to EventConverter for modular implementation.

        Args:
            domain_event: AgentDomainEvent from processor

        Returns:
            Event dict or None to skip
        """
        # Delegate to EventConverter
        return self._event_converter.convert(domain_event)

    async def _execute_plan_mode(
        self,
        conversation_id: str,
        user_message: str,
        project_id: str,
        user_id: str,
        tenant_id: str,
        conversation_context: List[Dict[str, str]],
        detection_result: Any,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Execute Plan Mode workflow.

        This method implements the Plan Mode execution path:
        1. Generate execution plan using PlanGenerator
        2. Execute plan steps using PlanExecutor
        3. Reflect and optionally adjust using PlanReflector
        4. Emit events for frontend updates

        Args:
            conversation_id: Conversation ID
            user_message: User's query
            project_id: Project ID
            user_id: User ID
            tenant_id: Tenant ID
            conversation_context: Conversation history
            detection_result: Detection result from detector

        Yields:
            Event dictionaries for Plan Mode execution
        """
        from src.configuration.config import get_settings
        from src.infrastructure.llm.litellm.litellm_client import LiteLLMClient

        from ..planning.plan_adjuster import PlanAdjuster
        from ..planning.plan_executor import PlanExecutor
        from ..planning.plan_generator import PlanGenerator
        from ..planning.plan_mode_orchestrator import PlanModeOrchestrator
        from ..planning.plan_reflector import PlanReflector

        logger.info("[ReActAgent] Executing Plan Mode workflow")

        # Emit plan_mode_entered event
        yield {
            "type": "plan_mode_entered",
            "data": {
                "conversation_id": conversation_id,
                "method": detection_result.method,
                "confidence": detection_result.confidence,
            },
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Create LLM client for Plan Mode components
        settings = get_settings()
        llm_client = LiteLLMClient(
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
        )

        # Get current tools (hot-plug support)
        _, current_tool_definitions = self._get_current_tools()

        # Create Plan Mode components
        generator = PlanGenerator(
            llm_client=llm_client,
            available_tools=current_tool_definitions,
        )

        # Create a simple session processor wrapper for tool execution
        class SessionProcessorWrapper:
            def __init__(wrapper_self, tools, permission_manager):
                wrapper_self.tools = tools
                wrapper_self.permission_manager = permission_manager

            async def execute_tool(
                wrapper_self, tool_name: str, tool_input: Dict, conversation_id: str
            ) -> str:
                """Execute a tool by name."""
                if tool_name == "__think__":
                    return f"Thought: {tool_input.get('thought', '')}"

                # Find the tool
                tool = None
                for t in wrapper_self.tools:
                    if t.name == tool_name:
                        tool = t
                        break

                if not tool:
                    return f"Error: Tool '{tool_name}' not found"

                # Execute the tool
                try:
                    result = await tool.execute(**tool_input)
                    return str(result) if result else ""
                except Exception as e:
                    return f"Error executing {tool_name}: {str(e)}"

        # Create wrapper instance (use current_tool_definitions from above)
        session_processor = SessionProcessorWrapper(current_tool_definitions, self.permission_manager)

        # Event emitter for Plan Mode events
        plan_events = []

        def event_emitter(event):
            plan_events.append(event)
            logger.debug(f"[PlanMode] Event emitted: {event['type']}")

        # Create executor with event emitter
        executor = PlanExecutor(
            session_processor=session_processor,
            event_emitter=event_emitter,
            parallel_execution=False,  # Sequential execution for stability
            max_parallel_steps=1,
        )

        reflector = PlanReflector(
            llm_client=llm_client,
            max_tokens=2048,
        )

        adjuster = PlanAdjuster()

        # Create orchestrator
        orchestrator = PlanModeOrchestrator(
            plan_generator=generator,
            plan_executor=executor,
            plan_reflector=reflector,
            plan_adjuster=adjuster,
            event_emitter=event_emitter,
            max_reflection_cycles=3,
        )

        try:
            # Generate plan
            logger.info("[ReActAgent] Generating execution plan")
            yield {
                "type": "plan_generation_started",
                "data": {
                    "conversation_id": conversation_id,
                    "query": user_message[:100],
                },
                "timestamp": datetime.utcnow().isoformat(),
            }

            plan = await generator.generate_plan(
                conversation_id=conversation_id,
                query=user_message,
                context=conversation_context,
                reflection_enabled=True,
                max_reflection_cycles=3,
            )

            # Emit plan_generated event
            yield {
                "type": "plan_generated",
                "data": {
                    "plan_id": plan.id,
                    "title": f"Plan for: {user_message[:50]}...",
                    "status": plan.status.value,
                    "steps": [
                        {
                            "step_id": step.step_id,
                            "description": step.description,
                            "tool_name": step.tool_name,
                            "status": step.status.value,
                            "dependencies": step.dependencies,
                        }
                        for step in plan.steps
                    ],
                },
                "timestamp": datetime.utcnow().isoformat(),
            }

            # Execute plan with orchestrator
            logger.info(f"[ReActAgent] Executing plan with {len(plan.steps)} steps")
            yield {
                "type": "plan_execution_started",
                "data": {
                    "plan_id": plan.id,
                    "step_count": len(plan.steps),
                },
                "timestamp": datetime.utcnow().isoformat(),
            }

            # Stream plan events during execution
            for event in plan_events:
                yield self._convert_plan_event(event)
            plan_events.clear()

            # Execute the plan
            final_plan = await orchestrator.execute_plan(plan=plan)

            # Emit any remaining events
            for event in plan_events:
                yield self._convert_plan_event(event)

            # Emit plan_complete event
            completed_steps = sum(1 for s in final_plan.steps if s.status.value == "completed")
            failed_steps = sum(1 for s in final_plan.steps if s.status.value == "failed")

            yield {
                "type": "plan_complete",
                "data": {
                    "plan_id": final_plan.id,
                    "status": final_plan.status.value,
                    "summary": f"Plan execution completed. "
                    f"Completed: {completed_steps}, Failed: {failed_steps}",
                    "completed_steps": completed_steps,
                    "failed_steps": failed_steps,
                    "total_steps": len(final_plan.steps),
                },
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"[ReActAgent] Plan Mode execution failed: {e}", exc_info=True)
            yield {
                "type": "plan_execution_failed",
                "data": {
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
                "timestamp": datetime.utcnow().isoformat(),
            }

    def _convert_plan_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert internal Plan Mode event to SSE event format.

        Args:
            event: Internal event from Plan Mode components

        Returns:
            SSE-compatible event dict
        """
        event_type = event.get("type", "unknown")

        # Map internal event types to SSE types
        type_mapping = {
            "PLAN_EXECUTION_START": "plan_execution_start",
            "PLAN_STEP_READY": "plan_step_ready",
            "PLAN_STEP_COMPLETE": "plan_step_complete",
            "PLAN_STEP_SKIPPED": "plan_step_skipped",
            "PLAN_EXECUTION_COMPLETE": "plan_execution_complete",
            "REFLECTION_COMPLETE": "reflection_complete",
            "ADJUSTMENT_APPLIED": "adjustment_applied",
        }

        return {
            "type": type_mapping.get(event_type, event_type.lower()),
            "data": event.get("data", {}),
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def astream_multi_level(
        self,
        conversation_id: str,
        project_id: str,
        user_id: str,
        tenant_id: str,
        user_query: str,
        conversation_context: Optional[List[Dict[str, str]]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
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
    tools: Dict[str, Any],
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    skills: Optional[List[Skill]] = None,
    subagents: Optional[List[SubAgent]] = None,
    **kwargs,
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
