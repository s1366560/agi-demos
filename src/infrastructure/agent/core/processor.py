"""
Session Processor - Core ReAct agent processing loop.

Orchestrates the complete agent execution cycle:
1. Receives user message
2. Calls LLM for reasoning and action
3. Executes tool calls
4. Observes results
5. Continues until task complete or blocked

Integrates all core components:
- LLMStream for streaming LLM responses
- DoomLoopDetector for detecting repeated patterns
- RetryPolicy for intelligent error handling
- CostTracker for real-time cost calculation
- PermissionManager for tool permission control

Reference: OpenCode's SessionProcessor in processor.ts (406 lines)
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from ..cost import CostTracker, TokenUsage
from ..doom_loop import DoomLoopDetector
from ..permission import PermissionAction, PermissionManager
from ..retry import RetryPolicy
from .events import SSEEvent, SSEEventType
from .llm_stream import LLMStream, StreamConfig, StreamEventType
from .message import Message, MessageRole, ToolPart, ToolState

logger = logging.getLogger(__name__)


class ProcessorState(str, Enum):
    """Session processor state."""

    IDLE = "idle"
    THINKING = "thinking"
    ACTING = "acting"
    OBSERVING = "observing"
    WAITING_PERMISSION = "waiting_permission"
    WAITING_CLARIFICATION = "waiting_clarification"  # Waiting for user clarification
    WAITING_DECISION = "waiting_decision"  # Waiting for user decision
    RETRYING = "retrying"
    COMPLETED = "completed"
    ERROR = "error"


class ProcessorResult(str, Enum):
    """Result of processor execution."""

    CONTINUE = "continue"  # Continue processing (tool calls pending)
    STOP = "stop"  # Stop processing (blocked or error)
    COMPACT = "compact"  # Need context compaction
    COMPLETE = "complete"  # Task completed successfully


@dataclass
class ProcessorConfig:
    """Configuration for session processor."""

    # Model configuration
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.0
    max_tokens: int = 4096

    # Processing limits
    max_steps: int = 50  # Maximum steps before forcing stop
    max_tool_calls_per_step: int = 10  # Max tool calls per LLM response
    doom_loop_threshold: int = 3  # Consecutive identical calls to trigger

    # Retry configuration
    max_attempts: int = 5
    initial_delay_ms: int = 2000

    # Permission configuration
    permission_timeout: float = 300.0  # seconds
    continue_on_deny: bool = False  # Continue loop if permission denied

    # Cost tracking
    context_limit: int = 200000  # Token limit before compaction warning


@dataclass
class ToolDefinition:
    """Tool definition for LLM."""

    name: str
    description: str
    parameters: Dict[str, Any]
    execute: Callable[..., Any]  # Async callable
    permission: Optional[str] = None  # Permission required

    def to_openai_format(self) -> Dict[str, Any]:
        """Convert to OpenAI tool format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class SessionProcessor:
    """
    Core ReAct agent processing loop.

    Manages the complete agent execution cycle with:
    - Streaming LLM responses
    - Tool execution with permission control
    - Doom loop detection
    - Intelligent retry with backoff
    - Real-time cost tracking
    - SSE event emission

    Usage:
        processor = SessionProcessor(config, tools)
        async for event in processor.process(session_id, messages):
            yield event.to_sse_format()
    """

    def __init__(
        self,
        config: ProcessorConfig,
        tools: List[ToolDefinition],
        permission_manager: Optional[PermissionManager] = None,
    ):
        """
        Initialize session processor.

        Args:
            config: Processor configuration
            tools: List of available tools
            permission_manager: Optional permission manager (creates default if None)
        """
        self.config = config
        self.tools = {t.name: t for t in tools}

        # Initialize components
        self.permission_manager = permission_manager or PermissionManager()
        self.doom_loop_detector = DoomLoopDetector(threshold=config.doom_loop_threshold)
        self.retry_policy = RetryPolicy(
            max_attempts=config.max_attempts,
            initial_delay_ms=config.initial_delay_ms,
        )
        self.cost_tracker = CostTracker()

        # Session state
        self._state = ProcessorState.IDLE
        self._step_count = 0
        self._current_message: Optional[Message] = None
        self._pending_tool_calls: Dict[str, ToolPart] = {}
        self._abort_event: Optional[asyncio.Event] = None

        # Work plan tracking
        self._work_plan_id: Optional[str] = None
        self._work_plan_steps: List[Dict[str, Any]] = []
        self._current_plan_step: int = 0
        self._tool_to_step_mapping: Dict[str, int] = {}  # tool_name -> step_number

        # Langfuse observability context
        self._langfuse_context: Optional[Dict[str, Any]] = None

    @property
    def state(self) -> ProcessorState:
        """Get current processor state."""
        return self._state

    async def process(
        self,
        session_id: str,
        messages: List[Dict[str, Any]],
        abort_signal: Optional[asyncio.Event] = None,
        langfuse_context: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[SSEEvent]:
        """
        Process a conversation turn.

        Runs the ReAct loop:
        1. Call LLM with messages
        2. Process response (text, reasoning, tool calls)
        3. Execute tool calls if any
        4. Continue until complete or blocked

        Args:
            session_id: Session identifier
            messages: Conversation messages in OpenAI format
            abort_signal: Optional abort signal
            langfuse_context: Optional context for Langfuse tracing containing:
                - conversation_id: Unique conversation identifier
                - user_id: User identifier
                - tenant_id: Tenant identifier for multi-tenant isolation
                - project_id: Project identifier
                - extra: Additional metadata dict

        Yields:
            SSEEvent objects for real-time streaming
        """
        self._abort_event = abort_signal or asyncio.Event()
        self._step_count = 0
        self._langfuse_context = langfuse_context  # Store for use in _process_step

        # Reset work plan tracking
        self._work_plan_id = str(uuid.uuid4())
        self._work_plan_steps = []
        self._current_plan_step = 0
        self._tool_to_step_mapping = {}

        # Emit start event
        yield SSEEvent.start()
        self._state = ProcessorState.THINKING

        # Generate and emit work plan based on available tools and user query
        user_query = self._extract_user_query(messages)
        if user_query and self.tools:
            work_plan_data = await self._generate_work_plan(user_query, messages)
            if work_plan_data:
                yield SSEEvent.work_plan(work_plan_data)

        try:
            result = ProcessorResult.CONTINUE

            while result == ProcessorResult.CONTINUE:
                # Check abort
                if self._abort_event.is_set():
                    yield SSEEvent.error("Processing aborted", code="ABORTED")
                    self._state = ProcessorState.ERROR
                    return

                # Check step limit
                self._step_count += 1
                if self._step_count > self.config.max_steps:
                    yield SSEEvent.error(
                        f"Maximum steps ({self.config.max_steps}) exceeded",
                        code="MAX_STEPS_EXCEEDED",
                    )
                    self._state = ProcessorState.ERROR
                    return

                # Process one step
                async for event in self._process_step(session_id, messages):
                    yield event

                    # Check for stop conditions in events
                    if event.type == SSEEventType.ERROR:
                        result = ProcessorResult.STOP
                        break
                    elif event.type == SSEEventType.STEP_FINISH:
                        # Check finish reason
                        finish_reason = event.data.get("finish_reason", "")
                        if finish_reason == "stop":
                            result = ProcessorResult.COMPLETE
                        elif finish_reason == "tool_calls":
                            result = ProcessorResult.CONTINUE
                        else:
                            result = ProcessorResult.COMPLETE
                    elif event.type == SSEEventType.COMPACT_NEEDED:
                        result = ProcessorResult.COMPACT
                        break

                # If we have pending tool results, add them to messages
                if result == ProcessorResult.CONTINUE and self._current_message:
                    # Add assistant message with tool calls
                    messages.append(self._current_message.to_llm_format())

                    # Add tool results
                    for part in self._current_message.get_tool_parts():
                        if part.status == ToolState.COMPLETED:
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": part.call_id,
                                    "content": part.output or "",
                                }
                            )
                        elif part.status == ToolState.ERROR:
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": part.call_id,
                                    "content": f"Error: {part.error}",
                                }
                            )

            # Emit completion
            if result == ProcessorResult.COMPLETE:
                # Build trace URL if Langfuse context is available
                trace_url = None
                if self._langfuse_context:
                    from src.configuration.config import get_settings

                    settings = get_settings()
                    if settings.langfuse_enabled and settings.langfuse_host:
                        trace_id = self._langfuse_context.get("conversation_id", session_id)
                        trace_url = f"{settings.langfuse_host}/trace/{trace_id}"
                yield SSEEvent.complete(trace_url=trace_url)
                self._state = ProcessorState.COMPLETED
            elif result == ProcessorResult.COMPACT:
                yield SSEEvent.status("compact_needed")

        except Exception as e:
            logger.error(f"Processor error: {e}", exc_info=True)
            yield SSEEvent.error(str(e), code=type(e).__name__)
            self._state = ProcessorState.ERROR

    def _extract_user_query(self, messages: List[Dict[str, Any]]) -> Optional[str]:
        """Extract the latest user query from messages."""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                return msg.get("content", "")
        return None

    def _classify_tool_by_description(self, tool_name: str, tool_def: ToolDefinition) -> str:
        """
        Classify tool into a category based on its description.

        Uses semantic keywords in the tool's description to determine its purpose,
        supporting dynamic tool addition via MCP or Skills without hardcoded names.

        Args:
            tool_name: Name of the tool
            tool_def: Tool definition with description

        Returns:
            Category string: "search", "scrape", "memory", "entity", "graph", "code", "summary", "other"
        """
        description = tool_def.description.lower()

        # Search tools: find information from web, databases, etc.
        search_keywords = ["search", "搜索", "查找", "find", "query", "查询", "bing", "google"]
        if any(kw in description for kw in search_keywords) and "web" in description:
            return "search"

        # Scrape tools: extract content from web pages
        scrape_keywords = ["scrape", "抓取", "extract", "提取", "fetch", "获取", "crawl", "爬取"]
        if any(kw in description for kw in scrape_keywords) and any(
            w in description for w in ["web", "page", "网页", "html", "url"]
        ):
            return "scrape"

        # Memory tools: access knowledge base
        memory_keywords = ["memory", "记忆", "knowledge", "知识", "recall", "回忆", "episodic"]
        if any(kw in description for kw in memory_keywords):
            return "memory"

        # Entity tools: lookup entities in knowledge graph
        entity_keywords = ["entity", "实体", "lookup", "查找"]
        if any(kw in description for kw in entity_keywords):
            return "entity"

        # Graph tools: query knowledge graph
        graph_keywords = ["graph", "图谱", "cypher", "relationship", "关系", "node", "节点"]
        if any(kw in description for kw in graph_keywords):
            return "graph"

        # Code tools: execute code
        code_keywords = ["code", "代码", "execute", "执行", "run", "运行", "python", "script"]
        if any(kw in description for kw in code_keywords):
            return "code"

        # Summary tools: summarize or synthesize information
        summary_keywords = ["summary", "总结", "summarize", "概括", "synthesize", "综合"]
        if any(kw in description for kw in summary_keywords):
            return "summary"

        return "other"

    async def _generate_work_plan(
        self,
        user_query: str,
        messages: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Generate a work plan based on user query and available tools.

        This creates a simple work plan that shows the expected execution flow
        to the user, improving transparency of the ReAct agent's process.

        Uses semantic classification of tools based on their descriptions,
        supporting dynamic tool addition via MCP or Skills.

        Args:
            user_query: The user's query
            messages: Full conversation context

        Returns:
            Work plan data dictionary for SSE event, or None if no plan needed
        """
        if not self.tools:
            return None

        # Classify all available tools by their semantic purpose
        tool_categories = {}
        for tool_name, tool_def in self.tools.items():
            category = self._classify_tool_by_description(tool_name, tool_def)
            if category not in tool_categories:
                tool_categories[category] = []
            tool_categories[category].append(tool_name)

        # Create a simple plan based on common tool patterns
        steps = []
        step_number = 0

        # Analyze query to predict likely tool usage
        query_lower = user_query.lower()

        # Pattern matching for common workflows
        needs_search = any(kw in query_lower for kw in ["搜索", "search", "查找", "find", "查询"])
        needs_scrape = any(
            kw in query_lower for kw in ["抓取", "scrape", "获取网页", "网站", "url", "http"]
        )
        needs_summary = any(
            kw in query_lower for kw in ["总结", "summarize", "summary", "概括", "归纳"]
        )
        needs_memory = any(kw in query_lower for kw in ["记忆", "memory", "记录", "知识"])
        needs_graph = any(kw in query_lower for kw in ["图谱", "graph", "实体", "entity", "关系"])
        needs_code = any(kw in query_lower for kw in ["代码", "code", "执行", "run", "python"])

        # Build steps based on detected needs and categorized tools
        if needs_search and "search" in tool_categories:
            search_tools = tool_categories["search"]
            steps.append(
                {
                    "step_number": step_number,
                    "description": "搜索相关信息",
                    "required_tools": search_tools,
                    "status": "pending",
                }
            )
            # Map all search tools to this step
            for tool_name in search_tools:
                self._tool_to_step_mapping[tool_name] = step_number
            step_number += 1

        if needs_scrape and "scrape" in tool_categories:
            scrape_tools = tool_categories["scrape"]
            steps.append(
                {
                    "step_number": step_number,
                    "description": "获取网页内容",
                    "required_tools": scrape_tools,
                    "status": "pending",
                }
            )
            # Map all scrape tools to this step
            for tool_name in scrape_tools:
                self._tool_to_step_mapping[tool_name] = step_number
            step_number += 1

        if needs_memory and "memory" in tool_categories:
            memory_tools = tool_categories["memory"]
            steps.append(
                {
                    "step_number": step_number,
                    "description": "搜索记忆库",
                    "required_tools": memory_tools,
                    "status": "pending",
                }
            )
            # Map all memory tools to this step
            for tool_name in memory_tools:
                self._tool_to_step_mapping[tool_name] = step_number
            step_number += 1

        if needs_graph:
            if "entity" in tool_categories:
                entity_tools = tool_categories["entity"]
                steps.append(
                    {
                        "step_number": step_number,
                        "description": "查询知识图谱实体",
                        "required_tools": entity_tools,
                        "status": "pending",
                    }
                )
                # Map all entity lookup tools to this step
                for tool_name in entity_tools:
                    self._tool_to_step_mapping[tool_name] = step_number
                step_number += 1

            if "graph" in tool_categories:
                graph_tools = tool_categories["graph"]
                steps.append(
                    {
                        "step_number": step_number,
                        "description": "执行图谱查询",
                        "required_tools": graph_tools,
                        "status": "pending",
                    }
                )
                # Map all graph query tools to this step
                for tool_name in graph_tools:
                    self._tool_to_step_mapping[tool_name] = step_number
                step_number += 1

        if needs_code and "code" in tool_categories:
            code_tools = tool_categories["code"]
            steps.append(
                {
                    "step_number": step_number,
                    "description": "执行代码",
                    "required_tools": code_tools,
                    "status": "pending",
                }
            )
            # Map all code execution tools to this step
            for tool_name in code_tools:
                self._tool_to_step_mapping[tool_name] = step_number
            step_number += 1

        if needs_summary and "summary" in tool_categories:
            summary_tools = tool_categories["summary"]
            steps.append(
                {
                    "step_number": step_number,
                    "description": "总结分析结果",
                    "required_tools": summary_tools,
                    "status": "pending",
                }
            )
            # Map all summary tools to this step
            for tool_name in summary_tools:
                self._tool_to_step_mapping[tool_name] = step_number
            step_number += 1

        # Always add a final synthesis step
        steps.append(
            {
                "step_number": step_number,
                "description": "生成最终回复",
                "required_tools": [],
                "status": "pending",
            }
        )

        # If no specific tools detected (only final step), don't generate a work plan
        # Simple conversations don't need execution plans - this makes the UI cleaner
        if len(steps) == 1:  # Only final step (no tool usage expected)
            self._work_plan_steps = []
            return None  # Don't show execution plan for simple conversations

        self._work_plan_steps = steps

        return {
            "plan_id": self._work_plan_id,
            "conversation_id": "",  # Will be set by caller
            "status": "in_progress",
            "steps": steps,
            "current_step": 0,
            "total_steps": len(steps),
        }

    async def _process_step(
        self,
        session_id: str,
        messages: List[Dict[str, Any]],
    ) -> AsyncIterator[SSEEvent]:
        """
        Process a single step in the ReAct loop.

        Args:
            session_id: Session identifier
            messages: Current messages

        Yields:
            SSEEvent objects
        """
        # DEBUG: Force logging at start of _process_step
        print(
            f"[Processor] _process_step called: session={session_id}, step={self._step_count}",
            flush=True,
        )
        logger.warning(
            f"[Processor] _process_step called: session={session_id}, step={self._step_count}"
        )

        # Get step description from work plan if available
        step_description = f"Step {self._step_count}"
        if self._work_plan_steps and self._current_plan_step < len(self._work_plan_steps):
            step_info = self._work_plan_steps[self._current_plan_step]
            step_description = step_info.get("description", step_description)

        # Emit step start with meaningful description
        yield SSEEvent.step_start(self._step_count, step_description)

        # Create new assistant message
        self._current_message = Message(
            session_id=session_id,
            role=MessageRole.ASSISTANT,
        )

        # Reset pending tool calls
        self._pending_tool_calls = {}

        # Prepare tools for LLM
        tools_for_llm = [t.to_openai_format() for t in self.tools.values()]

        # Create stream config
        stream_config = StreamConfig(
            model=self.config.model,
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            tools=tools_for_llm if tools_for_llm else None,
        )

        # Create LLM stream
        llm_stream = LLMStream(stream_config)

        # Track state for this step
        text_buffer = ""
        reasoning_buffer = ""
        tool_calls_completed = []
        step_tokens = TokenUsage()
        step_cost = 0.0
        finish_reason = "stop"

        # Process LLM stream with retry
        attempt = 0
        while True:
            try:
                # Build step-specific langfuse context
                step_langfuse_context = None
                if self._langfuse_context:
                    step_langfuse_context = {
                        **self._langfuse_context,
                        "extra": {
                            **self._langfuse_context.get("extra", {}),
                            "step_number": self._step_count,
                            "model": self.config.model,
                        },
                    }

                async for event in llm_stream.generate(
                    messages, langfuse_context=step_langfuse_context
                ):
                    # Check abort
                    if self._abort_event and self._abort_event.is_set():
                        raise asyncio.CancelledError("Aborted")

                    # Debug: log all events from LLM stream
                    logger.info(
                        f"[Processor] LLM event: type={event.type}, data_keys={list(event.data.keys()) if event.data else []}"
                    )

                    # Process stream events
                    if event.type == StreamEventType.TEXT_START:
                        logger.info("[Processor] Yielding TEXT_START")
                        yield SSEEvent.text_start()

                    elif event.type == StreamEventType.TEXT_DELTA:
                        delta = event.data.get("delta", "")
                        text_buffer += delta
                        logger.info(
                            f"[Processor] Yielding TEXT_DELTA: {delta[:30]}..."
                            if len(delta) > 30
                            else f"[Processor] Yielding TEXT_DELTA: {delta}"
                        )
                        yield SSEEvent.text_delta(delta)

                    elif event.type == StreamEventType.TEXT_END:
                        full_text = event.data.get("full_text", text_buffer)
                        self._current_message.add_text(full_text)
                        yield SSEEvent.text_end(full_text)

                    elif event.type == StreamEventType.REASONING_START:
                        yield SSEEvent.thought("", thought_level="reasoning")

                    elif event.type == StreamEventType.REASONING_DELTA:
                        delta = event.data.get("delta", "")
                        reasoning_buffer += delta
                        yield SSEEvent.thought_delta(delta)

                    elif event.type == StreamEventType.REASONING_END:
                        full_reasoning = event.data.get("full_text", reasoning_buffer)
                        self._current_message.add_reasoning(full_reasoning)
                        yield SSEEvent.thought(full_reasoning, thought_level="reasoning")

                    elif event.type == StreamEventType.TOOL_CALL_START:
                        call_id = event.data.get("call_id", "")
                        tool_name = event.data.get("name", "")

                        # Create tool part (don't emit act event yet - wait for complete args)
                        tool_part = self._current_message.add_tool_call(
                            call_id=call_id,
                            tool=tool_name,
                            input={},
                        )
                        self._pending_tool_calls[call_id] = tool_part
                        # Note: Don't emit act event here - wait for TOOL_CALL_END with full args

                    elif event.type == StreamEventType.TOOL_CALL_END:
                        call_id = event.data.get("call_id", "")
                        tool_name = event.data.get("name", "")
                        arguments = event.data.get("arguments", {})

                        # Update tool part
                        if call_id in self._pending_tool_calls:
                            tool_part = self._pending_tool_calls[call_id]
                            tool_part.input = arguments
                            tool_part.status = ToolState.RUNNING
                            tool_part.start_time = time.time()

                            # Get step number from tool-to-step mapping
                            step_number = self._tool_to_step_mapping.get(tool_name)

                            # Update work plan step status
                            if step_number is not None and step_number < len(self._work_plan_steps):
                                self._work_plan_steps[step_number]["status"] = "running"
                                self._current_plan_step = step_number

                            yield SSEEvent.act(
                                tool_name=tool_name,
                                tool_input=arguments,
                                call_id=call_id,
                                status="running",
                            )
                            # Add step_number to the event data for frontend
                            if step_number is not None:
                                # Re-emit with step_number in data
                                yield SSEEvent(
                                    type=SSEEventType.STEP_START,
                                    data={
                                        "step_number": step_number,
                                        "description": self._work_plan_steps[step_number].get(
                                            "description", ""
                                        ),
                                        "tool_name": tool_name,
                                    },
                                )

                            # Execute tool
                            async for tool_event in self._execute_tool(
                                session_id, call_id, tool_name, arguments
                            ):
                                yield tool_event

                            tool_calls_completed.append(call_id)

                    elif event.type == StreamEventType.USAGE:
                        # Extract usage data
                        step_tokens = TokenUsage(
                            input=event.data.get("input_tokens", 0),
                            output=event.data.get("output_tokens", 0),
                            reasoning=event.data.get("reasoning_tokens", 0),
                            cache_read=event.data.get("cache_read_tokens", 0),
                            cache_write=event.data.get("cache_write_tokens", 0),
                        )

                        # Calculate cost
                        cost_result = self.cost_tracker.calculate(
                            usage={
                                "input_tokens": step_tokens.input,
                                "output_tokens": step_tokens.output,
                                "reasoning_tokens": step_tokens.reasoning,
                                "cache_read_tokens": step_tokens.cache_read,
                                "cache_write_tokens": step_tokens.cache_write,
                            },
                            model_name=self.config.model,
                        )
                        step_cost = float(cost_result.cost)

                        yield SSEEvent.cost_update(
                            cost=step_cost,
                            tokens={
                                "input": step_tokens.input,
                                "output": step_tokens.output,
                                "reasoning": step_tokens.reasoning,
                            },
                        )

                        # Check for compaction need
                        if self.cost_tracker.needs_compaction(step_tokens):
                            yield SSEEvent.compact_needed()

                    elif event.type == StreamEventType.FINISH:
                        finish_reason = event.data.get("reason", "stop")

                    elif event.type == StreamEventType.ERROR:
                        error_msg = event.data.get("message", "Unknown error")
                        raise Exception(error_msg)

                # Step completed successfully
                break

            except Exception as e:
                # Check if retryable
                if self.retry_policy.is_retryable(e) and attempt < self.config.max_attempts:
                    attempt += 1
                    delay_ms = self.retry_policy.calculate_delay(attempt, e)

                    self._state = ProcessorState.RETRYING
                    yield SSEEvent.retry(
                        attempt=attempt,
                        delay_ms=delay_ms,
                        message=str(e),
                    )

                    # Wait before retry
                    await asyncio.sleep(delay_ms / 1000)
                    continue
                else:
                    # Not retryable or max retries exceeded
                    raise

        # Update message tokens and cost
        self._current_message.tokens = {
            "input": step_tokens.input,
            "output": step_tokens.output,
            "reasoning": step_tokens.reasoning,
        }
        self._current_message.cost = step_cost
        self._current_message.finish_reason = finish_reason
        self._current_message.completed_at = time.time()

        # Build trace URL if Langfuse context is available
        trace_url = None
        if self._langfuse_context:
            from src.configuration.config import get_settings

            settings = get_settings()
            if settings.langfuse_enabled and settings.langfuse_host:
                trace_id = self._langfuse_context.get("conversation_id", session_id)
                trace_url = f"{settings.langfuse_host}/trace/{trace_id}"

        # Emit step finish
        yield SSEEvent.step_finish(
            tokens=self._current_message.tokens,
            cost=step_cost,
            finish_reason=finish_reason,
            trace_url=trace_url,
        )

        # Emit step end
        yield SSEEvent.step_end(self._step_count, status="completed")

    async def _execute_tool(
        self,
        session_id: str,
        call_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> AsyncIterator[SSEEvent]:
        """
        Execute a tool call with permission checking and doom loop detection.

        Args:
            session_id: Session identifier
            call_id: Tool call ID
            tool_name: Name of tool to execute
            arguments: Tool arguments

        Yields:
            SSEEvent objects for tool execution
        """
        tool_part = self._pending_tool_calls.get(call_id)
        if not tool_part:
            yield SSEEvent.observe(
                tool_name=tool_name,
                error="Tool call not found",
                call_id=call_id,
            )
            return

        # Get tool definition
        tool_def = self.tools.get(tool_name)
        if not tool_def:
            tool_part.status = ToolState.ERROR
            tool_part.error = f"Unknown tool: {tool_name}"
            tool_part.end_time = time.time()

            yield SSEEvent.observe(
                tool_name=tool_name,
                error=f"Unknown tool: {tool_name}",
                call_id=call_id,
            )
            return

        # Check doom loop
        if self.doom_loop_detector.should_intervene(tool_name, arguments):
            # Emit doom loop detected
            yield SSEEvent.doom_loop_detected(tool_name, arguments)

            # Ask for permission to continue
            self._state = ProcessorState.WAITING_PERMISSION

            try:
                permission_result = await asyncio.wait_for(
                    self.permission_manager.ask(
                        permission="doom_loop",
                        patterns=[tool_name],
                        session_id=session_id,
                        metadata={
                            "tool": tool_name,
                            "input": arguments,
                        },
                    ),
                    timeout=self.config.permission_timeout,
                )

                if permission_result == "reject":
                    tool_part.status = ToolState.ERROR
                    tool_part.error = "Doom loop detected and rejected by user"
                    tool_part.end_time = time.time()

                    yield SSEEvent.observe(
                        tool_name=tool_name,
                        error="Doom loop detected and rejected",
                        call_id=call_id,
                    )
                    return

            except asyncio.TimeoutError:
                tool_part.status = ToolState.ERROR
                tool_part.error = "Permission request timed out"
                tool_part.end_time = time.time()

                yield SSEEvent.observe(
                    tool_name=tool_name,
                    error="Permission request timed out",
                    call_id=call_id,
                )
                return

        # Record tool call for doom loop detection
        self.doom_loop_detector.record(tool_name, arguments)

        # === Human-in-the-Loop Tool Handling ===
        # Handle clarification and decision tools specially to enable
        # SSE event emission before blocking on user response

        if tool_name == "ask_clarification":
            async for event in self._handle_clarification_tool(
                session_id, call_id, tool_name, arguments, tool_part
            ):
                yield event
            return

        if tool_name == "request_decision":
            async for event in self._handle_decision_tool(
                session_id, call_id, tool_name, arguments, tool_part
            ):
                yield event
            return

        # Check tool permission
        if tool_def.permission:
            permission_rule = self.permission_manager.evaluate(
                permission=tool_def.permission,
                pattern=tool_name,
            )

            if permission_rule.action == PermissionAction.DENY:
                tool_part.status = ToolState.ERROR
                tool_part.error = f"Permission denied: {tool_def.permission}"
                tool_part.end_time = time.time()

                yield SSEEvent.observe(
                    tool_name=tool_name,
                    error=f"Permission denied: {tool_def.permission}",
                    call_id=call_id,
                )
                return

            elif permission_rule.action == PermissionAction.ASK:
                # Request permission
                self._state = ProcessorState.WAITING_PERMISSION

                yield SSEEvent.permission_asked(
                    request_id=f"perm_{uuid.uuid4().hex[:8]}",
                    permission=tool_def.permission,
                    patterns=[tool_name],
                    metadata={"tool": tool_name, "input": arguments},
                )

                try:
                    permission_result = await asyncio.wait_for(
                        self.permission_manager.ask(
                            permission=tool_def.permission,
                            patterns=[tool_name],
                            session_id=session_id,
                            metadata={"tool": tool_name, "input": arguments},
                        ),
                        timeout=self.config.permission_timeout,
                    )

                    if permission_result == "reject":
                        tool_part.status = ToolState.ERROR
                        tool_part.error = "Permission rejected by user"
                        tool_part.end_time = time.time()

                        yield SSEEvent.observe(
                            tool_name=tool_name,
                            error="Permission rejected by user",
                            call_id=call_id,
                        )
                        return

                except asyncio.TimeoutError:
                    tool_part.status = ToolState.ERROR
                    tool_part.error = "Permission request timed out"
                    tool_part.end_time = time.time()

                    yield SSEEvent.observe(
                        tool_name=tool_name,
                        error="Permission request timed out",
                        call_id=call_id,
                    )
                    return

        # Execute tool
        self._state = ProcessorState.ACTING

        try:
            # Call tool execute function
            start_time = time.time()
            result = await tool_def.execute(**arguments)
            end_time = time.time()

            # Handle structured return format {title, output, metadata}
            # Reference: OpenCode SkillTool structured return
            if isinstance(result, dict) and "output" in result:
                # Extract output for tool_part (used for LLM context)
                output_str = result.get("output", "")
                # Keep full result for SSE event (frontend can use metadata)
                sse_result = result
            elif isinstance(result, str):
                output_str = result
                sse_result = result
            else:
                output_str = json.dumps(result)
                sse_result = result

            # Update tool part
            tool_part.status = ToolState.COMPLETED
            tool_part.output = output_str
            tool_part.end_time = end_time

            # Update work plan step status to completed
            step_number = self._tool_to_step_mapping.get(tool_name)
            if step_number is not None and step_number < len(self._work_plan_steps):
                self._work_plan_steps[step_number]["status"] = "completed"
                # Emit step_end event
                yield SSEEvent.step_end(step_number, status="completed")

            yield SSEEvent.observe(
                tool_name=tool_name,
                result=sse_result,
                duration_ms=int((end_time - start_time) * 1000),
                call_id=call_id,
            )

        except Exception as e:
            logger.error(f"Tool execution error: {e}", exc_info=True)

            tool_part.status = ToolState.ERROR
            tool_part.error = str(e)
            tool_part.end_time = time.time()

            # Update work plan step status to failed
            step_number = self._tool_to_step_mapping.get(tool_name)
            if step_number is not None and step_number < len(self._work_plan_steps):
                self._work_plan_steps[step_number]["status"] = "failed"
                # Emit step_end event with failed status
                yield SSEEvent.step_end(step_number, status="failed")

            yield SSEEvent.observe(
                tool_name=tool_name,
                error=str(e),
                duration_ms=int((time.time() - tool_part.start_time) * 1000)
                if tool_part.start_time
                else None,
                call_id=call_id,
            )

        self._state = ProcessorState.OBSERVING

    async def _handle_clarification_tool(
        self,
        session_id: str,
        call_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        tool_part: ToolPart,
    ) -> AsyncIterator[SSEEvent]:
        """
        Handle clarification tool with SSE event emission.

        Emits clarification_asked event before blocking on user response,
        allowing frontend to display dialog immediately.

        Args:
            session_id: Session identifier
            call_id: Tool call ID
            tool_name: Tool name (ask_clarification)
            arguments: Tool arguments
            tool_part: Tool part for tracking state

        Yields:
            SSEEvent objects for clarification flow
        """
        from ..tools.clarification import (
            ClarificationOption,
            ClarificationRequest,
            ClarificationType,
            get_clarification_manager,
        )

        self._state = ProcessorState.WAITING_CLARIFICATION
        manager = get_clarification_manager()

        try:
            # Parse arguments
            question = arguments.get("question", "")
            clarification_type = arguments.get("clarification_type", "custom")
            options_raw = arguments.get("options", [])
            allow_custom = arguments.get("allow_custom", True)
            context = arguments.get("context", {})
            timeout = arguments.get("timeout", 300.0)

            # Create request ID
            request_id = f"clarif_{uuid.uuid4().hex[:8]}"

            # Convert options to proper format
            clarification_options = []
            for opt in options_raw:
                clarification_options.append(
                    {
                        "id": opt.get("id", ""),
                        "label": opt.get("label", ""),
                        "description": opt.get("description"),
                        "recommended": opt.get("recommended", False),
                    }
                )

            # Create the request object for manager
            try:
                clarif_type = ClarificationType(clarification_type)
            except ValueError:
                clarif_type = ClarificationType.CUSTOM

            option_objects = [
                ClarificationOption(
                    id=opt["id"],
                    label=opt["label"],
                    description=opt.get("description"),
                    recommended=opt.get("recommended", False),
                )
                for opt in clarification_options
            ]

            request = ClarificationRequest(
                request_id=request_id,
                question=question,
                clarification_type=clarif_type,
                options=option_objects,
                allow_custom=allow_custom,
                context=context,
            )

            # Register request with manager
            async with manager._lock:
                manager._pending_requests[request_id] = request

            # Emit clarification_asked event BEFORE blocking
            yield SSEEvent.clarification_asked(
                request_id=request_id,
                question=question,
                clarification_type=clarification_type,
                options=clarification_options,
                allow_custom=allow_custom,
                context=context,
            )

            # Wait for user response
            start_time = time.time()
            try:
                answer = await asyncio.wait_for(request.future, timeout=timeout)
                end_time = time.time()

                # Emit answered event
                yield SSEEvent.clarification_answered(
                    request_id=request_id,
                    answer=answer,
                )

                # Update tool part
                tool_part.status = ToolState.COMPLETED
                tool_part.output = answer
                tool_part.end_time = end_time

                yield SSEEvent.observe(
                    tool_name=tool_name,
                    result=answer,
                    duration_ms=int((end_time - start_time) * 1000),
                    call_id=call_id,
                )

            except asyncio.TimeoutError:
                tool_part.status = ToolState.ERROR
                tool_part.error = "Clarification request timed out"
                tool_part.end_time = time.time()

                yield SSEEvent.observe(
                    tool_name=tool_name,
                    error="Clarification request timed out",
                    call_id=call_id,
                )
            finally:
                # Clean up request
                async with manager._lock:
                    manager._pending_requests.pop(request_id, None)

        except Exception as e:
            logger.error(f"Clarification tool error: {e}", exc_info=True)
            tool_part.status = ToolState.ERROR
            tool_part.error = str(e)
            tool_part.end_time = time.time()

            yield SSEEvent.observe(
                tool_name=tool_name,
                error=str(e),
                call_id=call_id,
            )

        self._state = ProcessorState.OBSERVING

    async def _handle_decision_tool(
        self,
        session_id: str,
        call_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        tool_part: ToolPart,
    ) -> AsyncIterator[SSEEvent]:
        """
        Handle decision tool with SSE event emission.

        Emits decision_asked event before blocking on user response,
        allowing frontend to display dialog immediately.

        Args:
            session_id: Session identifier
            call_id: Tool call ID
            tool_name: Tool name (request_decision)
            arguments: Tool arguments
            tool_part: Tool part for tracking state

        Yields:
            SSEEvent objects for decision flow
        """
        from ..tools.decision import (
            DecisionOption,
            DecisionRequest,
            DecisionType,
            get_decision_manager,
        )

        self._state = ProcessorState.WAITING_DECISION
        manager = get_decision_manager()

        try:
            # Parse arguments
            question = arguments.get("question", "")
            decision_type = arguments.get("decision_type", "custom")
            options_raw = arguments.get("options", [])
            allow_custom = arguments.get("allow_custom", False)
            default_option = arguments.get("default_option")
            context = arguments.get("context", {})
            timeout = arguments.get("timeout", 300.0)

            # Create request ID
            request_id = f"decision_{uuid.uuid4().hex[:8]}"

            # Convert options to proper format
            decision_options = []
            for opt in options_raw:
                decision_options.append(
                    {
                        "id": opt.get("id", ""),
                        "label": opt.get("label", ""),
                        "description": opt.get("description"),
                        "recommended": opt.get("recommended", False),
                        "estimated_time": opt.get("estimated_time"),
                        "estimated_cost": opt.get("estimated_cost"),
                        "risks": opt.get("risks", []),
                    }
                )

            # Create the request object for manager
            try:
                dec_type = DecisionType(decision_type)
            except ValueError:
                dec_type = DecisionType.CUSTOM

            option_objects = [
                DecisionOption(
                    id=opt["id"],
                    label=opt["label"],
                    description=opt.get("description"),
                    recommended=opt.get("recommended", False),
                    estimated_time=opt.get("estimated_time"),
                    estimated_cost=opt.get("estimated_cost"),
                    risks=opt.get("risks", []),
                )
                for opt in decision_options
            ]

            request = DecisionRequest(
                request_id=request_id,
                question=question,
                decision_type=dec_type,
                options=option_objects,
                allow_custom=allow_custom,
                default_option=default_option,
                context=context,
            )

            # Register request with manager
            async with manager._lock:
                manager._pending_requests[request_id] = request

            # Emit decision_asked event BEFORE blocking
            yield SSEEvent.decision_asked(
                request_id=request_id,
                question=question,
                decision_type=decision_type,
                options=decision_options,
                allow_custom=allow_custom,
                default_option=default_option,
                context=context,
            )

            # Wait for user response
            start_time = time.time()
            try:
                decision = await asyncio.wait_for(request.future, timeout=timeout)
                end_time = time.time()

                # Emit answered event
                yield SSEEvent.decision_answered(
                    request_id=request_id,
                    decision=decision,
                )

                # Update tool part
                tool_part.status = ToolState.COMPLETED
                tool_part.output = decision
                tool_part.end_time = end_time

                yield SSEEvent.observe(
                    tool_name=tool_name,
                    result=decision,
                    duration_ms=int((end_time - start_time) * 1000),
                    call_id=call_id,
                )

            except asyncio.TimeoutError:
                # Use default option if provided, otherwise error
                if default_option:
                    end_time = time.time()

                    yield SSEEvent.decision_answered(
                        request_id=request_id,
                        decision=default_option,
                    )

                    tool_part.status = ToolState.COMPLETED
                    tool_part.output = f"Timeout - used default: {default_option}"
                    tool_part.end_time = end_time

                    yield SSEEvent.observe(
                        tool_name=tool_name,
                        result=f"Timeout - used default: {default_option}",
                        duration_ms=int((end_time - start_time) * 1000),
                        call_id=call_id,
                    )
                else:
                    tool_part.status = ToolState.ERROR
                    tool_part.error = "Decision request timed out"
                    tool_part.end_time = time.time()

                    yield SSEEvent.observe(
                        tool_name=tool_name,
                        error="Decision request timed out",
                        call_id=call_id,
                    )
            finally:
                # Clean up request
                async with manager._lock:
                    manager._pending_requests.pop(request_id, None)

        except Exception as e:
            logger.error(f"Decision tool error: {e}", exc_info=True)
            tool_part.status = ToolState.ERROR
            tool_part.error = str(e)
            tool_part.end_time = time.time()

            yield SSEEvent.observe(
                tool_name=tool_name,
                error=str(e),
                call_id=call_id,
            )

        self._state = ProcessorState.OBSERVING

    def abort(self) -> None:
        """Abort current processing."""
        if self._abort_event:
            self._abort_event.set()

    def get_session_summary(self) -> Dict[str, Any]:
        """Get summary of session costs and tokens."""
        return self.cost_tracker.get_session_summary()


def create_processor(
    model: str,
    tools: List[ToolDefinition],
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    **kwargs,
) -> SessionProcessor:
    """
    Factory function to create session processor.

    Args:
        model: Model name
        tools: List of tool definitions
        api_key: Optional API key
        base_url: Optional base URL
        **kwargs: Additional configuration options

    Returns:
        Configured SessionProcessor instance
    """
    config = ProcessorConfig(
        model=model,
        api_key=api_key,
        base_url=base_url,
        **kwargs,
    )
    return SessionProcessor(config, tools)
