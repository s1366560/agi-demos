"""
Unified LLM client adapter for LiteLLMClient.

This module provides a wrapper that exposes LiteLLMClient through the domain's
unified LLMClient interface, replacing LangChain dependencies with our own
abstraction layer.
"""

import logging
from typing import Any, Optional

from src.domain.llm_providers.llm_types import (
    DEFAULT_MAX_TOKENS,
    ChatResponse,
    LLMClient,
    LLMConfig,
    Message,
    ModelSize,
)

logger = logging.getLogger(__name__)


class UnifiedLLMClient(LLMClient):
    """
    Unified LLM client adapter wrapping LiteLLMClient.

    This adapter enables using LiteLLM's unified multi-provider interface
    through the domain's standard LLMClient interface. This allows all
    components to use a consistent API while leveraging LiteLLM's 100+
    provider support.

    This class replaces the previous LangChainCompatibleLLM adapter,
    removing the dependency on langchain-core.

    Example:
        from src.infrastructure.llm.litellm.litellm_client import create_litellm_client
        from src.infrastructure.llm.litellm.unified_llm_client import UnifiedLLMClient

        litellm_client = create_litellm_client(provider_config)
        unified_client = UnifiedLLMClient(litellm_client=litellm_client)

        # Use with domain interface
        response = await unified_client.ainvoke([Message.user("Hello")])
        print(response.content)
    """

    def __init__(
        self,
        litellm_client: Any,  # LiteLLMClient - use Any to avoid circular imports
        temperature: float = 0.7,
        config: Optional[LLMConfig] = None,
    ):
        """
        Initialize the unified LLM client.

        Args:
            litellm_client: The underlying LiteLLMClient instance
            temperature: Default temperature for generation
            config: Optional LLMConfig (will create default if not provided)
        """
        # Create a minimal config if not provided
        if config is None:
            config = LLMConfig(temperature=temperature)

        super().__init__(config=config, cache=True)
        self._litellm_client = litellm_client
        self.temperature = temperature

    @property
    def litellm_client(self) -> Any:
        """Access the underlying LiteLLM client."""
        return self._litellm_client

    async def _generate_response(
        self,
        messages: list[Message],
        response_model: Any = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model_size: ModelSize = ModelSize.medium,
    ) -> dict[str, Any]:
        """
        Generate a response from the LLM.

        Args:
            messages: List of conversation messages
            response_model: Optional Pydantic model for structured output
            max_tokens: Maximum tokens in response
            model_size: Which model size to use

        Returns:
            Dictionary containing the response
        """
        try:
            response = await self._litellm_client._generate_response(
                messages=messages,
                response_model=response_model,
                max_tokens=max_tokens,
                model_size=model_size,
            )
            return response
        except Exception as e:
            logger.error(f"UnifiedLLMClient generation failed: {e}")
            raise

    async def ainvoke(
        self,
        messages: list[Message] | str,
        **kwargs: Any,  # noqa: ANN401
    ) -> ChatResponse:
        """
        Async invoke method for chat completion.

        This method provides a simpler interface for chat completion.

        Args:
            messages: List of Message objects or a single string prompt
            **kwargs: Additional keyword arguments (temperature, max_tokens, etc.)

        Returns:
            ChatResponse containing the assistant's response
        """
        # Convert string to messages
        if isinstance(messages, str):
            messages = [Message.user(messages)]

        # Call the underlying generate method
        response = await self._generate_response(
            messages=messages,
            response_model=None,
            max_tokens=kwargs.get("max_tokens", DEFAULT_MAX_TOKENS),
        )

        # Extract content from response
        if isinstance(response, dict):
            content = response.get("content", "")
        else:
            content = str(response)

        return ChatResponse(content=content)

    async def generate_chat(
        self,
        system_prompt: str,
        user_message: str,
        **kwargs: Any,  # noqa: ANN401
    ) -> ChatResponse:
        """
        Convenience method for simple system + user message chat.

        Args:
            system_prompt: System message content
            user_message: User message content
            **kwargs: Additional generation parameters

        Returns:
            ChatResponse containing the assistant's response
        """
        messages = [
            Message.system(system_prompt),
            Message.user(user_message),
        ]
        return await self.ainvoke(messages, **kwargs)
