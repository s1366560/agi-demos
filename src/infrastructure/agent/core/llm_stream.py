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

import json
import logging
import random
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================================
# Model to Provider Mapping
# ============================================================================

# Model name prefixes that map to specific providers
MODEL_PROVIDER_MAP: Dict[str, str] = {
    # Qwen/Dashscope models
    "qwen-": "qwen",
    "qwq-": "qwen",
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
        Provider type: "qwen", "openai", "gemini", "deepseek", "zhipu"
    """
    model_lower = model.lower()

    for prefix, provider in MODEL_PROVIDER_MAP.items():
        if model_lower.startswith(prefix):
            return provider

    # Default to qwen for unknown models (most restrictive)
    return "qwen"


# ============================================================================
# P0-2: Batch Logging and Token Delta Sampling
# ============================================================================


class TokenDeltaSampler:
    """
    Samples token deltas for logging to reduce I/O overhead.

    Instead of logging every single token delta (which can be thousands),
    this sampler intelligently selects which deltas to log based on:
    - Sample rate: Probability of sampling each delta
    - Minimum interval: Minimum time between samples
    - First delta: Always logged for debugging

    Usage:
        sampler = TokenDeltaSampler(sample_rate=0.1, min_sample_interval=0.5)
        sampler.reset()
        for delta in deltas:
            if sampler.should_sample(delta):
                logger.info(f"Sampled delta: {delta}")
    """

    def __init__(
        self,
        sample_rate: float = 0.1,
        min_sample_interval: float = 0.5,
    ):
        """
        Initialize the token delta sampler.

        Args:
            sample_rate: Probability of sampling each delta (0.0 to 1.0).
                        0.0 = only interval-based sampling, 1.0 = sample all.
            min_sample_interval: Minimum seconds between samples.
        """
        self.sample_rate = max(0.0, min(1.0, sample_rate))
        self.min_sample_interval = max(0.0, min_sample_interval)
        self._last_sample_time = 0.0
        self._count = 0

    def reset(self) -> None:
        """Reset the sampler state for a new stream."""
        self._last_sample_time = 0.0
        self._count = 0

    def should_sample(self, delta: str) -> bool:
        """
        Determine if a delta should be sampled.

        Args:
            delta: The token delta content.

        Returns:
            True if the delta should be logged, False otherwise.
        """
        self._count += 1
        now = time.time()

        # Always sample the first delta
        if self._count == 1:
            self._last_sample_time = now
            return True

        # Check minimum interval
        if now - self._last_sample_time < self.min_sample_interval:
            return False

        # Apply sample rate (if not 0 or 1)
        if 0.0 < self.sample_rate < 1.0:
            should_sample = random.random() < self.sample_rate
            if should_sample:
                self._last_sample_time = now
            return should_sample

        # Edge cases: sample_rate == 0.0 or 1.0
        if self.sample_rate == 0.0:
            # Only interval-based sampling
            if now - self._last_sample_time >= self.min_sample_interval:
                self._last_sample_time = now
                return True
            return False

        # sample_rate == 1.0: sample all (subject to interval)
        if now - self._last_sample_time >= self.min_sample_interval:
            self._last_sample_time = now
        return True


class BatchLogBuffer:
    """
    Buffers log entries and flushes them in batches to reduce I/O.

    Instead of writing each log entry immediately, this buffer:
    - Accumulates entries up to max_size
    - Flushes periodically based on flush_interval
    - Provides manual flush capability

    Usage:
        buffer = BatchLogBuffer(max_size=100, flush_interval=1.0)
        buffer.add("info", "Processing chunk")
        buffer.add("debug", "Token count: 42")
        # Auto-flush when full or after interval
    """

    def __init__(
        self,
        max_size: int = 100,
        flush_interval: float = 1.0,
        flush_callback: Optional[Callable[[List[Dict[str, Any]]], None]] = None,
    ):
        """
        Initialize the batch log buffer.

        Args:
            max_size: Maximum number of entries before auto-flush.
            flush_interval: Seconds between auto-flushes (0 = disable).
            flush_callback: Optional callback for flushed entries.
        """
        self.max_size = max_size
        self.flush_interval = flush_interval
        self.flush_callback = flush_callback or self._default_flush
        self.entries: List[Dict[str, Any]] = []
        self._last_flush_time = time.time()

    def _default_flush(self, entries: List[Dict[str, Any]]) -> None:
        """Default flush callback - logs to standard logger."""
        for entry in entries:
            level = entry.get("level", "info").lower()
            message = entry.get("message", "")
            if level == "debug":
                logger.debug(message)
            elif level == "info":
                logger.info(message)
            elif level == "warning":
                logger.warning(message)
            elif level == "error":
                logger.error(message)

    def add(self, level: str, message: str, **kwargs) -> None:
        """
        Add a log entry to the buffer.

        Args:
            level: Log level (debug, info, warning, error).
            message: Log message.
            **kwargs: Additional metadata to include with the entry.
        """
        entry = {
            "level": level,
            "message": message,
            "timestamp": time.time(),
            **kwargs,
        }
        self.entries.append(entry)

        # Auto-flush if at max size
        if len(self.entries) >= self.max_size:
            self.flush()

    def flush(self) -> None:
        """Flush all buffered entries via the callback."""
        if not self.entries:
            return

        try:
            self.flush_callback(self.entries)
        except Exception as e:
            # Don't let logging errors break the stream
            logger.warning(f"[BatchLogBuffer] Flush failed: {e}")
        finally:
            self.entries.clear()
            self._last_flush_time = time.time()

    def should_flush(self) -> bool:
        """
        Check if buffer should flush based on time interval.

        Returns:
            True if flush_interval has passed since last flush.
        """
        if self.flush_interval <= 0:
            return False
        return (time.time() - self._last_flush_time) >= self.flush_interval


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

    def to_dict(self) -> Dict[str, Any]:
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
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    @classmethod
    def text_start(cls) -> "StreamEvent":
        """Create text start event."""
        return cls(StreamEventType.TEXT_START)

    @classmethod
    def text_delta(cls, delta: str) -> "StreamEvent":
        """Create text delta event."""
        return cls(StreamEventType.TEXT_DELTA, {"delta": delta})

    @classmethod
    def text_end(cls, full_text: str = "") -> "StreamEvent":
        """Create text end event."""
        return cls(StreamEventType.TEXT_END, {"full_text": full_text})

    @classmethod
    def reasoning_start(cls) -> "StreamEvent":
        """Create reasoning start event."""
        return cls(StreamEventType.REASONING_START)

    @classmethod
    def reasoning_delta(cls, delta: str) -> "StreamEvent":
        """Create reasoning delta event."""
        return cls(StreamEventType.REASONING_DELTA, {"delta": delta})

    @classmethod
    def reasoning_end(cls, full_text: str = "") -> "StreamEvent":
        """Create reasoning end event."""
        return cls(StreamEventType.REASONING_END, {"full_text": full_text})

    @classmethod
    def tool_call_start(
        cls,
        call_id: str,
        name: str,
        index: int = 0,
    ) -> "StreamEvent":
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
    ) -> "StreamEvent":
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
        arguments: Dict[str, Any],
    ) -> "StreamEvent":
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
    ) -> "StreamEvent":
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
    def finish(cls, reason: str) -> "StreamEvent":
        """Create finish event."""
        return cls(StreamEventType.FINISH, {"reason": reason})

    @classmethod
    def error(cls, message: str, code: str = None) -> "StreamEvent":
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
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.0
    max_tokens: int = 4096

    # Tool configuration
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[str] = None  # "auto", "none", "required", or specific tool

    # Provider-specific options
    provider_options: Dict[str, Any] = field(default_factory=dict)

    # Provider for rate limiting (inferred from model if not set)
    provider: Optional[str] = None

    # Request metadata (increased from 300 to 600 seconds for long-running agents)
    timeout: int = 600  # seconds (10 minutes)

    def get_provider(self) -> str:
        """Get the provider type, inferring from model if not set."""
        if self.provider:
            return self.provider
        return infer_provider_from_model(self.model)

    def to_litellm_kwargs(self) -> Dict[str, Any]:
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

    def __init__(self, config: StreamConfig):
        """
        Initialize LLM stream.

        Args:
            config: Stream configuration
        """
        self.config = config

        # Accumulated state during streaming
        self._text_buffer: str = ""
        self._reasoning_buffer: str = ""
        self._tool_calls: Dict[int, ToolCallChunk] = {}
        self._in_text: bool = False
        self._in_reasoning: bool = False

        # Usage tracking
        self._usage: Optional[Dict[str, int]] = None
        self._finish_reason: Optional[str] = None

        # P0-2: Batch logging and token delta sampling
        # Get configuration from environment or use defaults
        import os

        sample_rate = float(os.environ.get("LLM_LOG_SAMPLE_RATE", "0.1"))
        min_interval = float(os.environ.get("LLM_LOG_MIN_INTERVAL", "0.5"))
        buffer_size = int(os.environ.get("LLM_LOG_BUFFER_SIZE", "100"))
        buffer_interval = float(os.environ.get("LLM_LOG_BUFFER_INTERVAL", "1.0"))

        self._token_sampler = TokenDeltaSampler(
            sample_rate=sample_rate,
            min_sample_interval=min_interval,
        )
        self._log_buffer = BatchLogBuffer(
            max_size=buffer_size,
            flush_interval=buffer_interval,
        )

    async def generate(
        self,
        messages: List[Dict[str, Any]],
        request_id: Optional[str] = None,
        langfuse_context: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[StreamEvent]:
        """
        Generate streaming response from LLM.

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
        import litellm

        # Import rate limiter for concurrency control
        from src.infrastructure.llm.rate_limiter import (
            ProviderType,
            RateLimitError,
            get_rate_limiter,
        )

        request_id = request_id or str(uuid.uuid4())

        # Reset state
        self._reset_state()

        # Prepare kwargs
        kwargs = self.config.to_litellm_kwargs()
        kwargs["messages"] = messages

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

        logger.debug(f"Starting LLM stream: model={self.config.model}, request_id={request_id}")

        start_time = time.time()

        # Get rate limiter and provider type
        rate_limiter = get_rate_limiter()
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

            elapsed = time.time() - start_time
            logger.debug(f"LLM stream completed: request_id={request_id}, elapsed={elapsed:.2f}s")

        except RateLimitError as e:
            logger.warning(f"Rate limit exceeded for {provider_name}: {e}")
            yield StreamEvent.error(
                "Rate limit exceeded. Please wait a moment and try again.", code="RATE_LIMIT"
            )
        except Exception as e:
            logger.error(f"LLM stream error: {e}", exc_info=True)
            yield StreamEvent.error(str(e), code=type(e).__name__)

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
        # Extract choices
        choices = getattr(chunk, "choices", [])
        if not choices:
            logger.debug("[LLMStream] chunk has no choices")
            return

        choice = choices[0]
        delta = getattr(choice, "delta", None)

        if delta is None:
            logger.debug("[LLMStream] choice has no delta")
            return

        # Debug: log delta contents
        logger.info(
            f"[LLMStream] delta: content={getattr(delta, 'content', None)}, tool_calls={getattr(delta, 'tool_calls', None)}"
        )

        # Check for content (text)
        content = getattr(delta, "content", None)
        if content:
            logger.info(f"[LLMStream] TEXT_DELTA: {content[:50]}...")
            # Start text stream if not started
            if not self._in_text:
                self._in_text = True
                yield StreamEvent.text_start()

            self._text_buffer += content
            yield StreamEvent.text_delta(content)

        # Check for reasoning content (o1, Claude extended thinking)
        # Different providers may use different field names
        reasoning = (
            getattr(delta, "reasoning_content", None)
            or getattr(delta, "thinking", None)
            or getattr(delta, "reasoning", None)
        )
        if reasoning:
            if not self._in_reasoning:
                self._in_reasoning = True
                yield StreamEvent.reasoning_start()

            self._reasoning_buffer += reasoning
            yield StreamEvent.reasoning_delta(reasoning)

        # Check for tool calls
        tool_calls = getattr(delta, "tool_calls", None)
        if tool_calls:
            async for event in self._process_tool_calls(tool_calls):
                yield event

        # Check for finish reason
        finish_reason = getattr(choice, "finish_reason", None)
        if finish_reason:
            self._finish_reason = finish_reason

        # Check for usage (usually in final chunk)
        usage = getattr(chunk, "usage", None)
        if usage:
            self._usage = self._extract_usage(usage)

    async def _process_tool_calls(
        self,
        tool_calls: List[Any],
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
        # IMPORTANT: End reasoning stream BEFORE text stream
        # Reasoning (thought) should logically complete before the final response (text)
        # This ensures correct timeline ordering in the frontend:
        # thought -> response (not response -> thought)
        if self._in_reasoning:
            yield StreamEvent.reasoning_end(self._reasoning_buffer)
            self._in_reasoning = False

        # End text stream after reasoning is complete
        if self._in_text:
            yield StreamEvent.text_end(self._text_buffer)
            self._in_text = False

        # Complete any pending tool calls
        for index, tracker in self._tool_calls.items():
            if not tracker.complete:
                tracker.complete = True

                # Parse arguments
                try:
                    arguments = json.loads(tracker.arguments) if tracker.arguments else {}
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse tool arguments: {tracker.arguments}")
                    arguments = {"_raw": tracker.arguments}

                yield StreamEvent.tool_call_end(
                    call_id=tracker.id,
                    name=tracker.name,
                    arguments=arguments,
                )

        # Emit usage if available
        if self._usage:
            yield StreamEvent.usage(**self._usage)

        # Emit finish event
        yield StreamEvent.finish(self._finish_reason or "stop")

    def _extract_usage(self, usage: Any) -> Dict[str, int]:
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
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    tools: Optional[List[Dict[str, Any]]] = None,
    **kwargs,
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
