"""
Unit tests for ContextFacade.

Tests cover:
- Full context building
- Compression handling
- Token estimation
- Simple context building
- Configuration updates
"""

import pytest

from src.domain.ports.agent.context_manager_port import (
    CompressionStrategy,
    ContextBuildRequest,
)
from src.infrastructure.agent.context.context_facade import (
    ContextFacade,
    ContextFacadeConfig,
)
from src.infrastructure.agent.context.window_manager import ContextWindowConfig


class TestContextFacadeConfig:
    """Tests for ContextFacadeConfig."""

    def test_default_config(self):
        """Test default configuration."""
        config = ContextFacadeConfig()
        assert config.message_builder is None
        assert config.attachment_injector is None
        assert config.context_window is None
        assert config.debug_logging is False

    def test_custom_config(self):
        """Test custom configuration."""
        window_config = ContextWindowConfig(max_context_tokens=64000)
        config = ContextFacadeConfig(
            context_window=window_config,
            debug_logging=True,
        )
        assert config.context_window.max_context_tokens == 64000
        assert config.debug_logging is True


class TestContextFacadeInit:
    """Tests for ContextFacade initialization."""

    def test_default_init(self):
        """Test default initialization creates all components."""
        facade = ContextFacade()
        assert facade.message_builder is not None
        assert facade.attachment_injector is not None
        assert facade.window_manager is not None

    def test_with_config(self):
        """Test initialization with config."""
        config = ContextFacadeConfig(debug_logging=True)
        facade = ContextFacade(config)
        assert facade._debug is True


class TestBuildContext:
    """Tests for build_context async method."""

    @pytest.mark.asyncio
    async def test_simple_context_no_attachments(self):
        """Test building context without attachments."""
        facade = ContextFacade()
        request = ContextBuildRequest(
            system_prompt="You are helpful.",
            conversation_context=[
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello!"},
            ],
            user_message="How are you?",
        )
        result = await facade.build_context(request)
        
        assert result.messages is not None
        assert len(result.messages) >= 3  # system + 2 history + 1 user
        assert result.final_message_count > 0
        assert result.estimated_tokens > 0

    @pytest.mark.asyncio
    async def test_context_with_attachment_metadata(self):
        """Test building context with attachment metadata."""
        facade = ContextFacade()
        request = ContextBuildRequest(
            system_prompt="You are helpful.",
            conversation_context=[],
            user_message="Check this file",
            attachment_metadata=[
                {
                    "filename": "test.py",
                    "sandbox_path": "/workspace/test.py",
                    "mime_type": "text/x-python",
                    "size_bytes": 1024,
                }
            ],
        )
        result = await facade.build_context(request)
        
        # User message should contain attachment context
        last_msg = result.messages[-1]
        content = last_msg.get("content", "")
        if isinstance(content, str):
            assert "test.py" in content
        else:
            # Multimodal content
            text_parts = [p.get("text", "") for p in content if p.get("type") == "text"]
            assert any("test.py" in t for t in text_parts)

    @pytest.mark.asyncio
    async def test_context_with_attachment_content(self):
        """Test building context with multimodal attachment content."""
        facade = ContextFacade()
        request = ContextBuildRequest(
            system_prompt="You are helpful.",
            conversation_context=[],
            user_message="Describe this image",
            attachment_content=[
                {
                    "type": "image_url",
                    "image_url": {"url": "https://example.com/img.png"},
                }
            ],
        )
        result = await facade.build_context(request)
        
        # User message should be multimodal
        last_msg = result.messages[-1]
        assert isinstance(last_msg.get("content"), list)

    @pytest.mark.asyncio
    async def test_context_compression_strategy_none(self):
        """Test compression strategy is NONE for small context."""
        facade = ContextFacade()
        request = ContextBuildRequest(
            system_prompt="Short.",
            conversation_context=[],
            user_message="Hi",
        )
        result = await facade.build_context(request)
        
        # Small context should not be compressed
        assert result.compression_strategy == CompressionStrategy.NONE
        assert result.was_compressed is False

    @pytest.mark.asyncio
    async def test_context_result_has_token_info(self):
        """Test result includes token budget info."""
        facade = ContextFacade()
        request = ContextBuildRequest(
            system_prompt="You are helpful.",
            conversation_context=[],
            user_message="Hello",
        )
        result = await facade.build_context(request)
        
        assert result.token_budget > 0
        assert 0 <= result.budget_utilization_pct <= 100

    @pytest.mark.asyncio
    async def test_context_result_to_event_data(self):
        """Test result can be converted to event data."""
        facade = ContextFacade()
        request = ContextBuildRequest(
            system_prompt="You are helpful.",
            conversation_context=[],
            user_message="Hello",
        )
        result = await facade.build_context(request)
        
        event_data = result.to_event_data()
        assert "was_compressed" in event_data
        assert "compression_strategy" in event_data
        assert "estimated_tokens" in event_data


class TestEstimateTokens:
    """Tests for token estimation methods."""

    def test_estimate_tokens_empty(self):
        """Test token estimation for empty string."""
        facade = ContextFacade()
        assert facade.estimate_tokens("") == 0

    def test_estimate_tokens_english(self):
        """Test token estimation for English text."""
        facade = ContextFacade()
        text = "Hello, how are you doing today?"
        tokens = facade.estimate_tokens(text)
        assert tokens > 0
        assert tokens < len(text)  # Tokens < chars for English

    def test_estimate_tokens_chinese(self):
        """Test token estimation for Chinese text."""
        facade = ContextFacade()
        text = "你好，今天天气怎么样？"
        tokens = facade.estimate_tokens(text)
        assert tokens > 0

    def test_estimate_message_tokens(self):
        """Test token estimation for message."""
        facade = ContextFacade()
        message = {"role": "user", "content": "Hello world!"}
        tokens = facade.estimate_message_tokens(message)
        assert tokens > 0

    def test_estimate_messages_tokens(self):
        """Test token estimation for multiple messages."""
        facade = ContextFacade()
        messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
        ]
        tokens = facade.estimate_messages_tokens(messages)
        assert tokens > 0


class TestBuildSimpleContext:
    """Tests for build_simple_context sync method."""

    def test_simple_context(self):
        """Test building simple context without compression."""
        facade = ContextFacade()
        messages = facade.build_simple_context(
            system_prompt="You are helpful.",
            conversation=[
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello!"},
            ],
            user_message="Bye",
        )
        
        # Should have: system + 2 conversation + 1 user
        assert len(messages) == 4
        assert messages[0]["role"] == "system"
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "Bye"

    def test_simple_context_empty_conversation(self):
        """Test simple context with empty conversation."""
        facade = ContextFacade()
        messages = facade.build_simple_context(
            system_prompt="You are helpful.",
            conversation=[],
            user_message="Hi",
        )
        
        # Should have: system + user
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"


class TestUpdateConfig:
    """Tests for update_config method."""

    def test_update_max_context_tokens(self):
        """Test updating max context tokens."""
        facade = ContextFacade()
        original = facade.window_manager.config.max_context_tokens
        
        facade.update_config(max_context_tokens=64000)
        
        assert facade.window_manager.config.max_context_tokens == 64000
        assert facade.window_manager.config.max_context_tokens != original

    def test_update_max_output_tokens(self):
        """Test updating max output tokens."""
        facade = ContextFacade()
        
        facade.update_config(max_output_tokens=8192)
        
        assert facade.window_manager.config.max_output_tokens == 8192

    def test_update_both(self):
        """Test updating both config values."""
        facade = ContextFacade()
        
        facade.update_config(max_context_tokens=32000, max_output_tokens=2048)
        
        assert facade.window_manager.config.max_context_tokens == 32000
        assert facade.window_manager.config.max_output_tokens == 2048

    def test_update_none_values_ignored(self):
        """Test that None values don't change config."""
        facade = ContextFacade()
        original_context = facade.window_manager.config.max_context_tokens
        original_output = facade.window_manager.config.max_output_tokens
        
        facade.update_config()  # No args
        
        assert facade.window_manager.config.max_context_tokens == original_context
        assert facade.window_manager.config.max_output_tokens == original_output
