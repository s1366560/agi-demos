"""LiteLLM adapter for memstack-agent."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

import litellm
from litellm import acompletion

from memstack_agent.llm.config import LLMConfig
from memstack_agent.llm.protocol import LLMClient
from memstack_agent.llm.types import ChatResponse, Message, StreamChunk, ToolCall, Usage

if TYPE_CHECKING:
    from litellm import ModelResponse

from memstack_agent.tools.protocol import ToolDefinition

logger = logging.getLogger(__name__)


class LiteLLMAdapter(LLMClient):
    """LiteLLM-based LLM client implementation.

    Supports 100+ providers through LiteLLM's unified interface.
    Providers are specified via model prefix (e.g., "openai/gpt-4", "anthropic/claude-3").

    Example:
        config = LLMConfig(model="openai/gpt-4", api_key="sk-...")
        client = LiteLLMAdapter(config)

        # Non-streaming
        response = await client.generate([
            Message.user("Hello!")
        ])

        # Streaming
        async for chunk in client.stream([Message.user("Hello!")]):
            print(chunk.delta, end="")
    """

    def __init__(self, config: LLMConfig) -> None:
        """Initialize LiteLLM adapter.

        Args:
            config: LLM configuration
        """
        self._config = config
        self._setup_litellm()

    def _setup_litellm(self) -> None:
        """Configure LiteLLM settings."""
        # Set API key if provided
        if self._config.api_key:
            # LiteLLM uses provider-specific env vars, but we can set via api_key
            pass  # Will be passed in completion call

        # Set base URL if provided
        if self._config.base_url:
            litellm.api_base = self._config.base_url

        # Configure timeouts
        litellm.request_timeout = self._config.timeout_seconds

    def _build_completion_params(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Build parameters for litellm completion call.

        Args:
            messages: Chat messages
            tools: Optional tool definitions
            **kwargs: Additional parameters

        Returns:
            Dictionary of completion parameters
        """
        params: dict[str, Any] = {
            "model": self._config.model,
            "messages": [msg.to_dict() for msg in messages],
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
            "top_p": self._config.top_p,
        }

        # Add API key if configured
        if self._config.api_key:
            params["api_key"] = self._config.api_key

        # Add base URL if configured
        if self._config.base_url:
            params["api_base"] = self._config.base_url

        # Convert tools to LiteLLM format
        if tools:
            params["tools"] = [self._tool_to_litellm_format(tool) for tool in tools]

        # Override with any additional kwargs
        params.update(kwargs)

        return params

    def _tool_to_litellm_format(self, tool: ToolDefinition) -> dict[str, Any]:
        """Convert ToolDefinition to LiteLLM tool format.

        Args:
            tool: Tool definition

        Returns:
            LiteLLM-compatible tool dict
        """
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }

    def _parse_tool_calls(self, response_tool_calls: list[Any]) -> list[ToolCall]:
        """Parse tool calls from LiteLLM response.

        Args:
            response_tool_calls: Raw tool calls from LiteLLM

        Returns:
            List of ToolCall objects
        """
        tool_calls = []
        for tc in response_tool_calls:
            # Parse arguments from JSON string
            args = {}
            if hasattr(tc.function, "arguments"):
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse tool arguments: {tc.function.arguments}")
                    args = {"raw_arguments": tc.function.arguments}

            tool_calls.append(
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                )
            )
        return tool_calls

    def _extract_usage(self, response: ModelResponse) -> Usage:
        """Extract token usage from LiteLLM response.

        Args:
            response: LiteLLM response object

        Returns:
            Usage object
        """
        if hasattr(response, "usage") and response.usage:
            return Usage(
                prompt_tokens=getattr(response.usage, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(response.usage, "completion_tokens", 0) or 0,
                total_tokens=getattr(response.usage, "total_tokens", 0) or 0,
            )
        return Usage()

    async def generate(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """Generate a non-streaming response.

        Args:
            messages: List of conversation messages
            tools: Optional tool definitions for function calling
            **kwargs: Additional provider-specific parameters

        Returns:
            ChatResponse with content and optional tool calls
        """
        params = self._build_completion_params(messages, tools, **kwargs)

        try:
            response = await acompletion(**params)

            # Extract content
            content = ""
            if response.choices and len(response.choices) > 0:
                choice = response.choices[0]
                content = choice.message.content or ""

            # Extract tool calls
            tool_calls = []
            if (
                response.choices
                and len(response.choices) > 0
                and hasattr(response.choices[0].message, "tool_calls")
                and response.choices[0].message.tool_calls
            ):
                tool_calls = self._parse_tool_calls(response.choices[0].message.tool_calls)

            # Extract finish reason
            finish_reason = None
            if response.choices and len(response.choices) > 0:
                finish_reason = response.choices[0].finish_reason

            # Extract usage
            usage = self._extract_usage(response)

            return ChatResponse(
                content=content,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
                usage=usage,
                model=self._config.model,
            )

        except Exception as e:
            logger.error(f"LiteLLM generate error: {e}")
            raise

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Generate a streaming response.

        Args:
            messages: List of conversation messages
            tools: Optional tool definitions for function calling
            **kwargs: Additional provider-specific parameters

        Yields:
            StreamChunk objects with incremental content
        """
        params = self._build_completion_params(messages, tools, **kwargs)
        params["stream"] = True

        try:
            response = await acompletion(**params)

            async for chunk in response:
                if not chunk.choices or len(chunk.choices) == 0:
                    continue

                choice = chunk.choices[0]

                # Extract delta content
                delta = ""
                if hasattr(choice.delta, "content") and choice.delta.content:
                    delta = choice.delta.content

                # Extract finish reason
                finish_reason = getattr(choice, "finish_reason", None)

                # Handle tool call deltas (for streaming tool calls)
                tool_call_delta = None
                if hasattr(choice.delta, "tool_calls") and choice.delta.tool_calls:
                    # Note: Full tool call handling in streaming is complex
                    # This is a simplified version
                    pass

                yield StreamChunk(
                    delta=delta,
                    tool_call_delta=tool_call_delta,
                    finish_reason=finish_reason,
                )

        except Exception as e:
            logger.error(f"LiteLLM stream error: {e}")
            raise

    def with_config(self, **kwargs: Any) -> LiteLLMAdapter:
        """Create a new adapter with modified configuration.

        Args:
            **kwargs: Configuration overrides

        Returns:
            New LiteLLMAdapter with modified config
        """
        new_config = LLMConfig(
            model=kwargs.get("model", self._config.model),
            api_key=kwargs.get("api_key", self._config.api_key),
            base_url=kwargs.get("base_url", self._config.base_url),
            temperature=kwargs.get("temperature", self._config.temperature),
            max_tokens=kwargs.get("max_tokens", self._config.max_tokens),
            top_p=kwargs.get("top_p", self._config.top_p),
            timeout_seconds=kwargs.get("timeout_seconds", self._config.timeout_seconds),
        )
        return LiteLLMAdapter(new_config)


def create_llm_client(
    model: str,
    api_key: str | None = None,
    **kwargs: Any,
) -> LiteLLMAdapter:
    """Factory function to create an LLM client.

    Args:
        model: Model identifier with provider prefix (e.g., "openai/gpt-4")
        api_key: Optional API key
        **kwargs: Additional configuration options

    Returns:
        Configured LiteLLMAdapter instance

    Example:
        # OpenAI
        client = create_llm_client("openai/gpt-4", api_key="sk-...")

        # Anthropic
        client = create_llm_client("anthropic/claude-3-sonnet", api_key="sk-ant-...")

        # DeepSeek
        client = create_llm_client("deepseek/deepseek-chat", api_key="sk-...")

        # Local model via Ollama
        client = create_llm_client("ollama/llama2", base_url="http://localhost:11434")
    """
    config = LLMConfig(model=model, api_key=api_key, **kwargs)
    return LiteLLMAdapter(config)


__all__ = [
    "LiteLLMAdapter",
    "create_llm_client",
]
