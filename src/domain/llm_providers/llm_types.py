"""
LLM type definitions for the knowledge graph system.

This module provides local type definitions that were previously imported from graphiti_core.
These types are used across the LLM client implementations.

This module serves as the unified LLM abstraction layer, replacing LangChain dependencies.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel

# Constants
DEFAULT_MAX_TOKENS = 4096


class ModelSize(str, Enum):
    """Model size enumeration for selecting appropriate models."""

    small = "small"
    medium = "medium"
    large = "large"


class MessageRole(str, Enum):
    """Role enumeration for chat messages."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class Message:
    """Chat message for LLM interactions."""

    role: str  # "system", "user", "assistant"
    content: str

    @classmethod
    def system(cls, content: str) -> "Message":
        """Create a system message."""
        return cls(role=MessageRole.SYSTEM.value, content=content)

    @classmethod
    def user(cls, content: str) -> "Message":
        """Create a user message."""
        return cls(role=MessageRole.USER.value, content=content)

    @classmethod
    def assistant(cls, content: str) -> "Message":
        """Create an assistant message."""
        return cls(role=MessageRole.ASSISTANT.value, content=content)


@dataclass
class ChatResponse:
    """Response from LLM chat completion."""

    content: str
    role: str = MessageRole.ASSISTANT.value
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        """Alias for content for compatibility."""
        return self.content


@dataclass
class LLMConfig:
    """Configuration for LLM clients."""

    api_key: str | None = None
    model: str = ""
    small_model: str | None = None
    temperature: float = 0.0
    max_tokens: int = 4096
    base_url: str | None = None


class RateLimitError(Exception):
    """Exception raised when LLM rate limit is exceeded."""



class LLMClient(ABC):
    """
    Abstract base class for LLM clients.

    This provides a consistent interface for LLM interactions across different providers.
    It serves as a unified abstraction replacing LangChain's BaseChatModel.
    """

    def __init__(self, config: LLMConfig, cache: bool = True) -> None:
        """
        Initialize the LLM client.

        Args:
            config: LLM configuration
            cache: Whether to enable response caching
        """
        self.config = config
        self.cache = cache
        self.temperature = config.temperature

    @abstractmethod
    async def _generate_response(
        self,
        messages: list[Message],
        response_model: type[BaseModel] | None = None,
        max_tokens: int = 4096,
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

    async def generate_response(
        self,
        messages: list[Message],
        response_model: type[BaseModel] | None = None,
        max_tokens: int = 4096,
        model_size: ModelSize = ModelSize.medium,
    ) -> dict[str, Any]:
        """
        Public method to generate a response.

        This method can implement caching logic around the abstract _generate_response.
        """
        return await self._generate_response(
            messages=messages,
            response_model=response_model,
            max_tokens=max_tokens,
            model_size=model_size,
        )

    async def ainvoke(
        self,
        messages: list[Message] | str,
        **kwargs: Any,
    ) -> ChatResponse:
        """
        Async invoke method for chat completion (LangChain-style interface).

        This method provides a simpler interface similar to LangChain's ainvoke().

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
            content = str(response)  # type: ignore[unreachable]

        return ChatResponse(content=content)


# Embedder types


@dataclass
class EmbedderConfig:
    """Configuration for embedding clients."""

    api_key: str | None = None
    model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    embedding_model: str | None = None
    base_url: str | None = None


class EmbedderClient(ABC):
    """
    Abstract base class for embedding clients.

    Provides a consistent interface for text embedding across different providers.
    """

    def __init__(self, config: EmbedderConfig) -> None:
        """
        Initialize the embedder client.

        Args:
            config: Embedder configuration
        """
        self.config = config

    @abstractmethod
    async def create(self, input_data: list[str]) -> list[list[float]]:
        """
        Create embeddings for the given input texts.

        Args:
            input_data: List of texts to embed

        Returns:
            List of embedding vectors
        """


# Cross-encoder/Reranker types


class CrossEncoderClient(ABC):
    """
    Abstract base class for cross-encoder/reranker clients.

    Provides a consistent interface for reranking across different providers.
    """

    @abstractmethod
    async def rank(
        self,
        query: str,
        passages: list[str],
        top_n: int | None = None,
    ) -> list[tuple[int, float]]:
        """
        Rank passages by relevance to query.

        Args:
            query: The query string
            passages: List of passages to rank
            top_n: Optional limit on number of results

        Returns:
            List of (index, score) tuples sorted by relevance
        """
