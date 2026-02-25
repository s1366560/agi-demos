"""
Unit tests for UnifiedLLMClient adapter.

Tests the adapter's ability to wrap LiteLLMClient and provide
a unified LLMClient interface using domain Message types.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.llm_providers.llm_types import ChatResponse, Message
from src.infrastructure.llm.litellm.unified_llm_client import UnifiedLLMClient


class TestUnifiedLLMClient:
    """Tests for UnifiedLLMClient adapter."""

    @pytest.fixture
    def mock_litellm_client(self):
        """Create a mock LiteLLMClient."""
        client = MagicMock()
        client.generate = AsyncMock(return_value={"content": "Test response"})
        return client

    @pytest.fixture
    def adapter(self, mock_litellm_client):
        """Create adapter instance with mock client."""
        return UnifiedLLMClient(
            litellm_client=mock_litellm_client,
            temperature=0.7,
        )

    @pytest.mark.unit
    async def test_ainvoke_with_string(self, adapter, mock_litellm_client):
        """Test ainvoke with simple string input."""
        result = await adapter.ainvoke("Hello")
        assert isinstance(result, ChatResponse)
        assert result.content == "Test response"
        mock_litellm_client.generate.assert_called_once()

    @pytest.mark.unit
    async def test_ainvoke_with_single_message(self, adapter, mock_litellm_client):
        """Test ainvoke with single Message."""
        messages = [Message.user("Hello")]
        result = await adapter.ainvoke(messages)
        assert isinstance(result, ChatResponse)
        assert result.content == "Test response"
        mock_litellm_client.generate.assert_called_once()

    @pytest.mark.unit
    async def test_ainvoke_with_system_and_user(self, adapter, mock_litellm_client):
        """Test ainvoke with system and user messages."""
        messages = [
            Message.system("You are helpful"),
            Message.user("Hello"),
        ]
        result = await adapter.ainvoke(messages)
        assert result.content == "Test response"

        # Verify messages were passed correctly
        call_args = mock_litellm_client.generate.call_args
        passed_messages = call_args.kwargs.get("messages") or call_args.args[0]

        assert len(passed_messages) == 2
        assert passed_messages[0].role == "system"
        assert passed_messages[0].content == "You are helpful"
        assert passed_messages[1].role == "user"
        assert passed_messages[1].content == "Hello"

    @pytest.mark.unit
    async def test_ainvoke_with_all_message_types(self, adapter, mock_litellm_client):
        """Test ainvoke with system, user, and assistant messages."""
        messages = [
            Message.system("System prompt"),
            Message.user("User message"),
            Message.assistant("Assistant response"),
            Message.user("Follow up"),
        ]
        result = await adapter.ainvoke(messages)
        assert result.content == "Test response"

        # Verify all messages passed correctly
        call_args = mock_litellm_client.generate.call_args
        passed_messages = call_args.kwargs.get("messages") or call_args.args[0]

        assert len(passed_messages) == 4
        assert passed_messages[0].role == "system"
        assert passed_messages[1].role == "user"
        assert passed_messages[2].role == "assistant"
        assert passed_messages[3].role == "user"

    @pytest.mark.unit
    async def test_generate_chat(self, adapter, mock_litellm_client):
        """Test generate_chat convenience method."""
        result = await adapter.generate_chat(
            system_prompt="You are helpful",
            user_message="Hello",
        )
        assert result.content == "Test response"

        # Verify messages were constructed correctly
        call_args = mock_litellm_client.generate.call_args
        passed_messages = call_args.kwargs.get("messages") or call_args.args[0]

        assert len(passed_messages) == 2
        assert passed_messages[0].role == "system"
        assert passed_messages[0].content == "You are helpful"
        assert passed_messages[1].role == "user"
        assert passed_messages[1].content == "Hello"

    @pytest.mark.unit
    def test_litellm_client_property(self, adapter, mock_litellm_client):
        """Test litellm_client property returns the wrapped client."""
        assert adapter.litellm_client is mock_litellm_client

    @pytest.mark.unit
    def test_temperature_attribute(self, adapter):
        """Test temperature attribute is set correctly."""
        assert adapter.temperature == 0.7

    @pytest.mark.unit
    async def test_ainvoke_handles_dict_response(self, adapter, mock_litellm_client):
        """Test ainvoke handles dict response from LiteLLM."""
        mock_litellm_client.generate = AsyncMock(
            return_value={"content": "Dict response", "usage": {"tokens": 100}}
        )
        result = await adapter.ainvoke("Test")
        assert result.content == "Dict response"

    @pytest.mark.unit
    async def test_ainvoke_handles_string_response(self, adapter, mock_litellm_client):
        """Test ainvoke handles string response from LiteLLM."""
        mock_litellm_client.generate = AsyncMock(return_value="String response")
        result = await adapter.ainvoke("Test")
        assert result.content == "String response"

    @pytest.mark.unit
    async def test_ainvoke_propagates_exceptions(self, adapter, mock_litellm_client):
        """Test ainvoke propagates exceptions from LiteLLM client."""
        mock_litellm_client.generate = AsyncMock(side_effect=Exception("API Error"))
        with pytest.raises(Exception) as exc_info:
            await adapter.ainvoke("Test")
        assert "API Error" in str(exc_info.value)

    @pytest.mark.unit
    async def test_ainvoke_with_empty_content(self, adapter, mock_litellm_client):
        """Test ainvoke handles empty content response."""
        mock_litellm_client.generate = AsyncMock(return_value={"content": ""})
        result = await adapter.ainvoke("Test")
        assert result.content == ""

    @pytest.mark.unit
    def test_message_factory_methods(self):
        """Test Message factory methods work correctly."""
        system = Message.system("System")
        assert system.role == "system"
        assert system.content == "System"

        user = Message.user("User")
        assert user.role == "user"
        assert user.content == "User"

        assistant = Message.assistant("Assistant")
        assert assistant.role == "assistant"
        assert assistant.content == "Assistant"
