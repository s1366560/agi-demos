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
    AgentActEvent,
    AgentDomainEvent,
    AgentErrorEvent,
    AgentEventType,
    AgentObserveEvent,
    AgentSkillExecutionCompleteEvent,
    AgentStepEndEvent,
    AgentStepStartEvent,
    AgentThoughtEvent,
    AgentWorkPlanEvent,
)
from src.domain.model.agent.skill import Skill
from src.domain.model.agent.subagent import SubAgent

from ..context import ContextWindowConfig, ContextWindowManager
from ..permission import PermissionManager
from ..prompts import PromptContext, PromptMode, SystemPromptManager
from .processor import ProcessorConfig, SessionProcessor, ToolDefinition
from .skill_executor import SkillExecutor
from .subagent_router import SubAgentExecutor, SubAgentMatch, SubAgentRouter

if TYPE_CHECKING:
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
        tools: Dict[str, Any],  # Tool name -> Tool instance
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
            tools: Dictionary of tool name -> tool instance
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
            _cached_tool_definitions: Pre-cached tool definitions from Session Pool
            _cached_system_prompt_manager: Pre-cached SystemPromptManager singleton
            _cached_subagent_router: Pre-cached SubAgentRouter with built index
        """
        self.model = model
        self.raw_tools = tools
        self.api_key = api_key
        self.base_url = base_url
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_steps = max_steps
        self.permission_manager = permission_manager or PermissionManager()
        self.agent_mode = agent_mode  # Store agent mode for skill filtering
        self.project_root = project_root or Path.cwd()
        self.plan_mode_detector = plan_mode_detector  # Plan Mode detection

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

        # Convert tools to ToolDefinition - use cached definitions if provided
        if _cached_tool_definitions is not None:
            self.tool_definitions = _cached_tool_definitions
            logger.debug(
                f"ReActAgent: Using {len(_cached_tool_definitions)} cached tool definitions"
            )
        else:
            self.tool_definitions = self._convert_tools(tools)

        # Create processor config
        self.config = ProcessorConfig(
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            max_steps=max_steps,
        )

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

        Args:
            query: User query

        Returns:
            Tuple of (best matching skill or None, match score)
        """
        logger.info(f"[ReActAgent] _match_skill called with query: {query}")
        logger.info(
            f"[ReActAgent] Number of skills available: {len(self.skills) if self.skills else 0}"
        )
        logger.info(f"[ReActAgent] Agent mode: {self.agent_mode}")

        if not self.skills:
            logger.info("[ReActAgent] No skills available for matching")
            return None, 0.0

        best_skill = None
        best_score = 0.0

        for skill in self.skills:
            logger.debug(f"[ReActAgent] Checking skill: {skill.name}, status: {skill.status.value}")

            # Check agent mode accessibility
            if not skill.is_accessible_by_agent(self.agent_mode):
                logger.debug(
                    f"[ReActAgent] Skill {skill.name} not accessible by agent_mode={self.agent_mode}"
                )
                continue

            if skill.status.value != "active":
                continue

            # Use skill's matches_query method
            score = skill.matches_query(query)
            logger.debug(f"[ReActAgent] Skill {skill.name} match score: {score}")

            if score > best_score:
                best_score = score
                best_skill = skill

        if best_skill:
            logger.info(f"Matched skill: {best_skill.name} with score {best_score:.2f}")
        else:
            logger.info("[ReActAgent] No skill matched for query")

        return best_skill, best_score

    def _match_subagent(self, query: str) -> SubAgentMatch:
        """
        Match query against available subagents.

        Args:
            query: User query

        Returns:
            SubAgentMatch result
        """
        if not self.subagent_router:
            return SubAgentMatch(subagent=None, confidence=0.0, match_reason="No router")

        match = self.subagent_router.match(query, self.subagent_match_threshold)

        if match.subagent:
            logger.info(
                f"Matched subagent: {match.subagent.name} "
                f"with confidence {match.confidence:.2f} ({match.match_reason})"
            )

        return match

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

        # Convert tool definitions to dict format
        tool_defs = [{"name": t.name, "description": t.description} for t in self.tool_definitions]

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

        # Convert conversation context to OpenAI format
        context_messages = []
        for msg in conversation_context:
            context_messages.append(
                {
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", ""),
                }
            )

        # Add current user message
        context_messages.append(
            {
                "role": "user",
                "content": user_message,
            }
        )

        # Use ContextWindowManager for dynamic context sizing
        context_result = await self.context_manager.build_context_window(
            system_prompt=system_prompt,
            messages=context_messages,
            llm_client=None,  # TODO: Pass LLM client for summary generation
        )

        messages = context_result.messages

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

        # Determine tools to use
        tools_to_use = self.tool_definitions

        if active_subagent and self.subagent_router:
            # Filter tools based on SubAgent permissions
            filtered_tools = self.subagent_router.filter_tools(
                active_subagent,
                self.raw_tools,
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
            )

        # Create processor
        processor = SessionProcessor(
            config=config,
            tools=tools_to_use,
            permission_manager=self.permission_manager,
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
        Execute skill directly via SkillExecutor.

        This method handles the direct execution path where we bypass the LLM
        and execute the skill's tool chain directly.

        Args:
            skill: Matched skill to execute
            query: User query
            project_id: Project ID for context
            user_id: User ID for context
            tenant_id: Tenant ID for context

        Yields:
            Event dictionaries for skill execution progress
        """
        if not self.skill_executor:
            raise ValueError("SkillExecutor not initialized")

        logger.info(f"[ReActAgent] Direct executing skill: {skill.name}")

        # Build execution context
        context = {
            "project_id": project_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
        }

        # Try to extract sandbox_id from tools
        # Sandbox tools have a sandbox_id attribute on the wrapper
        sandbox_id = None
        for tool_name in skill.tools:
            if tool_name in self.tools and hasattr(self.tools[tool_name], "sandbox_id"):
                # Found a sandbox tool with explicit sandbox_id attribute
                sandbox_id = self.tools[tool_name].sandbox_id
                break

        # Emit skill execution start event
        yield {
            "type": "skill_execution_start",
            "data": {
                "skill_id": skill.id,
                "skill_name": skill.name,
                "tools": list(skill.tools),
                "total_steps": len(skill.tools),
            },
            "timestamp": datetime.utcnow().isoformat(),
        }

        tool_results = []
        current_step = 0

        # Execute skill and convert events (pass sandbox_id if available)
        async for domain_event in self.skill_executor.execute(
            skill, query, context, sandbox_id=sandbox_id
        ):
            # Convert SkillExecutor Domain events to our format
            converted_event = self._convert_skill_domain_event(domain_event, skill, current_step)

            if converted_event:
                yield converted_event

            # Track tool results from observe events (outside if block)
            if domain_event.event_type == AgentEventType.OBSERVE:
                tool_results.append(
                    {
                        "tool_name": domain_event.tool_name,
                        "result": domain_event.result,
                        "error": domain_event.error,
                        "duration_ms": domain_event.duration_ms,
                        "status": domain_event.status,
                    }
                )
                current_step += 1

            # Handle completion event (outside if block since converted_event is None for COMPLETE)
            if domain_event.event_type == AgentEventType.SKILL_EXECUTION_COMPLETE:
                # Type check for safety
                if isinstance(domain_event, AgentSkillExecutionCompleteEvent):
                    success = domain_event.success
                    error = domain_event.error
                    execution_time_ms = domain_event.execution_time_ms

                    # Generate summary from tool results
                    summary = self._summarize_skill_results(skill, tool_results, success, error)

                    # Emit skill execution complete event
                    yield {
                        "type": "skill_execution_complete",
                        "data": {
                            "skill_id": skill.id,
                            "skill_name": skill.name,
                            "success": success,
                            "summary": summary,
                            "tool_results": tool_results,
                            "execution_time_ms": execution_time_ms,
                            "error": error,
                        },
                        "timestamp": datetime.utcnow().isoformat(),
                    }

    def _convert_skill_domain_event(
        self,
        domain_event: AgentDomainEvent,
        skill: Skill,
        current_step: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Convert SkillExecutor Domain event to ReActAgent event format.

        Args:
            domain_event: Domain event from SkillExecutor
            skill: The skill being executed
            current_step: Current step index in the skill execution

        Returns:
            Converted event dict or None to skip
        """
        event_type = domain_event.event_type
        timestamp = datetime.fromtimestamp(domain_event.timestamp).isoformat()

        if event_type == AgentEventType.THOUGHT:
            # Assuming AgentThoughtEvent
            if isinstance(domain_event, AgentThoughtEvent):
                thought_level = domain_event.thought_level

                # Map skill thoughts to appropriate event types
                if thought_level == "skill":
                    return {
                        "type": "thought",
                        "data": {
                            "thought": domain_event.content,
                            "thought_level": "skill",
                            "skill_id": skill.id,
                        },
                        "timestamp": timestamp,
                    }
                elif thought_level == "skill_complete":
                    # Skill completion thought - handled separately
                    return None

                return {
                    "type": "thought",
                    "data": {
                        "thought": domain_event.content,
                        "thought_level": thought_level,
                    },
                    "timestamp": timestamp,
                }

        elif event_type == AgentEventType.ACT:
            if isinstance(domain_event, AgentActEvent):
                return {
                    "type": "skill_tool_start",
                    "data": {
                        "skill_id": skill.id,
                        "skill_name": skill.name,
                        "tool_name": domain_event.tool_name,
                        "tool_input": domain_event.tool_input or {},
                        "step_index": current_step,
                        "total_steps": len(skill.tools),
                        "status": domain_event.status,
                    },
                    "timestamp": timestamp,
                }

        elif event_type == AgentEventType.OBSERVE:
            if isinstance(domain_event, AgentObserveEvent):
                return {
                    "type": "skill_tool_result",
                    "data": {
                        "skill_id": skill.id,
                        "skill_name": skill.name,
                        "tool_name": domain_event.tool_name,
                        "result": domain_event.result,
                        "error": domain_event.error,
                        "duration_ms": domain_event.duration_ms or 0,
                        "step_index": current_step,
                        "total_steps": len(skill.tools),
                        "status": domain_event.status,
                    },
                    "timestamp": timestamp,
                }

        elif event_type == AgentEventType.SKILL_EXECUTION_COMPLETE:
            # Completion handled in _execute_skill_directly
            return None

        # Skip other event types
        return None

    def _summarize_skill_results(
        self,
        skill: Skill,
        tool_results: List[Dict[str, Any]],
        success: bool,
        error: Optional[str] = None,
    ) -> str:
        """
        Generate a summary from skill execution results.

        Args:
            skill: Executed skill
            tool_results: List of tool execution results
            success: Whether execution was successful
            error: Optional error message

        Returns:
            Human-readable summary string
        """
        if not success:
            failed_tool = None
            for result in tool_results:
                if result.get("status") == "error" or result.get("error"):
                    failed_tool = result.get("tool_name", "unknown")
                    break

            if error:
                return f"Skill '{skill.name}' failed: {error}"
            elif failed_tool:
                return f"Skill '{skill.name}' failed at tool '{failed_tool}'"
            else:
                return f"Skill '{skill.name}' execution failed"

        # Build summary from successful results
        summary_parts = [f"Completed skill '{skill.name}':"]

        for result in tool_results:
            tool_name = result.get("tool_name", "unknown")
            tool_result = result.get("result")

            if tool_result:
                # Truncate long results
                result_str = str(tool_result)
                if len(result_str) > 200:
                    result_str = result_str[:200] + "..."
                summary_parts.append(f"- {tool_name}: {result_str}")

        if len(summary_parts) == 1:
            return f"Skill '{skill.name}' completed successfully"

        return "\n".join(summary_parts)

    def _convert_domain_event(self, domain_event: AgentDomainEvent) -> Optional[Dict[str, Any]]:
        """
        Convert AgentDomainEvent to event dictionary format.

        Uses the unified to_event_dict() method with minimal customization
        for backward compatibility.

        Args:
            domain_event: AgentDomainEvent from processor

        Returns:
            Event dict or None to skip
        """
        event_type = domain_event.event_type

        # Debug log to track event conversion
        logger.info(f"[ReActAgent] Converting Domain event: type={event_type}")

        # Use unified serialization for most events
        event_dict = domain_event.to_event_dict()

        # Special handling for specific events to maintain backward compatibility

        # COMPLETE event is handled separately in stream()
        if event_type == AgentEventType.COMPLETE:
            return None

        # OBSERVE event: add redundant 'observation' field for legacy compat
        if event_type == AgentEventType.OBSERVE and isinstance(domain_event, AgentObserveEvent):
            observation = (
                domain_event.result
                if domain_event.result is not None
                else (domain_event.error or "")
            )
            event_dict["data"]["observation"] = observation

        # DOOM_LOOP_DETECTED: rename to 'doom_loop' for frontend compatibility
        if event_type == AgentEventType.DOOM_LOOP_DETECTED:
            event_dict["type"] = "doom_loop"

        # WORK_PLAN: data should be the plan directly
        if event_type == AgentEventType.WORK_PLAN and isinstance(domain_event, AgentWorkPlanEvent):
            event_dict["data"] = domain_event.plan

        # STEP_START: rename step_index to step_number
        if event_type == AgentEventType.STEP_START and isinstance(
            domain_event, AgentStepStartEvent
        ):
            event_dict["data"] = {
                "step_number": domain_event.step_index,
                "description": domain_event.description,
            }

        # STEP_END: rename step_index to step_number, add success flag
        if event_type == AgentEventType.STEP_END and isinstance(domain_event, AgentStepEndEvent):
            event_dict["data"] = {
                "step_number": domain_event.step_index,
                "success": domain_event.status == "completed",
            }

        # THOUGHT: rename content to thought
        if event_type == AgentEventType.THOUGHT and isinstance(domain_event, AgentThoughtEvent):
            event_dict["data"] = {
                "thought": domain_event.content,
                "thought_level": domain_event.thought_level,
            }

        # ACT: normalize call_id and tool_input
        if event_type == AgentEventType.ACT and isinstance(domain_event, AgentActEvent):
            event_dict["data"] = {
                "tool_name": domain_event.tool_name,
                "tool_input": domain_event.tool_input or {},
                "call_id": domain_event.call_id or "",
                "status": domain_event.status,
            }

        # ERROR: provide default code
        if event_type == AgentEventType.ERROR and isinstance(domain_event, AgentErrorEvent):
            event_dict["data"]["code"] = domain_event.code or "UNKNOWN"

        return event_dict

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

        # Create Plan Mode components
        generator = PlanGenerator(
            llm_client=llm_client,
            available_tools=self.tool_definitions,
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

        # Create wrapper instance
        session_processor = SessionProcessorWrapper(self.tool_definitions, self.permission_manager)

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
