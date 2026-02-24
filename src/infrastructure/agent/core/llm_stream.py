"""
LLM Stream - Async streaming wrapper for LiteLLM.

Provides unified streaming interface for LLM responses with support for:
- Text generation (streaming deltas)
- Tool calls (function calling)
- Reasoning/thinking tokens (o1/Claude style)
- Token usage tracking
- Provider-specific metadata handling
- Rate limiting to prevent API provider concurrent limits

P0-2 Optimization: Batch logging and token delta sampling to reduce I/O overhead.

Reference: OpenCode's LLM.stream() in llm.ts
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from src.domain.llm_providers.llm_types import LLMClient


# Import sampling utilities from llm package
from src.infrastructure.agent.llm.token_sampler import BatchLogBuffer, TokenDeltaSampler

logger = logging.getLogger(__name__)


# ============================================================================
# Module-level configuration (read once at import time)
# This avoids os.environ access inside Temporal workflow sandbox
# ============================================================================
_LLM_LOG_SAMPLE_RATE = float(os.environ.get("LLM_LOG_SAMPLE_RATE", "0.1"))
_LLM_LOG_MIN_INTERVAL = float(os.environ.get("LLM_LOG_MIN_INTERVAL", "0.5"))
_LLM_LOG_BUFFER_SIZE = int(os.environ.get("LLM_LOG_BUFFER_SIZE", "100"))
_LLM_LOG_BUFFER_INTERVAL = float(os.environ.get("LLM_LOG_BUFFER_INTERVAL", "1.0"))


# ============================================================================
# Model to Provider Mapping
# ============================================================================

# Model name prefixes that map to specific providers
MODEL_PROVIDER_MAP: dict[str, str] = {
    # Qwen/Dashscope models
    "qwen-": "dashscope",
    "qwq-": "dashscope",
    # OpenAI models
    "gpt-": "openai",
    "o1-": "openai",
    # Gemini models
    "gemini-": "gemini",
    # Deepseek models
    "deepseek-": "deepseek",
    "deepseek-r1": "deepseek",
    # Zhipu AI models
    "glm-": "zhipu",
    # Claude models (via Anthropic/OpenAI)
    "claude-": "openai",
}


def infer_provider_from_model(model: str) -> str:
    """
    Infer provider type from model name.

    Args:
        model: Model name (e.g., "qwen-turbo", "gpt-4", "gemini-pro")

    Returns:
        Provider type: "dashscope", "openai", "gemini", "deepseek", "zhipu"
    """
    model_lower = model.lower()

    for prefix, provider in MODEL_PROVIDER_MAP.items():
        if model_lower.startswith(prefix):
            return provider

    # Default to dashscope for unknown models (most restrictive)
    return "dashscope"


# ============================================================================
# P0-2: Batch Logging and Token Delta Sampling
# Note: TokenDeltaSampler and BatchLogBuffer moved to llm/token_sampler.py
# ============================================================================


class StreamEventType(str, Enum):
    """Types of events emitted during LLM streaming."""

    # Text events
    TEXT_START = "text_start"
    TEXT_DELTA = "text_delta"
    TEXT_END = "text_end"

    # Reasoning events (for o1, Claude extended thinking)
    REASONING_START = "reasoning_start"
    REASONING_DELTA = "reasoning_delta"
    REASONING_END = "reasoning_end"

    # Tool call events
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_DELTA = "tool_call_delta"
    TOOL_CALL_END = "tool_call_end"

    # Usage events
    USAGE = "usage"

    # Completion events
    FINISH = "finish"
    ERROR = "error"


@dataclass
class ToolCallChunk:
    """
    Partial tool call being accumulated from stream.

    Tool calls may arrive in multiple chunks:
    - First chunk: id, name (possibly partial)
    - Subsequent chunks: argument deltas
    - Final chunk: complete arguments
    """

    id: str
    index: int
    name: str = ""
    arguments: str = ""
    complete: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "index": self.index,
            "name": self.name,
            "arguments": self.arguments,
            "complete": self.complete,
        }


@dataclass
class StreamEvent:
    """
    Event emitted during LLM streaming.

    Each event represents a discrete piece of the response:
    - Text deltas for content generation
    - Tool call chunks for function calling
    - Reasoning deltas for extended thinking
    - Usage data at completion
    """

    type: StreamEventType
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    @classmethod
    def text_start(cls) -> StreamEvent:
        """Create text start event."""
        return cls(StreamEventType.TEXT_START)

    @classmethod
    def text_delta(cls, delta: str) -> StreamEvent:
        """Create text delta event."""
        return cls(StreamEventType.TEXT_DELTA, {"delta": delta})

    @classmethod
    def text_end(cls, full_text: str = "") -> StreamEvent:
        """Create text end event."""
        return cls(StreamEventType.TEXT_END, {"full_text": full_text})

    @classmethod
    def reasoning_start(cls) -> StreamEvent:
        """Create reasoning start event."""
        return cls(StreamEventType.REASONING_START)

    @classmethod
    def reasoning_delta(cls, delta: str) -> StreamEvent:
        """Create reasoning delta event."""
        return cls(StreamEventType.REASONING_DELTA, {"delta": delta})

    @classmethod
    def reasoning_end(cls, full_text: str = "") -> StreamEvent:
        """Create reasoning end event."""
        return cls(StreamEventType.REASONING_END, {"full_text": full_text})

    @classmethod
    def tool_call_start(
        cls,
        call_id: str,
        name: str,
        index: int = 0,
    ) -> StreamEvent:
        """Create tool call start event."""
        return cls(
            StreamEventType.TOOL_CALL_START,
            {
                "call_id": call_id,
                "name": name,
                "index": index,
            },
        )

    @classmethod
    def tool_call_delta(
        cls,
        call_id: str,
        arguments_delta: str,
    ) -> StreamEvent:
        """Create tool call delta event."""
        return cls(
            StreamEventType.TOOL_CALL_DELTA,
            {
                "call_id": call_id,
                "arguments_delta": arguments_delta,
            },
        )

    @classmethod
    def tool_call_end(
        cls,
        call_id: str,
        name: str,
        arguments: dict[str, Any],
    ) -> StreamEvent:
        """Create tool call end event."""
        return cls(
            StreamEventType.TOOL_CALL_END,
            {
                "call_id": call_id,
                "name": name,
                "arguments": arguments,
            },
        )

    @classmethod
    def usage(
        cls,
        input_tokens: int,
        output_tokens: int,
        reasoning_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> StreamEvent:
        """Create usage event."""
        return cls(
            StreamEventType.USAGE,
            {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "reasoning_tokens": reasoning_tokens,
                "cache_read_tokens": cache_read_tokens,
                "cache_write_tokens": cache_write_tokens,
            },
        )

    @classmethod
    def finish(cls, reason: str) -> StreamEvent:
        """Create finish event."""
        return cls(StreamEventType.FINISH, {"reason": reason})

    @classmethod
    def error(cls, message: str, code: str | None = None) -> StreamEvent:
        """Create error event."""
        data = {"message": message}
        if code:
            data["code"] = code
        return cls(StreamEventType.ERROR, data)


@dataclass
class StreamConfig:
    """
    Configuration for LLM streaming.

    Controls model behavior, token limits, and streaming options.
    """

    model: str
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.0
    max_tokens: int = 4096

    # Tool configuration
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | None = None  # "auto", "none", "required", or specific tool

    # Provider-specific options
    provider_options: dict[str, Any] = field(default_factory=dict)

    # Provider for rate limiting (inferred from model if not set)
    provider: str | None = None

    # Request metadata (increased from 300 to 600 seconds for long-running agents)
    timeout: int = 600  # seconds (10 minutes)

    def get_provider(self) -> str:
        """Get the provider type, inferring from model if not set."""
        if self.provider:
            return self.provider
        return infer_provider_from_model(self.model)

    def to_litellm_kwargs(self) -> dict[str, Any]:
        """
        Convert to LiteLLM acompletion kwargs.

        Returns:
            Dictionary of kwargs for litellm.acompletion()
        """
        kwargs = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": True,
            "timeout": self.timeout,
        }

        if self.api_key:
            kwargs["api_key"] = self.api_key

        if self.base_url:
            kwargs["api_base"] = self.base_url

        if self.tools:
            kwargs["tools"] = self.tools
            if self.tool_choice:
                kwargs["tool_choice"] = self.tool_choice

        # Merge provider-specific options
        kwargs.update(self.provider_options)

        return kwargs


class LLMStream:
    """
    Async streaming wrapper for LiteLLM.

    Handles the complexity of streaming LLM responses:
    - Accumulates partial tool calls
    - Tracks text and reasoning content
    - Extracts usage data from final chunk
    - Handles provider-specific formats

    Usage:
        stream = LLMStream(config)
        async for event in stream.generate(messages):
            if event.type == StreamEventType.TEXT_DELTA:
                print(event.data["delta"], end="")
            elif event.type == StreamEventType.TOOL_CALL_END:
                tool_name = event.data["name"]
                arguments = event.data["arguments"]
                # Execute tool...
    """

    def __init__(self, config: StreamConfig, llm_client: LLMClient | None = None) -> None:
        """
        Initialize LLM stream.

        Args:
            config: Stream configuration
            llm_client: Optional LiteLLMClient instance for unified resilience.
                        When provided, uses client's rate limiter & circuit breaker.
                        When None, falls back to direct litellm calls with basic rate limiting.
        """
        self.config = config
        self._llm_client = llm_client

        # Accumulated state during streaming
        self._text_buffer: str = ""
        self._reasoning_buffer: str = ""
        self._tool_calls: dict[int, ToolCallChunk] = {}
        self._in_text: bool = False
        self._in_reasoning: bool = False

        # Usage tracking
        self._usage: dict[str, int] | None = None
        self._finish_reason: str | None = None

        # P0-2: Batch logging and token delta sampling
        # Get configuration from environment or use defaults
        # Note: Read env vars at module load time to avoid Temporal workflow sandbox issues
        self._token_sampler = TokenDeltaSampler(
            sample_rate=_LLM_LOG_SAMPLE_RATE,
            min_sample_interval=_LLM_LOG_MIN_INTERVAL,
        )
        self._log_buffer = BatchLogBuffer(
            max_size=_LLM_LOG_BUFFER_SIZE,
            flush_interval=_LLM_LOG_BUFFER_INTERVAL,
        )

    async def generate(
        self,
        messages: list[dict[str, Any]],
        request_id: str | None = None,
        langfuse_context: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """
        Generate streaming response from LLM.

        Uses injected LiteLLMClient if available (provides circuit breaker + rate limiting),
        otherwise falls back to direct litellm calls with basic rate limiting.

        Args:
            messages: List of messages in OpenAI format
            request_id: Optional request ID for tracing
            langfuse_context: Optional context for Langfuse tracing containing:
                - conversation_id: Unique conversation identifier (used as trace_id)
                - user_id: User identifier for trace attribution
                - tenant_id: Tenant identifier for multi-tenant isolation
                - project_id: Project identifier
                - extra: Additional metadata dict

        Yields:
            StreamEvent objects as response is generated
        """
        request_id = request_id or str(uuid.uuid4())

        # Reset state
        self._reset_state()

        logger.debug(f"Starting LLM stream: model={self.config.model}, request_id={request_id}")

        start_time = time.time()

        try:
            # Use injected client if available (preferred path with full resilience)
            if self._llm_client:
                async for event in self._generate_with_client(
                    messages, request_id, langfuse_context
                ):
                    yield event
            else:
                # Fallback: direct litellm calls with basic rate limiting
                async for event in self._generate_direct(messages, request_id, langfuse_context):
                    yield event

            elapsed = time.time() - start_time
            logger.debug(f"LLM stream completed: request_id={request_id}, elapsed={elapsed:.2f}s")

        except Exception as e:
            logger.error(f"LLM stream error: {e}", exc_info=True)
            yield StreamEvent.error(str(e), code=type(e).__name__)

    async def _generate_with_client(
        self,
        messages: list[dict[str, Any]],
        request_id: str,
        langfuse_context: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """
        Generate using injected LiteLLMClient (has circuit breaker + rate limiter).

        Args:
            messages: List of messages in OpenAI format
            request_id: Request ID for tracing
            langfuse_context: Optional Langfuse context

        Yields:
            StreamEvent objects
        """
        from src.domain.llm_providers.llm_types import RateLimitError

        # Build langfuse context for client
        client_langfuse_context = None
        if langfuse_context:
            client_langfuse_context = {
                "trace_name": "agent_chat",
                "trace_id": langfuse_context.get("conversation_id", request_id),
                "tags": [langfuse_context.get("tenant_id", "default")],
                "extra": {
                    "user_id": langfuse_context.get("user_id"),
                    "project_id": langfuse_context.get("project_id"),
                    **(langfuse_context.get("extra", {})),
                },
            }

        # Prepare additional kwargs from config
        extra_kwargs: dict[str, Any] = {}
        if self.config.tools:
            extra_kwargs["tools"] = self.config.tools
            if self.config.tool_choice:
                extra_kwargs["tool_choice"] = self.config.tool_choice
        if self.config.temperature:
            extra_kwargs["temperature"] = self.config.temperature

        try:
            # Use client's generate_stream (has circuit breaker + rate limiter)
            async for chunk in self._llm_client.generate_stream(
                messages=messages,
                max_tokens=self.config.max_tokens,
                langfuse_context=client_langfuse_context,
                **extra_kwargs,
            ):
                # Process raw LiteLLM chunk
                async for event in self._process_chunk(chunk):
                    yield event

            # Finalize any pending state
            async for event in self._finalize():
                yield event

        except RateLimitError as e:
            logger.warning(f"Rate limit error via client: {e}")
            yield StreamEvent.error(
                "Rate limit exceeded. Please wait a moment and try again.", code="RATE_LIMIT"
            )

    async def _generate_direct(
        self,
        messages: list[dict[str, Any]],
        request_id: str,
        langfuse_context: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """
        Generate using direct litellm calls with basic rate limiting.

        Fallback path when no LiteLLMClient is injected.

        Args:
            messages: List of messages in OpenAI format
            request_id: Request ID for tracing
            langfuse_context: Optional Langfuse context

        Yields:
            StreamEvent objects
        """
        import litellm

        # Import rate limiter for concurrency control
        from src.domain.llm_providers.models import ProviderType
        from src.infrastructure.llm.resilience import (
            RateLimitExceededError,
            get_provider_rate_limiter,
        )

        # Prepare kwargs
        kwargs = self.config.to_litellm_kwargs()
        kwargs["messages"] = messages

        # Clamp max_tokens to model-specific limits
        from src.infrastructure.llm.model_registry import clamp_max_tokens as _clamp_max_tokens

        if "max_tokens" in kwargs:
            kwargs["max_tokens"] = _clamp_max_tokens(kwargs["model"], kwargs["max_tokens"])

        # Inject Langfuse metadata if provided
        if langfuse_context:
            langfuse_metadata = {
                "trace_id": langfuse_context.get("conversation_id", request_id),
                "session_id": langfuse_context.get("conversation_id", request_id),
                "trace_user_id": langfuse_context.get("user_id"),
                "tags": [langfuse_context.get("tenant_id", "default")],
                "trace_name": "agent_chat",
            }
            # Add extra metadata if provided
            if langfuse_context.get("extra"):
                langfuse_metadata.update(langfuse_context["extra"])
            # Merge with existing metadata
            kwargs["metadata"] = {**kwargs.get("metadata", {}), **langfuse_metadata}

        # Get rate limiter and provider type
        rate_limiter = get_provider_rate_limiter()
        provider_name = self.config.get_provider()
        provider_type = ProviderType(provider_name)

        try:
            # Acquire rate limit slot before calling LLM
            # This blocks if we've exceeded the provider's concurrent request limit
            async with rate_limiter.acquire(provider_type):
                # Call LiteLLM streaming (now that we have a slot)
                response = await litellm.acompletion(**kwargs)

                async for chunk in response:
                    # Process each chunk and yield events
                    async for event in self._process_chunk(chunk):
                        yield event

                # Finalize any pending state
                async for event in self._finalize():
                    yield event

        except RateLimitExceededError as e:
            logger.warning(f"Rate limit exceeded for {provider_name}: {e}")
            yield StreamEvent.error(
                "Rate limit exceeded. Please wait a moment and try again.", code="RATE_LIMIT"
            )

    def _reset_state(self) -> None:
        """Reset accumulated state for new generation."""
        self._text_buffer = ""
        self._reasoning_buffer = ""
        self._tool_calls = {}
        self._in_text = False
        self._in_reasoning = False
        self._usage = None
        self._finish_reason = None
        # P0-2: Reset sampler for new stream
        self._token_sampler.reset()
        # Flush any pending logs
        self._log_buffer.flush()

    def _handle_content_delta(self, content: str) -> Iterator[StreamEvent]:
        """Handle a text content delta from the LLM stream."""
        logger.info(f"[LLMStream] TEXT_DELTA: {content[:50]}...")
        if not self._in_text:
            self._in_text = True
            yield StreamEvent.text_start()
        self._text_buffer += content
        yield StreamEvent.text_delta(content)

    def _handle_reasoning_delta(self, reasoning: str) -> Iterator[StreamEvent]:
        """Handle a reasoning content delta (o1, Claude extended thinking)."""
        if not self._in_reasoning:
            self._in_reasoning = True
            yield StreamEvent.reasoning_start()
        self._reasoning_buffer += reasoning
        yield StreamEvent.reasoning_delta(reasoning)

    async def _process_chunk(
        self,
        chunk: Any,
    ) -> AsyncIterator[StreamEvent]:
        """
        Process a single streaming chunk.

        Handles different chunk types:
        - Content deltas (text)
        - Tool call deltas
        - Reasoning content (extended thinking)
        - Usage data (final chunk)

        Args:
            chunk: Raw chunk from LiteLLM

        Yields:
            StreamEvent objects
        """
        choices = getattr(chunk, "choices", [])
        if not choices:
            logger.debug("[LLMStream] chunk has no choices")
            return

        choice = choices[0]
        delta = getattr(choice, "delta", None)
        if delta is None:
            logger.debug("[LLMStream] choice has no delta")
            return

        # Debug: log delta summary without serializing provider-specific objects.
        tool_calls = getattr(delta, "tool_calls", None)
        if isinstance(tool_calls, list):
            tool_call_count = len(tool_calls)
        elif tool_calls:
            tool_call_count = 1
        else:
            tool_call_count = 0
        logger.debug(
            "[LLMStream] delta: has_content=%s, tool_call_count=%s",
            bool(getattr(delta, "content", None)),
            tool_call_count,
        )

        # Check for content (text)
        content = getattr(delta, "content", None)
        if content:
            for event in self._handle_content_delta(content):
                yield event

        # Check for reasoning content (o1, Claude extended thinking)
        reasoning = (
            getattr(delta, "reasoning_content", None)
            or getattr(delta, "thinking", None)
            or getattr(delta, "reasoning", None)
        )
        if reasoning:
            for event in self._handle_reasoning_delta(reasoning):
                yield event

        # Check for tool calls
        tool_calls = getattr(delta, "tool_calls", None)
        if tool_calls:
            async for event in self._process_tool_calls(tool_calls):
                yield event

        finish_reason = getattr(choice, "finish_reason", None)
        if finish_reason:
            self._finish_reason = finish_reason

        usage = getattr(chunk, "usage", None)
        if usage:
            self._usage = self._extract_usage(usage)

    async def _process_tool_calls(
        self,
        tool_calls: list[Any],
    ) -> AsyncIterator[StreamEvent]:
        """
        Process tool call deltas.

        Tool calls arrive incrementally:
        1. First chunk has id and function name
        2. Subsequent chunks have argument fragments
        3. When complete, emit tool_call_end event

        Args:
            tool_calls: List of tool call deltas

        Yields:
            StreamEvent objects for tool calls
        """
        for tc in tool_calls:
            index = getattr(tc, "index", 0)

            # Get or create tool call tracker
            if index not in self._tool_calls:
                # New tool call starting
                call_id = getattr(tc, "id", None) or f"call_{uuid.uuid4().hex[:8]}"
                self._tool_calls[index] = ToolCallChunk(
                    id=call_id,
                    index=index,
                )

            tracker = self._tool_calls[index]

            # Update function name if present
            function = getattr(tc, "function", None)
            if function:
                name = getattr(function, "name", None)
                if name:
                    if not tracker.name:
                        # First time seeing name - emit start event
                        tracker.name = name
                        yield StreamEvent.tool_call_start(
                            call_id=tracker.id,
                            name=name,
                            index=index,
                        )
                    else:
                        tracker.name = name

                # Accumulate arguments
                args_delta = getattr(function, "arguments", None)
                if args_delta:
                    tracker.arguments += args_delta
                    yield StreamEvent.tool_call_delta(
                        call_id=tracker.id,
                        arguments_delta=args_delta,
                    )

    @staticmethod
    def _escape_control_chars(s: str) -> str:
        """Escape control characters in a JSON string."""
        s = s.replace("\n", "\\n")
        s = s.replace("\r", "\\r")
        s = s.replace("\t", "\\t")
        return s

    def _try_fix_control_chars(self, raw_args: str, tool_name: str) -> dict[str, Any] | None:
        """Attempt to parse JSON after escaping unescaped control characters."""
        try:
            fixed_args = self._escape_control_chars(raw_args)
            result = json.loads(fixed_args)
            logger.info(
                f"[LLMStream] Successfully parsed JSON after escaping control chars for {tool_name}"
            )
            return cast(dict[str, Any] | None, result)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _try_fix_double_encoded(raw_args: str, tool_name: str) -> dict[str, Any] | None:
        """Attempt to parse double-encoded JSON."""
        try:
            if raw_args.startswith('"') and raw_args.endswith('"'):
                inner = raw_args[1:-1]
                inner = inner.replace('\\"', '"').replace("\\\\", "\\")
                result = json.loads(inner)
                logger.info(f"[LLMStream] Successfully parsed double-encoded JSON for {tool_name}")
                return cast(dict[str, Any] | None, result)
        except json.JSONDecodeError:
            pass
        return None

    def _build_truncation_fallback(
        self, raw_args: str, error_str: str, tool_name: str
    ) -> dict[str, Any]:
        """Build fallback arguments dict for unparseable tool arguments."""
        is_truncated = self._finish_reason == "length" or (
            ("Unterminated string" in error_str or "Expecting" in error_str)
            and not raw_args.rstrip().endswith("}")
        )
        if is_truncated:
            logger.error(
                f"[LLMStream] Tool arguments truncated for {tool_name}. "
                f"finish_reason={self._finish_reason}. "
                f"Consider increasing max_tokens or reducing content size."
            )
            return {
                "_error": "truncated",
                "_message": (
                    "Tool arguments were truncated (incomplete JSON). "
                    "The content may be too large. Try with smaller content or increase max_tokens."
                ),
                "_raw": raw_args,
            }
        logger.warning(
            f"[LLMStream] Could not parse tool arguments for {tool_name}, "
            f"passing _raw for processor to handle"
        )
        return {"_raw": raw_args}

    def _parse_tool_arguments(self, tracker: ToolCallChunk) -> dict[str, Any]:
        """Parse tool call arguments with error recovery."""
        if not tracker.arguments:
            return {}

        raw_args = tracker.arguments
        try:
            return cast(dict[str, Any], json.loads(raw_args))
        except json.JSONDecodeError as e:
            error_str = str(e)
            logger.warning(
                f"Failed to parse tool arguments for {tracker.name}: {e}. "
                f"Arguments preview: {raw_args[:200]}..."
            )

        # Try common fixes in order
        fixed = self._try_fix_control_chars(raw_args, tracker.name)
        if fixed is not None:
            return fixed

        fixed = self._try_fix_double_encoded(raw_args, tracker.name)
        if fixed is not None:
            return fixed

        return self._build_truncation_fallback(raw_args, error_str, tracker.name)

    def _finalize_streams(self) -> Iterator[StreamEvent]:
        """Close any open text/reasoning streams in correct order."""
        # IMPORTANT: End reasoning stream BEFORE text stream
        # Reasoning (thought) should logically complete before the final response (text)
        # This ensures correct timeline ordering in the frontend:
        # thought -> response (not response -> thought)
        if self._in_reasoning:
            yield StreamEvent.reasoning_end(self._reasoning_buffer)
            self._in_reasoning = False
        if self._in_text:
            yield StreamEvent.text_end(self._text_buffer)
            self._in_text = False

    def _complete_pending_tool_calls(self) -> Iterator[StreamEvent]:
        """Complete any pending tool calls and parse their arguments."""
        for _index, tracker in self._tool_calls.items():
            if not tracker.complete:
                tracker.complete = True
                arguments = self._parse_tool_arguments(tracker)
                yield StreamEvent.tool_call_end(
                    call_id=tracker.id,
                    name=tracker.name,
                    arguments=arguments,
                )

    async def _finalize(self) -> AsyncIterator[StreamEvent]:
        """
        Finalize streaming and emit completion events.

        Called after all chunks are processed to:
        - Close any open text/reasoning streams
        - Complete any pending tool calls
        - Emit usage data
        - Emit finish event

        Yields:
            Final StreamEvent objects
        """
        for event in self._finalize_streams():
            yield event
        for event in self._complete_pending_tool_calls():
            yield event

        # Emit usage if available
        if self._usage:
            yield StreamEvent.usage(**self._usage)

        yield StreamEvent.finish(self._finish_reason or "stop")

    def _extract_usage(self, usage: Any) -> dict[str, int]:
        """
        Extract token usage from response.

        Handles different provider formats:
        - OpenAI: prompt_tokens, completion_tokens
        - Anthropic: input_tokens, output_tokens, cache_read_input_tokens
        - Claude extended thinking: reasoning_tokens

        Args:
            usage: Usage object from response

        Returns:
            Normalized usage dictionary
        """
        result = {
            "input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        }

        # OpenAI format
        if hasattr(usage, "prompt_tokens"):
            result["input_tokens"] = getattr(usage, "prompt_tokens", 0) or 0
        elif hasattr(usage, "input_tokens"):
            result["input_tokens"] = getattr(usage, "input_tokens", 0) or 0

        if hasattr(usage, "completion_tokens"):
            result["output_tokens"] = getattr(usage, "completion_tokens", 0) or 0
        elif hasattr(usage, "output_tokens"):
            result["output_tokens"] = getattr(usage, "output_tokens", 0) or 0

        # Reasoning tokens (o1, o3 models)
        if hasattr(usage, "completion_tokens_details"):
            details = usage.completion_tokens_details
            if hasattr(details, "reasoning_tokens"):
                result["reasoning_tokens"] = getattr(details, "reasoning_tokens", 0) or 0

        # Anthropic cache tokens
        if hasattr(usage, "cache_read_input_tokens"):
            result["cache_read_tokens"] = getattr(usage, "cache_read_input_tokens", 0) or 0
        if hasattr(usage, "cache_creation_input_tokens"):
            result["cache_write_tokens"] = getattr(usage, "cache_creation_input_tokens", 0) or 0

        return result


def create_stream(
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    tools: list[dict[str, Any]] | None = None,
    **kwargs: Any,
) -> LLMStream:
    """
    Factory function to create LLM stream.

    Args:
        model: Model name (e.g., "gpt-4", "claude-3-opus")
        api_key: Optional API key
        base_url: Optional base URL override
        temperature: Sampling temperature
        max_tokens: Maximum output tokens
        tools: Optional list of tools for function calling
        **kwargs: Additional provider-specific options

    Returns:
        Configured LLMStream instance
    """
    config = StreamConfig(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
        max_tokens=max_tokens,
        tools=tools,
        provider_options=kwargs,
    )
    return LLMStream(config)
