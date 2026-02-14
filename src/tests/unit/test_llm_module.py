"""Unit tests for memstack_agent.llm module."""

import pytest

from memstack_agent.llm import (
    ChatResponse,
    LLMConfig,
    Message,
    MessageRole,
    StreamChunk,
    ToolCall,
    Usage,
    anthropic_config,
    create_llm_client,
    deepseek_config,
    gemini_config,
    openai_config,
)
from memstack_agent.llm.litellm_adapter import LiteLLMAdapter
from memstack_agent.llm.protocol import LLMClient, LLMClientSync


class TestMessage:
    """Tests for Message type."""

    def test_create_system_message(self) -> None:
        """Test creating a system message."""
        msg = Message.system("You are a helpful assistant.")
        assert msg.role == "system"
        assert msg.content == "You are a helpful assistant."
        assert msg.name is None
        assert msg.tool_call_id is None
        assert msg.tool_calls is None

    def test_create_user_message(self) -> None:
        """Test creating a user message."""
        msg = Message.user("Hello!")
        assert msg.role == "user"
        assert msg.content == "Hello!"

    def test_create_assistant_message(self) -> None:
        """Test creating an assistant message."""
        msg = Message.assistant("Hi there!")
        assert msg.role == "assistant"
        assert msg.content == "Hi there!"

    def test_create_assistant_message_with_tool_calls(self) -> None:
        """Test creating an assistant message with tool calls."""
        tool_call = ToolCall(id="call-123", name="search", arguments={"query": "test"})
        msg = Message.assistant(tool_calls=[tool_call])
        assert msg.role == "assistant"
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].name == "search"

    def test_create_tool_result_message(self) -> None:
        """Test creating a tool result message."""
        msg = Message.tool_result('{"result": "ok"}', tool_call_id="call-123", name="search")
        assert msg.role == "tool"
        assert msg.content == '{"result": "ok"}'
        assert msg.tool_call_id == "call-123"
        assert msg.name == "search"

    def test_message_to_dict(self) -> None:
        """Test message to dictionary conversion."""
        msg = Message.user("Hello")
        result = msg.to_dict()
        assert result["role"] == "user"
        assert result["content"] == "Hello"

    def test_message_to_dict_with_tool_calls(self) -> None:
        """Test message with tool calls to dictionary."""
        tool_call = ToolCall(id="call-1", name="test", arguments={"a": 1})
        msg = Message.assistant(content="", tool_calls=[tool_call])
        result = msg.to_dict()
        assert "tool_calls" in result
        assert result["tool_calls"][0]["function"]["name"] == "test"

    def test_message_immutability(self) -> None:
        """Test that messages are immutable."""
        msg = Message.user("Hello")
        with pytest.raises(AttributeError):
            msg.content = "Changed"  # type: ignore


class TestToolCall:
    """Tests for ToolCall type."""

    def test_create_tool_call(self) -> None:
        """Test creating a tool call."""
        tc = ToolCall(id="call-123", name="search", arguments={"query": "test"})
        assert tc.id == "call-123"
        assert tc.name == "search"
        assert tc.arguments == {"query": "test"}

    def test_tool_call_to_dict(self) -> None:
        """Test tool call to dictionary conversion."""
        tc = ToolCall(id="call-1", name="test", arguments={"a": 1, "b": 2})
        result = tc.to_dict()
        assert result["id"] == "call-1"
        assert result["type"] == "function"
        assert result["function"]["name"] == "test"
        assert result["function"]["arguments"] == {"a": 1, "b": 2}

    def test_tool_call_default_arguments(self) -> None:
        """Test tool call with default empty arguments."""
        tc = ToolCall(id="call-1", name="test")
        assert tc.arguments == {}

    def test_tool_call_immutability(self) -> None:
        """Test that tool calls are immutable."""
        tc = ToolCall(id="call-1", name="test")
        with pytest.raises(AttributeError):
            tc.name = "changed"  # type: ignore


class TestUsage:
    """Tests for Usage type."""

    def test_create_usage(self) -> None:
        """Test creating usage."""
        usage = Usage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        assert usage.prompt_tokens == 100
        assert usage.completion_tokens == 50
        assert usage.total_tokens == 150

    def test_usage_default_values(self) -> None:
        """Test usage with default values."""
        usage = Usage()
        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0
        assert usage.total_tokens == 0

    def test_usage_addition(self) -> None:
        """Test adding usage objects."""
        usage1 = Usage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        usage2 = Usage(prompt_tokens=200, completion_tokens=100, total_tokens=300)
        result = usage1 + usage2
        assert result.prompt_tokens == 300
        assert result.completion_tokens == 150
        assert result.total_tokens == 450

    def test_usage_immutability(self) -> None:
        """Test that usage is immutable."""
        usage = Usage(prompt_tokens=100)
        with pytest.raises(AttributeError):
            usage.prompt_tokens = 200  # type: ignore


class TestChatResponse:
    """Tests for ChatResponse type."""

    def test_create_chat_response(self) -> None:
        """Test creating a chat response."""
        response = ChatResponse(content="Hello!")
        assert response.content == "Hello!"
        assert response.tool_calls == []
        assert response.finish_reason is None

    def test_chat_response_with_tool_calls(self) -> None:
        """Test chat response with tool calls."""
        tool_call = ToolCall(id="call-1", name="test", arguments={})
        response = ChatResponse(content="", tool_calls=[tool_call])
        assert response.has_tool_calls is True
        assert len(response.tool_calls) == 1

    def test_chat_response_no_tool_calls(self) -> None:
        """Test chat response without tool calls."""
        response = ChatResponse(content="Hello")
        assert response.has_tool_calls is False

    def test_chat_response_immutability(self) -> None:
        """Test that chat response is immutable."""
        response = ChatResponse(content="Hello")
        with pytest.raises(AttributeError):
            response.content = "Changed"  # type: ignore


class TestStreamChunk:
    """Tests for StreamChunk type."""

    def test_create_stream_chunk(self) -> None:
        """Test creating a stream chunk."""
        chunk = StreamChunk(delta="Hello")
        assert chunk.delta == "Hello"
        assert chunk.tool_call_delta is None
        assert chunk.finish_reason is None

    def test_stream_chunk_is_final(self) -> None:
        """Test checking if chunk is final."""
        chunk = StreamChunk(delta="", finish_reason="stop")
        assert chunk.is_final is True

    def test_stream_chunk_not_final(self) -> None:
        """Test checking if chunk is not final."""
        chunk = StreamChunk(delta="Hello")
        assert chunk.is_final is False

    def test_stream_chunk_immutability(self) -> None:
        """Test that stream chunk is immutable."""
        chunk = StreamChunk(delta="Hello")
        with pytest.raises(AttributeError):
            chunk.delta = "Changed"  # type: ignore


class TestLLMConfig:
    """Tests for LLMConfig."""

    def test_create_config(self) -> None:
        """Test creating LLM config."""
        config = LLMConfig(model="gpt-4")
        assert config.model == "gpt-4"
        assert config.api_key is None
        assert config.temperature == 0.0
        assert config.max_tokens == 4096

    def test_with_model(self) -> None:
        """Test creating new config with different model."""
        config = LLMConfig(model="gpt-4", temperature=0.7)
        new_config = config.with_model("gpt-4-turbo")
        assert new_config.model == "gpt-4-turbo"
        assert new_config.temperature == 0.7
        assert config.model == "gpt-4"  # Original unchanged

    def test_with_temperature(self) -> None:
        """Test creating new config with different temperature."""
        config = LLMConfig(model="gpt-4", temperature=0.0)
        new_config = config.with_temperature(0.7)
        assert new_config.temperature == 0.7
        assert config.temperature == 0.0  # Original unchanged

    def test_config_immutability(self) -> None:
        """Test that config is immutable."""
        config = LLMConfig(model="gpt-4")
        with pytest.raises(AttributeError):
            config.model = "changed"  # type: ignore


class TestPresetConfigs:
    """Tests for preset configuration functions."""

    def test_anthropic_config(self) -> None:
        """Test Anthropic preset config."""
        config = anthropic_config(api_key="sk-ant-test")
        assert config.model == "anthropic/claude-3-sonnet-20240229"
        assert config.api_key == "sk-ant-test"

    def test_openai_config(self) -> None:
        """Test OpenAI preset config."""
        config = openai_config(api_key="sk-test")
        assert config.model == "openai/gpt-4-turbo-preview"
        assert config.api_key == "sk-test"

    def test_gemini_config(self) -> None:
        """Test Gemini preset config."""
        config = gemini_config(api_key="gemini-key")
        assert config.model == "gemini/gemini-pro"
        assert config.api_key == "gemini-key"

    def test_deepseek_config(self) -> None:
        """Test DeepSeek preset config."""
        config = deepseek_config(api_key="ds-key")
        assert config.model == "deepseek/deepseek-chat"
        assert config.api_key == "ds-key"


class TestLiteLLMAdapter:
    """Tests for LiteLLMAdapter."""

    def test_create_adapter(self) -> None:
        """Test creating LiteLLM adapter."""
        config = LLMConfig(model="openai/gpt-4", api_key="sk-test")
        adapter = LiteLLMAdapter(config)
        assert adapter._config.model == "openai/gpt-4"

    def test_adapter_with_config(self) -> None:
        """Test creating new adapter with modified config."""
        config = LLMConfig(model="openai/gpt-4", temperature=0.0)
        adapter = LiteLLMAdapter(config)
        new_adapter = adapter.with_config(temperature=0.7)
        assert new_adapter._config.temperature == 0.7
        assert adapter._config.temperature == 0.0


class TestCreateLLMClient:
    """Tests for create_llm_client factory function."""

    def test_create_client(self) -> None:
        """Test creating client via factory."""
        client = create_llm_client("openai/gpt-4", api_key="sk-test")
        assert isinstance(client, LiteLLMAdapter)
        assert client._config.model == "openai/gpt-4"

    def test_create_client_with_kwargs(self) -> None:
        """Test creating client with additional kwargs."""
        client = create_llm_client(
            "openai/gpt-4",
            api_key="sk-test",
            temperature=0.7,
            max_tokens=2000,
        )
        assert client._config.temperature == 0.7
        assert client._config.max_tokens == 2000


class TestProtocolCompliance:
    """Tests for Protocol compliance."""

    def test_litellm_adapter_is_llm_client(self) -> None:
        """Test that LiteLLMAdapter implements LLMClient protocol."""
        config = LLMConfig(model="openai/gpt-4")
        adapter = LiteLLMAdapter(config)
        assert isinstance(adapter, LLMClient)


class TestMessageRole:
    """Tests for MessageRole enum."""

    def test_message_role_values(self) -> None:
        """Test message role enum values."""
        assert MessageRole.SYSTEM.value == "system"
        assert MessageRole.USER.value == "user"
        assert MessageRole.ASSISTANT.value == "assistant"
        assert MessageRole.TOOL.value == "tool"
