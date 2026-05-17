"""Unit tests for the current domain LLM abstraction."""

from collections.abc import AsyncGenerator
from typing import Any

from pydantic import BaseModel

from src.domain.llm_providers.llm_types import (
    DEFAULT_MAX_TOKENS,
    ChatResponse,
    LLMClient,
    LLMConfig,
    Message,
    MessageRole,
    ModelSize,
)


class FakeLLMClient(LLMClient):
    """Small concrete client for exercising the abstract base behavior."""

    async def _generate_response(
        self,
        messages: list[Message],
        response_model: type[BaseModel] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model_size: ModelSize = ModelSize.medium,
    ) -> dict[str, Any]:
        del response_model, max_tokens, model_size
        return {"content": messages[-1].text}

    async def generate(
        self,
        messages: list[Message] | list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model_size: ModelSize = ModelSize.medium,
        langfuse_context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del tools, temperature, max_tokens, model_size, langfuse_context, kwargs
        last = messages[-1]
        if isinstance(last, Message):
            return {"content": last.text}
        return {"content": str(last.get("content", ""))}

    async def generate_stream(
        self,
        messages: list[Message],
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model_size: ModelSize = ModelSize.medium,
        langfuse_context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, str], None]:
        del max_tokens, model_size, langfuse_context, kwargs
        yield {"content": messages[-1].text}


class TestMessage:
    """Tests for domain chat messages."""

    def test_create_system_message(self) -> None:
        msg = Message.system("You are a helpful assistant.")

        assert msg.role == MessageRole.SYSTEM.value
        assert msg.content == "You are a helpful assistant."
        assert msg.text == "You are a helpful assistant."

    def test_create_user_message(self) -> None:
        msg = Message.user("Hello!")

        assert msg.role == MessageRole.USER.value
        assert msg.content == "Hello!"

    def test_create_assistant_message(self) -> None:
        msg = Message.assistant("Hi there!")

        assert msg.role == MessageRole.ASSISTANT.value
        assert msg.content == "Hi there!"

    def test_create_multimodal_user_message_extracts_text_parts(self) -> None:
        msg = Message.user_multimodal(
            [
                {"type": "text", "text": "first"},
                {"type": "image_url", "image_url": {"url": "https://example.invalid/image.png"}},
                {"type": "text", "text": "second"},
            ]
        )

        assert msg.role == MessageRole.USER.value
        assert msg.text == "first\nsecond"


class TestChatResponse:
    """Tests for chat response compatibility helpers."""

    def test_create_chat_response(self) -> None:
        response = ChatResponse(content="Hello!")

        assert response.content == "Hello!"
        assert response.role == MessageRole.ASSISTANT.value
        assert response.metadata == {}

    def test_text_alias_returns_content(self) -> None:
        response = ChatResponse(content="Hello!")

        assert response.text == response.content

    def test_metadata_is_per_instance(self) -> None:
        first = ChatResponse(content="one")
        second = ChatResponse(content="two")
        first.metadata["provider"] = "fake"

        assert second.metadata == {}


class TestLLMConfig:
    """Tests for domain LLM configuration."""

    def test_create_config_with_defaults(self) -> None:
        config = LLMConfig(model="gpt-4")

        assert config.model == "gpt-4"
        assert config.api_key is None
        assert config.temperature == 0.0
        assert config.max_tokens == DEFAULT_MAX_TOKENS
        assert config.top_p is None
        assert config.response_format is None

    def test_create_config_with_extended_generation_parameters(self) -> None:
        config = LLMConfig(
            model="gpt-4",
            top_p=0.9,
            frequency_penalty=0.2,
            presence_penalty=0.1,
            seed=42,
            stop=["END"],
            response_format={"type": "json_object"},
        )

        assert config.top_p == 0.9
        assert config.frequency_penalty == 0.2
        assert config.presence_penalty == 0.1
        assert config.seed == 42
        assert config.stop == ["END"]
        assert config.response_format == {"type": "json_object"}


class TestLLMClient:
    """Tests for the domain LLM client base behavior."""

    async def test_generate_response_delegates_to_subclass(self) -> None:
        client = FakeLLMClient(LLMConfig(model="fake"))

        result = await client.generate_response([Message.user("Hello")])

        assert result == {"content": "Hello"}

    async def test_ainvoke_accepts_string_prompt(self) -> None:
        client = FakeLLMClient(LLMConfig(model="fake"))

        result = await client.ainvoke("Hello")

        assert isinstance(result, ChatResponse)
        assert result.content == "Hello"

    async def test_generate_accepts_message_objects(self) -> None:
        client = FakeLLMClient(LLMConfig(model="fake"))

        result = await client.generate([Message.user("Hello")])

        assert result == {"content": "Hello"}

    async def test_generate_stream_yields_message_text(self) -> None:
        client = FakeLLMClient(LLMConfig(model="fake"))

        chunks = [chunk async for chunk in client.generate_stream([Message.user("Hello")])]

        assert chunks == [{"content": "Hello"}]


class TestMessageRole:
    """Tests for MessageRole enum."""

    def test_message_role_values(self) -> None:
        assert MessageRole.SYSTEM.value == "system"
        assert MessageRole.USER.value == "user"
        assert MessageRole.ASSISTANT.value == "assistant"
